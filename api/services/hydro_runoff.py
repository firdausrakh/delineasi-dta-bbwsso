"""GIS-initialized Mock and supervised runoff-depth models at half-month steps."""
from __future__ import annotations

import math
import numpy as np
from .hydro_model import validate_records, statistics, EXCEEDANCES
from .hydro_mock_settings import configuration as mock_configuration, PARAMETERS
from .hydro_recession import cat_distance


def mock(rows, soil, params, *, initial_soil_mm=None, initial_groundwater_mm=0.):
    """Conservative Mock variant: moisture-limited ET, duration-adjusted recession.

    The original monthly exposed-surface correction uses wet days normalized to
    30 days. No storm-flow percentage is added: it would create water unless
    explicitly deducted from other components.
    """
    scale,infiltration,k30=map(float,params)
    capacity=float(soil['smc_mm'])*scale
    if not np.isfinite([capacity,infiltration,k30]).all() or capacity<=0 or not 0<=infiltration<=1 or not 0<k30<1:
        raise ValueError('Parameter Mock di luar batas fisik.')
    m=float(soil['exposed_fraction'])
    if not 0<=m<=1:
        raise ValueError('Fraksi lahan terbuka harus 0–1.')
    moisture=capacity/2 if initial_soil_mm is None else float(initial_soil_mm)
    groundwater=float(initial_groundwater_mm)
    if not np.isfinite([moisture,groundwater]).all() or not 0<=moisture<=capacity or groundwater<0:
        raise ValueError('Kondisi awal tampungan Mock tidak valid.')
    def step(row):
        nonlocal moisture,groundwater
        p,et0,days,wet=map(float,(row['p_mm'],row['et0_mm'],row['days'],row['wet_days']))
        if not np.isfinite([p,et0,days,wet]).all() or p<0 or et0<0 or days<=0 or not 0<=wet<=days:
            raise ValueError('Input iklim Mock tidak valid.')
        prev_s,prev_g=moisture,groundwater
        limited=et0*(1-m/20*max(18-wet*30/days,0))
        aet=min(limited,p+moisture)
        available=p+moisture-aet
        moisture=min(capacity,available)
        surplus=max(available-capacity,0.)
        recharge=surplus*infiltration
        direct=surplus-recharge
        k=k30**(days/30)
        groundwater=k*groundwater+.5*(1+k)*recharge
        baseflow=recharge-(groundwater-prev_g)
        runoff=direct+baseflow
        residual=p-aet-runoff-(moisture-prev_s)-(groundwater-prev_g)
        return {**row,'aet_mm':aet,'soil_mm':moisture,'groundwater_mm':groundwater,
                'recharge_mm':recharge,'direct_mm':direct,'baseflow_mm':baseflow,'runoff_mm':runoff,
                'balance_error_mm':residual}
    return [step(row) for row in rows]


def q_from_depth(depth,area,days):
    return np.asarray(depth)*float(area)*1000/(np.asarray(days)*86400)


def metrics(observed,predicted):
    o,p=np.asarray(observed,float),np.asarray(predicted,float)
    if not len(o) or o.shape!=p.shape or not np.isfinite(o).all() or not np.isfinite(p).all():
        raise ValueError('Pasangan validasi debit tidak valid.')
    den=float(((o-o.mean())**2).sum())
    kge=None
    if len(o)>1 and o.std()>0 and p.std()>0 and o.mean()>0:
        r=float(np.corrcoef(o,p)[0,1])
        kge=float(1-np.sqrt((r-1)**2+(p.std()/o.std()-1)**2+(p.mean()/o.mean()-1)**2))
    return {'count':len(o),'rmse':float(np.sqrt(np.mean((p-o)**2))), 'bias':float((p-o).mean()),
            'nse':float(1-((p-o)**2).sum()/den) if den>0 else None,'kge':kge,
            'pbias_pct':float(100*(p-o).sum()/o.sum()) if o.sum()>0 else None}


def safe_stats(values):
    clean=[v for v in values if v is not None and math.isfinite(v)]
    if clean:
        return statistics(clean)
    return {'count':0,'zero_count':0,**{k:None for k in ('min','max','mean','median','std','cv')},
            'quantiles':{f'Q{q}':None for q in EXCEEDANCES}}


