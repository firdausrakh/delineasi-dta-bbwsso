from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.runtime_backend import _r2_client, load_project_dotenv  # noqa: E402


def _upload_tree(client, bucket: str, source: Path, *, public_assets: bool = False) -> tuple[int, int]:
    files = [p for p in source.rglob("*") if p.is_file()]
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
    args = parser.parse_args()
    load_project_dotenv(ROOT)

    runtime_bucket = os.getenv("R2_RUNTIME_BUCKET", "").strip()
    map_bucket = os.getenv("R2_MAP_ASSETS_BUCKET", "").strip()
    if not runtime_bucket or not map_bucket:
        raise RuntimeError("R2_RUNTIME_BUCKET dan R2_MAP_ASSETS_BUCKET wajib diisi.")

    bundle = Path(args.bundle).resolve()
    runtime = bundle / "runtime"
    map_assets = bundle / "map-assets"
    if not (runtime / "manifest.json").exists():
        raise RuntimeError(f"Bundle runtime belum dibuat: {runtime}")
    if not map_assets.exists():
        raise RuntimeError(f"Bundle map-assets belum dibuat: {map_assets}")

    client = _r2_client()
    print("Upload runtime private...")
    n1, b1 = _upload_tree(client, runtime_bucket, runtime)
    print("Upload map assets public...")
    n2, b2 = _upload_tree(client, map_bucket, map_assets, public_assets=True)
    print(f"Selesai: {n1+n2} file, {(b1+b2)/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
