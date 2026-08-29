from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
import threading
import time
import urllib.parse
import urllib.request
import tempfile
import zipfile
import atexit
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from rasterio.windows import from_bounds as raster_window_from_bounds
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pyproj import Transformer
from shapely import make_valid, union_all
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import nearest_points, transform

from api.services.boundary_stitch import process_fabdem_polygon, stitch_watershed_boundary
from shapely.strtree import STRtree

try:
    import resource
except ImportError:  # pragma: no cover - Windows local development
    resource = None

API_DIR = Path(__file__).resolve().parent
ROOT_DIR = API_DIR.parent
DATA_DIR = ROOT_DIR / "data"
REFERENCE_DATA_DIR = DATA_DIR / "reference"
SHARED_DATA_DIR = DATA_DIR / "shared"
PROCESSED_DATA_ROOT = DATA_DIR / "processed"
STATIC_DIR = ROOT_DIR / "static"
TEMPLATES_DIR = ROOT_DIR / "templates"

from api.services.runtime_backend import (
    ensure_runtime_object,
    ensure_official_rivers_original,
    ensure_toponym_db_path,
    get_r2_runtime_metrics,
    load_runtime_bundle,
)
from api.services.hydrologic_analysis import build_hydrologic_analysis, optional_spatial_path, refresh_characteristic_narratives
from api.services.characteristics_report import create_characteristics_report
from api.services.characteristics_workbook import create_characteristics_workbook
from api.services.hss_analysis import calculate_hss
from api.services.hss_workbook import create_hss_workbook
from api.services.hss_report import create_hss_report
from api.services.river_display import RIVER_DISPLAY_TIER_BY_FILENAME, build_river_display_gdf
from api.services.performance import (
    HEAVY_JOBS,
    LATEST_REQUESTS,
    HeavyJobQueueFull,
    SupersededRequest,
)

RUNTIME_DATA = load_runtime_bundle(ROOT_DIR)
DATA_BACKEND = RUNTIME_DATA.backend
ACTIVE_DATASET_ID = RUNTIME_DATA.active_dataset_id
ACTIVE_DATASET_METADATA = RUNTIME_DATA.active_dataset_metadata
streams = RUNTIME_DATA.streams
subbasins = RUNTIME_DATA.subbasins
official_basins = RUNTIME_DATA.official_basins
official_rivers = RUNTIME_DATA.official_rivers
official_rivers_original = RUNTIME_DATA.official_rivers_original
crosswalk = RUNTIME_DATA.crosswalk
official_summary = RUNTIME_DATA.official_summary
FDIR_PATH = RUNTIME_DATA.fdir_path
SUBBASIN_RASTER_PATH = RUNTIME_DATA.subbasin_raster_path
TOPONYM_DB_PATH = RUNTIME_DATA.toponym_db_path or (REFERENCE_DATA_DIR / "toponim.sqlite")
MAP_ASSETS_PUBLIC_BASE = RUNTIME_DATA.map_assets_public_base
MAP_ASSETS_VERSION = RUNTIME_DATA.map_assets_version
DEM_PATH = optional_spatial_path(ROOT_DIR, "DTA_DEM_PATH", "dem.tif")
PLEN_PATH = optional_spatial_path(ROOT_DIR, "DTA_FLOW_PATH_PATH", "plen.tif")
CN_PATH = optional_spatial_path(ROOT_DIR, "DTA_CN_PATH", "cn2.tif")
LANDCOVER_PATH = optional_spatial_path(ROOT_DIR, "DTA_LANDCOVER_PATH", "landcover.tif")
ANALYSIS_STREAM_PATH = optional_spatial_path(ROOT_DIR, "DTA_ANALYSIS_STREAM_PATH", "streams_analysis.zip")
LANDSYSTEM_PATH = optional_spatial_path(ROOT_DIR, "DTA_LANDSYSTEM_PATH", "landsystem.zip")

CRS_WEB = "EPSG:4326"
CRS_AREA = "ESRI:54034"
CRS_EXPORT = "EPSG:32749"
APP_VERSION = "1.4.0"
MAX_POINTS = 10
KARST_BASIN_NAMES = {"Bribin", "Seropan", "Buh Putih"}
DEFAULT_PAEK_TOLERANCE_M = 150.0
DEFAULT_VW_TOLERANCE_M = 4.0
HOLE_AREA_THRESHOLD_M2 = 62_500.0  # 6.25 ha
KARST_WARNING_TITLE = "Kawasan Bentang Alam Karst Terdeteksi"
KARST_WARNING_SUBTITLE = "Delineasi Otomatis Tidak Dapat Diproses"
KARST_WARNING_MESSAGE = (
    "Delineasi berbasis DEM permukaan tidak valid untuk kawasan karst. "
    "Sistem hidrologi karst didominasi oleh sungai bawah tanah sehingga batas "
    "topografi permukaan tidak mencerminkan daerah tangkapan air yang sebenarnya."
)
TOPONYM_SETTLEMENT_PRIORITY = {
    "Permukiman Lainnya": 0,
    "Ibukota Desa": 0,
    "Ibukota Kecamatan": 0,
    "Desa": 1,
    "Kecamatan": 2,
    "Kota": 3,
    "Ibukota Kabupaten": 4,
}
TOPONYM_NAMING_RADIUS_M = 5_000.0
TOPOLOGY_CACHE_SIZE = max(256, int(os.getenv("DTA_TOPOLOGY_CACHE_SIZE", "2048")))
UPSTREAM_UNION_CACHE_SIZE = max(4, int(os.getenv("DTA_UPSTREAM_UNION_CACHE_SIZE", "24")))
HYBRID_CACHE_SIZE = max(4, int(os.getenv("DTA_HYBRID_CACHE_SIZE", "16")))
BOUNDARY_CACHE_SIZE = max(4, int(os.getenv("DTA_BOUNDARY_CACHE_SIZE", "16")))
CACHE_PRESSURE_MB = max(256.0, float(os.getenv("DTA_CACHE_PRESSURE_MB", "1400")))
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    "bbwsso-watershed-local-test/1.0 (local watershed delineation application)",
)

print(f"[startup] Loading runtime backend={DATA_BACKEND} dataset={ACTIVE_DATASET_ID} ...")
_start_load = time.perf_counter()

HYBRID_RASTER_AVAILABLE = FDIR_PATH.exists() and SUBBASIN_RASTER_PATH.exists()
if HYBRID_RASTER_AVAILABLE:
    with rasterio.open(FDIR_PATH) as _fdir_ds, rasterio.open(SUBBASIN_RASTER_PATH) as _ws_ds:
        if (_fdir_ds.crs != _ws_ds.crs or _fdir_ds.transform != _ws_ds.transform
                or _fdir_ds.width != _ws_ds.width or _fdir_ds.height != _ws_ds.height):
            raise RuntimeError("Raster flow direction dan subbasin ID tidak memiliki grid yang identik.")
        HYBRID_RASTER_CRS = _fdir_ds.crs
        HYBRID_RASTER_TRANSFORM = _fdir_ds.transform
        HYBRID_RASTER_SHAPE = (_fdir_ds.height, _fdir_ds.width)
else:
    HYBRID_RASTER_CRS = None
    HYBRID_RASTER_TRANSFORM = None
    HYBRID_RASTER_SHAPE = None

if streams.crs is None or subbasins.crs is None or official_basins.crs is None:
    raise RuntimeError("CRS is missing from one or more GeoPackage layers.")
if streams.crs != subbasins.crs or streams.crs != official_basins.crs:
    official_basins = official_basins.to_crs(streams.crs)
if official_rivers.crs is None:
    raise RuntimeError("CRS is missing from official river layer.")
if official_rivers.crs != streams.crs:
    official_rivers = official_rivers.to_crs(streams.crs)

subbasins_by_id = subbasins.set_index("polygon_id", drop=False)
crosswalk_by_id = crosswalk.set_index("polygon_id", drop=False)
streams_by_linkno = streams.set_index("linkno", drop=False)

# Add official basin assignment to in-memory subbasin table.
subbasins = subbasins.merge(
    crosswalk[["polygon_id", "official_basin_code", "official_basin_name", "overlap_ratio"]],
    on="polygon_id",
    how="left",
)
subbasins_by_id = subbasins.set_index("polygon_id", drop=False)

# Directed topology: downstream link -> immediate upstream links.
upstream_by_downstream: dict[int, list[int]] = {}
for linkno, downstream_id in zip(streams["linkno"], streams["downstream_id"]):
    if downstream_id is None or (isinstance(downstream_id, float) and math.isnan(downstream_id)):
        continue
    upstream_by_downstream.setdefault(int(downstream_id), []).append(int(linkno))

link_to_stream_pos = {int(v): i for i, v in enumerate(streams["linkno"].tolist())}
link_to_official_code = {
    int(pid): str(code)
    for pid, code in zip(crosswalk["polygon_id"], crosswalk["official_basin_code"])
    if isinstance(code, str) and code
}

# Official basin lookup.
official_by_code = {
    str(row["basin_code"]): row for _, row in official_basins.iterrows()
}
official_geometries = list(official_basins.geometry.values)
official_tree = STRtree(official_geometries)
supported_basin_codes = set(link_to_official_code.values())
official_river_geometries = list(official_rivers.geometry.values)
official_river_tree = STRtree(official_river_geometries)
official_river_original_geometries: list[Any] | None = None
official_river_original_tree: STRtree | None = None
_ORIGINAL_RIVER_LOCK = threading.Lock()

# Global and per-official-basin stream spatial indexes.
stream_geometries = list(streams.geometry.values)
stream_tree = STRtree(stream_geometries)
stream_indexes_by_basin: dict[str, tuple[list[int], STRtree]] = {}
for code in sorted(supported_basin_codes):
    global_positions = [
        i for i, linkno in enumerate(streams["linkno"].tolist())
        if link_to_official_code.get(int(linkno)) == code
    ]
    geoms = [stream_geometries[i] for i in global_positions]
    if geoms:
        stream_indexes_by_basin[code] = (global_positions, STRtree(geoms))

# Coordinate transformers are always_xy so inputs are lon, lat.
to_data = Transformer.from_crs(CRS_WEB, streams.crs, always_xy=True)
to_web = Transformer.from_crs(streams.crs, CRS_WEB, always_xy=True)
to_area = Transformer.from_crs(streams.crs, CRS_AREA, always_xy=True)
to_export = Transformer.from_crs(streams.crs, CRS_EXPORT, always_xy=True)

def area_km2_equal(geom) -> float:
    """Area in km² using ESRI:54034 World Cylindrical Equal Area."""
    if geom is None or geom.is_empty:
        return 0.0
    return float(transform(to_area.transform, geom).area / 1e6)

def to_export_geom(geom):
    if str(streams.crs).upper() == CRS_EXPORT:
        return geom
    return transform(to_export.transform, geom)


def largest_polygon_component(geom):
    """Keep the largest connected polygon component of a cumulative DTA."""
    if geom is None or geom.is_empty:
        return geom
    fixed = geom if geom.is_valid else make_valid(geom)
    polygons = []

    def collect(g):
        if g is None or g.is_empty:
            return
        if isinstance(g, Polygon):
            polygons.append(g)
        elif isinstance(g, MultiPolygon):
            polygons.extend([part for part in g.geoms if not part.is_empty])
        elif isinstance(g, GeometryCollection):
            for part in g.geoms:
                collect(part)

    collect(fixed)
    if not polygons:
        return fixed
    return max(polygons, key=lambda g: g.area)


def clean_dta_polygon(geom, *, hole_area_threshold_m2: float = HOLE_AREA_THRESHOLD_M2):
    """Topological cleanup shared by RAW and display DTA geometries.

    A cumulative single-outlet DTA is expected to be one connected polygon. Detached
    slivers are removed by keeping the largest polygon component. Interior rings smaller
    than 6.25 ha are filled because they are far below the working scale of the ~30 m DEM
    and are usually repair/stitch artifacts rather than meaningful enclosed non-catchments.
    Larger holes are preserved for QA rather than silently removed.
    """
    if geom is None or geom.is_empty:
        return geom
    poly = largest_polygon_component(geom)
    if not isinstance(poly, Polygon):
        return poly
    holes = []
    for ring in poly.interiors:
        try:
            hole = Polygon(ring)
            if hole.area >= float(hole_area_threshold_m2):
                holes.append(list(ring.coords))
        except Exception:
            continue
    cleaned = Polygon(list(poly.exterior.coords), holes)
    if not cleaned.is_valid:
        cleaned = make_valid(cleaned)
    return largest_polygon_component(cleaned)


