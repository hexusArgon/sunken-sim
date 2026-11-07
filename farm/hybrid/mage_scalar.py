# Reviewed CPU scheduler reads (raw damage/scoring are downstream on fresh stats).
SCALAR_STATS = ("attack_base", "attack_mana", "attack_mana_crit", "attack_mana_pct",
 "attack_speed", "bomb_period", "cast_refund", "cast_refund_flat", "cast_refund_mastery",
 "cast_stun_lock", "cd_temp", "crit_as", "crit_as_duration", "damage_mana_pct",
 "flat_cdr", "frenzy", "haste", "luck", "mana_max", "mana_regen", "mastery", "str",
 "stun_per_swing", "swing")

"""Exact scalar Mage planner. No global capture patch, history, or legacy caches."""

def generate_scalar_timelines(builds, spec, targets, bound_keys, prepared_stats=None, diagnostics=None):
    from sunken_sim import mage
    if len(builds) != len(bound_keys):
        raise ValueError('bound_keys length mismatch')
    if prepared_stats is not None and len(prepared_stats) != len(builds):
        raise ValueError('prepared_stats length mismatch')
    import os
    hooks = {}
    if os.environ.get("FARM_FIRE_JIT_HYDRA", "0") == "1":
        try:
            from farm.hybrid.mage_jit import hooks as jit_hooks
            native, make = jit_hooks()
            hooks = dict(_hydra_sum=native, _new_hydras=make)
        except Exception:
            if diagnostics is not None:
                diagnostics['jit_unavailable'] = diagnostics.get('jit_unavailable', 0) + 1
    out = []
    for i, (build, bound) in enumerate(zip(builds, bound_keys)):
        stats = None if prepared_stats is None else prepared_stats[i]
        try:
            row = mage.simulate(build, targets, None, bound, spec, use_history=False,
                                _capture_only=True, _prepared_stats=stats, **hooks)
            if hooks and diagnostics is not None:
                diagnostics['jit_rows'] = diagnostics.get('jit_rows', 0) + 1
        except Exception:
            if not hooks: raise
            if diagnostics is not None:
                diagnostics['jit_fallback_rows'] = diagnostics.get('jit_fallback_rows', 0) + 1
            row = mage.simulate(build, targets, None, bound, spec, use_history=False,
                                _capture_only=True, _prepared_stats=stats)
        from types import MappingProxyType
        events, stats, used_spec, evocation = row
        immutable = tuple(tuple(ev[:5]) + (MappingProxyType(dict(ev[5])),) for ev in events)
        out.append((immutable, stats, used_spec, evocation))
    if diagnostics is not None:
        diagnostics['scalar_calls'] = diagnostics.get('scalar_calls', 0) + 1
        diagnostics['scalar_rows'] = diagnostics.get('scalar_rows', 0) + len(out)
    return out

def cadence_stats(stats):
    keys = ('attack_base', 'attack_mana', 'attack_mana_crit', 'attack_mana_pct', 'attack_speed', 'bomb_period', 'cast_refund', 'cast_refund_flat', 'cast_refund_mastery', 'cast_stun_lock', 'cd_temp', 'crit_as', 'crit_as_duration', 'damage_mana_pct', 'flat_cdr', 'frenzy', 'haste', 'luck', 'mana_max', 'mana_regen', 'mastery', 'str', 'stun_per_swing', 'swing')
    attrs = {k: stats.get(k) for k in keys}
    attrs['crit'] = stats.get('crit') if stats.get('attack_mana_crit',0) or (stats.get('crit_as',0)>0 and stats.get('crit_as_duration',0)>0) else None
    return attrs


def verify_vector_rows(builds, spec, targets, keys, rows, prepared_stats, diagnostics):
    """Fail closed: score tolerances cannot certify discrete scheduling choices.

    This opt-in diagnostic arm deliberately pays for exact scalar captures.
    Even sub-ulp event differences are canonicalized, not waved through using
    a DPS tolerance. The scalar default does not pay this second planner cost.
    """
    from sunken_sim import mage
    out=[]
    for i,(b,key,row) in enumerate(zip(builds,keys,rows)):
        st=None if prepared_stats is None else prepared_stats[i]
        exact=mage.simulate(b,targets,None,key,spec,use_history=False,
                            _capture_only=True,_prepared_stats=st)
        diagnostics['vector_checked_rows']=diagnostics.get('vector_checked_rows',0)+1
        if list(row[0]) != exact[0] or row[1:] != exact[1:]:
            diagnostics['vector_repaired_rows']=diagnostics.get('vector_repaired_rows',0)+1
            out.append(exact)
        else:
            out.append(row)
    return out
