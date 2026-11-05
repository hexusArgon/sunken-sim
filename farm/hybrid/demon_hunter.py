# -*- coding: utf-8 -*-
"""demon_hunter (havoc, vengeance, devourer): GPU kind/weight compile over sunken_sim.demon_hunter ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class DemonHunterFights(KindFights):
    MODULE = "demon_hunter"
