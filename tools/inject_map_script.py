#!/usr/bin/env python3
"""Replace the (unnamed, encrypted) war3map.j inside the Sunken City .w3x.

The script block is located the same way as sunken_sim.library._extract_script.
The new script is zlib-compressed into sectors, encrypted with the same file key
(no FIX_KEY flag in this map), appended to the archive, and the block-table entry
is repointed. Hash table / file names are untouched.

usage: inject_map_script.py <in.w3x> <war3map.j> <out.w3x>
"""
import struct, sys, zlib, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sunken_sim import library as lb

CT = lb.CT


def encrypt(plain: bytes, key: int) -> bytes:
    seed = 0xEEEEEEEE
    key &= 0xFFFFFFFF
    out = bytearray()
    n = len(plain) // 4
    for i in range(n):
        seed = (seed + CT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        v = struct.unpack_from('<I', plain, i * 4)[0]
        out += struct.pack('<I', (v ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF)
        key = (((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (v + seed + ((seed << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    out += plain[n * 4:]
    return bytes(out)


def find_script_block(data):
    sector_size, entries, blocks = lb._archive_tables(data)
    seen = set(); cands = []
    for _a, _b, _l, _p, bi in entries:
        if bi in (0xFFFFFFFF, 0xFFFFFFFE) or bi in seen:
            continue
        seen.add(bi)
        pos, comp, size, flags = struct.unpack_from('<IIII', blocks, bi * 16)
        if size < 1000 or not (flags & 0x200):
            continue
        cands.append((size, pos, comp, flags, bi))
    cands.sort(reverse=True)
    for size, pos, comp, flags, bi in cands:
        sectors = (size + sector_size - 1) // sector_size
        tk = lb._table_key(struct.unpack_from('<I', data, pos)[0], (sectors + 1) * 4)
        if tk is None:
            continue
        key = (tk + 1) & 0xFFFFFFFF
        try:
            head = lb._decode_block(data, sector_size, pos, comp, size, flags, key, 32).lstrip(b'\xef\xbb\xbf')
        except Exception:
            continue
        if head.startswith((b'globals', b'function', b'//')):
            return sector_size, blocks, bi, flags, key
    raise SystemExit('script block not found')


def main(src, script, dst):
    data = bytearray(open(src, 'rb').read())
    assert data[:4] == b'MPQ\x1a', 'MPQ header must be at offset 0 for this map'
    sector_size, blocks, bi, flags, key = find_script_block(bytes(data))
    if flags & 0x00020000:
        raise SystemExit('FIX_KEY flag set: not supported')
    body = open(script, 'rb').read()
    n = (len(body) + sector_size - 1) // sector_size
    table_bytes = (n + 1) * 4
    chunks = []
    for i in range(n):
        raw = body[i * sector_size:(i + 1) * sector_size]
        c = b'\x02' + zlib.compress(raw, 9)
        if len(c) >= len(raw):
            c = raw
        chunks.append(encrypt(c, key + i) if flags & 0x10000 else c)
    offs = [table_bytes]
    for c in chunks:
        offs.append(offs[-1] + len(c))
    table = struct.pack('<' + 'I' * (n + 1), *offs)
    if flags & 0x10000:
        table = encrypt(table, key - 1)
    blob = table + b''.join(chunks)
    new_pos = len(data)
    data += blob
    blocks = bytearray(blocks)
    struct.pack_into('<III', blocks, bi * 16, new_pos, len(blob), len(body))
    hash_off, block_off, hash_n, block_n = struct.unpack_from('<IIII', data, 16)
    data[block_off:block_off + block_n * 16] = encrypt(bytes(blocks), lb._hash_string('(block table)', 3))
    struct.pack_into('<I', data, 8, len(data))  # archive size
    open(dst, 'wb').write(data)
    # verify
    out = lb._extract_script(type('P', (), {'__fspath__': lambda s: dst, '__str__': lambda s: dst})())
    assert out == body, 'verification failed'
    print('ok: block', bi, 'pos', new_pos, 'comp', len(blob), 'size', len(body))


if __name__ == '__main__':
    main(*sys.argv[1:4])
