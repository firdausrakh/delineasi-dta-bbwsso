from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.runtime_backend import _r2_client, load_project_dotenv  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _raster_content_signature(path: Path) -> tuple[tuple, str]:
    """Compare categorical raster values independently from TIFF/COG encoding."""
    digest = hashlib.sha256()
    with rasterio.open(path) as ds:
        metadata = (
            str(ds.crs), tuple(ds.transform), ds.width, ds.height, ds.count,
            tuple(ds.dtypes), tuple(ds.nodatavals),
        )
        for band in range(1, ds.count + 1):
            for row in range(0, ds.height, 512):
                height = min(512, ds.height - row)
                digest.update(ds.read(band, window=Window(0, row, ds.width, height)).tobytes(order="C"))
    return metadata, digest.hexdigest()


def _local_data_dir() -> Path | None:
    raw = os.getenv("LOCAL_DATA_DIR", "").strip()
    candidates = [Path(raw).expanduser().resolve()] if raw else [ROOT / "data"]
    for candidate in candidates:
        if (candidate / "processed").is_dir():
            return candidate
        if (candidate / "data" / "processed").is_dir():
            return candidate / "data"
    return None


def main() -> int:
    load_project_dotenv(ROOT)
    bucket = os.getenv("R2_RUNTIME_BUCKET", "").strip()
    map_bucket = os.getenv("R2_MAP_ASSETS_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("R2_RUNTIME_BUCKET belum diisi.")
    client = _r2_client()
    manifest_key = os.getenv("R2_MANIFEST_KEY", "manifest.json").strip() or "manifest.json"
    manifest = json.loads(client.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8-sig"))
    schema_version = int(manifest.get("schema_version") or 0)
    if schema_version < 2:
        raise RuntimeError(f"FAIL schema manifest R2 terlalu lama/tidak valid: {schema_version}")
    dsid = os.getenv("HYDRO_DATASET", "").strip() or manifest.get("active_dataset")
    spec = manifest["datasets"][dsid]
    ref = manifest["reference"]
    keys = {
        "engine": spec["engine"],
        "crosswalk": spec["crosswalk"],
        "summary": spec["summary"],
        "metadata": spec["metadata"],
        "subbasin_raster": spec["subbasin_raster"],
        "flowdir": spec["flowdir"],
        "official": ref["official"],
        "rivers_original": ref["rivers_original"],
        "toponim": ref["toponim"],
    }
    object_meta = manifest.get("objects") or {}

    print(f"Verifikasi R2 bucket={bucket} dataset={dsid}")
    print(
        f"  INFO manifest schema={schema_version} profile={manifest.get('runtime_profile') or 'legacy'} "
        f"map_assets_version={manifest.get('map_assets_version') or 'legacy'}"
    )
    for name, key in keys.items():
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head["ContentLength"])
        expected = (object_meta.get(key) or {}).get("size")
        if expected is not None and int(expected) != size:
            raise RuntimeError(f"FAIL ukuran R2 {key}: {size} != manifest {expected}")
        print(f"  PASS object {name:16s} {size/1024/1024:9.2f} MB  {key}")

    with tempfile.TemporaryDirectory(prefix="dta-r2-verify-") as td_raw:
        td = Path(td_raw)
        local: dict[str, Path] = {}
        for name, key in keys.items():
            suffix = Path(key).suffix or ".bin"
            path = td / f"{name}{suffix}"
            client.download_file(bucket, key, str(path))
            local[name] = path
            expected_hash = (object_meta.get(key) or {}).get("sha256")
            if expected_hash and _sha256(path) != expected_hash:
                raise RuntimeError(f"FAIL SHA256 R2 object: {key}")

        streams = gpd.read_file(local["engine"], layer="streams_web")
        subbasins = gpd.read_file(local["engine"], layer="subbasins_web")
        basins = gpd.read_file(local["official"], layer="official_basins")
        rivers = gpd.read_file(local["official"], layer="official_rivers")
        original = gpd.read_file(local["rivers_original"], layer="jaringan_sungai")
        crosswalk = pd.read_csv(local["crosswalk"])
        with sqlite3.connect(local["toponim"]) as conn:
            top_count = int(conn.execute("select count(*) from toponim").fetchone()[0])
            rtree_count = int(conn.execute("select count(*) from toponim_rtree").fetchone()[0])
        with rasterio.open(local["flowdir"]) as fdir, rasterio.open(local["subbasin_raster"]) as sub:
            same_grid = (
                fdir.crs == sub.crs
                and fdir.transform == sub.transform
                and fdir.width == sub.width
                and fdir.height == sub.height
            )
            if not same_grid:
                raise RuntimeError("FAIL: flowdir.tif dan subbasins.tif tidak memiliki grid identik.")
            if schema_version >= 3:
                for label, ds in (("flowdir", fdir), ("subbasin_raster", sub)):
                    layout = str(ds.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") or "").upper()
                    if layout != "COG":
                        raise RuntimeError(f"FAIL raster {label} belum COG (LAYOUT={layout or 'kosong'}).")
            raster_shape = (fdir.height, fdir.width)

        checks = {
            "streams": len(streams),
            "subbasins": len(subbasins),
            "crosswalk": len(crosswalk),
            "official_basins": len(basins),
            "official_rivers": len(rivers),
            "official_rivers_original": len(original),
            "toponim": top_count,
        }
        if len(streams) != len(subbasins) or len(crosswalk) != len(subbasins):
            raise RuntimeError(f"FAIL runtime counts: {checks}")
        if top_count != rtree_count:
            raise RuntimeError(f"FAIL SQLite RTree: toponim={top_count}, rtree={rtree_count}")
        print("  PASS runtime file structure + SHA256")
        print(f"  PASS counts {checks}")
        print(f"  PASS raster grid {raster_shape[1]}x{raster_shape[0]}")

        data_dir = _local_data_dir()
        if data_dir is not None:
            processed = data_dir / "processed" / dsid
            source_paths = {
                "engine": processed / "hydro_engine.gpkg",
                "crosswalk": processed / "crosswalk.csv",
                "official": data_dir / "reference" / "official_reference.gpkg",
                "rivers_original": data_dir / "reference" / "official_rivers_original.gpkg",
                "toponim": data_dir / "reference" / "toponim.sqlite",
            }
            present = {name: path for name, path in source_paths.items() if path.exists()}
            mismatches = []
            for name, src in present.items():
                # metadata.json intentionally gets a runtime_source field during bundling,
                # so only immutable GIS/runtime source files are byte-compared here.
                if _sha256(src) != _sha256(local[name]):
                    mismatches.append(name)
            if mismatches:
                raise RuntimeError("FAIL data lokal vs R2 berbeda: " + ", ".join(mismatches))
            raster_sources = {
                "subbasin_raster": processed / "subbasins.tif",
                "flowdir": data_dir / "shared" / "flowdir.tif",
            }
            for name, src in raster_sources.items():
                if src.exists() and _raster_content_signature(src) != _raster_content_signature(local[name]):
                    raise RuntimeError(f"FAIL nilai/grid raster lokal vs R2 berbeda: {name}")
            print(f"  PASS data lokal vs R2 byte-identical ({len(present)} file utama)")
            print("  PASS raster lokal vs COG R2 grid/value-identical")
        else:
            print("  INFO LOCAL_DATA_DIR/data lokal tidak ditemukan; perbandingan sumber lokal dilewati.")

    if map_bucket:
        print(f"Verifikasi map-assets R2 bucket={map_bucket}")
        river_asset_keys = (
            "official_rivers_z6_8.geojson",
            "official_rivers_z8_10.geojson",
            "official_rivers_z10_11.geojson",
            "official_rivers_z11_12.geojson",
            "official_rivers_z12_14.geojson",
            "official_rivers.geojson",
        )
        for key in ("official_basins.geojson", *river_asset_keys):
            head = client.head_object(Bucket=map_bucket, Key=key)
            cache_control = str(head.get("CacheControl") or "")
            if schema_version >= 3 and "immutable" not in cache_control.lower():
                raise RuntimeError(f"FAIL Cache-Control map asset belum immutable: {key}: {cache_control!r}")
            print(f"  PASS map asset {key:34s} {int(head['ContentLength'])/1024/1024:9.2f} MB")

        river_payloads = {}
        for key in river_asset_keys:
            river_payloads[key] = json.loads(
                client.get_object(Bucket=map_bucket, Key=key)["Body"].read().decode("utf-8-sig")
            )
            if not (river_payloads[key].get("features") or []):
                raise RuntimeError(f"FAIL {key} di R2 kosong.")

        expected_orders = {
            "official_rivers_z6_8.geojson": {1, 2},
            "official_rivers_z8_10.geojson": {1, 2},
            "official_rivers_z10_11.geojson": {1, 2, 3},
            "official_rivers_z11_12.geojson": {1, 2, 3},
        }
        for key, allowed in expected_orders.items():
            seen = set()
            for feature in river_payloads[key].get("features") or []:
                props = feature.get("properties") or {}
                raw = props.get("river_order_int", props.get("river_order"))
                try:
                    seen.add(int(raw))
                except (TypeError, ValueError):
                    seen.add(None)
            if not seen.issubset(allowed):
                raise RuntimeError(f"FAIL klasifikasi orde {key}: ditemukan {sorted(seen, key=str)}, expected subset {sorted(allowed)}")

        full_count = len(river_payloads["official_rivers.geojson"].get("features") or [])
        high_count = len(river_payloads["official_rivers_z12_14.geojson"].get("features") or [])
        if high_count != full_count:
            raise RuntimeError(f"FAIL tier z12-14 harus memuat semua sungai: {high_count} != {full_count}")

        river_features = river_payloads["official_rivers.geojson"].get("features") or []
        bad_labels = []
        for feature in river_features:
            props = feature.get("properties") or {}
            name = str(props.get("river_name") or "").strip()
            label = str(props.get("river_label") or "").strip()
            if name and not label.startswith("K. "):
                bad_labels.append((name, label))
                if len(bad_labels) >= 5:
                    break
        if bad_labels:
            raise RuntimeError(f"FAIL river_label map-assets belum berformat 'K. <nama>': {bad_labels}")
        print(f"  PASS river labels: format K. <nama> ({len(river_features)} fitur full-detail)")
        print(
            "  PASS river multiscale counts "
            + ", ".join(f"{key}={len(payload.get('features') or []):,}" for key, payload in river_payloads.items())
        )

    print("VERIFY R2: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
