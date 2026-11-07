"""Counterexample: bare Fire score is not a bound on unresolved TL/glyph/ESC."""
import unittest
from farm import admission
from farm.catalog import _parts
from sunken_sim import mage
from sunken_sim.shadow import Build
from sunken_sim.esc import empty_points,apply_points


class FireBoundTests(unittest.TestCase):
    def test_bare_is_not_upper_bound_documented_gate_limitation(self):
        items=_parts('mage','fire','mixed',None,100)[5]
        gear=tuple(items[c] for c in ('I04G','I06U','I0BR','I0D8','fgrd','sor8'))
        bare=Build(frozenset(),frozenset(),gear,0,0)
        points=empty_points();points.update(potency=20,luck=10)
        full=apply_points(Build(frozenset({'I0KU','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),gear,0,0),points)
        low=mage.simulate(bare,5,spec='fire',use_history=False).dps
        high=mage.simulate(full,5,spec='fire',use_history=False).dps
        self.assertGreater(high,low)
        # A putative U=bare violates the defining score(candidate)<=U inequality.
        self.assertEqual(admission.policy(),admission.BARE)
        self.assertIn('No global optimum guarantee',admission.description({}))
