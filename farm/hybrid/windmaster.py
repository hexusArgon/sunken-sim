# -*- coding: utf-8 -*-
"""windmaster (upheaval, storm, combat): GPU kind/weight compile over sunken_sim.windmaster ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class WindmasterFights(KindFights):
    MODULE = "windmaster"
