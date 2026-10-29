#!/usr/bin/env python3
"""Set war3map.wts STRING 1 (lobby map name) and write out.w3x under that name.

usage: set_map_lobby_name.py <in.w3x> "Sunken City v2.5.2A All Pick" [out.w3x]
"""
import re, struct, sys, zlib, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sunken_sim import library as lb
from pathlib import Path

def encrypt(plain: bytes, key: int) -> bytes:
    seed = 0xEEEEEEEE
    key &= 0xFFFFFFFF
    out = bytearray()
    n = len(plain) // 4
    for i in range(n):
        seed = (seed + lb.CT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        v = struct.unpack_from('<I', plain, i * 4)[0]
        out += struct.pack('<I', (v ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF)
        key = (((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (v + seed + ((seed << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    out += plain[n * 4:]
    return bytes(out)

def main(src, new_name, dst=None):
    src, new_name = Path(src), new_name
    dst = Path(dst) if dst else src.parent / f'{new_name}.w3x'
    wts = lb._extract(src, 'war3map.wts').decode('utf-8')
    pat = re.compile(r'(STRING\s+1\s*\n\{\s*\n)(.*?)(\n\})', re.S)
    m = pat.search(wts)
    if not m:
        raise SystemExit('STRING 1 not found')
    old = m.group(2)
    new_body = new_name + ('\r' if old.endswith('\r') else '')
    wts2, n = pat.subn(lambda mo: mo.group(1) + new_body + mo.group(3), wts, count=1)
    assert n == 1
    body = wts2.encode('utf-8')
    data = bytearray(src.read_bytes())
    assert data[:4] == b'MPQ\x1a'
    sector_size, entries, blocks = lb._archive_tables(bytes(data))
    hash_n = len(entries)
    name = 'war3map.wts'
    slot = lb._hash_string(name, 0) % hash_n
    name_a, name_b = lb._hash_string(name, 1), lb._hash_string(name, 2)
    found = None
    for _ in range(hash_n):
        ha, hb, loc, plat, bi = entries[slot]
        if bi == 0xFFFFFFFF:
            break
        if ha == name_a and hb == name_b and bi != 0xFFFFFFFE:
            found = bi
            break
        slot = (slot + 1) % hash_n
    if found is None:
        raise SystemExit('war3map.wts not found')
    file_pos, comp_size, file_size, flags = struct.unpack_from('<IIII', blocks, found * 16)
    if flags & 0x00020000:
        raise SystemExit('FIX_KEY not supported')
    key = lb._hash_string(name, 3)
    n_sec = (len(body) + sector_size - 1) // sector_size
    table_bytes = (n_sec + 1) * 4
    chunks = []
    for i in range(n_sec):
        raw = body[i * sector_size:(i + 1) * sector_size]
        c = b'\x02' + zlib.compress(raw, 9)
        if len(c) >= len(raw):
            c = raw
        chunks.append(encrypt(c, key + i) if flags & 0x10000 else c)
    offs = [table_bytes]
    for c in chunks:
        offs.append(offs[-1] + len(c))
    table = struct.pack('<' + 'I' * (n_sec + 1), *offs)
    if flags & 0x10000:
        table = encrypt(table, key - 1)
    blob = table + b''.join(chunks)
    new_pos = len(data)
    data += blob
    blocks = bytearray(blocks)
    struct.pack_into('<III', blocks, found * 16, new_pos, len(blob), len(body))
    hash_off, block_off, hash_cnt, block_cnt = struct.unpack_from('<IIII', data, 16)
    data[block_off:block_off + block_cnt * 16] = encrypt(bytes(blocks), lb._hash_string('(block table)', 3))
    struct.pack_into('<I', data, 8, len(data))
    dst.write_bytes(data)
    got = lb._extract(dst, 'war3map.wts').decode('utf-8')
    assert pat.search(got).group(2) == new_body
    print('ok:', dst, 'STRING 1 =', repr(new_body))

if __name__ == '__main__':
    main(*sys.argv[1:4] if len(sys.argv) > 3 else sys.argv[1:3])
