from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


@dataclass(frozen=True)
class RuntimeObjectRef:
    bucket: str
    key: str
    local_path: Path
    expected_size: int | None = None
    expected_sha256: str | None = None


@dataclass
class RuntimeBundle:
    backend: str
    active_dataset_id: str
    active_dataset_metadata: dict[str, Any]
    streams: gpd.GeoDataFrame
    subbasins: gpd.GeoDataFrame
    official_basins: gpd.GeoDataFrame
    official_rivers: gpd.GeoDataFrame
    official_rivers_original: gpd.GeoDataFrame | None
    crosswalk: pd.DataFrame
    official_summary: dict[str, Any]
    fdir_path: Path
    subbasin_raster_path: Path
    toponym_db_path: Path | None
    map_assets_public_base: str | None = None
    map_assets_version: str | None = None
    lazy_objects: dict[str, RuntimeObjectRef] = field(default_factory=dict)
    analysis_paths: dict[str, Path] = field(default_factory=dict)


_R2_METRICS_LOCK = threading.Lock()
_R2_METRICS: dict[str, int | float] = {
    "head_requests": 0,
    "get_requests": 0,
    "downloaded_bytes": 0,
    "cache_hits": 0,
    "lazy_downloads": 0,
    "startup_download_ms": 0.0,
}
_LAZY_OBJECT_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LAZY_OBJECT_LOCKS_GUARD = threading.Lock()


def _metric_add(name: str, value: int | float = 1) -> None:
    with _R2_METRICS_LOCK:
        _R2_METRICS[name] = _R2_METRICS.get(name, 0) + value


def get_r2_runtime_metrics() -> dict[str, int | float]:
    with _R2_METRICS_LOCK:
        payload = dict(_R2_METRICS)
    payload["startup_download_ms"] = round(float(payload.get("startup_download_ms", 0.0)), 1)
    return payload


def _lazy_object_lock(ref: RuntimeObjectRef) -> threading.Lock:
    identity = (ref.bucket, ref.key)
    with _LAZY_OBJECT_LOCKS_GUARD:
        return _LAZY_OBJECT_LOCKS.setdefault(identity, threading.Lock())


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
    download_workers = max(1, int(os.getenv("R2_DOWNLOAD_WORKERS", "4")))
    return boto3.client(
        "s3",
        endpoint_url=_r2_endpoint_url(),
        aws_access_key_id=values["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 4, "mode": "standard"},
            connect_timeout=10,
            read_timeout=120,
            max_pool_connections=max(6, download_workers + 2),
            tcp_keepalive=True,
        ),
    )


def _runtime_cache_root(dataset_id: str) -> Path:
    base = os.getenv("DTA_RUNTIME_CACHE_DIR", "").strip()
    root = Path(base) if base else Path(tempfile.gettempdir()) / "delineasi-dta-runtime"
    return root / dataset_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _r2_download(
    client,
    bucket: str,
    key: str,
    local_path: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> Path:
    """Download one R2 object with manifest-first cache validation.

    Manifest size/SHA metadata avoids a separate HEAD request on warm workers.
    Older manifests remain supported and fall back to ETag validation.
    """
    refresh = os.getenv("R2_REFRESH_CACHE", "0").strip().lower() in {"1", "true", "yes", "y"}
    verify_sha = os.getenv("R2_VERIFY_DOWNLOAD_SHA256", "0").strip().lower() in {"1", "true", "yes", "y"}
    etag_path = local_path.with_suffix(local_path.suffix + ".etag")
    sha_path = local_path.with_suffix(local_path.suffix + ".sha256")

    if not refresh and local_path.exists() and local_path.stat().st_size > 0 and expected_size:
        size_ok = local_path.stat().st_size == int(expected_size)
        sha_ok = not expected_sha256 or (
            sha_path.exists() and sha_path.read_text(encoding="utf-8").strip() == expected_sha256
        )
        if size_ok and sha_ok:
            _metric_add("cache_hits")
            return local_path

    etag = ""
    remote_size = int(expected_size or 0)
    if not expected_size:
        try:
            _metric_add("head_requests")
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise RuntimeError(f"R2 object tidak ditemukan/tidak dapat dibaca: {bucket}/{key}: {exc}") from exc
        etag = str(head.get("ETag", "")).strip('"')
        remote_size = int(head.get("ContentLength") or 0)
    cached_etag = etag_path.read_text(encoding="utf-8").strip() if etag_path.exists() else ""
    if (
        not refresh
        and local_path.exists()
        and local_path.stat().st_size > 0
        and (remote_size <= 0 or local_path.stat().st_size == remote_size)
        and etag
        and cached_etag == etag
    ):
        _metric_add("cache_hits")
        return local_path

    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_path.with_suffix(local_path.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        _metric_add("get_requests")
        client.download_file(bucket, key, str(tmp))
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Gagal download R2 {bucket}/{key}: {exc}") from exc
    if not tmp.exists() or tmp.stat().st_size <= 0:
        raise RuntimeError(f"R2 object kosong setelah download: {bucket}/{key}")
    if remote_size > 0 and tmp.stat().st_size != remote_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Ukuran R2 object tidak sesuai setelah download: {bucket}/{key}: "
            f"{tmp.stat().st_size if tmp.exists() else 0} != {remote_size}"
        )
    if expected_sha256 and verify_sha:
        actual_sha = _sha256(tmp)
        if actual_sha != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"SHA256 R2 object tidak sesuai: {bucket}/{key}")
    tmp.replace(local_path)
    _metric_add("downloaded_bytes", int(local_path.stat().st_size))
    if etag:
        etag_path.write_text(etag, encoding="utf-8")
    if expected_sha256:
        sha_path.write_text(expected_sha256, encoding="utf-8")
    return local_path