def _topology_tolerance_m2() -> float:
    """Small tolerance for raster-cell/smoothing edge effects, not a geometry repair budget."""
    if HYBRID_RASTER_TRANSFORM is not None:
        cell_area = abs(float(HYBRID_RASTER_TRANSFORM.a * HYBRID_RASTER_TRANSFORM.e))
        return max(1.0, cell_area * 4.0)
    return 4_000.0

# Label points are generated from the largest polygon component of each DAS only.
# This prevents repeated labels on small offshore/island components while preserving the
# original official boundary geometry for display and analysis.
def _build_basin_label_fc() -> dict[str, Any]:
    features = []
    for _, row in official_basins.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        main = largest_polygon_component(geom)
        if main is None or main.is_empty:
            continue
        pt = main.representative_point()
        web_pt = transform(to_web.transform, pt)
        features.append({
            "type": "Feature",
            "properties": {"basin_name": str(row.get("basin_name") or "")},
            "geometry": mapping(web_pt),
        })
    return {"type": "FeatureCollection", "features": features}


# Initial map bounds use the official BBWSSO coverage.
_web_bounds = official_basins.to_crs(CRS_WEB).total_bounds.tolist()
_minlon, _minlat, _maxlon, _maxlat = [float(v) for v in _web_bounds]

print(
    f"[startup] Dataset={ACTIVE_DATASET_ID}; loaded {len(streams):,} FABDEM streams, {len(subbasins):,} subbasins, "
    f"{len(official_rivers):,} official rivers and {len(official_basins):,} official basins "
    f"in {time.perf_counter() - _start_load:.2f}s; "
    f"hybrid raster={'ON' if HYBRID_RASTER_AVAILABLE else 'OFF'}"
)


class OutletPoint(BaseModel):
    point_id: str = Field(..., min_length=1, max_length=10)
    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)
    source: str = Field("map", max_length=30)
    label: str | None = Field(None, max_length=160)


class MultiDelineateRequest(BaseModel):
    points: list[OutletPoint] = Field(..., min_length=1, max_length=MAX_POINTS)
    snap_radius_m: float = Field(300.0, gt=0, le=20000)
    boundary_match_m: float = Field(90.0, ge=10, le=500)
    paek_tolerance_m: float = Field(DEFAULT_PAEK_TOLERANCE_M, ge=10, le=1000)
    vw_tolerance_m: float = Field(DEFAULT_VW_TOLERANCE_M, ge=0, le=100)
    decimal_separator: str = Field(",", pattern="^[,.]$")


class CachedResultsRequest(BaseModel):
    """Already-computed DTA results that only need multi-point topology refresh."""
    results: list[dict[str, Any]] = Field(..., min_length=1, max_length=MAX_POINTS)


class DelineateRequest(BaseModel):
    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)
    snap_radius_m: float = Field(300.0, gt=0, le=20000)
    boundary_match_m: float = Field(90.0, ge=10, le=500)
    paek_tolerance_m: float = Field(DEFAULT_PAEK_TOLERANCE_M, ge=10, le=1000)
    vw_tolerance_m: float = Field(DEFAULT_VW_TOLERANCE_M, ge=0, le=100)
    decimal_separator: str = Field(",", pattern="^[,.]$")


class CharacteristicAnalysisRequest(BaseModel):
    point_result: dict[str, Any]
    decimal_separator: str = Field(",", pattern="^[,.]$")


class HssRequest(BaseModel):
    point_id: str = Field(..., min_length=1, max_length=10)
    label: str | None = Field(None, max_length=160)
    hydrologic_analysis: dict[str, Any]
    methods: list[str] = Field(default_factory=lambda: ["scs", "nakayasu", "snyder_alexeyev", "gama1", "limantara", "itb1b", "itb2b"])
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    input_overrides: dict[str, Any] = Field(default_factory=dict)
    global_tr_hours: float = Field(1.0, gt=0, le=24)


class DownloadRequest(BaseModel):
    points: list[OutletPoint] = Field(..., min_length=1, max_length=MAX_POINTS)
    snap_radius_m: float = Field(300.0, gt=0, le=20000)
    boundary_match_m: float = Field(90.0, ge=10, le=500)
    geometry_modes: list[str] = Field(default_factory=lambda: ["smoothed"])
    formats: list[str] = Field(default_factory=lambda: ["shp"])
    include_rivers: bool = False
    include_analysis_report: bool = False
    include_hss: bool = False
    hss_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    language: str = Field("id", pattern="^(id|en)$")
    decimal_separator: str = Field(",", pattern="^[,.]$")


@lru_cache(maxsize=TOPOLOGY_CACHE_SIZE)
def collect_upstream_ids(outlet_linkno: int) -> tuple[int, ...]:
    """Return outlet + all upstream links; topology is immutable per worker."""
    seen: set[int] = set()
    ordered: list[int] = []
    stack = [int(outlet_linkno)]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        stack.extend(upstream_by_downstream.get(current, ()))
    return tuple(ordered)


@lru_cache(maxsize=UPSTREAM_UNION_CACHE_SIZE)
def watershed_union_projected(outlet_linkno: int):
    """Build/cache raw FABDEM upstream union in native projected CRS."""
    upstream_ids = collect_upstream_ids(outlet_linkno)
    missing = [x for x in upstream_ids if x not in subbasins_by_id.index]
    if missing:
        raise KeyError(f"Missing subbasin polygon(s): {missing[:10]}")
    geoms = subbasins_by_id.loc[upstream_ids].geometry.values
    geom = union_all(geoms, grid_size=0.01)
    if not geom.is_valid:
        geom = make_valid(geom)
    return clean_dta_polygon(geom)


# TauDEM D8 direction codes: 1=E, 2=NE, 3=N, 4=NW, 5=W, 6=SW, 7=S, 8=SE.
_TAUDEM_D8_STEP = {
    1: (0, 1), 2: (-1, 1), 3: (-1, 0), 4: (-1, -1),
    5: (0, -1), 6: (1, -1), 7: (1, 0), 8: (1, 1),
}

# Persistent GDAL readers for warm-worker performance. Access is serialized because
# Rasterio dataset handles are not assumed to be thread-safe across FastAPI threads.
_RASTER_LOCK = threading.RLock()
_FDIR_READER = None
_SUBBASIN_READER = None

def _get_raster_readers():
    global _FDIR_READER, _SUBBASIN_READER
    if _FDIR_READER is None or _FDIR_READER.closed:
        _FDIR_READER = rasterio.open(FDIR_PATH)
    if _SUBBASIN_READER is None or _SUBBASIN_READER.closed:
        _SUBBASIN_READER = rasterio.open(SUBBASIN_RASTER_PATH)
    return _FDIR_READER, _SUBBASIN_READER

def _close_raster_readers():
    global _FDIR_READER, _SUBBASIN_READER
    with _RASTER_LOCK:
        for ds in (_FDIR_READER, _SUBBASIN_READER):
            try:
                if ds is not None and not ds.closed:
                    ds.close()
            except Exception:
                pass
        _FDIR_READER = None
        _SUBBASIN_READER = None

atexit.register(_close_raster_readers)


def _nearest_local_raster_cell(
    local_mask: np.ndarray, transform_window, x: float, y: float, reach_geom=None
) -> tuple[int, int]:
    """Return the nearest D8 cell on the selected TauDEM reach inside its local subbasin.

    Rasterizing the matching reach avoids accidentally selecting a nearby hillslope cell when
    the vector line falls close to a cell edge. A plain nearest-subbasin-cell search remains
    available as a fallback.
    """
    inv = ~transform_window
    col_f, row_f = inv * (x, y)
    candidates = None
    if reach_geom is not None and not reach_geom.is_empty:
        reach_mask = rio_features.rasterize(
            [(reach_geom, 1)],
            out_shape=local_mask.shape,
            transform=transform_window,
            fill=0,
            all_touched=True,
            dtype=np.uint8,
        ).astype(bool)
        candidates = np.argwhere(local_mask & reach_mask)
    if candidates is None or candidates.size == 0:
        candidates = np.argwhere(local_mask)
    if candidates.size == 0:
        raise ValueError("Subbasin raster tidak memiliki cell untuk LINKNO yang dipilih.")
    d2 = (candidates[:, 0] + 0.5 - row_f) ** 2 + (candidates[:, 1] + 0.5 - col_f) ** 2
    j = int(np.argmin(d2))
    return int(candidates[j, 0]), int(candidates[j, 1])


def _trace_local_d8_catchment(fdir: np.ndarray, local_mask: np.ndarray, outlet_rc: tuple[int, int]) -> np.ndarray:
    """Reverse-trace all local cells whose TauDEM D8 path reaches the outlet cell."""
    h, w = fdir.shape
    out = np.zeros((h, w), dtype=bool)
    stack = [outlet_rc]
    while stack:
        r, c = stack.pop()
        if r < 0 or c < 0 or r >= h or c >= w or out[r, c] or not local_mask[r, c]:
            continue
        out[r, c] = True
        # Check the 8 neighboring cells and retain neighbors that flow into (r,c).
        for nr in range(max(0, r - 1), min(h, r + 2)):
            for nc in range(max(0, c - 1), min(w, c + 2)):
                if nr == r and nc == c or out[nr, nc] or not local_mask[nr, nc]:
                    continue
                code = int(fdir[nr, nc])
                step = _TAUDEM_D8_STEP.get(code)
                if step is not None and nr + step[0] == r and nc + step[1] == c:
                    stack.append((nr, nc))
    return out


def _read_local_raster_window(outlet_linkno: int):
    if not HYBRID_RASTER_AVAILABLE:
        raise RuntimeError("Raster hybrid belum tersedia.")
    row = subbasins_by_id.loc[int(outlet_linkno)]
    local_geom = row.geometry
    with _RASTER_LOCK:
        fds, wds = _get_raster_readers()
        px = max(abs(float(fds.transform.a)), abs(float(fds.transform.e)))
        minx, miny, maxx, maxy = local_geom.bounds
        win = raster_window_from_bounds(
            minx - 2 * px, miny - 2 * px, maxx + 2 * px, maxy + 2 * px,
            transform=fds.transform,
        )
        win = win.round_offsets().round_lengths()
        full = rasterio.windows.Window(0, 0, fds.width, fds.height)
        win = win.intersection(full)
        fdir = fds.read(1, window=win)
        ws = wds.read(1, window=win)
        wtransform = fds.window_transform(win)
    return fdir, ws, wtransform, win


def locate_outlet_raster_cell(outlet_linkno: int, snapped_point: Point) -> tuple[int, int]:
    """Resolve a snapped outlet to a stable global raster row/column cache key."""
    fdir, ws, wtransform, win = _read_local_raster_window(int(outlet_linkno))
    del fdir
    local_mask = ws == int(outlet_linkno)
    stream_pos = link_to_stream_pos[int(outlet_linkno)]
    reach_geom = streams.iloc[stream_pos].geometry
    local_row, local_col = _nearest_local_raster_cell(
        local_mask, wtransform, snapped_point.x, snapped_point.y, reach_geom=reach_geom
    )
    return int(win.row_off) + local_row, int(win.col_off) + local_col


def local_raster_catchment_by_cell(outlet_linkno: int, outlet_row: int, outlet_col: int):
    """Delineate the local incremental subbasin from a stable global D8 cell."""
    fdir, ws, wtransform, win = _read_local_raster_window(int(outlet_linkno))
    local_mask = ws == int(outlet_linkno)
    outlet_rc = (int(outlet_row) - int(win.row_off), int(outlet_col) - int(win.col_off))
    r, c = outlet_rc
    if r < 0 or c < 0 or r >= local_mask.shape[0] or c >= local_mask.shape[1] or not local_mask[r, c]:
        raise ValueError("Sel outlet cache tidak berada di subbasin raster yang dipilih.")
    catch_mask = _trace_local_d8_catchment(fdir, local_mask, outlet_rc)
    if not catch_mask.any():
        raise ValueError("DTA raster lokal kosong setelah tracing D8.")
    geoms = []
    vals = catch_mask.astype(np.uint8)
    for gj, value in rio_features.shapes(vals, mask=catch_mask, transform=wtransform):
        if int(value) == 1:
            geoms.append(shape(gj))
    if not geoms:
        raise ValueError("Gagal membentuk polygon DTA raster lokal.")
    geom = union_all(geoms, grid_size=0.01)
    if not geom.is_valid:
        geom = make_valid(geom)
    return largest_polygon_component(geom), int(catch_mask.sum()), outlet_rc


