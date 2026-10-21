import io
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from api.services.hydro_model import EXCEEDANCES, MONTHS, parse_debit_workbook, percentile_exc, simulate
from api.services.hydro_workbook import workbook_bytes


def records(years=(2020, 2021), value=10):
    return [{'year': y, 'values': [value] * 24} for y in years]


def point(id, area, features=None):
    return {'point_id': id, 'label': id, 'area_km2': area, 'features': features or {}}


def donor(id, value=10, years=(2020, 2021)):
    return {'point_id': id, 'sheet': id, 'records': records(years, value)}


def fixture_xlsx(*, second_header='II', rows=None):
    output = io.BytesIO()
    def text(ref, value):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    first = text('A1', 'Tahun') + ''.join(text(f'{chr(66+i*2)}1', m) for i, m in enumerate(MONTHS))
    second = ''.join(text(f'{chr(66+i)}2', 'I' if i % 2 == 0 else second_header) for i in range(24))
    data = ''.join(f'<row r="{r}"><c r="A{r}"><v>{year}</v></c>'+''.join(f'<c r="{chr(66+i)}{r}"><v>{v}</v></c>' for i, v in enumerate(values) if v is not None)+'</row>' for r, (year, values) in enumerate(rows or [(2020, [0]+[10]*23)], 3))
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Donor A" sheetId="4" r:id="r4"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r4" Target="worksheets/sheet4.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet4.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">'+first+'</row><row r="2">'+second+'</row>'+data+'</sheetData></worksheet>')
    return output.getvalue()


def test_parser_uses_relationships_and_preserves_zero():
    sheet = parse_debit_workbook(fixture_xlsx())['sheets'][0]
    assert sheet['name'] == 'Donor A'
    assert sheet['error'] is None
    assert sheet['records'][0]['values'][0] == 0


def test_upload_statistics_exclude_missing_but_keep_zero():
    values = [0, 2, 4] + [None] * 21
    sheet = parse_debit_workbook(fixture_xlsx(rows=[(2020, values)]), allow_missing=True)['sheets'][0]
    s = sheet['statistics']
    assert s['count'] == 3 and s['missing_count'] == 21 and s['zero_count'] == 1
    assert (s['min'], s['max'], s['mean'], s['median'], s['std'], s['cv']) == (0, 4, 2, 2, 2, 1)
    assert s['quantiles']['Q50'] == 2
    assert s['quantiles']['Q95'] is None


def test_upload_statistics_single_observation_and_invalid_sheet():
    sheet = parse_debit_workbook(fixture_xlsx(rows=[(2020, [0] + [None] * 23)]), allow_missing=True)['sheets'][0]
    assert sheet['statistics']['mean'] == 0
    assert sheet['statistics']['std'] is None
    assert sheet['statistics']['cv'] is None
    invalid = parse_debit_workbook(fixture_xlsx(rows=[(2020, [-1] * 24)]))['sheets'][0]
    assert invalid['error'] and 'statistics' not in invalid


@pytest.mark.parametrize('options, message', [
    ({'second_header': 'I'}, 'header'),
    ({'rows': [(2020, [10]*24), (2020, [20]*24)]}, 'ganda'),
    ({'rows': [(2020.5, [10]*24)]}, 'Tahun tidak valid'),
    ({'rows': [(2020, [None]+[10]*23)]}, 'tidak boleh kosong'),
    ({'rows': [(2020, [-1]+[10]*23)]}, 'angka'),
])
def test_parser_rejects_invalid_selected_sheets(options, message):
    assert message in parse_debit_workbook(fixture_xlsx(**options))['sheets'][0]['error']


def test_area_transfer_and_day_weighted_volume():
    model = simulate([point('A', 100), point('B', 200)], [donor('A', years=(2020,))])
    target = model['results'][0]
    assert target['records'][0]['values'] == [20]*24
    assert target['statistics']['quantiles']['Q25'] == 20
    assert list(target['statistics']['quantiles']) == [f'Q{p}' for p in EXCEEDANCES]
    assert target['volume_m3'] == 20*366*86400
    assert percentile_exc([1], 95) is None
    assert percentile_exc(range(1, 13), 90) == pytest.approx(1.3)


def test_multi_donor_weights_vary_by_target_and_intersect_years():
    points = [point('A', 100, {'aquifer': {'x':1}}), point('B', 100, {'aquifer': {'y':1}}),
              point('C', 100, {'aquifer': {'x':1}}), point('D', 100, {'aquifer': {'y':1}})]
    model = simulate(points, [donor('A', 10), donor('B', 30, (2021, 2022))], groups=['aquifer'])
    assert model['years'] == [2021]
    c, d = model['results']
    assert c['donors'][0]['weight'] == pytest.approx(1/(1+np.exp(-1)))
    assert c['statistics']['mean'] < d['statistics']['mean']
    assert len(model['validation']) == 2
    baseline = simulate(points, [donor('A',10),donor('B',30)])
    assert baseline['results'][0]['statistics']['mean'] == 20


