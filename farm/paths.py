"""Paths for a farm process. Each computer keeps its own farm-data."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    raw = os.environ.get("FARM_DATA", "").strip()
    folder = Path(raw) if raw else ROOT / "farm-data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
