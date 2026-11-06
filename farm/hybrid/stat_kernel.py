# -*- coding: utf-8 -*-
"""ESC / stat-kernel helpers for hybrid DirectML greedy.

Warrior Whirlwind cleave and Sulfuras echo are unbaked (2026-11-06): crit,
potency and luck are applied in score_events / kind-score, so CPU
`_timeline_key` and WarriorFights reuse the event tape when only those points
change. Paladin Sulfuras echo is unbaked the same way; crit and potency
reuse the tape, and luck reuses it when Divine Toll / bell is absent (Toll
still bakes luck into extra hammer weight). Druid Sulfuras echo is unbaked
the same way; crit and potency reuse the tape, luck stays because proc()
changes wisp spread and extra hits. Shaman Sulfuras echo is unbaked the
same way; deal events store a totem crit bonus and score applies hero
crit and potency (Sulfuras splash still has no potency). Luck stays
because proc() changes Thunderstorm and lesser-chain weights. Other
heroes still bake some
flat/cleave/splash raws at emit time; a closed-form kernel for them needs
the same per-class unbake. Until then, greedy stays on full dps_many batches
with structural attr skips only.

Result must equal sunken_sim.esc.greedy_points (every under-cap attr tried each
step, strict '>', earliest attr wins ties, points spent even with no gain).

Structural skips (not fought, scored as the current DPS):
  - healing_power: no DPS class sim reads stats["healing_power"]
  - pet_damage: only heroes that scale pets/summons (see PET_DAMAGE_HEROES)
A skipped attr still takes part in the pick with score == current best, so tie
breaks and "spend anyway" picks are the same as the full greedy. Each skip is
guarded by a source scan (_attr_read_in_sources): if the hero's sim / GPU files
read stats["<attr>"] (or .get("<attr>") / V("<attr>")), the attr is fought.

Removed (2026-11-05): the zero-delta skip (drop attrs that tied the baseline
after an improving step). It is not exact: demon_hunter/havoc catalog sample
gave 590.5479 vs 596.8404 full greedy (-1.05%), because mastery tied early and
won later. Regression: farm/hybrid/test_stat_kernel_greedy.py.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
from sunken_sim.shadow import SKILL_POINTS

# Heroes whose sim multiplies pet/summon damage by stats["pet_damage"].
PET_DAMAGE_HEROES = frozenset({
    "hunter",
    "necromancer",
    "siren",
    "tidewarrior",
    "tinker",
    "warlock",
    "witch_doctor",
})

_MODULE_ALIAS = {"priest": "shadow"}  # mirrors registry.MODULES
_ROOT = Path(__file__).resolve().parents[2]
_SHARED = (
    "sunken_sim/shadow.py",
    "sunken_sim/ledger.py",
    "farm/hybrid/kindscore.py",
    "farm/hybrid/engine.py",
    "farm/hybrid/timeline_gpu.py",
    "farm/hybrid/fight.py",
)


def _hero_files(hero: str) -> list[Path] | None:
    try:
        from farm.hybrid.registry import MODULES

        module = MODULES.get(hero, _MODULE_ALIAS.get(hero, hero))
    except Exception:  # registry needs farm/hybrid/lock.py; keep the scan usable without it
        module = _MODULE_ALIAS.get(hero, hero)
    main = _ROOT / "sunken_sim" / f"{module}.py"
    if not main.is_file():
        return None
    files = {main}
    for name in {hero, module}:
        files.update((_ROOT / "farm" / "hybrid").glob(f"{name}*.py"))
    files.update(_ROOT / rel for rel in _SHARED if (_ROOT / rel).is_file())
    return sorted(files)


@lru_cache(maxsize=None)
def _attr_read_in_sources(hero: str | None, attr: str) -> bool:
    """True (= fight the attr) if any sim/GPU file for hero reads stats[attr].

    Fails closed: unknown hero / missing module file / unreadable file -> True.
    """
    if hero is None:
        return True
    files = _hero_files(hero)
    if files is None:
        return True
    pattern = re.compile(r"(?:\[|\.get\(|\bV\()\s*[\"']" + re.escape(attr) + r"[\"']")
    for path in files:
        if path.name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return True
        if pattern.search(text):
            return True
    return False


def structural_skip_attrs(hero: str | None) -> frozenset[str]:
    """Attrs that cannot change DPS for this hero (not fought; scored as current)."""
    want = {"healing_power"}
    if hero is None or hero not in PET_DAMAGE_HEROES:
        want.add("pet_damage")
    return frozenset(attr for attr in want if not _attr_read_in_sources(hero, attr))


def greedy_points_batched(
    dps_many,
    build,
    *,
    total: int | None = None,
    cap: int = ESC_CAP,
    hero: str | None = None,
):
    """sunken_sim.esc.greedy_points, batched per step, structural attrs not fought."""
    if total is None:
        total = SKILL_POINTS
    counts = empty_points()
    best = float(dps_many([apply_points(build, counts)])[0])
    skip = structural_skip_attrs(hero)
    for _ in range(total):
        names = [name for name in ESC_ATTRS if counts[name] < cap]
        if not names:
            break
        fight = [name for name in names if name not in skip]
        trials = [apply_points(build, {**counts, name: counts[name] + 1}) for name in fight]
        scores = dict(zip(fight, (float(x) for x in dps_many(trials)))) if trials else {}
        pick, pick_dps = None, -1.0
        for name in names:
            dps = best if name in skip else scores[name]
            if dps > pick_dps:
                pick, pick_dps = name, dps
        counts[pick] += 1
        best = pick_dps
    return best, counts


def greedy_points_many(dps_many, builds, *, total: int | None = None, cap: int = ESC_CAP, hero: str | None = None):
    """greedy_points_batched for several independent builds in lockstep.

    Step k of every still-active build goes into ONE dps_many call (row order,
    attr order), then each build picks with its own counts/best and the same strict
    '>' tie rule; a build whose attrs are all capped drops out (its loop would
    break). No state is shared between builds: each slice of the result belongs
    to exactly one build. Returns [(best, counts)] in input order.
    """
    if total is None:
        total = SKILL_POINTS
    n = len(builds)
    counts = [empty_points() for _ in range(n)]
    if not n:
        return []
    best = [float(x) for x in dps_many([apply_points(b, c) for b, c in zip(builds, counts)])]
    skip = structural_skip_attrs(hero)
    active = list(range(n))
    for _ in range(total):
        plan, flat = [], []
        for r in active:
            names = [name for name in ESC_ATTRS if counts[r][name] < cap]
            if not names:
                continue
            fight = [name for name in names if name not in skip]
            plan.append((r, names, fight, len(flat)))
            flat.extend(apply_points(builds[r], {**counts[r], name: counts[r][name] + 1}) for name in fight)
        if not plan:
            break
        res = [float(x) for x in dps_many(flat)] if flat else []
        active = []
        for r, names, fight, off in plan:
            scores = dict(zip(fight, res[off : off + len(fight)]))
            pick, pick_dps = None, -1.0
            for name in names:
                dps = best[r] if name in skip else scores[name]
                if dps > pick_dps:
                    pick, pick_dps = name, dps
            counts[r][pick] += 1
            best[r] = pick_dps
            active.append(r)
    return list(zip(best, counts))
