import sys,re
for fn in sys.argv[1:]:
    stack=[]
    for raw in open(fn):
        ind=(len(raw)-len(raw.lstrip(' ')))//2; l=raw.strip()
        while stack and stack[-1][0]>=ind: stack.pop()
        if l.startswith('IF '): stack.append((ind,l[3:])); continue
        if l=='ELSE':
            if stack and stack[-1][0]==ind: stack[-1]=(ind,'NOT['+stack[-1][1][:60]+']')
            continue
        if re.search(r'DamageEventAmount=|Evasion_HitChance=|DamageEventAmount\)|DamageTypeBlocked|UnitDamageTargetBJ\(DamageEventTarget|UnitDamageTargetBJ\(Hero_',l):
            conds=[c for _,c in stack if c not in('1==1','0==0')]
            print(fn.split('_Actions')[0][5:],'|',' && '.join(c[:170] for c in conds[1:]),'=>',l[:200])
