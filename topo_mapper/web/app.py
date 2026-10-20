"""Minimal FastAPI backend for the interactive topology viewer.

    topo-mapper serve --in topology.json --port 8000

Endpoints:
    GET /               -> the Cytoscape.js single-page viewer
    GET /simple         -> static HTML report (tables, no JavaScript)
    GET /api/topology   -> Cytoscape elements + meta (what the viewer fetches)
    GET /api/snapshot   -> the raw discovery snapshot
"""
from __future__ import annotations

from pathlib import Path

from ..exporters import to_cytoscape, to_simple_html
from ..graph import load_snapshot

_STATIC = Path(__file__).with_name("static")


def create_app(snapshot_path: str | Path):
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "The web viewer needs FastAPI. Install extras: pip install 'topo-mapper[web]'"
        ) from exc

    snapshot_path = Path(snapshot_path)
    app = FastAPI(title="Topo Mapper", version="0.1.0")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(_STATIC / "index.html")

    @app.get("/simple", include_in_schema=False)
    def simple():
        return HTMLResponse(to_simple_html(load_snapshot(snapshot_path)))

    @app.get("/api/topology")
    def topology():
        return JSONResponse(to_cytoscape(load_snapshot(snapshot_path)))

    @app.get("/api/snapshot")
    def snapshot():
        return JSONResponse(load_snapshot(snapshot_path))

    return app


def serve(snapshot_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "The web viewer needs uvicorn. Install extras: pip install 'topo-mapper[web]'"
        ) from exc

    uvicorn.run(create_app(snapshot_path), host=host, port=port)
