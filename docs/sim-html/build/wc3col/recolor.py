"""Restore WC3 |cAARRGGBB..|r colors onto plain tip text by exact match against raw map strings."""
import json,re,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
CORPUS=json.load(open(HERE/'corpus.json',encoding='utf-8'))
CRE=re.compile(r'\|[cC]([0-9a-fA-F]{8})|\|[rR]|\|n|\r\n|\r')
def model(r):
    s=[];c=[];cur=None;pos=0
    for m in CRE.finditer(r):
        seg=r[pos:m.start()]; s.append(seg); c+= [cur]*len(seg); pos=m.end()
        t=m.group(0)
        if m.group(1): cur=m.group(1)[2:].lower()
        elif t in('|r','|R'): cur=None
        else: s.append('\n'); c.append(cur)
    seg=r[pos:]; s.append(seg); c+=[cur]*len(seg)
    return ''.join(s),c
SRC=[]
for r in CORPUS:
    if '|c' not in r and '|C' not in r: continue
    s,c=model(r)
    if any(c): SRC.append((s,c))
ALLPLAIN=[model(r)[0] for r in CORPUS]
def emit(p,cols):
    out=[];cur=None
    for ch,col in zip(p,cols):
        if ch=='\n':
            # keep color across newline in WC3 (color persists); emit as-is
            pass
        if col!=cur:
            if cur: out.append('|r')
            if col: out.append('|cff'+col)
            cur=col
        out.append(ch)
    if cur: out.append('|r')
    return ''.join(out)
def colors_for(p):
    """return per-char colors for plain p, or None"""
    best=None
    for s,c in SRC:
        i=s.find(p)
        if i>=0:
            cc=c[i:i+len(p)]
            n=sum(1 for x in cc if x)
            if best is None or n>best[0]: best=(n,cc)
    if best: return best[1]
    # per-line fallback
    lines=p.split('\n'); cols=[]; hit=False
    for k,ln in enumerate(lines):
        lc=[None]*len(ln)
        if len(ln.strip())>=4:
            cand=None
            for s,c in SRC:
                i=s.find(ln)
                if i>=0:
                    cc=c[i:i+len(ln)]; n=sum(1 for x in cc if x)
                    # require line-boundary match for short lines
                    if len(ln)<25 and not ((i==0 or s[i-1]=='\n') and (i+len(ln)==len(s) or s[i+len(ln)]=='\n')): continue
                    if cand is None or n>cand[0]: cand=(n,cc)
            if cand and cand[0]: lc=cand[1]; hit=True
        cols+=lc
        if k<len(lines)-1: cols.append(None)
    return cols if hit else None
def recolor(p):
    if '|c' in p: return p
    cols=colors_for(p)
    if not cols or not any(cols): return p
    return emit(p,cols)