def _observations(points,donors):
    ids={p['point_id'] for p in points}
    if len(ids)!=len(points) or any(not math.isfinite(p['area_km2']) or p['area_km2']<=0 for p in points):
        raise ValueError('ID DTA harus unik dan luas harus positif.')
    if len({d['point_id'] for d in donors})!=len(donors) or len({d['sheet'] for d in donors})!=len(donors):
        raise ValueError('DTA dan sheet referensi tidak boleh dipasangkan ganda.')
    data={}
    for d in donors:
        if d['point_id'] not in ids:
            raise ValueError('DTA referensi tidak ditemukan.')
        years=validate_records(d['records'],allow_missing=True)
        data[d['point_id']]={(y,j):v for y,values in years.items() for j,v in enumerate(values) if v is not None}
    return data


def _fit_mock(point,observations,initial,controls,indices=None):
    from scipy.optimize import least_squares
    rows=point['climate']['rows']
    positions=[i for i,r in enumerate(rows) if (r['year'],r['period']) in observations]
    if indices is not None:
        positions=list(indices)
    if len(positions)<24:
        raise ValueError(f'{point["label"]}: kalibrasi Mock membutuhkan ≥24 pasangan debit–iklim setelah pemanasan.')
    actual=np.array([observations[(rows[i]['year'],rows[i]['period'])] for i in positions])
    active=controls['active_indices']
    seed=np.array(initial,dtype=float)
    def expand(values):
        params=seed.copy();params[active]=values
        return params
    def residual(values):
        params=expand(values)
        trace=mock(rows,point['soil_parameters'],params)
        predicted=q_from_depth([trace[i]['runoff_mm'] for i in positions],point['area_km2'],[rows[i]['days'] for i in positions])
        return (predicted-actual)/max(float(actual.mean()),.01)
    if not active:
        return seed
    lower=[controls['bounds'][PARAMETERS[j]][0] for j in active]
    upper=[controls['bounds'][PARAMETERS[j]][1] for j in active]
    fit=least_squares(residual,seed[active],bounds=(lower,upper),max_nfev=100)
    if not fit.success or not np.isfinite(fit.x).all():
        raise ValueError(f'{point["label"]}: kalibrasi Mock tidak konvergen; periksa debit dan iklim.')
    return expand(fit.x)


def _ml_features(point):
    rows=point['climate']['rows']
    soil=point['soil_parameters']
    elevation,slope=point['features']['terrain']
    static=[soil['smc_mm'],soil['ksat_mm_h'],soil['infiltration'],soil['exposed_fraction'],elevation,slope]
    rain=np.array([r['p_mm'] for r in rows])
    # Only earlier rain is used; initial lags are omitted rather than zero-filled.
    return {i:[r['p_mm'],r['et0_mm'],r['wet_days']/r['days'],r['days'],
               rain[i-1],rain[i-2],rain[i-3],float(rain[i-6:i].sum()),
               math.sin(2*math.pi*r['period']/24),math.cos(2*math.pi*r['period']/24),*static]
            for i,r in enumerate(rows) if i>=6}


def _estimator(model):
    if model=='random_forest':
        from sklearn.ensemble import RandomForestRegressor
        return RandomForestRegressor(n_estimators=160,max_depth=12,min_samples_leaf=3,n_jobs=1,random_state=42)
    from xgboost import XGBRegressor
    return XGBRegressor(n_estimators=200,max_depth=3,learning_rate=.04,objective='reg:squarederror',n_jobs=1,random_state=42)