def local_raster_catchment_projected(outlet_linkno: int, snapped_point: Point):
    """Backward-compatible wrapper used by local diagnostics and benchmarks."""
    outlet_row, outlet_col = locate_outlet_raster_cell(int(outlet_linkno), snapped_point)
    return local_raster_catchment_by_cell(int(outlet_linkno), outlet_row, outlet_col)


@lru_cache(maxsize=UPSTREAM_UNION_CACHE_SIZE)
def _upstream_union_excluding_outlet(outlet_linkno: int):
    """Cache immutable full-upstream polygon union per LINKNO."""
    upstream_full_ids = tuple(
        x for x in collect_upstream_ids(int(outlet_linkno)) if int(x) != int(outlet_linkno)
    )
    if not upstream_full_ids:
        return None, 0
    missing = [x for x in upstream_full_ids if x not in subbasins_by_id.index]
    if missing:
        raise KeyError(f"Missing upstream subbasin polygon(s): {missing[:10]}")
    geom = union_all(subbasins_by_id.loc[list(upstream_full_ids)].geometry.values, grid_size=0.01)
    if not geom.is_valid:
        geom = make_valid(geom)
    return clean_dta_polygon(geom), len(upstream_full_ids)


@lru_cache(maxsize=HYBRID_CACHE_SIZE)
def _hybrid_watershed_cached(outlet_linkno: int, outlet_row: int, outlet_col: int):
    """Cache raw hybrid D8 geometry by raster cell, not floating-point coordinates."""
    local_geom, local_cells, outlet_rc = local_raster_catchment_by_cell(
        outlet_linkno, int(outlet_row), int(outlet_col)
    )
    upstream_geom, upstream_count = _upstream_union_excluding_outlet(int(outlet_linkno))
    geom = local_geom if upstream_geom is None else union_all([local_geom, upstream_geom], grid_size=0.01)
    if not geom.is_valid:
        geom = make_valid(geom)
    return largest_polygon_component(geom), int(local_cells), int(upstream_count), tuple(outlet_rc)


def hybrid_watershed_projected(outlet_linkno: int, snapped_point: Point):
    """Combine predefined upstream units with a raster-cut local outlet unit."""
    before = _hybrid_watershed_cached.cache_info().hits
    outlet_row, outlet_col = locate_outlet_raster_cell(int(outlet_linkno), snapped_point)
    geom, local_cells, upstream_count, outlet_rc = _hybrid_watershed_cached(
        int(outlet_linkno), int(outlet_row), int(outlet_col)
    )
    cache_hit = _hybrid_watershed_cached.cache_info().hits > before
    return geom, {
        "engine": "hybrid_d8",
        "local_cells": int(local_cells),
        "full_upstream_units": int(upstream_count),
        "local_linkno": int(outlet_linkno),
        "outlet_raster_row": int(outlet_row),
        "outlet_raster_col": int(outlet_col),
        "hybrid_cache_hit": bool(cache_hit),
    }


def official_basin_at_point(point_projected: Point) -> dict[str, Any] | None:
    """Return official basin containing the input point, if any."""
    idxs = official_tree.query(point_projected, predicate="within")
    if len(idxs) == 0:
        idxs = official_tree.query(point_projected, predicate="intersects")
    if len(idxs) == 0:
        return None
    row = official_basins.iloc[int(idxs[0])]
    name = str(row["basin_name"])
    code = str(row["basin_code"])
    supported = code in supported_basin_codes
    return {
        "code": code,
        "name": name,
        "area_km2": area_km2_equal(row.geometry),
        "supported": supported,
        "karst": name in KARST_BASIN_NAMES,
        "direct_official": (not supported) and name not in KARST_BASIN_NAMES,
    }


def _nearest_from_tree(
    point_projected: Point,
    tree: STRtree,
    positions: list[int] | None,
    snap_radius_m: float,
) -> tuple[int, float, Point]:
    idxs, distances = tree.query_nearest(
        point_projected,
        max_distance=float(snap_radius_m),
        return_distance=True,
        all_matches=True,
    )
    if len(idxs) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Tidak ditemukan jalur aliran dalam radius {snap_radius_m:g} m. Perbesar radius snapping pada Pengaturan Lanjutan.",
        )
    min_distance = float(np.min(distances))
    tolerance = max(1e-7, min_distance * 1e-10)
    tied_local = [
        int(i) for i, d in zip(idxs, distances)
        if abs(float(d) - min_distance) <= tolerance
    ]
    tied_global = [positions[i] for i in tied_local] if positions is not None else tied_local
    if len(tied_global) == 1:
        pos = tied_global[0]
    else:
        pos = max(
            tied_global,
            key=lambda i: float(streams.iloc[i].get("ds_cont_area_km2", 0.0) or 0.0),
        )
    stream_geom = streams.iloc[pos].geometry
    snapped = nearest_points(point_projected, stream_geom)[1]
    return pos, min_distance, snapped


def select_nearest_stream(
    point_projected: Point,
    snap_radius_m: float,
    requested_official: dict[str, Any] | None,
) -> tuple[int, float, Point]:
    """Snap using hidden FABDEM stream, constrained to official basin when possible."""
    if requested_official is not None:
        code = requested_official["code"]
        if code not in supported_basin_codes:
            raise HTTPException(status_code=422, detail="DTA menggunakan batas DAS resmi pada wilayah ini.")
        positions, basin_tree = stream_indexes_by_basin[code]
        return _nearest_from_tree(point_projected, basin_tree, positions, snap_radius_m)
    return _nearest_from_tree(point_projected, stream_tree, None, snap_radius_m)


def _river_base_name(name: str | None) -> str | None:
    """Return a river name without a generic prefix."""
    text = (name or "").strip()
    if not text:
        return None
    for prefix in ("Kali ", "K. ", "K ", "Sungai ", "S. ", "S "):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    return text or None


def _river_label(name: str | None) -> str | None:
    """Long-form river name for cards, popups, exports, and API responses."""
    text = _river_base_name(name)
    return f"Kali {text}" if text else None


def _river_map_label(name: str | None) -> str | None:
    """Compact map-only river label."""
    text = _river_base_name(name)
    return f"K. {text}" if text else None


def nearest_official_river(point_projected: Point, max_distance_m: float = 1000.0) -> dict[str, Any] | None:
    try:
        idxs, distances = official_river_tree.query_nearest(
            point_projected, max_distance=float(max_distance_m), return_distance=True, all_matches=True
        )
    except Exception:
        return None
    if len(idxs) == 0:
        return None
    j = int(np.argmin(distances))
    pos = int(idxs[j])
    row = official_rivers.iloc[pos]
    label = _river_label(str(row.get("river_name") or ""))
    if not label:
        return None
    order = row.get("river_order")
    return {
        "name": label,
        "order": int(order) if order is not None and not pd.isna(order) else None,
        "basin": str(row.get("basin_name") or "") or None,
        "distance_m": round(float(distances[j]), 1),
    }


def constrain_to_official(
    outlet_linkno: int,
    raw_geom,
    boundary_match_m: float,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
):
    """Boundary matching + stitching; no polygon hard-clip is used."""
    row = subbasins_by_id.loc[int(outlet_linkno)]
    code = str(row.get("official_basin_code") or "")
    official_row = official_by_code.get(code)
    official_geom = official_row.geometry if official_row is not None else None
    is_network_outlet = int(outlet_linkno) == int(row["basin_id"])

    final_geom, stitch = stitch_watershed_boundary(
        raw_geom,
        official_geom,
        match_tolerance_m=float(boundary_match_m),
        paek_tolerance_m=float(paek_tolerance_m),
        vw_tolerance_m=float(vw_tolerance_m),
        allow_full_official=bool(is_network_outlet),
    )

    official_info = None
    if official_row is not None:
        official_info = {
            "code": code,
            "name": str(official_row["basin_name"]),
            "area_official_km2": float(official_row["area_official_km2"]),
            "area_geometry_km2": float(official_row["area_geometry_km2"]),
        }

    raw_geom = clean_dta_polygon(raw_geom)
    final_geom = clean_dta_polygon(final_geom)
    adjustment_km2 = area_km2_equal(final_geom) - area_km2_equal(raw_geom)
    return final_geom, official_info, str(stitch["mode"]), adjustment_km2, stitch

@lru_cache(maxsize=BOUNDARY_CACHE_SIZE)
def _constrain_network_cached(
    outlet_linkno: int,
    outlet_row: int,
    outlet_col: int,
    boundary_match_m: float,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
):
    """Cache boundary smoothing/stitching by the hydrologically decisive D8 cell."""
    if HYBRID_RASTER_AVAILABLE:
        raw_geom, *_ = _hybrid_watershed_cached(
            int(outlet_linkno), int(outlet_row), int(outlet_col)
        )
    else:
        raw_geom = watershed_union_projected(int(outlet_linkno))
    return constrain_to_official(
        int(outlet_linkno), raw_geom, float(boundary_match_m), float(paek_tolerance_m), float(vw_tolerance_m)
    )


_CACHE_TRIM_LOCK = threading.Lock()
_CACHE_TRIM_COUNT = 0
_LAST_CACHE_TRIM = 0.0


def _rss_memory_mb() -> float:
    """Best-effort current resident memory for Linux/Vercel and local QA."""
    try:
        fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
        if len(fields) >= 2:
            return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE")) / 1024 / 1024
    except Exception:
        pass
    if resource is not None:
        try:
            value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value / 1024 / 1024 if sys.platform == "darwin" else value / 1024
        except Exception:
            pass
    return 0.0


def _trim_geometry_caches_if_needed() -> bool:
    global _CACHE_TRIM_COUNT, _LAST_CACHE_TRIM
    rss = _rss_memory_mb()
    if rss <= 0 or rss < CACHE_PRESSURE_MB or time.monotonic() - _LAST_CACHE_TRIM < 30.0:
        return False
    with _CACHE_TRIM_LOCK:
        rss = _rss_memory_mb()
        if rss < CACHE_PRESSURE_MB or time.monotonic() - _LAST_CACHE_TRIM < 30.0:
            return False
        watershed_union_projected.cache_clear()
        _upstream_union_excluding_outlet.cache_clear()
        _hybrid_watershed_cached.cache_clear()
        _constrain_network_cached.cache_clear()
        _CACHE_TRIM_COUNT += 1
        _LAST_CACHE_TRIM = time.monotonic()
        return True


def _heavy_job_context():
    """Acquire the bounded GIS slot and trim caches under memory pressure."""
    return HEAVY_JOBS.slot()


def _analysis_data_paths() -> dict[str, Path | None]:
    """Resolve optional analysis layers, lazily materializing them from R2 when configured."""
    defaults = {"dem": DEM_PATH, "plen": PLEN_PATH, "flowdir": FDIR_PATH, "cn2": CN_PATH, "landcover": LANDCOVER_PATH,
                "streams_analysis": ANALYSIS_STREAM_PATH, "landsystem": LANDSYSTEM_PATH}
    if DATA_BACKEND != "r2":
        return defaults
    resolved: dict[str, Path | None] = {}
    for name, fallback in defaults.items():
        if name not in RUNTIME_DATA.lazy_objects:
            resolved[name] = fallback
            continue
        try:
            resolved[name] = ensure_runtime_object(RUNTIME_DATA, name)
        except Exception:
            resolved[name] = fallback
    return resolved


