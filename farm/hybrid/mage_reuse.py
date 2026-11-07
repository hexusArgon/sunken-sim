"""Engine-local bounded Mage tape LRU. All state stats retained except proven potency.

No disk cache / cross-job singleton. Blazing Soul's derived bomb_period remains
in the key, so potency is NOT reusable when it changes cadence. Events immutable.
"""
from collections import OrderedDict,Counter
from types import MappingProxyType
import math,os,hashlib,inspect,re,functools
from pathlib import Path
from types import CodeType

VERIFIED_SOURCES = {'sunken_sim.mage': '627496ad2f6f9549ff61c0152f21d32205bde1d4f4e0457199130684d22e5e65', 'sunken_sim.shadow': 'cc655a33d29dc37ec421ee55ab2bf5472d2389c34952072973db606aa2cbad48', 'sunken_sim.pressure': '05960bd54bda601731bcd0e3102910496a1193b1ceefd9bdf2359340995b27a3', 'farm.hybrid.mage_gpu_timeline': 'cf080f6e4d3bd150d7e55d9f1b98a1ad49ce06cae800b338bda865b11140a61e'}


def freeze(value):
    if isinstance(value,dict):return tuple(sorted((k,freeze(v)) for k,v in value.items()))
    if isinstance(value,(list,tuple)):return tuple(freeze(v) for v in value)
    if isinstance(value,(set,frozenset)):return tuple(sorted(freeze(v) for v in value))
    if isinstance(value,float) and math.isnan(value):raise ValueError('NaN cache key')
    hash(value);return value


def code_token(code):
    return (code.co_code,code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,
            code.co_argcount,code.co_kwonlyargcount,code.co_flags,
            tuple(code_token(x) if isinstance(x,CodeType) else x for x in code.co_consts))


def verified(modules,sources):
    """Only the reviewed source/callable bodies may omit potency from keys.

    Compile without executing. Detect monkeypatch wrappers, even when the file
    remains unchanged. Future game/scheduler changes fail closed (fresh tapes).
    """
    for module,source in zip(modules,sources):
        if hashlib.sha256(source.encode()).hexdigest()!=VERIFIED_SOURCES.get(module.__name__):return False
        try:
            expected=compile(source,module.__file__,'exec',dont_inherit=True)
            for code in expected.co_consts:
                if not isinstance(code,CodeType) or code.co_name.startswith("<"):continue
                fn=getattr(module,code.co_name,None)
                # Only the standard pure memoizer may be unwrapped. A function
                # carrying functools.wraps metadata is still unknown executable code.
                while isinstance(fn,functools._lru_cache_wrapper):fn=fn.__wrapped__
                if inspect.isclass(fn):continue
                if not hasattr(fn,'__code__') or fn.__globals__ is not vars(module) or code_token(fn.__code__)!=code_token(code):return False
        except (TypeError,ValueError):return False
    return True


def constants(module):
    values=[]
    for k,v in vars(module).items():
        if not k.isupper() or k.endswith(('CACHE','COUNTS')):continue
        if isinstance(v,re.Pattern):values.append((k,(v.pattern,v.flags)))
        elif isinstance(v,(str,int,float,bool,tuple,list,dict,set,frozenset)):
            try:values.append((k,freeze(v)))
            except (TypeError,ValueError):values.append((k,repr(v)))
    return tuple(sorted(values))


class TapeLRU:
    def __init__(self,max_entries=128,max_bytes=32*1024*1024):
        self.entries=OrderedDict();self.bytes=0;self.max_entries=max_entries;self.max_bytes=max_bytes
        self.counts=Counter();self.context=None;self.pid=os.getpid()
    def clear(self):
        self.entries.clear();self.bytes=0
        self.counts["resident_bytes"]=self.counts["resident_entries"]=0
    def sync_context(self,spec,targets):
        from sunken_sim import mage,shadow,pressure
        from farm.hybrid import mage_gpu_timeline as mt
        modules=(mage,shadow,pressure,mt)
        try:
            sources=[Path(m.__file__).read_text(encoding='utf8') for m in modules]
        except (OSError,UnicodeError):
            self.clear();self.context=None;self.split=False
            self.counts['source_unavailable']+=1
            return
        ctx=(os.getpid(),spec,targets,tuple((id(m),tuple(sorted((k,id(v)) for k,v in vars(m).items() if callable(v))),constants(m),hashlib.sha256(src.encode()).hexdigest()) for m,src in zip(modules,sources)))
        if ctx!=self.context:
            self.clear();self.context=ctx;self.counts['invalidations']+=1
            self.split=verified(modules,sources)

    def key(self,build,stats,bound):
        attrs={k:v for k,v in stats.items() if k!='potency' or not self.split}
        return (freeze(build.talents),freeze(build.glyphs),tuple(freeze(vars(i)) for i in build.items),bound,freeze(attrs))
    def rows(self,builds,spec,targets,keys,generate):
        from sunken_sim import mage
        self.sync_context(spec,targets)
        if len(builds)!=len(keys):raise ValueError("bound_keys length mismatch")
        fresh=[];cachekeys=[];unique={};rows=[None]*len(builds)
        for i,(build,bound) in enumerate(zip(builds,keys)):
            stats=dict(mage.sheet(build))
            if spec=='fire':stats['swing']=stats['attack_base']
            fresh.append(stats)
            try:
                key=self.key(build,stats,bound) if self.split else ("unverified",object())
                if not self.split:self.counts["unverified_rows"]+=1
            except (ValueError,TypeError):key=('uncacheable',object());self.counts['uncacheable']+=1
            cachekeys.append(key)
            found=self.entries.get(key)
            if found is not None:
                self.entries.move_to_end(key);rows[i]=(found[0],stats,spec,found[1]);self.counts['hits']+=1
            elif key in unique:self.counts['clustered_rows']+=1
            else:unique[key]=i;self.counts['misses']+=1
        missing=list(unique.values())
        generated=generate([builds[i] for i in missing],[keys[i] for i in missing],[fresh[i] for i in missing]) if missing else []
        if len(generated)!=len(missing):raise ValueError("generator row count mismatch")
        produced={}
        for i,row in zip(missing,generated):
            events,stats,used_spec,evo=row
            immutable=tuple(tuple(ev[:5])+(MappingProxyType(dict(ev[5])),) for ev in events)
            key=cachekeys[i];size=512*len(immutable)+8*len(repr(key))+256
            produced[key]=(immutable,evo)
            if self.split and size<=self.max_bytes and self.max_entries>0:
                while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
                    _,old=self.entries.popitem(last=False);self.bytes-=old[2];self.counts['evictions']+=1
                self.entries[key]=(immutable,evo,size);self.bytes+=size
                self.counts['stores']+=1
            elif not self.split:self.counts['uncached_unverified']+=1
            else:self.counts['oversized']+=1
        for i,row in enumerate(rows):
            if row is None:
                ev,evo=produced[cachekeys[i]];rows[i]=(ev,fresh[i],spec,evo)
        self.counts['requested_rows']+=len(builds);self.counts['generated_rows']+=len(missing)
        self.counts['resident_bytes']=self.bytes;self.counts['resident_entries']=len(self.entries)
        return rows
