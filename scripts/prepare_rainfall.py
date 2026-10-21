"""Inspect the supplied CF NetCDF and preserve it as a dated, multiband COG."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy


QUALITY_NOTE = ('Interpolasi TPS tanpa pembatasan nilai; 30 nilai grid tertinggi perlu diperiksa terhadap stasiun, '
                'terutama di tepi domain. Akumulasi sumber menerima minimal 10 hari valid per periode; '
                'kelengkapan hari per sel tidak tersedia. Nilai asli dipertahankan, tanpa clipping atau imputasi.')


def prepare(source: Path, output: Path, report_dir: Path, crs='EPSG:4326'):
    if source.resolve() == output.resolve():
        raise ValueError('File keluaran harus berbeda dari NetCDF sumber.')
    with rasterio.open(source) as ds:
        tags = ds.tags()
        if tags.get('prcp#units') != 'mm' or ds.tags(1).get('NETCDF_VARNAME') != 'prcp':
            raise ValueError('Diperlukan variabel prcp dengan satuan mm.')
        if tags.get('time#calendar') not in ('standard', 'gregorian', 'proleptic_gregorian'):
            raise ValueError('Kalender NetCDF tidak didukung.')
        match = re.fullmatch(r'days since (\d{4}-\d{2}-\d{2})(?: 00:00:00)?', tags.get('time#units', ''))
        if not match:
            raise ValueError('Satuan waktu NetCDF harus days since tanggal ISO.')
        origin = datetime.fromisoformat(match[1])
        dates = [(origin + timedelta(days=float(ds.tags(b)['NETCDF_DIM_time']))).date() for b in ds.indexes]
        if dates != sorted(set(dates)) or any(d.day not in (1, 16) for d in dates):
            raise ValueError('Periode NetCDF harus unik, berurutan, tanggal 1/16.')
        data = ds.read(masked=True).astype(np.float32).filled(np.nan)
        if np.isinf(data).any() or np.any(data < 0):
            raise ValueError('Hujan negatif/tak hingga: perbaiki sumber sebelum persiapan model.')
        if not np.isfinite(data).any():
            raise ValueError('NetCDF tidak memiliki data hujan valid.')
        grid_crs = ds.crs or rasterio.crs.CRS.from_user_input(crs)
        if not ds.crs and (not grid_crs.is_geographic or not (-180 <= ds.bounds.left < ds.bounds.right <= 180 and -90 <= ds.bounds.bottom < ds.bounds.top <= 90)):
            raise ValueError('CRS sumber tidak tersedia dan batas bukan koordinat geografis.')
        profile = dict(driver='GTiff', width=ds.width, height=ds.height, count=ds.count,
                       dtype='float32', nodata=np.nan, crs=grid_crs, transform=ds.transform)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rainfall-') as temp:
            raw = Path(temp) / 'rainfall.tif'
            with rasterio.open(raw, 'w', **profile) as dest:
                dest.write(data)
                dest.update_tags(units='mm', source=source.name, source_sha256=digest,
                                 description=ds.tags(1).get('description', ''), quality_note=QUALITY_NOTE,
                                 crs_note='CRS dari sumber' if ds.crs else f'CRS ditetapkan {grid_crs} dari grid lon/lat; NetCDF tanpa deklarasi CRS.',
                                 period_definition=tags.get('NC_GLOBAL#period_definition', ''))
                for band, value in enumerate(dates, 1):
                    dest.update_tags(band, period_start=value.isoformat())
                    dest.set_band_description(band, value.isoformat())
            raster_copy(raw, output, driver='COG', compress='DEFLATE', blocksize=128, overview_count=0, BIGTIFF='IF_SAFER')
        with rasterio.open(output) as check:
            if not np.array_equal(data, check.read(), equal_nan=True) or check.transform != ds.transform or check.crs != grid_crs:
                raise RuntimeError('Konversi hujan mengubah nilai/grid.')
        valid = np.isfinite(data)
        ids = np.flatnonzero(valid)
        top = ids[np.argsort(-data.ravel()[ids], kind='stable')[:30]]
        rows = []
        for rank, index in enumerate(top, 1):
            t, r, c = np.unravel_index(index, data.shape)
            day = dates[t]
            end = day.replace(day=15 if day.day == 1 else calendar.monthrange(day.year, day.month)[1])
            x, y = ds.xy(int(r), int(c))
            rows.append(dict(rank=rank, start=day.isoformat(), end=end.isoformat(), rainfall_mm=float(data[t, r, c]),
                             longitude=x, latitude=y, row=int(r), col=int(c),
                             edge_cell=bool(r in (0, ds.height-1) or c in (0, ds.width-1))))
        latitude = np.array([ds.xy(r, 0)[1] for r in range(ds.height)])
        weights = np.broadcast_to(np.cos(np.deg2rad(latitude))[:, None], data.shape[1:])
        if not grid_crs.is_geographic:
            raise ValueError('Laporan domain membutuhkan grid lon/lat.')
        area = np.sum(valid * weights, axis=(1, 2))
        means = np.divide(np.sum(np.where(valid, data, 0)*weights, axis=(1, 2)), area,
                          out=np.full(ds.count, np.nan), where=area > 0)
        periods = [dict(start=dates[t].isoformat(), mean_domain_mm=float(means[t]), coverage=float(valid[t].mean()))
                   for t in np.argsort(-means, kind='stable') if np.isfinite(means[t])][:30]
        summary = dict(source=str(source), source_sha256=digest, output=str(output), unit='mm/tengah bulan',
                       shape=list(data.shape), start=dates[0].isoformat(), end=dates[-1].isoformat(),
                       valid_count=int(valid.sum()), missing_count=int((~valid).sum()), zero_count=int((data == 0).sum()),
                       negative_count=0, max_mm=float(data[valid].max()),
                       all_missing_periods=[dates[t].isoformat() for t in range(ds.count) if not valid[t].any()],
                       top30=rows, top30_period_mean=periods, quality_note=QUALITY_NOTE,
                       domain_note='Rerata seluruh domain grid, bukan rerata DTA; bobot luas proporsional cos(lintang).')
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, values in [('top30_grid', rows), ('top30_period_mean', periods)]:
        with (report_dir / f'{name}.csv').open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    (report_dir / 'rainfall_review.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('top30', 'top30_period_mean')}, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/shared/rainfall.tif')
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--crs', default='EPSG:4326', help='CRS lon/lat saat NetCDF tidak mendeklarasikan CRS.')
    args = parser.parse_args()
    prepare(args.source, args.output, args.report_dir, args.crs)
