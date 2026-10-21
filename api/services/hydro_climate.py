"""Daily areal rainfall and FAO56 ET0, aggregated to calendar half-months."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError

import h5py
import numpy as np
from rasterio.transform import from_origin, array_bounds
from pyproj import Transformer
from shapely.ops import transform

from .hydro_rainfall import cell_weights


def _text(value):
    return value.decode() if isinstance(value, bytes) else str(value)


def daily_rainfall(path, geom, crs, start_year, end_year):
    """Read a single HDF5 hyperslab: native chunks span thousands of dates."""
    with h5py.File(path, 'r', rdcc_nbytes=128*1024**2) as f:
        rain=f['prcp']
        if _text(rain.attrs.get('units','')).lower() not in ('mm','mm/day','mm/d'):
            raise ValueError('Satuan hujan harian harus mm/hari.')
        lat,lon=np.asarray(f['lat']),np.asarray(f['lon'])
        if rain.shape!=(len(f['time']),len(lat),len(lon)) or len(lat)<2 or len(lon)<2:
            raise ValueError('Dimensi NetCDF hujan harus time, lat, lon.')
        dx,dy=float(lon[1]-lon[0]),float(lat[1]-lat[0])
        if dx<=0 or dy<=0 or not np.allclose(np.diff(lat),dy) or not np.allclose(np.diff(lon),dx):
            raise ValueError('Koordinat hujan harus grid teratur dengan lat/lon menaik.')
        tr=from_origin(lon[0]-dx/2,lat[-1]+dy/2,dx,dy)
        ds=SimpleNamespace(transform=tr,crs='EPSG:4326',height=len(lat),width=len(lon),bounds=array_bounds(len(lat),len(lon),tr))
        win,weights,area=cell_weights(ds,geom,crs)
        units=_text(f['time'].attrs.get('units',''))
        if not units.startswith('days since ') or _text(f['time'].attrs.get('calendar','standard')) not in ('standard','gregorian','proleptic_gregorian'):
            raise ValueError('Sumbu waktu NetCDF harus hari kalender Gregorian.')
        base=date.fromisoformat(units[11:21])
        times=np.asarray(f['time'],dtype=float)
        if not np.isfinite(times).all() or not np.equal(times,np.floor(times)).all() or not np.all(np.diff(times)==1):
            raise ValueError('Sumbu waktu hujan harus harian, unik, dan berurutan.')
        dates=[base+timedelta(days=int(t)) for t in times]
        indices=[i for i,d in enumerate(dates) if start_year<=d.year<=end_year]
        if not indices or dates[indices[0]]!=date(start_year,1,1):
            raise ValueError('Awal tahun simulasi tidak tercakup hujan harian.')
        r,c,h,w=map(int,(win.row_off,win.col_off,win.height,win.width))
        data=np.asarray(rain[indices[0]:indices[-1]+1,len(lat)-r-h:len(lat)-r,c:c+w],dtype=float)[:,::-1,:]
        fill=rain.attrs.get('_FillValue',np.nan)
        if np.isfinite(fill):
            data[data==fill]=np.nan
        inside=weights>0
        if np.any(((data<0)|np.isinf(data))&inside):
            raise ValueError('Hujan negatif/tak hingga pada DTA; periksa sumber.')
        valid=np.isfinite(data)
        areas=(valid*weights).sum(axis=(1,2))
        coverage=np.minimum(areas/area,1)
        means=np.divide((np.where(valid,data,0)*weights).sum(axis=(1,2)),areas,out=np.full(len(data),np.nan),where=areas>0)
        dates=dates[indices[0]:indices[-1]+1]
        # A trailing unavailable interval is omitted, internal missing days are errors.
        good=np.flatnonzero(coverage>=.95)
        if not good.size:
            raise ValueError('Tidak ada hari hujan dengan cakupan valid ≥95% DTA.')
        last=int(good[-1])+1
        if np.any(coverage[:last]<.95):
            bad=int(np.flatnonzero(coverage[:last]<.95)[0])
            raise ValueError(f'Hujan {dates[bad]}: cakupan {coverage[bad]:.1%}, minimal 95%; tidak diisi nol.')
        if last<len(dates) and np.any(areas[last:]>0):
            raise ValueError('Ujung deret hujan memiliki cakupan parsial; periksa data sumber.')
        return dates[:last],means[:last],float(coverage[:last].min())


def fetch_et0(lon, lat, start, end, cache_dir):
    """Cache only complete, validated responses; never silently replace missing ET0."""
    params={'latitude':round(lat,5),'longitude':round(lon,5),'start_date':str(start),'end_date':str(end),
            'daily':'et0_fao_evapotranspiration','models':'era5_seamless','timezone':'Asia/Jakarta',
            'elevation':'nan','cell_selection':'nearest'}
    url='https://archive-api.open-meteo.com/v1/archive?'+urlencode(params)
    key=hashlib.sha256(url.encode()).hexdigest()
    cache=Path(cache_dir)/f'{key}.json'
    expected=[str(start+timedelta(days=i)) for i in range((end-start).days+1)]
    def validate(payload):
        if not isinstance(payload,dict):
            raise ValueError('Respons ET0 Open-Meteo tidak valid.')
        daily=payload.get('daily',{})
        values=daily.get('et0_fao_evapotranspiration',[])
        if daily.get('time')!=expected or len(values)!=len(expected) or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not np.isfinite(x) or x<0 for x in values):
            raise ValueError('ET0 Open-Meteo tidak lengkap/nonvalid; periksa ketersediaan tanggal dan koneksi.')
        if payload.get('daily_units',{}).get('et0_fao_evapotranspiration')!='mm':
            raise ValueError('Satuan ET0 Open-Meteo tidak sesuai mm/hari.')
        return np.array(values,dtype=float)
    if cache.exists():
        try:
            payload=json.loads(cache.read_text(encoding='utf-8'))
            return validate(payload),{'url':url,'latitude':payload['latitude'],'longitude':payload['longitude'],'cached':True}
        except (ValueError,KeyError,OSError):
            pass
    try:
        with urlopen(url,timeout=60) as response:
            body=response.read(8*1024**2+1)
        if len(body)>8*1024**2:
            raise ValueError('Respons ET0 terlalu besar.')
        payload=json.loads(body)
        values=validate(payload)
    except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc:
        raise ValueError(f'Pengambilan ET0 Open-Meteo gagal: {exc}') from exc
    cache.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=cache.parent,delete=False) as f:
        json.dump(payload,f,allow_nan=False)
        temp=Path(f.name)
    temp.replace(cache)
    return values,{'url':url,'latitude':payload['latitude'],'longitude':payload['longitude'],'cached':False}


def aggregate(dates, rain, et0):
    if len(dates)!=len(rain) or len(dates)!=len(et0):
        raise ValueError('Panjang data iklim tidak sejajar.')
    rows=[]
    i=0
    while i<len(dates):
        d=dates[i]
        first=1 if d.day<=15 else 16
        last=15 if first==1 else calendar.monthrange(d.year,d.month)[1]
        days=last-first+1
        if d.day!=first:
            raise ValueError('Deret iklim harus dimulai tanggal 1 atau 16.')
        if i+days>len(dates):
            break  # Partial final half-month cannot be treated as a complete period.
        expected=[d+timedelta(days=j) for j in range(days)]
        if dates[i:i+days]!=expected:
            raise ValueError('Tanggal iklim tidak berurutan.')
        p,e=np.asarray(rain[i:i+days]),np.asarray(et0[i:i+days])
        if not np.isfinite(p).all() or not np.isfinite(e).all() or (p<0).any() or (e<0).any():
            raise ValueError('Hujan dan ET0 harus lengkap serta non-negatif.')
        rows.append({'year':d.year,'period':2*(d.month-1)+(first==16),'start':str(d),'days':days,
                     'p_mm':float(p.sum()),'et0_mm':float(e.sum()),'wet_days':int((p>=1).sum())})
        i+=days
    if len(rows)<24:
        raise ValueError('Diperlukan minimal satu tahun lengkap iklim untuk kondisi awal model.')
    return rows


def climate(path,geom,crs,start_year,end_year,cache_dir):
    dates,rain,coverage=daily_rainfall(path,geom,crs,start_year,end_year)
    # shortcut: centroid ET0 approximates basin climate; upgrade to area sampling for large/high-relief basins.
    local=transform(Transformer.from_crs(crs,'EPSG:6933',always_xy=True).transform,geom).centroid
    center=transform(Transformer.from_crs('EPSG:6933','EPSG:4326',always_xy=True).transform,local)
    et0,metadata=fetch_et0(center.x,center.y,dates[0],dates[-1],cache_dir)
    rows=aggregate(dates,rain,et0)
    return {'rows':rows,'coverage_min':coverage,'rainfall_source':Path(path).name,'et0':metadata,
            'last_complete_period':rows[-1]['start'],'wet_day_threshold_mm':1.,
            'method':'Hujan rerata areal irisan sel EPSG:6933; hari hujan dari hujan areal harian ≥1 mm; ET0 FAO56 Penman–Monteith Open-Meteo ERA5 seamless pada centroid DTA, bukan evapotranspirasi aktual.'}
