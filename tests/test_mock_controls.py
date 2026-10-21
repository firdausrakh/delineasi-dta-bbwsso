import math
from copy import deepcopy

import pytest

from api.services.hydro_recession import recession_prior,cat_distance
from api.services.hydro_runoff import simulate_runoff
from test_hydro_runoff import point,donor


def spatial(lithology='Endapan Lepas',prod='Produktif Tinggi'):
    return {'features':{'aquifer':{prod:1.}},'coverage':{'aquifer':1.},
        'hydrogeology_context':{
            'lithology':{'available':True,'coverage':1.,'classes':{lithology:1.}},
            'groundwater_availability':{'available':True,'coverage':1.,'classes':{prod:1.}},
            'cat':{'available':True,'coverage':1.,'classes':{'CAT contoh':1.}}}}


def test_recession_gis_formula_units_and_correlated_map_group():
    s=spatial();r=recession_prior(s)
    assert r['available'] and r['tau_days']==pytest.approx(90*(.75+.5*.9))
    assert r['k30']==pytest.approx(math.exp(-30/r['tau_days']))
    # Duplicate productivity information does not multiply its weight.
    s['hydrogeology_context'].pop('groundwater_availability')
    assert recession_prior(s)['k30']==pytest.approx(r['k30'])
    s['hydrogeology_context']['cat']['classes']={'CAT lain':1.}
    assert recession_prior(s)['k30']==pytest.approx(r['k30'])
    assert 'bukan persamaan/koefisien USGS' in r['reference_scope']


@pytest.mark.parametrize('change',['unknown','partial','no_productivity'])
def test_unavailable_recession_prior_is_not_silently_replaced_by_point_six(change):
    s=spatial()
    if change=='unknown':s['hydrogeology_context']['lithology']['classes']={'Tak dikenal':1.}
    elif change=='partial':s['hydrogeology_context']['lithology']['coverage']=.8
    else:s['features']['aquifer']={};s['hydrogeology_context'].pop('groundwater_availability')
    r=recession_prior(s)
    assert not r['available'] and r['k30'] is None
    p=point();p['recession_parameters']=r
    with pytest.raises(ValueError,match='prior resesi GIS tidak tersedia'):
        simulate_runoff([p],[],mock_mode='gis')
    manual=simulate_runoff([p],[],mock_mode='manual',mock_parameters={'A':{'k30':.7}})
    assert manual['results'][0]['model_parameters']['k30']==.7


def test_recession_prior_uses_known_classes_when_unknown_sliver_is_below_coverage_threshold():
    s=spatial()
    s['hydrogeology_context']['lithology']['classes']={'Batuan Volkanik':.999,'Perairan':.001}
    result=recession_prior(s)
    assert result['available']
    assert result['k30']==pytest.approx(math.exp(-30/(75*(.75+.5*.9))))


def test_manual_values_are_used_exactly_without_optimization_and_have_observation_metrics():
    p=point();d=donor(p)
    overrides={'A':{'smc_multiplier':1.4,'infiltration':.23,'k30':.99}}
    original=deepcopy(overrides)
    result=simulate_runoff([p],[d],mock_mode='manual',mock_parameters=overrides)
    params=result['results'][0]['model_parameters']
    assert (params['smc_mm'],params['infiltration'],params['k30'])==(168,.23,.99)
    assert params['calibration_mode']=='manual' and not result['validation']
    assert result['results'][0]['observation_comparison']['count']==24
    assert overrides==original
    gis=simulate_runoff([p],[],mock_mode='gis',mock_parameters=overrides)['results'][0]['model_parameters']
    assert (gis['smc_multiplier'],gis['infiltration'],gis['k30'])==(1.,.55,.6)


def test_auto_bounds_and_fixed_parameters_apply_to_fit_and_transfer():
    a,b=point('A',6),point('B',6)
    overrides={'A':{'smc_multiplier':1.1,'k30':.72},'B':{'smc_multiplier':1.3,'k30':.8}}
    result=simulate_runoff([a,b],[donor(a)],mock_mode='auto',mock_parameters=overrides,
        mock_bounds={'infiltration':[.2,.35]},mock_fit_parameters=['infiltration'])
    for p,smc,k in zip(result['results'],[1.1,1.3],[.72,.8]):
        params=p['model_parameters']
        assert params['smc_multiplier']==smc and params['k30']==k
        assert .2<=params['infiltration']<=.35
        assert params['calibration_active_parameters']==['infiltration']
    assert result['validation']


def test_equal_bounds_lock_parameter_and_custom_ranges_can_exceed_old_defaults():
    p=point()
    result=simulate_runoff([p],[],mock_mode='auto',
        mock_bounds={'smc_multiplier':[3,3],'infiltration':[.2,.2],'k30':[.99,.99]})
    params=result['results'][0]['model_parameters']
    assert (params['smc_multiplier'],params['infiltration'],params['k30'])==(3.,.2,.99)
    assert params['calibration_active_parameters']==[]
    assert set(params['clipped_initial_parameters'])=={'smc_multiplier','infiltration','k30'}


@pytest.mark.parametrize('kwargs',[
    {'mock_bounds':{'infiltration':[.8,.2]}}, {'mock_bounds':{'k30':[0,.9]}},
    {'mock_bounds':{'infiltration':[0,1.1]}}, {'mock_bounds':{'wrong':[0,1]}},
    {'mock_fit_parameters':['k30','k30']}, {'mock_parameters':{'B':{'k30':.6}}},
    {'mock_parameters':{'A':{'k30':True}}}, {'mock_parameters':{'A':{'smc_multiplier':0}}},
])
def test_invalid_manual_or_automatic_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):simulate_runoff([point()],[],**kwargs)


def test_cat_influences_regional_reference_weights_but_not_direct_gis_prior():
    a,b,c=point('A'),point('B'),point('C')
    for p,cat in [(a,'Sama'),(b,'Lain'),(c,'Sama')]:
        p['hydrogeology_context']={'cat':{'available':True,'coverage':1.,'classes':{cat:1.}}}
    assert cat_distance(a,c)==0 and cat_distance(a,b)==1
    result=simulate_runoff([a,b,c],[donor(a),donor(b)],mock_fit_parameters=['infiltration'])
    transferred=result['results'][2]['model_parameters']['parameter_references']
    assert transferred[0]['weight']>transferred[1]['weight']