def build_point_result(
    point: OutletPoint,
    snap_radius_m: float,
    boundary_match_m: float,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
    forced_linkno: int | None = None,
    cancel_check=None,
) -> tuple[dict[str, Any], set[int]]:
    started = time.perf_counter()
    if cancel_check:
        cancel_check()
    x, y = to_data.transform(point.lon, point.lat)
    requested_projected = Point(x, y)
    requested_official = official_basin_at_point(requested_projected)
    official_river = nearest_official_river(requested_projected)
    if cancel_check:
        cancel_check()

    if forced_linkno is None and requested_official is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "outside_region",
                "title": "Berada di luar wilayah BBWS Serayu Opak",
                "message": "Titik yang dipilih berada di luar cakupan wilayah aplikasi.",
            },
        )

    # Three known karst basins are explicitly blocked for surface-DEM delineation.
    if forced_linkno is None and requested_official and requested_official.get("karst"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "karst_detected",
                "title": KARST_WARNING_TITLE,
                "subtitle": KARST_WARNING_SUBTITLE,
                "message": KARST_WARNING_MESSAGE,
                "official_basin": requested_official,
            },
        )

    # Small official basins outside the FABDEM predefined network use their exact official polygon.
    if forced_linkno is None and requested_official and requested_official.get("direct_official"):
        official_row = official_by_code[requested_official["code"]]
        raw_geom = clean_dta_polygon(official_row.geometry)
        final_geom = raw_geom
        raw_web = transform(to_web.transform, raw_geom)
        snapped = requested_projected
        snapped_web = transform(to_web.transform, snapped)
        result = {
            "point_id": point.point_id,
            "source": point.source,
            "label": point.label,
            "outlet_linkno": None,
            "fabdem_network_id": None,
            "requested_lon": float(point.lon),
            "requested_lat": float(point.lat),
            "snapped_lon": float(snapped_web.x),
            "snapped_lat": float(snapped_web.y),
            "snap_distance_m": 0.0,
            "area_km2": area_km2_equal(final_geom),
            "raw_fabdem_area_km2": area_km2_equal(raw_geom),
            "boundary_adjustment_km2": 0.0,
            "subbasin_count": None,
            "stream_order": official_river.get("order") if official_river else None,
            "level_to_outlet": None,
            "local_subbasin_area_km2": None,
            "official_basin": {
                "code": requested_official["code"],
                "name": requested_official["name"],
                "area_official_km2": float(official_row["area_official_km2"]),
                "area_geometry_km2": float(official_row["area_geometry_km2"]),
            },
            "requested_official_basin": requested_official,
            "official_river": official_river,
            "boundary_mode": "official_direct",
            "boundary_stitch": {"mode": "official_direct"},
            "dta_geojson": mapping(raw_web),
            "dta_raw_geojson": mapping(raw_web),
            "watershed_geojson": mapping(raw_web),
            "processing": {"total_ms": round((time.perf_counter() - started) * 1000.0, 1)},
        }
        result["processing"]["total_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        return result, set()

    t_snap = time.perf_counter()
    if forced_linkno is None:
        stream_pos, snap_distance, snapped = select_nearest_stream(
            requested_projected, snap_radius_m, requested_official,
        )
        outlet_linkno = int(streams.iloc[stream_pos]["linkno"])
    else:
        outlet_linkno = int(forced_linkno)
        if outlet_linkno not in link_to_stream_pos:
            raise HTTPException(status_code=404, detail=f"LINKNO {outlet_linkno} tidak ditemukan.")
        stream_pos = link_to_stream_pos[outlet_linkno]
        stream_row = streams.iloc[stream_pos]
        snapped = Point(float(stream_row["outlet_x"]), float(stream_row["outlet_y"]))
        snap_distance = float(requested_projected.distance(snapped))
    # Nama sungai untuk identitas DTA tidak memengaruhi algoritma delineasi. Jika titik
    # yang diminta agak jauh dari garis sungai resmi, coba lagi pada titik outlet hasil
    # snapping agar label Karakteristik/HSS tetap berupa "Kali ... - Nama Titik".
    if official_river is None:
        official_river = nearest_official_river(snapped)
    snap_ms = (time.perf_counter() - t_snap) * 1000.0

    try:
        t_union = time.perf_counter()
        if HYBRID_RASTER_AVAILABLE:
            raw_geom, hybrid_info = hybrid_watershed_projected(outlet_linkno, snapped)
            outlet_row = int(hybrid_info["outlet_raster_row"])
            outlet_col = int(hybrid_info["outlet_raster_col"])
        else:
            raw_geom = watershed_union_projected(outlet_linkno)
            hybrid_info = {"engine": "predefined_vector"}
            outlet_row = -1
            outlet_col = -1
        union_ms = (time.perf_counter() - t_union) * 1000.0
        if cancel_check:
            cancel_check()

        boundary_hits_before = _constrain_network_cached.cache_info().hits
        t_boundary = time.perf_counter()
        final_geom, official_info, boundary_mode, adjustment_km2, boundary_stitch = _constrain_network_cached(
            int(outlet_linkno), int(outlet_row), int(outlet_col),
            float(boundary_match_m), float(paek_tolerance_m), float(vw_tolerance_m)
        )
        boundary_ms = (time.perf_counter() - t_boundary) * 1000.0
        if cancel_check:
            cancel_check()
        geometry_cache_hit = _constrain_network_cached.cache_info().hits > boundary_hits_before
        geometry_ms = union_ms + boundary_ms
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    t_serialize = time.perf_counter()
    raw_geom = clean_dta_polygon(raw_geom)
    final_geom = clean_dta_polygon(final_geom)
    geom_web = transform(to_web.transform, final_geom)
    raw_web = transform(to_web.transform, raw_geom)
    snapped_web = transform(to_web.transform, snapped)
    row = subbasins_by_id.loc[outlet_linkno]
    upstream_ids = set(collect_upstream_ids(outlet_linkno))
    serialize_ms = (time.perf_counter() - t_serialize) * 1000.0

    result = {
        "point_id": point.point_id,
        "source": point.source,
        "label": point.label,
        "outlet_linkno": outlet_linkno,
        "fabdem_network_id": int(row["basin_id"]),
        "requested_lon": float(point.lon),
        "requested_lat": float(point.lat),
        "snapped_lon": float(snapped_web.x),
        "snapped_lat": float(snapped_web.y),
        "snap_distance_m": round(float(snap_distance), 3),
        "area_km2": area_km2_equal(final_geom),
        "raw_fabdem_area_km2": area_km2_equal(raw_geom),
        "boundary_adjustment_km2": float(adjustment_km2),
        "subbasin_count": int(len(upstream_ids)),
        "stream_order": int(row["strm_order"]),
        "level_to_outlet": int(row["level_to_outlet"]),
        "local_subbasin_area_km2": float(row["area_km2"]),
        "official_basin": official_info,
        "requested_official_basin": requested_official,
        "official_river": official_river,
        "boundary_mode": boundary_mode,
        "boundary_stitch": boundary_stitch,
        "dta_geojson": mapping(geom_web),
        "dta_raw_geojson": mapping(raw_web),
        "watershed_geojson": mapping(geom_web),
        "processing": {
            "snap_ms": round(snap_ms, 1),
            "union_ms": round(union_ms, 1),
            "boundary_ms": round(boundary_ms, 1),
            "geometry_ms": round(geometry_ms, 1),
            "geometry_cache_hit": bool(geometry_cache_hit),
            "serialize_ms": round(serialize_ms, 1),
            "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            **hybrid_info,
        },
    }
    result["processing"]["total_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return result, upstream_ids


def analyze_point_network(results: list[dict[str, Any]], upstream_sets: list[set[int]]) -> dict[str, Any]:
    n = len(results)
    relations: list[dict[str, Any]] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = results[i], results[j]
            la, lb = a.get("outlet_linkno"), b.get("outlet_linkno")
            if la is not None and lb is not None:
                la, lb = int(la), int(lb)
                if la == lb:
                    # Hybrid raster can distinguish multiple pour points along the same predefined reach.
                    area_a = float(a.get("raw_fabdem_area_km2") or a.get("area_km2") or 0.0)
                    area_b = float(b.get("raw_fabdem_area_km2") or b.get("area_km2") or 0.0)
                    if abs(area_a - area_b) <= max(1e-6, 1e-5 * max(area_a, area_b, 1.0)):
                        relation, upstream_id, downstream_id = "same_outlet", a["point_id"], b["point_id"]
                    elif area_a < area_b:
                        relation, upstream_id, downstream_id = "same_flow_path", a["point_id"], b["point_id"]
                    else:
                        relation, upstream_id, downstream_id = "same_flow_path", b["point_id"], a["point_id"]
                elif la in upstream_sets[j]:
                    relation, upstream_id, downstream_id = "same_flow_path", a["point_id"], b["point_id"]
                elif lb in upstream_sets[i]:
                    relation, upstream_id, downstream_id = "same_flow_path", b["point_id"], a["point_id"]
                else:
                    ca=(a.get("official_basin") or {}).get("code"); cb=(b.get("official_basin") or {}).get("code")
                    relation="same_basin_different_branch" if ca and ca==cb else "different_basin"
                    upstream_id=downstream_id=None
            else:
                ca=(a.get("official_basin") or {}).get("code"); cb=(b.get("official_basin") or {}).get("code")
                relation="same_basin_different_branch" if ca and ca==cb else "different_basin"
                upstream_id=downstream_id=None
            relations.append({"point_a":a["point_id"],"point_b":b["point_id"],"relation":relation,"upstream_point":upstream_id,"downstream_point":downstream_id})

    order = sorted(range(n), key=lambda idx: (results[idx]["area_km2"], results[idx]["point_id"]))
    chain = n >= 2
    segments: list[dict[str, Any]] = []
    for a_idx, b_idx in zip(order[:-1], order[1:]):
        a, b = results[a_idx], results[b_idx]
        la, lb = a.get("outlet_linkno"), b.get("outlet_linkno")
        if la is None or lb is None:
            chain = False; break
        la, lb = int(la), int(lb)
        if not (la == lb or la in upstream_sets[b_idx]):
            chain = False; break
        segments.append({"upstream_point":a["point_id"],"downstream_point":b["point_id"],"incremental_area_km2":max(0.0,float(b["area_km2"]-a["area_km2"]))})
    return {"same_flow_path_all":bool(chain),"ordered_points":[results[i]["point_id"] for i in order] if chain else [],"segments":segments if chain else [],"pair_relations":relations}


def _result_native_geometry(result: dict[str, Any], key: str = "dta_geojson"):
    value = result.get(key)
    if not value:
        return None
    return transform(to_data.transform, shape(value))


def _compute_hydrologic_analysis_for_result(result: dict[str, Any], *, decimal_separator: str = ",") -> dict[str, Any]:
    """Compute DTA characteristics lazily from an already-delineated final geometry.

    Delineation intentionally does not call this function. It is invoked only by the
    Karakteristik/HSS flows or when an analysis report is explicitly requested.
    """
    geom = _result_native_geometry(result)
    if geom is None or geom.is_empty:
        raise ValueError("Geometri DTA tidak tersedia untuk analisis karakteristik.")
    snapped = Point(*to_data.transform(float(result["snapped_lon"]), float(result["snapped_lat"])))
    outlet_linkno = result.get("outlet_linkno")
    upstream_ids = set(collect_upstream_ids(int(outlet_linkno))) if outlet_linkno is not None else set()
    analysis_paths = _analysis_data_paths()
    analysis = build_hydrologic_analysis(
        geom=geom,
        outlet=snapped,
        source_crs=streams.crs,
        area_km2=area_km2_equal(geom),
        streams=streams,
        upstream_ids=upstream_ids,
        upstream_by_downstream=upstream_by_downstream,
        outlet_linkno=outlet_linkno,
        dem_path=analysis_paths["dem"], plen_path=analysis_paths["plen"], flowdir_path=analysis_paths["flowdir"],
        landcover_path=analysis_paths["landcover"], cn_path=analysis_paths["cn2"],
        analysis_stream_path=analysis_paths["streams_analysis"], landsystem_path=analysis_paths["landsystem"],
    )
    return refresh_characteristic_narratives(analysis, decimal_separator)


def _refresh_reconciled_hydrologic_analysis(result: dict[str, Any], upstream_ids: set[int]) -> None:
    """Compatibility helper for explicit analysis refreshes only."""
    del upstream_ids
    result["hydrologic_analysis"] = _compute_hydrologic_analysis_for_result(result)


def _safe_smoothed_raw(result: dict[str, Any]):
    raw = _result_native_geometry(result, "dta_raw_geojson")
    if raw is None or raw.is_empty:
        return _result_native_geometry(result, "dta_geojson")
    candidate = process_fabdem_polygon(
        clean_dta_polygon(raw),
        paek_tolerance_m=DEFAULT_PAEK_TOLERANCE_M,
        vw_tolerance_m=DEFAULT_VW_TOLERANCE_M,
    )
    return clean_dta_polygon(candidate)



def _geometry_outside_area(inner, outer, *, epsilon_m: float = 0.25) -> float:
    """Area of *inner* genuinely outside *outer* after a tiny numeric buffer."""
    if inner is None or outer is None or inner.is_empty or outer.is_empty:
        return 0.0
    try:
        return float(inner.difference(outer.buffer(float(epsilon_m))).area)
    except Exception:
        return float(inner.difference(outer).area)


def reconcile_final_geometries(results: list[dict[str, Any]], upstream_sets: list[set[int]]) -> list[dict[str, Any]]:
    """Reconcile independently smoothed DTA into deterministic hydrologic topology.

    Toponym naming rules:
    - Different tributary branches are reconciled first. If smoothing creates overlap,
      both branches fall back to DEM-derived geometry; raw D8 is the final fail-safe.
    - Same-flow DTA are then enforced as strictly nested with a tiny numeric epsilon.
      Small crossing strips are not ignored merely because their area is below a few cells.
    - Nesting is processed upstream -> downstream and repeated so 3+ point chains are
      independent of click order.
    - No line/polygon is fabricated here: reconciliation only uses polygon union/fallback.
    """
    if len(results) < 2:
        return results

    finals = [clean_dta_polygon(_result_native_geometry(r)) for r in results]
    id_to_idx = {r["point_id"]: i for i, r in enumerate(results)}
    net = analyze_point_network(results, upstream_sets)
    notes = {r["point_id"]: [] for r in results}
    branch_tol = max(1.0, _topology_tolerance_m2() * 0.25)

    branch_pairs: list[tuple[int, int]] = []
    for rel in net.get("pair_relations", []):
        if rel.get("relation") != "same_basin_different_branch":
            continue
        ai = id_to_idx.get(rel.get("point_a"))
        bi = id_to_idx.get(rel.get("point_b"))
        if ai is not None and bi is not None:
            branch_pairs.append((ai, bi))

    for ai, bi in branch_pairs:
        overlap = float(finals[ai].intersection(finals[bi]).area)
        if overlap <= branch_tol:
            continue
        safe_a, safe_b = _safe_smoothed_raw(results[ai]), _safe_smoothed_raw(results[bi])
        if safe_a is not None and safe_b is not None:
            safe_overlap = float(safe_a.intersection(safe_b).area)
            if safe_overlap < overlap:
                finals[ai], finals[bi] = safe_a, safe_b
                notes[results[ai]["point_id"]].append("branch_dem_fallback")
                notes[results[bi]["point_id"]].append("branch_dem_fallback")
                overlap = safe_overlap
        if overlap > branch_tol:
            raw_a = clean_dta_polygon(_result_native_geometry(results[ai], "dta_raw_geojson"))
            raw_b = clean_dta_polygon(_result_native_geometry(results[bi], "dta_raw_geojson"))
            if raw_a is not None and raw_b is not None:
                finals[ai], finals[bi] = raw_a, raw_b
                notes[results[ai]["point_id"]].append("branch_raw_topology_fallback")
                notes[results[bi]["point_id"]].append("branch_raw_topology_fallback")

    same_flow_pairs: list[tuple[int, int]] = []
    for rel in net.get("pair_relations", []):
        if rel.get("relation") != "same_flow_path":
            continue
        ui = id_to_idx.get(rel.get("upstream_point"))
        di = id_to_idx.get(rel.get("downstream_point"))
        if ui is not None and di is not None:
            same_flow_pairs.append((ui, di))

    def raw_area(idx: int) -> float:
        return float(results[idx].get("raw_fabdem_area_km2") or results[idx].get("area_km2") or 0.0)

    same_flow_pairs.sort(
        key=lambda pair: (raw_area(pair[1]), raw_area(pair[0]), results[pair[1]]["point_id"])
    )

    for _ in range(max(1, len(results))):
        changed = False
        for ui, di in same_flow_pairs:
            outside = _geometry_outside_area(finals[ui], finals[di], epsilon_m=0.25)
            if outside <= 1.0:
                continue
            candidate = clean_dta_polygon(finals[di].union(finals[ui]))
            if candidate is None or candidate.is_empty:
                continue
            finals[di] = candidate
            if "strict_nested_union" not in notes[results[di]["point_id"]]:
                notes[results[di]["point_id"]].append("strict_nested_union")
            changed = True
        if not changed:
            break

    pair_qa: list[dict[str, Any]] = []
    for rel in net.get("pair_relations", []):
        relation = rel.get("relation")
        qa = {
            "point_a": rel.get("point_a"),
            "point_b": rel.get("point_b"),
            "relation": relation,
            "status": "pass",
        }
        if relation == "same_flow_path":
            ui = id_to_idx.get(rel.get("upstream_point"))
            di = id_to_idx.get(rel.get("downstream_point"))
            if ui is not None and di is not None:
                outside = _geometry_outside_area(finals[ui], finals[di], epsilon_m=0.25)
                qa["outside_m2"] = round(outside, 3)
                if outside > 1.0:
                    finals[di] = clean_dta_polygon(finals[di].union(finals[ui]))
                    outside = _geometry_outside_area(finals[ui], finals[di], epsilon_m=0.25)
                    qa["outside_m2_after"] = round(outside, 3)
                    qa["status"] = "reconciled" if outside <= 1.0 else "warning"
                    notes[results[di]["point_id"]].append("final_nested_union")
        elif relation == "same_basin_different_branch":
            ai = id_to_idx.get(rel.get("point_a"))
            bi = id_to_idx.get(rel.get("point_b"))
            if ai is not None and bi is not None:
                overlap = float(finals[ai].intersection(finals[bi]).area)
                qa["overlap_m2"] = round(overlap, 3)
                if overlap > branch_tol:
                    qa["status"] = "warning"
        pair_qa.append(qa)

    for i, result in enumerate(results):
        geom = clean_dta_polygon(finals[i])
        raw = clean_dta_polygon(_result_native_geometry(result, "dta_raw_geojson"))
        result["dta_geojson"] = mapping(transform(to_web.transform, geom))
        result["watershed_geojson"] = result["dta_geojson"]
        result["area_km2"] = area_km2_equal(geom)
        if raw is not None:
            result["raw_fabdem_area_km2"] = area_km2_equal(raw)
            result["boundary_adjustment_km2"] = result["area_km2"] - result["raw_fabdem_area_km2"]
        if notes[result["point_id"]]:
            # Any previously cached characteristic/HSS source analysis belongs to the old
            # geometry. Keep delineation light and force a fresh lazy analysis on next open.
            result.pop("hydrologic_analysis", None)
        result["topology_qa"] = {
            "status": "reconciled" if notes[result["point_id"]] else "pass",
            "actions": notes[result["point_id"]],
            "hole_filter_ha": HOLE_AREA_THRESHOLD_M2 / 10_000.0,
            "pairs": [
                q for q in pair_qa
                if q.get("point_a") == result["point_id"] or q.get("point_b") == result["point_id"]
            ],
        }
    return results


def apply_incremental_geometries(results: list[dict[str, Any]], upstream_sets: list[set[int]]) -> None:
    """Refresh incremental hatch without re-running raster delineation."""
    projected_final = [_result_native_geometry(r) for r in results]
    for j, result in enumerate(results):
        link_j = result.get("outlet_linkno")
        upstream_selected = []
        if link_j is not None:
            for i, other in enumerate(results):
                if i == j:
                    continue
                link_i = other.get("outlet_linkno")
                if link_i is None:
                    continue
                same_link = int(link_i) == int(link_j)
                if same_link:
                    area_i = float(other.get("raw_fabdem_area_km2") or other.get("area_km2") or 0.0)
                    area_j = float(result.get("raw_fabdem_area_km2") or result.get("area_km2") or 0.0)
                    if area_i < area_j - max(1e-6, 1e-5 * max(area_i, area_j, 1.0)):
                        upstream_selected.append(projected_final[i])
                elif int(link_i) in upstream_sets[j]:
                    upstream_selected.append(projected_final[i])
        incremental = projected_final[j]
        if upstream_selected:
            try:
                incremental = incremental.difference(union_all(upstream_selected, grid_size=0.01))
                if not incremental.is_valid:
                    incremental = make_valid(incremental)
            except Exception:
                incremental = projected_final[j]
        result["dta_incremental_geojson"] = mapping(transform(to_web.transform, incremental))
        result["incremental_area_km2"] = area_km2_equal(incremental)



def _normalize_search_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\\s+", " ", value).strip()


def _toponym_connection() -> sqlite3.Connection | None:
    try:
        path = ensure_toponym_db_path(RUNTIME_DATA)
    except RuntimeError:
        return None
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * radius * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1.0 - h)))


