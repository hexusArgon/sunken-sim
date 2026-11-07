"""Engine-owned exact sheet / ordered-item passive LRU (no ESC algebra).

Never reorders floating additions. Item regex parsing is shared across talent,
glyph and ESC variants; full sheets require *all* Build fields and item values.
"""
from collections import OrderedDict, Counter
import copy,sys
from farm.hybrid.mage_reuse import freeze

def deep_size(value, seen=None):
    if seen is None: seen=set()
    if id(value) in seen:return 0
    seen.add(id(value));size=sys.getsizeof(value)
    if isinstance(value,dict):size+=sum(deep_size(k,seen)+deep_size(v,seen) for k,v in value.items())
    elif isinstance(value,(tuple,list,set,frozenset)):size+=sum(deep_size(v,seen) for v in value)
    return size

class SheetLRU:
    def __init__(self,max_entries=512,max_bytes=8*1024*1024):
        self.max_entries=max_entries;self.max_bytes=max_bytes
        self.entries=OrderedDict();self.bytes=0;self.context=None;self.counts=Counter()
    def clear(self):
        self.entries.clear();self.bytes=0
        self.counts['resident_bytes']=self.counts['resident_entries']=0
    def _get(self,key):
        row=self.entries.get(key)
        if row is not None:
            self.entries.move_to_end(key);self.counts[key[0]+'_hits']+=1
            return copy.deepcopy(row[0])
        self.counts[key[0]+'_misses']+=1
    def _put(self,key,value):
        size=deep_size((key,value))+256
        if size>self.max_bytes or self.max_entries<=0:
            self.counts['oversized']+=1;return
        while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
            _,old=self.entries.popitem(last=False);self.bytes-=old[1];self.counts['evictions']+=1
        self.entries[key]=(copy.deepcopy(value),size);self.bytes+=size
        self.counts['resident_bytes']=self.bytes;self.counts['resident_entries']=len(self.entries)
    def rows(self,builds,guard,spec,targets):
        from sunken_sim import mage,shadow,stacking
        guard.sync_context(spec,targets)
        # The stacking profile is a mutable map-derived configuration, not a
        # source constant. Include its complete current value, not object id.
        context=(guard.context,freeze(stacking.stack_profiles()))
        if context!=self.context:
            self.clear();self.context=context;self.counts['invalidations']+=1
        if not guard.split:
            self.counts['unverified_rows']+=len(builds)
            return [dict(mage.sheet(b)) for b in builds]
        import os
        full = os.environ.get("FARM_FIRE_PREP_CACHE", "items") == "full"
        out=[]
        for b in builds:
            items=tuple(tuple(vars(i).items()) for i in b.items)
            key=('sheet',(freeze({k:v for k,v in vars(b).items() if k!='items'}),items))
            st=self._get(key) if full else None
            if st is None:
                pkey=('passive',items);passive=self._get(pkey)
                if passive is None:
                    passive=shadow._passive_mana(b.items);self._put(pkey,passive)
                st=mage.sheet(b,_mana_passives=passive)
                if full:self._put(key,st)
            out.append(st)
        return out


def fresh_rows(builds, guard, spec, targets):
    """One passive parse per sheet; share repeated ring-row inputs only in this call.

    No retained cache, no reordering of float additions, all outputs are copies.
    Unknown source/callable bodies use the public sheet normally instead.
    """
    from sunken_sim import mage, shadow
    guard.sync_context(spec,targets)
    memo={};out=[]
    for b in builds:
        ident=id(b)
        if ident not in memo:
            memo[ident]=mage.sheet(b,_mana_passives=shadow._passive_mana(b.items)) if guard.split else mage.sheet(b)
        out.append(copy.deepcopy(memo[ident]))
    return out
