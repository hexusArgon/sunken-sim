#!/usr/bin/env python3
"""Patch Sunken City war3map.j: shared hero-pick crystals.

- Picking a hero no longer removes the crystal (another player can buy from it).
- Hero goes to the class's native slot (Agi=1, Str=2, Int=3) if free, otherwise to
  the first free slot, so 2-3 heroes of the same attribute can be picked.
- When all 3 slots are filled, all 3 crystals (n01I/n01K/n01L) are removed.
- The same CLASS cannot be picked twice (class globals udg_Hero_<Class> are singletons).
- Class-specific reads of udg_PlayerNumber_AGI/STR/INT -> owner of udg_Hero_<Class>.
- Class talent / spec checks on udg_Talents_Unit[N] / udg_Glyphs_Unit[N] are remapped
  to the slot that hero actually occupies.

usage: patch_hero_crystals.py <in war3map.j> <out war3map.j>
"""
import re, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from hp_maps import funcs, class_maps, ATTRS

ARR = [  # (orig suffix pattern, scratch name, type, max index)
    ('Talents_{a}', 'HP_Talents', 'integer', 20),
    ('Ability_{a}_CDBase', 'HP_Ability_CDBase', 'real', 9),
    ('Ability_{a}_Tooltip', 'HP_Ability_Tooltip', 'string', 36),
    ('Ability_{a}_CD', 'HP_Ability_CD', 'real', 9),
    ('Ability_{a}', 'HP_Ability', 'integer', 9),
    ('CDR_Flat_{a}', 'HP_CDR_Flat', 'real', 9),
    ('CD_Temp_{a}', 'HP_CD_Temp', 'real', 9),
    ('SpecTooltipBase_{a}', 'HP_SpecTooltipBase', 'string', 3),
]
SLOT_ARR = ['Glyphs_Unit', 'BackpackUnit', 'Agi_Str_Int', 'Ability_Q_Type', 'Ability_Q']

# class-specific PlayerNumber reads: function-name regex -> {ATTR: class or 'slot'}
PN_MAP = [
    (r'^(GenerateFury|GenerateFuryAmount|Trig_Attack_Speed_Tooltip_|Trig_PreDamage_Increase_|Trig_PreDamage_Reduce_|'
     r'Trig_AfterDamage_Global_|Trig_Healing_|Trig_Eye_Beam_|Trig_Fury_|Trig_Immolation_Aura_|Trig_Leap_A_)',
     {'AGI': 'DemonHunter'}),
    (r'^(Trig_CDR_Setup_|Trig_Stampeding_Roar_|Trig_Swipe_|Trig_Rake_|Trig_Ferocity_)', {'AGI': 'FeralDruid'}),
    (r'^(StaggerCalculation|Trig_Stagger_|Trig_Stagger_Periodic_)', {'STR': 'Monk'}),
    (r'^(Trig_Dragon_Form_|Trig_Dragonfury_|Trig_OnSpellcast_Heroes_|Trig_Talents_|Trig_Talent_Disables_)',
     {'STR': 'DragonSentinel', 'AGI': 'FeralDruid'}),
    (r'^Trig_PreDamage_Heroes_', {'AGI': 'DemonHunter', 'STR': 'DragonSentinel', 'INT': 'Mage'}),
    (r'^(Trig_Arcane_Blast_|Trig_Pyroblast_)', {'INT': 'Mage'}),
    (r'^Trig_Lightning_Shield_', {'INT': 'Shaman'}),
    (r'^Trig_Specialization_Change_', {'INT': 'Mage', 'AGI': 'FeralDruid'}),
    (r'^(Trig_Eye_of_Discord_|Trig_Signet_of_the_Swarm_|Trig_Talent_List_Talent_Shop_)',
     {'AGI': 'slot', 'STR': 'slot', 'INT': 'slot'}),
]
SLOTNUM = {'AGI': 1, 'STR': 2, 'INT': 3}


