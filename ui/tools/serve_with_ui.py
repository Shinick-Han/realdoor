"""Serve the API and the built UI from one process, one origin, no CORS.

This is the UI stream's own harness for exercising live mode, and it is also the
demonstration of the single line api/app.py still needs. api/app.py already computes
UI_DIR = ROOT / "ui" / "dist" but never mounts it; mounting is the API stream's call to
make, so this file does it from the outside instead of editing a directory it does not own:

    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")

Run:
    python ui/tools/serve_with_ui.py
Then open http://127.0.0.1:8000/?live  -- the ?live switch points the UI at the API on the
same origin. Without it the same page runs entirely on bundled fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi.staticfiles import StaticFiles

from api.app import app

app.mount("/", StaticFiles(directory=str(ROOT / "ui" / "dist"), html=True), name="ui")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