@lru_cache(maxsize=512)
def _search_local_toponyms_cached(query_text: str) -> tuple[dict[str, Any], ...]:
    conn = _toponym_connection()
    if conn is None:
        return ()
    qn = _normalize_search_text(query_text)
    if len(qn) < 2:
        conn.close()
        return ()
    rows = conn.execute(
        """
        SELECT id,name,category,lon,lat,settlement_priority,name_norm
        FROM toponim
        WHERE name_norm LIKE ?
        ORDER BY
          CASE WHEN name_norm = ? THEN 0
               WHEN name_norm LIKE ? THEN 1
               ELSE 2 END,
          CASE WHEN settlement_priority IS NULL THEN 99 ELSE settlement_priority END,
          length(name_norm),
          name_norm
        LIMIT 10
        """,
        (f"%{qn}%", qn, f"{qn}%"),
    ).fetchall()
    conn.close()
    return tuple(
        {
            "display_name": f"{row['name']} · {row['category']}" if row["category"] else row["name"],
            "name": row["name"],
            "category": row["category"] or "Toponim",
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "source": "toponim",
            "source_label": "Toponim",
        }
        for row in rows
    )


@lru_cache(maxsize=4096)
def _nearby_settlement_candidates_cached(lon_key: float, lat_key: float) -> tuple[dict[str, Any], ...]:
    """Return settlement toponyms within the naming radius.

    Category priority is intentionally evaluated in Python instead of trusting the
    SQLite priority column so an older prebuilt database remains compatible with
    newer ranking rules.
    """
    lon, lat = float(lon_key), float(lat_key)
    radius_m = TOPONYM_NAMING_RADIUS_M
    conn = _toponym_connection()
    if conn is None:
        return ()
    lat_delta = radius_m / 111_320.0
    lon_delta = radius_m / max(10_000.0, 111_320.0 * math.cos(math.radians(lat)))
    rows = conn.execute(
        """
        SELECT t.id,t.name,t.category,t.lon,t.lat
        FROM toponim_rtree r
        JOIN toponim t ON t.id=r.id
        WHERE r.min_lon BETWEEN ? AND ?
          AND r.min_lat BETWEEN ? AND ?
        """,
        (lon - lon_delta, lon + lon_delta, lat - lat_delta, lat + lat_delta),
    ).fetchall()
    conn.close()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        category = str(row["category"] or "").strip()
        if category not in TOPONYM_SETTLEMENT_PRIORITY:
            continue
        distance = _haversine_m(lon, lat, float(row["lon"]), float(row["lat"]))
        if distance > radius_m:
            continue
        candidates.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "category": category,
                "distance_m": float(distance),
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
                "priority": int(TOPONYM_SETTLEMENT_PRIORITY[category]),
            }
        )
    return tuple(candidates)


def _stream_component_near_point(geom, point: Point):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "LineString":
        return geom
    if geom.geom_type == "MultiLineString":
        parts = [g for g in geom.geoms if not g.is_empty and g.length > 0]
        return min(parts, key=lambda g: g.distance(point)) if parts else None
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if g.geom_type == "LineString" and not g.is_empty and g.length > 0]
        return min(parts, key=lambda g: g.distance(point)) if parts else None
    return None


