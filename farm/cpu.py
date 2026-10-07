"""System CPU use between calls. The first call only starts the clock."""

from __future__ import annotations

import sys

_prev: tuple[int, int] | None = None


def cpu_percent() -> float | None:
    global _prev
    if sys.platform == "win32":
        sample = _windows()
    else:
        sample = _linux()
    if sample is None:
        return None
    if _prev is None:
        _prev = sample
        return None
    idle, total = sample
    idle_d = idle - _prev[0]
    total_d = total - _prev[1]
    _prev = sample
    if total_d <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total_d - idle_d) / total_d))


def _windows() -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    idle, kernel, user = FileTime(), FileTime(), FileTime()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    )
    if not ok:
        return None

    def ticks(value: FileTime) -> int:
        return (value.high << 32) + value.low

    # Kernel time already includes idle time.
    idle_ticks = ticks(idle)
    total = ticks(kernel) + ticks(user)
    return idle_ticks, total


def _linux() -> tuple[int, int] | None:
    try:
        line = open("/proc/stat", encoding="utf-8").readline()
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu" or len(parts) < 5:
        return None
    numbers = [int(part) for part in parts[1:]]
    idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
    return idle, sum(numbers)
