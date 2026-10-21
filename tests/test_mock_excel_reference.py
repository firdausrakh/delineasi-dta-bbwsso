"""Controlled comparison against the user's monthly FJ MOCK workbook.

The fixture preserves cached source values, including its wet-day approximation,
ET correction, 28-day leap February, and external baseflow. No spreadsheet engine
or external source file is required by the regression tests.
"""
import csv
import json
from pathlib import Path

import pytest

from api.services.hydro_runoff import mock, q_from_depth


def reference():
    with (Path(__file__).parent/'fixtures/fj_mock_excel_reference.csv').open(encoding='utf-8',newline='') as stream:
        settings=json.loads(stream.readline()[2:])
        rows=[{key:value if key=='start' else float(value) for key,value in row.items()} for row in csv.DictReader(stream)]
    return settings,rows


def test_replay_original_excel_arithmetic_matches_all_84_cached_months():
    p,rows=reference()
    s,g=p['initial_soil_mm'],p['initial_groundwater_mm']
    assert len(rows)==84
    for r in rows:
        et=r['ep_mm']*(1-r['m']/20*(18-r['wet_days']))
        new_s=min(p['smc_mm'],max(s+r['p_mm']-et,0))
        surplus=max(r['p_mm']-et-max(new_s-s,0),0)
        infiltration=p['i']*surplus
        new_g=p['k_month']*g+.5*(1+p['k_month'])*infiltration
        baseflow=infiltration-(new_g-g)
        direct=surplus-infiltration
        q=float(q_from_depth(direct+baseflow,p['area_km2'],r['days']))+r['external_baseflow_m3s']
        for actual,expected in [(et,r['et_mm']),(new_s,r['soil_mm']),(surplus,r['surplus_mm']),
                                (new_g,r['groundwater_mm']),(q,r['q_m3s'])]:
            assert actual==pytest.approx(expected,abs=1e-10),r['start']
        s,g=new_s,new_g


def test_production_mock_routing_matches_excel_when_inputs_and_recession_are_aligned():
    p,rows=reference()
    s,g=p['initial_soil_mm'],p['initial_groundwater_mm']
    soil={'smc_mm':p['smc_mm'],'exposed_fraction':0.}
    for r in rows:
        # Feed the Excel ET demand directly (m=0), isolate routing, and convert its
        # fixed monthly k to our duration-normalized k30 for this particular month.
        weather={'start':r['start'],'days':r['days'],'p_mm':r['p_mm'],
                 'et0_mm':r['et_mm'],'wet_days':r['wet_days']}
        k30=p['k_month']**(30/r['days'])
        actual=mock([weather],soil,[1,p['i'],k30],initial_soil_mm=s,initial_groundwater_mm=g)[0]
        for key in ('soil_mm','recharge_mm','groundwater_mm','baseflow_mm','direct_mm','runoff_mm'):
            assert actual[key]==pytest.approx(r[key],abs=1e-10),(r['start'],key)
        # The external 0.75 m3/s belongs only to the reference comparison, not to
        # the production water budget.
        q=float(q_from_depth(actual['runoff_mm'],p['area_km2'],r['days']))+r['external_baseflow_m3s']
        assert q==pytest.approx(r['q_m3s'],abs=1e-10)
        assert abs(actual['balance_error_mm'])<1e-10
        s,g=actual['soil_mm'],actual['groundwater_mm']


def test_original_workbook_et_differences_remain_explicit_not_silently_copied():
    p,rows=reference()
    january=rows[0]
    soil={'smc_mm':p['smc_mm'],'exposed_fraction':january['m']}
    r=mock([{'days':january['days'],'p_mm':january['p_mm'],'et0_mm':january['ep_mm'],
             'wet_days':january['wet_days']}],soil,[1,p['i'],p['k_month']],
             initial_soil_mm=p['initial_soil_mm'],initial_groundwater_mm=p['initial_groundwater_mm'])[0]
    assert january['et_mm']==pytest.approx(134.226125)
    assert r['aet_mm']==pytest.approx(103.85)
    assert sum(row['et_mm']>row['ep_mm'] for row in rows)==80
    assert r['aet_mm']<=january['p_mm']+p['initial_soil_mm']
