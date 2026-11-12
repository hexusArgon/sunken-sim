"""Versioned, identity-aware item admission.

Two policies:
* ``bare-top10`` (default): talents/glyphs/ESC are refined when the item-only DPS enters the current
  top-10 of a category; the boards and the result keep 10 builds per list.
* ``bare-top50`` (default for Priest, Paladin, Shaman, Mage, Druid): the gate remembers the top-50
  item-only sextuples of each category and refines a sextuple that enters them; the run keeps the 50 best
  finished builds per list while it runs and, once the whole span is done, writes only the top-20
  (the other 30 are dropped from the result and the checkpoint).

The production gate is a search heuristic, never an admissible upper bound.
Anonymous legacy float snapshots cannot identify observations and are ignored.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = 2
BARE = 'bare-top10'
BARE50 = 'bare-top50'
LEGACY_ALL = 'all'
UNSAFE = 'unsafe-bare-top10'
KEYS = ('overall', 'shop', 'drop')
LIMITS = {BARE: 10, BARE50: 50}      # item-only gate size and finished builds kept while running
FINAL_KEEP = {BARE: 10, BARE50: 20}  # finished builds per list written when the run is complete
TOP50_HEROES = frozenset({'priest', 'paladin', 'shaman', 'mage', 'druid', 'berserker', 'death_knight'})
LIMIT = LIMITS[BARE]  # active gate size of this process; set by activate()


def activate(name):
    """Make ``name`` the active policy of this process (gate size, board size)."""
    global LIMIT
    LIMIT = LIMITS[policy({'admission_policy': name})]
    return LIMIT


def final_keep(name):
    return FINAL_KEEP[policy({'admission_policy': name})]


def policy(job=None):
    """One production policy; normalize the old unsafe spelling for fresh jobs.

    FARM_UNSAFE_BARE_GATE is obsolete: neither 0 nor 1 selects all-admission.
    Stored checkpoint metadata is never normalized when validating resumes.
    """
    value = (job or {}).get('admission_policy')
    if value is None:
        hero = str((job or {}).get('hero') or '').strip().lower()
        return BARE50 if hero in TOP50_HEROES else BARE
    if value in (BARE, UNSAFE):
        return BARE
    if value == BARE50:
        return BARE50
    if value == LEGACY_ALL:
        raise ValueError("admission_policy='all' has been removed; use 'bare-top10' or 'bare-top50'")
    raise ValueError(f'Unknown admission_policy: {value!r}; use {BARE!r} or {BARE50!r}')


def groups(group):
    return ('overall', group) if group in ('shop', 'drop') else ('overall',)


class Observations:
    """Bounded top observations keyed by chunk within a fingerprinted search space."""
    def __init__(self, raw=None):
        self.rows = {k: {} for k in KEYS}
        for k in KEYS:
            for row in (raw or {}).get(k, []) if isinstance(raw, dict) else []:
                if not isinstance(row, dict) or 'chunk' not in row or 'dps' not in row:
                    continue  # unattributed legacy scores are never active gate state
                chunk, dps = int(row['chunk']), float(row['dps'])
                if chunk < 0 or not math.isfinite(dps):
                    raise ValueError('Invalid item admission observation')
                self.rows[k][chunk] = max(dps, self.rows[k].get(chunk, -math.inf))
            self._trim(k)

    def _trim(self, key):
        self.rows[key] = dict(sorted(self.rows[key].items(), key=lambda r: (-r[1], r[0]))[:LIMIT])

    def claim(self, chunk, dps, group):
        admitted = False
        for k in groups(group):
            held = self.rows[k]
            if chunk in held:
                continue
            if len(held) >= LIMIT and dps <= min(held.values()):
                continue
            held[chunk] = float(dps)
            self._trim(k)
            admitted = True
        return admitted

    def snapshot(self):
        return {k: [{'chunk': c, 'dps': d} for c, d in self.rows[k].items()] for k in KEYS}

    def scores(self):
        return {k: list(self.rows[k].values()) for k in KEYS}


def merge(left, right):
    """Set union by observation identity, deterministic even for equal DPS ties."""
    a, b = Observations(left).snapshot(), Observations(right).snapshot()
    return Observations({k: a[k] + b[k] for k in KEYS}).snapshot()


def configure(job, space, items):
    """Fingerprint catalog AND scoring sources; never reuse incompatible done spans."""
    out = dict(job)
    attrs = ('slots', 'require_leg', 'talents', 'glyphs', 'picks_without', 'picks_with', 'glyph_picks')
    catalog = {'space_type': type(space).__module__ + '.' + type(space).__qualname__,
               'forced': getattr(space, 'forced', None),
               'pieces': [vars(p) for p in space.pieces],
               'options': {k: getattr(space, k) for k in attrs},
               'items': {c: vars(i) for c, i in items.items()}}
    fingerprint = hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    paths = list((root/'sunken_sim').glob('*.py')) + list((root/'farm').glob('*.py')) + list((root/'farm/hybrid').glob('*.py'))
    for p in sorted(paths):
        if p.name.startswith('test_'):
            continue
        h.update(p.relative_to(root).as_posix().encode()); h.update(p.read_bytes())
    out.update(search_schema=SCHEMA, admission_policy=policy(job), catalog_fingerprint=fingerprint,
               scoring_fingerprint=h.hexdigest())
    return out


def metadata(job):
    return {k: job.get(k) for k in ('search_schema', 'admission_policy', 'catalog_fingerprint', 'scoring_fingerprint')}


def suffix(job):
    context = json.dumps({**metadata(job), **{k: job.get(k) for k in ('hero', 'spec', 'pool', 'targets', 'preset', 'top', 'start', 'end')}}, sort_keys=True).encode()
    return f"admission-v{SCHEMA}-{job['admission_policy']}-{hashlib.sha256(context).hexdigest()[:16]}"


def description(job):
    if job.get('admission_policy') == BARE50:
        return ('Bare top-50: talents/glyphs/ESC are refined only when item-only DPS enters the current top-50 of a relevant category. '
                'While running, the 50 best finished builds of each list are kept; when the whole span is done, only the top-20 '
                'of each list is written and the other 30 are dropped. '
                'Heuristic: item-only DPS is not an upper bound on finished DPS; synergistic builds may be lost. No global optimum guarantee. '
                'Talent selection, then glyph selection, then greedy ESC are staged as before. '
                'top=overall; top_shop_random=mixed sources; top_shop=shop; top_random=drop; legendaries belong to any source category.')
    return ('Bare top-10: talents/glyphs/ESC are refined only when item-only DPS enters the current top-10 of a relevant category. '
            'Heuristic: item-only DPS is not an upper bound on finished DPS; synergistic builds may be lost. No global optimum guarantee. '
            'Talent selection, then glyph selection, then greedy ESC are staged as before. '
            'top=overall; top_shop_random=mixed sources; top_shop=shop; top_random=drop; legendaries belong to any source category.')
