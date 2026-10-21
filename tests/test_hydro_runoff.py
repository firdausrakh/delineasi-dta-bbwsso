import calendar
from copy import deepcopy
from datetime import date,timedelta
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest
from shapely.geometry import box

from api.services.hydro_climate import aggregate,daily_rainfall,fetch_et0
from api.services.hydro_model import validate_records,parse_debit_workbook
from api.services.hydro_soil import pedotransfer,soil_parameters,SOIL_RASTERS
from api.services.hydro_runoff import mock,simulate_runoff,q_from_depth
from api.services.hydro_workbook import workbook_bytes


def point(id_='A',years=4,start_year=2000):
    dates=[date(start_year,1,1)+timedelta(days=i) for i in range((date(start_year+years,1,1)-date(start_year,1,1)).days)]
    rain=np.array([6+5*np.cos(2*np.pi*(d.timetuple().tm_yday)/365) for d in dates])
    rows=aggregate(dates,rain,np.full(len(dates),3.))
    return {'point_id':id_,'label':id_,'area_km2':100.,'features':{'terrain':[500,10]},
            'recession_parameters':{'available':True,'k30':.6,'status':'fixture'},
            'soil_parameters':{'smc_mm':120.,'ksat_mm_h':8.,'infiltration':.55,'exposed_fraction':.25,'status':'GIS'},
            'climate':{'rows':rows,'method':'test','rainfall_source':'fixture','coverage_min':1.,'et0':{},'last_complete_period':rows[-1]['start']}}


def donor(p):
    trace=mock(p['climate']['rows'],p['soil_parameters'],[1,.55,.6])
    values=q_from_depth([r['runoff_mm'] for r in trace],p['area_km2'],[r['days'] for r in trace])
    years={}
    for r,q in zip(trace,values):
        years.setdefault(r['year'],[None]*24)[r['period']]=float(q)
    return {'point_id':p['point_id'],'sheet':p['label'],'records':[{'year':y,'values':v} for y,v in years.items()]}


def test_mock_closes_mass_balance_including_dry_periods_and_leap_days():
    p=point()
    rows=p['climate']['rows']
    rows[20]['p_mm']=0;rows[20]['wet_days']=0;rows[20]['et0_mm']=1000
    trace=mock(rows,p['soil_parameters'],[1,.55,.6])
    assert trace[3]['days']==14  # leap-year second half of February
    assert max(abs(r['balance_error_mm']) for r in trace)<1e-10
    assert all(r[k]>=-1e-12 for r in trace for k in ('aet_mm','soil_mm','groundwater_mm','runoff_mm','baseflow_mm'))
    assert all(r['soil_mm']<=120 for r in trace)


def test_soil_units_awc_and_equation_hand_calculation():
    values={'sand':400,'silt':350,'clay':250,'bd':130,'carbon':200,'coarse':100,'swc0033':300,'swc1500':150}
    r=pedotransfer({k:np.full((6,1,1),v,dtype=float) for k,v in values.items()})
    assert r['valid'].all()
    assert r['awc'][0,0,0]==pytest.approx(.135)
    assert r['bulk_density'][0,0,0]==1.3
    assert r['organic_carbon_pct'][0,0,0]==2
    c1=60.96*10**(-.884+.0153*40)*10/24
    c2=60.96*10**(-.6+.0126*40-.0064*25)*10/24
    w=np.exp(7.755+.0352*35+.93-.967*1.3**2-.000484*25**2-.000322*35**2+.001/35-.129/2-.643*np.log(35)-.01398*1.3*25-.0973*1.3*2+.02986*25-.03305*35)*10/24
    wy=np.exp(1.9582+.0308*40-.6142*1.3-.01566*2)*10/24
    assert r['ksat'][0,0,0]==pytest.approx(np.median([c1,c2,w,wy]))


