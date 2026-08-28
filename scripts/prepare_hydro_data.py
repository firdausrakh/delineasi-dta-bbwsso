from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_ROOT = DATA / "source"
PROCESSED_ROOT = DATA / "processed"
SHARED_DIR = DATA / "shared"
REFERENCE_DIR = DATA / "reference"
ACTIVE_PATH = DATA / "active_dataset.json"
FLOWDIR_PATH = SHARED_DIR / "flowdir.tif"
OFFICIAL_PATH = REFERENCE_DIR / "official_reference.gpkg"
TARGET_CRS = "EPSG:32749"
SUPPORTED_COVERAGE_MIN = 0.90

STREAM_REQUIRED = {
    "LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2", "strmOrder", "Length",
    "Magnitude", "DSContArea", "Slope", "USContArea", "DOUTEND", "DOUTSTART", "DOUTMID",
}
SUB_REQUIRED = {"PolygonId", "Area", "Subbasin"}


def say(msg: str = ""):
    print(msg, flush=True)


def dataset_dirs() -> list[Path]:
    if not SOURCE_ROOT.exists():
        return []
    return sorted([p for p in SOURCE_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")])


def discover(folder: Path, names: list[str]) -> Path | None:
    for name in names:
        p = folder / name
        if p.exists():
            return p
    return None


def extract_single_shp(zip_path: Path, temp_dir: Path) -> Path:
    with ZipFile(zip_path) as zf:
        zf.extractall(temp_dir)
    shps = list(temp_dir.rglob("*.shp"))
    if len(shps) != 1:
        raise RuntimeError(f"{zip_path.name}: diharapkan tepat 1 SHP, ditemukan {len(shps)}")
    return shps[0]


def polygonal(geom):
    if geom is None or geom.is_empty:
        return None
    g = geom if geom.is_valid else make_valid(geom)
    parts: list[Polygon] = []
    def collect(x):
        if x is None or x.is_empty:
            return
        if isinstance(x, Polygon):
            parts.append(x)
        elif isinstance(x, MultiPolygon):
            parts.extend([p for p in x.geoms if not p.is_empty])
        elif isinstance(x, GeometryCollection):
            for p in x.geoms:
                collect(p)
    collect(g)
    if not parts:
        return None
    return MultiPolygon(parts)


def first_line_point(geom) -> Point:
    if geom is None or geom.is_empty:
        return Point()
    try:
        coords = list(geom.coords)
        if coords:
            return Point(coords[0])
    except Exception:
        pass
    c = geom.centroid
    return Point(c.x, c.y)


def line_endpoint_candidates(geom) -> list[Point]:
    """Return digitization-independent endpoint candidates for line/multiline geometry."""
    if geom is None or geom.is_empty:
        return []
    parts = [geom] if isinstance(geom, LineString) else []
    if not parts:
        try:
            parts = [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
        except Exception:
            parts = []
    points: list[Point] = []
    for part in parts:
        coords = list(part.coords)
        if coords:
            points.extend([Point(coords[0]), Point(coords[-1])])
    # Avoid duplicated endpoints in multipart linework.
    unique: list[Point] = []
    for pt in points:
        if not any(pt.distance(other) <= 1e-7 for other in unique):
            unique.append(pt)
    return unique


def topology_downstream_point(
    linkno: int,
    geom,
    downstream_id: int | None,
    upstream_ids: list[int],
    stream_idx: gpd.GeoDataFrame,
) -> tuple[Point, str]:
    """
    Determine the downstream reach endpoint from topology, not digitization order.

    If a downstream reach exists, the endpoint nearest that geometry is downstream. At a
    network outlet, the endpoint farthest from connected upstream reaches is selected. This
    remains valid when source stream vectors are digitized downstream->upstream or vice versa.
    """
    candidates = line_endpoint_candidates(geom)
    if not candidates:
        return geom.representative_point(), "representative_point_fallback"

    if downstream_id is not None and int(downstream_id) in stream_idx.index:
        ds_geom = stream_idx.loc[int(downstream_id)].geometry
        point = min(candidates, key=lambda pt: pt.distance(ds_geom))
        return point, "nearest_downstream_reach"

    upstream_geoms = [
        stream_idx.loc[int(uid)].geometry
        for uid in upstream_ids
        if int(uid) in stream_idx.index
    ]
    if upstream_geoms:
        # The upstream-side endpoint touches one or more incoming reaches; the opposite end is
        # the network outlet. Maximize distance from the nearest upstream geometry.
        point = max(candidates, key=lambda pt: min(pt.distance(g) for g in upstream_geoms))
        return point, "farthest_from_upstream_reaches"

    # Isolated single-reach network: orientation cannot be inferred from connectivity alone.
    # Retain the source end only as an explicit fallback and record the method for QA.
    return candidates[-1], "source_end_fallback"


def resolve_ds(link: int, raw_ds: dict[int, int], connector_ids: set[int], all_ids: set[int]) -> int | None:
    seen = {link}
    cur = int(raw_ds.get(link, -1))
    while cur in connector_ids:
        if cur in seen:
            raise RuntimeError(f"Loop connector terdeteksi pada LINKNO {cur}")
        seen.add(cur)
        cur = int(raw_ds.get(cur, -1))
    if cur == -1:
        return None
    if cur not in all_ids:
        raise RuntimeError(f"LINKNO {link} menunjuk DSLINKNO {cur} yang tidak tersedia")
    return cur


def check_cycles(ds_map: dict[int, int | None]) -> list[list[int]]:
    cycles = []
    state: dict[int, int] = {}
    for start in ds_map:
        if state.get(start) == 2:
            continue
        path: list[int] = []
        pos: dict[int, int] = {}
        cur: int | None = start
        while cur is not None and state.get(cur, 0) != 2:
            if cur in pos:
                cycles.append(path[pos[cur]:] + [cur])
                break
            if state.get(cur) == 1:
                break
            pos[cur] = len(path)
            path.append(cur)
            state[cur] = 1
            cur = ds_map.get(cur)
        for node in path:
            state[node] = 2
    return cycles


def build_topology(stream_raw: gpd.GeoDataFrame, sub_raw: gpd.GeoDataFrame):
    stream_raw = stream_raw.copy()
    sub_raw = sub_raw.copy()
    stream_raw["LINKNO"] = stream_raw["LINKNO"].astype(int)
    stream_raw["DSLINKNO"] = stream_raw["DSLINKNO"].astype(int)
    sub_raw["PolygonId"] = sub_raw["PolygonId"].astype(int)

    if stream_raw["LINKNO"].duplicated().any():
        vals = stream_raw.loc[stream_raw["LINKNO"].duplicated(), "LINKNO"].tolist()[:10]
        raise RuntimeError(f"LINKNO duplikat: {vals}")
    if sub_raw["PolygonId"].duplicated().any():
        vals = sub_raw.loc[sub_raw["PolygonId"].duplicated(), "PolygonId"].tolist()[:10]
        raise RuntimeError(f"PolygonId duplikat: {vals}")

    all_stream_ids = set(stream_raw["LINKNO"].tolist())
    sub_ids = set(sub_raw["PolygonId"].tolist())
    raw_ds = dict(zip(stream_raw["LINKNO"], stream_raw["DSLINKNO"]))
    length_by = dict(zip(stream_raw["LINKNO"], pd.to_numeric(stream_raw["Length"], errors="coerce").fillna(0.0)))
    connector_ids = {i for i in all_stream_ids if i not in sub_ids or float(length_by.get(i, 0.0)) <= 1e-9}
    real_ids = sorted(sub_ids)

    missing_stream = sorted(sub_ids - all_stream_ids)
    if missing_stream:
        raise RuntimeError(f"Subbasin tanpa stream LINKNO: {missing_stream[:20]}")

    ds_map: dict[int, int | None] = {}
    broken = []
    for link in real_ids:
        try:
            ds = resolve_ds(link, raw_ds, connector_ids, all_stream_ids)
        except RuntimeError:
            raise
        if ds is not None and ds in connector_ids:
            broken.append((link, ds))
        if ds is not None and ds not in sub_ids:
            broken.append((link, ds))
        ds_map[link] = ds
    if broken:
        raise RuntimeError(f"Downstream runtime tidak valid: {broken[:20]}")
    self_refs = [i for i, d in ds_map.items() if d == i]
    if self_refs:
        raise RuntimeError(f"Self-reference topology: {self_refs[:20]}")
    cycles = check_cycles(ds_map)
    if cycles:
        raise RuntimeError(f"Circular topology terdeteksi: {cycles[:3]}")

    upstream: dict[int, list[int]] = defaultdict(list)
    for link, ds in ds_map.items():
        if ds is not None:
            upstream[ds].append(link)

    basin_memo: dict[int, int] = {}
    level_memo: dict[int, int] = {}
    def basin_level(node: int) -> tuple[int, int]:
        if node in basin_memo:
            return basin_memo[node], level_memo[node]
        ds = ds_map[node]
        if ds is None:
            basin_memo[node] = node
            level_memo[node] = 0
        else:
            b, lvl = basin_level(ds)
            basin_memo[node] = b
            level_memo[node] = lvl + 1
        return basin_memo[node], level_memo[node]
    for n in real_ids:
        basin_level(n)

    return ds_map, upstream, connector_ids, basin_memo, level_memo


def validate_rasters(subbasin_raster: Path, vector_ids: set[int]) -> dict:
    if not FLOWDIR_PATH.exists():
        raise RuntimeError(f"Flow direction shared tidak ditemukan: {FLOWDIR_PATH}")
    with rasterio.open(FLOWDIR_PATH) as fds, rasterio.open(subbasin_raster) as wds:
        aligned = (
            fds.crs == wds.crs and fds.transform == wds.transform and
            fds.width == wds.width and fds.height == wds.height
        )
        if not aligned:
            raise RuntimeError("Grid flowdir.tif dan subbasins.tif tidak identik (CRS/transform/shape).")
        if str(fds.crs).upper() != TARGET_CRS:
            say(f"[warning] Flow direction CRS={fds.crs}; target runtime biasanya {TARGET_CRS}")
        # Read unique values block-wise to avoid a second full in-memory array for large experiments.
        fvals: set[int] = set()
        for _, win in fds.block_windows(1):
            arr = fds.read(1, window=win, masked=True)
            if arr.count():
                fvals.update(int(v) for v in np.unique(arr.compressed()))
        invalid_d8 = sorted(v for v in fvals if v not in {1,2,3,4,5,6,7,8})
        if invalid_d8:
            raise RuntimeError(f"Kode D8 di luar 1..8: {invalid_d8[:20]}")

        rids: set[int] = set()
        for _, win in wds.block_windows(1):
            arr = wds.read(1, window=win, masked=True)
            if arr.count():
                vals = np.unique(arr.compressed())
                rids.update(int(v) for v in vals if int(v) > 0)
        missing_raster = sorted(vector_ids - rids)
        extra_raster = sorted(rids - vector_ids)
        if missing_raster or extra_raster:
            raise RuntimeError(
                "ID raster/vector tidak 1:1. "
                f"Missing raster={missing_raster[:20]}, extra raster={extra_raster[:20]}"
            )
        return {
            "crs": str(fds.crs),
            "width": int(fds.width),
            "height": int(fds.height),
            "pixel_size_x": abs(float(fds.transform.a)),
            "pixel_size_y": abs(float(fds.transform.e)),
            "d8_codes": sorted(fvals),
            "raster_id_count": len(rids),
            "aligned": True,
        }


def build_crosswalk(subs: gpd.GeoDataFrame, official: gpd.GeoDataFrame):
    official = official.to_crs(subs.crs)
    sindex = official.sindex
    rows = []
    assigned_intersection_area: dict[str, float] = defaultdict(float)
    for idx, row in subs.iterrows():
        geom = row.geometry
        candidates = list(sindex.query(geom, predicate="intersects"))
        best = None
        best_area = 0.0
        for j in candidates:
            basin = official.iloc[int(j)]
            inter_area = geom.intersection(basin.geometry).area
            if inter_area > best_area:
                best_area = float(inter_area)
                best = basin
        if best is None or geom.area <= 0:
            rows.append({
                "polygon_id": int(row["polygon_id"]),
                "official_basin_code": "",
                "official_basin_name": "",
                "overlap_ratio": 0.0,
            })
        else:
            code = str(best["basin_code"])
            rows.append({
                "polygon_id": int(row["polygon_id"]),
                "official_basin_code": code,
                "official_basin_name": str(best["basin_name"]),
                "overlap_ratio": float(best_area / geom.area),
            })
            assigned_intersection_area[code] += best_area
    cross = pd.DataFrame(rows)
    supported = []
    unsupported = []
    for _, basin in official.iterrows():
        code = str(basin["basin_code"])
        area = float(basin.geometry.area)
        coverage = assigned_intersection_area.get(code, 0.0) / area if area > 0 else 0.0
        count = int((cross["official_basin_code"] == code).sum())
        item = {
            "basin_code": code,
            "basin_name": str(basin["basin_name"]),
            "coverage_ratio": float(coverage),
            "subbasin_count": count,
        }
        if coverage >= SUPPORTED_COVERAGE_MIN:
            supported.append(item)
        else:
            unsupported.append({"basin_code": code, "basin_name": str(basin["basin_name"]), "coverage_ratio": float(coverage), "subbasin_count": count})
    summary = {
        "official_basins_count": int(len(official)),
        "supported_basin_count": len(supported),
        "supported_basins": supported,
        "unsupported_basins": unsupported,
    }
    return cross, summary


def prepare(dataset_id: str, activate: bool = False) -> Path:
    src = SOURCE_ROOT / dataset_id
    if not src.exists():
        raise RuntimeError(f"Folder dataset tidak ditemukan: {src}")
    streams_zip = discover(src, ["streams.zip", "fabdemstream.zip"])
    subbasins_zip = discover(src, ["subbasins.zip", "fabdemsubbasins.zip"])
    subbasins_tif = discover(src, ["subbasins.tif", "fabdemwStream.tif", "fabdem_subbasin_id.tif"])
    missing = [name for name, p in [("streams.zip", streams_zip), ("subbasins.zip", subbasins_zip), ("subbasins.tif", subbasins_tif)] if p is None]
    if missing:
        raise RuntimeError(f"Dataset {dataset_id} belum lengkap. Missing: {', '.join(missing)}")
    if not OFFICIAL_PATH.exists():
        raise RuntimeError(f"Reference Batas DAS tidak ditemukan: {OFFICIAL_PATH}")

    meta_src = {}
    meta_path = src / "dataset.json"
    if meta_path.exists():
        meta_src = json.loads(meta_path.read_text(encoding="utf-8"))

    say(f"\n=== PREPARE DATASET: {dataset_id} ===")
    say(f"Stream     : {streams_zip.name}")
    say(f"Subbasin   : {subbasins_zip.name}")
    say(f"Raster ID  : {subbasins_tif.name}")
    say(f"Flowdir    : {FLOWDIR_PATH.name} (shared)")

    invalid_before = 0
    with tempfile.TemporaryDirectory(prefix="dta_prepare_") as td:
        td = Path(td)
        stream_shp = extract_single_shp(streams_zip, td / "streams")
        sub_shp = extract_single_shp(subbasins_zip, td / "subbasins")
        stream_raw = gpd.read_file(stream_shp)
        sub_raw = gpd.read_file(sub_shp)
        if stream_raw.crs is None or sub_raw.crs is None:
            raise RuntimeError("CRS SHP streams/subbasins wajib tersedia.")
        if str(stream_raw.crs).upper() != TARGET_CRS:
            stream_raw = stream_raw.to_crs(TARGET_CRS)
        if str(sub_raw.crs).upper() != TARGET_CRS:
            sub_raw = sub_raw.to_crs(TARGET_CRS)
        missing_stream_fields = sorted(STREAM_REQUIRED - set(stream_raw.columns))
        missing_sub_fields = sorted(SUB_REQUIRED - set(sub_raw.columns))
        if missing_stream_fields or missing_sub_fields:
            raise RuntimeError(f"Field tidak lengkap. stream={missing_stream_fields}; subbasin={missing_sub_fields}")

        invalid_before = int((~sub_raw.geometry.is_valid).sum())
        cleaned_geoms = [polygonal(g) for g in sub_raw.geometry]
        if any(g is None or g.is_empty for g in cleaned_geoms):
            raise RuntimeError("Ada geometry subbasin yang tidak dapat diperbaiki.")
        sub_raw = sub_raw.copy()
        sub_raw.geometry = cleaned_geoms
        invalid_after = int((~sub_raw.geometry.is_valid).sum())
        if invalid_after:
            raise RuntimeError(f"Masih ada {invalid_after} geometry subbasin invalid setelah make_valid.")

        ds_map, upstream, connector_ids, basin_map, level_map = build_topology(stream_raw, sub_raw)
        real_ids = set(int(v) for v in sub_raw["PolygonId"])
        raster_qa = validate_rasters(subbasins_tif, real_ids)

        stream_idx = stream_raw.set_index(stream_raw["LINKNO"].astype(int), drop=False)
        to_web = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)

        # Local geometry areas and cumulative topology stats.
        local_area = {int(pid): float(g.area / 1e6) for pid, g in zip(sub_raw["PolygonId"], sub_raw.geometry)}
        area_up_memo: dict[int, float] = {}
        count_up_memo: dict[int, int] = {}
        def accum(node: int) -> tuple[float, int]:
            if node in area_up_memo:
                return area_up_memo[node], count_up_memo[node]
            area = local_area[node]
            count = 1
            for u in upstream.get(node, []):
                a, c = accum(u)
                area += a
                count += c
            area_up_memo[node] = area
            count_up_memo[node] = count
            return area, count
        for node in real_ids:
            accum(node)

        stream_rows = []
        sub_rows = []
        for _, sr in sub_raw.iterrows():
            pid = int(sr["PolygonId"])
            st = stream_idx.loc[pid]
            ds = ds_map[pid]
            op, outlet_method = topology_downstream_point(
                pid, st.geometry, ds, upstream.get(pid, []), stream_idx
            )
            lon, lat = to_web.transform(op.x, op.y)
            common = {
                "basin_id": int(basin_map[pid]),
                "level_to_outlet": int(level_map[pid]),
                "upstream_count_immediate": int(len(upstream.get(pid, []))),
                "outlet_x": float(op.x),
                "outlet_y": float(op.y),
                "outlet_lon": float(lon),
                "outlet_lat": float(lat),
                "outlet_method": outlet_method,
            }
            stream_rows.append({
                "linkno": pid,
                "orig_dslinkno": int(st["DSLINKNO"]),
                "downstream_id": int(ds) if ds is not None else None,
                **common,
                "strm_order": int(st["strmOrder"]),
                "length_m": float(st["Length"]),
                "length_km": float(st["Length"]) / 1000.0,
                "magnitude": int(st["Magnitude"]),
                "ds_cont_area_km2": float(st["DSContArea"]) / 1e6,
                "us_cont_area_km2": float(st["USContArea"]) / 1e6,
                "slope": float(st["Slope"]),
                "dout_end_m": float(st["DOUTEND"]),
                "dout_start_m": float(st["DOUTSTART"]),
                "dout_mid_m": float(st["DOUTMID"]),
                "geometry": st.geometry,
            })
            sub_rows.append({
                "polygon_id": pid,
                "subbasin_no": int(sr["Subbasin"]),
                "area_ha": float(sr["Area"]),
                "area_km2": float(sr.geometry.area / 1e6),
                "downstream_id": int(ds) if ds is not None else None,
                **common,
                "area_upstream_km2": float(area_up_memo[pid]),
                "upstream_subbasin_count": int(count_up_memo[pid]),
                "strm_order": int(st["strmOrder"]),
                "length_km": float(st["Length"]) / 1000.0,
                "magnitude": int(st["Magnitude"]),
                "ds_cont_area_km2": float(st["DSContArea"]) / 1e6,
                "geometry": sr.geometry,
            })

        streams_web = gpd.GeoDataFrame(stream_rows, geometry="geometry", crs=TARGET_CRS)
        subbasins_web = gpd.GeoDataFrame(sub_rows, geometry="geometry", crs=TARGET_CRS)

        connector_rows = []
        for cid in sorted(connector_ids):
            if cid not in stream_idx.index:
                continue
            st = stream_idx.loc[cid]
            connector_rows.append({
                "linkno": int(cid),
                "downstream_linkno": int(st["DSLINKNO"]),
                "upstream_linkno1": int(st["USLINKNO1"]),
                "upstream_linkno2": int(st["USLINKNO2"]),
                "length_m": float(st["Length"]),
                "note": "TauDEM topology connector; dilewati pada topology runtime.",
                "geometry": first_line_point(st.geometry),
            })
        connectors = gpd.GeoDataFrame(connector_rows, geometry="geometry", crs=TARGET_CRS)

        official = gpd.read_file(OFFICIAL_PATH, layer="official_basins")
        crosswalk, summary = build_crosswalk(subbasins_web, official)

        build_dir = PROCESSED_ROOT / f"._build_{dataset_id}"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        gpkg = build_dir / "hydro_engine.gpkg"
        subbasins_web.to_file(gpkg, layer="subbasins_web", driver="GPKG")
        streams_web.to_file(gpkg, layer="streams_web", driver="GPKG")
        if len(connectors):
            connectors.to_file(gpkg, layer="topology_connectors", driver="GPKG")
        crosswalk.to_csv(build_dir / "crosswalk.csv", index=False)
        (build_dir / "official_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        shutil.copy2(subbasins_tif, build_dir / "subbasins.tif")

        threshold = meta_src.get("threshold_km2")
        metadata = {
            "dataset_id": dataset_id,
            "name": meta_src.get("name") or dataset_id,
            "threshold_km2": threshold,
            "description": meta_src.get("description", ""),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "crs": TARGET_CRS,
            "flow_direction": "D8 TauDEM codes 1-8",
            "streams_raw": int(len(stream_raw)),
            "streams_runtime": int(len(streams_web)),
            "subbasins": int(len(subbasins_web)),
            "connectors": int(len(connector_ids)),
            "network_outlets": int(sum(1 for v in ds_map.values() if v is None)),
            "raster": raster_qa,
        }
        (build_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        qa = {
            **metadata,
            "invalid_subbasins_before": invalid_before,
            "invalid_subbasins_after": invalid_after,
            "topology_cycles": 0,
            "self_references": 0,
            "broken_downstream": 0,
            "raster_vector_ids_match": True,
            "supported_official_basins": summary["supported_basin_count"],
            "status": "PASS",
        }
        (build_dir / "qa.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
        qa_md = f"""# QA Dataset {dataset_id}\n\n- Status: **PASS**\n- Streams raw: **{len(stream_raw):,}**\n- Streams runtime: **{len(streams_web):,}**\n- Subbasins: **{len(subbasins_web):,}**\n- Connectors: **{len(connector_ids):,}**\n- Invalid polygon sebelum perbaikan: **{invalid_before:,}**\n- Invalid polygon sesudah perbaikan: **{invalid_after:,}**\n- Network outlets: **{metadata['network_outlets']}**\n- Raster/vector ID match: **PASS ({raster_qa['raster_id_count']:,} ID)**\n- Grid raster: **{raster_qa['width']} × {raster_qa['height']}**, ~{raster_qa['pixel_size_x']:.2f} m\n- D8 codes: **{raster_qa['d8_codes']}**\n- DAS dengan coverage engine ≥ {SUPPORTED_COVERAGE_MIN:.0%}: **{summary['supported_basin_count']}**\n"""
        (build_dir / "qa.md").write_text(qa_md, encoding="utf-8")

        final_dir = PROCESSED_ROOT / dataset_id
        backup_dir = PROCESSED_ROOT / f"._backup_{dataset_id}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if final_dir.exists():
            final_dir.rename(backup_dir)
        build_dir.rename(final_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    if activate:
        ACTIVE_PATH.write_text(json.dumps({"dataset": dataset_id}, indent=2), encoding="utf-8")
        say(f"Dataset aktif -> {dataset_id}")

    say("\nSTATUS: PASS")
    say(f"Runtime: {PROCESSED_ROOT / dataset_id}")
    say(f"Streams runtime : {len(streams_web):,}")
    say(f"Subbasins       : {len(subbasins_web):,}")
    say(f"Connectors      : {len(connector_ids):,}")
    say(f"Outlets         : {sum(1 for v in ds_map.values() if v is None)}")
    return PROCESSED_ROOT / dataset_id


def interactive() -> tuple[str, bool]:
    folders = dataset_dirs()
    if not folders:
        raise RuntimeError(f"Belum ada folder dataset di {SOURCE_ROOT}")
    say("=" * 58)
    say(" PREPARE DATASET HIDROLOGI - DELINEASI DTA BBWSSO")
    say("=" * 58)
    for i, folder in enumerate(folders, 1):
        label = folder.name
        meta = folder / "dataset.json"
        if meta.exists():
            try:
                payload = json.loads(meta.read_text(encoding="utf-8"))
                if payload.get("name"):
                    label += f"  |  {payload['name']}"
                if payload.get("threshold_km2") is not None:
                    label += f"  |  threshold {payload['threshold_km2']} km2"
            except Exception:
                pass
        say(f"[{i}] {label}")
    while True:
        raw = input("\nPilih dataset (nomor/nama): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(folders):
            dataset_id = folders[int(raw)-1].name
            break
        if (SOURCE_ROOT / raw).is_dir():
            dataset_id = raw
            break
        say("Pilihan tidak dikenali.")
    ans = input("Aktifkan dataset setelah build? [Y/n]: ").strip().lower()
    return dataset_id, ans not in {"n", "no", "tidak", "t"}


def main():
    parser = argparse.ArgumentParser(description="Validasi, preprocess, dan aktifkan dataset hidrologi.")
    parser.add_argument("--dataset", help="ID folder di data/source/")
    parser.add_argument("--activate", action="store_true", help="Aktifkan setelah build berhasil")
    args = parser.parse_args()
    if args.dataset:
        dataset_id, activate = args.dataset, args.activate
    else:
        dataset_id, activate = interactive()
    try:
        prepare(dataset_id, activate=activate)
    except Exception as exc:
        say("\nSTATUS: FAIL")
        say(str(exc))
        raise

if __name__ == "__main__":
    main()
