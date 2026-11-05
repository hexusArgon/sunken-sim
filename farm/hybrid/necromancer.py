# -*- coding: utf-8 -*-
"""necromancer (bone, blood, essence): GPU kind/weight compile over sunken_sim.necromancer ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class NecromancerFights(KindFights):
    MODULE = "necromancer"
