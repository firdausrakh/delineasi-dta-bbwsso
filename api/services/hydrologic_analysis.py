"""Physical and hydrologic characterization for a delineated DTA.

The module intentionally treats DEM-derived values as optional. Geometry and
stream-network metrics are still returned when ``data/shared/dem.tif`` or
``data/shared/plen.tif`` have not been installed yet.
"""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform
from pyproj import Transformer


SLOPE_CLASSES = (
    ("Datar", 0.0, 8.0),
    ("Landai", 8.0, 15.0),
    ("Agak curam", 15.0, 25.0),
    ("Curam", 25.0, 40.0),
    ("Sangat curam", 40.0, math.inf),
)

LANDCOVER_LABELS = {
    2001: "Hutan lahan kering primer", 2002: "Hutan lahan kering sekunder",
    2005: "Hutan rawa primer", 20051: "Hutan rawa sekunder",
    2004: "Hutan mangrove primer", 20041: "Hutan mangrove sekunder",
    2007: "Semak belukar", 20071: "Semak belukar rawa", 3000: "Savana",
    2006: "Hutan tanaman industri", 2010: "Perkebunan",
    20091: "Pertanian lahan kering", 20092: "Pertanian lahan kering bercampur semak",
    20122: "Transmigrasi", 6009: "Transmigrasi", 20093: "Sawah", 20094: "Tambak",
    2014: "Tanah terbuka", 20141: "Pertambangan", 2012: "Permukiman",
    5001: "Tubuh air", 20121: "Pelabuhan udara/laut", 5011: "Rawa", 50011: "Rawa",
}
FOREST_CODES = {2001, 2002, 2005, 20051, 2004, 20041, 2006}
_ANALYSIS_STREAMS: dict[str, gpd.GeoDataFrame] = {}
_ANALYSIS_STREAMS_LOCK = threading.Lock()
_LANDSYSTEMS: dict[str, gpd.GeoDataFrame] = {}
_LANDSYSTEMS_LOCK = threading.Lock()

PHYSIOGRAPHY_ID = {
    "Hills": "perbukitan", "Mountains": "pegunungan", "Plains": "dataran",
    "Alluvial Plains": "dataran aluvial", "Alluvial Valleys": "lembah aluvial",
    "Beaches": "pantai", "Fans and Lahars": "kipas aluvial dan lahar",
    "Terraces": "teras", "Tidal Swamps": "rawa pasang surut",
}
RELIEF_ID = {
    "Flat": "datar", "Undulating": "bergelombang", "Rolling": "berombak",
    "Hilly": "berbukit", "Hillocky": "berbukit kecil", "Mountainous": "bergunung",
}
LAND_TYPE_ID = {
    "Asymmetric non-orientated ridges on mixed sedimentary rocks": "punggungan asimetris pada batuan sedimen campuran",
    "Young intermediate/basaltic stratovolcanoes": "stratovolkano muda berbatuan intermediat hingga basaltik",
    "Irregular mountain ridges on intermediate/basaltic volcanics": "punggungan pegunungan tidak beraturan pada batuan vulkanik intermediat hingga basaltik",
    "Coalescent estuarine/riverine plains": "dataran estuari dan sungai yang menyatu",
    "Tilted plateaus with conical karst hillocks in dry areas": "plato miring dengan bukit-bukit karst kerucut di wilayah kering",
    "Minor river floodplains within hills": "dataran banjir sungai kecil di kawasan perbukitan",
    "Very steep ridges on tuffaceous sediments": "punggungan sangat curam pada sedimen tufaan",
    "Very steep ridges on basaltic volcanics": "punggungan sangat curam pada batuan vulkanik basaltik",
    "Coral islands and reefs": "pulau dan terumbu karang",
    "Low rounded hills on marls and claystones": "perbukitan rendah membulat pada napal dan batulempung",
    "Hillocks plains on marls, limestones and sandstones in dry areas": "dataran berbukit kecil pada napal, batugamping, dan batupasir di wilayah kering",
    "Rolling plains with hillocks on marls": "dataran berombak dengan bukit kecil pada napal",
    "Long narrow steep-sided ridges on sandstones": "punggungan panjang dan sempit berlereng curam pada batupasir",
    "Coastal beach ridges and swales": "punggungan pantai dan cekungan antarpunggungan",
    "Deeply eroded mountainous stratovolcanoes on intermediate/basic volcanics": "stratovolkano bergunung yang tererosi kuat pada batuan vulkanik intermediat hingga basa",
    "Moderately dissected intermediate/basic lava flows": "aliran lava intermediat hingga basa yang terdiseksi sedang",
    "Moderately dissected tilted plateaus on limestones in dry areas": "plato batugamping miring yang terdiseksi sedang di wilayah kering",
    "Long mountain ridges on marls with rock outcrops": "punggungan pegunungan panjang pada napal dengan singkapan batuan",
    "Flat to undulating volcanic plains": "dataran vulkanik datar hingga bergelombang",
    "Asymmetric broadly dissected ridges on sandstones and mudstones": "punggungan asimetris yang terdiseksi luas pada batupasir dan batulumpur",
    "Moderately steep hills on basaltic volcanics": "perbukitan agak curam pada batuan vulkanik basaltik",
    "Flat to undulating karstic plains with hums": "dataran karst datar hingga bergelombang dengan bukit sisa",
    "Hillocky plains on mixed sedimentary rocks": "dataran berbukit kecil pada batuan sedimen campuran",
    "Moderately steep and dissected lahar slopes": "lereng lahar agak curam dan terdiseksi",
    "Undulating to rolling basic volcanic plains": "dataran vulkanik basa bergelombang hingga berombak",
    "Asymmetric non-orientated sedimentary ridges": "punggungan sedimen asimetris tanpa orientasi tertentu",
    "Braided river floodplains": "dataran banjir sungai berjalin",
    "Dissected intermediate/basaltic volcanic cones": "kerucut vulkanik intermediat hingga basaltik yang terdiseksi",
    "Extremely steep volcanic cones or plugs": "kerucut atau sumbat vulkanik yang sangat curam",
    "Flat to undulating acid volcanic tuff plains": "dataran tuf vulkanik asam yang datar hingga bergelombang",
    "Gently lahar slopes with rounded basalt hillocks": "lereng lahar landai dengan bukit kecil basalt membulat",
    "Gently sloping non-volcanic alluvial fans": "kipas aluvial nonvulkanik berlereng landai",
    "Gently sloping volcanic alluvial fans": "kipas aluvial vulkanik berlereng landai",
    "Hillocks and hills on turbidite (mixed marine) sediments": "bukit kecil dan perbukitan pada sedimen turbidit laut campuran",
    "Hillocky basic/intermediate lava flows": "aliran lava basa hingga intermediat yang berbukit kecil",
    "Hillocky karstic plains": "dataran karst berbukit kecil",
    "Hillocky plains on intermediate/basic volcanic rocks in highland areas": "dataran berbukit kecil pada batuan vulkanik intermediat hingga basa di dataran tinggi",
    "Hillocky plains on tuffaceous sediments": "dataran berbukit kecil pada sedimen tufaan",
    "Inland volcanic alluvial plains": "dataran aluvial vulkanik pedalaman",
    "Intertidal swamps under halophytic vegetation": "rawa pasang surut dengan vegetasi halofit",
    "Linear dissected mountain ridges over igneous rocks": "punggungan pegunungan linier terdiseksi pada batuan beku",
    "Linear sedimentary ridge systems with steep dipslopes": "sistem punggungan sedimen linier dengan lereng kemiringan lapisan yang curam",
    "Low karstic hills on limestones and marls": "perbukitan karst rendah pada batugamping dan napal",
    "Low, broad and flat riverine terraces": "teras sungai rendah, lebar, dan datar",
    "Moderately dissected tilted plateaus on limestone": "plato batugamping miring yang terdiseksi sedang",
    "Moderately sloping recent lahars": "lahar muda berlereng sedang",
    "Moderately sloping volcanic alluvial fans": "kipas aluvial vulkanik berlereng sedang",
    "Moderately sloping volcanic alluvial fans in highland areas": "kipas aluvial vulkanik berlereng sedang di dataran tinggi",
    "Mountainous sandstone cuestas with dissected dipslopes": "kuesta batupasir bergunung dengan lereng kemiringan lapisan terdiseksi",
    "Partly dissected alluvial fans of inland alluvial plains": "kipas aluvial yang terdiseksi sebagian pada dataran aluvial pedalaman",
    "Raised tilted hillocky karstic terraces in dry areas": "teras karst terangkat dan miring yang berbukit kecil di wilayah kering",
    "Rugged karst ridges and mountains": "punggungan dan pegunungan karst yang terjal",
    "Slightly dissected coalescent volcanic alluvial fans": "kipas aluvial vulkanik menyatu yang sedikit terdiseksi",
    "Slightly dissected lacustrine plains": "dataran lakustrin yang sedikit terdiseksi",
    "Steep hills on marls with rock outcrops": "perbukitan curam pada napal dengan singkapan batuan",
    "Strongly dissected tilted plateaus on tuffaceous sediments": "plato miring yang terdiseksi kuat pada sedimen tufaan",
    "Undulating intermediate/basic volcanic plains in highland areas": "dataran vulkanik intermediat hingga basa yang bergelombang di dataran tinggi",
    "Undulating karstic plains": "dataran karst bergelombang",
    "Undulating plains on calcareous tuffs in dry areas": "dataran bergelombang pada tuf gampingan di wilayah kering",
    "Undulating plains on marls and limestones": "dataran bergelombang pada napal dan batugamping",
    "Undulating to rolling riverine terraces in dry areas": "teras sungai bergelombang hingga berombak di wilayah kering",
    "Undulating tuffaceous sedimentary plains": "dataran sedimen tufaan bergelombang",
    "Very steep karstic ridges on limestone": "punggungan karst sangat curam pada batugamping",
}


def _translated_land_attribute(value: Any, mapping: dict[str, str], fallback: str) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return fallback
    return mapping.get(text, text[:1].lower() + text[1:])


