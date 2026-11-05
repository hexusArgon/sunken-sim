# -*- coding: utf-8 -*-
"""witch_doctor (voodoo, poison): GPU kind/weight compile over sunken_sim.witch_doctor ledger events.

Shared kernel and pack: farm/hybrid/kindscore.py; event kinds: sunken_sim/ledger.py.
"""

from __future__ import annotations

from farm.hybrid.kindscore import KindFights


class WitchDoctorFights(KindFights):
    MODULE = "witch_doctor"
