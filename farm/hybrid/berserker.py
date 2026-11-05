# -*- coding: utf-8 -*-
"""berserker (headhunter, poison, fury): GPU kind/weight compile over sunken_sim.berserker ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class BerserkerFights(KindFights):
    MODULE = "berserker"
