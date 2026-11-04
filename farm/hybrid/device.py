"""Pick DirectML when it is installed and works, else CPU.

FARM_HYBRID_DEVICE: auto (default) | cpu | dml
torch / torch_directml are imported lazily, so the normal farm never needs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from farm.hybrid.lock import cpu_locked


@dataclass(frozen=True)
class DeviceInfo:
    kind: str  # "dml" or "cpu"
    name: str
    reason: str = ""
    handle: object = None  # torch device for dml, None for cpu

    @property
    def gpu(self) -> bool:
        return self.kind == "dml"


def _cpu(reason: str) -> DeviceInfo:
    return DeviceInfo("cpu", "cpu", reason, None)


def detect(hero: str | None = None, spec: str | None = None) -> DeviceInfo:
    if hero is not None and spec is not None and cpu_locked(hero, spec):
        return _cpu(f"{hero}/{spec} locked to CPU")
    want = os.environ.get("FARM_HYBRID_DEVICE", "auto").strip().lower() or "auto"
    if want == "cpu":
        return _cpu("FARM_HYBRID_DEVICE=cpu")
    try:
        import torch  # noqa: F401
        import torch_directml
    except Exception as exc:  # ImportError or broken DLLs
        if want == "dml":
            raise RuntimeError(f"FARM_HYBRID_DEVICE=dml but torch_directml failed: {exc}") from exc
        return _cpu(f"torch_directml not available: {exc.__class__.__name__}")
    try:
        if not torch_directml.is_available() or torch_directml.device_count() < 1:
            raise RuntimeError("no DirectML device")
        handle = torch_directml.device(torch_directml.default_device())
        name = str(torch_directml.device_name(torch_directml.default_device())).replace("\x00", "").strip()
    except Exception as exc:
        if want == "dml":
            raise
        return _cpu(f"DirectML init failed: {exc}")
    return DeviceInfo("dml", name, "", handle)