"""SQLite history for probe results.

The probe process is the only writer. The web viewer opens the same file with
``query_only`` set. The file is created with mode 0600 because path data
reveals the shape of the home network and the ISP's first hops.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .mtr import Hop, PathResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS probe_runs (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    ts REAL NOT NULL,
    ok INTEGER NOT NULL,
    reached INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    signature TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_target_id ON probe_runs(target, id);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON probe_runs(ts);
CREATE TABLE IF NOT EXISTS probe_hops (
    run_id INTEGER NOT NULL REFERENCES probe_runs(id) ON DELETE CASCADE,
    ttl INTEGER NOT NULL,
    host TEXT,
    loss REAL, sent INTEGER, last REAL, avg REAL, best REAL, worst REAL, stdev REAL,
    PRIMARY KEY (run_id, ttl)
);
CREATE TABLE IF NOT EXISTS path_changes (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    ts REAL NOT NULL,
    old_signature TEXT NOT NULL,
    new_signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changes_ts ON path_changes(ts);
CREATE TABLE IF NOT EXISTS target_stats (
    target TEXT PRIMARY KEY,
    path_changes INTEGER NOT NULL DEFAULT 0,
    baseline TEXT NOT NULL DEFAULT ''
);
"""


class StoreUnavailable(RuntimeError):
    """The database does not exist yet (the probe has not run)."""


@dataclass(frozen=True)
class RunRecord:
    id: int
    target: str
    ts: float
    ok: bool
    reached: bool
    error: str | None
    hops: tuple[Hop, ...]


@dataclass(frozen=True)
class PathChange:
    target: str
    ts: float
    old_signature: str
    new_signature: str


def same_path(old: str, new: str) -> bool:
    """True if two signatures describe the same route.

    A hop that stayed silent in one run (ICMP rate limiting) makes one signature
    a subsequence of the other, and that is not a route change. A hop being
    swapped for a different address is.
    """
    a = old.split(">") if old else []
    b = new.split(">") if new else []
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    it = iter(long_)
    return all(any(item == other for other in it) for item in short)


class ProbeStore:
    def __init__(self, path: str | Path, *, readonly: bool = False) -> None:
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            if not self.path.is_file():
                raise StoreUnavailable(f"{self.path} does not exist yet")
            self._db = sqlite3.connect(self.path, timeout=5)
            self._db.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600))
            self._db = sqlite3.connect(self.path, timeout=5)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA)
        self._db.row_factory = sqlite3.Row

    def __enter__(self) -> "ProbeStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def salt(self) -> str:
        """Per-installation salt for masking public IPs. Empty if not created yet."""
        query = "SELECT value FROM meta WHERE key='redact_salt'"
        row = self._db.execute(query).fetchone()
        if row:
            return row["value"]
        if self.readonly:
            return ""
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('redact_salt', ?)",
                (secrets.token_hex(16),),
            )
        return self._db.execute(query).fetchone()["value"]

    def record(self, result: PathResult) -> bool:
        """Store one probe result. Returns True if it revealed a route change."""
        signature = result.signature
        changed = False
        with self._db:
            cur = self._db.execute(
                "INSERT INTO probe_runs(target, ts, ok, reached, error, signature) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (result.target, result.ts, int(result.ok), int(result.reached), result.error, signature),
            )
            run_id = cur.lastrowid
            self._db.executemany(
                "INSERT INTO probe_hops(run_id, ttl, host, loss, sent, last, avg, best, worst, stdev) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (run_id, h.ttl, h.host, h.loss, h.sent, h.last, h.avg, h.best, h.worst, h.stdev)
                    for h in result.hops
                ],
            )
            self._db.execute(
                "INSERT OR IGNORE INTO target_stats(target, path_changes) VALUES (?, 0)",
                (result.target,),
            )
            if result.ok and result.reached:
                baseline = self._db.execute(
                    "SELECT baseline FROM target_stats WHERE target=?", (result.target,)
                ).fetchone()["baseline"]
                if not baseline:
                    new_baseline = signature
                elif same_path(baseline, signature):
                    # Same route: keep whichever view of it names more hops, so a hop that
                    # was silent in one run does not shrink the reference.
                    new_baseline = max(baseline, signature, key=lambda s: s.count(">"))
                else:
                    changed = True
                    new_baseline = signature
                    self._db.execute(
                        "INSERT INTO path_changes(target, ts, old_signature, new_signature) "
                        "VALUES (?, ?, ?, ?)",
                        (result.target, result.ts, baseline, signature),
                    )
                self._db.execute(
                    "UPDATE target_stats SET baseline=?, path_changes = path_changes + ? WHERE target=?",
                    (new_baseline, int(changed), result.target),
                )
        return changed

    def latest_runs(self) -> list[RunRecord]:
        rows = self._db.execute(
            "SELECT r.* FROM probe_runs r "
            "JOIN (SELECT MAX(id) AS mid FROM probe_runs GROUP BY target) m ON r.id = m.mid "
            "ORDER BY r.target"
        ).fetchall()
        runs = []
        for row in rows:
            hop_rows = self._db.execute(
                "SELECT * FROM probe_hops WHERE run_id=? ORDER BY ttl", (row["id"],)
            ).fetchall()
            hops = tuple(
                Hop(
                    ttl=h["ttl"], host=h["host"], loss=h["loss"] or 0.0, sent=h["sent"] or 0,
                    last=h["last"] or 0.0, avg=h["avg"] or 0.0, best=h["best"] or 0.0,
                    worst=h["worst"] or 0.0, stdev=h["stdev"] or 0.0,
                )
                for h in hop_rows
            )
            runs.append(
                RunRecord(
                    id=row["id"], target=row["target"], ts=row["ts"], ok=bool(row["ok"]),
                    reached=bool(row["reached"]), error=row["error"], hops=hops,
                )
            )
        return runs

    def recent_changes(self, limit: int = 50) -> list[PathChange]:
        rows = self._db.execute(
            "SELECT target, ts, old_signature, new_signature FROM path_changes "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [PathChange(r["target"], r["ts"], r["old_signature"], r["new_signature"]) for r in rows]

    def change_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT target, path_changes FROM target_stats").fetchall()
        return {r["target"]: r["path_changes"] for r in rows}

    def prune(self, retention_days: float, now: float | None = None) -> int:
        """Delete history older than the retention window, keeping each target's latest run."""
        cutoff = (now if now is not None else time.time()) - retention_days * 86_400
        with self._db:
            cur = self._db.execute(
                "DELETE FROM probe_runs WHERE ts < ? "
                "AND id NOT IN (SELECT MAX(id) FROM probe_runs GROUP BY target)",
                (cutoff,),
            )
            self._db.execute("DELETE FROM path_changes WHERE ts < ?", (cutoff,))
        return cur.rowcount
