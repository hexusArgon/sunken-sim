#!/usr/bin/env python3
"""All Pick v2: specialization per hero copy (run after patch_all_pick_v2.py).

Spec state itself is per slot (level of the spec ability on udg_Glyphs_Unit[slot]),
but its presentation was class-global, so two copies of one class looked like one spec:
  * BlzSetAbilityIcon changes the icon of an ability TYPE for everybody: spec button
    on the glyph unit + spec-dependent class icons (Metamorphosis, Divine Image, ...).
  * Specs_Board_Update drew every row with BlzGetAbilityIcon(<spec ability>), so all
    copies of a class showed the icon of whoever switched last.
  * Glyph/talent clicks were bound to "the first copy owned by the player".

Changes (v2 only):
  1. BlzSetAbilityIcon -> HP_SpecIcon (Specialization_Change) / HP_AbIcon (rest).
     While a class has <2 copies the call is unchanged (global). With 2+ copies the
     icon is applied only on the owner's client (GetLocalPlayer, visual only).
  2. udg_HP_SpecIcon[slot] keeps the synced spec icon per slot; the spec board reads it.
  3. A new copy of an already-taken class gets that class's icons reset to the map
     defaults on its owner's client (unless that player already has a copy).
  4. HP_EvE_<Class>: a glyph/talent unit of slot s binds the hero in slot s first.
Idempotent check: refuses to run twice. usage: patch_spec_per_copy.py <in.j> <out.j>
"""
import re
import sys

ICON = re.compile(r"^call BlzSetAbilityIcon\((.*)\)$")
LOCAL_FN = {'MetamorphosisIcons': 'DemonHunter', 'DivineImageIcon': 'Priest',
            'HomingMissilesTooltip': 'Tinker'}
LOCAL_IDS = {'DemonHunter': ["'A0RD'", "'A076'", "'A06F'", "'A0CK'"], 'Priest': ["'A0JK'"],
             'Tinker': ["'A02T'"], 'DragonSentinel': ["'A0O6'"]}
# literal ability id -> class, for icon calls outside Specialization_Change
ABIL_CLASS = {"'A0HI'": 'Tidewarrior', "'A01T'": 'Windmaster', "'A0OB'": 'DragonSentinel',
              "'A0O1'": 'DragonSentinel', "'A0FE'": 'Monk', "'A0QX'": 'Warlock', "'A02T'": 'Tinker'}

HELPERS = r'''function HP_AuxSlot takes unit u returns integer
local integer s=1
if u==null then
return 0
endif
loop
exitwhen s>3
if u==udg_Glyphs_Unit[s] or u==udg_Talents_Unit[s] or u==udg_Agi_Str_Int[s] then
return s
endif
set s=s+1
endloop
return 0
endfunction
function HP_AuxHero takes unit u returns unit
local integer s=HP_AuxSlot(u)
if s==0 then
return null
endif
return udg_Agi_Str_Int[s]
endfunction
function HP_IconKeep takes integer abil returns nothing
if not HaveSavedString(udg_HP_IconHT,0,abil) then
call SaveStr(udg_HP_IconHT,0,abil,BlzGetAbilityIcon(abil))
endif
endfunction
function HP_IconFor takes integer abil,string path,player p,integer c returns nothing
call HP_IconKeep(abil)
if udg_HP_Cnt[c]<2 or p==null then
call BlzSetAbilityIcon(abil,path)
elseif GetLocalPlayer()==p then
call BlzSetAbilityIcon(abil,path)
endif
endfunction
function HP_AbIcon takes integer abil,string path,unit u,integer c returns nothing
call HP_IconFor(abil,path,GetOwningPlayer(u),c)
endfunction
function HP_SpecIcon takes integer abil,string path,integer c returns nothing
local integer s=HP_AuxSlot(GetTriggerUnit())
if s>0 and abil==GetSpellAbilityId() then
set udg_HP_SpecIcon[s]=path
endif
call HP_IconFor(abil,path,GetTriggerPlayer(),c)
endfunction
function HP_SpecIconOf takes integer s,integer abil returns string
if udg_HP_SpecIcon[s]!="" and udg_HP_SpecIcon[s]!=null then
return udg_HP_SpecIcon[s]
endif
if HaveSavedString(udg_HP_IconHT,0,abil) then
return LoadStr(udg_HP_IconHT,0,abil)
endif
return BlzGetAbilityIcon(abil)
endfunction
function HP_IconDef takes player p,integer abil returns nothing
if HaveSavedString(udg_HP_IconHT,0,abil) and GetLocalPlayer()==p then
call BlzSetAbilityIcon(abil,LoadStr(udg_HP_IconHT,0,abil))
endif
endfunction
function HP_OwnsCopy takes integer c,player p returns boolean
local integer k=1
loop
exitwhen k>udg_HP_Cnt[c]
if GetOwningPlayer(udg_HP_I[c*4+k])==p then
return true
endif
set k=k+1
endloop
return false
endfunction'''


