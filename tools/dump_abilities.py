import struct
import zlib
from pathlib import Path

MAP = Path(__file__).resolve().parents[1] / "maps" / "Sunken City v2.5.2a.w3x"


def crypt_table():
    seed = 0x00100001
    tbl = [0] * 0x500
    for i1 in range(0x100):
        i2 = i1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            t1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            t2 = seed & 0xFFFF
            tbl[i2] = (t1 | t2) & 0xFFFFFFFF
            i2 += 0x100
    return tbl


CT = crypt_table()


def hash_string(s, ht):
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in s.replace("/", "\\").upper():
        c = ord(ch)
        seed1 = (CT[(ht << 8) + c] ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (c + seed1 + seed2 + ((seed2 << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
    return seed1


def decrypt_block(raw, key):
    seed = 0xEEEEEEEE
    key &= 0xFFFFFFFF
    n = len(raw) & ~3
    out = bytearray()
    for i in range(0, n, 4):
        seed = (seed + CT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        val = struct.unpack_from("<I", raw, i)[0]
        val = (val ^ ((key + seed) & 0xFFFFFFFF)) & 0xFFFFFFFF
        key = ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) | (key >> 0x0B)
        key &= 0xFFFFFFFF
        seed = (val + seed + ((seed << 5) & 0xFFFFFFFF) + 3) & 0xFFFFFFFF
        out += struct.pack("<I", val)
    out += raw[n:]
    return bytes(out)


class Archive:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        _ver, shift = struct.unpack_from("<HH", self.data, 12)
        hash_off, block_off, hash_n, block_n = struct.unpack_from("<IIII", self.data, 16)
        self.sector_size = 512 << shift
        hraw = decrypt_block(self.data[hash_off : hash_off + hash_n * 16], hash_string("(hash table)", 3))
        braw = decrypt_block(self.data[block_off : block_off + block_n * 16], hash_string("(block table)", 3))
        self.blocks = [struct.unpack_from("<IIII", braw, i * 16) for i in range(block_n)]
        self.hashes = [struct.unpack_from("<IIHHI", hraw, i * 16) for i in range(hash_n)]
        self.hash_n = hash_n

    def find(self, name):
        h0 = hash_string(name, 0) % self.hash_n
        n1, n2 = hash_string(name, 1), hash_string(name, 2)
        i = h0
        for _ in range(self.hash_n):
            a, b, _loc, _plat, bi = self.hashes[i]
            if bi == 0xFFFFFFFF:
                return None
            if a == n1 and b == n2 and bi != 0xFFFFFFFE:
                return bi
            i = (i + 1) % self.hash_n
        return None

    def extract(self, name):
        bi = self.find(name)
        if bi is None:
            raise FileNotFoundError(name)
        fp, cs, fs, fl = self.blocks[bi]
        raw = self.data[fp : fp + cs]
        encrypted = bool(fl & 0x00010000)
        compressed = bool(fl & 0x00000200) or bool(fl & 0x00000100)
        key = hash_string(name, 3)
        if not compressed:
            blob = decrypt_block(raw, key) if encrypted else raw
            return blob[:fs]
        nsectors = (fs + self.sector_size - 1) // self.sector_size
        table_bytes = (nsectors + 1) * 4
        table = decrypt_block(raw[:table_bytes], (key - 1) & 0xFFFFFFFF) if encrypted else raw[:table_bytes]
        offs = list(struct.unpack("<" + "I" * (nsectors + 1), table[:table_bytes]))
        if not (offs and offs[0] == table_bytes and offs[-1] == cs):
            key = hash_string(name.split("\\")[-1], 3)
            table = decrypt_block(raw[:table_bytes], (key - 1) & 0xFFFFFFFF)
            offs = list(struct.unpack("<" + "I" * (nsectors + 1), table[:table_bytes]))
        out = bytearray()
        for s in range(nsectors):
            chunk = raw[offs[s] : offs[s + 1]]
            remain = fs - len(out)
            this_un = min(self.sector_size, remain)
            if encrypted:
                chunk = decrypt_block(chunk, (key + s) & 0xFFFFFFFF)
            if len(chunk) == this_un:
                out += chunk
            else:
                mask = chunk[0]
                if not (mask & 0x02):
                    raise RuntimeError(hex(mask))
                out += zlib.decompress(chunk[1:])
        return bytes(out[:fs])


class R:
    def __init__(self, b):
        self.b = b
        self.o = 0

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.o)[0]
        self.o += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.o)[0]
        self.o += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.b, self.o)[0]
        self.o += 4
        return v

    def cstr(self):
        end = self.b.index(0, self.o)
        raw = self.b[self.o : end]
        self.o = end + 1
        return raw.decode("utf-8", "replace")

    def raw4(self):
        v = self.b[self.o : self.o + 4]
        self.o += 4
        return v


def parse_objs(blob, optional):
    rr = R(blob)
    ver = rr.u32()

    def read_table():
        n = rr.u32()
        objs = []
        for _ in range(n):
            base = rr.raw4().decode("latin1")
            new = rr.raw4().decode("latin1")
            sets = rr.u32() if ver >= 3 else 1
            mods = {}
            for _s in range(sets):
                if ver >= 3:
                    rr.u32()
                nmod = rr.u32()
                for __ in range(nmod):
                    mid = rr.raw4().decode("latin1")
                    vtype = rr.u32()
                    level = dptr = 0
                    if optional:
                        level = rr.u32()
                        dptr = rr.u32()
                    if vtype == 0:
                        val = rr.i32()
                    elif vtype in (1, 2):
                        val = rr.f32()
                    elif vtype == 3:
                        val = rr.cstr()
                    else:
                        raise RuntimeError(f"type {vtype} {mid}")
                    if ver > 0:
                        rr.raw4()
                    mods.setdefault(mid, []).append((level, dptr, val))
            objs.append((base, new, mods))
        return objs

    return ver, read_table(), read_table()


def main():
    ar = Archive(MAP)
    w3a = ar.extract("war3map.w3a")
    _ver, orig, cust = parse_objs(w3a, True)
    by = {new: (base, mods) for base, new, mods in orig + cust}
    want = ["A0GB", "A0GK", "A0MI", "A0GS", "A0JK", "A0NC", "A0GC", "A0GL", "A0MH"]
    for ability_id in want:
        if ability_id not in by:
            print("MISSING", ability_id)
            continue
        base, mods = by[ability_id]
        print("====", ability_id, "base", base, "fields", len(mods))
        for key, values in mods.items():
            shown = []
            for level, data_ptr, val in values[:8]:
                if isinstance(val, str):
                    shown.append(f"L{level}/{data_ptr}:{val[:100]}")
                else:
                    shown.append(f"L{level}/{data_ptr}:{val}")
            print(f"  {key}: {shown}")


if __name__ == "__main__":
    main()
