"""Battle Frenzy (glyph I0GZ) and Silent Messenger (I0QN-style crit_as items) during a fight.

Map 2.5.2c (war3map.j):
* Battle Frenzy: on a hero attack (IsDamageAttack), if the hero has no B03W buff,
  18% x Luck_Multiplier chance to cast A0KD -> B03W for 5 s.  Not refreshed while on.
* Silent Messenger: on critical-strike damage, A08O -> B01M for 3 s, refreshed by every crit.
* Attack_Speed_Tooltip adds +0.32 (B03W) and +0.28 (B01M) to AttackSpeed_Buffs and writes
  the clamped sum into A0QG ATTACK_SPEED_INCREASE, so both are real attack speed.

The sim is deterministic, so each buff is a probability over time:
* Battle Frenzy keeps a list of (expiry, mass).  An attack at `now` while the buff is on
  with probability a adds mass p * (1 - a) that expires at now + 5.
* Silent Messenger keeps a list of (expiry, crit chance) for the attacks in the last
  window; the buff is on with probability 1 - prod(1 - c).
Both lists drop expired entries before an attack and hold at most SLOTS entries:
Battle Frenzy folds its lightest entry into the next one (the previous one for the last),
Silent Messenger drops its oldest entry.  The OpenCL kernels mirror this exactly.
"""

from __future__ import annotations

SLOTS = 8
FRENZY_AS = 0.32
FRENZY_DURATION = 5.0
FRENZY_GLYPH = "I0GZ"


def frenzy_chance(luck: float) -> float:
    return min(1.0, 0.18 * (1.0 + luck))


class AttackProcs:
    __slots__ = ("p", "crit_as", "crit_dur", "fe", "fm", "se", "sc")

    def __init__(self, frenzy_p: float, crit_as: float, crit_dur: float) -> None:
        self.p = frenzy_p
        self.crit_as = crit_as if crit_dur > 0 else 0.0
        self.crit_dur = crit_dur
        self.fe: list[float] = []
        self.fm: list[float] = []
        self.se: list[float] = []
        self.sc: list[float] = []

    @property
    def active(self) -> bool:
        return self.p > 0 or self.crit_as > 0

    def frenzy_on(self, now: float) -> float:
        s = 0.0
        for e, m in zip(self.fe, self.fm):
            if now < e:
                s += m
        return s

    def messenger_on(self, now: float) -> float:
        off = 1.0
        for e, c in zip(self.se, self.sc):
            if now < e:
                off *= 1.0 - c
        return 1.0 - off

    def bonus(self, now: float) -> float:
        b = 0.0
        if self.p > 0:
            b += FRENZY_AS * self.frenzy_on(now)
        if self.crit_as > 0:
            b += self.crit_as * self.messenger_on(now)
        return b

    def on_attack(self, now: float, crit: float) -> None:
        """A hero attack at `now`; `crit` is its crit chance in percent."""
        if self.p > 0:
            keep = [i for i, e in enumerate(self.fe) if e > now]
            if len(keep) != len(self.fe):
                self.fe = [self.fe[i] for i in keep]
                self.fm = [self.fm[i] for i in keep]
            add = self.p * (1.0 - self.frenzy_on(now))
            if add > 0:
                self.fe.append(now + FRENZY_DURATION)
                self.fm.append(add)
                if len(self.fe) > SLOTS:
                    j = 0
                    for i in range(1, len(self.fm)):
                        if self.fm[i] < self.fm[j]:
                            j = i
                    k = j + 1 if j + 1 < len(self.fm) else j - 1
                    self.fm[k] += self.fm[j]
                    del self.fe[j]
                    del self.fm[j]
        if self.crit_as > 0:
            keep = [i for i, e in enumerate(self.se) if e > now]
            if len(keep) != len(self.se):
                self.se = [self.se[i] for i in keep]
                self.sc = [self.sc[i] for i in keep]
            c = min(max(crit, 0.0), 100.0) / 100.0
            if c > 0:
                self.se.append(now + self.crit_dur)
                self.sc.append(c)
                if len(self.se) > SLOTS:
                    del self.se[0]
                    del self.sc[0]


def item_crit_as(build) -> tuple[float, float]:
    """Crit -> attack speed from items (each distinct item once), like shadow.character()."""
    total = 0.0
    duration = 0.0
    seen: set[str] = set()
    for item in build.items:
        if item.rawcode in seen:
            continue
        seen.add(item.rawcode)
        total += item.crit_as
        if item.crit_as:
            duration = max(duration, item.crit_as_duration)
    return total, duration


def from_stats(build, stats: dict, luck: float) -> AttackProcs:
    has = FRENZY_GLYPH in build.glyphs or FRENZY_GLYPH in build.talents
    p = frenzy_chance(luck) if has else 0.0
    if "crit_as" in stats:
        crit_as, duration = float(stats["crit_as"]), float(stats.get("crit_as_duration", 0.0))
    else:
        crit_as, duration = item_crit_as(build)
    return AttackProcs(p, crit_as, duration)
