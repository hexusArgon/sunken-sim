"""Usage: python corpus.py && python apply.py ../../sources/*.tsx  (re-colors plain tip strings in place; text unchanged)."""
import json,re,sys
sys.path.insert(0,__import__('os').path.dirname(__file__))
from recolor import recolor
STR=re.compile(r'"((?:[^"\\\n]|\\.)*)"')
def looks_tip(s): return ('\n' in s or (len(s)>=40 and ' ' in s))
for f in sys.argv[1:]:
    src=open(f,encoding='utf-8').read()
    stats={'cand':0,'col':0}; nocol=[]
    def rep(m):
        try: s=json.loads(m.group(0))
        except Exception: return m.group(0)
        if not isinstance(s,str) or not looks_tip(s): return m.group(0)
        stats['cand']+=1
        r=recolor(s)
        if r==s: nocol.append(s[:70]); return m.group(0)
        stats['col']+=1
        return json.dumps(r,ensure_ascii=False)
    out=STR.sub(rep,src)
    open(f,'w',encoding='utf-8').write(out)
    print(f,stats)
