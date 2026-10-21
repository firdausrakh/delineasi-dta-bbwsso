from __future__ import annotations

import argparse
import mimetypes
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.runtime_backend import _r2_client, load_project_dotenv  # noqa: E402


def _upload_tree(client, bucket: str, source: Path, *, public_assets: bool = False, skip_manifest: bool = False) -> tuple[int, int]:
    files = sorted(p for p in source.rglob("*") if p.is_file() and not (skip_manifest and p == source / 'manifest.json'))
    total = sum(p.stat().st_size for p in files)
    for i, path in enumerate(files, 1):
        key = path.relative_to(source).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        extra = {"ContentType": content_type}
        if public_assets:
            extra["CacheControl"] = "public, max-age=31536000, immutable"
        elif path.name == "manifest.json":
            extra["CacheControl"] = "no-cache"
        print(f"[{i}/{len(files)}] {bucket}/{key} ({path.stat().st_size / 1024 / 1024:.2f} MB)")
        client.upload_file(str(path), bucket, key, ExtraArgs=extra)
    return len(files), total


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload bundle hasil export ke Cloudflare R2.")
    parser.add_argument("--bundle", default=str(ROOT / "r2_bundle"))
    parser.add_argument('--hydro-only', action='store_true', help='Unggah hanya data Model Hidrologi dan gabungkan ke manifest R2 aktif.')
    args = parser.parse_args()
    load_project_dotenv(ROOT)

    runtime_bucket = os.getenv("R2_RUNTIME_BUCKET", "").strip()
    map_bucket = os.getenv("R2_MAP_ASSETS_BUCKET", "").strip()
    if not runtime_bucket or (not args.hydro_only and not map_bucket):
        raise RuntimeError("R2_RUNTIME_BUCKET dan R2_MAP_ASSETS_BUCKET wajib diisi.")

    bundle = Path(args.bundle).resolve()
    runtime = bundle / "runtime"
    map_assets = bundle / "map-assets"
    if not (runtime / "manifest.json").exists():
        raise RuntimeError(f"Bundle runtime belum dibuat: {runtime}")
    if not args.hydro_only and not map_assets.exists():
        raise RuntimeError(f"Bundle map-assets belum dibuat: {map_assets}")

    client = _r2_client()
    manifest_key = os.getenv('R2_MANIFEST_KEY', 'manifest.json').strip() or 'manifest.json'
    if args.hydro_only:
        local_manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
        dsid = os.getenv('HYDRO_DATASET', '').strip() or local_manifest['active_dataset']
        spec = local_manifest['datasets'][dsid]
        names = ('hydro_vectors', 'sand', 'silt', 'clay') + tuple(n for n in ('bd','coarse','carbon','swc0033','swc1500','rainfall','daily_rainfall') if spec.get(n))
        files = []
        for name in names:
            if name not in spec:
                raise RuntimeError(f'Bundle Model Hidrologi belum lengkap: {name}.')
            key = spec[name]
            path = (runtime / key).resolve()
            if not path.is_relative_to(runtime.resolve()):
                raise RuntimeError('Path object berada di luar bundle.')
            metadata = local_manifest['objects'][key]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != metadata['sha256'] or path.stat().st_size != metadata['size']:
                raise RuntimeError(f'Checksum/ukuran bundle tidak cocok: {key}.')
            files.append((name, key, path, metadata))
        remote = json.loads(client.get_object(Bucket=runtime_bucket, Key=manifest_key)['Body'].read().decode('utf-8-sig'))
        if dsid not in remote.get('datasets', {}):
            raise RuntimeError('Dataset Model Hidrologi tidak ada pada manifest R2 aktif.')
        for name, key, path, metadata in files:
            print(f'Upload model: {key}')
            client.upload_file(str(path), runtime_bucket, key, ExtraArgs={'ContentType': 'application/geopackage+sqlite3' if name == 'hydro_vectors' else 'application/x-netcdf' if name == 'daily_rainfall' else 'image/tiff'})
            remote['datasets'][dsid][name] = key
            remote.setdefault('objects', {})[key] = metadata
        remote['schema_version'] = max(5, int(remote.get('schema_version', 0)))
        client.put_object(Bucket=runtime_bucket, Key=manifest_key, Body=json.dumps(remote, ensure_ascii=False, indent=2).encode('utf-8'), ContentType='application/json', CacheControl='no-cache')
        print('Upload Model Hidrologi selesai; manifest diterbitkan terakhir.')
        return 0
    print("Upload runtime private...")
    n1, b1 = _upload_tree(client, runtime_bucket, runtime, skip_manifest=True)
    print("Upload map assets public...")
    n2, b2 = _upload_tree(client, map_bucket, map_assets, public_assets=True)
    print('Menerbitkan manifest setelah seluruh object selesai diunggah...')
    client.upload_file(str(runtime / 'manifest.json'), runtime_bucket, manifest_key,
                       ExtraArgs={'ContentType': 'application/json', 'CacheControl': 'no-cache'})
    n1 += 1
    b1 += (runtime / 'manifest.json').stat().st_size
    print(f"Selesai: {n1+n2} file, {(b1+b2)/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