def test_zeros_and_missing_parameters_are_not_silently_filled():
    p = [point('A',100),point('B',200)]
    target = simulate(p,[donor('A',0)])['results'][0]
    assert target['statistics']['zero_count'] == 48
    assert target['statistics']['cv'] is None
    with pytest.raises(ValueError, match='parameter tidak tersedia'):
        simulate(p,[donor('A')],groups=['soil'])
    with pytest.raises(ValueError, match='irisan'):
        simulate([*p,point('C',100)],[donor('A',years=(2020,)),donor('B',years=(2021,))])
    with pytest.raises(ValueError, match='sheet'):
        simulate([*p,point('C',100)],[donor('A'),dict(donor('B'),sheet='A')])


def test_context_changes_warnings_but_not_weights_or_discharge():
    points = [point('A', 100, {'aquifer': {'x': 1}}), point('B', 100, {'aquifer': {'y': 1}}),
              point('C', 100, {'aquifer': {'x': 1}})]
    inputs = [donor('A', 10), donor('B', 30)]
    baseline = simulate(points, inputs, groups=['aquifer'])['results'][0]
    for p in points:
        p['hydrogeology_context'] = {'cat': {'available': True, 'coverage': 1, 'classes': {p['label']: 1}},
                                    'lithology': {'available': True, 'coverage': 1, 'classes': {'Batugamping': 1}}}
    result = simulate(points, inputs, groups=['aquifer'])['results'][0]
    assert result['records'] == baseline['records']
    assert [d['weight'] for d in result['donors']] == [d['weight'] for d in baseline['donors']]
    assert any('CAT terpetakan berbeda' in warning for warning in result['warnings'])
    assert result['hydrogeology_context'] == points[-1]['hydrogeology_context']
    with pytest.raises(ValueError, match='Parameter model tidak dikenal'):
        simulate(points, inputs, groups=['aquifer', 'lithology'])


