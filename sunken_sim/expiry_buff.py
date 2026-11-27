"""Debuff as a distribution of expiry times (expected-value debuffs of the Ledger fight models).

Moved from sunken_sim/death_knight.py when its Python fight model was removed (2026-11-27);
used by sunken_sim.demon_hunter (Fallout) and sunken_sim.dragon_sentinel (Dragonfire, Dragon Claw).
The OpenCL kernels mirror it entry by entry (bmass / bsure / bmaybe).
"""

from __future__ import annotations

BUFF_SLOTS = 8  # expiry points kept per debuff and target


class _Buff:
    """A debuff on one target as a distribution of expiry times: (expiry, probability).

    Active at ``now`` when ``now <= expiry``. A sure application collapses it to one point;
    a chance application moves a share of the probability to ``now + duration``.
    """

    __slots__ = ("e", "m")

    def __init__(self) -> None:
        self.e: list[float] = []
        self.m: list[float] = []

    def mass(self, now: float) -> float:
        total = 0.0
        for expiry, share in zip(self.e, self.m):
            if now <= expiry:
                total += share
        return total

    def sure(self, now: float, duration: float) -> None:
        self.e = [now + duration]
        self.m = [1.0]

    def maybe(self, now: float, duration: float, p_on: float, p_off: float) -> None:
        """Apply with chance ``p_on`` where the debuff is on, ``p_off`` where it is off."""
        active = self.mass(now)
        new_e: list[float] = []
        new_m: list[float] = []
        for expiry, share in zip(self.e, self.m):
            if now <= expiry:
                new_e.append(expiry)
                new_m.append(share * (1.0 - p_on))
        added = p_on * active + p_off * (1.0 - active)
        until = now + duration
        if new_e and new_e[-1] == until:
            new_m[-1] = new_m[-1] + added
        else:
            new_e.append(until)
            new_m.append(added)
        while len(new_e) > BUFF_SLOTS:
            # Fold the lightest point into the next (later) one: a small, deterministic overestimate.
            k = 0
            for j in range(1, len(new_e) - 1):
                if new_m[j] < new_m[k]:
                    k = j
            new_m[k + 1] = new_m[k + 1] + new_m[k]
            del new_e[k]
            del new_m[k]
        self.e = new_e
        self.m = new_m