def main(src, dst):
    L = open(src, encoding='latin-1').read().split('\n')
    F = funcs(L)
    type2cls, item2cls, spec2cls, cls2attr = class_maps(L, F)
    stats = {}
    def bump(k, n=1): stats[k] = stats.get(k, 0) + n

    # owner function for each line
    owner = [None] * len(L)
    for name, (s, e) in F.items():
        for i in range(s, e + 1): owner[i] = name
    select_bodies = {}
    for n, a, A in ATTRS:
        select_bodies['Trig_Select_%s_Hero_Actions' % a] = (n, a, A)

    out = list(L)

    # ---------- 1. generic remaps (outside Select bodies) ----------
    re_tal = re.compile(r"UnitHasItemOfTypeBJ\(udg_Talents_Unit\[([123])\],('\w{4}')\)")
    re_spec = re.compile(r"(GetUnitAbilityLevelSwapped|UnitAddAbilityBJ|UnitRemoveAbilityBJ)\(('\w{4}'),udg_Glyphs_Unit\[([123])\]\)")
    re_pn = re.compile(r'udg_PlayerNumber_(AGI|STR|INT)')
    unmapped_pn = []
    for i, l in enumerate(L):
        f = owner[i]
        if f is None or f in select_bodies or f == 'InitGlobals':
            continue
        nl = l
        def tal(m):
            c = item2cls.get(m.group(2))
            if c and cls2attr[c] == int(m.group(1)):
                bump('talent_check'); return "UnitHasItemOfTypeBJ(udg_Talents_Unit[HP_SlotOf(udg_Hero_%s)],%s)" % (c, m.group(2))
            return m.group(0)
        nl = re_tal.sub(tal, nl)
        def spec(m):
            cs = spec2cls.get(m.group(2))
            if cs and len(cs) == 1:
                c = next(iter(cs))
                if cls2attr[c] == int(m.group(3)):
                    bump('spec_check'); return "%s(%s,udg_Glyphs_Unit[HP_SlotOf(udg_Hero_%s)])" % (m.group(1), m.group(2), c)
            return m.group(0)
        nl = re_spec.sub(spec, nl)
        if re_pn.search(nl) and not f.startswith('Trig_Skins_Select'):
            mp = None
            for rx, d in PN_MAP:
                if re.match(rx, f): mp = d; break
            def pn(m):
                A = m.group(1)
                if mp is None or A not in mp:
                    unmapped_pn.append((i + 1, f, A)); return m.group(0)
                bump('playernumber')
                if mp[A] == 'slot':
                    return 'HP_PidOf(udg_Agi_Str_Int[%d])' % SLOTNUM[A]
                return 'HP_PidOf(udg_Hero_%s)' % mp[A]
            nl = re_pn.sub(pn, nl)
        out[i] = nl
    if unmapped_pn:
        raise SystemExit('unmapped PlayerNumber reads: %r' % unmapped_pn)

    # ---------- 2. CDR_Cast talent blocks: CDR_Flat_X writes -> HP_FlatAdd(slot of class) ----------
    s, e = F['Trig_CDR_Cast_And_Spell_Types_Actions']
    re_if = re.compile(r'if\((Trig_CDR_Cast_And_Spell_Types_\w+)\(\)\)then$')
    re_w = re.compile(r'set udg_CDR_Flat_(Agi|Str|Int)\[(\d)\]=\(udg_CDR_Flat_\1\[\2\]\+(.+)\)$')
    stack = []  # class per open if
    for i in range(s, e):
        l = L[i]
        m = re_if.match(l)
        if m:
            cls = None
            if m.group(1) in F:
                cs, ce = F[m.group(1)]
                items = re.findall(r"UnitHasItemOfTypeBJ\(udg_Talents_Unit\[[123]\],('\w{4}')\)", '\n'.join(L[cs:ce]))
                cl = {item2cls[x] for x in items if x in item2cls}
                if len(cl) == 1: cls = cl.pop()
            stack.append(cls); continue
        if l.startswith('if(') and l.endswith('then'):
            stack.append(None); continue
        if l == 'endif':
            if stack: stack.pop()
            continue
        m = re_w.match(l)
        if m:
            cls = next((c for c in reversed(stack) if c), None)
            if cls:
                out[i] = 'call HP_FlatAdd(HP_SlotOf(udg_Hero_%s),%s,%s)' % (cls, m.group(2), m.group(3))
                bump('cdr_flat')

    # ---------- 3. Select bodies ----------
    inserts = {}  # line idx -> list of lines to insert BEFORE
    for fname, (n, a, A) in select_bodies.items():
        s, e = F[fname]
        last_local = max(i for i in range(s, e) if L[i].startswith('local '))
        guard = [
            'local integer hp_s=HP_FindSlot(%d)' % n,
        ]
        out[last_local] = L[last_local] + '\n' + '\n'.join(guard) + '\n' + '\n'.join([
            'call HP_ReleaseCrystal(GetSellingUnit())',
            'if hp_s==0 or HP_ClassTaken(GetUnitTypeId(GetSoldUnit())) then',
            'call DisplayTimedTextToPlayer(GetOwningPlayer(GetSoldUnit()),0,0,8.00,"|cffff5555This hero is already taken or all 3 hero slots are full.|r")',
            'call RemoveUnit(GetSoldUnit())',
            'return',
            'endif',
            'set udg_HeroPickSlot=hp_s',
            'set udg_HP_SlotAttr[hp_s]=%d' % n,
            'call HP_LoadSlot(hp_s)',
        ])
        for i in range(last_local + 1, e):
            l = out[i]
            for arr in SLOT_ARR:
                l = l.replace('udg_%s[%d]' % (arr, n), 'udg_%s[hp_s]' % arr)
            for pat, scr, _, _ in ARR:
                l = re.sub(r'\budg_%s\[' % pat.format(a=a), 'udg_%s[' % scr, l)
            if l == 'call EnableTrigger(gg_trg_Talent_Select_%d)' % n:
                l = 'call HP_EnableTalentSelect(hp_s)'; bump('talent_select')
            if l == 'call RemoveUnit(GetSellingUnit())':
                l = 'call HP_CommitSlot(hp_s)\ncall HP_RemoveCrystalsIfFull()'; bump('remove_crystal')
            elif l.startswith('call ConditionalTriggerExecute(') or l.startswith('call TriggerExecute('):
                l = 'call HP_CommitSlot(hp_s)\n' + l + '\ncall HP_LoadSlot(hp_s)'; bump('commit')
            out[i] = l
        out[e] = 'call HP_CommitSlot(hp_s)\nendfunction'
        # leftovers check
        body = '\n'.join(out[s:e + 1])
        for arr in SLOT_ARR + ['Talents_Unit']:
            for k in (1, 2, 3):
                if 'udg_%s[%d]' % (arr, k) in body:
                    print('WARN leftover udg_%s[%d] in %s' % (arr, k, fname))

    # ---------- 4. Specs_Board_Update: loop over slots ----------
    for name, (s, e) in F.items():
        if name.startswith('Trig_Specs_Board_Update_') and not name.startswith('Trig_Specs_Board_Update_Init'):
            for i in range(s, e):
                out[i] = re.sub(r'udg_Agi_Str_Int\[[123]\]', 'udg_Agi_Str_Int[udg_HP_BoardSlot]', out[i])
    s, e = F['Trig_Specs_Board_Update_Actions']
    out[s] = out[s] + '\nset udg_HP_BoardSlot=1\nloop\nexitwhen udg_HP_BoardSlot>3\nif udg_Agi_Str_Int[udg_HP_BoardSlot]!=null then'
    out[e] = 'endif\nset udg_HP_BoardSlot=udg_HP_BoardSlot+1\nendloop\nendfunction'
    if any(re.search(r'\breturn\b', out[i]) for i in range(s + 1, e)):
        raise SystemExit('Specs_Board_Update_Actions has return; loop wrap unsafe')

    # ---------- 5. Skins ----------
    for name, (s, e) in F.items():
        if name.startswith('Trig_Skins_Dialog_'):
            for i in range(s, e):
                out[i] = re.sub(r'udg_Agi_Str_Int\[[13]\]', 'udg_Agi_Str_Int[udg_HeroPickSlot]', out[i])
            if name == 'Trig_Skins_Dialog_Actions':
                out[s] = out[s] + '\nset udg_HP_SkinHero[HP_PidOf(udg_Agi_Str_Int[udg_HeroPickSlot])]=udg_Agi_Str_Int[udg_HeroPickSlot]'
        if name.startswith('Trig_Skins_Select_') and name != 'Trig_Skins_Select_Actions' and not name.startswith('InitTrig'):
            for i in range(s, e):
                out[i] = re.sub(r'udg_Agi_Str_Int\[[13]\]', 'udg_HP_SkinHero[GetConvertedPlayerId(GetTriggerPlayer())]', out[i])
    s, e = F['Trig_Skins_Select_Actions']
    for i in range(s, e):
        l = out[i]
        m = re.match(r'call RemoveUnit\((udg_Hero_\w+)\)$', l)
        if m:
            l = 'set udg_HP_TmpSlot=HP_SlotOf(%s)\n%s' % (m.group(1), l)
        l = re.sub(r'udg_(BackpackUnit|Agi_Str_Int)\[[13]\]', r'udg_\1[udg_HP_TmpSlot]', l)
        l = re.sub(r'udg_Hero_Icon\[udg_PlayerNumber_(AGI|INT)\]', 'udg_Hero_Icon[HP_PidOf(GetLastCreatedUnit())]', l)
        out[i] = l

    # ---------- 6. Random_* ----------
    for n, a, A in ATTRS:
        s, e = F['Trig_Random_%s_Conditions' % a]
        for i in range(s, e):
            out[i] = out[i].replace('if(not(udg_Agi_Str_Int[%d]==null))then' % n, 'if(HP_FindSlot(%d)==0)then' % n)
        s, e = F['Trig_Random_%s_Actions' % a]
        for i in range(s, e):
            out[i] = out[i].replace('udg_Random_%s[GetRandomInt(1,7)]' % a, 'HP_RandomFree(%d)' % n)
            if out[i] == 'call DisableTrigger(GetTriggeringTrigger())':
                out[i] = '// shared crystals: trigger stays enabled until all slots are filled'

    # ---------- 7. globals + helpers ----------
    gi = L.index('endglobals')
    glob = ['integer udg_HeroPickSlot=0', 'integer array udg_HP_SlotAttr', 'integer udg_HP_TmpSlot=0',
            'integer udg_HP_BoardSlot=0', 'unit array udg_HP_SkinHero']
    glob += ['%s array udg_%s' % (t, scr) for _, scr, t, _ in ARR]
    out[gi] = '\n'.join(glob) + '\nendglobals'
    ni = gi + 1  # natives must stay before any function
    while ni < len(L) and not L[ni].startswith('function '):
        ni += 1
    out[ni] = helpers(type2cls, cls2attr) + '\n' + out[ni]

    txt = '\n'.join(out)
    open(dst, 'w', encoding='latin-1', newline='').write(txt)
    print('stats', stats)
    print('classes', len(cls2attr), 'talent items', len(item2cls))


