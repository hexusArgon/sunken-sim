# -*- coding: utf-8 -*-
"""monk (windwalker, brewmaster, mistweaver): GPU kind/weight compile over sunken_sim.monk ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class MonkFights(KindFights):
    MODULE = "monk"
