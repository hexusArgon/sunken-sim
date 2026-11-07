"""Versioned, identity-aware item admission. No damage-only pruning by default.

The optional unsafe gate is a search heuristic, never an admissible upper bound.
Anonymous legacy float snapshots cannot identify observations and are ignored.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = 2
ALL = 'all'
UNSAFE = 'unsafe-bare-top10'
KEYS = ('overall', 'shop', 'drop')
LIMIT = 10


def policy(job=None):
    value = (job or {}).get('admission_policy')
    if value is None:
        value = UNSAFE if os.environ.get('FARM_UNSAFE_BARE_GATE', '') == '1' else ALL
    if value not in (ALL, UNSAFE):
        raise ValueError(f'Unknown admission_policy: {value!r}')
    return value


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
    mode = job.get('admission_policy', ALL)
    text = ('Все шестёрки проходят к подбору талантов/глифов/ESC; отсечения по item-only DPS нет. '
            if mode == ALL else
            'UNSAFE HEURISTIC: item-only top-10 gate включён явно; синергичные билды могут быть потеряны. ')
    return text + ('Полный обход предметов не доказывает глобальный максимум: подбор талантов, затем глифов, затем greedy ESC остаётся поэтапной эвристикой. '
                   'top — общий top-10; top_shop_random — смешанные источники; top_shop — лавка; top_random — дроп. Легендарки входят в любой список.')
