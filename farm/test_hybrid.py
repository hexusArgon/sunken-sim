"""Hybrid path tests. Run: python -m unittest farm.test_hybrid"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from farm import runner as cpu_runner
from farm.hybrid import HYBRID_WORKER, cpu_locked, detect
from farm.hybrid import runner as hybrid_runner
from farm.hybrid.kernel import decode_rows, item_table, parity, stat_fields, totals_cpu, totals_device
from farm.hybrid.lock import GpuLocked, assert_gpu_allowed
from sunken_sim.library import Item

ROOT = Path(__file__).resolve().parents[1]
HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    # Import once up front: patch.dict(sys.modules) below would otherwise drop
    # torch on exit, and re-importing its C extension crashes the process.
    import torch  # noqa: F401


class FakeSpace:
    slots = 3

    def __init__(self, builds):
        self.builds = builds
        self.total = len(builds)

    def decode(self, index):
        return self.builds[index], (), ()


def _items():
    return {
        "A": Item("A", "a", "", intel=10, crit=0.05, haste=0.1),
        "B": Item("B", "b", "", intel=3, potency=7, damage_pct=0.25),
        "C": Item("C", "c", "", mastery=4, cdr_pct=0.15, spell_crit=True),
    }


def _job(hero, spec, worker=HYBRID_WORKER):
    return {"id": "t", "worker": worker, "hero": hero, "spec": spec, "pool": "mixed", "start": 0, "end": 0, "targets": 1}


class LockTest(unittest.TestCase):
    def test_arcane_locked(self):
        self.assertTrue(cpu_locked("mage", "arcane"))
        self.assertTrue(cpu_locked(" Mage ", "ARCANE"))
        self.assertFalse(cpu_locked("mage", "fire"))
        self.assertFalse(cpu_locked("priest", "shadow"))
        with self.assertRaises(GpuLocked):
            assert_gpu_allowed("mage", "arcane")
        assert_gpu_allowed("mage", "fire")

    def test_arcane_detect_is_cpu_even_when_dml_forced(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "dml"}):
            info = detect("mage", "arcane")
        self.assertEqual(info.kind, "cpu")
        self.assertFalse(info.gpu)

    def test_dispatch(self):
        self.assertIs(hybrid_runner.dispatch(_job("mage", "arcane")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "arcane", "local-esc")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "fire", "local-esc")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "fire")), hybrid_runner.run_job)

    def test_arcane_run_job_never_detects_device(self):
        with mock.patch.object(cpu_runner, "run_job", return_value={"ok": 1}) as old, \
             mock.patch.object(hybrid_runner, "detect", side_effect=AssertionError("GPU path touched")), \
             mock.patch.object(hybrid_runner, "prep_check", side_effect=AssertionError("GPU path touched")):
            ticks = []
            out = hybrid_runner.run_job(_job("mage", "arcane"), {}, ticks.append)
        self.assertEqual(out, {"ok": 1})
        old.assert_called_once()
        self.assertEqual(ticks, [])

    def test_arcane_scripts_stay_on_local_esc(self):
        for name in ("run_mage_arcane_top80_esc.py", "resume_mage_arcane_top80_esc.py"):
            path = ROOT / "tools" / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("hybrid", text, name)


class FallbackTest(unittest.TestCase):
    def test_cpu_env(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}):
            self.assertEqual(detect("mage", "fire").kind, "cpu")

    def test_no_directml_falls_back(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "auto"}), \
             mock.patch.dict(sys.modules, {"torch_directml": None}):
            info = detect("mage", "fire")
        self.assertEqual(info.kind, "cpu")
        self.assertIn("not available", info.reason)

    def test_forced_dml_without_directml_raises(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "dml"}), \
             mock.patch.dict(sys.modules, {"torch_directml": None}):
            with self.assertRaises(RuntimeError):
                detect("mage", "fire")

    def test_hybrid_runs_cpu_fights(self):
        """Non-locked hybrid still hands fights to the old CPU run_job."""
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())):
            ticks = []
            out = hybrid_runner.run_job(_job("mage", "fire"), {}, ticks.append)
        self.assertEqual(out, {"done": 1})
        old.assert_called_once()
        self.assertEqual(ticks[0]["hybrid"]["device"], "cpu")
        self.assertTrue(ticks[0]["hybrid"]["prep"]["parity"])


class KernelParityTest(unittest.TestCase):
    def setUp(self):
        self.items = _items()
        self.fields = stat_fields(Item)
        self.space = FakeSpace([("A", "B", "C"), ("A", "A", "A"), ("B",), ("C", "B")])
        self.index, self.table = item_table(self.items, self.fields)
        self.rows = decode_rows(self.space, self.index, 0, self.space.total)

    def test_fields_skip_bools(self):
        self.assertIn("intel", self.fields)
        self.assertIn("crit", self.fields)
        self.assertNotIn("spell_crit", self.fields)
        self.assertNotIn("rawcode", self.fields)

    def test_cpu_reference(self):
        out = totals_cpu(self.table, self.rows)
        col = self.fields.index("intel")
        self.assertEqual([row[col] for row in out], [13.0, 30.0, 3.0, 3.0])
        col = self.fields.index("haste")
        self.assertAlmostEqual(out[1][col], 0.3)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_torch_cpu_parity(self):
        from farm.hybrid.device import DeviceInfo

        ok, worst = parity(totals_cpu(self.table, self.rows), totals_device(self.table, self.rows, DeviceInfo("cpu", "cpu")))
        self.assertTrue(ok, worst)

    def test_dml_parity_if_present(self):
        info = detect("mage", "fire")
        if not info.gpu:
            self.skipTest(f"no DirectML: {info.reason}")
        ok, worst = parity(totals_cpu(self.table, self.rows), totals_device(self.table, self.rows, info))
        self.assertTrue(ok, worst)

    def test_parity_detects_mismatch(self):
        ref = totals_cpu(self.table, self.rows)
        bad = [list(row) for row in ref]
        bad[0][0] += 1.0
        self.assertFalse(parity(ref, bad)[0])


if __name__ == "__main__":
    unittest.main()