from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from api.app import app


async def _asgi_get(path: str, *, accept_encoding: str | None = None, host: str = "testserver"):
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
    headers.append((b"host", host.encode("ascii")))
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
            "server": (host.split(":", 1)[0], 80),
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
        self.assertIn('<script defer src="/static/js/spatial.js?v=1.3.5-geodata-rewrite"></script>', html)
        self.assertIn("mapAssetsBase", html)
        self.assertNotIn('<script src="https://cdn.jsdelivr.net/npm/chart.js', html)

    def test_geodata_rewrite_precedes_container_fallback(self):
        config = json.loads((Path(__file__).parents[1] / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(config["rewrites"][0]["source"], "/geodata/:path*")
        self.assertIn(".r2.dev/:path*", config["rewrites"][0]["destination"])

    def test_public_r2_base_is_used_only_on_localhost(self):
        with patch.dict(os.environ, {"R2_MAP_ASSETS_PUBLIC_BASE": "https://assets.example"}):
            _, _, local_body = asyncio.run(_asgi_get("/", host="localhost:8000"))
            _, _, production_body = asyncio.run(_asgi_get("/", host="delineasi-dta-bbwsso.vercel.app"))

        self.assertIn('mapAssetsBase: "https://assets.example"', local_body.decode("utf-8"))
        self.assertIn('mapAssetsBase: ""', production_body.decode("utf-8"))

    def test_map_assets_use_same_origin_geodata_in_production(self):
        source = (Path(__file__).parents[1] / "static" / "js" / "spatial.js").read_text(encoding="utf-8")
        self.assertIn("`/geodata/${filename}`", source)
        self.assertNotIn("/api/map-assets/${key}", source)

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


if __name__ == "__main__":
    unittest.main()
