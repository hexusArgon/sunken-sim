"""Paths for a farm process. Each computer keeps its own farm-data."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    raw = os.environ.get("FARM_DATA", "").strip()
    folder = Path(raw) if raw else ROOT / "farm-data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def atomic_write(path: Path, text: str) -> None:
    """Write via a private temp file. Retry the replace when Windows still holds the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    delay = 0.02
    try:
        for _attempt in range(40):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(delay)
                delay = min(delay * 1.4, 0.25)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def try_file_lock(path: Path):
    """Own path until this process exits. None if another process already owns it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        _lock(handle, block=False)
    except OSError:
        handle.close()
        return None
    return handle


@contextmanager
def file_lock(path: Path, timeout: float = 30):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        _lock(handle, block=True, timeout=timeout)
        yield
    finally:
        _unlock(handle)
        handle.close()


def _lock(handle, block: bool, timeout: float = 30) -> None:
    if handle.seek(0, os.SEEK_END) < 1:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + timeout
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if not block or time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if block else fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
