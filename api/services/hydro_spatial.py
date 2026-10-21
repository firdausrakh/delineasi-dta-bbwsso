"""Native-resolution descriptors for reference/target similarity."""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.mask import mask
from rasterio.features import geometry_mask
from shapely import union_all, from_wkb
from shapely.geometry import Point, box
from shapely.ops import transform

from api.services.hydrologic_analysis import terrain_metrics
from api.services.hydro_rainfall import rainfall_features

SOIL_LAYERS = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200)]
MODEL_RASTERS = ('sand', 'silt', 'clay')
MODEL_VECTORS = ('produktivitas_akuifer', 'litologi_akuifer', 'cekungan_air_tanah', 'ketersediaan_air_tanah', 'landcover')


def project(geom, source, target):
    return transform(Transformer.from_crs(source, target, always_xy=True).transform, geom)


def distribution(path: Path, layer: str | None, field: str, geom, crs, *, minimum_coverage=.95, relative_to_dta=False):
    info = gpd.read_file(path, layer=layer, rows=0)
    if info.crs is None or field not in info.columns:
        raise ValueError(f'{path.name}: CRS/atribut {field} tidak tersedia.')
    query = project(geom, crs, info.crs)
    frame = gpd.read_file(path, layer=layer, bbox=query.bounds)
    frame = frame[frame.intersects(query)].to_crs(crs)
    if frame.empty:
        return ({} if minimum_coverage == 0 else None), 0.
    frame = frame.copy()
    frame.geometry = frame.geometry.intersection(geom)
    covered = union_all(frame.geometry.to_numpy()).area / geom.area
    if covered < minimum_coverage:
        return None, covered
    grouped = {}
    for category, group in frame.groupby(field, dropna=False):
        name = str(category) if not pd.isna(category) else 'Tidak diketahui'
        grouped[name] = union_all(group.geometry.to_numpy()).area
    total = sum(grouped.values())
    if total > geom.area * 1.02:
        raise ValueError(f'{path.name}: kelas saling overlap; periksa sumber sebelum pembobotan.')
    if not total:
        return ({} if minimum_coverage == 0 else None), float(covered)
    if minimum_coverage and grouped.get('Tidak diketahui', 0) / total > .05:
        return None, covered
    denominator = geom.area if relative_to_dta else total
    return {k: float(v / denominator) for k, v in grouped.items() if v > 0}, float(min(covered, 1))


def soil_features(paths, geom, crs, depth):
    if depth not in (30, 100, 200):
        raise ValueError('Kedalaman tanah harus 30, 100, atau 200 cm.')
    arrays = []
    weights = []
    for name in MODEL_RASTERS:
        path = paths.get(name)
        if path is None or not Path(path).exists():
            return None
        with rasterio.open(path) as ds:
            if ds.count != 6 or ds.crs is None:
                raise ValueError(f'{name}: diperlukan enam band SoilGrids dengan CRS valid.')
            query = project(geom, crs, ds.crs)
            if query.intersection(box(*ds.bounds)).area / query.area < .95:
                return None
            try:
                a, tr = mask(ds, [query.__geo_interface__], crop=True, filled=False)
            except ValueError:
                return None
            signature = (str(ds.crs), tuple(tr), a.shape)
            if arrays and signature != grid:
                raise ValueError('Grid pasir, debu, dan lempung harus sama.')
            grid = signature
            arrays.append(a.astype(float))
            if not weights:
                if CRS(ds.crs).is_geographic:
                    lat = tr.f + (np.arange(a.shape[1]) + .5) * tr.e
                    cell_weights = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], a.shape[1:])
                else:
                    cell_weights = np.ones(a.shape[1:])
                weights.append(cell_weights)
    thicknesses = [max(0, min(end, depth) - start) for start, end in SOIL_LAYERS]
    values = np.stack([a.filled(np.nan) for a in arrays])
    valid = np.all(np.isfinite(values) & (values >= 0) & (values <= 1000), axis=0)
    valid &= np.abs(values.sum(axis=0) - 1000) <= 50
    means = np.zeros(3)
    for band, thickness in enumerate(thicknesses):
        if not thickness:
            continue
        inside = geometry_mask([query.__geo_interface__], out_shape=values.shape[2:], transform=tr, invert=True)
        count = int(inside.sum())
        if not count or valid[band].sum() / count < .95:
            return None
        for i in range(3):
            means[i] += float(np.average(values[i, band][valid[band]], weights=weights[0][valid[band]])) / 10 * thickness / depth
    return means.tolist()


