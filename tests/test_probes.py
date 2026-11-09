import json
import os
import sqlite3
import subprocess

import pytest

from topo_mapper.probes import (
    Hop,
    PathResult,
    ProbeError,
    ProbeStore,
    Redactor,
    StoreUnavailable,
    Target,
    TargetError,
    effective_losses,
    hop_status,
    load_targets,
    parse_mtr_json,
    run_mtr,
)
from topo_mapper.probes.graphview import build_changes_api, build_path_snapshot, build_paths_api
from topo_mapper.probes.metrics import render_metrics
from topo_mapper.probes.monitor import Monitor
from topo_mapper.probes.store import same_path
from topo_mapper.probes.targets import parse_targets


def hub(count, host, loss=0.0, avg=1.0, snt=10):
    return {"count": count, "host": host, "Loss%": loss, "Snt": snt, "Last": avg,
            "Avg": avg, "Best": avg / 2, "Wrst": avg * 2, "StDev": 0.1}


def mtr_json(*hubs):
    return json.dumps({"report": {"mtr": {"src": "box", "dst": "target"}, "hubs": list(hubs)}})


def result(target, hosts, *, reached=True, ts=1000.0, loss=None, ok=True, error=None):
    loss = loss or {}
    hops = tuple(
        Hop(ttl=i + 1, host=h, loss=loss.get(i + 1, 0.0), sent=10, avg=float(i + 1),
            best=0.5, worst=9.0, stdev=0.1)
        for i, h in enumerate(hosts)
    )
    return PathResult(target=target, ts=ts, ok=ok, reached=reached, hops=hops, error=error)


class TestTargets:
    def test_load_and_defaults(self, tmp_path):
        f = tmp_path / "t.yaml"
        f.write_text("defaults: {interval: 120}\ntargets:\n  - {name: modem, host: 192.168.1.1}\n"
                     "  - {name: dns, host: One.One.One.One, interval: 60, count: 5}\n")
        modem, dns = load_targets(f)
        assert (modem.interval, modem.count) == (120, 10)
        assert (dns.host, dns.interval, dns.count) == ("one.one.one.one", 60, 5)

    @pytest.mark.parametrize("host", ["-oProxyCommand=x", "a b", "x;rm -rf /", "", "--help", "a" * 300])
    def test_rejects_unsafe_hosts(self, host):
        with pytest.raises(TargetError):
            parse_targets({"targets": [{"name": "t", "host": host}]})

    @pytest.mark.parametrize("entry", [
        {"name": "bad name", "host": "1.1.1.1"},
        {"name": "-x", "host": "1.1.1.1"},
        {"name": "ok", "host": "1.1.1.1", "interval": 5},
        {"name": "ok", "host": "1.1.1.1", "count": 500},
        {"name": "ok", "host": "1.1.1.1", "interval": "soon"},
    ])
    def test_rejects_bad_fields(self, entry):
        with pytest.raises(TargetError):
            parse_targets({"targets": [entry]})

    def test_rejects_duplicates_empty_and_too_many(self):
        with pytest.raises(TargetError):
            parse_targets({"targets": [{"name": "a", "host": "1.1.1.1"}, {"name": "a", "host": "9.9.9.9"}]})
        with pytest.raises(TargetError):
            parse_targets({"targets": []})
        with pytest.raises(TargetError):
            parse_targets({"targets": [{"name": f"t{i}", "host": "1.1.1.1"} for i in range(26)]})
        with pytest.raises(TargetError):
            parse_targets(["not", "a", "mapping"])

    def test_directory_gives_actionable_error(self, tmp_path):
        with pytest.raises(TargetError, match="directory"):
            load_targets(tmp_path)


