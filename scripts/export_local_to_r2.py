from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.shutil import copy as raster_copy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.runtime_backend import load_project_dotenv  # noqa: E402
from api.services.river_display import RIVER_DISPLAY_TIERS, build_river_display_gdf  # noqa: E402


def _json_load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_raster_as_cog(src: Path, dst: Path, *, categorical: bool = True) -> None:
    """Create a categorical COG while preserving the authoritative base grid."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    compression = os.getenv("R2_RASTER_COG_COMPRESSION", "ZSTD").strip().upper() or "ZSTD"
    options = {
        "driver": "COG",
        "compress": compression,
        "blocksize": 512,
        "overview_resampling": "NEAREST" if categorical else "BILINEAR",
        "BIGTIFF": "IF_SAFER",
    }
    try:
        raster_copy(src, dst, **options)
    except Exception:
        if compression == "DEFLATE":
            raise
        dst.unlink(missing_ok=True)
        options["compress"] = "DEFLATE"
        raster_copy(src, dst, **options)
    with rasterio.open(src) as source, rasterio.open(dst) as output:
        same_grid = (
            source.crs == output.crs
            and source.transform == output.transform
            and source.width == output.width
            and source.height == output.height
            and source.count == output.count
            and source.dtypes == output.dtypes
        )
        if not same_grid:
            dst.unlink(missing_ok=True)
            raise RuntimeError(f"Konversi COG mengubah grid/dtype raster: {src}")


def _river_base_name(value: Any) -> str | None:
    """Normalize a river name to its base name for map labeling."""
    text = str(value or "").strip()
    if not text:
        return None
    for prefix in ("Kali ", "K. ", "K ", "Sungai ", "S. ", "S "):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    return text or None


def _river_map_label(value: Any) -> str | None:
    """Compact official river label used on the web map."""
    base = _river_base_name(value)
    return f"K. {base}" if base else None


def _resolve_data_dir(raw: str | None) -> Path:
    candidate = Path(raw).expanduser().resolve() if raw else (ROOT / "data").resolve()
    if (candidate / "processed").is_dir() and (candidate / "reference").is_dir():
        return candidate
    if (candidate / "data" / "processed").is_dir() and (candidate / "data" / "reference").is_dir():
        return candidate / "data"
    raise RuntimeError(
        "Folder sumber lokal tidak valid. Harus menunjuk ke folder 'data' yang berisi "
        "processed/, reference/, dan shared/. Gunakan --data-dir atau LOCAL_DATA_DIR."
    )


def _resolve_dataset(data_dir: Path, requested: str | None) -> str:
    if requested:
        return requested
    active = data_dir / "active_dataset.json"
    if active.exists():
        payload = _json_load(active, {})
        value = str((payload or {}).get("dataset", "")).strip()
        if value:
            return value
    processed = data_dir / "processed"
    dirs = sorted(p.name for p in processed.iterdir() if p.is_dir()) if processed.exists() else []
    if len(dirs) == 1:
        return dirs[0]
    if "1km2" in dirs:
        return "1km2"
    raise RuntimeError(
        "Dataset tidak dapat ditentukan otomatis. Isi HYDRO_DATASET atau gunakan --dataset. "
        f"Dataset lokal yang ditemukan: {dirs or 'tidak ada'}"
    )


def _validate_source(data_dir: Path, dsid: str) -> dict[str, Path]:
    processed = data_dir / "processed" / dsid
    reference = data_dir / "reference"
    shared = data_dir / "shared"
    paths = {
        "engine": processed / "hydro_engine.gpkg",
        "crosswalk": processed / "crosswalk.csv",
        "summary": processed / "official_summary.json",
        "metadata": processed / "metadata.json",
        "subbasin_raster": processed / "subbasins.tif",
        "flowdir": shared / "flowdir.tif",
        "dem": shared / "dem.tif",
        "plen": shared / "plen.tif",
        "cn2": shared / "cn2.tif",
        "landcover": shared / "landcover.tif",
        "streams_analysis": shared / "streams_analysis.zip",
        "landsystem": shared / "landsystem.zip",
        "official": reference / "official_reference.gpkg",
        "rivers_original": reference / "official_rivers_original.gpkg",
        "toponim": reference / "toponim.sqlite",
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise RuntimeError("Data lokal belum lengkap:\n- " + "\n- ".join(missing))

    streams = gpd.read_file(paths["engine"], layer="streams_web")
    subbasins = gpd.read_file(paths["engine"], layer="subbasins_web")
    basins = gpd.read_file(paths["official"], layer="official_basins")
    rivers = gpd.read_file(paths["official"], layer="official_rivers")
    original = gpd.read_file(paths["rivers_original"], layer="jaringan_sungai")
    crosswalk = pd.read_csv(paths["crosswalk"])
    if streams.empty or subbasins.empty or basins.empty or rivers.empty or original.empty:
        raise RuntimeError("GeoPackage lokal kosong/tidak lengkap.")
    if len(streams) != len(subbasins):
        raise RuntimeError(f"Streams/subbasins lokal tidak 1:1: {len(streams)} != {len(subbasins)}")
    if len(crosswalk) != len(subbasins):
        raise RuntimeError(f"Crosswalk/subbasins lokal tidak 1:1: {len(crosswalk)} != {len(subbasins)}")

    with sqlite3.connect(paths["toponim"]) as conn:
        top_count = int(conn.execute("select count(*) from toponim").fetchone()[0])
        rtree_count = int(conn.execute("select count(*) from toponim_rtree").fetchone()[0])
    if top_count <= 0 or top_count != rtree_count:
        raise RuntimeError(f"toponim.sqlite / RTree tidak valid: {top_count} vs {rtree_count}")

    with rasterio.open(paths["flowdir"]) as fdir, rasterio.open(paths["subbasin_raster"]) as sub, \
            rasterio.open(paths["dem"]) as dem, rasterio.open(paths["plen"]) as plen, \
            rasterio.open(paths["cn2"]) as cn2, rasterio.open(paths["landcover"]) as landcover:
        same_grid = (
            fdir.crs == sub.crs
            and fdir.transform == sub.transform
            and fdir.width == sub.width
            and fdir.height == sub.height
        )
        if not same_grid:
            raise RuntimeError("flowdir.tif dan subbasins.tif lokal tidak memiliki grid identik.")
        analysis_grid = (dem.crs == fdir.crs and dem.transform == fdir.transform and dem.width == fdir.width and dem.height == fdir.height)
        if not analysis_grid:
            raise RuntimeError("dem.tif harus memiliki grid identik dengan flowdir.tif.")
        for label, ds in (("plen.tif", plen), ("cn2.tif", cn2), ("landcover.tif", landcover)):
            if ds.crs != fdir.crs:
                raise RuntimeError(f"{label} CRS tidak sama dengan flowdir.tif.")

    print(
        f"Sumber lokal valid: streams={len(streams):,}, subbasins={len(subbasins):,}, "
        f"basins={len(basins):,}, rivers={len(rivers):,}, toponim={top_count:,}"
    )
    return paths


def main() -> int:
    load_project_dotenv(ROOT)
    parser = argparse.ArgumentParser(
        description="Buat Cloudflare R2 bundle langsung dari dataset runtime lokal, tanpa Supabase."
    )
    parser.add_argument("--data-dir", default=os.getenv("LOCAL_DATA_DIR", "").strip() or None)
    parser.add_argument("--dataset", default=os.getenv("HYDRO_DATASET", "").strip() or None)
    parser.add_argument("--output", default=str(ROOT / "r2_bundle"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    data_dir = _resolve_data_dir(args.data_dir)
    dsid = _resolve_dataset(data_dir, args.dataset)
    paths = _validate_source(data_dir, dsid)

    out = Path(args.output).resolve()
    if out.exists() and args.overwrite:
        shutil.rmtree(out)
    runtime = out / "runtime"
    map_assets = out / "map-assets"
    processed_out = runtime / "datasets" / dsid
    reference_out = runtime / "reference"
    shared_out = runtime / "shared"
    for p in (processed_out, reference_out, shared_out, map_assets):
        p.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Menyalin runtime lokal dataset '{dsid}'...")
    copy_map = {
        paths["engine"]: processed_out / "hydro_engine.gpkg",
        paths["crosswalk"]: processed_out / "crosswalk.csv",
        paths["summary"]: processed_out / "official_summary.json",
        paths["metadata"]: processed_out / "metadata.json",
        paths["official"]: reference_out / "official_reference.gpkg",
        paths["rivers_original"]: reference_out / "official_rivers_original.gpkg",
        paths["toponim"]: reference_out / "toponim.sqlite",
        paths["streams_analysis"]: shared_out / "streams_analysis.zip",
        paths["landsystem"]: shared_out / "landsystem.zip",
    }
    for src, dst in copy_map.items():
        _copy(src, dst)
        print(f"  {src.name:32s} -> {dst.relative_to(runtime)}")
    for src, dst, categorical in (
        (paths["subbasin_raster"], processed_out / "subbasins.tif", True),
        (paths["flowdir"], shared_out / "flowdir.tif", True),
        (paths["dem"], shared_out / "dem.tif", False),
        (paths["plen"], shared_out / "plen.tif", True),
        (paths["cn2"], shared_out / "cn2.tif", True),
        (paths["landcover"], shared_out / "landcover.tif", True),
    ):
        _copy_raster_as_cog(src, dst, categorical=categorical)
        print(f"  {src.name:32s} -> {dst.relative_to(runtime)} (COG)")

    print("[2/4] Membuat map-assets multiscale dari reference lokal...")
    basins = gpd.read_file(paths["official"], layer="official_basins").to_crs("EPSG:4326")
    rivers_source = gpd.read_file(paths["official"], layer="official_rivers")
    if "river_name" in rivers_source.columns:
        rivers_source = rivers_source.copy()
        rivers_source["river_label"] = rivers_source["river_name"].map(_river_map_label)
    (map_assets / "official_basins.geojson").write_text(basins.to_json(drop_id=True), encoding="utf-8")

    for tier in RIVER_DISPLAY_TIERS:
        display = build_river_display_gdf(rivers_source, tier)
        target = map_assets / tier.filename
        target.write_text(display.to_json(drop_id=True), encoding="utf-8")
        max_zoom = f"<{tier.max_zoom:g}" if tier.max_zoom is not None else "+"
        orders = "semua" if tier.allowed_orders is None else "+".join(str(v) for v in tier.allowed_orders)
        print(
            f"  {tier.filename:34s} z{tier.min_zoom:g}-{max_zoom:>5s} "
            f"orde={orders:7s} simplify={tier.tolerance_m:g} m fitur={len(display):,}"
        )

    print("[3/4] Membuat manifest + checksum...")
    object_paths = {
        "engine": f"datasets/{dsid}/hydro_engine.gpkg",
        "crosswalk": f"datasets/{dsid}/crosswalk.csv",
        "summary": f"datasets/{dsid}/official_summary.json",
        "metadata": f"datasets/{dsid}/metadata.json",
        "subbasin_raster": f"datasets/{dsid}/subbasins.tif",
        "flowdir": "shared/flowdir.tif",
        "dem": "shared/dem.tif",
        "plen": "shared/plen.tif",
        "cn2": "shared/cn2.tif",
        "landcover": "shared/landcover.tif",
        "streams_analysis": "shared/streams_analysis.zip",
        "landsystem": "shared/landsystem.zip",
        "official": "reference/official_reference.gpkg",
        "rivers_original": "reference/official_rivers_original.gpkg",
        "toponim": "reference/toponim.sqlite",
    }
    checksums: dict[str, dict[str, Any]] = {}
    for name, rel in object_paths.items():
        fp = runtime / rel
        checksums[rel] = {"sha256": _sha256(fp), "size": fp.stat().st_size, "role": name}

    metadata = _json_load(processed_out / "metadata.json", {}) or {}
    if isinstance(metadata, dict):
        metadata["runtime_source"] = "local-to-cloudflare-r2"
        _json_dump(processed_out / "metadata.json", metadata)
        rel = object_paths["metadata"]
        checksums[rel] = {
            "sha256": _sha256(runtime / rel),
            "size": (runtime / rel).stat().st_size,
            "role": "metadata",
        }

    asset_digest = hashlib.sha256()
    for asset in sorted(p for p in map_assets.iterdir() if p.is_file()):
        asset_digest.update(asset.name.encode("utf-8"))
        asset_digest.update(_sha256(asset).encode("ascii"))
    map_assets_version = asset_digest.hexdigest()[:16]

    manifest = {
        "schema_version": 4,
        "source": "local-runtime-data",
        "active_dataset": dsid,
        "map_assets_version": map_assets_version,
        "runtime_profile": "r2-performance-v2",
        "raster_layout": "global_cog",
        "datasets": {
            dsid: {
                "engine": object_paths["engine"],
                "crosswalk": object_paths["crosswalk"],
                "summary": object_paths["summary"],
                "metadata": object_paths["metadata"],
                "subbasin_raster": object_paths["subbasin_raster"],
                "flowdir": object_paths["flowdir"],
                "dem": object_paths["dem"],
                "plen": object_paths["plen"],
                "cn2": object_paths["cn2"],
                "landcover": object_paths["landcover"],
                "streams_analysis": object_paths["streams_analysis"],
                "landsystem": object_paths["landsystem"],
            }
        },
        "reference": {
            "official": object_paths["official"],
            "rivers_original": object_paths["rivers_original"],
            "toponim": object_paths["toponim"],
        },
        "map_assets": {
            "official_basins": "official_basins.geojson",
            "official_rivers": "official_rivers.geojson",
            "official_rivers_z6_8": "official_rivers_z6_8.geojson",
            "official_rivers_z8_10": "official_rivers_z8_10.geojson",
            "official_rivers_z10_11": "official_rivers_z10_11.geojson",
            "official_rivers_z11_12": "official_rivers_z11_12.geojson",
            "official_rivers_z12_14": "official_rivers_z12_14.geojson",
        },
        "objects": checksums,
    }
    _json_dump(runtime / "manifest.json", manifest)

    print("[4/4] Bundle lokal -> R2 selesai")
    print(f"Sumber data : {data_dir}")
    print(f"Dataset     : {dsid}")
    print(f"Runtime     : {runtime}")
    print(f"Map assets  : {map_assets}")
    print(f"Asset versi : {map_assets_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
