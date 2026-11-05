# -*- coding: utf-8 -*-
"""tidewarrior (myrmidon, guardian): GPU kind/weight compile over sunken_sim.tidewarrior ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class TidewarriorFights(KindFights):
    MODULE = "tidewarrior"