def simulate_runoff(points,donors,*,model='mock',calibrate=True,k30=None,source_file='',warmup_years=3,
                    mock_mode=None,mock_parameters=None,mock_bounds=None,mock_fit_parameters=None):
    if model not in ('mock','random_forest','xgboost'):
        raise ValueError('Model hujan–debit tidak dikenal.')
    observations=_observations(points,donors)
    validation=[]
    predictions={}
    parameters={}
    traces={}
    if model=='mock':
        mode=mock_mode or ('auto' if calibrate else 'manual')
        controls=mock_configuration(points,mode=mode,bounds=mock_bounds,fit_parameters=mock_fit_parameters,
                                    overrides=mock_parameters,k30=k30)
        if isinstance(warmup_years,bool) or not isinstance(warmup_years,int) or not 0<=warmup_years<=100:
            raise ValueError('Pemanasan Mock harus bilangan bulat 0–100 tahun.')
        output_starts={}
        for p in points:
            rows=p['climate']['rows']
            if not rows:
                raise ValueError('Deret iklim Mock kosong.')
            first_year=rows[0]['year']
            output_start=first_year+warmup_years
            expected=[(y,j) for y in range(first_year,output_start) for j in range(24)]
            actual=[(r['year'],r['period']) for r in rows if r['year']<output_start]
            if actual!=expected:
                raise ValueError(f'{p["label"]}: iklim untuk {warmup_years} tahun pemanasan harus lengkap dan berurutan.')
            if not any(r['year']>=output_start for r in rows):
                raise ValueError(f'{p["label"]}: tidak ada periode keluaran setelah pemanasan; perpanjang rentang iklim atau kurangi tahun pemanasan.')
            output_starts[p['point_id']]=output_start
        fitted={}
        if mode=='auto' and controls['active_indices']:
            for p in points:
                obs=observations.get(p['point_id'],{})
                if not obs:
                    continue
                rows=p['climate']['rows']
                indices=[i for i,r in enumerate(rows) if r['year']>=output_starts[p['point_id']] and (r['year'],r['period']) in obs]
                if len(indices)>=48:
                    split=max(24,int(len(indices)*.75))
                    fit=_fit_mock(p,obs,controls['initials'][p['point_id']],controls,indices[:split])
                    trace=mock(rows,p['soil_parameters'],fit)
                    test=indices[split:]
                    predicted=q_from_depth([trace[i]['runoff_mm'] for i in test],p['area_km2'],[rows[i]['days'] for i in test])
                    actual=[obs[(rows[i]['year'],rows[i]['period'])] for i in test]
                    validation.append({'point_id':p['point_id'],'label':p['label'],'scheme':'Temporal 75% awal / 25% akhir setelah pemanasan',
                        'test_start':rows[test[0]]['start'],'test_end':rows[test[-1]]['start'],**metrics(actual,predicted)})
                fitted[p['point_id']]=_fit_mock(p,obs,controls['initials'][p['point_id']],controls,indices)
        for p in points:
            params=np.array(controls['initials'][p['point_id']])
            status='Parameter awal GIS/masukan pengguna, tanpa kalibrasi regional tervalidasi.'
            if mode=='manual':
                status='Simulasi parameter manual; tidak menjalankan optimisasi otomatis.'
            elif mode=='gis':
                status='Parameter awal GIS; tanpa optimisasi atau penggantian nilai manual.'
            transfer=[]
            if p['point_id'] in fitted:
                params=fitted[p['point_id']]
                status='Kalibrasi debit lokal; model akhir memakai seluruh pengamatan yang beririsan.'
            elif fitted:
                donors_p=[q for q in points if q['point_id'] in fitted]
                raw=[]
                for q in donors_p:
                    a,b=p['soil_parameters'],q['soil_parameters']
                    distance=abs(math.log(a['smc_mm']/b['smc_mm']))+abs(math.log(a['ksat_mm_h']/b['ksat_mm_h']))+abs(p['features']['terrain'][1]-q['features']['terrain'][1])/15
                    regional=cat_distance(p,q)
                    if regional is not None:
                        distance+=regional
                    raw.append(math.exp(-min(distance,700)))
                weights=np.asarray(raw)/sum(raw)
                # Transfer fitted corrections, retaining the target GIS infiltration.
                corrections=[]
                for q,w in zip(donors_p,weights):
                    fit=fitted[q['point_id']]
                    seed=controls['initials'][q['point_id']]
                    corrections.append([fit[0]/seed[0],fit[1]-seed[1],fit[2]-seed[2]])
                    transfer.append({'point_id':q['point_id'],'label':q['label'],'weight':float(w)})
                avg=np.average(corrections,axis=0,weights=weights)
                proposed=[params[0]*avg[0],params[1]+avg[1],params[2]+avg[2]]
                for j in controls['active_indices']:
                    lo,hi=controls['bounds'][PARAMETERS[j]]
                    params[j]=min(hi,max(lo,proposed[j]))
                status='Transfer koreksi parameter referensi terkalibrasi berbobot kemiripan GIS; belum validasi DAS target.'
            trace=mock(p['climate']['rows'],p['soil_parameters'],params)
            traces[p['point_id']]=trace
            predictions[p['point_id']]=q_from_depth([r['runoff_mm'] for r in trace],p['area_km2'],[r['days'] for r in trace]).tolist()
            parameters[p['point_id']]={'smc_multiplier':float(params[0]),'smc_mm':float(params[0]*p['soil_parameters']['smc_mm']),
                'infiltration':float(params[1]),'k30':float(params[2]),'status':status,'parameter_references':transfer,
                'calibration_mode':mode,'calibration_bounds':controls['bounds'],'calibration_parameters':controls['fit_parameters'],
                'calibration_active_parameters':[PARAMETERS[j] for j in controls['active_indices']] if mode=='auto' else [],
                'calibration_performed':p['point_id'] in fitted,'parameter_transfer_applied':bool(transfer),
                'initial_parameters':dict(zip(PARAMETERS,controls['initials'][p['point_id']])),
                'clipped_initial_parameters':controls['clipped_initial_parameters'][p['point_id']],
                'gis_prior':{'smc_mm':p['soil_parameters']['smc_mm'],'infiltration':p['soil_parameters']['infiltration'],
                             'k30':p.get('recession_parameters',{}).get('k30')},
                'recession_gis':p.get('recession_parameters',{}),
                'warmup_years':warmup_years,'output_start_year':output_starts[p['point_id']],
                'initial_soil_mm':float(params[0]*p['soil_parameters']['smc_mm']/2),'initial_groundwater_mm':0.,
                'spinup':f'{warmup_years} tahun iklim aktual sejak {p["climate"]["rows"][0]["year"]}; tampungan diteruskan tanpa reset. Periode pemanasan tidak masuk keluaran, statistik, kalibrasi, atau validasi.',
                'formulation':'ETlimited=ET0[1-m/20 max(18-30*n/d,0)]; AET=min(ETlimited,P+S); k=k30^(d/30); G=kGprev+0.5(1+k)I; BF=I-ΔG; Q=(DR+BF)A/(86.4d). A km², kedalaman mm.',
                'max_balance_error_mm':float(max(abs(r['balance_error_mm']) for r in trace))}
    else:
        features={p['point_id']:_ml_features(p) for p in points}
        samples=[]
        for p in points:
            for i,x in features[p['point_id']].items():
                row=p['climate']['rows'][i]
                q=observations.get(p['point_id'],{}).get((row['year'],row['period']))
                if q is not None:
                    depth=q*row['days']*86400/(p['area_km2']*1000)
                    samples.append((p['point_id'],i,x,depth,q,row['year'],row['period']))
        if len(samples)<24:
            raise ValueError('RF/XGBoost membutuhkan ≥24 pasangan debit–iklim setelah enam periode lag hujan awal.')
        X=np.array([s[2] for s in samples]);y=np.array([s[3] for s in samples])
        ids=sorted({s[0] for s in samples})
        splits=[]
        if len(ids)>1:
            for id_ in ids:
                test=np.array([s[0]==id_ for s in samples]);splits.append((~test,test,'Leave-one-DTA-out',id_))
        else:
            order=sorted(range(len(samples)),key=lambda i:(samples[i][5],samples[i][6]))
            cutoff=max(24,int(len(order)*.75))
            test=np.zeros(len(samples),dtype=bool);test[order[cutoff:]]=True
            splits.append((~test,test,'Temporal 75% awal / 25% akhir',ids[0]))
        by_id={p['point_id']:p for p in points}
        for train,test,scheme,id_ in splits:
            if train.sum()<24 or test.sum()<6:
                continue
            estimator=_estimator(model).fit(X[train],y[train])
            qpred=[]
            for sample,depth in zip([s for s,t in zip(samples,test) if t],np.maximum(estimator.predict(X[test]),0)):
                p=by_id[sample[0]];row=p['climate']['rows'][sample[1]]
                qpred.append(float(q_from_depth(depth,p['area_km2'],row['days'])))
            validation.append({'point_id':id_,'label':by_id[id_]['label'],'scheme':scheme,**metrics([s[4] for s,t in zip(samples,test) if t],qpred)})
        estimator=_estimator(model).fit(X,y)
        for p in points:
            f=features[p['point_id']]
            values=[None]*len(p['climate']['rows'])
            if f:
                depths=np.maximum(estimator.predict(np.array(list(f.values()))),0)
                for i,depth in zip(f,depths):
                    values[i]=float(q_from_depth(depth,p['area_km2'],p['climate']['rows'][i]['days']))
            predictions[p['point_id']]=values
            importance=getattr(estimator,'feature_importances_',[])
            parameters[p['point_id']]={'status':'Model dilatih pada debit referensi; target pelatihan berupa kedalaman limpasan mm/periode.',
                'training_samples':len(samples),'training_dtas':ids,'random_seed':42,
                'features':['P','ET0','wet_fraction','days','P_lag1','P_lag2','P_lag3','P_previous6','sin_season','cos_season','SMC','Ksat','infiltration','exposed_fraction','elevation','slope'],
                'importance':[float(v) for v in importance],
                'settings':{k:v for k,v in estimator.get_params().items() if v is None or isinstance(v,(str,bool,int)) or isinstance(v,float) and math.isfinite(v)},
                'note':'Enam periode pertama tidak diprediksi (lag belum lengkap). Prediksi bukan neraca air dan dapat bias saat ekstrapolasi.'}
    results=[]
    for p in points:
        rows=p['climate']['rows'];values=predictions[p['point_id']]
        climate=p['climate']
        water_balance=traces.get(p['point_id'],[])
        if model=='mock':
            start=output_starts[p['point_id']]
            values=[q for r,q in zip(rows,values) if r['year']>=start]
            rows=[r for r in rows if r['year']>=start]
            water_balance=[r for r in water_balance if r['year']>=start]
            climate={**climate,'rows':rows,'simulation_start':p['climate']['rows'][0]['start'],
                'output_start':rows[0]['start'],'warmup_years':warmup_years}
        records={r['year']:[None]*24 for r in rows}
        volume=0.
        for row,q in zip(rows,values):
            if q is not None and (not math.isfinite(q) or q<0):
                raise ValueError('Prediksi debit tidak berhingga/negatif.')
            records[row['year']][row['period']]=q
            if q is not None:
                volume+=q*row['days']*86400
        warnings=list(p.get('warnings',[]))+['ET0 centroid merupakan pendekatan spasial; perubahan tutupan lahan historis, pengambilan air dan operasi waduk belum dimodelkan.']
        if not validation:
            warnings.append('Belum tersedia validasi independen; statistik hasil bukan bukti akurasi model.')
        if rows[-1]['period']!=23:
            warnings.append('Tahun terakhir parsial; periode yang belum tersedia tetap kosong, bukan debit nol.')
        results.append({**p,'climate':climate,'records':[{'year':y,'values':v} for y,v in sorted(records.items())],
            'statistics':safe_stats(values),'period_statistics':[safe_stats([v[j] for v in records.values()]) for j in range(24)],
            'volume_m3':volume,'model_parameters':parameters[p['point_id']],'water_balance':water_balance,
            'donors':[],'warnings':warnings})
        if model=='mock':
            paired=[(observations.get(p['point_id'],{}).get((r['year'],r['period'])),q) for r,q in zip(rows,values)]
            paired=[(o,q) for o,q in paired if o is not None and q is not None]
            results[-1]['observation_comparison']=metrics([o for o,_ in paired],[q for _,q in paired]) if paired else None
            results[-1]['comparison_note']='Perbandingan seluruh pengamatan setelah pemanasan; ini bukan validasi independen.'
    names={'mock':'FJ Mock (adaptasi tengah bulanan)','random_forest':'Random Forest','xgboost':'XGBoost'}
    return {'model':model,'method':names[model],'unit':'m³/det','source_file':source_file,'results':results,
            'warmup_years':warmup_years if model=='mock' else 0,
            'years':sorted({r['year'] for p in results for r in p['records']}),
            'references':[{**d,'label':next(p['label'] for p in points if p['point_id']==d['point_id'])} for d in donors],
            'validation':validation,'validation_note':'Uji memakai data yang tidak dipakai untuk fitting pada fold tersebut. Model akhir dilatih ulang pada seluruh pengamatan; validasi temporal tidak membuktikan akurasi di DAS lain.',
            'statistic_convention':'Statistik hanya periode numerik tersedia; kuantil Excel EXC/Weibull; tahun parsial tidak diisi nol',
            'uncertainty_note':'Parameter GIS adalah prior awal, bukan kalibrasi regional tervalidasi. Kinerja harus diuji pada debit independen; model ML tidak menjamin konservasi air.'}
