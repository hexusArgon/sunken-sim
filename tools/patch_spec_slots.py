#!/usr/bin/env python3
"""Spec checks that still read a hard-coded "native" glyph slot (All Pick + v2).

Spec = level of the spec ability on udg_Glyphs_Unit[slot]. In All Pick a hero may sit in
any slot 1..3, but three places still read a literal slot:
  MetamorphosisIcons (Demon Hunter, Glyphs_Unit[1]) -> HP_SlotOf(udg_Hero_DemonHunter)
  DivineImageIcon    (Priest, Glyphs_Unit[3])       -> HP_SlotOf(udg_Hero_Priest)
  ArmorDamage_Reduce (Dragon Sentinel A0O6, [3])     -> HP_SlotOf(udg_DamageEventTarget)
Idempotent. usage: patch_spec_slots.py <in.j> <out.j>
"""
import sys

FIX = {
    'MetamorphosisIcons': ('GetUnitAbilityLevelSwapped(specAbility,udg_Glyphs_Unit[1])',
                           'GetUnitAbilityLevelSwapped(specAbility,udg_Glyphs_Unit[HP_SlotOf(udg_Hero_DemonHunter)])', 3),
    'DivineImageIcon': ('GetUnitAbilityLevelSwapped(specAbility,udg_Glyphs_Unit[3])',
                        'GetUnitAbilityLevelSwapped(specAbility,udg_Glyphs_Unit[HP_SlotOf(udg_Hero_Priest)])', 3),
    'Trig_ArmorDamage_Reduce_Func001Func022Func004Func024C': (
        "GetUnitAbilityLevelSwapped('A0O6',udg_Glyphs_Unit[3])",
        "GetUnitAbilityLevelSwapped('A0O6',udg_Glyphs_Unit[HP_SlotOf(udg_DamageEventTarget)])", 1),
}


def main(src, dst):
    text = open(src, encoding='latin-1', newline='').read()
    lines = text.split('\n')
    cur, cnt = None, {k: 0 for k in FIX}
    for i, l in enumerate(lines):
        if l.startswith('function '):
            cur = l.split()[1]
        if cur in FIX and FIX[cur][0] in l:
            lines[i] = l.replace(FIX[cur][0], FIX[cur][1])
            cnt[cur] += 1
    for k, (a, b, n) in FIX.items():
        done = sum(1 for l in lines if b in l)
        if cnt[k] not in (0, n) or done < n:
            raise SystemExit(f'{k}: replaced {cnt[k]}, present {done}, expected {n}')
    open(dst, 'w', encoding='latin-1', newline='').write('\n'.join(lines))
    print('spec slot fixes', cnt)


if __name__ == '__main__':
    main(*sys.argv[1:3])
