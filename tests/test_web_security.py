import base64
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from topo_mapper.exporters import to_standalone_html  # noqa: E402
from topo_mapper.probes import Hop, PathResult, ProbeStore  # noqa: E402
from topo_mapper.web.app import create_app  # noqa: E402
from topo_mapper.web.security import (  # noqa: E402
    AuthConfig,
    FailureLimiter,
    credentials_match,
    ensure_safe_bind,
)

AUTH = AuthConfig("admin", "correct horse battery")


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "p.db"
    hops = tuple(
        Hop(ttl=i + 1, host=h, avg=float(i + 1)) for i, h in enumerate(["192.168.1.1", "1.1.1.1"])
    )
    with ProbeStore(path) as store:
        store.record(PathResult("cloudflare", 1000.0, True, True, hops))
    return path


@pytest.fixture
def client(db):
    return TestClient(create_app(db_path=db, auth=AUTH))


GOOD = basic("admin", "correct horse battery")


def test_everything_but_healthz_needs_credentials(client):
    assert client.get("/healthz").json() == {"ok": True}
    for path in ["/", "/api/topology", "/api/paths", "/api/changes", "/metrics", "/simple",
                 "/static/cytoscape.min.js"]:
        r = client.get(path)
        assert r.status_code == 401, path
        assert "Basic" in r.headers["www-authenticate"]
        assert client.get(path, headers=basic("admin", "wrong")).status_code == 401
        assert client.get(path, headers=GOOD).status_code == 200, path


def test_security_headers_and_no_docs(client):
    r = client.get("/api/paths", headers=GOOD)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
    assert "http" not in csp
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path, headers=GOOD).status_code == 404


def test_lockout_after_repeated_failures(db):
    client = TestClient(create_app(db_path=db, auth=AUTH))
    for _ in range(5):
        assert client.get("/api/paths", headers=basic("admin", "nope")).status_code == 401
    r = client.get("/api/paths", headers=GOOD)
    assert r.status_code == 429 and r.headers["retry-after"] == "300"


def test_public_addresses_are_masked_by_default(client):
    body = client.get("/api/topology", headers=GOOD).text + client.get("/metrics", headers=GOOD).text
    assert "1.1.1.1" not in body and "pub-" in body and "192.168.1.1" in body


def test_masking_can_be_turned_off(db):
    open_client = TestClient(create_app(db_path=db, redact=False))
    assert "1.1.1.1" in open_client.get("/metrics").text


def test_viewer_has_no_third_party_requests(client):
    html = client.get("/", headers=GOOD).text
    assert "cdnjs" not in html and "https://" not in html.split("<script>")[0]
    js = client.get("/static/cytoscape.min.js", headers=GOOD)
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_no_data_yet_is_graceful(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "missing.db"))
    assert client.get("/api/topology").json()["elements"] == []
    assert client.get("/metrics").status_code == 503


def test_snapshot_mode_still_works_and_probe_endpoints_404(tmp_path):
    snap = tmp_path / "t.json"
    snap.write_text(json.dumps({"version": 1, "generated_at": "x", "seeds": [], "stats": {},
                                "devices": [], "links": []}))
    client = TestClient(create_app(snap))
    assert client.get("/api/topology").status_code == 200
    assert client.get("/metrics").status_code == 404


def test_standalone_export_is_self_contained():
    html = to_standalone_html({"devices": [], "links": [], "stats": {}})
    assert "cdnjs" not in html and 'src="static/' not in html and "cytoscape" in html


def test_bind_safety_and_password_rules(monkeypatch):
    with pytest.raises(SystemExit):
        ensure_safe_bind("0.0.0.0", None)
    ensure_safe_bind("127.0.0.1", None)
    ensure_safe_bind("::1", None)
    ensure_safe_bind("0.0.0.0", AUTH)

    monkeypatch.setenv("TOPO_WEB_PASSWORD", "short")
    with pytest.raises(SystemExit):
        AuthConfig.from_env()
    monkeypatch.setenv("TOPO_WEB_PASSWORD", "long enough password")
    assert AuthConfig.from_env().user == "admin"
    monkeypatch.delenv("TOPO_WEB_PASSWORD")
    assert AuthConfig.from_env() is None


def test_credentials_parser_rejects_garbage():
    for header in [None, "", "Bearer abc", "Basic !!!notbase64", "Basic " + base64.b64encode(b"\xff\xfe:x").decode()]:
        assert not credentials_match(header, AUTH)
    assert credentials_match(GOOD["Authorization"], AUTH)
    assert not credentials_match(basic("admin", "correct horse battery ")["Authorization"], AUTH)


def test_limiter_expires():
    now = [0.0]
    limiter = FailureLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.failure("c")
    assert limiter.blocked("c")
    now[0] = 301
    assert not limiter.blocked("c")