class TestMtr:
    def test_parse_with_silent_middle_hop(self):
        hops, reached = parse_mtr_json(mtr_json(
            hub(1, "192.168.1.1"), hub(2, "???", loss=100.0), hub(3, "1.1.1.1", avg=9.5)))
        assert reached and [h.host for h in hops] == ["192.168.1.1", None, "1.1.1.1"]
        assert hops[2].avg == 9.5

    def test_trailing_silence_means_not_reached(self):
        hops, reached = parse_mtr_json(mtr_json(
            hub(1, "192.168.1.1"), hub(2, "???", loss=100.0), hub(3, "???", loss=100.0)))
        assert not reached and [h.host for h in hops] == ["192.168.1.1"]

    def test_tolerates_odd_output(self):
        hops, _ = parse_mtr_json(mtr_json(
            hub("1", "10.0.0.1"), hub(1, "10.9.9.9"), hub(2, "bad host;rm -rf"),
            {"count": 3, "host": "10.0.0.3", "Loss%": "nan", "Avg": "x"},
            {"count": 4, "host": "10.0.0.4", "Loss%": 250}, "garbage"))
        assert [h.host for h in hops] == ["10.0.0.1", None, "10.0.0.3", "10.0.0.4"]
        assert hops[2].loss == 0.0 and hops[3].loss == 100.0

    @pytest.mark.parametrize("text", ["", "not json", "{}", '{"report": {}}', mtr_json()])
    def test_rejects_unusable_output(self, text):
        with pytest.raises(ProbeError):
            parse_mtr_json(text)

    def test_command_is_a_safe_argument_list(self):
        seen = {}

        def runner(cmd, **kwargs):
            seen.update(cmd=cmd, kwargs=kwargs)
            return subprocess.CompletedProcess(cmd, 0, mtr_json(hub(1, "1.1.1.1")), "")

        out = run_mtr(Target("t", "1.1.1.1", count=5), runner=runner, now=lambda: 5.0)
        assert out.ok and out.reached and out.ts == 5.0
        cmd = seen["cmd"]
        assert isinstance(cmd, list) and cmd[-2:] == ["--", "1.1.1.1"]
        assert "-n" in cmd and "-z" not in cmd and "--aslookup" not in cmd
        assert not seen["kwargs"].get("shell")
        assert set(seen["kwargs"]["env"]) == {"PATH", "LC_ALL"}

    def test_failures_become_results_not_exceptions(self):
        def raises(exc):
            def runner(cmd, **kwargs):
                raise exc
            return runner

        t = Target("t", "1.1.1.1")
        assert "not installed" in run_mtr(t, runner=raises(FileNotFoundError())).error
        assert "timed out" in run_mtr(t, runner=raises(subprocess.TimeoutExpired("mtr", 1))).error
        bad = run_mtr(t, runner=lambda c, **k: subprocess.CompletedProcess(c, 1, "", "x" * 500))
        assert not bad.ok and len(bad.error) < 220
        junk = run_mtr(t, runner=lambda c, **k: subprocess.CompletedProcess(c, 0, "<html>", ""))
        assert not junk.ok


class TestAnalysis:
    def test_rate_limited_middle_hop_is_not_loss(self):
        hops = result("t", ["a", "b", "c"], loss={2: 60.0}).hops
        assert effective_losses(hops) == {1: 0.0, 2: 0.0, 3: 0.0}

    def test_loss_that_continues_downstream_is_real(self):
        hops = result("t", ["a", "b", "c"], loss={2: 30.0, 3: 30.0}).hops
        assert effective_losses(hops)[2] == 30.0
        assert hop_status(30.0) == "degraded" and hop_status(100.0) == "down"
        assert hop_status(0.0) == "up" and hop_status(None) == "unknown"

    def test_silent_hops_are_unknown(self):
        assert effective_losses(result("t", ["a", None, "c"]).hops)[2] is None


class TestPathComparison:
    def test_same_path_tolerates_silent_hops_only(self):
        assert same_path("a>b>c", "a>b>c")
        assert same_path("a>b>c", "a>c")
        assert not same_path("a>b>c", "a>x>c")
        assert not same_path("a>b>c", "a>b>d")


