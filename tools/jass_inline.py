"""Print a JASS trigger action function with its condition functions inlined.
usage: inline.py war3map_norm.j FunctionName"""
import re,sys
src=open(sys.argv[1],encoding='utf-8',errors='replace').read().split('\n')
funcs={};cur=None;body=[]
for line in src:
    m=re.match(r'function (\w+) takes',line)
    if m: cur=m.group(1); body=[]; continue
    if line.startswith('endfunction') and cur: funcs[cur]=body; cur=None; continue
    if cur: body.append(line)
def cond(name):
    b=funcs.get(name,[]); out=[]
    for l in b:
        m=re.match(r'if\(not\((.*)\)\)then$',l)
        if m: out.append(m.group(1)); continue
        m=re.match(r'if\((.*)\)then$',l)
        if m: out.append('OR '+m.group(1)); continue
        m=re.match(r'if not (\w+)\(\) then',l) or re.match(r'if\(not (\w+)\(\)\)then',l)
        if m: out.append('['+' & '.join(cond(m.group(1)))+']'); continue
    return [re.sub(r'(\w+C)\(\)',lambda mm:'('+' & '.join(cond(mm.group(1)))+')',c) for c in out]
def show(name,depth=0):
    ind='  '*depth
    for l in funcs.get(name,[]):
        m=re.match(r'if\((\w+C)\(\)\)then',l) or re.match(r'if\(not\((\w+C)\(\)\)\)then',l)
        if m: print(ind+'IF '+' AND '.join(cond(m.group(1)))); depth+=1; ind='  '*depth; continue
        if l=='else': print('  '*(depth-1)+'ELSE'); continue
        if l=='endif': depth-=1; ind='  '*depth; continue
        m=re.match(r'call ForGroupBJ\(.*function (\w+)\)',l)
        print(ind+l[:220])
        if m and len(sys.argv)>3: show(m.group(1),depth+1)
for n in sys.argv[2:3]: show(n)