def test_context_overlay_preserves_partial_cat_coverage_and_works_in_area_only_mode(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box, Point
    from api.services.hydro_spatial import descriptors
    source = tmp_path / 'context.gpkg'
    gpd.GeoDataFrame({'namobj': ['CAT A']}, geometry=[box(0, 0, 25, 100)], crs='EPSG:32749').to_file(source, layer='cekungan_air_tanah')
    gpd.GeoDataFrame({'litologi': ['Batugamping']}, geometry=[box(0, 0, 100, 100)], crs='EPSG:32749').to_file(source, layer='litologi_akuifer')
    context = descriptors(box(0, 0, 100, 100), 'EPSG:32749', Point(0, 0), {'hydro_vectors': source}, [])
    assert context['features'] == {}
    assert context['hydrogeology_context']['cat']['classes'] == {'CAT A': .25}
    assert context['hydrogeology_context']['cat']['coverage'] == .25
    assert any('Batugamping' in warning for warning in context['warnings'])
    missing = descriptors(box(0, 0, 100, 100), 'EPSG:32749', Point(0, 0), {}, [])
    assert missing['hydrogeology_context']['cat']['available'] is False
    assert missing['hydrogeology_context']['cat']['coverage'] is None


def test_export_includes_reference_inputs_and_formula_based_target_outputs():
    model = simulate([point('A',100),point('B',200),point('C',300)],[donor('A')])
    with zipfile.ZipFile(io.BytesIO(workbook_bytes(model))) as z:
        ns = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        workbook = ET.fromstring(z.read('xl/workbook.xml'))
        assert [sheet.get('name') for sheet in workbook.findall('m:sheets/m:sheet', ns)] == ['A', 'B', 'C']
        reference = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        assert float(reference.findtext('.//m:c[@r="B3"]/m:v', namespaces=ns)) == 10
        assert reference.find('.//m:c[@r="B3"]', ns).get('s') == '6'
        assert reference.findtext('.//m:c[@r="AA1"]/m:is/m:t', namespaces=ns) == 'Pengisian dilakukan pada kolom kuning'
        assert reference.find('.//m:c[@r="AA1"]', ns).get('s') == '7'
        root = ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
        assert root.findtext('.//m:c[@r="AA1"]/m:is/m:t', namespaces=ns) == 'Kolom hijau merupakan hasil model'
        assert root.find('.//m:c[@r="AA1"]', ns).get('s') == '8'
        assert root.findtext('.//m:c[@r="AA4"]/m:is/m:t', namespaces=ns) == 'Ringkasan'
        assert root.findtext('.//m:c[@r="AA5"]/m:is/m:t', namespaces=ns) == 'Q10%'
        assert root.find('.//m:c[@r="A3"]', ns).get('s') == '4'
        value = root.find('.//m:c[@r="B3"]', ns)
        assert value.get('s') == '3'
        assert float(value.findtext('m:v',namespaces=ns)) == 20
        assert "'A'!B3" in value.findtext('m:f', namespaces=ns)
        assert any('0.75' in (e.text or '') for e in root.findall('.//m:f',ns))
        assert b'Arial' in z.read('xl/styles.xml')
        assert b'FF92D050' in z.read('xl/styles.xml')
        assert b'FFFFFF00' in z.read('xl/styles.xml')
        assert b'[&lt;10]0.00;[&lt;100]0.0;0' in z.read('xl/styles.xml')
        for file in z.namelist():
            if file.endswith('.xml'):
                ET.fromstring(z.read(file))


def test_soil_layer_weighting_and_cog_preserve_base_values(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box
    from api.services.hydro_spatial import soil_features
    from scripts.export_local_to_r2 import export_hydro_assets
    source = tmp_path/'source';source.mkdir()
    for name, values in [('sand',[100,200,300,400,400,400]),('silt',[300]*6),('clay',[600,500,400,300,300,300])]:
        with rasterio.open(source/f'{name}.tif','w',driver='GTiff',width=4,height=4,count=6,dtype='int16',crs='EPSG:32749',transform=from_origin(400000,9200000,250,250)) as ds:
            for band, value in enumerate(values,1):ds.write(np.full((4,4),value,dtype=np.int16),band)
    paths = {name:source/f'{name}.tif' for name in ['sand','silt','clay']}
    value = soil_features(paths,box(400000,9199000,401000,9200000),'EPSG:32749',30)
    assert value[0] == pytest.approx((10*5+20*10+30*15)/30)
    output = tmp_path/'output'
    assets = export_hydro_assets(source,output)
    assert set(assets) == {'sand','silt','clay'}
    for name in assets:
        with rasterio.open(paths[name]) as a,rasterio.open(output/f'{name}.tif') as b:
            assert np.array_equal(a.read(),b.read())
            assert b.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'


@pytest.mark.parametrize('include_rainfall', [False, True])
def test_r2_model_upload_preserves_active_manifest_and_publishes_last(tmp_path, monkeypatch, include_rainfall):
    import hashlib
    import json
    import sys
    from scripts import upload_r2
    runtime = tmp_path/'runtime';(runtime/'shared').mkdir(parents=True)
    names = ('hydro_vectors','sand','silt','clay') + (('rainfall',) if include_rainfall else ())
    spec, objects = {}, {}
    for name in names:
        key = f'shared/{name}.gpkg' if name == 'hydro_vectors' else f'shared/{name}.tif'
        payload = name.encode()
        (runtime/key).write_bytes(payload)
        spec[name] = key
        objects[key] = {'sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload),'role':name}
    (runtime/'manifest.json').write_text(json.dumps({'active_dataset':'test','datasets':{'test':spec},'objects':objects}))
    calls = []
    class Client:
        def get_object(self,**kwargs):
            return {'Body':io.BytesIO(json.dumps({'schema_version':4,'active_dataset':'test','datasets':{'test':{'engine':'existing.gpkg'}},'map_assets':{'rivers':'existing.geojson'},'objects':{}}).encode())}
        def upload_file(self,*args,**kwargs):calls.append(('upload',args))
        def put_object(self,**kwargs):calls.append(('manifest',json.loads(kwargs['Body'])))
    monkeypatch.setattr(upload_r2,'_r2_client',lambda:Client())
    monkeypatch.setattr(upload_r2,'load_project_dotenv',lambda root:None)
    monkeypatch.setenv('R2_RUNTIME_BUCKET','test-bucket')
    monkeypatch.setenv('HYDRO_DATASET','test')
    monkeypatch.setenv('R2_MANIFEST_KEY','manifest.json')
    monkeypatch.setattr(sys,'argv',['upload_r2','--bundle',str(tmp_path),'--hydro-only'])
    assert upload_r2.main() == 0
    assert [c[0] for c in calls] == ['upload']*len(names)+['manifest']
    published=calls[-1][1]
    assert published['datasets']['test']['engine']=='existing.gpkg'
    assert published['map_assets']['rivers']=='existing.geojson'
    if include_rainfall:
        assert published['datasets']['test']['rainfall'] == 'shared/rainfall.tif'
    calls.clear();(runtime/spec['sand']).write_bytes(b'bad')
    with pytest.raises(RuntimeError,match='Checksum'):
        upload_r2.main()
    assert not calls
