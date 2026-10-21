"""Prepare full-calendar half-month rain COG from daily Soil/Rain project NetCDF."""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import tempfile

import h5py
import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin


def prepare(source,output,report_dir):
    source,output,report_dir=map(Path,(source,output,report_dir))
    if source.resolve()==output.resolve():
        raise ValueError('Keluaran harus berbeda dari sumber.')
    with source.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with h5py.File(source,'r',rdcc_nbytes=128*1024**2) as f:
        def text(x): return x.decode() if isinstance(x,bytes) else str(x)
        if text(f['prcp'].attrs.get('units',''))!='mm' or not text(f['time'].attrs['units']).startswith('days since '):
            raise ValueError('Diperlukan prcp mm dan waktu days since.')
        base=date.fromisoformat(text(f['time'].attrs['units'])[11:21])
        times=np.asarray(f['time'])
        if not np.equal(times,np.floor(times)).all() or not np.all(np.diff(times)==1):
            raise ValueError('Sumbu waktu harian tidak berurutan.')
        dates=[base+timedelta(days=int(t)) for t in times]
        lat,lon=np.array(f['lat']),np.array(f['lon'])
        dx,dy=float(lon[1]-lon[0]),float(lat[1]-lat[0])
        if dx<=0 or dy<=0 or not np.allclose(np.diff(lon),dx) or not np.allclose(np.diff(lat),dy):
            raise ValueError('Grid harus teratur dan menaik.')
        # Offline preparation reads each compressed HDF5 chunk once.
        raw=np.asarray(f['prcp'],dtype=np.float32)
        if np.isinf(raw).any() or (raw<0).any():
            raise ValueError('Data hujan mengandung nilai negatif/tak hingga.')
        bands=[];starts=[];counts=[]
        i=0
        while i<len(dates):
            d=dates[i]
            if d.day not in (1,16):
                raise ValueError('Awal data harus tanggal 1 atau 16.')
            n=15 if d.day==1 else calendar.monthrange(d.year,d.month)[1]-15
            if i+n>len(dates):break
            block=raw[i:i+n]
            valid=np.isfinite(block).all(axis=0)
            values=np.where(valid,block.sum(axis=0),np.nan)
            if valid.any():
                bands.append(values[::-1]);starts.append(d);counts.append(valid.sum())
            elif bands and np.isfinite(raw[i+n:]).any():
                raise ValueError(f'Periode hilang di tengah deret: {d}.')
            i+=n
        if not bands:
            raise ValueError('Tidak ada periode lengkap dengan data valid.')
        data=np.stack(bands).astype('float32')
        tr=from_origin(lon[0]-dx/2,lat[-1]+dy/2,dx,dy)
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rain-daily-',dir=output.parent) as td:
            raw_tif=Path(td)/'raw.tif';cog=Path(td)/'rainfall.tif'
            with rasterio.open(raw_tif,'w',driver='GTiff',height=len(lat),width=len(lon),count=len(bands),
                               dtype='float32',nodata=np.nan,crs='EPSG:4326',transform=tr) as ds:
                ds.write(data)
                ds.update_tags(units='mm',source=source.name,source_sha256=digest,
                    description=text(f['prcp'].attrs.get('description','')),
                    quality_note='Akumulasi harian hanya bila semua hari dalam periode valid per sel; tanpa imputasi. Sumber TPS dibatasi 400 mm/hari; ekstrem perlu verifikasi stasiun.',
                    period_definition='1–15 dan 16–akhir bulan; hanya periode lengkap.')
                for b,d in enumerate(starts,1):
                    ds.update_tags(b,period_start=str(d));ds.set_band_description(b,str(d))
            raster_copy(raw_tif,cog,driver='COG',compress='DEFLATE',blocksize=128,overview_count=0)
            with rasterio.open(cog) as check:
                if not np.array_equal(data,check.read(),equal_nan=True):
                    raise RuntimeError('Konversi COG mengubah nilai hujan.')
            cog.replace(output)
        # Stable top-30 without sorting the entire time/grid cube.
        def highest(cube,dates_,daily=False):
            valid=np.flatnonzero(np.isfinite(cube))
            values=cube.ravel()[valid]
            n=min(30,len(valid))
            threshold=np.partition(values,len(values)-n)[-n]
            greater=np.flatnonzero(values>threshold)
            equal=np.flatnonzero(values==threshold)[:n-len(greater)]
            ix=np.concatenate([greater,equal])
            order=ix[np.lexsort((valid[ix],-values[ix]))]
            result=[]
            for rank,j in enumerate(order,1):
                t,r,c=np.unravel_index(valid[j],cube.shape)
                result.append({'rank':rank,'start':str(dates_[t]),'rainfall_mm':float(values[j]),
                    'latitude':float(lat[r] if daily else lat[-1-r]),'longitude':float(lon[c]),
                    'edge_cell':bool(r in (0,len(lat)-1) or c in (0,len(lon)-1))})
            return result
        report_dir.mkdir(parents=True,exist_ok=True)
        reports={'daily':highest(raw,dates,True),'semimonthly':highest(data,starts)}
        for name,rows in reports.items():
            with (report_dir/f'top30_{name}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        summary={'source':str(source),'sha256':digest,'start':str(starts[0]),'last_complete_period':str(starts[-1]),
                 'periods':len(bands),'top30':reports,'threshold_wet_day_mm':1,'missing_policy':'Semua hari harus valid; tidak diisi nol.'}
        (report_dir/'daily_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='top30'},ensure_ascii=False))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,default=Path('data/shared/rainfall.tif'))
    parser.add_argument('--report-dir',type=Path,default=Path('data/shared/rainfall_review'))
    args=parser.parse_args();prepare(args.source,args.output,args.report_dir)