def _download_ref(client, ref: RuntimeObjectRef) -> Path:
    return _r2_download(
        client,
        ref.bucket,
        ref.key,
        ref.local_path,
        expected_size=ref.expected_size,
        expected_sha256=ref.expected_sha256,
    )


def _download_many(client, refs: dict[str, RuntimeObjectRef]) -> dict[str, Path]:
    """Download independent R2 objects concurrently to reduce cold-start latency."""
    workers = max(1, min(int(os.getenv("R2_DOWNLOAD_WORKERS", "4")), len(refs)))
    if workers == 1:
        return {name: _download_ref(client, ref) for name, ref in refs.items()}
    output: dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="r2-download") as pool:
        futures = {pool.submit(_download_ref, client, ref): name for name, ref in refs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                output[name] = future.result()
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise
    return output


def _r2_manifest(client, bucket: str) -> dict[str, Any]:
    key = os.getenv("R2_MANIFEST_KEY", "manifest.json").strip() or "manifest.json"
    try:
        _metric_add("get_requests")
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
    object_meta = manifest.get("objects") or {}

    def ref(name: str, object_key: str, local_path: Path) -> RuntimeObjectRef:
        meta = object_meta.get(object_key) if isinstance(object_meta, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        size = meta.get("size")
        return RuntimeObjectRef(
            bucket=bucket,
            key=object_key,
            local_path=local_path,
            expected_size=int(size) if size is not None else None,
            expected_sha256=str(meta.get("sha256") or "").strip() or None,
        )

    refs = {
        "engine": ref("engine", key("engine", f"datasets/{dsid}/hydro_engine.gpkg"), cache_root / "processed" / "hydro_engine.gpkg"),
        "crosswalk": ref("crosswalk", key("crosswalk", f"datasets/{dsid}/crosswalk.csv"), cache_root / "processed" / "crosswalk.csv"),
        "summary": ref("summary", key("summary", f"datasets/{dsid}/official_summary.json"), cache_root / "processed" / "official_summary.json"),
        "metadata": ref("metadata", key("metadata", f"datasets/{dsid}/metadata.json"), cache_root / "processed" / "metadata.json"),
        "subbasin_raster": ref("subbasin_raster", key("subbasin_raster", f"datasets/{dsid}/subbasins.tif"), cache_root / "processed" / "subbasins.tif"),
        "flowdir": ref("flowdir", key("flowdir", "shared/flowdir.tif"), cache_root / "shared" / "flowdir.tif"),
        "official": ref("official", ref_key("official", "reference/official_reference.gpkg"), cache_root / "reference" / "official_reference.gpkg"),
    }
    lazy_objects = {
        "rivers_original": ref(
            "rivers_original",
            ref_key("rivers_original", "reference/official_rivers_original.gpkg"),
            cache_root / "reference" / "official_rivers_original.gpkg",
        ),
        "toponim": ref(
            "toponim",
            ref_key("toponim", "reference/toponim.sqlite"),
            cache_root / "reference" / "toponim.sqlite",
        ),
        "dem": ref("dem", key("dem", "shared/dem.tif"), cache_root / "shared" / "dem.tif"),
        "plen": ref("plen", key("plen", "shared/plen.tif"), cache_root / "shared" / "plen.tif"),
        "cn2": ref("cn2", key("cn2", "shared/cn2.tif"), cache_root / "shared" / "cn2.tif"),
        "landcover": ref("landcover", key("landcover", "shared/landcover.tif"), cache_root / "shared" / "landcover.tif"),
        "streams_analysis": ref("streams_analysis", key("streams_analysis", "shared/streams_analysis.zip"), cache_root / "shared" / "streams_analysis.zip"),
        "landsystem": ref("landsystem", key("landsystem", "shared/landsystem.zip"), cache_root / "shared" / "landsystem.zip"),
    }
    download_started = time.perf_counter()
    paths = _download_many(client, refs)
    _metric_add("startup_download_ms", (time.perf_counter() - download_started) * 1000.0)

    streams = gpd.read_file(paths["engine"], layer="streams_web").reset_index(drop=True)
    subbasins = gpd.read_file(paths["engine"], layer="subbasins_web").reset_index(drop=True)
    basins = gpd.read_file(paths["official"], layer="official_basins").reset_index(drop=True)
    rivers = gpd.read_file(paths["official"], layer="official_rivers").reset_index(drop=True)
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
    metadata["vector_loading"] = "startup_core_lazy_export_reference"

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
        official_rivers_original=None,
        crosswalk=crosswalk,
        official_summary=summary if isinstance(summary, dict) else {},
        fdir_path=paths["flowdir"],
        subbasin_raster_path=paths["subbasin_raster"],
        toponym_db_path=lazy_objects["toponim"].local_path,
        map_assets_public_base=map_assets_base,
        map_assets_version=str(manifest.get("map_assets_version") or "").strip() or None,
        lazy_objects=lazy_objects,
        analysis_paths={name: ref.local_path for name, ref in lazy_objects.items() if name in {"dem", "plen", "cn2", "landcover", "streams_analysis", "landsystem"}},
    )


def ensure_runtime_object(bundle: RuntimeBundle, name: str) -> Path:
    """Materialize one optional R2 object on its first actual use."""
    ref = bundle.lazy_objects.get(name)
    if ref is None:
        if name == "toponim" and bundle.toponym_db_path is not None:
            return bundle.toponym_db_path
        raise RuntimeError(f"Runtime object '{name}' tidak tersedia.")
    lock = _lazy_object_lock(ref)
    with lock:
        before = ref.local_path.exists()
        path = _download_ref(_r2_client(), ref)
        if not before:
            _metric_add("lazy_downloads")
        return path


def ensure_toponym_db_path(bundle: RuntimeBundle) -> Path:
    if bundle.backend == "r2" and "toponim" in bundle.lazy_objects:
        return ensure_runtime_object(bundle, "toponim")
    if bundle.toponym_db_path is None:
        raise RuntimeError("Database toponim tidak tersedia.")
    return bundle.toponym_db_path


def ensure_official_rivers_original(bundle: RuntimeBundle) -> gpd.GeoDataFrame:
    if bundle.official_rivers_original is not None:
        return bundle.official_rivers_original
    if bundle.backend != "r2":
        raise RuntimeError("Jaringan sungai asli tidak tersedia.")
    ref = bundle.lazy_objects.get("rivers_original")
    if ref is None:
        raise RuntimeError("Object jaringan sungai asli tidak tercantum di manifest R2.")
    lock = _lazy_object_lock(ref)
    with lock:
        if bundle.official_rivers_original is None:
            path = _download_ref(_r2_client(), ref)
            _metric_add("lazy_downloads")
            frame = gpd.read_file(path, layer="jaringan_sungai").reset_index(drop=True)
            if frame.empty:
                raise RuntimeError("Jaringan sungai asli R2 kosong.")
            bundle.official_rivers_original = frame
    return bundle.official_rivers_original

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
        analysis_paths={
            "dem": data_dir / "shared" / "dem.tif", "plen": data_dir / "shared" / "plen.tif",
            "cn2": data_dir / "shared" / "cn2.tif", "landcover": data_dir / "shared" / "landcover.tif",
            "streams_analysis": data_dir / "shared" / "streams_analysis.zip",
            "landsystem": data_dir / "shared" / "landsystem.zip",
        },
    )


def load_runtime_bundle(root: Path) -> RuntimeBundle:
    started = time.perf_counter()
    load_project_dotenv(root)
    backend = os.getenv("DATA_BACKEND", "local").strip().lower() or "local"
    requested = os.getenv("HYDRO_DATASET", "").strip() or None
    if backend == "local":
        bundle = _load_local(root, requested)
    elif backend == "r2":
        bundle = _load_r2(root, requested)
    else:
        raise RuntimeError("DATA_BACKEND harus 'local' atau 'r2'.")
    bundle.active_dataset_metadata["runtime_bundle_load_ms"] = round(
        (time.perf_counter() - started) * 1000.0, 1
    )
    return bundle
