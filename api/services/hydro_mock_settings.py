"""Validate manual values and configurable automatic-calibration ranges."""
from __future__ import annotations

import math

PARAMETERS=('smc_multiplier','infiltration','k30')
DEFAULT_BOUNDS={'smc_multiplier':[.5,2.], 'infiltration':[0.,1.], 'k30':[.05,.98]}


def _physical(key,value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{key}: nilai harus angka berhingga.')
    valid=value>0 if key=='smc_multiplier' else 0<=value<=1 if key=='infiltration' else 0<value<1
    if not valid:
        raise ValueError(f'{key}: perlu SMC >0, infiltrasi 0–1, dan resesi 0<k30<1.')
    return float(value)


def configuration(points, *, mode, bounds=None, fit_parameters=None, overrides=None, k30=None):
    if mode not in ('gis','manual','auto'):
        raise ValueError('Mode Mock harus gis, manual, atau auto.')
    bounds=bounds or {}
    if set(bounds)-set(PARAMETERS):
        raise ValueError('Parameter batas kalibrasi Mock tidak dikenal.')
    ranges={key:list(pair) for key,pair in DEFAULT_BOUNDS.items()}
    for key,pair in bounds.items():
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:
            raise ValueError(f'{key}: batas harus berisi minimum dan maksimum.')
        ranges[key]=[_physical(key,value) for value in pair]
    if any(pair[0]>pair[1] for pair in ranges.values()):
        raise ValueError('Minimum parameter Mock harus ≤ maksimum.')
    selected=list(PARAMETERS) if fit_parameters is None else list(fit_parameters)
    if set(selected)-set(PARAMETERS) or len(set(selected))!=len(selected):
        raise ValueError('Pilihan parameter kalibrasi Mock tidak dikenal atau ganda.')
    overrides=overrides or {}
    if set(overrides)-{p['point_id'] for p in points}:
        raise ValueError('Nilai manual Mock merujuk ke DTA yang tidak tersedia.')
    initials={};clipped={}
    for p in points:
        raw=overrides.get(p['point_id'],{})
        if not isinstance(raw,dict) or set(raw)-set(PARAMETERS):
            raise ValueError('Nama parameter manual Mock tidak dikenal.')
        manual={key:_physical(key,value) for key,value in raw.items() if value is not None}
        gis_k=p.get('recession_parameters',{}).get('k30')
        seed={'smc_multiplier':1.,'infiltration':p['soil_parameters']['infiltration'],'k30':gis_k}
        if mode!='gis':
            if k30 is not None:
                seed['k30']=_physical('k30',k30)
            seed.update(manual)
        if seed['k30'] is None:
            raise ValueError(f'{p["label"]}: prior resesi GIS tidak tersedia; ambil/periksa peta hidrogeologi atau isi k30 manual.')
        seed={key:_physical(key,value) for key,value in seed.items()}
        before=dict(seed)
        if mode=='auto':
            for key in selected:
                lo,hi=ranges[key]
                seed[key]=min(hi,max(lo,seed[key]))
        initials[p['point_id']]=[seed[key] for key in PARAMETERS]
        clipped[p['point_id']]=[key for key in PARAMETERS if seed[key]!=before[key]]
    return {'mode':mode,'bounds':ranges,'fit_parameters':selected,
            'active_indices':[j for j,key in enumerate(PARAMETERS) if key in selected and ranges[key][0]<ranges[key][1]],
            'initials':initials,'clipped_initial_parameters':clipped}
