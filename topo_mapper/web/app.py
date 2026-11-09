"""FastAPI backend for the interactive topology viewer.

    topo-mapper serve --in topology.json            # CDP/LLDP snapshot
    topo-mapper serve --db /data/probe.db           # live hop monitoring

Endpoints:
    GET /               the Cytoscape.js single-page viewer
    GET /simple         static HTML report (tables, no JavaScript)
    GET /api/topology   Cytoscape elements + meta (what the viewer fetches)
    GET /api/snapshot   the raw snapshot
    GET /api/paths      per-target hop tables               (--db only)
    GET /api/changes    recent route changes                (--db only)
    GET /metrics        Prometheus exposition               (--db only)
    GET /healthz        liveness, no auth, no data

Everything except /healthz requires HTTP Basic auth when TOPO_WEB_PASSWORD is
set, and the server refuses to bind a non-loopback address without it.
"""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

from ..exporters import to_cytoscape, to_simple_html
from ..graph import load_snapshot
from .security import (
    OPEN_PATHS,
    SECURITY_HEADERS,
    AuthConfig,
    FailureLimiter,
    credentials_match,
    ensure_safe_bind,
)

log = logging.getLogger(__name__)
_STATIC = Path(__file__).with_name("static")
_NO_STORE_PREFIXES = ("/api/", "/metrics", "/simple")


def _require_web_deps():
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "The web viewer needs FastAPI. Install extras: pip install 'topo-mapper[web]'"
        ) from exc


def create_app(
    snapshot_path: str | Path | None = None,
    *,
    db_path: str | Path | None = None,
    auth: AuthConfig | None = None,
    redact: bool = True,
):
    _require_web_deps()
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

    from ..probes.graphview import build_changes_api, build_path_snapshot, build_paths_api
    from ..probes.metrics import CONTENT_TYPE, render_metrics
    from ..probes.redact import Redactor
    from ..probes.store import ProbeStore, StoreUnavailable

    if snapshot_path is None and db_path is None:
        raise ValueError("create_app needs a snapshot_path or a db_path")

    app = FastAPI(
        title="Topo Mapper", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    limiter = FailureLimiter()
    ephemeral_salt = secrets.token_hex(16)

    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        if auth is not None and path not in OPEN_PATHS:
            client = request.client.host if request.client else "unknown"
            if limiter.blocked(client):
                return PlainTextResponse("Too many failed attempts", status_code=429,
                                         headers={"Retry-After": "300", **SECURITY_HEADERS})
            if not credentials_match(request.headers.get("authorization"), auth):
                limiter.failure(client)
                return PlainTextResponse(
                    "Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="topo-mapper", charset="UTF-8"',
                             **SECURITY_HEADERS})
            limiter.success(client)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if path.startswith(_NO_STORE_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        return response

    def open_store() -> tuple[ProbeStore, Redactor]:
        if db_path is None:
            raise HTTPException(status_code=404)
        try:
            store = ProbeStore(db_path, readonly=True)
        except StoreUnavailable:
            raise HTTPException(status_code=503, detail="No probe data yet") from None
        return store, Redactor(store.salt() or ephemeral_salt, enabled=redact)

    def current_snapshot() -> dict:
        if db_path is None:
            return load_snapshot(snapshot_path)
        try:
            store, redactor = open_store()
        except HTTPException:
            return {"version": 1, "mode": "probe", "redacted": redact, "generated_at": None,
                    "seeds": [], "stats": {}, "devices": [], "links": []}
        with store:
            return build_path_snapshot(store, redactor)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(_STATIC / "index.html")

    @app.get("/static/cytoscape.min.js", include_in_schema=False)
    def cytoscape_js():
        return FileResponse(_STATIC / "cytoscape.min.js", media_type="text/javascript",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/simple", include_in_schema=False)
    def simple():
        return HTMLResponse(to_simple_html(current_snapshot()))

    @app.get("/api/topology")
    def topology():
        return JSONResponse(to_cytoscape(current_snapshot()))

    @app.get("/api/snapshot")
    def snapshot():
        return JSONResponse(current_snapshot())

    @app.get("/api/paths")
    def paths():
        store, redactor = open_store()
        with store:
            return JSONResponse(build_paths_api(store, redactor, time.time()))

    @app.get("/api/changes")
    def changes(limit: int = 50):
        store, redactor = open_store()
        with store:
            return JSONResponse(build_changes_api(store, redactor, limit))

    @app.get("/metrics")
    def metrics():
        store, redactor = open_store()
        with store:
            return Response(render_metrics(store, redactor), media_type=CONTENT_TYPE)

    return app


def serve(
    snapshot_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    db_path: str | Path | None = None,
    auth: AuthConfig | None = None,
    redact: bool = True,
) -> None:
    _require_web_deps()
    import uvicorn

    ensure_safe_bind(host, auth)
    if auth is None:
        log.warning("No TOPO_WEB_PASSWORD set: serving without authentication on loopback only")
    app = create_app(snapshot_path, db_path=db_path, auth=auth, redact=redact)
    uvicorn.run(app, host=host, port=port, server_header=False)
