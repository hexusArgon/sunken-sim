"""Parity of the OpenCL kernels with the Python sims on builds that wear Silent Messenger (I0QN)
and/or take Battle Frenzy (I0GZ).  Usage: python tools/aprocs_parity.py HERO SPEC [N]"""
import random
import sys

from farm.catalog import load
from farm import runner as R
from farm.hybrid import mage_cl
from farm.hybrid.mage_cl import random_builds


def main():
    hero, spec = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    space, items = None, None
    for top in (80, 150, 300):
        space, items = load(hero, spec, "mixed", None, top)
        if "I0QN" in items:
            break
    print("I0QN in catalog:", "I0QN" in items, "top", top)
    sources = R.source_map(items)
    engine = mage_cl.make_engine(hero, space, items, sources, 5, spec)
    mod = sys.modules[type(engine).__module__]
    rng = random.Random(7)
    base = random_builds(space, n * 6, 11)
    out = []
    for chunk, talents, glyphs, points in base:
        codes = space.decode(chunk)[0]
        silent = "I0QN" in codes
        if not silent and rng.random() < 0.7:
            continue
        if "I0GZ" in space.glyphs and rng.random() < 0.75 and "I0GZ" not in glyphs:
            glyphs = tuple(glyphs[:-1]) + ("I0GZ",) if glyphs else ("I0GZ",) + tuple(rng.sample([g for g in space.glyphs if g != "I0GZ"], max(0, space.glyph_picks - 1)))
        out.append((chunk, talents, glyphs, points))
        if len(out) >= n:
            break
    # force some Silent Messenger chunks
    for _ in range(400000):
        if sum("I0QN" in space.decode(b[0])[0] for b in out) >= n // 2 or "I0QN" not in items:
            break
        i = rng.randrange(space.total)
        if "I0QN" in space.decode(i)[0]:
            g = ("I0GZ",) + tuple(rng.sample([x for x in space.glyphs if x != "I0GZ"], max(0, space.glyph_picks - 1)))
            out.append((i, base[len(out) % len(base)][1], g if rng.random() < 0.6 else (), base[len(out) % len(base)][3]))
    nq = sum("I0QN" in space.decode(b[0])[0] for b in out)
    ng = sum("I0GZ" in b[2] for b in out)
    res = mod.parity_full(engine, space, items, 5, out) if hasattr(mod, "parity_full") else None
    print(hero, spec, "builds", len(out), "with I0QN", nq, "with I0GZ", ng, res)


if __name__ == "__main__":
    main()
