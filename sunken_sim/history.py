"""Remember finished fights so the same one is not simulated twice.

The three item pools run separate searches. A shop sextuple is legal inside
Shop + drop and again inside Shop only. The key is the fight, not the pool.
"""

from __future__ import annotations

import atexit
import json
import sqlite3
import time
from pathlib import Path

from sunken_sim.shadow import Build, Report

_PATH = Path(__file__).resolve().parents[1] / "extract" / "sim-history.sqlite"
_CONN: sqlite3.Connection | None = None
_MEMORY: dict[str, dict] = {}
_PENDING = 0


def sim_key(engine: str, spec: str, build: Build, targets: int, bound_spell: str | None) -> str:
    items = ",".join(sorted(item.rawcode for item in build.items))
    talents = ",".join(sorted(build.talents))
    glyphs = ",".join(sorted(build.glyphs))
    points = f"{build.crit_points},{build.potency_points},{build.luck_points},{build.mastery_points}"
    # Bump when a fight mechanic changes, so old rows are not reused.
    return "|".join(("v2", engine, spec, str(targets), talents, glyphs, items, points, bound_spell or ""))


def _connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _PATH.parent.mkdir(exist_ok=True)
        _CONN = sqlite3.connect(_PATH, timeout=120)
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.execute("PRAGMA synchronous=NORMAL")
        _CONN.execute("PRAGMA busy_timeout=120000")
        _CONN.execute(
            "CREATE TABLE IF NOT EXISTS sims (key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
    return _CONN


def release() -> None:
    """Commit and close before a process pool forks.

    A worker must not inherit the parent's open write transaction. That lock
    made every parallel slice fail with "database is locked".
    """
    global _CONN, _PENDING
    if _CONN is None:
        return
    if _PENDING:
        _CONN.commit()
        _PENDING = 0
    _CONN.close()
    _CONN = None


def _dump(value):
    if isinstance(value, tuple):
        return [_dump(part) for part in value]
    if isinstance(value, list):
        return [_dump(part) for part in value]
    if isinstance(value, dict):
        return {str(key): _dump(inner) for key, inner in value.items()}
    return value


def recall(engine: str, spec: str, build: Build, targets: int, bound_spell: str | None) -> Report | None:
    key = sim_key(engine, spec, build, targets, bound_spell)
    payload = _MEMORY.get(key)
    if payload is None:
        row = _connect().execute("SELECT payload FROM sims WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        _MEMORY[key] = payload
    return Report(
        build,
        payload["dps"],
        payload["total"],
        payload["sources"],
        [tuple(step) for step in payload["actions"]],
        payload["stats"],
        payload["targets"],
        payload["orb_mode"],
        payload["bound_spell"],
        payload["mana_left"],
    )


def remember(engine: str, spec: str, report: Report, bound_spell: str | None) -> Report:
    global _PENDING
    key = sim_key(engine, spec, report.build, report.targets, bound_spell)
    payload = {
        "dps": report.dps,
        "total": report.total,
        "sources": _dump(report.sources),
        "actions": _dump(report.actions),
        "stats": _dump(report.stats),
        "targets": report.targets,
        "orb_mode": report.orb_mode,
        "bound_spell": report.bound_spell,
        "mana_left": report.mana_left,
    }
    _MEMORY[key] = payload
    connection = _connect()
    text = json.dumps(payload, ensure_ascii=False)
    for attempt in range(8):
        try:
            connection.execute(
                "INSERT OR IGNORE INTO sims (key, payload) VALUES (?, ?)",
                (key, text),
            )
            break
        except sqlite3.OperationalError:
            connection.rollback()
            if attempt == 7:
                raise
            time.sleep(0.25 * (attempt + 1))
    _PENDING += 1
    if _PENDING >= 100:
        connection.commit()
        _PENDING = 0
    return report


def flush() -> None:
    global _PENDING
    if _CONN is not None and _PENDING:
        _CONN.commit()
        _PENDING = 0


atexit.register(flush)