def helpers(type2cls, cls2attr):
    h = []
    h.append('''function HP_PidOf takes unit u returns integer
if u==null then
return 0
endif
return GetConvertedPlayerId(GetOwningPlayer(u))
endfunction
function HP_SlotOf takes unit u returns integer
if u==null then
return 0
endif
if udg_Agi_Str_Int[1]==u then
return 1
elseif udg_Agi_Str_Int[2]==u then
return 2
elseif udg_Agi_Str_Int[3]==u then
return 3
endif
return 0
endfunction
function HP_FindSlot takes integer nat returns integer
local integer i=1
if udg_Agi_Str_Int[nat]==null then
return nat
endif
loop
exitwhen i>3
if udg_Agi_Str_Int[i]==null then
return i
endif
set i=i+1
endloop
return 0
endfunction
function HP_EnableTalentSelect takes integer s returns nothing
if s==1 then
call EnableTrigger(gg_trg_Talent_Select_1)
elseif s==2 then
call EnableTrigger(gg_trg_Talent_Select_2)
elseif s==3 then
call EnableTrigger(gg_trg_Talent_Select_3)
endif
endfunction
function HP_FlatAdd takes integer s,integer k,real v returns nothing
if s==1 then
set udg_CDR_Flat_Agi[k]=udg_CDR_Flat_Agi[k]+v
elseif s==2 then
set udg_CDR_Flat_Str[k]=udg_CDR_Flat_Str[k]+v
elseif s==3 then
set udg_CDR_Flat_Int[k]=udg_CDR_Flat_Int[k]+v
endif
endfunction''')
    h.append('function HP_ClassTaken takes integer t returns boolean')
    first = True
    for t, c in type2cls.items():
        h.append('%sif t==%s then' % ('' if first else 'else', t)); first = False
        h.append('return udg_Hero_%s!=null' % c)
    h.append('endif\nreturn false\nendfunction')
    h.append('''function HP_RandomFree takes integer attr returns integer
local integer i=0
local integer t=0
loop
exitwhen i>40
if attr==1 then
set t=udg_Random_Agi[GetRandomInt(1,7)]
elseif attr==2 then
set t=udg_Random_Str[GetRandomInt(1,7)]
else
set t=udg_Random_Int[GetRandomInt(1,7)]
endif
if not HP_ClassTaken(t) then
return t
endif
set i=i+1
endloop
return t
endfunction''')
    for verb, a2b in (('Load', True), ('Commit', False)):
        h.append('function HP_%sSlot takes integer s returns nothing\nlocal integer k=1' % verb)
        for n, a, A in ATTRS:
            h.append('%sif s==%d then' % ('' if n == 1 else 'else', n))
            for pat, scr, t, mx in ARR:
                o = 'udg_' + pat.format(a=a)
                src, dst = (o, 'udg_' + scr) if a2b else ('udg_' + scr, o)
                h.append('set k=1\nloop\nexitwhen k>%d\nset %s[k]=%s[k]\nset k=k+1\nendloop' % (mx, dst, src))
        h.append('endif\nendfunction')
    h.append('''function HP_ReleaseCrystal takes unit c returns nothing
if c!=null and GetOwningPlayer(c)!=Player(PLAYER_NEUTRAL_PASSIVE) then
call SetUnitOwner(c,Player(PLAYER_NEUTRAL_PASSIVE),false)
endif
endfunction
function HP_CrystalFilter takes nothing returns boolean
local integer t=GetUnitTypeId(GetFilterUnit())
return t=='n01I' or t=='n01K' or t=='n01L'
endfunction
function HP_RemoveCrystalsIfFull takes nothing returns nothing
local group g
local unit u
if udg_Agi_Str_Int[1]==null or udg_Agi_Str_Int[2]==null or udg_Agi_Str_Int[3]==null then
return
endif
call DisableTrigger(gg_trg_Random_Agi)
call DisableTrigger(gg_trg_Random_Str)
call DisableTrigger(gg_trg_Random_Int)
call DisableTrigger(gg_trg_All_Random)
set g=CreateGroup()
call GroupEnumUnitsInRect(g,bj_mapInitialPlayableArea,Filter(function HP_CrystalFilter))
loop
set u=FirstOfGroup(g)
exitwhen u==null
call GroupRemoveUnit(g,u)
call RemoveUnit(u)
endloop
call DestroyGroup(g)
set g=null
if gg_unit_n01I_0273!=null then
call RemoveUnit(gg_unit_n01I_0273)
endif
if gg_unit_n01K_0282!=null then
call RemoveUnit(gg_unit_n01K_0282)
endif
if gg_unit_n01L_0281!=null then
call RemoveUnit(gg_unit_n01L_0281)
endif
endfunction''')
    return '\n'.join(h)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
