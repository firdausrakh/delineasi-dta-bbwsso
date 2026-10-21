"""Explicit, uncalibrated GIS prior for a Mock recession time scale."""
from __future__ import annotations

import math

# Hypotheses for initial screening, not measured residence times or USGS coefficients.
LITHOLOGY_TAU_DAYS = {'Endapan Lepas':90., 'Batuan Volkanik':75., 'Batuan Padu':45.,
                      'Batuan Malihan Dan Beku':30., 'Batugamping':30.}
PRODUCTIVITY_SCORES = {'Langka':0., 'Produktif Rendah':.2, 'Produktif Kecil Setempat Berarti':.25,
    'Setempat Produktif':.4, 'Produktif Sedang':.6, 'Produktif Sedang Dgn Penyebaran Luas':.65,
    'Produktif Dgn Penyebaran Luas':.7, 'Produktif Tinggi':.9,
    'Produktif Tinggi Dgn Penyebaran Luas':1.,
    'Produktif Kecil Menutupi Akuifer Produktif Dgn Batugamping Produktif':.5}


def recession_prior(spatial):
    """The maps do not identify T/S or drainage geometry: this is a prior only.

    Productivity and availability are correlated; their scores form ONE group.
    CAT names remain regional context and never receive arbitrary numeric scores.
    """
    context=spatial.get('hydrogeology_context',{})
    lithology=context.get('lithology',{})
    products=spatial.get('features',{}).get('aquifer') or {}
    available=context.get('groundwater_availability',{})
    result={'available':False,'k30':None,'tau_days':None,'components':{},
        'lithology_tau_days':LITHOLOGY_TAU_DAYS,'productivity_scores':PRODUCTIVITY_SCORES,
        'cat':context.get('cat',{}),
        'source_distributions':{'lithology':lithology,
            'aquifer_productivity':{'classes':products,'coverage':spatial.get('coverage',{}).get('aquifer')},
            'groundwater_availability':available},
        'formula':'tau_lith=sum(f_lithology*tau_class)/sum(f_lithology); tau=tau_lith*(0.75+0.5*mean(productivity_group_scores)); k30=exp(-30/tau).',
        'status':'Prior GIS heuristik belum dikalibrasi; produktivitas tinggi tidak selalu berarti resesi lambat. Peta ini tidak menyediakan T/S, geometri aliran atau bukti konektivitas akuifer.',
        'reference':'https://www.usgs.gov/publications/predicting-baseflow-recession-characteristics-ungauged-stream-locations-using-a',
        'reference_scope':'Rujukan untuk pendekatan regionalisasi atribut DAS; angka tabel dan formula prior ini adalah asumsi aplikasi, bukan persamaan/koefisien USGS.'}
    def weighted(classes, table, coverage):
        if not classes or coverage is None or coverage<.95:
            return None
        total=sum(classes.values())
        if not math.isfinite(total) or total<=0 or any(not math.isfinite(v) or v<0 for v in classes.values()):
            return None
        known={key:value for key,value in classes.items() if key in table}
        known_total=sum(known.values())
        # Tiny non-hydrogeologic slivers (for example, water) should not discard
        # an otherwise complete DTA prior; large unknown areas still do.
        if not known_total or coverage*known_total/total<.95:
            return None
        return sum(table[key]*value for key,value in known.items())/known_total
    tau=weighted(lithology.get('classes',{}),LITHOLOGY_TAU_DAYS,lithology.get('coverage'))
    prod=weighted(products,PRODUCTIVITY_SCORES,spatial.get('coverage',{}).get('aquifer'))
    availability=weighted(available.get('classes',{}),PRODUCTIVITY_SCORES,available.get('coverage'))
    scores=[v for v in (prod,availability) if v is not None]
    if tau is None or not scores:
        result['reason']='Litologi dan minimal satu peta produktivitas/ketersediaan harus memiliki kelas dikenal dengan cakupan ≥95%. Isi k30 manual bila prior GIS tidak tersedia.'
        return result
    score=sum(scores)/len(scores)
    result.update(available=True,tau_days=tau*(.75+.5*score),
        k30=math.exp(-30/(tau*(.75+.5*score))),
        components={'lithology_tau_days':tau,'productivity_score':prod,'availability_score':availability,'combined_groundwater_score':score})
    if 'Batugamping' in lithology.get('classes',{}):
        result['status']+=' Batugamping/karst dapat memiliki resesi cepat dan lambat sekaligus; satu reservoir Mock belum mewakili keduanya.'
    return result


def cat_distance(a,b):
    """Use well-covered CAT distributions as a regional transfer descriptor."""
    cats=[p.get('hydrogeology_context',{}).get('cat',{}) for p in (a,b)]
    if any(not c.get('available') or (c.get('coverage') or 0)<.95 for c in cats):
        return None
    x,y=(c.get('classes',{}) for c in cats)
    if not x or not y:
        return None
    return .5*sum(abs(x.get(k,0)-y.get(k,0)) for k in x.keys()|y.keys())
