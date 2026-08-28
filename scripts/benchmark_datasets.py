from __future__ import annotations
import argparse, csv, json, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROCESSED=ROOT/'data'/'processed'
DEFAULT_POINTS=ROOT/'benchmark_points.csv'

p=argparse.ArgumentParser(description='Bandingkan hasil/waktu dataset threshold pada titik yang sama.')
p.add_argument('--points', default=str(DEFAULT_POINTS))
p.add_argument('--datasets', nargs='*', help='Dataset tertentu; default semua folder processed')
p.add_argument('--output', default=str(ROOT/'benchmark_results.csv'))
args=p.parse_args()
points=Path(args.points)
if not points.exists(): raise SystemExit(f'File titik tidak ditemukan: {points}')
datasets=args.datasets or sorted(d.name for d in PROCESSED.iterdir() if d.is_dir() and not d.name.startswith('.'))
if not datasets: raise SystemExit('Belum ada dataset processed.')
all_rows=[]
for dataset in datasets:
    print(f'Benchmark {dataset}...', flush=True)
    cmd=[sys.executable, str(ROOT/'scripts'/'benchmark_one.py'),'--dataset',dataset,'--points',str(points)]
    proc=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    if proc.returncode:
        print(proc.stdout); print(proc.stderr,file=sys.stderr); continue
    # startup logs precede the final JSON line
    line=[x for x in proc.stdout.splitlines() if x.strip()][-1]
    payload=json.loads(line)
    threshold=(payload.get('metadata') or {}).get('threshold_km2')
    for row in payload['rows']:
        all_rows.append({'dataset':dataset,'threshold_km2':threshold,**row})
cols=[]
for r in all_rows:
    for k in r:
        if k not in cols: cols.append(k)
if not all_rows:
    raise SystemExit('Tidak ada hasil benchmark yang berhasil. Lihat error di atas.')
out=Path(args.output)
with out.open('w',newline='',encoding='utf-8-sig') as fh:
    w=csv.DictWriter(fh,fieldnames=cols); w.writeheader(); w.writerows(all_rows)
print(f'\nSelesai: {out}')
for r in all_rows:
    if r.get('status')=='PASS':
        print(f"{r['dataset']:12} {r['point']:12} area={r.get('area_km2',0):.4f} km2  {r.get('processing_ms')} ms")
