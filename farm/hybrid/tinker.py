# -*- coding: utf-8 -*-
"""tinker (engineering, demolitions, nanotech): GPU kind/weight compile over sunken_sim.tinker ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class TinkerFights(KindFights):
    MODULE = "tinker"
