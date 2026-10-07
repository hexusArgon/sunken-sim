"""Five-letter name of this computer. Stable across restarts."""

from __future__ import annotations

import os
import random
import re
from pathlib import Path

from farm.paths import ROOT, data_dir

_WORD = re.compile(r"[a-z]{5}")
_CONS = "bcdfghjklmnpqrstvwxyz"
_VOWELS = "aeiou"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _generate() -> str:
    rng = random.SystemRandom()
    letters = []
    for index in range(5):
        letters.append(rng.choice(_CONS if index % 2 == 0 else _VOWELS))
    return "".join(letters)


def worker_name() -> str:
    path = data_dir() / "name.txt"
    forced = os.environ.get("WORKER_NAME", "").strip().lower()
    if forced:
        if not _WORD.fullmatch(forced):
            raise SystemExit("WORKER_NAME — пять латинских букв, например kivor")
        path.write_text(forced, encoding="utf-8")
        return forced
    if path.exists():
        saved = path.read_text(encoding="utf-8").strip().lower()
        if _WORD.fullmatch(saved):
            return saved
    name = _generate()
    path.write_text(name, encoding="utf-8")
    return name


def env_required(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise SystemExit(f"Нет {key}. Скопируй .env.example в .env и заполни.")
    return value
