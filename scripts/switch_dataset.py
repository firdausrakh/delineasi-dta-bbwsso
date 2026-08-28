from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
processed=ROOT/'data'/'processed'
active=ROOT/'data'/'active_dataset.json'
folders=sorted([p for p in processed.iterdir() if p.is_dir() and not p.name.startswith('.') and (p/'hydro_engine.gpkg').exists()]) if processed.exists() else []
if not folders: raise SystemExit('Belum ada dataset processed. Jalankan prepare_data.bat.')
print('='*52); print(' PILIH DATASET HIDROLOGI AKTIF'); print('='*52)
for i,p in enumerate(folders,1):
    label=p.name
    mp=p/'metadata.json'
    if mp.exists():
        try:
            m=json.loads(mp.read_text(encoding='utf-8'))
            if m.get('threshold_km2') is not None: label += f"  | threshold {m['threshold_km2']} km2"
            if m.get('subbasins'): label += f"  | {m['subbasins']:,} subbasin"
        except Exception: pass
    print(f'[{i}] {label}')
while True:
    x=input('\nPilih dataset (nomor/nama): ').strip()
    if x.isdigit() and 1<=int(x)<=len(folders): choice=folders[int(x)-1].name; break
    if (processed/x/'hydro_engine.gpkg').exists(): choice=x; break
    print('Pilihan tidak dikenali.')
active.write_text(json.dumps({'dataset':choice},indent=2),encoding='utf-8')
print(f'\nDataset aktif: {choice}')
print('Restart run.bat agar dataset dimuat ulang.')
