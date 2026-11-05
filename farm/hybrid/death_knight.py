# -*- coding: utf-8 -*-
"""death_knight (frost, blood, unholy): GPU kind/weight compile over sunken_sim.death_knight ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class DeathKnightFights(KindFights):
    MODULE = "death_knight"
