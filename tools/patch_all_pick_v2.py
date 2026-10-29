#!/usr/bin/env python3
"""All Pick v2: allow the same hero class to be picked more than once.

Input : All Pick script (patch_hero_crystals.py [+ patch_anticheat.py] output).
Output: script where every class keeps a list of instances and swaps its
        class-private globals in/out when a different instance becomes "bound".

Design (see docs/hero-all-pick-v2.md):
  udg_HP_I[c*4+k]  k=1..udg_HP_Cnt[c]  hero instances of class c
  udg_HP_Cur[c]    index of the instance currently loaded into udg_Hero_X and
                   the class-private globals; udg_HPS_<var>[k] holds the rest
                   (k=0 is the default snapshot used to initialise new copies)
  udg_HP_Dup       true once any class has >=2 instances (fast path otherwise)
  HP_Is_X(u)       replaces every  u==udg_Hero_X  test; binds u when it is
                   another instance of X
  entry binding    triggers that touch class X bind the instance from the
                   event (unit / damage source+target / expired timer / player)
  periodic per-hero triggers run once per instance
  waits            re-bind the instance the thread had before the wait
With one instance per class the behaviour is identical to the All Pick map.
"""
import re, sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hp_maps import funcs, class_maps

# periodic triggers that implement one hero's own passive -> run per instance
LOOP_TRIGGERS = ['Ardent_Defender_CD', 'Berserker_Rage', 'Insanity', 'Lightning_Shield_Buff_Clear',
                 'Minigun_Sentries_Counter', 'Out_of_Combat_Paladin', 'Out_of_Combat_Tinker',
                 'Out_of_Combat_WM', 'Reinforce_Reset', 'Stagger_Periodic', 'Teeth_Passive', 'Tenacity',
                 'Tidewarrior_AS_Bonuses', 'Collect_Soul_Fragments', 'Blood_Reaper_Magical',
                 'Siren_Periodic', 'Ysera_Gift', 'Presence', 'Primal_Instinct']
SWAP_TYPES = {'integer', 'real', 'boolean', 'string', 'unit', 'effect', 'timer', 'commandbuttoneffect', 'item'}
MAXINST = 4      # stride; instances 1..3 (3 hero slots), 0 = default snapshot
WAIT_RX = re.compile(r'^call (TriggerSleepAction|PolledWait)\(')
REG_RX = re.compile(r'^call (\w*TriggerRegister\w+)\(gg_trg_(\w+),(.*)$')


def die(msg):
    sys.stderr.write('patch_all_pick_v2: ' + msg + '\n'); sys.exit(1)


# ---------------------------------------------------------------- operand scan
STOP = set(',=!<>+-*/ ')

def left_start(s, end):
    depth = 0; j = end - 1
    while j >= 0:
        ch = s[j]
        if ch == '"' or ch == "'" and depth == 0 and False: return None
        if ch in ')]': depth += 1
        elif ch in '([':
            if depth == 0: break
            depth -= 1
        elif depth == 0 and ch in STOP: break
        j -= 1
    return j + 1

def right_end(s, start):
    depth = 0; j = start
    while j < len(s):
        ch = s[j]
        if ch in '([': depth += 1
        elif ch in ')]':
            if depth == 0: break
            depth -= 1
        elif depth == 0 and ch in STOP: break
        j += 1
    return j

def skip_operand(a):
    a = a.strip()
    return a == '' or a == 'null' or 'GetFilterUnit()' in a or 'GetEnumUnit()' in a or '"' in a