def _oriented_stream_line(stream_pos: int, snapped_point: Point):
    """Return the local stream component oriented from upstream to downstream.

    Geometry digitising direction is not assumed. The downstream endpoint is
    inferred from the TauDEM linkage. At a network outlet, immediate upstream
    reaches are used to identify the upstream end.
    """
    row = streams.iloc[int(stream_pos)]
    line = _stream_component_near_point(row.geometry, snapped_point)
    if line is None or line.length <= 0:
        return None

    coords = list(line.coords)
    if len(coords) < 2:
        return None
    start_pt, end_pt = Point(coords[0]), Point(coords[-1])
    downstream_is_end: bool | None = None

    downstream_id = row.get("downstream_id")
    if downstream_id is not None and not pd.isna(downstream_id):
        downstream_id = int(downstream_id)
        if downstream_id in streams_by_linkno.index:
            ds_geom = streams_by_linkno.loc[downstream_id].geometry
            downstream_is_end = end_pt.distance(ds_geom) <= start_pt.distance(ds_geom)

    if downstream_is_end is None:
        upstream_links = upstream_by_downstream.get(int(row["linkno"]), [])
        upstream_geoms = [
            streams_by_linkno.loc[int(link)].geometry
            for link in upstream_links
            if int(link) in streams_by_linkno.index
        ]
        if upstream_geoms:
            start_up_dist = min(start_pt.distance(g) for g in upstream_geoms)
            end_up_dist = min(end_pt.distance(g) for g in upstream_geoms)
            # Endpoint farther from connected upstream reaches is downstream.
            downstream_is_end = end_up_dist >= start_up_dist

    if downstream_is_end is None:
        try:
            outlet = Point(float(row["outlet_x"]), float(row["outlet_y"]))
            downstream_is_end = end_pt.distance(outlet) <= start_pt.distance(outlet)
        except Exception:
            downstream_is_end = True

    if downstream_is_end:
        return line
    from shapely.geometry import LineString
    return LineString(coords[::-1])


def _flow_side(stream_pos: int, snapped_point: Point, target_point: Point) -> int:
    """Side of target relative to downstream flow: +1 left, -1 right, 0 unknown."""
    line = _oriented_stream_line(stream_pos, snapped_point)
    if line is None or line.length <= 0:
        return 0
    offset = float(snapped_point.distance(target_point))
    if offset < 12.0:
        return 0

    station = float(line.project(snapped_point))
    delta = min(90.0, max(20.0, float(line.length) * 0.03))
    a_station = max(0.0, station - delta)
    b_station = min(float(line.length), station + delta)
    if b_station - a_station < 5.0:
        return 0
    a = line.interpolate(a_station)
    b = line.interpolate(b_station)
    dx, dy = float(b.x - a.x), float(b.y - a.y)
    vx, vy = float(target_point.x - snapped_point.x), float(target_point.y - snapped_point.y)
    tangent_len = math.hypot(dx, dy)
    if tangent_len <= 1e-9:
        return 0
    cross = dx * vy - dy * vx
    # If target lies almost on the local flow axis, side classification is unstable.
    sin_angle = abs(cross) / max(1e-9, tangent_len * max(offset, 1e-9))
    if sin_angle < 0.08:
        return 0
    return 1 if cross > 0 else -1


def nearest_settlement_toponym(
    lon: float,
    lat: float,
    *,
    stream_pos: int | None = None,
    snapped_point: Point | None = None,
) -> dict[str, Any] | None:
    """Choose an automatic point name from settlement toponyms.

    Permukiman Lainnya, Ibukota Desa, and Ibukota Kecamatan are the same
    priority tier, so the nearest one wins. If the requested point is clearly on
    one side of a river, same-side candidates are preferred before falling back
    to candidates on either side.
    """
    lon_key, lat_key = round(float(lon), 5), round(float(lat), 5)
    candidates = [dict(item) for item in _nearby_settlement_candidates_cached(lon_key, lat_key)]
    if not candidates:
        return None

    requested_side = 0
    same_side_used = False
    if stream_pos is not None and snapped_point is not None:
        requested_projected = Point(*to_data.transform(float(lon), float(lat)))
        requested_side = _flow_side(int(stream_pos), snapped_point, requested_projected)
        if requested_side:
            for candidate in candidates:
                candidate_projected = Point(*to_data.transform(candidate["lon"], candidate["lat"]))
                candidate["flow_side"] = _flow_side(int(stream_pos), snapped_point, candidate_projected)
            same_side = [item for item in candidates if item.get("flow_side") == requested_side]
            if same_side:
                candidates = same_side
                same_side_used = True

    candidates.sort(
        key=lambda item: (
            int(item["priority"]),
            float(item["distance_m"]),
            str(item["name"]).casefold(),
        )
    )
    chosen = candidates[0]
    return {
        "name": chosen["name"],
        "category": chosen["category"],
        "distance_m": round(float(chosen["distance_m"]), 1),
        "lon": float(chosen["lon"]),
        "lat": float(chosen["lat"]),
        "priority": int(chosen["priority"]),
        "source": "toponim",
        "same_river_side_preferred": bool(same_side_used),
        "requested_river_side": "left" if requested_side > 0 else "right" if requested_side < 0 else None,
    }


# Nominatim: no autocomplete, max 1 request/s, app-identifying User-Agent, local cache.
_geocode_lock = threading.Lock()
_last_geocode_request = 0.0


@lru_cache(maxsize=128)
def _nominatim_search_cached(query_text: str) -> tuple[dict[str, Any], ...]:
    global _last_geocode_request
    with _geocode_lock:
        elapsed = time.monotonic() - _last_geocode_request
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        params = {
            "q": query_text,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
            "countrycodes": "id",
            "viewbox": f"{_minlon},{_maxlat},{_maxlon},{_minlat}",
            "bounded": 1,
        }
        url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": NOMINATIM_USER_AGENT,
                "Accept-Language": "id,en;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Nominatim tidak dapat diakses: {exc}") from exc
        finally:
            _last_geocode_request = time.monotonic()

    clean: list[dict[str, Any]] = []
    for item in payload:
        try:
            lon = float(item["lon"])
            lat = float(item["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        display_name = str(item.get("display_name", ""))
        clean.append({
            "display_name": display_name,
            "name": str(item.get("name") or (display_name.split(",")[0] if display_name else query_text)),
            "lon": lon,
            "lat": lat,
            "type": str(item.get("type", "")),
            "category": str(item.get("category", item.get("class", ""))) or "OpenStreetMap",
            "source": "osm",
            "source_label": "OpenStreetMap",
        })
    return tuple(clean)


app = FastAPI(title="Delineasi DTA API", version=APP_VERSION)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif request.url.path == "/":
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _register_delineation_request(request: Request):
    return LATEST_REQUESTS.register(
        request.headers.get("x-dta-client-id"), request.headers.get("x-dta-request-id")
    )


def _performance_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SupersededRequest):
        return HTTPException(
            status_code=409,
            detail={"code": "request_superseded", "message": str(exc)},
        )
    return HTTPException(
        status_code=429,
        detail={"code": "server_busy", "message": str(exc)},
        headers={"Retry-After": "2"},
    )


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="spatial.html",
        context={
            "map_assets_public_base": MAP_ASSETS_PUBLIC_BASE or "",
            "map_assets_version": MAP_ASSETS_VERSION or APP_VERSION,
        },
    )


@app.get("/api/info")
def info():
    performance = {
        "persistent_raster_reader": True,
        "r2_etag_cache": DATA_BACKEND == "r2",
        "r2_manifest_first_cache": DATA_BACKEND == "r2",
        "r2_parallel_downloads": DATA_BACKEND == "r2",
        "lazy_original_rivers_and_toponyms": DATA_BACKEND == "r2",
        "raster_cell_cache_key": True,
        "rss_memory_mb": round(_rss_memory_mb(), 1),
        "cache_pressure_mb": CACHE_PRESSURE_MB,
        "cache_trim_count": _CACHE_TRIM_COUNT,
        "heavy_jobs": HEAVY_JOBS.metrics(),
        "latest_requests": LATEST_REQUESTS.metrics(),
        "r2_runtime": get_r2_runtime_metrics() if DATA_BACKEND == "r2" else None,
        "upstream_topology_cache": collect_upstream_ids.cache_info()._asdict(),
        "upstream_union_cache": _upstream_union_excluding_outlet.cache_info()._asdict(),
        "hybrid_cache": _hybrid_watershed_cached.cache_info()._asdict(),
        "boundary_geometry_cache": _constrain_network_cached.cache_info()._asdict(),
    }
    return {
        "app_version": APP_VERSION,
        "active_dataset": ACTIVE_DATASET_ID,
        "data_backend": DATA_BACKEND,
        "active_dataset_metadata": ACTIVE_DATASET_METADATA,
        "official_rivers": int(len(official_rivers)),
        "official_basins": int(len(official_basins)),
        "bounds_wgs84": [float(v) for v in _web_bounds],
        "max_points": MAX_POINTS,
        "default_snap_radius_m": 300,
        "default_boundary_match_m": 90,
        "hybrid_raster_available": bool(HYBRID_RASTER_AVAILABLE),
        "hydrologic_analysis": {
            "dem_available": bool(DEM_PATH),
            "flow_path_available": bool(PLEN_PATH),
            "curve_number_available": bool(CN_PATH),
            "landcover_available": bool(LANDCOVER_PATH),
            "analysis_streams_available": bool(ANALYSIS_STREAM_PATH),
            "landsystem_available": bool(LANDSYSTEM_PATH),
            "dem_source": DEM_PATH.name if DEM_PATH else None,
            "flow_path_source": PLEN_PATH.name if PLEN_PATH else None,
            "curve_number_source": CN_PATH.name if CN_PATH else None,
            "landcover_source": LANDCOVER_PATH.name if LANDCOVER_PATH else None,
            "analysis_streams_source": ANALYSIS_STREAM_PATH.name if ANALYSIS_STREAM_PATH else None,
            "landsystem_source": LANDSYSTEM_PATH.name if LANDSYSTEM_PATH else None,
        },
        "hydrology_streams": int(len(streams)),
        "hydrology_subbasins": int(len(subbasins)),
        "hybrid_raster_shape": list(HYBRID_RASTER_SHAPE) if HYBRID_RASTER_SHAPE else None,
        "google_maps_available": bool(os.getenv("GOOGLE_MAPS_TILE_URL")),
        "google_satellite_available": bool(os.getenv("GOOGLE_SATELLITE_TILE_URL")),
        "google_maps_tile_url": os.getenv("GOOGLE_MAPS_TILE_URL", ""),
        "google_satellite_tile_url": os.getenv("GOOGLE_SATELLITE_TILE_URL", ""),
        "performance_v1": performance,
        "performance_v2": performance,
    }


