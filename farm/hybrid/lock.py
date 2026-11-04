"""Hero/spec pairs that must always use the old CPU sim. Never the GPU path."""

from __future__ import annotations

# Arcane Mage: long running farm on the old CPU sim. Hard lock.
CPU_LOCKED: frozenset[tuple[str, str]] = frozenset({("mage", "arcane")})


def cpu_locked(hero: str, spec: str) -> bool:
    return (str(hero).strip().lower(), str(spec).strip().lower()) in CPU_LOCKED


class GpuLocked(RuntimeError):
    pass


def assert_gpu_allowed(hero: str, spec: str) -> None:
    if cpu_locked(hero, spec):
        raise GpuLocked(f"{hero}/{spec} is locked to the CPU sim")