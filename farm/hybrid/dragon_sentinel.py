# -*- coding: utf-8 -*-
"""dragon_sentinel (ruby, obsidian, emerald): GPU kind/weight compile over sunken_sim.dragon_sentinel ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class DragonSentinelFights(KindFights):
    MODULE = "dragon_sentinel"
