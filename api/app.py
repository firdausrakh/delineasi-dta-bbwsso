"""Local entry point for Delineasi DTA BBWS Serayu Opak.

Struktur mengikuti repo olah-data-hidrologi-bbwsso: entry point kecil di api/app.py,
logic utama di api/core.py, service GIS di api/services, template dan static terpisah.
"""
from __future__ import annotations
import sys
from pathlib import Path
if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
from api.core import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app:app", host="127.0.0.1", port=8000, reload=False)
