from datetime import date
import io
import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, Point
from shapely.ops import transform
from pyproj import Transformer

from api.services.hydro_rainfall import rainfall_features
from api.services.hydro_spatial import descriptors
from api.services.hydro_model import group_distance, simulate
from api.services.hydro_workbook import workbook_bytes


def rainfall_grid(tmp_path, data=None):
    path = tmp_path / 'rainfall.tif'
    data = np.tile([10., 30.], (24, 1, 1)).astype('float32') if data is None else data
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=1, count=len(data),
                       dtype='float32', nodata=np.nan, crs='EPSG:4326', transform=from_origin(109, -7, .02, .02)) as ds:
        ds.write(data)
        ds.update_tags(units='mm', source='fixture.nc', source_sha256='abc', quality_note='TPS test')
        for band in ds.indexes:
            year = 2020 + (band-1)//24
            period = (band-1) % 24
            ds.update_tags(band, period_start=date(year, period//2+1, 1 if period%2 == 0 else 16).isoformat())
    return path


def test_fractional_cell_area_and_tiny_dta(tmp_path):
    path = rainfall_grid(tmp_path)
    result = rainfall_features(path, box(109.015, -7.02, 109.04, -7), 'EPSG:4326', [2020])
    assert result['coverage_min'] == pytest.approx(1)
    assert result['records'][0]['values'] == pytest.approx([26]*24)
    assert result['mean_annual_mm'] == pytest.approx(26*24)
    projected = transform(Transformer.from_crs(4326, 32749, always_xy=True).transform,
                          box(109.015, -7.02, 109.04, -7))
    assert rainfall_features(path, projected, 'EPSG:32749', [2020])['records'][0]['values'] == pytest.approx([26]*24)
    tiny = rainfall_features(path, box(109.001, -7.002, 109.002, -7.001), 'EPSG:4326', [2020])
    assert tiny['records'][0]['values'] == pytest.approx([10]*24)


def test_rainfall_missing_data_is_not_zero_and_dates_must_match(tmp_path):
    data = np.tile([10., 30.], (24, 1, 1)).astype('float32')
    data[1] = np.nan
    path = rainfall_grid(tmp_path, data)
    geom = box(109, -7.02, 109.04, -7)
    with pytest.raises(ValueError, match='2020-01-16.*0.0%'):
        rainfall_features(path, geom, 'EPSG:4326', [2020])
    with pytest.raises(ValueError, match='2021-01-01'):
        rainfall_features(path, geom, 'EPSG:4326', [2021])
    with pytest.raises(ValueError, match='luar cakupan'):
        rainfall_features(path, box(110, -7.02, 110.1, -7), 'EPSG:4326', [2020])


def test_coverage_checks_full_dta_not_only_intersected_grid(tmp_path):
    path = rainfall_grid(tmp_path)
    with pytest.raises(ValueError, match='minimal 95%'):
        rainfall_features(path, box(108.98, -7.02, 109.04, -7), 'EPSG:4326', [2020])


def test_zero_rain_valid_negative_and_bad_metadata_rejected(tmp_path):
    path = rainfall_grid(tmp_path, np.zeros((24, 1, 2), dtype='float32'))
    geom = box(109, -7.02, 109.04, -7)
    assert rainfall_features(path, geom, 'EPSG:4326', [2020])['mean_annual_mm'] == 0
    with rasterio.open(path, 'r+') as ds:
        ds.write(np.array([[-1., 0.]], dtype='float32'), 1)
    with pytest.raises(ValueError, match='negatif'):
        rainfall_features(path, geom, 'EPSG:4326', [2020])
    with rasterio.open(path, 'r+') as ds:
        ds.update_tags(units='mm/day')
    with pytest.raises(ValueError, match='satuan mm'):
        rainfall_features(path, geom, 'EPSG:4326', [2020])


def test_rainfall_distance_and_area_only_baseline():
    assert group_distance([0, 0], [0, 0], 'rainfall') == 0
    assert group_distance([0, 10], [10, 0], 'rainfall') == 1
    assert group_distance([10, 10], [20, 20], 'rainfall') == pytest.approx(1/3)
    with pytest.raises(ValueError, match='sejajar'):
        group_distance([10], [10, 10], 'rainfall')
    points = [dict(point_id=p, label=p, area_km2=100, features={'rainfall': rain})
              for p, rain in [('A', [10]*24), ('B', [30]*24), ('T', [10]*24)]]
    donors = [dict(point_id=p, sheet=p, records=[{'year':2020, 'values':[q]*24}]) for p,q in [('A',10),('B',30)]]
    baseline = simulate(points, donors)['results'][0]
    weighted = simulate(points, donors, groups=['rainfall'])
    assert baseline['statistics']['mean'] == 20
    assert weighted['results'][0]['donors'][0]['weight'] > .5
    assert weighted['results'][0]['statistics']['mean'] < 20
    single = simulate(points, donors[:1], groups=['rainfall'])
    assert single['results'][-1]['records'][0]['values'] == [10]*24


def test_zonal_rainfall_model_and_export_keep_inputs(tmp_path):
    path = rainfall_grid(tmp_path)
    points = []
    for name, geom in [('A',box(109,-7.02,109.02,-7)), ('T',box(109.02,-7.02,109.04,-7))]:
        spatial = descriptors(geom, 'EPSG:4326', Point(109,-7), {'rainfall':path}, ['rainfall'], rainfall_years=[2020])
        points.append(dict(point_id=name, label=name, area_km2=100, **spatial))
    model = simulate(points, [dict(point_id='A',sheet='A', records=[{'year':2020,'values':[10]*24}])], groups=['rainfall'])
    target = model['results'][0]
    assert target['rainfall']['mean_annual_mm'] == pytest.approx(720)
    assert target['donors'][0]['rainfall']['mean_annual_mm'] == pytest.approx(240)
    assert target['records'][0]['values'] == [10]*24
    with zipfile.ZipFile(io.BytesIO(workbook_bytes(model))) as archive:
        xml = archive.read('xl/worksheets/sheet2.xml').decode()
        assert 'fixture.nc' in xml and 'SHA256 sumber' in xml and 'TPS test' in xml
        assert 'Hujan T' in xml and 'Hujan A' in xml


def test_r2_export_preserves_rainfall_dates_values_and_nan_signature(tmp_path):
    from scripts.export_local_to_r2 import export_hydro_assets
    from scripts.verify_r2 import _raster_content_signature
    source = tmp_path/'source'
    source.mkdir()
    path = rainfall_grid(source)
    destination = tmp_path/'bundle'
    assert export_hydro_assets(source, destination) == {'rainfall':'shared/rainfall.tif'}
    assert _raster_content_signature(path) == _raster_content_signature(destination/'rainfall.tif')
    with rasterio.open(destination/'rainfall.tif') as ds:
        assert ds.tags(24)['period_start'] == '2020-12-16'
        assert ds.tags()['source_sha256'] == 'abc'
