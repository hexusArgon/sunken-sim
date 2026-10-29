#!/usr/bin/env python3
"""Replace one named file inside a w3x (MPQ) by appending a new compressed blob
and repointing its block entry (same method as set_map_lobby_name.py).

usage: mpq_replace_file.py <in.w3x> <archive name> <new file> <out.w3x>
"""
import struct, sys, zlib, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sunken_sim import library as lb
from set_map_lobby_name import encrypt
from pathlib import Path

def replace(data: bytearray, name: str, body: bytes) -> bytearray:
    assert data[:4] == b'MPQ\x1a'
    sector_size, entries, blocks = lb._archive_tables(bytes(data))
    hash_n = len(entries)
    slot = lb._hash_string(name, 0) % hash_n
    na, nb = lb._hash_string(name, 1), lb._hash_string(name, 2)
    found = None
    for _ in range(hash_n):
        ha, hb, loc, plat, bi = entries[slot]
        if bi == 0xFFFFFFFF: break
        if ha == na and hb == nb and bi != 0xFFFFFFFE:
            found = bi; break
        slot = (slot + 1) % hash_n
    if found is None: raise SystemExit(name + ' not found')
    pos, csize, fsize, flags = struct.unpack_from('<IIII', blocks, found * 16)
    if flags & 0x00020000: raise SystemExit('FIX_KEY not supported')
    if flags & 0x01000000: raise SystemExit('single-unit files not supported')
    if not flags & 0x200: raise SystemExit('only zlib-compressed (0x200) entries supported')
    key = lb._hash_string(name.replace('/', '\\').split('\\')[-1], 3)
    n_sec = (len(body) + sector_size - 1) // sector_size
    chunks = []
    for i in range(n_sec):
        raw = body[i * sector_size:(i + 1) * sector_size]
        c = b'\x02' + zlib.compress(raw, 9)
        if len(c) >= len(raw): c = raw
        chunks.append(encrypt(c, key + i) if flags & 0x10000 else c)
    offs = [(n_sec + 1) * 4]
    for c in chunks: offs.append(offs[-1] + len(c))
    table = struct.pack('<' + 'I' * (n_sec + 1), *offs)
    if flags & 0x10000: table = encrypt(table, key - 1)
    blob = table + b''.join(chunks)
    new_pos = len(data)
    data += blob
    blocks = bytearray(blocks)
    struct.pack_into('<IIII', blocks, found * 16, new_pos, len(blob), len(body), flags)
    hash_off, block_off, hash_cnt, block_cnt = struct.unpack_from('<IIII', data, 16)
    data[block_off:block_off + block_cnt * 16] = encrypt(bytes(blocks), lb._hash_string('(block table)', 3))
    struct.pack_into('<I', data, 8, len(data))
    return data

def main(src, name, newfile, dst):
    body = Path(newfile).read_bytes()
    data = replace(bytearray(Path(src).read_bytes()), name, body)
    Path(dst).write_bytes(data)
    got = lb._extract(Path(dst), name)
    assert got == body, 'verify failed'
    print('ok:', dst, name, len(body), 'bytes')

if __name__ == '__main__':
    if len(sys.argv) != 5: raise SystemExit(__doc__)
    main(*sys.argv[1:])