def test_soil_root_depth_and_gis_infiltration_order(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    values={'sand':400,'silt':350,'clay':250,'bd':130,'carbon':200,'coarse':100,'swc0033':300,'swc1500':150}
    for k,v in values.items():
        with rasterio.open(tmp_path/f'{k}.tif','w',driver='GTiff',height=2,width=2,count=6,dtype='float32',crs='EPSG:4326',transform=from_origin(109,-7,.01,.01)) as ds:
            ds.write(np.full((6,2,2),v,dtype='float32'))
    paths={k:tmp_path/f'{k}.tif' for k in SOIL_RASTERS}
    g=box(109,-7.02,109.02,-7)
    forest=soil_parameters(paths,g,'EPSG:4326',0,{'2001':1.})
    steep=soil_parameters(paths,g,'EPSG:4326',30,{'2001':1.})
    urban=soil_parameters(paths,g,'EPSG:4326',0,{'2012':1.})
    assert forest['smc_mm']==pytest.approx(135.)
    assert 0<=urban['infiltration']<forest['infiltration']<=1
    assert steep['infiltration']<forest['infiltration']


def test_wet_days_are_from_daily_areal_rain_and_partial_period_omitted(tmp_path):
    path=tmp_path/'daily.nc'
    with h5py.File(path,'w') as f:
        f['lat']=[-7.01,-6.99];f['lon']=[108.99,109.01]
        t=f.create_dataset('time',data=np.arange(366+30));t.attrs['units']='days since 2000-01-01';t.attrs['calendar']='proleptic_gregorian'
        data=np.full((396,2,2),np.nan,dtype='float32');data[:370,:,0]=.5;data[:370,:,1]=1.5
        r=f.create_dataset('prcp',data=data);r.attrs['units']='mm'
    dates,rain,coverage=daily_rainfall(path,box(108.98,-7.02,109.02,-6.98),'EPSG:4326',2000,2001)
    assert len(dates)==370
    assert np.allclose(rain,1)
    assert coverage==pytest.approx(1)
    rows=aggregate(dates,np.round(rain,8),np.ones(370))
    assert len(rows)==24 and rows[0]['wet_days']==15
    with h5py.File(path,'r+') as f:f['prcp'][20]=np.nan
    with pytest.raises(ValueError,match='cakupan'):
        daily_rainfall(path,box(108.98,-7.02,109.02,-6.98),'EPSG:4326',2000,2001)


@pytest.mark.parametrize('model',['mock','random_forest','xgboost'])
def test_runoff_models_validation_partial_year_export_and_missing_observations(model):
    p=point();target=point('B');target['area_km2']=200
    target['climate']['rows']=target['climate']['rows'][:-6]
    d=donor(p);d['records'][1]['values'][4]=None
    payload=simulate_runoff([p,target],[d],model=model,warmup_years=0)
    json.dumps(payload,allow_nan=False)
    assert payload['validation'] and payload['validation'][0]['count']>=6
    assert payload['results'][1]['records'][-1]['values'][-1] is None
    if model=='mock':
        assert payload['results'][1]['model_parameters']['max_balance_error_mm']<1e-10
        assert payload['validation'][0]['rmse']<1e-4
    else:
        assert payload['results'][1]['records'][0]['values'][:6]==[None]*6
    with zipfile.ZipFile(io.BytesIO(workbook_bytes(payload))) as z:
        for n in z.namelist():
            if n.endswith('.xml'):ET.fromstring(z.read(n))
        assert b'Validasi independen' in z.read('xl/worksheets/sheet2.xml')


def test_ml_spatial_holdout_and_need_observed_data():
    a,b,c=point('A',2),point('B',2),point('C',2)
    payload=simulate_runoff([a,b,c],[donor(a),donor(b)],model='random_forest')
    assert len(payload['validation'])==2
    assert all(v['scheme']=='Leave-one-DTA-out' for v in payload['validation'])
    with pytest.raises(ValueError,match='24 pasangan'):
        simulate_runoff([a],[],model='random_forest')
    assert simulate_runoff([a],[],model='mock',warmup_years=0)['results'][0]['model_parameters']['status'].startswith('Parameter awal GIS')


def test_sparse_workbook_preserves_blanks_and_strict_dar_rejects():
    p=point('A',1);d=donor(p);d['records'][0]['values'][5]=None
    payload=simulate_runoff([p],[d],model='mock',calibrate=False,warmup_years=0)
    blob=workbook_bytes(payload)
    loose=parse_debit_workbook(blob,allow_missing=True)
    assert loose['sheets'][0]['records'][0]['values'][5] is None
    assert parse_debit_workbook(blob)['sheets'][0]['error']
    with pytest.raises(ValueError):validate_records(d['records'])


def test_et0_refuses_missing_and_caches_validated_data(tmp_path,monkeypatch):
    from api.services import hydro_climate
    response={'latitude':-7,'longitude':109,'daily_units':{'et0_fao_evapotranspiration':'mm'},
              'daily':{'time':['2000-01-01','2000-01-02'],'et0_fao_evapotranspiration':[1.,None]}}
    calls=[]
    def open_(*args,**kwargs):calls.append(args);return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(hydro_climate,'urlopen',open_)
    with pytest.raises(ValueError,match='tidak lengkap'):fetch_et0(109,-7,date(2000,1,1),date(2000,1,2),tmp_path)
    assert not list(tmp_path.glob('*.json'))
    response['daily']['et0_fao_evapotranspiration'][1]=2.
    values,meta=fetch_et0(109,-7,date(2000,1,1),date(2000,1,2),tmp_path)
    assert values.tolist()==[1,2] and not meta['cached']
    assert fetch_et0(109,-7,date(2000,1,1),date(2000,1,2),tmp_path)[1]['cached']
    assert len(calls)==2


def test_mock_default_warmup_user_example_continues_state_and_trims_all_outputs():
    p=point(years=16,start_year=2010)
    original=deepcopy(p)
    trace=mock(p['climate']['rows'],p['soil_parameters'],[1,.55,.6])
    payload=simulate_runoff([p],[],calibrate=False)
    r=payload['results'][0]
    assert payload['warmup_years']==3 and payload['years']==list(range(2013,2026))
    assert [rec['year'] for rec in r['records']]==list(range(2013,2026))
    assert r['statistics']['count']==13*24
    assert all(s['count']==13 for s in r['period_statistics'])
    assert r['water_balance']==trace[72:]
    assert r['climate']['rows']==p['climate']['rows'][72:]
    assert r['climate']['simulation_start']=='2010-01-01'
    assert r['climate']['output_start']=='2013-01-01'
    expected=q_from_depth([t['runoff_mm'] for t in trace[72:]],100,[t['days'] for t in trace[72:]])
    assert np.allclose([q for rec in r['records'] for q in rec['values']],expected)
    assert r['volume_m3']==pytest.approx(sum(q*t['days']*86400 for q,t in zip(expected,trace[72:])))
    reset_trace=mock(p['climate']['rows'][72:],p['soil_parameters'],[1,.55,.6])
    assert r['water_balance'][0]['groundwater_mm']!=pytest.approx(reset_trace[0]['groundwater_mm'])
    assert p==original
    with zipfile.ZipFile(io.BytesIO(workbook_bytes(payload))) as z:
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        assert sheet.findtext('.//m:c[@r="A3"]/m:v',namespaces=ns)=='2013'
        assert sheet.findtext('.//m:c[@r="A15"]/m:v',namespaces=ns)=='2025'
        rows=sheet.findall('m:sheetData/m:row',ns)
        weather=next(i for i,row in enumerate(rows) if row.findtext('m:c/m:is/m:t',namespaces=ns)=='Tanggal')
        assert rows[weather+1].findtext('m:c/m:is/m:t',namespaces=ns)=='2013-01-01'


def test_mock_warmup_observations_never_affect_calibration_or_validation():
    p=point(years=6)
    d=donor(p)
    baseline=simulate_runoff([p],[d])
    poisoned=deepcopy(d)
    for rec in poisoned['records'][:3]:rec['values']=[1e9]*24
    result=simulate_runoff([p],[poisoned])
    assert result['results'][0]['model_parameters']==baseline['results'][0]['model_parameters']
    assert result['validation']==baseline['validation']
    assert result['validation'][0]['test_start']>='2003-01-01'
    assert result['validation'][0]['rmse']<1e-4
    only_warmup=deepcopy(d);only_warmup['records']=only_warmup['records'][:3]
    with pytest.raises(ValueError,match='setelah pemanasan'):simulate_runoff([p],[only_warmup])


@pytest.mark.parametrize('warmup',[-1,1.5,True,101])
def test_mock_rejects_invalid_warmup(warmup):
    with pytest.raises(ValueError,match='bilangan bulat'):
        simulate_runoff([point()],[],warmup_years=warmup)


def test_mock_warmup_needs_complete_years_and_remaining_output():
    with pytest.raises(ValueError,match='tidak ada periode keluaran'):
        simulate_runoff([point(years=3)],[])
    p=point();p['climate']['rows'].pop(35)
    with pytest.raises(ValueError,match='lengkap dan berurutan'):
        simulate_runoff([p],[])
    p=point();p['climate']['rows']=p['climate']['rows'][:-6]
    result=simulate_runoff([p],[])['results'][0]
    assert result['records'][0]['year']==2003 and len(result['records'])==1
    assert result['records'][0]['values'][-6:]==[None]*6
    assert result['statistics']['count']==18


def test_mock_zero_warmup_outputs_first_year_and_ml_ignores_mock_warmup():
    p=point(years=2)
    result=simulate_runoff([p],[],warmup_years=0)
    assert result['years']==[2000,2001] and result['results'][0]['statistics']['count']==48
    ml=simulate_runoff([p],[donor(p)],model='random_forest')
    assert ml['years']==[2000,2001] and ml['warmup_years']==0
