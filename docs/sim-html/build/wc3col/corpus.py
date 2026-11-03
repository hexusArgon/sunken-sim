"""Collect raw map strings (with |c color codes) from the w3x: wts, object files, war3map.j. Writes corpus.json."""
import sys,re,json,struct
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT))
from sunken_sim import library as L
raw={}
for m in re.finditer(r'STRING (\d+)\s*\n(?://[^\n]*\n)?\{\r?\n(.*?)\r?\n\}', L._map_text("war3map.wts"), re.S):
    raw[int(m.group(1))]=m.group(2)
def res(v):
    m=re.fullmatch(r'TRIGSTR_(\d+)',v or '')
    return raw.get(int(m.group(1)),'') if m else (v or '')
out=set(raw.values())
def parse(blob,opt):
    pos=0
    def rd(fmt,n):
        nonlocal pos; v=struct.unpack_from(fmt,blob,pos)[0]; pos+=n; return v
    def raw4():
        nonlocal pos; v=blob[pos:pos+4]; pos+=4; return v
    def cstr():
        nonlocal pos; e=blob.index(b'\x00',pos); v=blob[pos:e].decode('utf-8','replace'); pos=e+1; return v
    ver=rd('<I',4)
    for _t in range(2):
        cnt=rd('<I',4)
        for _ in range(cnt):
            raw4(); raw4(); sets=rd('<I',4) if ver>=3 else 1
            for _s in range(sets):
                if ver>=3: rd('<I',4)
                mc=rd('<I',4)
                for _m in range(mc):
                    raw4(); vt=rd('<I',4)
                    if opt: rd('<i',4); rd('<i',4)
                    if vt==0: rd('<i',4)
                    elif vt in(1,2): rd('<f',4)
                    elif vt==3: out.add(res(cstr()))
                    else: raise RuntimeError(vt)
                    if ver>0: raw4()
for fn,opt in [('war3map.w3a',1),('war3mapSkin.w3a',1),('war3map.w3t',0),('war3mapSkin.w3t',0),('war3map.w3u',0),('war3mapSkin.w3u',0),('war3map.w3q',1),('war3mapSkin.w3q',1),('war3map.w3h',0),('war3mapSkin.w3h',0)]:
    try: parse(L._extract(L.MAP_PATH,fn),opt); print(fn,'ok',len(out))
    except Exception as e: print(fn,'skip',repr(e)[:80])
try:
    j=L._extract_script(L.MAP_PATH).decode('utf-8','replace')
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"',j):
        s=m.group(1).replace('\\"','"').replace('\\\\','\\')
        if '|c' in s or len(s)>20: out.add(s)
    print('j ok',len(out))
except Exception as e: print('j skip',e)
json.dump(sorted(out),open(HERE/'corpus.json','w'),ensure_ascii=False)
