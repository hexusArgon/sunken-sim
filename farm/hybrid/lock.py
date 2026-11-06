"""Hero/spec pairs that must always use the old CPU sim. Never the GPU path."""

from __future__ import annotations

import os

# Arcane Mage: long running farm on the old CPU sim. Locked by default.
# The GPU timeline matches the CPU sim exactly for Arcane (Evocation, mana ticks,
# reset chance, Blast stacks; tools/_parity_mage_arcane.py, events max diff ~1e-13),
# so the GPU path is the default now; FARM_HYBRID_ARCANE_GPU=0 locks it back to CPU.
CPU_LOCKED: frozenset[tuple[str, str]] = frozenset({("mage", "arcane")})
UNLOCK_ENV = {("mage", "arcane"): "FARM_HYBRID_ARCANE_GPU"}


def _unlocked(key: tuple[str, str]) -> bool:
    name = UNLOCK_ENV.get(key)
    if not name:
        return False
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "off", "no")


def cpu_locked(hero: str, spec: str) -> bool:
    key = (str(hero).strip().lower(), str(spec).strip().lower())
    return key in CPU_LOCKED and not _unlocked(key)


class GpuLocked(RuntimeError):
    pass


def assert_gpu_allowed(hero: str, spec: str) -> None:
    if cpu_locked(hero, spec):
        raise GpuLocked(f"{hero}/{spec} is locked to the CPU sim")