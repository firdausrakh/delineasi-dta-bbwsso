"""SoilGrids units and GIS initial parameters, based on Abbaspour et al. (2019)."""
from __future__ import annotations

import numpy as np
import rasterio
from .hydro_rainfall import cell_weights

SOIL_RASTERS = ('sand', 'silt', 'clay', 'bd', 'coarse', 'carbon', 'swc0033', 'swc1500')
DEPTHS_CM = ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))
# Initial retention scores, not fitted runoff/infiltration coefficients.
LAND_RETENTION = {2001:.95, 2002:.85, 2006:.8, 2010:.7, 2007:.65, 3000:.6,
                  20091:.5, 20092:.6, 20122:.4, 6009:.4, 20093:.3, 2014:.2,
                  20141:.1, 2012:.05, 20121:.05, 5001:0., 20094:.1,
                  2005:.5, 20051:.5, 2004:.4, 20041:.4, 20071:.4, 5011:.3, 50011:.3}


def pedotransfer(raw):
    """Arrays in native SoilGrids units; outputs AWC fraction and Ksat mm/hour.

    AWC follows the supplied QGIS toolbox (theta33-theta1500). Ksat uses the
    two Cosby, Wosten, and Weynants equations in Table 4, with a robust median.
    These four require no undocumented repairs to the ambiguous printed terms.
    """
    s, t, c = (np.asarray(raw[k], dtype=float)/10 for k in ('sand','silt','clay'))
    bd, oc = np.asarray(raw['bd'], dtype=float)/100, np.asarray(raw['carbon'], dtype=float)/100
    rock = np.asarray(raw['coarse'], dtype=float)/1000
    fc, wp = np.asarray(raw['swc0033'], dtype=float)/1000, np.asarray(raw['swc1500'], dtype=float)/1000
    valid = np.isfinite(np.stack(list(raw.values()))).all(axis=0)
    valid &= (np.abs(s+t+c-100)<=5)&(s>=0)&(t>0)&(c>=0)&(bd>0)&(bd<2.65)&(oc>0)&(oc<=100)
    valid &= (rock>=0)&(rock<1)&(wp>=0)&(fc>wp)&(fc<=1)
    topsoil = np.array([int(bottom<=30) for _,bottom in DEPTHS_CM]).reshape((-1,)+(1,)*(s.ndim-1))
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        cosby1 = 60.96*10**(-.884+.0153*s)
        cosby2 = 60.96*10**(-.6+.0126*s-.0064*c)
        wosten = np.exp(7.755+.0352*t+.93*topsoil-.967*bd**2-.000484*c**2-.000322*t**2
                        +.001/t-.129/oc-.643*np.log(t)-.01398*bd*c-.0973*bd*oc
                        +.02986*topsoil*c-.03305*topsoil*t)
        weynants = np.exp(1.9582+.0308*s-.6142*bd-.01566*oc)
    candidates = np.stack([cosby1, cosby2, wosten, weynants])*10/24
    valid &= np.isfinite(candidates).all(axis=0)&(candidates>0).all(axis=0)
    return {'valid':valid, 'awc':(fc-wp)*(1-rock), 'ksat':np.median(candidates,axis=0),
            'ksat_min':candidates.min(axis=0), 'ksat_max':candidates.max(axis=0),
            'bulk_density':bd, 'organic_carbon_pct':oc, 'coarse_fraction':rock}


def soil_parameters(paths, geom, crs, slope_pct, landcover):
    missing=[k for k in SOIL_RASTERS if k not in paths or not paths[k].exists()]
    if missing:
        raise ValueError('Raster tanah belum tersedia: '+', '.join(missing))
    raw={}
    signature=None
    window=None
    for name in SOIL_RASTERS:
        with rasterio.open(paths[name]) as ds:
            if ds.crs is None or ds.count!=6:
                raise ValueError(f'{name}: perlu enam band dengan CRS.')
            current=(str(ds.crs),tuple(ds.transform),ds.width,ds.height)
            if signature is not None and current!=signature:
                raise ValueError('Seluruh grid raster tanah harus identik.')
            signature=current
            if window is None:
                window,weights,target_area=cell_weights(ds,geom,crs)
                if weights.sum()/target_area<.95:
                    raise ValueError('Cakupan grid tanah kurang dari 95% luas DTA.')
            data=ds.read(window=window,masked=True)
            raw[name]=data.astype(float).filled(np.nan)
    inside=weights>0
    ptf=pedotransfer(raw)
    layers=[]
    for i,(top,bottom) in enumerate(DEPTHS_CM):
        valid=ptf['valid'][i]&inside
        coverage=min(float(weights[valid].sum()/target_area),1.)
        if coverage<.95:
            raise ValueError(f'Tanah {top}–{bottom} cm: cakupan valid {coverage:.1%}, minimal 95%.')
        row={'top_cm':top,'bottom_cm':bottom,'coverage':float(coverage)}
        for key in ('awc','ksat','ksat_min','ksat_max','bulk_density','organic_carbon_pct','coarse_fraction'):
            row[key]=float(np.average(ptf[key][i][valid],weights=weights[valid]))
        layers.append(row)
    thickness=np.array([50,100,150,300,400],dtype=float)
    smc=float(sum(row['awc']*dz for row,dz in zip(layers,thickness)))
    ksat=float(thickness.sum()/sum(dz/row['ksat'] for row,dz in zip(layers,thickness)))
    if not landcover or abs(sum(landcover.values())-1)>.02:
        raise ValueError('Tutupan lahan lengkap diperlukan untuk indeks infiltrasi.')
    unknown=set(landcover)-{str(k) for k in LAND_RETENTION}
    if unknown:
        raise ValueError('Kelas tutupan lahan belum dipetakan untuk infiltrasi: '+', '.join(sorted(unknown)))
    land=float(sum(LAND_RETENTION[int(k)]*v for k,v in landcover.items()))
    soil=ksat/(ksat+10.)
    slope=1/(1+max(float(slope_pct),0)/15.)
    infiltration=float(np.clip((soil*slope*land)**(1/3),0,1))
    return {'root_depth_m':1., 'smc_mm':smc,'ksat_mm_h':ksat,'infiltration':infiltration,
            'exposed_fraction':1-land,'layers':layers,
            'infiltration_components':{'soil':soil,'slope':slope,'landcover':land},
            'infiltration_formula':'i=(Ksat/(Ksat+10) × 1/(1+slope_pct/15) × L)^(1/3); L=tabel skor retensi tutupan lahan.',
            'landcover_scores':{str(k):v for k,v in LAND_RETENTION.items()},
            'reference':'https://doi.org/10.1038/s41597-019-0282-4; persamaan satuan mengikuti toolbox QGIS hitungParameter_optimized.py.',
            'method':'AWC=(SWC33-SWC1500)/1000 × (1-coarse/1000); Ksat=median Cosby-1, Cosby-2, Wosten, Weynants (Abbaspour 2019 Tabel 4); Ksat profil=harmonik berbobot ketebalan.',
            'status':'Estimasi awal GIS; indeks infiltrasi dan skala 10 mm/jam serta 15% lereng belum dikalibrasi.'}
