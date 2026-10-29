#!/usr/bin/env python3
"""Rewrite stock replenish interval (usrg) of the hero units sold by the hero crystals.

usage: patch_w3u_stock.py <in.w3u> <out.w3u> [seconds=1] [ID ...]
Only int mods already present are overwritten in place (file size unchanged).
"""
import struct, sys

HEROES = 'E000 E005 E00A H000 H001 H01H N03T N03Y N04R O000 O005 O009 O00A O00F O00G O00H O00N O00P O00R O00Y U002'.split()

def walk(blob):
    """yield (rawcode, mod_id, type, value_offset)"""
    p = 0
    u32 = lambda: struct.unpack_from('<I', blob, p)[0]
    ver = u32(); p += 4
    for _t in range(2):
        cnt = u32(); p += 4
        for _ in range(cnt):
            base = blob[p:p + 4].decode('latin1'); new = blob[p + 4:p + 8].decode('latin1'); p += 8
            code = new if new.strip('\x00') else base
            sets = 1
            if ver >= 3:
                sets = u32(); p += 4
            for _s in range(sets):
                if ver >= 3: p += 4
                mc = u32(); p += 4
                for _m in range(mc):
                    mid = blob[p:p + 4].decode('latin1'); typ = struct.unpack_from('<I', blob, p + 4)[0]; p += 8
                    off = p
                    if typ in (0, 1, 2): p += 4
                    elif typ == 3: p = blob.index(b'\x00', p) + 1
                    else: raise SystemExit('bad type %d' % typ)
                    if ver > 0: p += 4
                    yield code, mid, typ, off
    if p != len(blob): raise SystemExit('trailing bytes %d' % (len(blob) - p))

def main(src, dst, secs='1', *ids):
    ids = list(ids) or HEROES
    data = bytearray(open(src, 'rb').read())
    hit = {}
    for code, mid, typ, off in list(walk(bytes(data))):
        if code in ids and mid == 'usrg':
            if typ != 0: raise SystemExit('%s usrg not int' % code)
            old = struct.unpack_from('<i', data, off)[0]
            struct.pack_into('<i', data, off, int(secs))
            hit[code] = old
    miss = [i for i in ids if i not in hit]
    if miss: raise SystemExit('usrg mod missing for ' + ' '.join(miss))
    open(dst, 'wb').write(data)
    for c in ids: print(c, 'usrg', hit[c], '->', secs)

if __name__ == '__main__':
    main(*sys.argv[1:])
