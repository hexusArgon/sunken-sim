"""Engine-local bounded Mage tape LRU. All state stats retained except proven potency.

No disk cache / cross-job singleton. Blazing Soul's derived bomb_period remains
in the key, so potency is NOT reusable when it changes cadence. Events immutable.
"""
from collections import OrderedDict,Counter
from types import MappingProxyType
import ast,math,os


def freeze(value):
    if isinstance(value,dict):return tuple(sorted((k,freeze(v)) for k,v in value.items()))
    if isinstance(value,(list,tuple)):return tuple(freeze(v) for v in value)
    if isinstance(value,(set,frozenset)):return tuple(sorted(freeze(v) for v in value))
    if isinstance(value,float) and math.isnan(value):raise ValueError('NaN cache key')
    hash(value);return value


class TapeLRU:
    def __init__(self,max_entries=128,max_bytes=32*1024*1024):
        self.entries=OrderedDict();self.bytes=0;self.max_entries=max_entries;self.max_bytes=max_bytes
        self.counts=Counter();self.context=None;self.pid=os.getpid()
    def clear(self):
        self.entries.clear();self.bytes=0
    def sync_context(self,spec,targets):
        from sunken_sim import mage,shadow,pressure
        from farm.hybrid import mage_gpu_timeline as mt
        modules=(mage,shadow,pressure,mt)
        # Code/monkeypatch/constant and device-policy epoch. Includes cap changes;
        # forced-overflow tests must not retrieve tapes generated under other caps.
        ctx=(os.getpid(),spec,targets,tuple((id(m),tuple(sorted((k,id(v)) for k,v in vars(m).items() if callable(v))),tuple(sorted((k,v) for k,v in vars(m).items() if k.isupper() and isinstance(v,(int,float,str,bool))))) for m in modules))
        if ctx!=self.context:
            self.clear();self.context=ctx;self.counts['invalidations']+=1
            # Fail closed if a future scheduler starts directly consuming potency.
            tree=ast.parse(open(mt.__file__,encoding='utf8').read())
            self.split=not any(isinstance(n,ast.Constant) and n.value=='potency' for n in ast.walk(tree))
    def key(self,build,stats,bound):
        attrs={k:v for k,v in stats.items() if k!='potency' or not self.split}
        return (freeze(build.talents),freeze(build.glyphs),tuple(freeze(vars(i)) for i in build.items),bound,freeze(attrs))
    def rows(self,builds,spec,targets,keys,generate):
        from sunken_sim import mage
        self.sync_context(spec,targets)
        fresh=[];cachekeys=[];unique={};rows=[None]*len(builds)
        for i,(build,bound) in enumerate(zip(builds,keys)):
            stats=dict(mage.sheet(build))
            if spec=='fire':stats['swing']=stats['attack_base']
            fresh.append(stats)
            try:key=self.key(build,stats,bound)
            except (ValueError,TypeError):key=('uncacheable',object());self.counts['uncacheable']+=1
            cachekeys.append(key)
            found=self.entries.get(key)
            if found is not None:
                self.entries.move_to_end(key);rows[i]=(found[0],stats,spec,found[1]);self.counts['hits']+=1
            elif key in unique:self.counts['clustered_rows']+=1
            else:unique[key]=i;self.counts['misses']+=1
        missing=list(unique.values())
        generated=generate([builds[i] for i in missing],[keys[i] for i in missing],[fresh[i] for i in missing]) if missing else []
        produced={}
        for i,row in zip(missing,generated):
            events,stats,used_spec,evo=row
            immutable=tuple(tuple(ev[:5])+(MappingProxyType(dict(ev[5])),) for ev in events)
            key=cachekeys[i];size=512*len(immutable)+8*len(repr(key))+256
            produced[key]=(immutable,evo)
            if size<=self.max_bytes and self.max_entries>0:
                while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
                    _,old=self.entries.popitem(last=False);self.bytes-=old[2];self.counts['evictions']+=1
                self.entries[key]=(immutable,evo,size);self.bytes+=size
                self.counts['stores']+=1
            else:self.counts['oversized']+=1
        for i,row in enumerate(rows):
            if row is None:
                ev,evo=produced[cachekeys[i]];rows[i]=(ev,fresh[i],spec,evo)
        self.counts['requested_rows']+=len(builds);self.counts['generated_rows']+=len(missing)
        self.counts['resident_bytes']=self.bytes;self.counts['resident_entries']=len(self.entries)
        return rows
