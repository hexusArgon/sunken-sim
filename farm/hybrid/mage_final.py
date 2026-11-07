"""Mage score is linear in the compiled weighted sums, not in all stats.

CPU builds exact sheet/raw/armor coefficients; GPU evaluates the final linear
form and ring maxima. This is not a GPU timeline scheduler or an ESC planner.
A source fingerprint fails closed if the manually verified formula changes.
"""
import hashlib
import inspect
from functools import lru_cache
import numpy as np

SCORE_SOURCE = 'c2aa78b5ac00ac0432b3ecaf3472c6407797afb3912ca4636ebc3e69ddb58feb'


@lru_cache(maxsize=8)
def supported(function):
    try:
        return hashlib.sha256(inspect.getsource(function).replace('\r\n','\n').encode()).hexdigest() == SCORE_SOURCE
    except (OSError, TypeError):
        return False


def coefficients(tl, hell):
    from farm.hybrid.fight import COLUMNS, BUCKETS, compiled_dict
    from sunken_sim import mage
    if not supported(mage._score):
        raise RuntimeError('unverified Mage score formula')
    c = compiled_dict(tl, np.zeros(len(COLUMNS)), hell)
    st = tl.stats
    raw, p, m = c['raw'], st['potency'], st['mastery']
    ac = mage._crit_factor(st['crit'], 2 + st['rating'])
    sc = mage._crit_factor(st['crit'], st['spell_mult'] + st['rating']) if st['spell_crit'] else 1.
    full = mage.armor_taken(mage.DUMMY_ARMOR)
    pen = mage.armor_taken(mage.DUMMY_ARMOR - st['armor_pen'])
    v = dict.fromkeys(COLUMNS, 0.)
    v['auto_weight'] = (st['ad'] + p * st['attack_potency']) * st['auto_pct'] * ac * pen
    # Preserve the reference's two full-armor factors on Stab (not a balance fix).
    v['auto_weight'] += (st['stab_ratio'] * st['ad'] + p * st['attack_potency']) * st['auto_pct'] * ac * mage.CHAOS_UNARMORED * st['stab_chance'] * (1 + st['luck']) * full * full
    v['soul_weight'] = st['soul_rate'] * mage.MEDIAN_MONSTER_HP * st['auto_pct'] * ac * pen
    v['splash'] = (20 + .35 * st['int']) * pen
    for k in BUCKETS:
        base = sc * raw['bolt' if k == 'bolt_splash' else k] * pen
        v['base:' + k], v['slope:' + k] = base, base * m
        v['pot_base:' + k], v['pot_slope:' + k] = sc * p * pen, sc * p * m * pen
    base = sc * raw['pyro'] * full
    v.update(pyro_base=base, pyro_slope=base*m, pyro_m_base=base*m,
             pyro_m_slope=base*m*m, pyro_pot_base=sc*p*full,
             pyro_pot_slope=sc*p*m*full, pyro_raw_base=raw['pyro']*full,
             pyro_raw_mastery=raw['pyro']*m*full)
    for k in ('hydra','cleave'):
        v[k+'_base'] = c['glass'] * raw['hydra'] * full
        v[k+'_pot_base'] = c['glass'] * p * st['attack_potency'] * full
    v['sulf_base'] = sc * st['int'] * pen
    v['sulf_slope'] = sc * st['int'] * m * pen
    v['sulf_echo'] = st['ad'] * full
    v['hell_weight'] = (c['hell_raw'] + p) * c['glass'] * pen
    v['blood'] = .03 * (20 + 1.6 * st['int'] + p) * c['glass'] * pen
    return np.array([v[k] for k in COLUMNS], dtype=np.float64)


def score_rows(torch, target, sums, tls, hells, pool=None):
    from sunken_sim.shadow import FIGHT
    values = np.array([coefficients(tl,h) for tl,h in zip(tls,hells)], dtype=np.float32)
    if not np.isfinite(values).all() or (values < 0).any():
        raise RuntimeError('unsupported non-positive/cancelling feature domain')
    features = pool.up('final_features',values) if pool else torch.from_numpy(values).to(target)
    dps = (sums * features).sum(dim=1) / FIGHT
    # Synchronize before a pooled input can be overwritten by the next batch.
    out = dps.cpu().numpy().astype(np.float64)
    if not np.isfinite(out).all():
        raise RuntimeError('non-finite device final score')
    return out


def owner_reduce(torch,target,scores,owners,count,pool=None):
    """GPU max/first argmax; padded copies are masked before the runner-up."""
    groups = [[] for _ in range(count)]
    for i,owner in enumerate(owners):groups[owner].append(i)
    if not groups or any(not g for g in groups):
        raise RuntimeError('missing owner timeline')
    width = max(map(len,groups))
    indices = np.array([g+[g[0]]*(width-len(g)) for g in groups],dtype=np.int64)
    valid = np.array([[1]*len(g)+[0]*(width-len(g)) for g in groups],dtype=np.float32)
    source = np.asarray(scores,dtype=np.float32)
    source = pool.up('owner_scores',source) if pool else torch.from_numpy(source).to(target)
    idx = torch.from_numpy(indices).to(target)
    mask = pool.up('owner_valid',valid) if pool else torch.from_numpy(valid).to(target)
    rows = source[idx]
    rows = torch.where(mask>.5,rows,torch.full_like(rows,-float('inf')))
    best, slots = rows.max(dim=1)
    columns = torch.arange(width,device=target,dtype=torch.int64)[None,:]
    rest = torch.where(columns==slots[:,None],torch.full_like(rows,-float('inf')),rows)
    second = rest.max(dim=1).values
    info = torch.stack((best,second,slots.to(torch.float32)),dim=1).cpu().numpy()
    if not np.isfinite(info[:,0]).all():raise RuntimeError('non-finite owner score')
    return info,groups
