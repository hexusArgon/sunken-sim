"""Opt-in hybrid GPU+CPU farm path (DirectML on AMD/Windows).

v1 scope: device detection, Arcane CPU lock, a batched item-stat prep kernel
with a CPU parity check. Fights still run on the old CPU sim (farm.runner).
"""

from farm.hybrid.device import DeviceInfo, detect
from farm.hybrid.lock import CPU_LOCKED, assert_gpu_allowed, cpu_locked

HYBRID_WORKER = "local-hybrid"

__all__ = ["CPU_LOCKED", "DeviceInfo", "HYBRID_WORKER", "assert_gpu_allowed", "cpu_locked", "detect"]