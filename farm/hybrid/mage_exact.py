"""Exact ordered oracle compile with per-compile invariant damage context.

No persistent item/stat cache and no reassociated summation. Source proof is
provided by the caller's current TapeLRU guard; unknown paths use the oracle.
"""
import os

def compile_exact(tl,guard):
    from sunken_sim import mage,shadow,pressure
    allowed=(guard.split and mage._wears is shadow._wears
             and mage.hero_hp_ratio is pressure.hero_hp_ratio
             and mage.max_hp is pressure.max_hp)
    if os.environ.get('FARM_FIRE_COMPILE_CONTEXT','1')=='0' or not allowed:
        return mage._compile(tl.events,tl.build,tl.stats,tl.spec,tl.evocation)
    build,stats=tl.build,tl.stats
    crimson=mage._wears(build,mage._CRIMSON)
    cap=0.38 if crimson else 1.0
    health=mage.max_hp(mage.BASE_HP,stats['str'])+mage._flat_health(build)
    furnace=mage._wears(build,mage._FURNACE)
    gladiator=mage._wears(build,mage._GLADIATOR_MASK)
    ratio_at=mage.hero_hp_ratio
    def damage_at(when,kind):
        ratio=ratio_at(when,health,0.0,cap)
        factor=1.0
        if furnace and kind not in ('hydra','cleave'):
            factor+=0.20*(1.0-ratio)
        if ratio<=0.40:
            if gladiator:factor+=0.15
            if crimson:factor+=0.15
        return factor
    return mage._compile(tl.events,build,stats,tl.spec,tl.evocation,_damage_at=damage_at)
