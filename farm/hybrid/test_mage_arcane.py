"""Arcane Mage on the GPU timeline: opt-in unlock + exact parity with the CPU sim."""
from __future__ import annotations

import os
import random
import unittest
from unittest import mock


def _builds(n, seed):
    from farm.hybrid.test_cross_build import _calls
    from sunken_sim.shadow import Build

    rng = random.Random(seed)
    out = []
    for eq, tal, gly, p0, p1, gp in _calls("mage", "arcane", n, seed=seed):
        picks = p1 if rng.random() < 0.5 else p0
        talents = frozenset(rng.sample(list(tal), min(picks, len(tal))))
        glyphs = frozenset(rng.sample(list(gly), min(gp, len(gly))))
        pts = [0] * 5
        for _ in range(rng.choice([0, 20, 60])):
            pts[rng.randrange(5)] += 1
        out.append(Build(talents, glyphs, eq, *pts))
    return out


def _canon(events):
    return sorted(events, key=lambda e: (round(float(e[0]), 9), str(e[1]), float(e[2]), float(e[3])))


class ArcaneLockTest(unittest.TestCase):
    def test_gpu_by_default(self):
        from farm.hybrid.fight import gpu_fights_for
        from farm.hybrid.lock import cpu_locked
        from farm.hybrid.registry import status, GPU_TIMELINE, LOCKED

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FARM_HYBRID_ARCANE_GPU", None)
            self.assertFalse(cpu_locked("mage", "arcane"))
            self.assertTrue(gpu_fights_for("mage", "arcane"))
            self.assertEqual(status("mage", "arcane"), GPU_TIMELINE)
        with mock.patch.dict(os.environ, {"FARM_HYBRID_ARCANE_GPU": "0"}):
            self.assertEqual(status("mage", "arcane"), LOCKED)

    def test_opt_in_unlock(self):
        from farm.hybrid.fight import gpu_fights_for
        from farm.hybrid.lock import cpu_locked, assert_gpu_allowed
        from farm.hybrid.registry import status, GPU_TIMELINE

        with mock.patch.dict(os.environ, {"FARM_HYBRID_ARCANE_GPU": "1"}):
            self.assertFalse(cpu_locked("mage", "arcane"))
            assert_gpu_allowed("mage", "arcane")
            self.assertTrue(gpu_fights_for("mage", "arcane"))
            self.assertEqual(status("mage", "arcane"), GPU_TIMELINE)
        with mock.patch.dict(os.environ, {"FARM_HYBRID_ARCANE_GPU": "0"}):
            self.assertTrue(cpu_locked("mage", "arcane"))


class ArcaneParityTest(unittest.TestCase):
    def _check(self, builds, targets, starve=None):
        import torch
        from sunken_sim import mage
        from farm.hybrid import fight as F
        from farm.hybrid.mage_gpu_timeline import _mage_batch

        sheet = mage.sheet

        def starved(build):
            st = sheet(build)
            st["mana_max"] *= starve
            st["mana_regen"] *= starve
            return st

        with mock.patch.object(mage, "sheet", starved if starve else sheet):
            flat, keys = [], []
            for b in builds:
                ks = [k for k in mage._buttons("arcane") if k != "Evocation"] if mage._wears(b, "I00D") else [None]
                for k in ks:
                    flat.append(b)
                    keys.append(k)
            rows = _mage_batch(torch, torch.device("cpu"), torch.float64, flat, "arcane", targets, keys)
            evo = 0
            for b, k, (events, _stats, _spec, evocation) in zip(flat, keys, rows):
                ref = [t for t in F.timelines(b, targets, "arcane", cache=False) if t.bound == k][0]
                self.assertTrue(evocation)
                got, want = _canon(events), _canon(ref.events)
                self.assertEqual(len(got), len(want))
                for a, r in zip(got, want):
                    self.assertEqual(a[1], r[1])
                    for x, y in zip(a[:5], r[:5]):
                        if not isinstance(x, str):
                            self.assertLessEqual(abs(float(x) - float(y)), 1e-9)
                    self.assertLessEqual(abs(a[5]["mana"] - r[5]["mana"]), 1e-9)
                    self.assertLessEqual(abs(a[5]["splinter"] - r[5]["splinter"]), 1e-9)
                if k is None:
                    rep = mage.simulate(b, targets, None, None, "arcane", use_history=False)
                    evo += sum(1 for _t, name in rep.actions if name == "Evocation")
            return evo

    def test_events_match_cpu(self):
        self._check(_builds(4, 7), 1)

    def test_evocation_mana_ticks_match_cpu(self):
        # starved sheets make Evocation / mana ticks fire on both sides
        evo = self._check(_builds(4, 5), 5, starve=0.12)
        self.assertGreater(evo, 0)


if __name__ == "__main__":
    unittest.main()
