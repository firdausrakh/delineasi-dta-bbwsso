from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


@dataclass
class RuntimeBundle:
    backend: str
    active_dataset_id: str
    active_dataset_metadata: dict[str, Any]
    streams: gpd.GeoDataFrame
    subbasins: gpd.GeoDataFrame
    official_basins: gpd.GeoDataFrame
    official_rivers: gpd.GeoDataFrame
    official_rivers_original: gpd.GeoDataFrame
    crosswalk: pd.DataFrame
    official_summary: dict[str, Any]
    fdir_path: Path
    subbasin_raster_path: Path
    toponym_db_path: Path | None
    map_assets_public_base: str | None = None


def load_project_dotenv(root: Path) -> None:
    """Load ROOT/.env without overriding real environment variables."""
    path = root / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _required_env(*keys: str) -> dict[str, str]:
    values = {key: os.getenv(key, "").strip() for key in keys}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError("Environment variable belum diisi: " + ", ".join(missing))
    return values


def _r2_endpoint_url() -> str:
    explicit = os.getenv("R2_ENDPOINT_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    values = _required_env("R2_ACCOUNT_ID")
    return f"https://{values['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"


def _r2_client():
    values = _required_env("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "DATA_BACKEND=r2 membutuhkan boto3. Jalankan pip install -r requirements.txt."
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=_r2_endpoint_url(),
        aws_access_key_id=values["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}),
    )


def _runtime_cache_root(dataset_id: str) -> Path:
    base = os.getenv("DTA_RUNTIME_CACHE_DIR", "").strip()
    root = Path(base) if base else Path(tempfile.gettempdir()) / "delineasi-dta-runtime"
    return root / dataset_id


def _r2_download(client, bucket: str, key: str, local_path: Path) -> Path:
    """Download one R2 object only when the cached ETag/size is stale."""
    refresh = os.getenv("R2_REFRESH_CACHE", "0").strip().lower() in {"1", "true", "yes", "y"}
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        raise RuntimeError(f"R2 object tidak ditemukan/tidak dapat dibaca: {bucket}/{key}: {exc}") from exc

    etag = str(head.get("ETag", "")).strip('"')
    remote_size = int(head.get("ContentLength") or 0)
    etag_path = local_path.with_suffix(local_path.suffix + ".etag")
    cached_etag = etag_path.read_text(encoding="utf-8").strip() if etag_path.exists() else ""
    if (
        not refresh
        and local_path.exists()
        and local_path.stat().st_size > 0
        and (remote_size <= 0 or local_path.stat().st_size == remote_size)
        and etag
        and cached_etag == etag
    ):
        return local_path

    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_path.with_suffix(local_path.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        client.download_file(bucket, key, str(tmp))
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Gagal download R2 {bucket}/{key}: {exc}") from exc
    if not tmp.exists() or tmp.stat().st_size <= 0:
        raise RuntimeError(f"R2 object kosong setelah download: {bucket}/{key}")
    tmp.replace(local_path)
    if etag:
        etag_path.write_text(etag, encoding="utf-8")
    return local_path


def _r2_manifest(client, bucket: str) -> dict[str, Any]:
    key = os.getenv("R2_MANIFEST_KEY", "manifest.json").strip() or "manifest.json"
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        payload = response["Body"].read()
        manifest = json.loads(payload.decode("utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Gagal membaca manifest R2 {bucket}/{key}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json R2 tidak valid: root harus JSON object.")
    return manifest


def _load_r2(root: Path, requested_dataset_id: str | None) -> RuntimeBundle:
    values = _required_env("R2_RUNTIME_BUCKET")
    bucket = values["R2_RUNTIME_BUCKET"]
    client = _r2_client()
    manifest = _r2_manifest(client, bucket)

    dsid = requested_dataset_id or str(manifest.get("active_dataset") or "").strip()
    if not dsid:
        raise RuntimeError("HYDRO_DATASET kosong dan manifest R2 tidak memiliki active_dataset.")
    datasets = manifest.get("datasets") or {}
    dataset_spec = datasets.get(dsid) if isinstance(datasets, dict) else None
    if not isinstance(dataset_spec, dict):
        raise RuntimeError(f"Dataset R2 '{dsid}' tidak ditemukan di manifest.json.")

    reference = manifest.get("reference") or {}
    if not isinstance(reference, dict):
        reference = {}

    def key(name: str, default: str) -> str:
        value = str(dataset_spec.get(name) or default).strip()
        if not value:
            raise RuntimeError(f"Path object R2 '{name}' untuk dataset '{dsid}' kosong.")
        return value

    def ref_key(name: str, default: str) -> str:
        value = str(reference.get(name) or default).strip()
        if not value:
            raise RuntimeError(f"Path reference R2 '{name}' kosong.")
        return value

    cache_root = _runtime_cache_root(dsid)
    paths = {
        "engine": _r2_download(client, bucket, key("engine", f"datasets/{dsid}/hydro_engine.gpkg"), cache_root / "processed" / "hydro_engine.gpkg"),
        "crosswalk": _r2_download(client, bucket, key("crosswalk", f"datasets/{dsid}/crosswalk.csv"), cache_root / "processed" / "crosswalk.csv"),
        "summary": _r2_download(client, bucket, key("summary", f"datasets/{dsid}/official_summary.json"), cache_root / "processed" / "official_summary.json"),
        "metadata": _r2_download(client, bucket, key("metadata", f"datasets/{dsid}/metadata.json"), cache_root / "processed" / "metadata.json"),
        "subbasin_raster": _r2_download(client, bucket, key("subbasin_raster", f"datasets/{dsid}/subbasins.tif"), cache_root / "processed" / "subbasins.tif"),
        "flowdir": _r2_download(client, bucket, key("flowdir", "shared/flowdir.tif"), cache_root / "shared" / "flowdir.tif"),
        "official": _r2_download(client, bucket, ref_key("official", "reference/official_reference.gpkg"), cache_root / "reference" / "official_reference.gpkg"),
        "rivers_original": _r2_download(client, bucket, ref_key("rivers_original", "reference/official_rivers_original.gpkg"), cache_root / "reference" / "official_rivers_original.gpkg"),
        "toponim": _r2_download(client, bucket, ref_key("toponim", "reference/toponim.sqlite"), cache_root / "reference" / "toponim.sqlite"),
    }

    streams = gpd.read_file(paths["engine"], layer="streams_web").reset_index(drop=True)
    subbasins = gpd.read_file(paths["engine"], layer="subbasins_web").reset_index(drop=True)
    basins = gpd.read_file(paths["official"], layer="official_basins").reset_index(drop=True)
    rivers = gpd.read_file(paths["official"], layer="official_rivers").reset_index(drop=True)
    rivers_original = gpd.read_file(paths["rivers_original"], layer="jaringan_sungai").reset_index(drop=True)
    crosswalk = pd.read_csv(paths["crosswalk"], dtype={"official_basin_code": str})
    try:
        summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    except Exception:
        summary = {}
    try:
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    except Exception:
        metadata = {"dataset_id": dsid}
    if not isinstance(metadata, dict):
        metadata = {"dataset_id": dsid}
    metadata.setdefault("dataset_id", dsid)
    metadata["runtime_backend"] = "r2"

    if streams.empty or subbasins.empty or basins.empty or rivers.empty:
        raise RuntimeError(f"Runtime bundle R2 '{dsid}' kosong/tidak lengkap.")
    if len(streams) != len(subbasins):
        raise RuntimeError(f"Runtime R2 tidak 1:1: streams={len(streams)} subbasins={len(subbasins)}")
    if crosswalk.empty or len(crosswalk) != len(subbasins):
        raise RuntimeError(f"Crosswalk R2 tidak lengkap: crosswalk={len(crosswalk)} subbasins={len(subbasins)}")

    map_assets_base = os.getenv("R2_MAP_ASSETS_PUBLIC_BASE", "").strip().rstrip("/") or None
    return RuntimeBundle(
        backend="r2",
        active_dataset_id=dsid,
        active_dataset_metadata=metadata,
        streams=streams,
        subbasins=subbasins,
        official_basins=basins,
        official_rivers=rivers,
        official_rivers_original=rivers_original,
        crosswalk=crosswalk,
        official_summary=summary if isinstance(summary, dict) else {},
        fdir_path=paths["flowdir"],
        subbasin_raster_path=paths["subbasin_raster"],
        toponym_db_path=paths["toponim"],
        map_assets_public_base=map_assets_base,
    )

def _resolve_local_dataset(root: Path, requested_dataset_id: str | None) -> str:
    if requested_dataset_id:
        return requested_dataset_id
    active_path = root / "data" / "active_dataset.json"
    if active_path.exists():
        try:
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            value = str(payload.get("dataset", "")).strip()
            if value:
                return value
        except Exception as exc:
            raise RuntimeError(f"Gagal membaca {active_path}: {exc}") from exc
    return "current"


def _load_local(root: Path, requested_dataset_id: str | None) -> RuntimeBundle:
    dsid = _resolve_local_dataset(root, requested_dataset_id)
    data_dir = root / "data"
    processed = data_dir / "processed" / dsid
    reference = data_dir / "reference"
    paths = {
        "engine": processed / "hydro_engine.gpkg",
        "official": reference / "official_reference.gpkg",
        "rivers_original": reference / "official_rivers_original.gpkg",
        "crosswalk": processed / "crosswalk.csv",
        "summary": processed / "official_summary.json",
        "metadata": processed / "metadata.json",
        "flowdir": data_dir / "shared" / "flowdir.tif",
        "subbasin_raster": processed / "subbasins.tif",
        "toponim": reference / "toponim.sqlite",
    }
    required = [paths[k] for k in ("engine", "official", "rivers_original", "crosswalk", "summary")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            f"Dataset runtime lokal '{dsid}' belum lengkap. Jalankan prepare_data.bat. Missing: {missing}"
        )

    streams = gpd.read_file(paths["engine"], layer="streams_web").reset_index(drop=True)
    subbasins = gpd.read_file(paths["engine"], layer="subbasins_web").reset_index(drop=True)
    basins = gpd.read_file(paths["official"], layer="official_basins").reset_index(drop=True)
    rivers = gpd.read_file(paths["official"], layer="official_rivers").reset_index(drop=True)
    rivers_original = gpd.read_file(paths["rivers_original"], layer="jaringan_sungai").reset_index(drop=True)
    crosswalk = pd.read_csv(paths["crosswalk"], dtype={"official_basin_code": str})
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    if paths["metadata"].exists():
        try:
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        except Exception:
            metadata = {"dataset_id": dsid}
    else:
        metadata = {"dataset_id": dsid}
    metadata["runtime_backend"] = "local"

    return RuntimeBundle(
        backend="local",
        active_dataset_id=dsid,
        active_dataset_metadata=metadata,
        streams=streams,
        subbasins=subbasins,
        official_basins=basins,
        official_rivers=rivers,
        official_rivers_original=rivers_original,
        crosswalk=crosswalk,
        official_summary=summary,
        fdir_path=paths["flowdir"],
        subbasin_raster_path=paths["subbasin_raster"],
        toponym_db_path=paths["toponim"],
        map_assets_public_base=None,
    )


def load_runtime_bundle(root: Path) -> RuntimeBundle:
    load_project_dotenv(root)
    backend = os.getenv("DATA_BACKEND", "local").strip().lower() or "local"
    requested = os.getenv("HYDRO_DATASET", "").strip() or None
    if backend == "local":
        return _load_local(root, requested)
    if backend == "r2":
        return _load_r2(root, requested)
    raise RuntimeError("DATA_BACKEND harus 'local' atau 'r2'.")
