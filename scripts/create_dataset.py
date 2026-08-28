from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'data'/'source'
print('='*52); print(' BUAT FOLDER EKSPERIMEN DATASET'); print('='*52)
raw=input('ID folder (contoh 1km2 / 0_5km2 / 0_2km2): ').strip()
if not re.fullmatch(r'[A-Za-z0-9_.-]+',raw): raise SystemExit('ID folder hanya boleh huruf, angka, _, -, atau titik.')
p=source/raw
if p.exists(): raise SystemExit(f'Folder sudah ada: {p}')
threshold_text=input('Threshold km2 (contoh 0.5; boleh kosong): ').strip()
threshold=float(threshold_text) if threshold_text else None
name=input('Nama dataset (boleh kosong): ').strip() or raw
p.mkdir(parents=True)
(p/'dataset.json').write_text(json.dumps({'name':name,'threshold_km2':threshold,'description':''},indent=2,ensure_ascii=False),encoding='utf-8')
(p/'TARUH_3_FILE_DI_SINI.txt').write_text('File wajib:\n- streams.zip\n- subbasins.zip\n- subbasins.tif\n\nKetiganya harus berasal dari run threshold yang sama.\n',encoding='utf-8')
print(f'\nFolder dibuat: {p}')
