from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from api.app import app


async def _asgi_get(path: str, *, accept_encoding: str | None = None):
    request_sent = False
    messages: list[dict] = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    headers = []
    if accept_encoding:
        headers.append((b"accept-encoding", accept_encoding.encode("ascii")))
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("test", 123),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in start["headers"]}
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], response_headers, body


class ShellPerformanceTests(unittest.TestCase):
    def test_static_assets_are_long_lived_and_compressed(self):
        status, headers, _ = asyncio.run(_asgi_get("/static/css/spatial.css", accept_encoding="gzip"))

        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(headers["content-encoding"], "gzip")
        self.assertIn("accept-encoding", headers.get("vary", "").lower())

    def test_html_revalidates_instead_of_being_stale(self):
        status, headers, body = asyncio.run(_asgi_get("/"))

        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-cache")
        html = body.decode("utf-8")
        self.assertIn("window.DTA_CORE_WARM_PROMISE=fetch('/api/health'", html)
        self.assertIn('<script defer src="/static/js/spatial.js?v=1.3.4-same-origin-map-assets"></script>', html)
        self.assertNotIn('<script src="https://cdn.jsdelivr.net/npm/chart.js', html)

    def test_location_check_has_no_blocking_status_message(self):
        source = (Path(__file__).parents[1] / "static" / "js" / "spatial.js").read_text(encoding="utf-8")

        self.assertNotIn("Memeriksa lokasi titik", source)
        self.assertNotIn("Memeriksa lokasi baru", source)
        self.assertIn("readApiJsonResponse", source)
        self.assertIn("delete copy.hydrologic_analysis", source)

    def test_point_name_limit_warning_is_shown_only_at_maximum(self):
        source = (Path(__file__).parents[1] / "static" / "js" / "spatial.js").read_text(encoding="utf-8")

        self.assertIn("input.value.length>=POINT_NAME_MAX_LENGTH", source)
        self.assertIn("setPointNameLimitWarning(input,input.value.length>=POINT_NAME_MAX_LENGTH)", source)
        self.assertIn("maxlength=\"25\"", source)
        self.assertIn("Maksimal 25 karakter.", source)

    def test_map_assets_use_shell_without_warming_core(self):
        with TemporaryDirectory() as directory:
            asset_dir = Path(directory) / "data"
            asset_dir.mkdir()
            (asset_dir / "official_basins.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
            with patch("api.app.STATIC_DIR", Path(directory)), patch("api.app._load_core_app_sync", side_effect=AssertionError("core warmed")):
                status, headers, body = asyncio.run(_asgi_get("/api/map-assets/official-basins"))
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/geo+json")
        self.assertIn(b"FeatureCollection", body)

    def test_map_assets_stream_from_r2_on_app_origin(self):
        body = Mock()
        body.read.side_effect = [b'{"type":"FeatureCollection","features":[]}', b'']
        client = Mock()
        client.get_object.return_value = {"Body": body}
        with TemporaryDirectory() as directory:
            with patch("api.app.STATIC_DIR", Path(directory)), patch("api.app.ROOT_DIR", Path(directory)), \
                 patch("api.app._map_asset_client", return_value=client), \
                 patch("api.app._load_core_app_sync", side_effect=AssertionError("core warmed")), \
                 patch.dict(os.environ, {"R2_MAP_ASSETS_BUCKET": "test-map-assets"}):
                status, headers, data = asyncio.run(_asgi_get("/api/map-assets/official-rivers-z6-8"))
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/geo+json")
        self.assertIn(b"FeatureCollection", data)
        client.get_object.assert_called_once_with(Bucket="test-map-assets", Key="official_rivers_z6_8.geojson")
        body.close.assert_called_once()

    def test_map_assets_can_proxy_public_r2_without_bucket_access(self):
        body = Mock()
        body.read.side_effect = [b'{"type":"FeatureCollection","features":[]}', b'']
        with TemporaryDirectory() as directory:
            with patch("api.app.STATIC_DIR", Path(directory)), patch("api.app.ROOT_DIR", Path(directory)), \
                 patch("api.app.urllib.request.urlopen", return_value=body) as open_public, \
                 patch("api.app._map_asset_client", side_effect=AssertionError("S3 opened")), \
                 patch.dict(os.environ, {"R2_MAP_ASSETS_BUCKET": "", "R2_MAP_ASSETS_PUBLIC_BASE": "https://example.r2.dev"}):
                status, _, data = asyncio.run(_asgi_get("/api/map-assets/official-basins"))
        self.assertEqual(status, 200)
        self.assertIn(b"FeatureCollection", data)
        open_public.assert_called_once_with("https://example.r2.dev/official_basins.geojson", timeout=25)
        body.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