class TestStore:
    def test_file_is_private_and_salt_is_stable(self, tmp_path):
        db = tmp_path / "sub" / "p.db"
        with ProbeStore(db) as store:
            salt = store.salt()
        assert oct(os.stat(db).st_mode & 0o777) == "0o600"
        assert len(salt) == 32
        with ProbeStore(db) as again, ProbeStore(db, readonly=True) as ro:
            assert again.salt() == salt == ro.salt()

    def test_route_change_detection(self, tmp_path):
        with ProbeStore(tmp_path / "p.db") as store:
            assert not store.record(result("t", ["a", "b", "c"], ts=1))
            assert not store.record(result("t", ["a", "b", "c"], ts=2))
            assert not store.record(result("t", ["a", None, "c"], ts=3))
            assert not store.record(result("t", ["a"], reached=False, ts=4))
            assert not store.record(result("t", [], ok=False, error="boom", ts=5))
            assert store.record(result("t", ["a", "x", "c"], ts=6))
            assert store.change_counts() == {"t": 1}
            change = store.recent_changes()[0]
            assert (change.old_signature, change.new_signature) == ("a>b>c", "a>x>c")

    def test_first_run_is_never_a_change_and_targets_are_independent(self, tmp_path):
        with ProbeStore(tmp_path / "p.db") as store:
            assert not store.record(result("one", ["a", "b"]))
            assert not store.record(result("two", ["x", "y"]))
            assert store.change_counts() == {"one": 0, "two": 0}

    def test_latest_runs_and_prune_keep_current_state(self, tmp_path):
        with ProbeStore(tmp_path / "p.db") as store:
            store.record(result("t", ["a", "b"], ts=100))
            store.record(result("t", ["a", "c"], ts=200))
            store.record(result("u", ["a", "b"], ts=100))
            assert store.prune(retention_days=1, now=100 + 5 * 86_400) == 1
            runs = {r.target: r for r in store.latest_runs()}
            assert runs["t"].ts == 200 and runs["u"].ts == 100
            assert [h.host for h in runs["t"].hops] == ["a", "c"]
            assert store.recent_changes() == []

    def test_readonly_store_cannot_write(self, tmp_path):
        db = tmp_path / "p.db"
        ProbeStore(db).close()
        with ProbeStore(db, readonly=True) as ro:
            with pytest.raises(sqlite3.OperationalError):
                ro.record(result("t", ["a"]))

    def test_missing_database(self, tmp_path):
        with pytest.raises(StoreUnavailable):
            ProbeStore(tmp_path / "nope.db", readonly=True)


class TestRedactor:
    def test_masks_only_public_addresses(self):
        r = Redactor("salt")
        masked = r.ip("8.8.8.8")
        assert masked.startswith("pub-") and "8.8.8.8" not in masked
        assert masked == r.ip("8.8.8.8") != Redactor("other").ip("8.8.8.8")
        for kept in ["192.168.1.1", "10.0.0.5", "172.18.0.1", "100.64.12.7", "127.0.0.1", "fd00::1"]:
            assert r.ip(kept) == kept
        assert r.ip(None) is None

    def test_disabled_and_scrub(self):
        assert Redactor("s", enabled=False).ip("8.8.8.8") == "8.8.8.8"
        text = Redactor("s").scrub("no route to 8.8.8.8 via 192.168.1.1 at 12:30:45")
        assert "8.8.8.8" not in text and "192.168.1.1" in text and "12:30:45" in text


@pytest.fixture
def populated(tmp_path):
    path = tmp_path / "p.db"
    with ProbeStore(path) as store:
        store.record(result("modem", ["192.168.1.1"], ts=1000))
        store.record(result("cloudflare", ["172.18.0.1", "192.168.1.1", None, "8.8.4.4", "1.1.1.1"],
                            loss={4: 40.0, 5: 40.0}, ts=1000))
        store.record(result("blackhole", ["172.18.0.1", "192.168.1.1"], reached=False, ts=1000))
        store.record(result("cloudflare", ["172.18.0.1", "192.168.1.1", None, "9.9.9.9", "1.1.1.1"],
                            loss={4: 40.0, 5: 40.0}, ts=1060))
        yield path


