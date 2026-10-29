import re
ATTRS=[(1,'Agi','AGI'),(2,'Str','STR'),(3,'Int','INT')]
def funcs(lines):
    """name -> (start,end) line idx (end = endfunction idx)"""
    out={};cur=None
    for i,l in enumerate(lines):
        if l.startswith('function '):
            cur=l.split()[1];st=i
        elif l=='endfunction' and cur:
            out[cur]=(st,i);cur=None
    return out
def class_maps(lines,F):
    type2cls={};item2cls={};spec2cls={};cls2attr={}
    for n,a,A in ATTRS:
        s,e=F['Trig_Select_%s_Hero_Actions'%a]
        pend=None;cls=None
        for l in lines[s:e]:
            m=re.match(r"if\((Trig_Select_%s_Hero_\w+)\(\)\)then"%a,l)
            if m and m.group(1) in F:
                cs,ce=F[m.group(1)]
                t=re.findall(r"GetUnitTypeId\(GetSoldUnit\(\)\)==('\w{4}')","\n".join(lines[cs:ce]))
                if t: pend=t
            m=re.match(r"set udg_Hero_(\w+)=GetSoldUnit\(\)",l)
            if m:
                cls=m.group(1);cls2attr[cls]=n
                for t in (pend or []): type2cls[t]=cls
                pend=None
            if cls:
                m=re.match(r"set udg_Talents_%s\[\d+\]=('\w{4}')"%a,l)
                if m: item2cls[m.group(1)]=cls
                m=re.match(r"call UnitAddAbilityBJ\(('\w{4}'),udg_Glyphs_Unit\[%d\]\)"%n,l)
                if m: spec2cls.setdefault(m.group(1),set()).add(cls)
    return type2cls,item2cls,spec2cls,cls2attr
if __name__=='__main__':
    L=open('/workspace/war3map.j',encoding='latin-1').read().split('\n')
    L=[x.rstrip('\r') for x in L]
    F=funcs(L)
    t,i,s,c=class_maps(L,F)
    print(t);print(c);print(s);print(len(i),i.get("'I0RU'"),i.get("'I0QK'"))