def rewrite_line(l, classes, stats):
    if 'udg_Hero_' not in l or l.startswith('local ') or l.startswith('//'):
        return l
    if '"' in l:   # keep it simple: no string literals on rewritten lines
        if re.search(r'[=!]=\s*(GetOwningPlayer\()?udg_Hero_|udg_Hero_\w+\)?[=!]=', l):
            stats['skip_string_line'] += 1
        return l
    for kind, tokrx, fn in (('own', r'GetOwningPlayer\(udg_Hero_(\w+)\)', 'HP_OwnIs_'),
                            ('id', r'udg_Hero_(\w+)\b(?![\[\w])', 'HP_Is_')):
        pos = 0
        while True:
            # form A: <op> TOKEN   form B: TOKEN <op>
            ma = re.compile(r'(==|!=)' + tokrx).search(l, pos)
            mb = re.compile(tokrx + r'(==|!=)').search(l, pos)
            cand = [m for m in (ma, mb) if m and (m.group(2) if m is ma else m.group(1)) in classes]
            # discard matches whose class group is not a class: advance past them
            if not cand:
                nxt = [m for m in (ma, mb) if m]
                if not nxt: break
                pos = min(m.end() for m in nxt) - 1 if min(m.end() for m in nxt) - 1 > pos else pos + 1
                if pos >= len(l): break
                continue
            m = min(cand, key=lambda x: x.start())
            if m is ma:
                op, cls = m.group(1), m.group(2)
                a0 = left_start(l, m.start()); oper = l[a0:m.start()]; a1 = m.end()
                tok_s = a0; tok_e = a1
            else:
                cls, op = m.group(1), m.group(2)
                if m.start() > 0 and (l[m.start()-1].isalnum() or l[m.start()-1] == '_'):
                    pos = m.end(); continue
                b1 = right_end(l, m.end()); oper = l[m.end():b1]
                tok_s = m.start(); tok_e = b1
            if kind == 'id' and m is mb and m.start() >= 16 and l[m.start()-16:m.start()] == 'GetOwningPlayer(':
                pos = m.end(); continue
            if skip_operand(oper):
                stats['skip_' + kind] += 1; pos = m.end(); continue
            rep = '%s%s(%s)' % (fn, cls, oper.strip())
            if op == '!=': rep = '(not %s)' % rep
            l = l[:tok_s] + rep + l[tok_e:]
            stats[kind + op] += 1
            pos = tok_s + len(rep)
    return l