@app.get("/api/location-check")
def location_check(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    snap_radius_m: float = Query(300.0, gt=0, le=20000),
):
    """Validate a requested point, preview snapping, and suggest a settlement name."""
    x, y = to_data.transform(lon, lat)
    pt = Point(x, y)
    basin = official_basin_at_point(pt)
    river = nearest_official_river(pt)

    if basin is None:
        return {
            "inside_official_basin": False,
            "official_basin": None,
            "delineation_supported": False,
            "karst_detected": False,
            "mode": "outside_region",
            "official_river": river,
            "toponym": nearest_settlement_toponym(lon, lat),
            "snap_preview": None,
            "warning": {
                "code": "outside_region",
                "title": "Berada di luar wilayah BBWS Serayu Opak",
                "message": "Titik yang dipilih berada di luar cakupan wilayah aplikasi.",
            },
        }

    karst = bool(basin.get("karst"))
    snap_preview: dict[str, Any] | None = None
    toponym: dict[str, Any] | None = None

    if karst:
        toponym = nearest_settlement_toponym(lon, lat)
    elif basin.get("direct_official"):
        snap_preview = {
            "available": True,
            "lon": float(lon),
            "lat": float(lat),
            "distance_m": 0.0,
            "linkno": None,
            "mode": "official_direct",
        }
        toponym = nearest_settlement_toponym(lon, lat)
    else:
        try:
            stream_pos, snap_distance, snapped = select_nearest_stream(pt, snap_radius_m, basin)
            snapped_web = transform(to_web.transform, snapped)
            snap_preview = {
                "available": True,
                "lon": float(snapped_web.x),
                "lat": float(snapped_web.y),
                "distance_m": round(float(snap_distance), 3),
                "linkno": int(streams.iloc[stream_pos]["linkno"]),
                "mode": "dem",
            }
            # Automatic naming follows the same river side as the original click
            # whenever that side can be determined robustly.
            toponym = nearest_settlement_toponym(
                lon,
                lat,
                stream_pos=int(stream_pos),
                snapped_point=snapped,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Jalur aliran tidak ditemukan pada radius pencarian."
            snap_preview = {
                "available": False,
                "distance_m": None,
                "linkno": None,
                "mode": "dem",
                "message": detail,
            }
            toponym = nearest_settlement_toponym(lon, lat)

    return {
        "inside_official_basin": True,
        "official_basin": basin,
        "delineation_supported": not karst,
        "karst_detected": karst,
        "mode": "official_direct" if basin.get("direct_official") else "dem",
        "official_river": river,
        "toponym": toponym,
        "snap_preview": snap_preview,
        "warning": None if not karst else {
            "code": "karst_detected",
            "title": KARST_WARNING_TITLE,
            "subtitle": KARST_WARNING_SUBTITLE,
            "message": KARST_WARNING_MESSAGE,
        },
    }

@app.get("/api/map-assets/{asset_key}")
def map_asset(asset_key: str):
    assets = {
        "official-basins": "official_basins.geojson",
        "official-rivers-z6-8": "official_rivers_z6_8.geojson",
        "official-rivers-z8-10": "official_rivers_z8_10.geojson",
        "official-rivers-z10-11": "official_rivers_z10_11.geojson",
        "official-rivers-z11-12": "official_rivers_z11_12.geojson",
        "official-rivers-z12-14": "official_rivers_z12_14.geojson",
        "official-rivers": "official_rivers.geojson",
    }
    filename = assets.get(asset_key)
    if not filename:
        raise HTTPException(status_code=404, detail="Map asset tidak ditemukan.")

    if MAP_ASSETS_PUBLIC_BASE:
        suffix = f"?v={urllib.parse.quote(MAP_ASSETS_VERSION)}" if MAP_ASSETS_VERSION else ""
        return RedirectResponse(
            f"{MAP_ASSETS_PUBLIC_BASE}/{filename}{suffix}",
            status_code=307,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    local_path = STATIC_DIR / "data" / filename
    if not local_path.exists():
        cache_dir = ROOT_DIR / ".cache" / "runtime-map-assets"
        cache_dir.mkdir(parents=True, exist_ok=True)
        local_path = cache_dir / filename
        if asset_key == "official-basins":
            frame = official_basins.copy().to_crs(CRS_WEB)
        else:
            frame = official_rivers.copy()
            name_col = "river_name" if "river_name" in frame.columns else ("NAMOBJ" if "NAMOBJ" in frame.columns else None)
            if name_col:
                frame["river_label"] = frame[name_col].map(_river_map_label)
            tier = RIVER_DISPLAY_TIER_BY_FILENAME.get(filename)
            frame = build_river_display_gdf(frame, tier) if tier is not None else frame.to_crs(CRS_WEB)
        local_path.write_text(frame.to_json(drop_id=True), encoding="utf-8")
    return FileResponse(
        local_path,
        media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/basin-labels")
def basin_labels():
    return _build_basin_label_fc()


@app.get("/api/geocode")
def geocode(q: str = Query(..., min_length=2, max_length=160)):
    """Search locations using OpenStreetMap/Nominatim only.

    The local toponym database is intentionally reserved for automatic DTA point
    naming and is not exposed in the search bar.
    """
    text = " ".join(q.strip().split())
    if len(text) < 2:
        raise HTTPException(status_code=400, detail="Kata pencarian terlalu pendek.")
    try:
        osm_results = list(_nominatim_search_cached(text))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "query": text,
        "results": osm_results[:5],
        "sources": {"openstreetmap": len(osm_results)},
    }

@app.post("/api/delineate-multi")
def delineate_multi(req: MultiDelineateRequest, request: Request):
    if len({p.point_id for p in req.points}) != len(req.points):
        raise HTTPException(status_code=400, detail="point_id harus unik.")
    token = _register_delineation_request(request)
    try:
        with _heavy_job_context() as ticket:
            LATEST_REQUESTS.ensure_current(token)
            _trim_geometry_caches_if_needed()
            results: list[dict[str, Any]] = []
            upstream_sets: list[set[int]] = []
            for p in req.points:
                result, upstream = build_point_result(
                    p,
                    req.snap_radius_m,
                    req.boundary_match_m,
                    req.paek_tolerance_m,
                    req.vw_tolerance_m,
                    cancel_check=lambda: LATEST_REQUESTS.ensure_current(token),
                )
                results.append(result)
                upstream_sets.append(upstream)
            LATEST_REQUESTS.ensure_current(token)
            reconcile_final_geometries(results, upstream_sets)
            apply_incremental_geometries(results, upstream_sets)
            LATEST_REQUESTS.ensure_current(token)
            return {
                "results": results,
                "network_analysis": analyze_point_network(results, upstream_sets),
                "performance": {"queue_ms": round(ticket.queue_ms, 1)},
            }
    except (HeavyJobQueueFull, SupersededRequest) as exc:
        raise _performance_http_error(exc) from exc


@app.post("/api/reconcile-results")
def reconcile_results(req: CachedResultsRequest, request: Request):
    """Refresh topology + incremental hatches from cached DTA polygons only.

    This endpoint deliberately does not run stream snapping, raster D8 tracing, smoothing,
    or boundary stitching. If reconciliation changes a final polygon, only its derived
    characterization is refreshed. It is used after deleting/restoring a point so
    unaffected DTA results do not need to be delineated again.
    """
    token = _register_delineation_request(request)
    try:
        with _heavy_job_context() as ticket:
            LATEST_REQUESTS.ensure_current(token)
            results = [dict(r) for r in req.results]
            ids = [str(r.get("point_id") or "") for r in results]
            if any(not x for x in ids) or len(set(ids)) != len(ids):
                raise HTTPException(status_code=400, detail="Cached point_id harus unik dan tidak kosong.")
            upstream_sets = []
            for result in results:
                link = result.get("outlet_linkno")
                upstream_sets.append(set(collect_upstream_ids(int(link))) if link is not None else set())
            LATEST_REQUESTS.ensure_current(token)
            reconcile_final_geometries(results, upstream_sets)
            apply_incremental_geometries(results, upstream_sets)
            return {
                "results": results,
                "network_analysis": analyze_point_network(results, upstream_sets),
                "performance": {"queue_ms": round(ticket.queue_ms, 1)},
            }
    except (HeavyJobQueueFull, SupersededRequest) as exc:
        raise _performance_http_error(exc) from exc


@app.post("/api/delineate")
def delineate(req: DelineateRequest, request: Request):
    p = OutletPoint(point_id="O1", lon=req.lon, lat=req.lat, source="api")
    token = _register_delineation_request(request)
    try:
        with _heavy_job_context() as ticket:
            _trim_geometry_caches_if_needed()
            result, _ = build_point_result(
                p,
                req.snap_radius_m,
                req.boundary_match_m,
                req.paek_tolerance_m,
                req.vw_tolerance_m,
                cancel_check=lambda: LATEST_REQUESTS.ensure_current(token),
            )
            result.setdefault("processing", {})["queue_ms"] = round(ticket.queue_ms, 1)
            return result
    except (HeavyJobQueueFull, SupersededRequest) as exc:
        raise _performance_http_error(exc) from exc


@app.get("/api/dta/{linkno}")
@app.get("/api/watershed/{linkno}")
def watershed_by_linkno(
    linkno: int,
    boundary_match_m: float = 90.0,
    paek_tolerance_m: float = DEFAULT_PAEK_TOLERANCE_M,
    vw_tolerance_m: float = DEFAULT_VW_TOLERANCE_M,
):
    if linkno not in link_to_stream_pos:
        raise HTTPException(status_code=404, detail=f"LINKNO {linkno} tidak ditemukan.")
    if linkno not in subbasins_by_id.index:
        raise HTTPException(status_code=404, detail=f"LINKNO {linkno} tidak memiliki subbasin.")

    pos = link_to_stream_pos[linkno]
    row = streams.iloc[pos]
    snapped = Point(float(row["outlet_x"]), float(row["outlet_y"]))
    outlet_web = transform(to_web.transform, snapped)
    p = OutletPoint(
        point_id="O1",
        lon=float(outlet_web.x),
        lat=float(outlet_web.y),
        source="linkno",
        label=f"LINKNO {linkno}",
    )
    try:
        with _heavy_job_context() as ticket:
            _trim_geometry_caches_if_needed()
            result, _ = build_point_result(
                p, 20000.0, float(boundary_match_m), float(paek_tolerance_m),
                float(vw_tolerance_m), forced_linkno=linkno
            )
            result.setdefault("processing", {})["queue_ms"] = round(ticket.queue_ms, 1)
            return result
    except HeavyJobQueueFull as exc:
        raise _performance_http_error(exc) from exc


def _selected_geometry_projected(result: dict[str, Any], geometry_mode: str):
    geom_web = result["dta_raw_geojson"] if geometry_mode == "raw" else result["dta_geojson"]
    return transform(to_data.transform, shape(geom_web))


def _sanitize_component(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"^K\.\s*", "K_", text, flags=re.IGNORECASE)
    text = re.sub(r"^S\.\s*", "K_", text, flags=re.IGNORECASE)
    text = text.replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^0-9A-Za-zÀ-ÿ_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


_BULAN_SINGKAT_ID = (
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
)


def _dta_export_source(processed_at: datetime) -> str:
    """Build the fixed DTA source/copyright attribute in Indonesian local time."""
    local_dt = processed_at.astimezone(ZoneInfo("Asia/Jakarta"))
    bulan = _BULAN_SINGKAT_ID[local_dt.month - 1]
    return (
        f"© {local_dt.year} Unit Hidrologi dan Kualitas Air BBWS Serayu Opak "
        f"diproses {local_dt.day} {bulan} {local_dt.year} {local_dt:%H:%M}"
    )


def _result_frames_for_point(
    point: OutletPoint,
    result: dict[str, Any],
    geometry_mode: str,
    dta_source: str,
):
    geom_native = _selected_geometry_projected(result, geometry_mode)
    geom = to_export_geom(geom_native)
    river_name = (result.get("official_river") or {}).get("name")
    basin_name = (result.get("official_basin") or result.get("requested_official_basin") or {}).get("name")
    label = point.label or point.point_id
    # Characterization describes the final/smoothed DTA. Do not attach those values to a
    # separately exported raw boundary because that would imply false geometric agreement.
    analysis = (result.get("hydrologic_analysis") or {}) if geometry_mode == "smoothed" else {}
    morphometry = analysis.get("morphometry") or {}
    terrain = analysis.get("terrain") or {}
    drainage = analysis.get("drainage") or {}
    landcover = analysis.get("landcover") or {}
    curve_number = analysis.get("curve_number") or {}
    concentration = analysis.get("time_of_concentration") or {}
    elevation = terrain.get("elevation") or {}
    slope = terrain.get("slope") or {}
    dta = gpd.GeoDataFrame(
        [{
            "ID": point.point_id,
            "NAMA": label,
            "LUAS_KM2": area_km2_equal(geom_native),
            "DAS": basin_name,
            "SUNGAI": river_name,
            "RESPON": (analysis.get("executive_summary") or {}).get("response_class"),
            "KELILING_KM": morphometry.get("perimeter_km"),
            "FORM_FACTOR": morphometry.get("form_factor"),
            "ELONG_RATIO": morphometry.get("elongation_ratio"),
            "CIRC_RATIO": morphometry.get("circularity_ratio"),
            "RELIEF_M": elevation.get("relief_m"),
            "SLOPE_MEAN": slope.get("mean_pct"),
            "DRAIN_DENS": drainage.get("drainage_density_km_per_km2"),
            "CN2": curve_number.get("weighted_cn_ii"),
            "RETEN_MM": curve_number.get("potential_retention_mm"),
            "TC_JAM": concentration.get("representative_hours") or concentration.get("recommended_hours"),
            "PL_HUTAN": (landcover.get("summary") or {}).get("forest_pct"),
            "PL_TANI": (landcover.get("summary") or {}).get("agriculture_pct"),
            "FLOWPATH_KM": terrain.get("longest_flow_path_km") or drainage.get("main_channel_length_km"),
            "SUMBER": dta_source,
            "geometry": geom,
        }],
        geometry="geometry",
        crs=CRS_EXPORT,
    )
    ox_native, oy_native = to_data.transform(point.lon, point.lat)
    outlet_geom = to_export_geom(Point(ox_native, oy_native))
    outlet = gpd.GeoDataFrame(
        [{
            "ID": point.point_id,
            "NAMA": label,
            "DAS": basin_name,
            "SUNGAI": river_name,
            "LINTANG": float(point.lat),
            "BUJUR": float(point.lon),
            "geometry": outlet_geom,
        }],
        geometry="geometry",
        crs=CRS_EXPORT,
    )
    return dta, outlet, geom


def _ensure_original_river_index():
    global official_rivers_original, official_river_original_geometries, official_river_original_tree
    if official_river_original_tree is not None and official_rivers_original is not None:
        return official_rivers_original, official_river_original_tree
    with _ORIGINAL_RIVER_LOCK:
        if official_river_original_tree is None or official_rivers_original is None:
            frame = ensure_official_rivers_original(RUNTIME_DATA)
            if frame.crs is None:
                raise RuntimeError("CRS is missing from original river layer.")
            if frame.crs != streams.crs:
                frame = frame.to_crs(streams.crs)
            official_rivers_original = frame
            official_river_original_geometries = list(frame.geometry.values)
            official_river_original_tree = STRtree(official_river_original_geometries)
    return official_rivers_original, official_river_original_tree


def _clip_original_rivers(geom_export):
    rivers_frame, rivers_tree = _ensure_original_river_index()
    # Spatial index is in the native processing CRS; convert the selected export geometry back when needed.
    if str(streams.crs).upper() == CRS_EXPORT:
        geom_native = geom_export
    else:
        back = Transformer.from_crs(CRS_EXPORT, streams.crs, always_xy=True)
        geom_native = transform(back.transform, geom_export)
    idxs = rivers_tree.query(geom_native, predicate="intersects")
    if len(idxs) == 0:
        return gpd.GeoDataFrame(
            columns=[c for c in rivers_frame.columns],
            geometry="geometry",
            crs=CRS_EXPORT,
        )
    rr = rivers_frame.iloc[[int(i) for i in idxs]].copy()
    rr["geometry"] = rr.geometry.intersection(geom_native)
    rr = rr[~rr.geometry.is_empty].copy()
    # Pertahankan struktur atribut asli SHP; hanya geometri yang di-clip.
    rr = rr[[c for c in rivers_frame.columns if c in rr.columns]]
    rr = rr.to_crs(CRS_EXPORT) if str(rr.crs).upper() != CRS_EXPORT else rr
    return gpd.GeoDataFrame(rr, geometry="geometry", crs=CRS_EXPORT)


def _write_geojson(gdf: gpd.GeoDataFrame, path: Path):
    path.write_text(gdf.to_crs(CRS_WEB).to_json(drop_id=True), encoding="utf-8")


def _geom_to_kml_coords(geom):
    return " ".join(f"{x:.8f},{y:.8f},0" for x, y, *_ in geom.coords)


def _kml_for_gdf(gdf: gpd.GeoDataFrame, name: str) -> str:
    from xml.sax.saxutils import escape
    g = gdf.to_crs(CRS_WEB)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f'<name>{escape(name)}</name>',
    ]
    for _, row in g.iterrows():
        geom = row.geometry
        label = escape(str(
            row.get("NAMA") or row.get("NAMOBJ") or row.get("river_name") or
            row.get("ID") or row.get("OBJECTID") or name
        ))
        geoms = list(geom.geoms) if geom.geom_type.startswith("Multi") or geom.geom_type == "GeometryCollection" else [geom]
        for gg in geoms:
            if gg.is_empty:
                continue
            parts.append(f'<Placemark><name>{label}</name>')
            source_value = row.get("SUMBER")
            if source_value is not None and str(source_value).strip():
                parts.append(
                    '<ExtendedData><Data name="SUMBER"><value>'
                    + escape(str(source_value))
                    + '</value></Data></ExtendedData>'
                )
            if gg.geom_type == 'Point':
                parts.append(f'<Point><coordinates>{gg.x:.8f},{gg.y:.8f},0</coordinates></Point>')
            elif gg.geom_type == 'LineString':
                parts.append(f'<LineString><tessellate>1</tessellate><coordinates>{_geom_to_kml_coords(gg)}</coordinates></LineString>')
            elif gg.geom_type == 'Polygon':
                parts.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>' + _geom_to_kml_coords(gg.exterior) + '</coordinates></LinearRing></outerBoundaryIs>')
                for ring in gg.interiors:
                    parts.append('<innerBoundaryIs><LinearRing><coordinates>' + _geom_to_kml_coords(ring) + '</coordinates></LinearRing></innerBoundaryIs>')
                parts.append('</Polygon>')
            parts.append('</Placemark>')
    parts.append('</Document></kml>')
    return ''.join(parts)


def _write_shapefile(gdf: gpd.GeoDataFrame, path: Path):
    gdf.to_file(path, driver="ESRI Shapefile", encoding="UTF-8")


def _write_vector_by_format(gdf: gpd.GeoDataFrame, path: Path, fmt: str, name: str):
    if fmt == "geojson":
        _write_geojson(gdf, path)
    elif fmt == "shp":
        _write_shapefile(gdf, path)
    elif fmt == "kml":
        path.write_text(_kml_for_gdf(gdf, name), encoding="utf-8")
    else:
        raise ValueError(fmt)


@app.post("/api/characteristics")
def characteristics_analysis(req: CharacteristicAnalysisRequest):
    try:
        return _compute_hydrologic_analysis_for_result(dict(req.point_result), decimal_separator=req.decimal_separator)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hss")
def hss_analysis(req: HssRequest):
    try:
        return calculate_hss(
            point_id=req.point_id,
            label=req.label,
            hydrologic_analysis=req.hydrologic_analysis,
            methods=req.methods,
            parameters=req.parameters,
            input_overrides=req.input_overrides,
            global_tr_hours=req.global_tr_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/download")
def download(req: DownloadRequest):
    try:
        with _heavy_job_context():
            _trim_geometry_caches_if_needed()
            return _download_impl(req)
    except HeavyJobQueueFull as exc:
        raise _performance_http_error(exc) from exc


def _download_impl(req: DownloadRequest):
    allowed_formats = {"gpkg", "shp", "geojson", "kml"}
    formats: list[str] = []
    for f in req.formats:
        key = f.lower().strip()
        if key in allowed_formats and key not in formats:
            formats.append(key)
    if not formats:
        raise HTTPException(status_code=400, detail="Pilih minimal satu format unduhan.")

    modes: list[str] = []
    for mode in req.geometry_modes:
        key = str(mode).lower().strip()
        if key in {"smoothed", "raw"} and key not in modes:
            modes.append(key)
    if not modes:
        raise HTTPException(status_code=400, detail="Pilih Diperhalus, Asli, atau keduanya.")

    td = Path(tempfile.mkdtemp(prefix="delineasi_dta_"))
    jakarta_now = datetime.now(ZoneInfo("Asia/Jakarta"))
    dta_source = _dta_export_source(jakarta_now)
    stamp = jakarta_now.strftime("%Y%m%d%H%M")
    root_name = f"Delineasi_DTA_{stamp}"
    root_dir = td / root_name
    root_dir.mkdir(parents=True, exist_ok=True)
    package = td / f"{root_name}.zip"

    try:
        # Build the requested set once, then apply the same multi-DTA topology
        # reconciliation used by the map. This keeps downloaded Diperhalus geometry
        # consistent with the geometry seen on screen.
        built_results: list[dict[str, Any]] = []
        upstream_sets: list[set[int]] = []
        for point in req.points:
            result, upstream = build_point_result(
                point,
                req.snap_radius_m,
                req.boundary_match_m,
                DEFAULT_PAEK_TOLERANCE_M,
                DEFAULT_VW_TOLERANCE_M,
            )
            built_results.append(result)
            upstream_sets.append(upstream)
        reconcile_final_geometries(built_results, upstream_sets)
        apply_incremental_geometries(built_results, upstream_sets)

        for point, result in zip(req.points, built_results):
            river_name = (result.get("official_river") or {}).get("name") or "Tanpa Nama Sungai"
            point_name = point.label or point.point_id
            river_part = _sanitize_component(river_name, "Tanpa_Nama_Sungai")
            point_part = _sanitize_component(point_name, point.point_id)
            base_name = f"{river_part}_{point_part}"
            point_dir = root_dir / base_name
            point_dir.mkdir(parents=True, exist_ok=True)

            frames: dict[str, tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, Any]] = {}
            for mode in modes:
                frames[mode] = _result_frames_for_point(point, result, mode, dta_source)

            clip_mode = "smoothed" if "smoothed" in modes else "raw"
            rivers = _clip_original_rivers(frames[clip_mode][2]) if req.include_rivers else None
            outlet = frames[clip_mode][1]

            if "gpkg" in formats:
                gpkg_path = point_dir / f"DTA_{base_name}.gpkg"
                first = True
                for mode in modes:
                    layer_name = "DTA_Diperhalus" if mode == "smoothed" else "DTA_Asli"
                    frames[mode][0].to_file(gpkg_path, layer=layer_name, driver="GPKG", mode="w" if first else "a")
                    first = False
                outlet.to_file(gpkg_path, layer="Outlet", driver="GPKG", mode="a")
                if req.include_rivers and rivers is not None and len(rivers):
                    rivers.to_file(gpkg_path, layer="Sungai", driver="GPKG", mode="a")

            for fmt in [f for f in formats if f != "gpkg"]:
                ext = {"geojson": ".geojson", "shp": ".shp", "kml": ".kml"}[fmt]
                for mode in modes:
                    suffix = "" if mode == "smoothed" else "_asli"
                    dta_path = point_dir / f"DTA_{base_name}{suffix}{ext}"
                    _write_vector_by_format(frames[mode][0], dta_path, fmt, f"DTA {base_name}{suffix}")
                outlet_path = point_dir / f"Outlet_{base_name}{ext}"
                _write_vector_by_format(outlet, outlet_path, fmt, f"Outlet {base_name}")
                if req.include_rivers and rivers is not None and len(rivers):
                    river_path = point_dir / f"Sungai_{base_name}{ext}"
                    _write_vector_by_format(rivers, river_path, fmt, f"Sungai {base_name}")

            if req.include_analysis_report:
                if not result.get("hydrologic_analysis"):
                    result["hydrologic_analysis"] = _compute_hydrologic_analysis_for_result(result, decimal_separator=req.decimal_separator)
                report_result = dict(result)
                report_result["label"] = f"{river_name} – {point_name}"
                create_characteristics_report(
                    [report_result],
                    point_dir / f"Laporan_Karakteristik_{base_name}.pdf",
                    language="id",
                    decimal_separator=req.decimal_separator,
                )
                create_characteristics_workbook(
                    [report_result],
                    point_dir / f"Karakteristik_{base_name}.xlsx",
                )

            if req.include_hss:
                hss_payload = req.hss_results.get(point.point_id)
                if hss_payload and any(method.get("available") for method in (hss_payload.get("methods") or [])):
                    create_hss_workbook(
                        hss_payload,
                        point_dir / f"HSS_{base_name}.xlsx",
                    )
                    create_hss_report(
                        hss_payload,
                        point_dir / f"HSS_{base_name}.pdf",
                    )

        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in root_dir.rglob("*"):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(td))
        payload = package.read_bytes()
    finally:
        shutil.rmtree(td, ignore_errors=True)

    filename = f"{root_name}.zip"
    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "data_backend": DATA_BACKEND,
        "active_dataset": ACTIVE_DATASET_ID,
        "hybrid_raster": bool(HYBRID_RASTER_AVAILABLE),
    }