class TestGraphAndMetrics:
    def test_snapshot_merges_shared_hops_and_masks_public_ips(self, populated):
        with ProbeStore(populated, readonly=True) as store:
            snap = build_path_snapshot(store, Redactor("s"))
        names = {d["name"] for d in snap["devices"]}
        assert "192.168.1.1" in names and "172.18.0.1" in names and "probe" in names
        assert not any(n in names for n in ("1.1.1.1", "9.9.9.9"))
        assert any(n.startswith("pub-") for n in names)
        assert "unreached-blackhole" in names and "silent-cloudflare-3" in names
        assert "1.1.1.1" not in json.dumps(snap) and "9.9.9.9" not in json.dumps(snap)

        by_name = {d["name"]: d for d in snap["devices"]}
        assert by_name["unreached-blackhole"]["errors"] and not by_name["unreached-blackhole"]["reachable"]
        statuses = {l["status"] for l in snap["links"]}
        assert {"up", "degraded", "down", "unknown"} <= statuses
        modem = by_name["192.168.1.1"]
        assert modem["platform"] == "private network" and modem["metrics"]["paths"] >= 2
        assert modem["label"] == "modem" and modem["role"] == "router"  # it also carries other paths
        assert by_name["probe"]["role"] == "endpoint"
        assert any(d["role"] == "endpoint" and d["label"] == "cloudflare" for d in snap["devices"])
        assert snap["stats"]["devices"] == len(snap["devices"])

    def test_unmasked_snapshot_keeps_real_addresses(self, populated):
        with ProbeStore(populated, readonly=True) as store:
            snap = build_path_snapshot(store, Redactor("s", enabled=False))
        assert "1.1.1.1" in {d["name"] for d in snap["devices"]}

    def test_api_payloads(self, populated):
        with ProbeStore(populated, readonly=True) as store:
            paths = build_paths_api(store, Redactor("s"), now=1100.0)
            changes = build_changes_api(store, Redactor("s"))
        by_target = {p["target"]: p for p in paths["paths"]}
        cf = by_target["cloudflare"]
        assert cf["age_seconds"] == 40 and cf["path_changes"] == 1
        assert [h["status"] for h in cf["hops"]] == ["up", "up", "unknown", "degraded", "degraded"]
        assert not by_target["blackhole"]["reached"]
        assert changes["changes"][0]["old_path"][2] != "8.8.4.4"
        assert "1.1.1.1" not in json.dumps(paths) + json.dumps(changes)

    def test_metrics_text(self, populated):
        with ProbeStore(populated, readonly=True) as store:
            text = render_metrics(store, Redactor("s"))
        assert 'topo_probe_up{target="modem"} 1' in text
        assert 'topo_probe_up{target="blackhole"} 0' in text
        assert 'topo_path_changes_total{target="cloudflare"} 1' in text
        assert 'topo_hop_responding{target="cloudflare",hop="3"} 0' in text
        assert 'topo_target_loss_ratio{target="cloudflare"} 0.4' in text
        assert 'topo_hop_info{target="modem",hop="1",host="192.168.1.1",scope="private network"} 1' in text
        assert "1.1.1.1" not in text and "9.9.9.9" not in text
        assert text.count("# TYPE topo_probe_up") == 1 and text.endswith("\n")


class TestMonitor:
    def test_probe_crash_is_recorded_not_raised(self, tmp_path):
        def boom(target):
            raise RuntimeError("secret detail 8.8.8.8")

        with ProbeStore(tmp_path / "p.db") as store:
            monitor = Monitor([Target("t", "1.1.1.1")], store, probe=boom)
            [out] = monitor.run_once()
            assert not out.ok and out.error == "probe crashed"
            assert store.latest_runs()[0].error == "probe crashed"

    def test_run_forever_respects_intervals_and_stop(self, tmp_path):
        import threading

        calls = []
        stop = threading.Event()

        now = [1.0]

        def fake(target):
            calls.append(target.name)
            return result(target.name, ["10.0.0.1"], ts=float(len(calls)))

        def fake_wait(timeout=None):
            now[0] += timeout  # time passes instead of sleeping
            if now[0] > 100:
                stop.set()

        with ProbeStore(tmp_path / "p.db") as store:
            monitor = Monitor([Target("a", "10.0.0.1", interval=30), Target("b", "10.0.0.2", interval=60)],
                              store, probe=fake, clock=lambda: now[0])
            monitor._next_due = {"a": 0.0, "b": 0.0}
            stop.wait = fake_wait
            monitor.run_forever(stop)
        assert calls[:2] == ["a", "b"]
        assert calls.count("a") > calls.count("b") >= 1
