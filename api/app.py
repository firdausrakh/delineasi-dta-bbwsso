"""Application entry point for Delineasi DTA BBWS Serayu Opak.

The visible WebGIS shell is intentionally served without importing the heavy GIS
engine.  This lets first paint happen immediately on a cold container while the
hydrologic runtime (GeoPandas/Rasterio/R2 bundle/STRtree indexes) warms in
parallel as soon as the browser requests an API endpoint.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
TEMPLATES_DIR = ROOT_DIR / "templates"
SHELL_VERSION = "1.3.2"
MAP_ASSET_FILENAMES = {
    "official-basins": "official_basins.geojson",
    "official-rivers-z6-8": "official_rivers_z6_8.geojson",
    "official-rivers-z8-10": "official_rivers_z8_10.geojson",
    "official-rivers-z10-11": "official_rivers_z10_11.geojson",
    "official-rivers-z11-12": "official_rivers_z11_12.geojson",
    "official-rivers-z12-14": "official_rivers_z12_14.geojson",
    "official-rivers": "official_rivers.geojson",
}


def _load_project_dotenv_lightweight() -> None:
    """Load ROOT/.env without importing the GIS runtime or third-party dotenv."""
    path = ROOT_DIR / ".env"
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_project_dotenv_lightweight()

# The dotenv loader above is intentionally lightweight, so resolve this only
# after it has populated the production environment.
MAP_ASSETS_PUBLIC_BASE = os.getenv("R2_MAP_ASSETS_PUBLIC_BASE", "").strip().rstrip("/")

shell = FastAPI(title="Delineasi DTA Web Shell", version=SHELL_VERSION)
shell.add_middleware(GZipMiddleware, minimum_size=1000)
shell.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@shell.middleware("http")
async def shell_cache_headers(request: Request, call_next):
    """Cache and compress the lightweight first-paint path too.

    Root/static requests intentionally never enter ``api.core``, so the cache
    middleware declared there cannot affect the assets that matter most to the
    initial render.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif request.url.path == "/":
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@shell.get("/")
def index(request: Request):
    # Production map display assets are public R2 objects, so the map can draw
    # basin/river layers before the heavy hydrologic engine has finished warming.
    return templates.TemplateResponse(
        request=request,
        name="spatial.html",
        context={
            "map_assets_public_base": os.getenv("R2_MAP_ASSETS_PUBLIC_BASE", "").strip().rstrip("/"),
            # A deployment-level value can be supplied explicitly. If omitted,
            # cache validation is left to the public object/CDN headers.
            "map_assets_version": os.getenv("R2_MAP_ASSETS_VERSION", "").strip() or SHELL_VERSION,
        },
    )


@shell.get("/api/map-assets/{asset_key}")
def proxy_map_asset(asset_key: str, proxy: int = 0, v: str = ""):
    """Serve a CORS-independent fallback for public R2 map display assets.

    Normal map requests still go directly to the public R2 hostname.  The
    browser switches to this endpoint only after that request fails, which
    avoids a Chrome-specific CORS/CDN cache failure without making Vercel the
    normal data path.
    """
    filename = MAP_ASSET_FILENAMES.get(asset_key)
    if not filename:
        raise HTTPException(status_code=404, detail="Map asset tidak ditemukan.")
    if proxy != 1 or not MAP_ASSETS_PUBLIC_BASE:
        raise HTTPException(status_code=404, detail="Map asset proxy tidak tersedia.")

    url = f"{MAP_ASSETS_PUBLIC_BASE}/{filename}"
    if v:
        url = f"{url}?{urllib.parse.urlencode({'v': v})}"
    try:
        upstream = urllib.request.urlopen(url, timeout=30)
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Map asset upstream tidak dapat dimuat.") from exc

    content_type = upstream.headers.get_content_type() or "application/geo+json"
    content_length = upstream.headers.get("Content-Length")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if content_length:
        headers["Content-Length"] = content_length

    def chunks():
        try:
            while data := upstream.read(64 * 1024):
                yield data
        finally:
            upstream.close()

    return StreamingResponse(chunks(), media_type=content_type, headers=headers)


_core_app: Any | None = None
_core_error: BaseException | None = None
_core_error_at = 0.0
_core_load_lock = threading.Lock()


def _load_core_app_sync():
    """Import the GIS application exactly once, outside the first-paint path."""
    global _core_app, _core_error, _core_error_at
    if _core_app is not None:
        return _core_app
    # Avoid a thundering herd immediately after a failed R2/network startup, but
    # allow the next request to retry instead of poisoning the worker forever.
    if _core_error is not None and (time.monotonic() - _core_error_at) < 2.0:
        raise _core_error
    with _core_load_lock:
        if _core_app is not None:
            return _core_app
        if _core_error is not None and (time.monotonic() - _core_error_at) < 2.0:
            raise _core_error
        _core_error = None
        try:
            module = importlib.import_module("api.core")
            _core_app = module.app
            return _core_app
        except BaseException as exc:
            _core_error = exc
            _core_error_at = time.monotonic()
            raise


class LazyCoreDispatcher:
    """Serve the lightweight shell first; lazily delegate API traffic to core."""

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") not in {"http", "websocket"}:
            await shell(scope, receive, send)
            return

        # The root page and static files never need the heavy GIS runtime.
        if path == "/" or path.startswith("/static/"):
            await shell(scope, receive, send)
            return

        # Keep the optional R2 proxy off the GIS cold-start path.  Requests
        # without the explicit proxy query still fall through to core so local
        # development can generate display assets from local data as before.
        if path.startswith("/api/map-assets/") and b"proxy=1" in scope.get("query_string", b"") and MAP_ASSETS_PUBLIC_BASE:
            await shell(scope, receive, send)
            return

        # API/docs/other application routes initialize the engine in a worker
        # thread so the event loop can continue serving already-open shell assets.
        try:
            core_app = await asyncio.to_thread(_load_core_app_sync)
        except BaseException as exc:
            if scope.get("type") != "http":
                raise
            payload = (
                '{"detail":"Engine hidrologi belum dapat diinisialisasi.",'
                f'"error":"{type(exc).__name__}"}}'
            ).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"retry-after", b"2"),
                ],
            })
            await send({"type": "http.response.body", "body": payload})
            return
        await core_app(scope, receive, send)


app = LazyCoreDispatcher()


if __name__ == "__main__":
    import uvicorn

    # Run the already-created ASGI callable directly. This keeps `python api/app.py`
    # working even when the repository root is not on Python's import path.
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
