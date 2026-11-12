"""Kernel/sim parity with every talent forced in turn: python tools/talent_parity.py HERO SPEC [per_talent]"""
import random
import sys

from farm import runner as R
from farm.catalog import load
from farm.hybrid import mage_cl
from farm.hybrid.mage_cl import random_builds


def main():
    hero, spec = sys.argv[1], sys.argv[2]
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    space, items = load(hero, spec, "mixed", None, 80)
    engine = mage_cl.make_engine(hero, space, items, R.source_map(items), 5, spec)
    mod = mage_cl.engine_module(engine)
    rng = random.Random(5)
    base = random_builds(space, 400, 9)
    builds = []
    for code in space.talents:
        pool = [b for b in base if b[1]]
        for chunk, talents, glyphs, points in rng.sample(pool, per):
            others = [c for c in talents if c != code]
            talents = tuple(([code] + others)[:len(talents)])
            builds.append((chunk, talents, glyphs, points))
    res = mod.parity_full(engine, space, items, 5, builds)
    print(hero, spec, {k: res[k] for k in res if k != "examples"}, res["examples"][:2])


if __name__ == "__main__":
    main()
