"""Semimonthly rainfall: exact cell intersections and auditable reference similarity."""
from __future__ import annotations

from datetime import date

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform


def band_dates(ds):
    if ds.crs is None or ds.tags().get('units') != 'mm':
        raise ValueError('Raster hujan memerlukan CRS dan satuan mm per tengah bulan.')
    dates = []
    for band in ds.indexes:
        try:
            value = date.fromisoformat(ds.tags(band)['period_start'])
        except (KeyError, ValueError):
            raise ValueError('Band hujan harus memiliki tanggal period_start ISO.') from None
        if value.day not in (1, 16):
            raise ValueError('Tanggal hujan harus tanggal 1 atau 16.')
        dates.append(value)
    if dates != sorted(set(dates)):
        raise ValueError('Periode hujan tidak berurutan atau ganda.')
    return dates


def cell_weights(ds, geom, crs):
    """Return a bounded raster window, cell-intersection areas, and full DTA area."""
    if ds.transform.b or ds.transform.d or ds.transform.a <= 0 or ds.transform.e >= 0:
        raise ValueError('Grid hujan harus north-up tanpa rotasi.')
    query = transform(Transformer.from_crs(crs, ds.crs, always_xy=True).transform, geom)
    overlap = query.intersection(box(*ds.bounds))
    if overlap.is_empty:
        raise ValueError('DTA berada di luar cakupan grid hujan.')
    raw = from_bounds(*overlap.bounds, transform=ds.transform)
    col0, row0 = max(0, int(np.floor(raw.col_off))), max(0, int(np.floor(raw.row_off)))
    col1 = min(ds.width, int(np.ceil(raw.col_off + raw.width)))
    row1 = min(ds.height, int(np.ceil(raw.row_off + raw.height)))
    window = Window(col0, row0, col1-col0, row1-row0)
    to_area = Transformer.from_crs(ds.crs, 'EPSG:6933', always_xy=True).transform
    target = transform(to_area, query)
    weights = np.zeros((row1-row0, col1-col0))
    for r in range(row0, row1):
        for c in range(col0, col1):
            left, top = ds.transform * (c, r)
            right, bottom = ds.transform * (c+1, r+1)
            weights[r-row0, c-col0] = transform(to_area, box(left, bottom, right, top)).intersection(target).area
    return window, weights, target.area


def rainfall_features(path, geom, crs, years):
    """Area weights include boundary-cell fractions; missing area is never zero rain."""
    with rasterio.open(path) as ds:
        dates = band_dates(ds)
        by_date = {value: band for band, value in enumerate(dates, 1)}
        requested = [date(year, month, day) for year in years for month in range(1, 13) for day in (1, 16)]
        missing = [d.isoformat() for d in requested if d not in by_date]
        if missing:
            raise ValueError(f'Hujan tidak tersedia untuk periode {missing[0]}.')
        window, weights, target_area = cell_weights(ds, geom, crs)
        data = ds.read([by_date[d] for d in requested], window=window, masked=True).astype(float).filled(np.nan)
        inside = weights > 0
        if np.any((np.isinf(data) | (data < 0)) & inside):
            raise ValueError('Hujan mengandung nilai negatif/tak hingga pada DTA; periksa sumber.')
        valid = np.isfinite(data)
        areas = np.sum(valid * weights, axis=(1, 2))
        coverage = np.minimum(areas / target_area, 1.)
        bad = np.flatnonzero(coverage < .95)
        if bad.size:
            i = int(bad[0])
            raise ValueError(f'Cakupan hujan valid {requested[i].isoformat()}: {coverage[i]:.1%} luas DTA, minimal 95%. Tidak diisi nol.')
        means = np.sum(np.where(valid, data, 0) * weights, axis=(1, 2)) / areas
        records = [{'year': year, 'values': means[i*24:(i+1)*24].tolist()} for i, year in enumerate(years)]
        metadata = ds.tags()
        return {
            'source': metadata.get('source', path.name), 'source_sha256': metadata.get('source_sha256', ''),
            'description': metadata.get('description', ''), 'quality_note': metadata.get('quality_note', ''),
            'unit': 'mm/tengah bulan', 'years': list(years), 'coverage_min': float(coverage.min()),
            'mean_annual_mm': float(means.sum() / len(years)), 'records': records,
            'spatial_method': 'Rerata areal berbobot luas irisan sel–DTA pada EPSG:6933; cakupan valid ≥95% setiap periode.',
        }