def main(src, dst):
    text = open(src, encoding='latin-1', newline='').read()
    if 'function HP_SpecIcon ' in text:
        raise SystemExit('already patched')
    L = text.split('\n')
    # class index from HP_New_<Class>
    cls_idx = {}
    for i, l in enumerate(L):
        m = re.match(r'function HP_New_(\w+) takes unit u', l)
        if m:
            m2 = re.search(r'udg_HP_Cnt\[(\d+)\]', L[i + 2])
            cls_idx[m.group(1)] = int(m2.group(1))
    assert len(cls_idx) == 21, cls_idx
    st = {'spec_icon': 0, 'ab_icon': 0, 'board': 0, 'eve': 0, 'spec_reset': 0, 'new_reset': 0,
          'icon_left': 0}
    ids_by_class = {c: set(v) for c, v in LOCAL_IDS.items()}
    out, cur, mclass = [], None, None
    for i, l in enumerate(L):
        if l.startswith('function '):
            cur = l.split()[1]
            mclass = None
        if cur == 'Trig_Specialization_Change_Actions':
            m = re.match(r'set udg_Mastery_Unit=udg_Hero_(\w+)$', l)
            if m:
                mclass = m.group(1)
            m = ICON.match(l)
            if m:
                assert mclass, i
                aid = m.group(1).split(',')[0]
                ids_by_class.setdefault(mclass, set()).add(aid)
                l = f'call HP_SpecIcon({m.group(1)},{cls_idx[mclass]})'
                st['spec_icon'] += 1
        else:
            m = ICON.match(l)
            if m:
                aid = m.group(1).split(',')[0]
                c = LOCAL_FN.get(cur) or ABIL_CLASS.get(aid)
                if c:
                    ids_by_class.setdefault(c, set()).add(aid)
                    l = f'call HP_AbIcon({m.group(1)},udg_Hero_{c},{cls_idx[c]})'
                    st['ab_icon'] += 1
                else:
                    st['icon_left'] += 1
                    print('unmapped icon call', i + 1, cur, l[:120])
        if cur == 'Trig_Specs_Board_Update_Actions' and 'BlzGetAbilityIcon(' in l:
            l, n = re.subn(r"BlzGetAbilityIcon\(('[A-Za-z0-9]{4}')\)",
                           r'HP_SpecIconOf(udg_HP_BoardSlot,\1)', l)
            st['board'] += n
        out.append(l)
        if l == 'set udg_Glyphs_Unit[hp_s]=GetLastCreatedUnit()':
            out.append('set udg_HP_SpecIcon[hp_s]=""')
            st['spec_reset'] += 1
        m = re.match(r'if HP_BindP_(\w+)\(GetTriggerPlayer\(\)\) then$', l)
        if m and cur == f'HP_EvE_{m.group(1)}':
            c = m.group(1)
            out[-1:] = [f'if HP_Is_{c}(HP_AuxHero(GetTriggerUnit())) then', 'return', 'endif', l]
            st['eve'] += 1
    L = out
    # reset per class on a new copy
    out = []
    cur = None
    for i, l in enumerate(L):
        if l.startswith('function '):
            cur = l.split()[1]
        out.append(l)
        if cur and cur.startswith('HP_New_') and l == 'set udg_HP_Dup=true':
            c = cur[len('HP_New_'):]
            out[-1:] = [f'if not HP_OwnsCopy({cls_idx[c]},GetOwningPlayer(u)) then',
                        f'call HP_IconReset_{c}(GetOwningPlayer(u))', 'endif', l]
            st['new_reset'] += 1
    L = out
    resets = []
    for c in sorted(cls_idx):
        resets.append(f'function HP_IconReset_{c} takes player p returns nothing')
        for a in sorted(a for a in ids_by_class.get(c, ()) if re.fullmatch(r"'[A-Za-z0-9]{4}'", a)):
            resets.append(f'call HP_IconDef(p,{a})')
        resets.append('endfunction')
    first = next(i for i, l in enumerate(L) if l.startswith('function HP_'))
    L[first:first] = HELPERS.split('\n') + resets
    eg = L.index('endglobals')
    L[eg:eg] = ['string array udg_HP_SpecIcon', 'hashtable udg_HP_IconHT=InitHashtable()']
    assert st['spec_icon'] == 66 and st['board'] == 21 and st['eve'] == 21 \
        and st['new_reset'] == 21 and st['spec_reset'] == 3 and st['icon_left'] == 0, st
    open(dst, 'w', encoding='latin-1', newline='').write('\n'.join(L))
    print('spec per copy', st)
    print({c: sorted(v) for c, v in ids_by_class.items()})


if __name__ == '__main__':
    main(*sys.argv[1:3])
