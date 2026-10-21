"""Semimonthly drainage-area transfer; no rainfall or fitted regression."""
from __future__ import annotations

import calendar
import io
import math
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Ags', 'Sep', 'Okt', 'Nov', 'Des']
EXCEEDANCES = [10, 20, 25, 30, 40, 50, 60, 70, 80, 90, 95]
GROUPS = ('aquifer', 'soil', 'landcover', 'terrain', 'rainfall')
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def validate_records(records, *, allow_missing=False):
    years = {}
    current_year = datetime.now(ZoneInfo('Asia/Jakarta')).year
    for record in records:
        raw = record.get('year')
        try:
            year = float(raw)
        except (TypeError, ValueError):
            raise ValueError('Tahun harus berupa bilangan bulat.') from None
        if isinstance(raw, bool) or not math.isfinite(year) or not year.is_integer() or not 1000 <= year <= current_year:
            raise ValueError(f'Tahun tidak valid: {raw}.')
        year = int(year)
        if year in years:
            raise ValueError(f'Tahun/periode ganda: {year}.')
        values = record.get('values', [])
        if len(values) != 24:
            raise ValueError(f'Tahun {year}: wajib memiliki 24 periode tengah bulanan.')
        clean = []
        for period, value in enumerate(values):
            if allow_missing and value is None:
                clean.append(None)
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{year} {MONTHS[period // 2]} {"I" if period % 2 == 0 else "II"}: debit harus angka ≥ 0, tidak boleh kosong.')
            clean.append(float(value))
        years[year] = clean
    if not years:
        raise ValueError('Sheet tidak berisi data debit.')
    if allow_missing and not any(v is not None for row in years.values() for v in row):
        raise ValueError('Sheet tidak berisi debit pengamatan numerik.')
    return years


def parse_debit_workbook(payload: bytes, *, allow_missing=False):
    """Read workbook relationships, including files whose first tab is not sheet1.xml."""
    if len(payload) > 10 * 1024 * 1024:
        raise ValueError('Ukuran Excel maksimal 10 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 80 * 1024 * 1024:
                raise ValueError('Isi Excel setelah dekompresi terlalu besar (maksimal 80 MB).')
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                strings = [''.join(e.itertext()) for e in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', NS)]
            relationships = {e.get('Id'): e.get('Target') for e in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
            book = ET.fromstring(archive.read('xl/workbook.xml'))
            sheets = []
            for tab in book.findall('m:sheets/m:sheet', NS):
                name = tab.get('name', '')
                rid = tab.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target = relationships.get(rid, '')
                path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
                if not path.startswith('xl/worksheets/'):
                    raise ValueError('Referensi sheet Excel tidak valid.')
                root = ET.fromstring(archive.read(path))
                cells = {}
                for cell in root.findall('m:sheetData/m:row/m:c', NS):
                    typ = cell.get('t')
                    text = cell.findtext('m:v', '', NS)
                    if typ == 's':
                        value = strings[int(text)] if text else ''
                    elif typ == 'inlineStr':
                        value = ''.join(cell.find('m:is', NS).itertext())
                    elif typ in ('b', 'e', 'str'):
                        value = text
                    else:
                        value = float(text) if text else None
                    cells[cell.get('r')] = None if isinstance(value,str) and not value.strip() else value
                try:
                    if str(cells.get('A1', '')).strip().lower() != 'tahun':
                        raise ValueError('A1 harus berisi Tahun, sesuai template.')
                    for p in range(24):
                        col = chr(66 + p)
                        if str(cells.get(f'{col}2', '')).strip() != ('I' if p % 2 == 0 else 'II'):
                            raise ValueError(f'Kolom {col}: header periode tidak lengkap/berubah.')
                        if p % 2 == 0 and str(cells.get(f'{col}1', '')).strip().lower() != MONTHS[p // 2].lower():
                            raise ValueError(f'Kolom {col}: urutan bulan tidak sesuai template.')
                    row_numbers = sorted({int(k[1:]) for k in cells if k.startswith('A') and k[1:].isdigit() and int(k[1:]) >= 3} |
                                         {int(k[1:]) for k, v in cells.items() if k[0] in 'BCDEFGHIJKLMNOPQRSTUVWXY' and k[1:].isdigit() and int(k[1:]) >= 3 and v is not None})
                    records = []
                    for r in row_numbers:
                        values = [cells.get(f'{chr(66 + p)}{r}') for p in range(24)]
                        year = cells.get(f'A{r}')
                        if year is None and all(v is None for v in values):
                            continue
                        records.append({'year': year, 'values': values})
                    validated = validate_records(records, allow_missing=allow_missing)
                    observed = [v for row in validated.values() for v in row if v is not None]
                    sheets.append({'name': name, 'records': [{'year': y, 'values': v} for y, v in sorted(validated.items())],
                                   'statistics': {**statistics(observed), 'missing_count': len(validated) * 24 - len(observed)}, 'error': None})
                except ValueError as exc:
                    sheets.append({'name': name, 'records': [], 'error': str(exc)})
            if not sheets:
                raise ValueError('Workbook tidak memiliki sheet.')
            return {'sheets': sheets, 'unit': 'm³/det'}
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, TypeError, OverflowError) as exc:
        raise ValueError('File .xlsx rusak atau bukan workbook yang didukung.') from exc


def percentile_exc(values, exceedance):
    values = np.asarray(values, dtype=float).ravel()
    p = 1 - exceedance / 100
    # Excel EXC rejects ranks outside the observed sample, rather than clipping.
    rank = (len(values) + 1) * p
    if not len(values) or rank < 1 - 1e-12 or rank > len(values) + 1e-12:
        return None
    return float(np.quantile(values, p, method='weibull'))


def statistics(values):
    a = np.asarray(values, dtype=float)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else None
    return {'count': int(a.size), 'zero_count': int((a == 0).sum()), 'min': float(a.min()), 'max': float(a.max()),
            'mean': mean, 'median': float(np.median(a)), 'std': std, 'cv': std / mean if mean > 0 and std is not None else None,
            'quantiles': {f'Q{p}': percentile_exc(a, p) for p in EXCEEDANCES}}


def group_distance(a, b, group):
    if group == 'rainfall':
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        if a.ndim != 1 or a.shape != b.shape or not a.size or not np.isfinite(a).all() or not np.isfinite(b).all() or np.any(a < 0) or np.any(b < 0):
            raise ValueError('Deret hujan harus sejajar, lengkap, non-negatif, dan berhingga.')
        total = float(a.sum() + b.sum())
        return float(np.abs(a-b).sum() / total) if total else 0.
    if group in ('aquifer', 'landcover'):
        return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in a.keys() | b.keys()) / 2
    # Fixed physical scales avoid fitting many coefficients to a handful of references.
    scales = [100, 100, 100] if group == 'soil' else [1000, 100]
    return sum(min(abs(x - y) / scale, 1) for x, y, scale in zip(a, b, scales)) / len(scales)


def simulate(points, donors, *, b=1.0, groups=(), soil_depth=30, source_file='', validate=True):
    if not math.isfinite(b) or not 0 < b <= 3:
        raise ValueError('Eksponen luas b harus > 0 dan ≤ 3.')
    if set(groups) - set(GROUPS):
        raise ValueError('Parameter model tidak dikenal.')
    if len(set(groups)) != len(groups):
        raise ValueError('Parameter model ganda.')
    ids = [p['point_id'] for p in points]
    if len(ids) != len(set(ids)):
        raise ValueError('ID DTA ganda.')
    donor_ids = [d['point_id'] for d in donors]
    if not donor_ids or len(donor_ids) != len(set(donor_ids)) or not set(donor_ids) <= set(ids):
        raise ValueError('Pilih DTA referensi yang valid dan tidak ganda.')
    if len(donors) > 1 and len({d['sheet'] for d in donors}) != len(donors):
        raise ValueError('Satu sheet hanya boleh dipasangkan ke satu DTA referensi.')
    data = {d['point_id']: validate_records(d['records']) for d in donors}
    years = sorted(set.intersection(*(set(v) for v in data.values())))
    if not years:
        raise ValueError('Tidak ada irisan tahun pencatatan seluruh DTA referensi.')
    lookup = {p['point_id']: p for p in points}
    for p in points:
        if not math.isfinite(p['area_km2']) or p['area_km2'] <= 0:
            raise ValueError('Luas DTA harus positif.')
        missing = [g for g in groups if p.get('features', {}).get(g) is None]
        if missing:
            raise ValueError(f'{p["label"]}: parameter tidak tersedia: {", ".join(missing)}. Nonaktifkan parameter tersebut atau lengkapi sumber data.')
    results = []
    for target in points:
        if target['point_id'] in donor_ids:
            continue
        distances = [sum(group_distance(target['features'][g], lookup[d['point_id']]['features'][g], g) for g in groups) / len(groups) if groups else 0 for d in donors]
        raw = np.exp(-np.asarray(distances))
        weights = raw / raw.sum()
        transfers = [np.array([data[d['point_id']][y] for y in years]) * (target['area_km2'] / lookup[d['point_id']]['area_km2']) ** b for d in donors]
        if any(not np.isfinite(a).all() for a in transfers):
            raise ValueError('Besaran debit/rasio luas melampaui rentang angka yang dapat dihitung.')
        values = sum(w * a for w, a in zip(weights, transfers))
        warnings = list(target.get('warnings', []))
        if len(donors) == 1 and groups:
            warnings.append('Satu referensi: kemiripan hanya pemeriksaan kesesuaian; bobot selalu 1.')
        if min(years) + len(years) - 1 != max(years):
            warnings.append('Irisan tahun tidak berurutan; tahun yang tidak tersedia tidak diisi.')
        for donor in donors:
            target_cat = target.get('hydrogeology_context', {}).get('cat', {})
            reference_cat = lookup[donor['point_id']].get('hydrogeology_context', {}).get('cat', {})
            if target_cat.get('available') and reference_cat.get('available'):
                target_names = set(target_cat.get('classes', {})) - {'Tidak diketahui'}
                reference_names = set(reference_cat.get('classes', {})) - {'Tidak diketahui'}
                if target_names and reference_names and not target_names & reference_names:
                    warnings.append(f'CAT terpetakan berbeda dari {lookup[donor["point_id"]]["label"]}; periksa kesesuaian hidrogeologi. Beda CAT tidak otomatis menolak referensi.')
                elif not target_names or not reference_names:
                    warnings.append(f'CAT tidak terpetakan pada salah satu DTA terhadap {lookup[donor["point_id"]]["label"]}; kesamaan sistem air tanah belum dapat dinilai.')
            ratio = target['area_km2'] / lookup[donor['point_id']]['area_km2']
            if ratio < .5 or ratio > 2:
                warnings.append(f'Rasio luas terhadap {lookup[donor["point_id"]]["label"]}: {ratio:.3f}; periksa kesesuaian transfer.')
        for g in groups:
            if g in ('soil', 'terrain'):
                donor_features = np.asarray([lookup[d['point_id']]['features'][g] for d in donors])
                x = np.asarray(target['features'][g])
                if np.any(x < donor_features.min(axis=0)) or np.any(x > donor_features.max(axis=0)):
                    warnings.append(f'Ekstrapolasi {g}: karakteristik target di luar rentang referensi.')
        monthly = []
        for period in range(24):
            monthly.append({'period': period + 1, **statistics(values[:, period])})
        volume = 0.
        for row, year in zip(values, years):
            for period, q in enumerate(row):
                days = 15 if period % 2 == 0 else calendar.monthrange(year, period // 2 + 1)[1] - 15
                volume += float(q) * days * 86400
        results.append({'point_id': target['point_id'], 'label': target['label'], 'area_km2': target['area_km2'],
                        'records': [{'year': y, 'values': row.tolist()} for y, row in zip(years, values)],
                        'statistics': statistics(values), 'period_statistics': monthly, 'volume_m3': volume,
                        'features': target.get('features', {}), 'warnings': warnings,
                        'rainfall': target.get('rainfall'),
                        'hydrogeology_context': target.get('hydrogeology_context', {}),
                        'donors': [{'point_id': d['point_id'], 'label': lookup[d['point_id']]['label'], 'sheet': d['sheet'],
                                    'area_km2': lookup[d['point_id']]['area_km2'], 'weight': float(w), 'distance': float(dist),
                                    'features': lookup[d['point_id']].get('features', {}), 'warnings': lookup[d['point_id']].get('warnings', []),
                                    'rainfall': lookup[d['point_id']].get('rainfall'),
                                    'hydrogeology_context': lookup[d['point_id']].get('hydrogeology_context', {})}
                                   for d, w, dist in zip(donors, weights, distances)],
                        'donor_transfer_range': {'min': np.minimum.reduce(transfers).tolist(), 'max': np.maximum.reduce(transfers).tolist()}})
    if not results:
        raise ValueError('Sisakan minimal satu DTA target yang tidak dipilih sebagai referensi.')
    validation = []
    if validate and len(donors) > 1:
        for held in donors:
            remaining = [d for d in donors if d['point_id'] != held['point_id']]
            predicted = simulate([lookup[d['point_id']] for d in donors], remaining, b=b, groups=groups,
                                 soil_depth=soil_depth, validate=False)['results'][0]
            predicted_data = {r['year']: r['values'] for r in predicted['records']}
            observed = np.asarray([data[held['point_id']][y] for y in years])
            estimated = np.asarray([predicted_data[y] for y in years])
            obs_q50 = percentile_exc(observed, 50)
            pred_q50 = percentile_exc(estimated, 50)
            if groups:
                baseline = simulate([lookup[d['point_id']] for d in donors], remaining, b=b, groups=(), validate=False)['results'][0]
                baseline_data = {r['year']: r['values'] for r in baseline['records']}
                baseline_q50 = percentile_exc([baseline_data[y] for y in years], 50)
            else:
                baseline_q50 = pred_q50
            validation.append({'point_id': held['point_id'], 'label': lookup[held['point_id']]['label'],
                               'observed_q50': obs_q50, 'predicted_q50': pred_q50,
                               'ape_q50_pct': abs(pred_q50 - obs_q50) / obs_q50 * 100 if obs_q50 > 0 else None,
                               'baseline_q50': baseline_q50, 'baseline_ape_q50_pct': abs(baseline_q50-obs_q50)/obs_q50*100 if obs_q50>0 else None,
                               'rmse': float(np.sqrt(np.mean((estimated-observed)**2))), 'bias': float(np.mean(estimated-observed))})
    return {'method': 'DAR' if len(donors) == 1 else 'Weighted DAR', 'b': b, 'groups': list(groups), 'soil_depth_cm': soil_depth,
            'unit': 'm³/det', 'source_file': source_file, 'years': years, 'results': results,
            # Keep the original reference series available to the workbook exporter.
            # Its target sheets can then show the transfer as an auditable Excel formula.
            'references': [{'point_id': d['point_id'], 'label': lookup[d['point_id']]['label'], 'sheet': d['sheet'],
                            'area_km2': lookup[d['point_id']]['area_km2'],
                            'records': [{'year': year, 'values': values} for year, values in sorted(data[d['point_id']].items())]}
                           for d in donors],
            'weight_convention': 'w=exp(-d)/sum(exp(-d)); d=rerata jarak kelompok; tanah/100%; elevasi/1000m; lereng/100%; hujan=sum(abs(Ptarget-P_referensi))/sum(Ptarget+P_referensi) pada periode yang sejajar. Hidrogeologi berbobot: produktivitas akuifer saja; CAT dan litologi hanya konteks.',
            'rainfall_convention': 'Hujan rerata areal pada irisan tahun debit digunakan untuk kemiripan referensi; tidak mengalikan debit dengan rasio hujan. Kelompok berbobot setara; belum dikalibrasi.' if 'rainfall' in groups else '',
            'validation': validation,
            'validation_note': 'Dengan dua referensi, LOOCV hanya menguji transfer satu referensi dan tidak menguji manfaat pembobotan. Referensi bersarang tidak independen.' if len(donors) == 2 else 'LOOCV memakai irisan tahun bersama. Hasil pada sedikit referensi belum membuktikan akurasi umum.'}