def descriptors(geom, crs, outlet, paths, groups, *, soil_depth=30, rainfall_years=()):
    signatures = tuple(sorted((name, str(path), Path(path).stat().st_mtime_ns if Path(path).exists() else None)
                              for name, path in paths.items() if path is not None))
    return _cached_descriptors(geom.wkb, str(crs), (outlet.x, outlet.y), signatures, tuple(groups), soil_depth, tuple(rainfall_years))


@lru_cache(maxsize=64)
def _cached_descriptors(wkb, crs, outlet_xy, signatures, groups, soil_depth, rainfall_years):
    geom = from_wkb(wkb)
    outlet = Point(*outlet_xy)
    paths = {name: Path(path) for name, path, _ in signatures}
    result = {'features': {}, 'warnings': [], 'coverage': {}, 'hydrogeology_context': {}}
    if 'rainfall' in groups:
        path = paths.get('rainfall')
        result['features']['rainfall'] = None
        if path is not None and path.exists() and rainfall_years:
            rainfall = rainfall_features(path, geom, crs, rainfall_years)
            result['rainfall'] = rainfall
            result['features']['rainfall'] = [value for row in rainfall['records'] for value in row['values']]
            result['coverage']['rainfall'] = rainfall['coverage_min']
            if rainfall['quality_note']:
                result['warnings'].append(rainfall['quality_note'])
    for key, name, field in [('aquifer', 'produktivitas_akuifer', 'prod'), ('landcover', 'landcover', 'PL2024_ID')]:
        if key not in groups:
            continue
        path = paths.get('hydro_vectors') or paths.get(name)
        if path is None or not Path(path).exists():
            result['features'][key] = None
            continue
        values, coverage = distribution(Path(path), name if paths.get('hydro_vectors') else None, field, geom, crs)
        result['features'][key] = values
        result['coverage'][key] = coverage
        if coverage < .999:
            result['warnings'].append(f'Cakupan {key}: {coverage:.1%}; ambang kelayakan 95%.')
    context_layers=[('cat', 'cekungan_air_tanah', 'namobj', 'CAT'),
                    ('lithology', 'litologi_akuifer', 'litologi', 'Litologi')]
    if 'recession' in groups:
        context_layers.append(('groundwater_availability','ketersediaan_air_tanah','PROD','Ketersediaan air tanah'))
    for key, name, field, label in context_layers:
        path = paths.get('hydro_vectors') or paths.get(name)
        context = {'available': False, 'classes': {}, 'coverage': None}
        if path is not None and Path(path).exists():
            try:
                values, coverage = distribution(Path(path), name if paths.get('hydro_vectors') else None,
                                                field, geom, crs, minimum_coverage=0, relative_to_dta=True)
                context = {'available': True, 'classes': values, 'coverage': coverage}
                if key == 'lithology' and coverage < .95:
                    result['warnings'].append('Cakupan konteks litologi kurang dari 95%; pemeriksaan batuan hanya mencakup sebagian DTA.')
                if key == 'lithology' and any('gamping' in category.casefold() and fraction > 0 for category, fraction in values.items()):
                    result['warnings'].append('Batugamping terpetakan; periksa potensi karst dan aliran bawah tanah lintas DTA. Peta ini belum membuktikan konektivitas aliran.')
            except (ValueError, OSError, RuntimeError) as exc:
                result['warnings'].append(f'Konteks {label} tidak dapat dibaca: {exc}')
        else:
            result['warnings'].append(f'Konteks {label} tidak tersedia.')
        result['hydrogeology_context'][key] = context
    if 'soil' in groups:
        result['features']['soil'] = soil_features(paths, geom, crs, soil_depth)
    if 'terrain' in groups:
        path = paths.get('dem')
        if path is None or not Path(path).exists():
            result['features']['terrain'] = None
        else:
            with rasterio.open(path) as ds:
                query = project(geom, crs, ds.crs)
                coverage = query.intersection(box(*ds.bounds)).area / query.area
            metrics = terrain_metrics(geom, outlet, crs, Path(path), None)
            elevation = (metrics.get('elevation') or {}).get('mean_m')
            slope = (metrics.get('slope') or {}).get('mean_pct')
            result['features']['terrain'] = [elevation, slope] if coverage >= .95 and elevation is not None and slope is not None else None
    return result