def main(src, dst):
    raw = open(src, 'rb').read().decode('latin-1')
    nl = '\r\n' if '\r\n' in raw else '\n'
    L = raw.split(nl)
    F = funcs(L)
    t2c, i2c, s2c, c2a = class_maps(L, F)
    CL = sorted(c2a)
    if len(CL) != 21: die('expected 21 classes, got %d' % len(CL))
    CI = {c: i + 1 for i, c in enumerate(CL)}
    body = {n: '\n'.join(L[s:e + 1]) for n, (s, e) in F.items()}
    rx_call = re.compile(r'\b([A-Za-z_]\w*)\(')
    calls = {n: set(m for m in rx_call.findall(b) if m in F and m != n and not m.startswith('HP_')) for n, b in body.items()}
    direct = {n: set(c for c in re.findall(r'udg_Hero_(\w+)\b', b) if c in c2a) for n, b in body.items()}
    for n in F:
        if n.startswith('HP_'): direct[n] = set()
    sys.setrecursionlimit(20000)
    reach = {}
    def R(n, stack=()):
        if n in reach: return reach[n]
        if n in stack: return set()
        s = set(direct[n])
        for m in calls[n]: s |= R(m, stack + (n,))
        reach[n] = s; return s
    for n in F: R(n)

    # ---- triggers: events + registered functions (scan whole file)
    events = collections.defaultdict(list); regs = collections.defaultdict(list)
    for i, l in enumerate(L):
        m = REG_RX.match(l)
        if m: events[m.group(2)].append((m.group(1), m.group(3), i))
        m = re.match(r'^call TriggerAdd(Action|Condition)\(gg_trg_(\w+),(?:Condition\(|Filter\()?function (\w+)\)?\)$', l)
        if m: regs[m.group(2)].append((m.group(1), m.group(3), i))
    sel = set(n for n in F if n.startswith('Trig_Select_'))
    EXCL = lambda n: (n in ('InitGlobals', 'main', 'config', 'InitCustomTriggers', 'RunInitializationTriggers')
                      or n.startswith('InitTrig_') or n.startswith('HP_') or n in sel)
    trigcls = {}
    for t, rr in regs.items():
        s = set()
        for _, f, _ in rr: s |= reach.get(f, set())
        trigcls[t] = s
    fn2trig = {}
    for t, rr in regs.items():
        for _, f, _ in rr: fn2trig.setdefault(f, set()).add(t)
    def fclass(n):
        s = set(reach[n])
        for t in fn2trig.get(n, ()): s |= trigcls[t]
        if n.startswith('Trig_'):
            for t in sorted(regs, key=len, reverse=True):
                if n.startswith('Trig_' + t + '_'):
                    s |= trigcls[t]; break
        return s

    # ---- globals
    gs = L.index('globals'); ge = L.index('endglobals')
    glob = {}
    for i in range(gs, ge):
        m = re.match(r'^(constant )?(\w+)( array)? (udg_\w+)', L[i])
        if m and not m.group(1): glob[m.group(4)] = (m.group(2), bool(m.group(3)))
    ig_s, ig_e = F['InitGlobals']
    ig_body = '\n'.join(L[ig_s:ig_e + 1])
    uses = collections.defaultdict(list)
    for n, b in body.items():
        if EXCL(n): continue
        for g in set(re.findall(r'\budg_\w+', b)):
            if g in glob: uses[g].append(n)
    alltext = '\n'.join(L[ge:])
    nonig = '\n'.join(L[ge:ig_s] + L[ig_e + 1:])
    priv = collections.defaultdict(list); rej = collections.Counter()
    for g, fs in sorted(uses.items()):
        if g.startswith('udg_Hero_') or g.startswith('udg_HP_'): continue
        cs = set()
        bad = False
        for f in fs:
            fc = fclass(f)
            if not fc: bad = True
            cs |= fc
        if bad or len(cs) != 1: continue
        c = next(iter(cs)); typ, arr = glob[g]
        if typ not in SWAP_TYPES: rej['type_' + typ] += 1; continue
        if arr:
            subs = re.findall(r'\b' + g + r'\[([^\]]*)\]', nonig)
            if not subs or any(not re.fullmatch(r'\d+', x) for x in subs): rej['array_varsub'] += 1; continue
            M = max(int(x) for x in subs) + 1
            if M > 32: rej['array_big'] += 1; continue
        else:
            M = 0
            if typ == 'integer' and re.search(r'\[[^\]\n]*\b' + g + r'\b', nonig): rej['int_index'] += 1; continue
            if re.search(r'exitwhen[^\n]*\b' + g + r'\b', nonig): rej['loop_counter'] += 1; continue
        if typ == 'timer' and arr: rej['timer_array'] += 1; continue
        priv[c].append((g, typ, M))
    # private timers created in InitGlobals and triggers registered on them
    fresh = {}
    for c in CL:
        for g, typ, M in priv[c]:
            if typ == 'timer' and re.search(r'^set ' + g + r'=CreateTimer\(\)$', ig_body, re.M):
                trg = [t for t, ev in events.items() for (k, a, _) in ev
                       if k.startswith('TriggerRegisterTimerExpireEvent') and a.rstrip(')') == g]
                fresh[g] = sorted(set(trg))
    ptimers = {c: [g for g, typ, M in priv[c] if typ == 'timer'] for c in CL}

    stats = collections.Counter()
    out = list(L)
    # ---- 1. identity rewrites
    classes = set(CL)
    for n, (s, e) in F.items():
        if EXCL(n) or not reach[n] and 'udg_Hero_' not in body[n]: continue
        if n.startswith('Trig_Skins_Select') and False: pass
        for i in range(s + 1, e):
            out[i] = rewrite_line(out[i], classes, stats)

    # ---- 2. Select bodies / skins / other assignments
    for i, l in enumerate(out):
        m = re.match(r'^set udg_Hero_(\w+)=(GetSoldUnit\(\)|GetLastCreatedUnit\(\))$', l)
        if m and m.group(1) in classes:
            owner = next((n for n, (s, e) in F.items() if s < i < e), None)
            if m.group(2) == 'GetSoldUnit()' and owner in sel:
                out[i] = 'call HP_New_%s(GetSoldUnit())' % m.group(1); stats['new'] += 1
            elif m.group(2) == 'GetLastCreatedUnit()' and owner and owner.startswith('Trig_Skins_Select'):
                out[i] = 'call HP_Replace_%s(GetLastCreatedUnit())' % m.group(1); stats['replace'] += 1
            else: die('unexpected hero assignment line %d: %s' % (i + 1, l))
        elif re.match(r'^set udg_Hero_(\w+)=', l) and l.split('=')[0][8:] in classes:
            owner = next((n for n, (s, e) in F.items() if s < i < e), None)
            if owner != 'InitGlobals': die('unexpected hero assignment line %d: %s (%s)' % (i + 1, l, owner))
    if stats['new'] != 21: die('expected 21 Select assignments, got %d' % stats['new'])
    g_old = 'if hp_s==0 or HP_ClassTaken(GetUnitTypeId(GetSoldUnit())) then'
    ng = sum(1 for l in out if l == g_old)
    if ng != 3: die('select guard count %d' % ng)
    out = ['if hp_s==0 then' if l == g_old else l for l in out]
    msg_old = 'This hero is already taken or all 3 hero slots are full.'
    nm = sum(1 for l in out if msg_old in l)
    out = [l.replace(msg_old, 'All 3 hero slots are full.') for l in out]
    stats['guard_msg'] = nm
    nr = sum(1 for l in out if l == 'if not HP_ClassTaken(t) then')
    if nr < 1: die('HP_RandomFree check not found')
    out = ['if true then' if l == 'if not HP_ClassTaken(t) then' else l for l in out]

    # ---- 3. entry binding, waits, loop wrappers (insertions per line index)
    after = collections.defaultdict(list); before = collections.defaultdict(list)
    def first_stmt(n):
        s, e = F[n]; i = s + 1
        while i < e and out[i].startswith('local '): i += 1
        return i
    def kind_of(t):
        ks = set()
        for k, a, _ in events.get(t, []):
            if 'VariableEvent' in k and 'Damage' in a: ks.add('D')
            elif k.startswith('TriggerRegisterTimerExpireEvent'): ks.add('T')
            elif k in ('TriggerRegisterTimerEventPeriodic', 'TriggerRegisterTimerEventSingle'): ks.add('P')
            elif 'VariableEvent' in k: ks.add('V')
            else: ks.add('E')
        if not ks and t in ('Damage_Modifiers',) or (not ks and 'Damage' in t): ks.add('D')
        return ks
    loopset = set(LOOP_TRIGGERS)
    bound_fns = set(); kinds = collections.Counter()
    for t, rr in sorted(regs.items()):
        if t in loopset: continue
        ks = kind_of(t); kinds[''.join(sorted(ks)) or '-'] += 1
        if not ks or ks <= {'P', 'V'}: continue
        for _, f, _ in rr:
            if f not in F or EXCL(f) or f in bound_fns: continue
            cs = sorted(reach[f])
            if not cs: continue
            lines = []
            for c in cs:
                if 'D' in ks: lines.append('call HP_EvD_%s()' % c)
                if 'E' in ks: lines.append('call HP_EvE_%s()' % c)
                if 'T' in ks and ptimers[c]: lines.append('call HP_EvT_%s(GetExpiredTimer())' % c)
            if not lines: continue
            before[first_stmt(f)] += ['if udg_HP_Dup then'] + lines + ['endif']
            bound_fns.add(f); stats['bind_fn'] += 1; stats['bind_call'] += len(lines)
    # waits
    for n, (s, e) in F.items():
        if EXCL(n) or not reach[n]: continue
        wl = [i for i in range(s + 1, e) if WAIT_RX.match(out[i])]
        if not wl: continue
        cs = sorted(reach[n]); fsi = first_stmt(n)
        after[fsi - 1] += ['local unit hp_w%d' % CI[c] for c in cs]
        for i in wl:
            before[i] += ['set hp_w%d=udg_Hero_%s' % (CI[c], c) for c in cs]
            after[i] += ['call HP_Bind_%s(hp_w%d)' % (c, CI[c]) for c in cs]
        stats['wait_fn'] += 1; stats['wait'] += len(wl)
    # loop wrappers
    wrappers = {}
    for t in LOOP_TRIGGERS:
        ks = kind_of(t); cs = trigcls.get(t, set())
        if ks != {'P'} or len(cs) != 1: die('loop trigger %s kind=%s cls=%s' % (t, ks, cs))
        c = next(iter(cs)); rr = regs[t]
        cond = [f for k, f, _ in rr if k == 'Condition']; act = [f for k, f, _ in rr if k == 'Action']
        if len(act) != 1 or len(cond) > 1: die('loop trigger %s regs %s' % (t, rr))
        a = act[0]; cn = cond[0] if cond else None
        if any(WAIT_RX.match(x) for x in out[F[a][0]:F[a][1]]): die('wait in loop trigger ' + t)
        call = ('if %s() then' % cn, 'call %s()' % a, 'endif') if cn else ('call %s()' % a,)
        ci = CI[c]
        w = ['function HP_Loop_%s takes nothing returns nothing' % t, 'local integer k=1',
             'local unit u=udg_Hero_%s' % c,
             'if udg_HP_Cnt[%d]<2 then' % ci] + list(call) + ['set u=null', 'return', 'endif',
             'loop', 'exitwhen k>udg_HP_Cnt[%d]' % ci, 'call HP_Bind_%s(udg_HP_I[%d+k])' % (c, ci * MAXINST)] + \
            list(call) + ['set k=k+1', 'endloop', 'call HP_Bind_%s(u)' % c, 'set u=null', 'endfunction']
        endi = max(F[a][1], F[cn][1] if cn else 0)
        after[endi] += w
        for k, f, i in rr:
            if k == 'Condition': out[i] = ''
            else: out[i] = 'call TriggerAddAction(gg_trg_%s,function HP_Loop_%s)' % (t, t)
        stats['loop'] += 1

    # ---- 4. helpers + globals
    G = ['boolean udg_HP_Dup=false', 'unit array udg_HP_I', 'integer array udg_HP_Cnt', 'integer array udg_HP_Cur']
    H = []
    nswap = 0
    for c in CL:
        ci = CI[c]; base = ci * MAXINST; hv = 'udg_Hero_' + c
        sv, ld = [], []
        for g, typ, M in priv[c]:
            G.append('%s array udg_HPS_%s' % (typ, g[4:]))
            if M == 0:
                sv.append('set udg_HPS_%s[k]=%s' % (g[4:], g)); ld.append('set %s=udg_HPS_%s[k]' % (g, g[4:]))
            else:
                for x in range(M):
                    sv.append('set udg_HPS_%s[k*%d+%d]=%s[%d]' % (g[4:], M, x, g, x))
                    ld.append('set %s[%d]=udg_HPS_%s[k*%d+%d]' % (g, x, g[4:], M, x))
            nswap += 1
        H += ['function HP_Save_%s takes integer k returns nothing' % c] + sv + ['endfunction']
        H += ['function HP_Load_%s takes integer k returns nothing' % c] + ld + ['endfunction']
        H += ['function HP_Bind_%s takes unit u returns nothing' % c, 'local integer k=1',
              'if u==null or u==%s or udg_HP_Cnt[%d]<2 then' % (hv, ci), 'return', 'endif',
              'loop', 'exitwhen k>udg_HP_Cnt[%d]' % ci, 'if udg_HP_I[%d+k]==u then' % base,
              'call HP_Save_%s(udg_HP_Cur[%d])' % (c, ci), 'call HP_Load_%s(k)' % c,
              'set udg_HP_Cur[%d]=k' % ci, 'set %s=u' % hv, 'return', 'endif', 'set k=k+1', 'endloop', 'endfunction']
        H += ['function HP_Is_%s takes unit u returns boolean' % c, 'local integer k=1',
              'if u==%s then' % hv, 'return true', 'endif',
              'if u==null or udg_HP_Cnt[%d]<2 then' % ci, 'return false', 'endif',
              'loop', 'exitwhen k>udg_HP_Cnt[%d]' % ci, 'if udg_HP_I[%d+k]==u then' % base,
              'call HP_Bind_%s(u)' % c, 'return true', 'endif', 'set k=k+1', 'endloop', 'return false', 'endfunction']
        H += ['function HP_BindP_%s takes player p returns boolean' % c, 'local integer k=1',
              'if p==null or udg_HP_Cnt[%d]<2 then' % ci, 'return false', 'endif',
              'if GetOwningPlayer(%s)==p then' % hv, 'return true', 'endif',
              'loop', 'exitwhen k>udg_HP_Cnt[%d]' % ci, 'if GetOwningPlayer(udg_HP_I[%d+k])==p then' % base,
              'call HP_Bind_%s(udg_HP_I[%d+k])' % (c, base), 'return true', 'endif', 'set k=k+1', 'endloop',
              'return false', 'endfunction']
        H += ['function HP_OwnIs_%s takes player p returns boolean' % c,
              'if GetOwningPlayer(%s)==p then' % hv, 'return true', 'endif',
              'return HP_BindP_%s(p)' % c, 'endfunction']
        H += ['function HP_EvE_%s takes nothing returns nothing' % c,
              'if udg_HP_Cnt[%d]<2 then' % ci, 'return', 'endif']
        for u in ('GetTriggerUnit()', 'GetSpellTargetUnit()', 'GetKillingUnit()', 'GetAttacker()',
                  'GetSummoningUnit()', 'GetEventTargetUnit()', 'GetOrderTargetUnit()'):
            H += ['if HP_Is_%s(%s) then' % (c, u), 'return', 'endif']
        H += ['if HP_BindP_%s(GetTriggerPlayer()) then' % c, 'return', 'endif',
              'if GetKillingUnit()!=null then', 'call HP_BindP_%s(GetOwningPlayer(GetKillingUnit()))' % c, 'endif',
              'endfunction']
        H += ['function HP_EvD_%s takes nothing returns nothing' % c,
              'if udg_HP_Cnt[%d]<2 then' % ci, 'return', 'endif',
              'if HP_Is_%s(udg_DamageEventSource) then' % c, 'return', 'endif',
              'if HP_Is_%s(udg_DamageEventTarget) then' % c, 'return', 'endif',
              'if udg_DamageEventSource!=null then',
              'if HP_BindP_%s(GetOwningPlayer(udg_DamageEventSource)) then' % c, 'return', 'endif', 'endif',
              'if udg_DamageEventTarget!=null then',
              'call HP_BindP_%s(GetOwningPlayer(udg_DamageEventTarget))' % c, 'endif', 'endfunction']
        if ptimers[c]:
            H += ['function HP_EvT_%s takes timer t returns nothing' % c, 'local integer k=1',
                  'if t==null or udg_HP_Cnt[%d]<2 then' % ci, 'return', 'endif',
                  'loop', 'exitwhen k>udg_HP_Cnt[%d]' % ci, 'if k==udg_HP_Cur[%d] then' % ci,
                  'if ' + ' or '.join('%s==t' % g for g in ptimers[c]) + ' then', 'return', 'endif',
                  'elseif ' + ' or '.join('udg_HPS_%s[k]==t' % g[4:] for g in ptimers[c]) + ' then',
                  'call HP_Bind_%s(udg_HP_I[%d+k])' % (c, base), 'return', 'endif',
                  'set k=k+1', 'endloop', 'endfunction']
        fr = []
        for g in ptimers[c]:
            if g in fresh:
                fr.append('set %s=CreateTimer()' % g)
                fr += ['call TriggerRegisterTimerExpireEvent(gg_trg_%s,%s)' % (t, g) for t in fresh[g]]
        H += ['function HP_New_%s takes unit u returns nothing' % c, 'local integer k',
              'if udg_HP_Cnt[%d]==0 then' % ci, 'call HP_Save_%s(0)' % c, 'else',
              'call HP_Save_%s(udg_HP_Cur[%d])' % (c, ci), 'call HP_Load_%s(0)' % c] + fr + \
             ['set udg_HP_Dup=true', 'endif', 'set udg_HP_Cnt[%d]=udg_HP_Cnt[%d]+1' % (ci, ci),
              'set k=udg_HP_Cnt[%d]' % ci, 'set udg_HP_I[%d+k]=u' % base, 'set udg_HP_Cur[%d]=k' % ci,
              'set %s=u' % hv, 'endfunction']
        H += ['function HP_Replace_%s takes unit u returns nothing' % c,
              'if udg_HP_Cnt[%d]>0 then' % ci, 'set udg_HP_I[%d+udg_HP_Cur[%d]]=u' % (base, ci), 'endif',
              'set %s=u' % hv, 'endfunction']
        stats['fresh_timers'] += sum(1 for g in ptimers[c] if g in fresh)

    # assemble
    res = []
    first_fn = next(i for i in range(ge, len(out)) if out[i].startswith('function '))
    for i, l in enumerate(out):
        if i == ge: res += G
        if i == first_fn: res += H
        res += before.get(i, [])
        if l != '' or i >= len(L) - 1 or L[i] == '':
            res.append(l)
        res += after.get(i, [])
    open(dst, 'wb').write(nl.join(res).encode('latin-1'))
    leftover = sum(len(re.findall(r'(==|!=)udg_Hero_(\w+)\b(?![\[\w])|udg_Hero_\w+(==|!=)', l))
                   for n, (s, e) in F.items() if not EXCL(n) for l in out[s:e])
    print('classes', len(CL), 'private vars', nswap, 'per class', {c: len(priv[c]) for c in CL})
    print('rejected', dict(rej))
    print('stats', dict(stats))
    print('trigger kinds', dict(kinds))
    print('unrewritten hero comparisons (null/filter/enum/string)', leftover)
    print('wrote', dst, len(res), 'lines')


if __name__ == '__main__':
    if len(sys.argv) != 3: die('usage: patch_all_pick_v2.py <all_pick.j> <out.j>')
    main(sys.argv[1], sys.argv[2])
