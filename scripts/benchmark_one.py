from __future__ import annotations
import argparse, csv, json, os, time, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

parser=argparse.ArgumentParser()
parser.add_argument('--dataset', required=True)
parser.add_argument('--points', required=True)
args=parser.parse_args()
os.environ['HYDRO_DATASET']=args.dataset

from api import core

rows=[]
with open(args.points, newline='', encoding='utf-8-sig') as fh:
    for r in csv.DictReader(fh):
        pid=(r.get('point') or r.get('point_id') or r.get('name') or f"T{len(rows)+1}").strip()
        lon=float(r['longitude']); lat=float(r['latitude'])
        p=core.OutletPoint(point_id=pid[:10], lon=lon, lat=lat, source='benchmark', label=pid)
        started=time.perf_counter()
        try:
            result,_=core.build_point_result(p, 2000.0, 120.0, core.DEFAULT_PAEK_TOLERANCE_M, core.DEFAULT_VW_TOLERANCE_M)
            rows.append({
                'point':pid,'longitude':lon,'latitude':lat,'status':'PASS',
                'area_km2':result.get('area_km2'),'processing_ms':round((time.perf_counter()-started)*1000,1),
                'linkno':result.get('outlet_linkno'),'engine':(result.get('processing') or {}).get('engine'),
                'local_cells':(result.get('processing') or {}).get('local_cells'),
                'full_upstream_units':(result.get('processing') or {}).get('full_upstream_units'),
                'basin':(result.get('official_basin') or {}).get('name'),
            })
        except Exception as exc:
            rows.append({'point':pid,'longitude':lon,'latitude':lat,'status':'FAIL','error':str(exc)})
print(json.dumps({'dataset':args.dataset,'metadata':core.ACTIVE_DATASET_METADATA,'rows':rows}, ensure_ascii=False))
