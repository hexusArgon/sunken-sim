"""Fail if any device-algebra op falls back to CPU on DirectML (fresh process)."""
import sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, torch, torch_directml
from farm.hybrid import esc_device as ed
from farm.hybrid.test_esc_device import _trace
dev = torch_directml.device()
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    for hero, spec in (("berserker", "headhunter"), ("necromancer", "essence"), ("witch_doctor", "poison")):
        mod, b, tr = _trace(hero, spec)
        dp = ed.CACHE.get(tr, torch, dev, torch.float32)
        base = mod.stats_of(b)
        print(hero, spec, "groups", len(dp.groups), "events", dp.E, dp.score(np.asarray([[base[k] for k in dp.leaf_keys]] * 4))[:1])
bad = [str(x.message) for x in w if "DML" in str(x.message) or "fall back" in str(x.message)]
print("fallbacks:", bad or "none")
sys.exit(1 if bad else 0)