def optional_spatial_path(root_dir: Path, env_name: str, filename: str) -> Path | None:
    configured = os.getenv(env_name, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
    else:
        local_root = Path(os.getenv("LOCAL_DATA_DIR", "").strip() or (root_dir / "data"))
        candidate = local_root / "shared" / filename
    return candidate if candidate.is_file() else None


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _narrative_number(value: Any, digits: int, decimal_separator: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    text = f"{number:.{digits}f}"
    return text.replace(".", ",") if decimal_separator == "," else text


def _natural_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " dan " + items[-1]


def _metric_geometry(geom, source_crs: Any):
    if str(source_crs).upper() == "EPSG:32749":
        return geom
    transformer = Transformer.from_crs(source_crs, "EPSG:32749", always_xy=True)
    return transform(transformer.transform, geom)


def _window_for_geometry(dataset, geom) -> Window | None:
    left, bottom, right, top = geom.bounds
    left = max(left, dataset.bounds.left)
    bottom = max(bottom, dataset.bounds.bottom)
    right = min(right, dataset.bounds.right)
    top = min(top, dataset.bounds.top)
    if left >= right or bottom >= top:
        return None
    window = from_bounds(left, bottom, right, top, dataset.transform).round_offsets().round_lengths()
    return window.intersection(Window(0, 0, dataset.width, dataset.height))


def _masked_raster(path: Path, geom, source_crs: Any, *, max_cells: int = 2_000_000,
                   resampling: Resampling = Resampling.bilinear):
    """Read a bounded raster sample.

    This helper remains for lightweight diagnostics/fallbacks. Hydrologic terrain, land-cover,
    and CN statistics below use native-resolution tiled readers so their reported values are not
    changed by display-oriented resampling.
    """
    with rasterio.open(path) as ds:
        raster_geom = geom
        if source_crs and ds.crs and str(source_crs) != str(ds.crs):
            transformer = Transformer.from_crs(source_crs, ds.crs, always_xy=True)
            raster_geom = transform(transformer.transform, geom)
        window = _window_for_geometry(ds, raster_geom)
        if window is None or window.width <= 0 or window.height <= 0:
            return None
        scale = max(1.0, math.sqrt((window.width * window.height) / max_cells))
        out_h = max(1, int(math.ceil(window.height / scale)))
        out_w = max(1, int(math.ceil(window.width / scale)))
        data = ds.read(1, window=window, out_shape=(out_h, out_w), resampling=resampling)
        src_transform = ds.window_transform(window)
        out_transform = src_transform * src_transform.scale(window.width / out_w, window.height / out_h)
        inside = rio_features.geometry_mask(
            [mapping(raster_geom)], out_shape=(out_h, out_w), transform=out_transform, invert=True
        )
        valid = inside & np.isfinite(data)
        if ds.nodata is not None:
            valid &= ~np.isclose(data, ds.nodata)
        if not np.any(valid):
            return None
        return data.astype("float64", copy=False), valid, out_transform, float(scale)


def _geometry_for_dataset(geom, source_crs: Any, dataset):
    if source_crs and dataset.crs and str(source_crs) != str(dataset.crs):
        transformer = Transformer.from_crs(source_crs, dataset.crs, always_xy=True)
        return transform(transformer.transform, geom)
    return geom


def _iter_tile_windows(window: Window, tile_size: int = 768):
    row0 = int(window.row_off)
    col0 = int(window.col_off)
    row1 = int(math.ceil(window.row_off + window.height))
    col1 = int(math.ceil(window.col_off + window.width))
    for row in range(row0, row1, tile_size):
        height = min(tile_size, row1 - row)
        for col in range(col0, col1, tile_size):
            width = min(tile_size, col1 - col)
            yield Window(col, row, width, height)


def _valid_raster_values(data: np.ndarray, nodata: float | int | None) -> np.ndarray:
    valid = np.isfinite(data)
    if nodata is not None:
        valid &= ~np.isclose(data, nodata)
    return valid


def _sample_raster(path: Path, x: float, y: float, source_crs: Any) -> float | None:
    try:
        with rasterio.open(path) as ds:
            sx, sy = x, y
            if source_crs and ds.crs and str(source_crs) != str(ds.crs):
                sx, sy = Transformer.from_crs(source_crs, ds.crs, always_xy=True).transform(x, y)
            value = float(next(ds.sample([(sx, sy)]))[0])
            if not math.isfinite(value) or (ds.nodata is not None and math.isclose(value, ds.nodata)):
                return None
            return value
    except (OSError, StopIteration, ValueError):
        return None


def _native_raster_code_counts(path: Path, geom, source_crs: Any) -> tuple[dict[int, int], int] | None:
    """Exact native-resolution categorical histogram inside a DTA polygon."""
    with rasterio.open(path) as ds:
        raster_geom = _geometry_for_dataset(geom, source_crs, ds)
        window = _window_for_geometry(ds, raster_geom)
        if window is None:
            return None
        counts: dict[int, int] = {}
        total = 0
        for tile in _iter_tile_windows(window):
            data = ds.read(1, window=tile)
            inside = rio_features.geometry_mask(
                [mapping(raster_geom)], out_shape=data.shape, transform=ds.window_transform(tile), invert=True
            )
            valid = inside & _valid_raster_values(data, ds.nodata)
            if not np.any(valid):
                continue
            values = data[valid].astype(np.int64, copy=False)
            codes, tile_counts = np.unique(values, return_counts=True)
            for code, count in zip(codes, tile_counts):
                counts[int(code)] = counts.get(int(code), 0) + int(count)
                total += int(count)
        return (counts, total) if total else None


def _native_raster_max(path: Path, geom, source_crs: Any) -> float | None:
    with rasterio.open(path) as ds:
        raster_geom = _geometry_for_dataset(geom, source_crs, ds)
        window = _window_for_geometry(ds, raster_geom)
        if window is None:
            return None
        max_value = None
        for tile in _iter_tile_windows(window):
            data = ds.read(1, window=tile, out_dtype="float64")
            inside = rio_features.geometry_mask(
                [mapping(raster_geom)], out_shape=data.shape, transform=ds.window_transform(tile), invert=True
            )
            valid = inside & _valid_raster_values(data, ds.nodata)
            if np.any(valid):
                tile_max = float(np.max(data[valid]))
                max_value = tile_max if max_value is None else max(max_value, tile_max)
        return max_value


def _hec_hms_terrain_from_dem(geom, outlet, source_crs: Any, dem_path: Path, *, percentile_samples: int = 1_000_000) -> dict[str, Any] | None:
    """Compute original-terrain statistics with the HEC-HMS basin-slope convention.

    HEC-HMS scans all eight neighboring cells, treats orthogonal and diagonal neighbors equally,
    uses the maximum scanned elevation difference for each basin cell, then averages those local
    slopes. This routine follows that convention at native DEM resolution while processing tiles
    with a one-cell halo to keep memory bounded.
    """
    aspect_labels = ("Utara", "Timur Laut", "Timur", "Tenggara", "Selatan", "Barat Daya", "Barat", "Barat Laut")
    aspect_offsets = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))
    slope_counts = [0] * len(SLOPE_CLASSES)
    aspect_counts = [0] * 8
    elev_count = 0
    elev_sum = 0.0
    z_min = math.inf
    z_max = -math.inf
    divide_max = -math.inf
    slope_sum = 0.0
    slope_count = 0
    slope_samples: list[np.ndarray] = []
    samples: list[np.ndarray] = []

    with rasterio.open(dem_path) as ds:
        raster_geom = _geometry_for_dataset(geom, source_crs, ds)
        window = _window_for_geometry(ds, raster_geom)
        if window is None:
            return None
        approx_cells = max(1, int(window.width * window.height))
        sample_stride = max(1, int(math.ceil(approx_cells / percentile_samples)))
        # HEC-HMS explicitly considers all eight neighbors equally. For the square UTM grid used
        # by this application that means one common raster-cell run for every scanned neighbor.
        cell_run = (abs(float(ds.transform.a)) + abs(float(ds.transform.e))) / 2.0
        if cell_run <= 0:
            raise ValueError("Resolusi data ketinggian tidak valid")
        boundary_geom = raster_geom.boundary

        for tile in _iter_tile_windows(window):
            h, w = int(tile.height), int(tile.width)
            halo = Window(int(tile.col_off) - 1, int(tile.row_off) - 1, w + 2, h + 2)
            data_halo = ds.read(1, window=halo, boundless=True, fill_value=np.nan, out_dtype="float64")
            center = data_halo[1:1 + h, 1:1 + w]
            center_valid_raster = _valid_raster_values(center, ds.nodata)
            tile_transform = ds.window_transform(tile)
            inside = rio_features.geometry_mask(
                [mapping(raster_geom)], out_shape=(h, w), transform=tile_transform, invert=True
            )
            center_valid = inside & center_valid_raster
            if not np.any(center_valid):
                continue

            values = center[center_valid]
            elev_count += int(values.size)
            elev_sum += float(values.sum(dtype=np.float64))
            z_min = min(z_min, float(values.min()))
            z_max = max(z_max, float(values.max()))
            sampled = values[::sample_stride]
            if sampled.size:
                samples.append(sampled)

            divide_mask = rio_features.geometry_mask(
                [mapping(boundary_geom)], out_shape=(h, w), transform=tile_transform,
                invert=True, all_touched=True,
            ) & center_valid_raster
            if np.any(divide_mask):
                divide_max = max(divide_max, float(center[divide_mask].max()))

            best_diff = np.full(center.shape, np.nan, dtype="float64")
            best_drop = np.full(center.shape, -np.inf, dtype="float64")
            best_dir = np.full(center.shape, -1, dtype=np.int8)
            for direction_index, (dr, dc) in enumerate(aspect_offsets):
                neighbor = data_halo[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
                neighbor_valid = _valid_raster_values(neighbor, ds.nodata)
                diff = np.where(neighbor_valid, np.abs(neighbor - center), np.nan)
                best_diff = np.fmax(best_diff, diff)
                drop = center - neighbor
                replace = center_valid & neighbor_valid & (drop > 0) & (drop > best_drop)
                best_drop[replace] = drop[replace]
                best_dir[replace] = direction_index

            slope_pct = best_diff / cell_run * 100.0
            slope_valid = center_valid & np.isfinite(slope_pct)
            if np.any(slope_valid):
                slope_values = slope_pct[slope_valid]
                slope_sum += float(slope_values.sum(dtype=np.float64))
                slope_count += int(slope_values.size)
                sampled_slopes = slope_values[::sample_stride]
                if sampled_slopes.size:
                    slope_samples.append(sampled_slopes)
                for class_index, (_, low, high) in enumerate(SLOPE_CLASSES):
                    slope_counts[class_index] += int(np.count_nonzero((slope_values >= low) & (slope_values < high)))
            for direction_index in range(8):
                aspect_counts[direction_index] += int(np.count_nonzero(center_valid & (best_dir == direction_index)))

        if elev_count == 0:
            return None

        z_mean = elev_sum / elev_count
        outlet_m = _sample_raster(dem_path, outlet.x, outlet.y, source_crs)
        elevation_range = z_max - z_min
        divide_elevation = divide_max if math.isfinite(divide_max) else z_max
        basin_relief = (divide_elevation - outlet_m) if outlet_m is not None else None
        mean_height_above_outlet = (z_mean - outlet_m) if outlet_m is not None else None
        slope_mean = slope_sum / slope_count if slope_count else None
        distribution = [
            {
                "class": label,
                "min_pct": low,
                "max_pct": None if math.isinf(high) else high,
                "area_pct": _round(count / slope_count * 100.0, 1) if slope_count else None,
            }
            for (label, low, high), count in zip(SLOPE_CLASSES, slope_counts)
        ]
        aspect_total = sum(aspect_counts)
        dominant_aspect = aspect_labels[int(np.argmax(aspect_counts))] if aspect_total else None
        percentile_values = np.concatenate(samples) if samples else np.asarray([z_mean])
        slope_percentile_values = np.concatenate(slope_samples) if slope_samples else np.asarray([], dtype=float)
        slope_p95 = float(np.percentile(slope_percentile_values, 95)) if slope_percentile_values.size else None
        hi = (z_mean - z_min) / elevation_range if elevation_range > 0 else 0.0
        hypsometric_stage = "Muda" if hi >= 0.60 else "Dewasa" if hi >= 0.35 else "Tua"
        return {
            "source": dem_path.name,
            "elevation": {
                "min_m": _round(z_min, 1),
                "mean_m": _round(z_mean, 1),
                "max_m": _round(z_max, 1),
                "divide_max_m": _round(divide_elevation, 1),
                "outlet_m": _round(outlet_m, 1),
                "relief_m": _round(basin_relief, 1),
                "elevation_range_m": _round(elevation_range, 1),
                "mean_height_above_outlet_m": _round(mean_height_above_outlet, 1),
            },
            "slope": {
                "mean_pct": _round(slope_mean, 3),
                "mean_ratio": _round(slope_mean / 100.0, 6) if slope_mean is not None else None,
                "p95_pct": _round(slope_p95, 3),
                "distribution": distribution,
                "method": "Beda elevasi terbesar terhadap delapan sel tetangga",
            },
            "aspect": {
                "dominant": dominant_aspect,
                "distribution_pct": {
                    label: _round(count / aspect_total * 100.0, 1) if aspect_total else None
                    for label, count in zip(aspect_labels, aspect_counts)
                },
            },
            "hypsometry": {
                "integral": _round(hi, 3),
                "stage": hypsometric_stage,
                "elevation_percentiles_m": {
                    str(q): _round(float(np.percentile(percentile_values, q)), 1) for q in (10, 25, 50, 75, 90)
                },
                "percentiles_are_sampled": sample_stride > 1,
            },
            "sample_scale": 1.0,
            "native_resolution_m": _round(cell_run, 3),
        }


def _cached_raster_cell(ds, row: int, col: int, cache: dict[tuple[int, int], tuple[np.ndarray, Window]], *, block_size: int = 256) -> float | None:
    if row < 0 or col < 0 or row >= ds.height or col >= ds.width:
        return None
    block_row = row // block_size
    block_col = col // block_size
    key = (block_row, block_col)
    payload = cache.get(key)
    if payload is None:
        window = Window(block_col * block_size, block_row * block_size,
                        min(block_size, ds.width - block_col * block_size),
                        min(block_size, ds.height - block_row * block_size))
        data = ds.read(1, window=window)
        payload = (data, window)
        # A traced path only crosses a small number of blocks. Keep the cache bounded anyway.
        if len(cache) >= 48:
            cache.pop(next(iter(cache)))
        cache[key] = payload
    data, window = payload
    value = float(data[row - int(window.row_off), col - int(window.col_off)])
    if not math.isfinite(value) or (ds.nodata is not None and math.isclose(value, ds.nodata)):
        return None
    return value


def _trace_longest_flowpath(geom, outlet, source_crs: Any, flowdir_path: Path, plen_path: Path) -> tuple[LineString, float] | None:
    """Trace the TauDEM longest-upstream branch from the DTA outlet using D8 topology and plen."""
    # TauDEM coding: E, NE, N, NW, W, SW, S, SE.
    direction_offset = {
        1: (0, 1), 2: (-1, 1), 3: (-1, 0), 4: (-1, -1),
        5: (0, -1), 6: (1, -1), 7: (1, 0), 8: (1, 1),
    }
    with rasterio.open(flowdir_path) as fds, rasterio.open(plen_path) as pds:
        if fds.crs != pds.crs or fds.transform != pds.transform or fds.width != pds.width or fds.height != pds.height:
            raise ValueError("Grid flowdir.tif dan plen.tif tidak identik")
        raster_geom = _geometry_for_dataset(geom, source_crs, fds)
        ox, oy = outlet.x, outlet.y
        if source_crs and fds.crs and str(source_crs) != str(fds.crs):
            ox, oy = Transformer.from_crs(source_crs, fds.crs, always_xy=True).transform(ox, oy)
        outlet_raster = Point(float(ox), float(oy))
        cell_size = (abs(float(fds.transform.a)) + abs(float(fds.transform.e))) / 2.0
        path_domain = raster_geom.buffer(cell_size * 0.8)
        base_row, base_col = fds.index(ox, oy)
        fcache: dict[tuple[int, int], tuple[np.ndarray, Window]] = {}
        pcache: dict[tuple[int, int], tuple[np.ndarray, Window]] = {}

        start_candidates: list[tuple[float, int, int]] = []
        fallback_candidates: list[tuple[float, int, int]] = []
        for radius in (1, 2, 3, 5):
            start_candidates.clear()
            fallback_candidates.clear()
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    row, col = base_row + dr, base_col + dc
                    plen = _cached_raster_cell(pds, row, col, pcache)
                    flowdir = _cached_raster_cell(fds, row, col, fcache)
                    if plen is None or flowdir is None or int(round(flowdir)) not in direction_offset:
                        continue
                    x, y = fds.xy(row, col)
                    point = Point(float(x), float(y))
                    # Prefer a true DTA cell.  The small buffered domain is only a fallback for
                    # outlets that lie exactly on a raster/polygon boundary, so a downstream
                    # regional-network cell cannot win merely because its plen is larger.
                    if raster_geom.covers(point):
                        start_candidates.append((plen, row, col))
                    elif path_domain.covers(point):
                        fallback_candidates.append((plen, row, col))
            if start_candidates:
                break
            if fallback_candidates:
                start_candidates.extend(fallback_candidates)
                break
        if not start_candidates:
            return None
        _, row, col = max(start_candidates, key=lambda item: item[0])
        plen_at_outlet = _cached_raster_cell(pds, row, col, pcache) or 0.0
        sx, sy = fds.xy(row, col)
        coords: list[tuple[float, float]] = [(outlet_raster.x, outlet_raster.y)]
        if math.hypot(float(sx) - outlet_raster.x, float(sy) - outlet_raster.y) > cell_size * 0.05:
            coords.append((float(sx), float(sy)))
        visited: set[tuple[int, int]] = set()
        current = (row, col)
        max_steps = 500_000
        for _ in range(max_steps):
            if current in visited:
                break
            visited.add(current)
            cr, cc = current
            candidates: list[tuple[float, int, int]] = []
            for nr in range(cr - 1, cr + 2):
                for nc in range(cc - 1, cc + 2):
                    if nr == cr and nc == cc:
                        continue
                    direction = _cached_raster_cell(fds, nr, nc, fcache)
                    plen = _cached_raster_cell(pds, nr, nc, pcache)
                    if direction is None or plen is None:
                        continue
                    offset = direction_offset.get(int(round(direction)))
                    if offset is None or (nr + offset[0], nc + offset[1]) != (cr, cc):
                        continue
                    x, y = fds.xy(nr, nc)
                    if not path_domain.covers(Point(float(x), float(y))):
                        continue
                    candidates.append((plen, nr, nc))
            if not candidates:
                break
            # plen is the longest upslope length terminating at a cell. The incoming branch with
            # the largest plen therefore continues the hydraulically most remote upstream path.
            _, nr, nc = max(candidates, key=lambda item: item[0])
            x, y = fds.xy(nr, nc)
            coords.append((float(x), float(y)))
            current = (nr, nc)
        if len(coords) < 2:
            return None
        line = LineString(coords)
        return (line, float(plen_at_outlet)) if line.length > 0 else None


def _flowpath_metrics(geom, outlet, source_crs: Any, dem_path: Path, flowdir_path: Path, plen_path: Path) -> dict[str, Any] | None:
    traced = _trace_longest_flowpath(geom, outlet, source_crs, flowdir_path, plen_path)
    if traced is None:
        return None
    line, plen_at_outlet_m = traced
    with rasterio.open(flowdir_path) as fds:
        flow_crs = fds.crs
    line_length = float(line.length)
    if line_length <= 0:
        return None
    centroid = geom.centroid
    if source_crs and flow_crs and str(source_crs) != str(flow_crs):
        centroid = transform(Transformer.from_crs(source_crs, flow_crs, always_xy=True).transform, centroid)
    centroid_distance = float(line.project(centroid))
    p_up = line.interpolate(line_length)
    p_centroid = line.interpolate(centroid_distance)
    p10 = line.interpolate(line_length * 0.10)
    p85 = line.interpolate(line_length * 0.85)

    def sample_flow_point(point: Point) -> float | None:
        x, y = point.x, point.y
        if flow_crs and source_crs and str(flow_crs) != str(source_crs):
            x, y = Transformer.from_crs(flow_crs, source_crs, always_xy=True).transform(x, y)
        return _sample_raster(dem_path, x, y, source_crs)

    z_outlet = _sample_raster(dem_path, outlet.x, outlet.y, source_crs)
    z_up = sample_flow_point(p_up)
    z_centroid = sample_flow_point(p_centroid)
    z10 = sample_flow_point(p10)
    z85 = sample_flow_point(p85)

    def slope_pct(z_upstream: float | None, z_downstream: float | None, length_m: float) -> float | None:
        if z_upstream is None or z_downstream is None or length_m <= 0:
            return None
        return (float(z_upstream) - float(z_downstream)) / length_m * 100.0

    longest_slope = slope_pct(z_up, z_outlet, line_length)
    centroid_slope = slope_pct(z_centroid, z_outlet, centroid_distance)
    segment_length = line_length * 0.75
    segment_slope = slope_pct(z85, z10, segment_length)
    return {
        "longest_flow_path_km": _round(line_length / 1000.0, 3),
        "centroidal_flowpath_km": _round(centroid_distance / 1000.0, 3),
        "flowpath_10_85_km": _round(segment_length / 1000.0, 3),
        "flowpath_slope": {
            "longest_flowpath_ratio": _round(longest_slope / 100.0, 6) if longest_slope is not None else None,
            "longest_flowpath_pct": _round(longest_slope, 3),
            "centroidal_flowpath_ratio": _round(centroid_slope / 100.0, 6) if centroid_slope is not None else None,
            "centroidal_flowpath_pct": _round(centroid_slope, 3),
            "flowpath_10_85_ratio": _round(segment_slope / 100.0, 6) if segment_slope is not None else None,
            "flowpath_10_85_pct": _round(segment_slope, 3),
            "elevation_upstream_m": _round(z_up, 1),
            "elevation_centroid_path_m": _round(z_centroid, 1),
            "elevation_10_m": _round(z10, 1),
            "elevation_85_m": _round(z85, 1),
        },
        "plen_at_outlet_km": _round(plen_at_outlet_m / 1000.0, 3),
        "flowpath_method": "Penelusuran arah aliran dan elevasi titik lintasan",
    }


def terrain_metrics(geom, outlet, source_crs: Any, dem_path: Path | None, plen_path: Path | None,
                    flowdir_path: Path | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "available": False,
        "source": None,
        "elevation": None,
        "slope": None,
        "hypsometry": None,
        "longest_flow_path_km": None,
        "centroidal_flowpath_km": None,
        "flowpath_10_85_km": None,
        "flowpath_slope": None,
        "missing": [],
    }
    if dem_path is None:
        output["missing"].append("data ketinggian")
    else:
        try:
            terrain = _hec_hms_terrain_from_dem(geom, outlet, source_crs, dem_path)
            if terrain is not None:
                output.update(terrain)
                output["available"] = True
        except (OSError, ValueError, rasterio.errors.RasterioError):
            output["missing"].append("data ketinggian tidak dapat dibaca")

    if plen_path is None:
        output["missing"].append("data panjang lintasan aliran")
    if flowdir_path is None:
        output["missing"].append("data arah aliran")

    if dem_path is not None and plen_path is not None and flowdir_path is not None:
        try:
            flow = _flowpath_metrics(geom, outlet, source_crs, dem_path, flowdir_path, plen_path)
            if flow is not None:
                output.update(flow)
        except (OSError, ValueError, rasterio.errors.RasterioError):
            output["missing"].append("lintasan aliran tidak dapat ditelusuri")

    # Backward-compatible length fallback if flowdir is unavailable or tracing fails. This only
    # supplies L; flowpath slopes remain unavailable rather than being synthesized from basin-wide
    # elevation statistics.
    if output.get("longest_flow_path_km") is None and plen_path is not None:
        try:
            lmax = _native_raster_max(plen_path, geom, source_crs)
            if lmax is not None:
                output["longest_flow_path_km"] = _round(lmax / 1000.0, 3)
        except (OSError, ValueError, rasterio.errors.RasterioError):
            pass
    return output


def landcover_metrics(geom, source_crs: Any, landcover_path: Path | None, area_km2: float | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {"available": False, "source": None, "classes": [], "summary": {}, "missing": []}
    if landcover_path is None:
        output["missing"].append("data penutup/penggunaan lahan")
        return output
    try:
        payload = _native_raster_code_counts(landcover_path, geom, source_crs)
        if payload is None:
            output["missing"].append("data penutup/penggunaan lahan tidak beririsan")
            return output
        by_code, total = payload
        classes = [
            {"code": int(code), "name": LANDCOVER_LABELS.get(int(code), f"Kelas PL {int(code)}"),
             "area_pct": _round(count / total * 100.0, 2),
             "area_km2": _round((count / total) * area_km2, 4) if area_km2 is not None else None}
            for code, count in sorted(by_code.items(), key=lambda pair: pair[1], reverse=True)
        ]
        def group_pct(predicate) -> float:
            return _round(sum(count for code, count in by_code.items() if predicate(code)) / total * 100.0, 2)
        output.update({
            "available": True, "source": landcover_path.name, "classes": classes, "sample_scale": 1.0,
            "summary": {
                "forest_pct": group_pct(lambda code: code in FOREST_CODES),
                "agriculture_pct": group_pct(lambda code: code in {20091, 20092, 20093, 2010, 20122, 6009}),
                "built_up_pct": group_pct(lambda code: code in {2012, 20121}),
                "open_land_pct": group_pct(lambda code: code in {2014, 20141}),
                "water_pct": group_pct(lambda code: code in {5001, 20094, 5011, 50011}),
            },
        })
    except (OSError, ValueError, rasterio.errors.RasterioError):
        output["missing"].append("data penutup/penggunaan lahan tidak dapat dibaca")
    return output


def curve_number_metrics(geom, source_crs: Any, cn_path: Path | None) -> dict[str, Any]:
    output: dict[str, Any] = {"available": False, "source": None, "weighted_cn_ii": None,
                              "potential_retention_mm": None, "distribution": [], "high_cn_pct": None,
                              "invalid_pct": None, "missing": []}
    if cn_path is None:
        output["missing"].append("data CN-II")
        return output
    try:
        with rasterio.open(cn_path) as ds:
            raster_geom = _geometry_for_dataset(geom, source_crs, ds)
            window = _window_for_geometry(ds, raster_geom)
            if window is None:
                output["missing"].append("data CN-II tidak beririsan")
                return output
            count = 0
            invalid_count = 0
            value_sum = 0.0
            bins = [0, 0, 0, 0, 0]
            high_count = 0
            for tile in _iter_tile_windows(window):
                data = ds.read(1, window=tile, out_dtype="float64")
                inside = rio_features.geometry_mask(
                    [mapping(raster_geom)], out_shape=data.shape, transform=ds.window_transform(tile), invert=True
                )
                raster_valid = inside & _valid_raster_values(data, ds.nodata)
                if not np.any(raster_valid):
                    continue
                values_all = data[raster_valid]
                valid_cn = (values_all > 0.0) & (values_all <= 100.0)
                invalid_count += int(np.count_nonzero(~valid_cn))
                values = values_all[valid_cn]
                if values.size == 0:
                    continue
                count += int(values.size)
                value_sum += float(values.sum(dtype=np.float64))
                bins[0] += int(np.count_nonzero(values < 60))
                bins[1] += int(np.count_nonzero((values >= 60) & (values < 70)))
                bins[2] += int(np.count_nonzero((values >= 70) & (values < 80)))
                bins[3] += int(np.count_nonzero((values >= 80) & (values <= 90)))
                bins[4] += int(np.count_nonzero(values > 90))
                high_count += int(np.count_nonzero(values >= 80))
        if count <= 0:
            output["missing"].append("data CN-II tidak memiliki nilai valid 0<CN≤100")
            return output
        weighted_cn = value_sum / count
        labels = ("CN < 60", "60 ≤ CN < 70", "70 ≤ CN < 80", "80 ≤ CN ≤ 90", "CN > 90")
        distribution = [{"class": label, "area_pct": _round(bin_count / count * 100.0, 1)} for label, bin_count in zip(labels, bins)]
        retention = 25400.0 / weighted_cn - 254.0 if weighted_cn > 0 else None
        high_cn_pct = high_count / count * 100.0
        all_count = count + invalid_count
        interpretations = {
            "weighted_cn": "Potensi limpasan tinggi" if weighted_cn >= 80 else "Potensi limpasan sedang" if weighted_cn >= 70 else "Potensi limpasan relatif rendah",
            "retention": "Retensi relatif rendah" if retention is not None and retention < 64 else "Retensi sedang" if retention is not None and retention < 127 else "Retensi relatif tinggi",
            "high_cn_area": "Dominan" if high_cn_pct >= 50 else "Signifikan" if high_cn_pct >= 25 else "Terbatas",
        }
        output.update({
            "available": True, "source": cn_path.name, "sample_scale": 1.0,
            "weighted_cn_ii": _round(weighted_cn, 1),
            "potential_retention_mm": _round(retention, 1),
            "distribution": distribution,
            "high_cn_pct": _round(high_cn_pct, 1),
            "invalid_pct": _round(invalid_count / all_count * 100.0, 2) if all_count else 0.0,
            "interpretations": interpretations,
        })
    except (OSError, ValueError, rasterio.errors.RasterioError):
        output["missing"].append("data CN-II tidak dapat dibaca")
    return output


def _load_analysis_streams(path: Path) -> gpd.GeoDataFrame:
    key = str(path.resolve())
    with _ANALYSIS_STREAMS_LOCK:
        cached = _ANALYSIS_STREAMS.get(key)
        if cached is not None:
            return cached
        gdf = gpd.read_file(f"zip://{path}") if path.suffix.lower() == ".zip" else gpd.read_file(path)
        if gdf.crs is None:
            raise ValueError("CRS streams_analysis tidak tersedia")
        _ANALYSIS_STREAMS[key] = gdf
        return gdf


def landsystem_metrics(geom, source_crs: Any, path: Path | None) -> dict[str, Any]:
    output: dict[str, Any] = {"available": False, "source": None, "classes": [], "dominant": None, "missing": []}
    if path is None:
        output["missing"].append("landsystem")
        return output
    try:
        key = str(path.resolve())
        with _LANDSYSTEMS_LOCK:
            systems = _LANDSYSTEMS.get(key)
            if systems is None:
                systems = gpd.read_file(f"zip://{path}") if path.suffix.lower() == ".zip" else gpd.read_file(path)
                if systems.crs is None:
                    raise ValueError("CRS landsystem tidak tersedia")
                _LANDSYSTEMS[key] = systems
        target = geom if str(systems.crs) == str(source_crs) else gpd.GeoSeries([geom], crs=source_crs).to_crs(systems.crs).iloc[0]
        selected = systems.loc[systems.intersects(target)].copy()
        if selected.empty:
            output["missing"].append("landsystem tidak beririsan")
            return output
        selected_equal = selected.to_crs("ESRI:54034")
        target_equal = gpd.GeoSeries([target], crs=systems.crs).to_crs("ESRI:54034").iloc[0]
        selected["_intersection_area"] = selected_equal.geometry.intersection(target_equal).area.to_numpy()
        selected = selected[selected["_intersection_area"] > 0]
        total = float(selected["_intersection_area"].sum())
        if total <= 0:
            output["missing"].append("landsystem tidak memiliki luasan beririsan")
            return output
        for column in ("m_ltype", "m_physiogr", "m_relclass"):
            if column not in selected.columns:
                selected[column] = "-"
            selected[column] = selected[column].fillna("-").astype(str).str.strip().replace("", "-")
        grouped = selected.groupby(["m_ltype", "m_physiogr", "m_relclass"], dropna=False)["_intersection_area"].sum().sort_values(ascending=False)
        classes = []
        water_area = 0.0
        for (land_type, physiography, relief), area in grouped.items():
            land_type_id = _translated_land_attribute(land_type, LAND_TYPE_ID, "tipe lahan belum teridentifikasi")
            physiography_id = _translated_land_attribute(physiography, PHYSIOGRAPHY_ID, "fisiografi belum teridentifikasi")
            relief_id = _translated_land_attribute(relief, RELIEF_ID, "relief belum teridentifikasi")
            is_unidentified = land_type_id.strip().lower() == "tipe lahan belum teridentifikasi"
            if is_unidentified:
                water_area += float(area)
                continue
            item = {
                "name": land_type_id if is_unidentified else f"{land_type_id}; fisiografi {physiography_id}; relief {relief_id}",
                "land_type": land_type_id, "physiography": physiography_id, "relief_class": relief_id,
                "land_type_source": str(land_type), "physiography_source": str(physiography), "relief_class_source": str(relief),
                "area_km2": _round(float(area) / 1_000_000.0, 4),
                "area_pct": _round(float(area) / total * 100.0, 2),
            }
            classes.append(item)
        if water_area > 0:
            classes.append({
                "name": "Badan Air", "land_type": "Badan Air", "physiography": "", "relief_class": "",
                "land_type_source": "tipe lahan belum teridentifikasi", "physiography_source": "", "relief_class_source": "",
                "area_km2": _round(water_area / 1_000_000.0, 4),
                "area_pct": _round(water_area / total * 100.0, 2),
            })
        attribute_groups: dict[str, list[dict[str, Any]]] = {}
        for source_name, output_name, translation, fallback in (
            ("m_ltype", "land_types", LAND_TYPE_ID, "tipe lahan belum teridentifikasi"),
            ("m_physiogr", "physiographies", PHYSIOGRAPHY_ID, "fisiografi belum teridentifikasi"),
            ("m_relclass", "relief_classes", RELIEF_ID, "relief belum teridentifikasi"),
        ):
            values = selected.groupby(source_name, dropna=False)["_intersection_area"].sum().sort_values(ascending=False)
            attribute_groups[output_name] = [
                {
                    "name": _translated_land_attribute(source_value, translation, fallback),
                    "source": str(source_value),
                    "area_km2": _round(float(area) / 1_000_000.0, 4),
                    "area_pct": _round(float(area) / total * 100.0, 2),
                }
                for source_value, area in values.items()
            ]
        output.update({"available": True, "source": path.name, "classes": classes,
                       "dominant": next((item for item in classes if item["land_type"] != "Badan Air"), None) or (classes[0] if classes else None), **attribute_groups})
    except (OSError, ValueError, KeyError):
        output["missing"].append("landsystem tidak dapat dibaca")
    return output


def _line_parts(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    parts: list[LineString] = []
    try:
        for child in geom.geoms:
            parts.extend(_line_parts(child))
    except Exception:
        pass
    return [part for part in parts if not part.is_empty and part.length > 0]


def _assemble_main_channel(path_links: list[int], rows: dict[int, Any], outlet_point: Point) -> tuple[list[tuple[float, float]], float]:
    """Build an outlet-to-upstream coordinate chain without assuming source digitization order."""
    coords: list[tuple[float, float]] = [(float(outlet_point.x), float(outlet_point.y))]
    total_length = 0.0
    current = outlet_point
    for link in path_links:
        row = rows[link]
        clipped = row.get("_clipped_geometry")
        parts = _line_parts(clipped)
        if not parts:
            continue
        part = min(parts, key=lambda candidate: candidate.distance(current))
        part_coords = list(part.coords)
        if len(part_coords) < 2:
            continue
        start = Point(part_coords[0])
        end = Point(part_coords[-1])
        if end.distance(current) < start.distance(current):
            part_coords.reverse()
        # Avoid inserting an artificial connector when the outlet is already on the first part.
        if Point(part_coords[0]).distance(current) <= max(0.01, part.length * 1e-8):
            coords.extend((float(x), float(y)) for x, y, *rest in part_coords[1:])
        else:
            coords.extend((float(x), float(y)) for x, y, *rest in part_coords)
        current = Point(part_coords[-1])
        total_length += float(row.get("_clipped_length_m", part.length) or part.length)
    return coords, total_length


def _strahler_stream_counts(rows: dict[int, Any], order_getter, downstream_getter) -> tuple[dict[int, int], dict[str, float]]:
    """Count maximal Strahler streams, not every link split at a junction."""
    link_orders: dict[int, int] = {}
    for link, row in rows.items():
        try:
            order = int(order_getter(row) or 0)
        except (TypeError, ValueError):
            order = 0
        if order > 0:
            link_orders[int(link)] = order

    counts: dict[int, int] = {}
    for link, order in link_orders.items():
        try:
            downstream = int(downstream_getter(rows[link]) or -1)
        except (TypeError, ValueError):
            downstream = -1
        # One stream is a maximal chain of links with the same Strahler order.
        # Count the downstream-most link of every same-order chain exactly once.
        if downstream not in link_orders or link_orders.get(downstream) != order:
            counts[order] = counts.get(order, 0) + 1

    ratios = {
        f"{order}-{order + 1}": counts[order] / counts[order + 1]
        for order in sorted(counts)
        if counts.get(order + 1, 0) > 0
    }
    return counts, ratios


def analysis_stream_metrics(geom, outlet, source_crs: Any, stream_path: Path | None, area_km2: float,
                            dem_path: Path | None = None) -> dict[str, Any]:
    empty = {"available": False, "source": None, "stream_count": None, "stream_order_max": None,
             "total_stream_length_km": None, "main_channel_length_km": None, "main_channel_slope_pct": None,
             "network_mean_slope_pct": None, "reach_slope_pct": None,
             "drainage_density_km_per_km2": None, "stream_frequency_per_km2": None,
             "bifurcation_ratio": None, "order_counts": {}, "bifurcation_ratios_by_order": {}, "mean_stream_length_km": None,
             "drainage_texture_per_km": None, "drainage_intensity": None, "overland_flow_length_km": None,
             "channel_maintenance_constant_km2_per_km": None, "infiltration_number": None,
             "junction_density_per_km2": None, "junction_count": None, "channel_sinuosity": None,
             "main_channel_linknos": [], "missing": []}
    if stream_path is None:
        empty["missing"].append("data jaringan sungai analisis")
        return empty
    try:
        streams = _load_analysis_streams(stream_path)
        target = geom if str(streams.crs) == str(source_crs) else gpd.GeoSeries([geom], crs=source_crs).to_crs(streams.crs).iloc[0]
        outlet_target = outlet if str(streams.crs) == str(source_crs) else gpd.GeoSeries([outlet], crs=source_crs).to_crs(streams.crs).iloc[0]
        selected = streams.loc[streams.intersects(target)].copy()
        if selected.empty:
            empty["missing"].append("data jaringan sungai analisis tidak beririsan")
            return empty

        selected["_clipped_geometry"] = [geometry.intersection(target) for geometry in selected.geometry]
        selected["_clipped_length_m"] = [float(geometry.length) for geometry in selected["_clipped_geometry"]]
        # A reach that merely touches the DTA boundary must not contribute its full regional length.
        selected = selected[selected["_clipped_length_m"] > 1e-6].copy()
        if selected.empty:
            empty["missing"].append("data jaringan sungai analisis hanya menyentuh batas DTA")
            return empty

        link_col = "LINKNO" if "LINKNO" in selected.columns else "linkno" if "linkno" in selected.columns else None
        if link_col is None:
            raise ValueError("Field LINKNO tidak tersedia pada streams_analysis")
        us1_col = "USLINKNO1" if "USLINKNO1" in selected.columns else "upstream_linkno1" if "upstream_linkno1" in selected.columns else None
        us2_col = "USLINKNO2" if "USLINKNO2" in selected.columns else "upstream_linkno2" if "upstream_linkno2" in selected.columns else None
        ds_col = "DSLINKNO" if "DSLINKNO" in selected.columns else "downstream_linkno" if "downstream_linkno" in selected.columns else None
        order_col = "strmOrder" if "strmOrder" in selected.columns else "strm_order" if "strm_order" in selected.columns else None
        slope_col = "Slope" if "Slope" in selected.columns else "slope" if "slope" in selected.columns else None

        rows: dict[int, Any] = {int(row[link_col]): row for _, row in selected.iterrows()}
        lengths = np.asarray([float(row.get("_clipped_length_m", 0.0) or 0.0) for row in rows.values()], dtype=float)
        total_length_m = float(lengths.sum())

        orders: dict[int, int] = {}
        order_ratios: dict[str, float] = {}
        if order_col is not None:
            orders, order_ratios = _strahler_stream_counts(
                rows,
                lambda row: row.get(order_col, 0),
                lambda row: row.get(ds_col, -1) if ds_col is not None else -1,
            )

        slope_values: list[float] = []
        slope_weights: list[float] = []
        if slope_col is not None:
            for row in rows.values():
                try:
                    slope_value = float(row.get(slope_col))
                    length_value = float(row.get("_clipped_length_m", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(slope_value) and length_value > 0:
                    slope_values.append(slope_value)
                    slope_weights.append(length_value)
        network_mean_slope = float(np.average(slope_values, weights=slope_weights)) * 100.0 if slope_weights else None

        # Identify DTA-relative root reach(es).  For a regional TauDEM network the proper root is a
        # clipped reach whose downstream LINKNO is no longer inside the DTA.  This is more robust
        # than simply taking the nearest reach and also handles an outlet exactly at a confluence,
        # where two upstream reaches can be equally close to the outlet.
        root_links: list[int] = []
        if ds_col is not None:
            for link, row in rows.items():
                try:
                    downstream = int(row.get(ds_col, -1) or -1)
                except (TypeError, ValueError):
                    downstream = -1
                if downstream not in rows:
                    root_links.append(link)
        if not root_links:
            root_links = list(rows)
        root_distances = {link: float(rows[link]["_clipped_geometry"].distance(outlet_target)) for link in root_links}
        nearest_root_distance = min(root_distances.values())
        outlet_tolerance = max(0.01, nearest_root_distance * 1e-6)
        outlet_roots = [
            link for link in root_links
            if root_distances[link] <= nearest_root_distance + outlet_tolerance
        ]

        memo: dict[int, tuple[list[int], float]] = {}

        def best_upstream_path(link: int) -> tuple[list[int], float]:
            if link in memo:
                return memo[link]
            row = rows[link]
            upstream: list[int] = []
            for column in (us1_col, us2_col):
                if column is None:
                    continue
                try:
                    candidate = int(row.get(column, -1) or -1)
                except (TypeError, ValueError):
                    candidate = -1
                if candidate in rows and candidate != link:
                    upstream.append(candidate)
            candidates = [best_upstream_path(candidate) for candidate in upstream]
            child_path, child_length = max(candidates, key=lambda item: item[1], default=([], 0.0))
            own = float(row.get("_clipped_length_m", 0.0) or 0.0)
            memo[link] = ([link, *child_path], own + child_length)
            return memo[link]

        root_paths = [best_upstream_path(link) for link in outlet_roots]
        main_path, main_length_m = max(root_paths, key=lambda item: item[1])
        chain_coords, assembled_length = _assemble_main_channel(main_path, rows, outlet_target)
        if assembled_length > 0:
            main_length_m = assembled_length
        upstream_point = Point(chain_coords[-1]) if len(chain_coords) >= 2 else None
        channel_sinuosity = None
        if upstream_point is not None:
            straight_length = float(outlet_target.distance(upstream_point))
            if straight_length > 0:
                channel_sinuosity = main_length_m / straight_length

        main_channel_slope = None
        if dem_path is not None and upstream_point is not None and main_length_m > 0:
            ux, uy = upstream_point.x, upstream_point.y
            if str(streams.crs) != str(source_crs):
                ux, uy = Transformer.from_crs(streams.crs, source_crs, always_xy=True).transform(ux, uy)
            z_up = _sample_raster(dem_path, ux, uy, source_crs)
            z_out = _sample_raster(dem_path, outlet.x, outlet.y, source_crs)
            if z_up is not None and z_out is not None:
                main_channel_slope = (float(z_up) - float(z_out)) / main_length_m * 100.0
        if main_channel_slope is None and main_path and slope_col is not None:
            path_slopes = []
            path_lengths = []
            for link in main_path:
                row = rows[link]
                try:
                    slope_value = float(row.get(slope_col))
                    length_value = float(row.get("_clipped_length_m", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(slope_value) and length_value > 0:
                    path_slopes.append(slope_value)
                    path_lengths.append(length_value)
            if path_lengths:
                main_channel_slope = float(np.average(path_slopes, weights=path_lengths)) * 100.0

        junction_count = 0
        if us1_col is not None and us2_col is not None:
            for row in rows.values():
                upstream_present = 0
                for column in (us1_col, us2_col):
                    try:
                        upstream_id = int(row.get(column, -1) or -1)
                    except (TypeError, ValueError):
                        upstream_id = -1
                    if upstream_id in rows:
                        upstream_present += 1
                if upstream_present >= 2:
                    junction_count += 1

        ratios = list(order_ratios.values())
        stream_count = int(sum(orders.values()))
        total_km = total_length_m / 1000.0
        drainage_density = total_km / area_km2 if area_km2 > 0 else None
        frequency = stream_count / area_km2 if area_km2 > 0 else None
        metric_geom = _metric_geometry(geom, source_crs)
        perimeter_km = float(metric_geom.length / 1000.0)
        drainage_intensity = frequency / drainage_density if drainage_density and drainage_density > 0 and frequency is not None else None
        infiltration_number = drainage_density * frequency if drainage_density is not None and frequency is not None else None
        return {
            "available": True,
            "source": stream_path.name,
            "stream_count": stream_count,
            "stream_order_max": max(orders, default=None),
            "total_stream_length_km": _round(total_km, 3),
            "main_channel_length_km": _round(main_length_m / 1000.0, 3),
            "main_channel_slope_pct": _round(main_channel_slope, 3),
            "network_mean_slope_pct": _round(network_mean_slope, 3),
            # Backward-compatible alias: this is the length-weighted mean slope of all clipped reaches.
            "reach_slope_pct": _round(network_mean_slope, 3),
            "drainage_density_km_per_km2": _round(drainage_density, 3),
            "stream_frequency_per_km2": _round(frequency, 3),
            "bifurcation_ratio": _round(float(np.mean(ratios)), 3) if ratios else None,
            "mean_stream_length_km": _round(total_km / stream_count, 3) if stream_count else None,
            "drainage_texture_per_km": _round(stream_count / perimeter_km, 3) if perimeter_km else None,
            # Faniran drainage intensity: Fs / Dd. It must not duplicate infiltration number.
            "drainage_intensity": _round(drainage_intensity, 3),
            "overland_flow_length_km": _round(1.0 / (2.0 * drainage_density), 4) if drainage_density else None,
            "channel_maintenance_constant_km2_per_km": _round(1.0 / drainage_density, 4) if drainage_density else None,
            "infiltration_number": _round(infiltration_number, 3),
            "junction_count": int(junction_count),
            "junction_density_per_km2": _round(junction_count / area_km2, 3) if area_km2 > 0 else None,
            "channel_sinuosity": _round(channel_sinuosity, 3),
            "main_channel_linknos": [int(link) for link in main_path],
            "order_counts": {str(k): v for k, v in sorted(orders.items())},
            "bifurcation_ratios_by_order": {key: _round(value, 3) for key, value in order_ratios.items()},
            "missing": [],
        }
    except (OSError, ValueError, KeyError, rasterio.errors.RasterioError):
        empty["missing"].append("data jaringan sungai analisis tidak dapat dibaca")
        return empty


def _main_channel(stream_rows: dict[int, Any], upstream_by_downstream: dict[int, list[int]], outlet_linkno: int | None):
    if outlet_linkno is None or outlet_linkno not in stream_rows:
        return [], 0.0
    memo: dict[int, tuple[list[int], float]] = {}

    def best(link: int) -> tuple[list[int], float]:
        if link in memo:
            return memo[link]
        row = stream_rows[link]
        own = float(row.get("length_m", 0.0) or 0.0)
        candidates = [best(int(child)) for child in upstream_by_downstream.get(link, []) if int(child) in stream_rows]
        path, length = max(candidates, key=lambda item: item[1], default=([], 0.0))
        memo[link] = ([link, *path], own + length)
        return memo[link]

    return best(int(outlet_linkno))


def drainage_metrics(streams, upstream_ids: Iterable[int], upstream_by_downstream: dict[int, list[int]],
                     outlet_linkno: int | None, area_km2: float) -> dict[str, Any]:
    ids = {int(v) for v in upstream_ids}
    if not ids:
        return {
            "available": False, "stream_count": None, "stream_order_max": None,
            "total_stream_length_km": None, "main_channel_length_km": None,
            "main_channel_slope_pct": None, "network_mean_slope_pct": None, "reach_slope_pct": None,
            "drainage_density_km_per_km2": None, "stream_frequency_per_km2": None,
            "bifurcation_ratio": None, "order_counts": {}, "bifurcation_ratios_by_order": {}, "mean_stream_length_km": None,
            "drainage_intensity": None, "infiltration_number": None, "junction_count": None,
            "junction_density_per_km2": None, "channel_sinuosity": None,
        }
    rows = {int(row["linkno"]): row for _, row in streams[streams["linkno"].isin(ids)].iterrows()}
    total_length_m = sum(float(row.get("length_m", row.geometry.length) or 0.0) for row in rows.values())
    path, main_length_m = _main_channel(rows, upstream_by_downstream, outlet_linkno)
    weighted_slope_num = 0.0
    weighted_slope_den = 0.0
    for link in path:
        row = rows[link]
        length = float(row.get("length_m", 0.0) or 0.0)
        slope = float(row.get("slope", 0.0) or 0.0)
        if length > 0 and math.isfinite(slope):
            weighted_slope_num += slope * length
            weighted_slope_den += length
    orders, order_ratios = _strahler_stream_counts(
        rows,
        lambda row: row.get("strm_order", 0),
        lambda row: row.get("downstream_id", -1),
    )
    ratios = list(order_ratios.values())
    stream_count = int(sum(orders.values()))
    total_km = total_length_m / 1000.0
    drainage_density = total_km / area_km2 if area_km2 > 0 else None
    frequency = stream_count / area_km2 if area_km2 > 0 else None
    all_slopes = []
    all_lengths = []
    for row in rows.values():
        length = float(row.get("length_m", 0.0) or 0.0)
        slope = float(row.get("slope", 0.0) or 0.0)
        if length > 0 and math.isfinite(slope):
            all_slopes.append(slope)
            all_lengths.append(length)
    network_mean_slope = float(np.average(all_slopes, weights=all_lengths)) * 100.0 if all_lengths else None
    junction_count = sum(
        1 for link in ids
        if len([child for child in upstream_by_downstream.get(link, []) if int(child) in ids]) >= 2
    )
    result = {
        "available": True,
        "stream_count": stream_count,
        "stream_order_max": max(orders, default=None),
        "total_stream_length_km": _round(total_km, 3),
        "main_channel_length_km": _round(main_length_m / 1000.0, 3),
        "main_channel_slope_pct": _round((weighted_slope_num / weighted_slope_den) * 100.0, 3) if weighted_slope_den else None,
        "network_mean_slope_pct": _round(network_mean_slope, 3),
        "reach_slope_pct": _round(network_mean_slope, 3),
        "drainage_density_km_per_km2": _round(drainage_density, 3),
        "stream_frequency_per_km2": _round(frequency, 3),
        "bifurcation_ratio": _round(float(np.mean(ratios)), 3) if ratios else None,
        "mean_stream_length_km": _round(total_km / stream_count, 3) if stream_count else None,
        "drainage_intensity": _round(frequency / drainage_density, 3) if drainage_density and frequency is not None else None,
        "infiltration_number": _round(drainage_density * frequency, 3) if drainage_density is not None and frequency is not None else None,
        "junction_count": int(junction_count),
        "junction_density_per_km2": _round(junction_count / area_km2, 3) if area_km2 > 0 else None,
        "channel_sinuosity": None,
        "order_counts": {str(k): v for k, v in sorted(orders.items())},
        "bifurcation_ratios_by_order": {key: _round(value, 3) for key, value in order_ratios.items()},
    }
    return result


def _classify(value: float | None, bands: tuple[tuple[float, str], ...], fallback: str) -> str | None:
    if value is None:
        return None
    for ceiling, label in bands:
        if value < ceiling:
            return label
    return fallback


def hydrologic_response_class(score: float) -> str:
    """Classify a normalized heuristic response score in the range -1..1.

    The score is intentionally an interpretive synthesis rather than a calibrated flood model.
    Normalizing by the number of available indicators prevents missing datasets from changing the
    meaning of the class thresholds.
    """
    if score >= 0.75:
        return "Cepat"
    if score >= 0.25:
        return "Sedang–Cepat"
    if score > -0.25:
        return "Sedang"
    if score > -0.75:
        return "Lambat–Sedang"
    return "Lambat"


def time_of_concentration_metrics(area_km2: float, longest_flow_path_km: float | None,
                                  relief_m: float | None, mean_slope_pct: float | None,
                                  weighted_cn: float | None, *,
                                  main_channel_length_km: float | None = None,
                                  main_channel_slope_pct: float | None = None,
                                  longest_flowpath_slope_pct: float | None = None,
                                  centroidal_flowpath_km: float | None = None,
                                  flowpath_10_85_slope_pct: float | None = None,
                                  mean_height_above_outlet_m: float | None = None,
                                  nrcs_velocity_segments: list[dict[str, float]] | None = None,
                                  kerby_inputs: dict[str, float] | None = None,
                                  izzard_inputs: dict[str, float] | None = None,
                                  viparelli_velocity_mps: float | None = None) -> dict[str, Any]:
    """Comparative Tc estimators using each method's own length/slope definition.

    ``mean_slope_pct`` is the HEC-HMS-style mean watershed land slope and is used by the NRCS
    watershed-lag equation. Channel-based empirical methods use ``main_channel_slope_pct`` and
    ``main_channel_length_km`` instead of reusing the basin mean slope.
    """
    basin_slope_pct = float(mean_slope_pct) if mean_slope_pct is not None and mean_slope_pct > 0 else None
    channel_length_km = float(main_channel_length_km) if main_channel_length_km and main_channel_length_km > 0 else None
    channel_slope_ratio = (float(main_channel_slope_pct) / 100.0) if main_channel_slope_pct is not None and main_channel_slope_pct > 0 else None
    flow_length_km = float(longest_flow_path_km) if longest_flow_path_km and longest_flow_path_km > 0 else None

    kirpich = None
    if channel_length_km is not None and channel_slope_ratio is not None:
        channel_length_m = channel_length_km * 1000.0
        kirpich = 0.0195 * channel_length_m ** 0.77 * channel_slope_ratio ** -0.385 / 60.0

    scs_lag = None
    cn_for_lag = float(weighted_cn) if weighted_cn is not None else None
    if flow_length_km is not None and basin_slope_pct is not None and cn_for_lag is not None and 50.0 <= cn_for_lag <= 95.0:
        length_ft = flow_length_km * 1000.0 * 3.28084
        retention_in = (1000.0 / cn_for_lag) - 10.0
        # NRCS Tc form is algebraically equivalent to lag/0.6 (1900*0.6 = 1140).
        scs_lag = (length_ft ** 0.8 * (retention_in + 1.0) ** 0.7) / (1140.0 * math.sqrt(basin_slope_pct))

    giandotti = None
    if flow_length_km is not None and mean_height_above_outlet_m is not None and mean_height_above_outlet_m > 0:
        giandotti = (4.0 * math.sqrt(area_km2) + 1.5 * flow_length_km) / (0.8 * math.sqrt(mean_height_above_outlet_m))

    kerby = None
    if kerby_inputs:
        overland_length_m = float(kerby_inputs.get("length_m", 0.0))
        overland_slope = float(kerby_inputs.get("slope_pct", 0.0)) / 100.0
        retardance_n = float(kerby_inputs.get("retardance_coefficient", 0.0))
        if overland_length_m > 0 and overland_slope > 0 and retardance_n > 0:
            # Kerby equation in SI-compatible implementation through the customary English form.
            overland_length_ft = overland_length_m * 3.28084
            kerby = (0.828 * (overland_length_ft * retardance_n) ** 0.467 * overland_slope ** -0.235) / 60.0

    temez = passini = ventura = bransby_williams = johnstone_cross = None
    if channel_length_km is not None and channel_slope_ratio is not None:
        temez = 0.3 * channel_length_km ** 0.76 * channel_slope_ratio ** -0.19
        passini = 0.108 * (area_km2 * channel_length_km) ** (1.0 / 3.0) / math.sqrt(channel_slope_ratio)
        ventura = 0.127 * math.sqrt(area_km2 / channel_slope_ratio)
        # General Bransby-Williams form: S is m/m and the equation explicitly uses (100*S)^0.2.
        bransby_williams = 0.605 * channel_length_km / ((100.0 * channel_slope_ratio) ** 0.2 * area_km2 ** 0.1)
        johnstone_cross = 0.4623 * math.sqrt(channel_length_km) * channel_slope_ratio ** -0.25

    nrcs_velocity = None
    if nrcs_velocity_segments and all(float(item.get("length_m", 0)) >= 0 and float(item.get("velocity_mps", 0)) > 0 for item in nrcs_velocity_segments):
        nrcs_velocity = sum(float(item["length_m"]) / float(item["velocity_mps"]) / 3600.0 for item in nrcs_velocity_segments)

    izzard = None
    if izzard_inputs:
        intensity = float(izzard_inputs.get("rainfall_intensity_in_h", 0))
        retardance = float(izzard_inputs.get("retardance_coefficient", 0))
        length_ft = float(izzard_inputs.get("length_ft", 0))
        izzard_slope = float(izzard_inputs.get("slope_ft_ft", 0))
        if intensity > 0 and retardance > 0 and length_ft > 0 and izzard_slope > 0:
            izzard = 41.025 * (0.0007 * intensity + retardance) * length_ft ** (1 / 3) / (izzard_slope ** (1 / 3) * intensity ** (2 / 3)) / 60.0

    viparelli = flow_length_km / (3.6 * viparelli_velocity_mps) if flow_length_km and viparelli_velocity_mps and viparelli_velocity_mps > 0 else None

    raw_values: dict[str, float | None] = {
        "kirpich": kirpich, "scs_lag": scs_lag, "nrcs_velocity": nrcs_velocity,
        "giandotti": giandotti, "temez": temez, "bransby_williams": bransby_williams,
        "kerby": kerby, "izzard": izzard, "passini": passini, "ventura_heras": ventura,
        "johnstone_cross": johnstone_cross, "viparelli": viparelli,
    }

    def method(key: str, label: str, status: str, reason: str, input_basis: str) -> dict[str, Any]:
        value = raw_values[key]
        return {
            "key": key, "label": label, "value_hours": _round(value, 2), "status": status,
            "reason": reason, "input_basis": input_basis, "used_for_recommendation": False,
        }

    kirpich_status = "Utama" if kirpich is not None and area_km2 <= 200 else "Kesesuaian terbatas"
    scs_status = "Utama" if scs_lag is not None and area_km2 <= 49 else "Kesesuaian terbatas"
    giandotti_status = "Utama" if giandotti is not None and area_km2 >= 170 else "Pembanding"
    temez_status = "Utama" if temez is not None and area_km2 <= 3000 else "Pembanding"
    bransby_status = "Utama" if bransby_williams is not None and area_km2 <= 137 else "Pembanding"
    johnstone_status = "Utama" if johnstone_cross is not None and 64.8 <= area_km2 <= 4206.1 else "Pembanding"
    methods = [
        method("kirpich", "Kirpich", kirpich_status,
               "Berbasis panjang dan kemiringan alur utama.",
               "L alur utama; S alur utama"),
        method("scs_lag", "Waktu Tunda NRCS/SCS", scs_status,
               "Memakai panjang lintasan, kemiringan DTA, dan CN-II." if scs_lag is not None else
               "Memerlukan panjang lintasan, kemiringan DTA, dan CN-II.",
               "L lintasan aliran terpanjang; S DTA; CN-II"),
        method("nrcs_velocity", "Metode Kecepatan NRCS", "Utama" if nrcs_velocity is not None else "Kesesuaian terbatas",
               "Menjumlahkan waktu aliran lembar, terkonsentrasi, dan saluran." if nrcs_velocity is not None else "Panjang dan kecepatan tiap segmen aliran belum tersedia.",
               "Σ(L/V) per segmen"),
        method("giandotti", "Giandotti", giandotti_status,
               "Berbasis luas, panjang lintasan, dan beda elevasi rata-rata terhadap outlet.",
               "A; L lintasan aliran terpanjang; Hm=Zrata-rata−Zoutlet"),
        method("temez", "Témez", temez_status,
               "Berbasis panjang dan kemiringan alur utama.",
               "L alur utama; S alur utama"),
        method("bransby_williams", "Bransby-Williams", bransby_status,
               "Berbasis panjang, luas, dan kemiringan alur utama.",
               "A; L alur utama; (100S)"),
        method("kerby", "Kerby", "Pembanding" if kerby is not None else "Kesesuaian terbatas",
               "Untuk aliran permukaan; memerlukan panjang dan hambatan permukaan.",
               "L permukaan; S permukaan; koefisien hambatan"),
        method("izzard", "Izzard", "Kesesuaian terbatas",
               "Memerlukan intensitas hujan dan parameter aliran lembar.",
               "i; c; L aliran lembar; S"),
        method("passini", "Passini", "Pembanding",
               "Berbasis luas, panjang, dan kemiringan alur utama.",
               "A; L alur utama; S alur utama"),
        method("ventura_heras", "Ventura-Heras", "Pembanding",
               "Berbasis luas dan kemiringan alur utama.",
               "A; S alur utama"),
        method("johnstone_cross", "Johnstone-Cross", johnstone_status,
               "Berbasis panjang dan kemiringan alur utama.",
               "L alur utama; S alur utama"),
        method("viparelli", "Viparelli", "Kesesuaian terbatas",
               "Memerlukan kecepatan rambat aliran yang terukur atau terkalibrasi.",
               "L lintasan aliran terpanjang; V terukur/terkalibrasi"),
    ]

    valid_by_key = {item["key"]: raw_values[item["key"]] for item in methods if raw_values[item["key"]] is not None and raw_values[item["key"]] > 0}
    primary = [item for item in methods if item["status"] == "Utama" and item["key"] in valid_by_key]
    if len(primary) >= 2:
        candidates = primary
    else:
        candidates = [item for item in methods if item["status"] in {"Utama", "Pembanding"} and item["key"] in valid_by_key]
    candidate_values = [float(valid_by_key[item["key"]]) for item in candidates]
    center = float(np.median(candidate_values)) if candidate_values else None
    consistent = [
        item for item in candidates
        if center is not None and 0.5 * center <= float(valid_by_key[item["key"]]) <= 2.0 * center
    ]
    recommended = float(np.median([valid_by_key[item["key"]] for item in consistent])) if consistent else center
    for item in consistent:
        item["used_for_recommendation"] = True
    if len(consistent) >= 2:
        consistent_values = [float(valid_by_key[item["key"]]) for item in consistent]
        spread = max(consistent_values) / min(consistent_values)
    else:
        spread = math.inf
    agreement = "Tinggi" if len(consistent) >= 3 and spread <= 1.35 else "Sedang" if len(consistent) >= 2 and spread <= 2.0 else "Rendah"
    result = {
        "available": bool(candidate_values),
        "kirpich_hours": _round(kirpich, 2), "scs_lag_hours": _round(scs_lag, 2),
        "giandotti_hours": _round(giandotti, 2), "kerby_hours": _round(kerby, 2), "temez_hours": _round(temez, 2),
        "passini_hours": _round(passini, 2), "ventura_heras_hours": _round(ventura, 2), "bransby_williams_hours": _round(bransby_williams, 2),
        "nrcs_velocity_hours": _round(nrcs_velocity, 2), "izzard_hours": _round(izzard, 2),
        "johnstone_cross_hours": _round(johnstone_cross, 2), "viparelli_hours": _round(viparelli, 2),
        "methods": methods,
        "representative_hours": _round(recommended, 2),
        "representative_methods": [item["label"] for item in consistent],
        "recommended_hours": _round(recommended, 2),
        "recommendation_methods": [item["label"] for item in consistent],
        "method_agreement": agreement,
        # Kept as a compatibility alias for older frontends; it is not statistical confidence.
        "confidence": agreement,
        "representative_basis": "Median robust dari metode yang sesuai; nilai menyimpang tidak disertakan.",
        "recommendation_basis": "Median robust dari metode yang sesuai; nilai menyimpang tidak disertakan.",
        "missing": [item["label"] for item in methods if item["value_hours"] is None],
        "input_summary": {
            "longest_flow_path_km": _round(flow_length_km, 3),
            "centroidal_flowpath_km": _round(centroidal_flowpath_km, 3),
            "flowpath_10_85_slope_pct": _round(flowpath_10_85_slope_pct, 3),
            "longest_flowpath_slope_pct": _round(longest_flowpath_slope_pct, 3),
            "basin_mean_slope_pct": _round(basin_slope_pct, 3),
            "main_channel_length_km": _round(channel_length_km, 3),
            "main_channel_slope_pct": _round(main_channel_slope_pct, 3),
            "basin_relief_m": _round(relief_m, 1),
            "mean_height_above_outlet_m": _round(mean_height_above_outlet_m, 1),
        },
    }
    return result


def refresh_characteristic_narratives(analysis: dict[str, Any], decimal_separator: str = ",") -> dict[str, Any]:
    """Rebuild all prose from structured metrics using one locale-aware source."""
    sep = "." if decimal_separator == "." else ","
    morph = analysis.get("morphometry") or {}
    terrain = analysis.get("terrain") or {}
    slope = terrain.get("slope") or {}
    elevation = terrain.get("elevation") or {}
    drainage = analysis.get("drainage") or {}
    landcover = analysis.get("landcover") or {}
    land_summary = landcover.get("summary") or {}
    landsystem = analysis.get("landsystem") or {}
    curve_number = analysis.get("curve_number") or {}
    summary = analysis.setdefault("executive_summary", {})
    response = str(summary.get("response_class") or "belum dapat dinilai").lower()
    shape = str(morph.get("shape_class") or "belum terklasifikasi").lower()
    slope_class = str((analysis.get("classifications") or {}).get("mean_slope") or "belum terklasifikasi").lower()
    mean_slope = _narrative_number(slope.get("mean_pct"), 1, sep)
    relief = _narrative_number(elevation.get("relief_m"), 1, sep)
    dd = _narrative_number(drainage.get("drainage_density_km_per_km2"), 2, sep)
    cn = _narrative_number(curve_number.get("weighted_cn_ii"), 1, sep)

    def dominant_phrases(key: str, limit: int = 5, with_pct: bool = True) -> list[str]:
        phrases = []
        candidates = [item for item in (landsystem.get(key) or []) if "belum teridentifikasi" not in str(item.get("name") or "")]
        if not candidates:
            candidates = landsystem.get(key) or []
        for item in candidates[:limit]:
            name = item.get("name") or "belum teridentifikasi"
            if key == "land_types" and "belum teridentifikasi" in str(name).lower():
                name = "Badan Air"
            suffix = f" ({_narrative_number(item.get('area_pct'), 1, sep)}%)" if with_pct else ""
            phrases.append(f"{name}{suffix}")
        return phrases

    land_types = dominant_phrases("land_types")
    physiographies = dominant_phrases("physiographies")
    relief_classes = dominant_phrases("relief_classes")
    if not land_types and landsystem.get("dominant"):
        dominant = landsystem["dominant"]
        land_types = [str(dominant.get("land_type") or "tipe lahan belum teridentifikasi")]
        physiographies = [str(dominant.get("physiography") or "fisiografi belum teridentifikasi")]
        relief_classes = [str(dominant.get("relief_class") or "relief belum teridentifikasi")]

    agriculture = _narrative_number(land_summary.get("agriculture_pct"), 1, sep)
    forest = _narrative_number(land_summary.get("forest_pct"), 1, sep)
    built = _narrative_number(land_summary.get("built_up_pct"), 1, sep)
    open_land = _narrative_number(land_summary.get("open_land_pct"), 1, sep)
    water = _narrative_number(land_summary.get("water_pct"), 1, sep)
    system_lead = _natural_join([phrase.split(" (")[0] for phrase in land_types[:2]]) or "tipe lahan yang belum teridentifikasi"
    phys_lead = _natural_join([phrase.split(" (")[0] for phrase in physiographies[:2]]) or "fisiografi yang belum teridentifikasi"
    relief_lead = _natural_join([phrase.split(" (")[0] for phrase in relief_classes[:2]]) or "relief yang belum teridentifikasi"

    # Keep the 12 indicator cards unchanged, but surface the most decision-useful
    # supporting evidence inside the executive narrative. These are contextual
    # diagnostics rather than additional dashboard indicators.
    steep_pct = sum(
        float(item.get("area_pct") or 0.0)
        for item in (slope.get("distribution") or [])
        if item.get("class") in {"Curam", "Sangat curam"}
    ) if slope.get("distribution") else None
    high_cn_pct = curve_number.get("high_cn_pct")
    dominant_landcover = (landcover.get("classes") or [None])[0]
    executive_focus: list[str] = []
    if high_cn_pct is not None:
        executive_focus.append(f"area CN ≥80 sebesar {_narrative_number(high_cn_pct, 1, sep)}%")
    if steep_pct is not None:
        executive_focus.append(f"area lereng curam–sangat curam sebesar {_narrative_number(steep_pct, 1, sep)}%")
    if dominant_landcover:
        executive_focus.append(
            f"tutupan lahan dominan {dominant_landcover.get('name') or 'belum teridentifikasi'} "
            f"({_narrative_number(dominant_landcover.get('area_pct'), 1, sep)}%)"
        )
    focus_sentence = (
        f"Untuk pembacaan eksekutif, indikator kontekstual yang paling perlu diperhatikan adalah {_natural_join(executive_focus)}. "
        if executive_focus else ""
    )
    summary["narrative"] = (
        f"Karakteristik DTA berkembang pada sistem lahan berupa {system_lead}. "
        f"Secara fisiografis wilayahnya didominasi {phys_lead} dengan relief {relief_lead}. "
        f"Kemiringan rata-rata DTA sebesar {mean_slope}% menunjukkan kondisi medan kelas {slope_class}. "
        f"{focus_sentence}"
        f"Kerapatan drainase {dd} km/km², bentuk DTA {shape}, dan Curve Number {cn} bersama karakter penutupan lahan mendukung kecenderungan respons DTA yang {response} terhadap hujan."
    )
    if land_types:
        paragraph_one = (
            f"Wilayah DTA tersusun atas beberapa sistem lahan dengan karakter yang beragam. Berdasarkan persentase luas hasil irisan, tipe sistem lahan utama berupa {_natural_join(land_types)}. "
            f"Secara fisiografis wilayah ini tersusun terutama oleh {_natural_join(physiographies)}, sedangkan karakter reliefnya berkisar pada {_natural_join(relief_classes)}. Persentase tersebut dihitung terhadap luas DTA, bukan berdasarkan jumlah fitur, sehingga komposisi yang dijelaskan mewakili luasan wilayah yang sebenarnya."
        )
    else:
        paragraph_one = "Data sistem lahan belum tersedia atau tidak beririsan dengan batas DTA, sehingga tipe sistem lahan, fisiografi, dan relief dominan belum dapat diuraikan."
    paragraph_two = (
        f"Berdasarkan kondisi kemiringan, DTA mempunyai kemiringan rata-rata {mean_slope}% dan termasuk kelas {slope_class}, dengan relief topografi sekitar {relief} m. "
        f"Kombinasi fisiografi, relief, dan lereng tersebut memengaruhi pembentukan serta pergerakan limpasan permukaan menuju jaringan sungai yang memiliki kerapatan {dd} km/km² dan orde maksimum Strahler {drainage.get('stream_order_max') or 0}. "
        "Bagian dengan relief lebih kuat dan lereng lebih curam cenderung mempercepat transfer aliran serta meningkatkan peluang erosi, sedangkan bagian yang lebih landai relatif lebih mendukung penyimpanan sementara dan infiltrasi; besar pengaruhnya tetap bergantung pada tanah, penutup lahan, dan kondisi hujan."
    )
    paragraph_three = (
        f"Penutupan lahan DTA terdiri atas pertanian {agriculture}%, hutan {forest}%, kawasan terbangun {built}%, lahan terbuka {open_land}%, dan perairan {water}%. "
        f"Interaksi antara sistem lahan, fisiografi, relief, kemiringan, bentuk DTA {shape}, penutup lahan, serta Curve Number {cn} memberikan gambaran umum karakter fisik wilayah. "
        "Gambaran tersebut menjadi dasar untuk membaca morfometri, keterhubungan jaringan drainase, kecenderungan infiltrasi, erosi, dan respons hidrologis DTA secara indikatif tanpa menyimpulkan kejadian banjir secara deterministik."
    )
    analysis["territory_paragraphs"] = [paragraph_one, paragraph_two, paragraph_three]
    analysis["territory_detail"] = "\n\n".join(analysis["territory_paragraphs"])
    return analysis


def build_hydrologic_analysis(*, geom, outlet, source_crs: Any, area_km2: float, streams,
                              upstream_ids: Iterable[int], upstream_by_downstream: dict[int, list[int]],
                              outlet_linkno: int | None, dem_path: Path | None, plen_path: Path | None,
                              flowdir_path: Path | None = None, landcover_path: Path | None = None, cn_path: Path | None = None,
                              analysis_stream_path: Path | None = None, landsystem_path: Path | None = None) -> dict[str, Any]:
    metric_geom = _metric_geometry(geom, source_crs)
    perimeter_km = float(metric_geom.length / 1000.0)
    terrain = terrain_metrics(geom, outlet, source_crs, dem_path, plen_path, flowdir_path)
    # Delineation remains tied to the 1 km² network. Morphometric drainage metrics
    # deliberately use the independent high-detail analysis stream data when supplied.
    drainage = analysis_stream_metrics(geom, outlet, source_crs, analysis_stream_path, area_km2, dem_path) if analysis_stream_path else drainage_metrics(
        streams, upstream_ids, upstream_by_downstream, outlet_linkno, area_km2
    )
    landcover = landcover_metrics(geom, source_crs, landcover_path, area_km2)
    landsystem = landsystem_metrics(geom, source_crs, landsystem_path)
    curve_number = curve_number_metrics(geom, source_crs, cn_path)
    basin_length_km = terrain.get("longest_flow_path_km") or drainage.get("main_channel_length_km")
    form_factor = area_km2 / basin_length_km**2 if basin_length_km else None
    circularity = (4.0 * math.pi * area_km2) / perimeter_km**2 if perimeter_km > 0 else None
    elongation = (2.0 * math.sqrt(area_km2 / math.pi)) / basin_length_km if basin_length_km else None
    relief_m = (terrain.get("elevation") or {}).get("relief_m")
    relief_ratio = (relief_m / (basin_length_km * 1000.0)) if relief_m is not None and basin_length_km else None
    shape_class = _classify(form_factor, ((0.3, "Sangat memanjang"), (0.5, "Memanjang"), (0.75, "Agak kompak")), "Kompak")
    elongation_class = _classify(
        elongation,
        ((0.5, "Sangat memanjang"), (0.7, "Memanjang"), (0.8, "Agak memanjang"), (0.9, "Oval")),
        "Mendekati membulat",
    )
    dd = drainage.get("drainage_density_km_per_km2")
    dd_class = _classify(dd, ((1.0, "Rendah"), (2.0, "Sedang"), (3.5, "Tinggi")), "Sangat tinggi")
    mean_slope = (terrain.get("slope") or {}).get("mean_pct")
    slope_class = _classify(mean_slope, ((8.0, "Datar"), (15.0, "Landai"), (25.0, "Agak curam"), (40.0, "Curam")), "Sangat curam")

    fast_factors: list[str] = []
    slow_factors: list[str] = []
    score = 0
    if form_factor is not None:
        (fast_factors if form_factor >= 0.5 else slow_factors).append(
            "bentuk DTA lebih kompak" if form_factor >= 0.5 else "bentuk DTA memanjang"
        )
        score += 1 if form_factor >= 0.5 else -1
    if dd is not None:
        (fast_factors if dd >= 2.0 else slow_factors).append(
            "jaringan drainase rapat" if dd >= 2.0 else "kerapatan drainase rendah–sedang"
        )
        score += 1 if dd >= 2.0 else -1
    if mean_slope is not None:
        (fast_factors if mean_slope >= 15.0 else slow_factors).append(
            "lereng relatif curam" if mean_slope >= 15.0 else "lereng relatif landai"
        )
        score += 1 if mean_slope >= 15.0 else -1
    weighted_cn = curve_number.get("weighted_cn_ii")
    if weighted_cn is not None:
        (fast_factors if weighted_cn >= 80 else slow_factors).append(
            "potensi pembentukan limpasan tinggi berdasarkan CN-II" if weighted_cn >= 80 else "retensi permukaan relatif lebih besar berdasarkan CN-II"
        )
        score += 1 if weighted_cn >= 80 else -1
    response_factor_count = len(fast_factors) + len(slow_factors)
    normalized_response_score = (score / response_factor_count) if response_factor_count else 0.0
    response = hydrologic_response_class(normalized_response_score)
    evidence = [*fast_factors, *slow_factors]
    if evidence:
        narrative = (
            f"Secara fisik–morfometrik DTA menunjukkan kecenderungan respons {response.lower()} terhadap hujan. "
            f"Penilaian ini mempertimbangkan {', '.join(evidence[:-1])}{' dan ' if len(evidence) > 1 else ''}{evidence[-1]}. "
            "Kesimpulan ini bersifat indikatif dan tidak menyatakan kejadian banjir atau bentuk recession limb."
        )
    else:
        narrative = "Data yang tersedia belum cukup untuk menyusun interpretasi respons hidrologi."

    morphometry = {
        "area_km2": _round(area_km2, 3), "perimeter_km": _round(perimeter_km, 3),
        "perimeter_basis": "Batas DTA diperhalus",
        "basin_length_km": _round(basin_length_km, 3),
        "basin_length_method": "Lintasan aliran terpanjang" if terrain.get("longest_flow_path_km") else "Panjang alur utama",
        "form_factor": _round(form_factor, 3), "circularity_ratio": _round(circularity, 3),
        "elongation_ratio": _round(elongation, 3), "relief_ratio": _round(relief_ratio, 4),
        "shape_class": shape_class, "elongation_class": elongation_class,
    }
    flow_slope = terrain.get("flowpath_slope") or {}
    elevation = terrain.get("elevation") or {}
    tc = time_of_concentration_metrics(
        area_km2, terrain.get("longest_flow_path_km") or drainage.get("main_channel_length_km"), relief_m, mean_slope, weighted_cn,
        main_channel_length_km=drainage.get("main_channel_length_km"),
        main_channel_slope_pct=drainage.get("main_channel_slope_pct"),
        longest_flowpath_slope_pct=flow_slope.get("longest_flowpath_pct"),
        centroidal_flowpath_km=terrain.get("centroidal_flowpath_km"),
        flowpath_10_85_slope_pct=flow_slope.get("flowpath_10_85_pct"),
        mean_height_above_outlet_m=elevation.get("mean_height_above_outlet_m"),
    )
    lc_summary = landcover.get("summary") or {}
    dominant_system = landsystem.get("dominant") or {}
    slope_text = slope_class.lower() if slope_class else "belum terklasifikasi"
    system_sentence = (
        f"Overlay sistem lahan menunjukkan dominasi {dominant_system.get('land_type', 'tipe lahan yang belum teridentifikasi')} "
        f"pada fisiografi {dominant_system.get('physiography', 'yang belum teridentifikasi')} dengan relief "
        f"{dominant_system.get('relief_class', 'yang belum teridentifikasi')} seluas {dominant_system.get('area_pct', 0):.1f}% DTA"
        if dominant_system else "Informasi sistem lahan dominan belum tersedia"
    )
    narrative = (
        f"Secara fisik–morfometrik DTA seluas {area_km2:.1f} km² dengan bentuk {shape_class.lower() if shape_class else 'belum terklasifikasi'} menunjukkan kecenderungan respons {response.lower()} terhadap hujan. "
        f"{system_sentence}, sedangkan kemiringan rata-rata {mean_slope or 0:.1f}% termasuk kelas {slope_text}. "
        f"Tutupan lahannya terutama berupa pertanian {lc_summary.get('agriculture_pct') or 0:.1f}%, hutan {lc_summary.get('forest_pct') or 0:.1f}%, dan kawasan terbangun {lc_summary.get('built_up_pct') or 0:.1f}%. "
        f"Kerapatan drainase {dd or 0:.2f} km/km² dan Curve Number {weighted_cn or 0:.1f} bersama bentuk DTA serta lereng menjelaskan kecenderungan kecepatan pengumpulan dan pembentukan limpasan. "
        "Sistem lahan dipakai sebagai konteks wilayah, sementara klasifikasi respons tetap merupakan sintesis morfometri, lereng, jaringan drainase, tutupan lahan, dan Curve Number serta bersifat indikatif, bukan prediksi banjir."
    )
    dominant_classes = (landsystem.get("classes") or [])[:5]
    if dominant_classes:
        class_phrases = [
            f"{item['land_type']} pada fisiografi {item['physiography']} dengan relief {item['relief_class']} ({item['area_pct']:.1f}%)"
            for item in dominant_classes
        ]
        system_detail = "; ".join(class_phrases[:-1]) + (f"; dan {class_phrases[-1]}" if len(class_phrases) > 1 else class_phrases[0])
        paragraph_one = (
            f"Hasil overlay berbasis luas memperlihatkan {len(dominant_classes)} kelas sistem lahan paling dominan, yaitu {system_detail}. "
            "Susunan ini menggambarkan variasi material, posisi fisiografi, dan kekasaran relief yang membentuk konteks fisik wilayah tangkapan; persentasenya dihitung dari luas irisan terhadap DTA, bukan jumlah poligon."
        )
    else:
        paragraph_one = "Data sistem lahan belum tersedia atau tidak beririsan dengan batas DTA, sehingga konteks tipe lahan, fisiografi, dan relief belum dapat diuraikan."
    paragraph_two = (
        f"Topografi DTA memiliki kemiringan rata-rata {mean_slope or 0:.1f}% atau kelas {slope_text}, relief {relief_m or 0:.1f} m, dan bentuk {shape_class.lower() if shape_class else 'belum terklasifikasi'}. "
        f"Jaringan sungainya mempunyai kerapatan drainase {dd or 0:.2f} km/km² dengan orde maksimum Strahler {drainage.get('stream_order_max') or 0}. "
        "Kombinasi kemiringan, relief, bentuk, dan kerapatan jaringan mengendalikan jarak serta kecepatan aliran dari lereng menuju saluran utama."
    )
    paragraph_three = (
        f"Penggunaan lahan terdiri atas pertanian {lc_summary.get('agriculture_pct') or 0:.1f}%, hutan {lc_summary.get('forest_pct') or 0:.1f}%, kawasan terbangun {lc_summary.get('built_up_pct') or 0:.1f}%, lahan terbuka {lc_summary.get('open_land_pct') or 0:.1f}%, dan perairan {lc_summary.get('water_pct') or 0:.1f}%. "
        f"Dengan Curve Number {weighted_cn or 0:.1f}, komposisi tersebut memberi indikasi kapasitas retensi dan potensi pembentukan limpasan, tetapi interpretasinya tetap harus dibaca bersama kondisi sistem lahan, lereng, morfometri, dan jaringan drainase."
    )
    territory_paragraphs = [paragraph_one, paragraph_two, paragraph_three]
    result = {
        "schema_version": 7,
        "scope": "Morfometri, jaringan drainase, penutup lahan, sistem lahan, Curve Number, dan waktu konsentrasi",
        "executive_summary": {"response_class": response, "narrative": narrative,
                              "accelerating_factors": fast_factors, "slowing_factors": slow_factors,
                              "response_score_normalized": _round(normalized_response_score, 3),
                              "response_factor_count": response_factor_count},
        "territory_detail": "\n\n".join(territory_paragraphs),
        "territory_paragraphs": territory_paragraphs,
        "key_indicators": {
            "area_km2": morphometry["area_km2"], "mean_slope_pct": mean_slope,
            "relief_total_m": relief_m,
            "drainage_density_km_per_km2": dd,
            "stream_frequency_per_km2": drainage.get("stream_frequency_per_km2"),
            "bifurcation_ratio": drainage.get("bifurcation_ratio"),
            "form_factor": morphometry["form_factor"],
            "longest_flow_path_km": terrain.get("longest_flow_path_km") or drainage.get("main_channel_length_km"),
            "main_channel_slope_pct": drainage.get("main_channel_slope_pct"),
            "curve_number": weighted_cn, "time_of_concentration_hours": tc.get("representative_hours") or tc.get("recommended_hours"),
            "built_up_pct": (landcover.get("summary") or {}).get("built_up_pct"),
        },
        "classifications": {"shape": shape_class, "elongation": elongation_class, "mean_slope": slope_class, "drainage_density": dd_class},
        "morphometry": morphometry, "terrain": terrain, "drainage": drainage,
        "landcover": landcover, "landsystem": landsystem, "curve_number": curve_number,
        "time_of_concentration": tc,
        "limitations": [
            "Interpretasi merupakan kecenderungan morfometrik, bukan prediksi banjir.",
            "Waktu konsentrasi adalah estimasi multi-metode otomatis dan bukan hasil kalibrasi hidrograf; tingkat yang ditampilkan adalah kesepakatan antar-metode, bukan ukuran kepercayaan statistik.",
            "Waktu surut memerlukan informasi geologi, air tanah, aliran dasar, dataran banjir, dan tampungan.",
        ],
    }
    keys = result["key_indicators"]
    result["key_indicator_items"] = [
        {"label": "Luas DTA (A)", "value": keys.get("area_km2"), "unit": "km²"},
        {"label": "Kemiringan rata-rata (S)", "value": keys.get("mean_slope_pct"), "unit": "%"},
        {"label": "Relief DTA (R)", "value": keys.get("relief_total_m"), "unit": "m"},
        {"label": "Kerapatan drainase (Dd)", "value": keys.get("drainage_density_km_per_km2"), "unit": "km/km²"},
        {"label": "Frekuensi sungai (Fs)", "value": keys.get("stream_frequency_per_km2"), "unit": "sungai/km²"},
        {"label": "Rasio percabangan (Rb)", "value": keys.get("bifurcation_ratio"), "unit": ""},
        {"label": "Faktor bentuk (Ff)", "value": keys.get("form_factor"), "unit": ""},
        {"label": "Lintasan aliran terpanjang (Lb)", "value": keys.get("longest_flow_path_km"), "unit": "km"},
        {"label": "Kemiringan alur utama (Sc)", "value": keys.get("main_channel_slope_pct"), "unit": "%"},
        {"label": "Curve Number (CN)", "value": keys.get("curve_number"), "unit": ""},
        {"label": "Waktu konsentrasi (Tc)", "value": keys.get("time_of_concentration_hours"), "unit": "jam"},
        {"label": "Kawasan terbangun", "value": keys.get("built_up_pct"), "unit": "%"},
    ]
    return refresh_characteristic_narratives(result, ",")
