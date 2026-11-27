"""Re-freeze frozen fights after a deliberate model change of a GPU-only class.

    python3.11 tools/refreeze_fixtures.py <hero> [--fix-note TEXT] [--incoming-note TEXT] [--refine-note TEXT]

For every case of farm/hybrid/fixtures/<hero>.json the current kernel (pocl CPU, exact float64) is run:
- an unmarked case whose DPS changed is marked "model_fix" (it wears one of the module's MODEL_FIX_ITEMS)
  or "incoming"; the Python == GPU value in "dps" is kept;
- every marked case gets "now": the current kernel's DPS, which class_cl.fixture_check (the GPU preflight) and
  test_fixtures replay;
- top-150 refinements that changed are re-frozen in place with a "frozen" note.
Run only after the change was checked against the map (tests, docs/defense-model.md).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_fixtures import CLASS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hero", choices=sorted(CLASS))
    ap.add_argument("--fix-note", default="model fix")
    ap.add_argument("--incoming-note", default="")
    ap.add_argument("--refine-note", default="GPU re-freeze")
    args = ap.parse_args()

    from farm import runner as R
    from farm.hybrid import class_cl as C
    from farm.hybrid.priest_cl import find_chunk
    from farm.space import Space
    from sunken_sim.esc import ESC_ATTRS

    hero = args.hero
    class_name, modname, clsname = CLASS[hero]
    mod = importlib.import_module(modname)
    path = Path(__file__).resolve().parents[1] / "farm" / "hybrid" / "fixtures" / f"{hero}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    full, items = C.full_space(hero, class_name, mod.TALENT_NAMES)
    src = R.source_map(items)
    fix = getattr(mod, "MODEL_FIX_ITEMS", frozenset())
    groups: dict = {}
    for c in data["cases"]:
        groups.setdefault((c["spec"], c["targets"]), []).append(c)
    count = {"same": 0, "marked_incoming": 0, "marked_model_fix": 0, "now": 0}
    for (spec, targets), cases in groups.items():
        e = getattr(mod, clsname)(full, items, src, targets, None, spec)
        dps, _g, status = e.pick([e.picks_of(c["items"]) for c in cases], [e.talent_mask(c["talents"]) for c in cases],
                                 [e.glyph_mask(c["glyphs"]) for c in cases],
                                 [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        for c, d, st in zip(cases, dps, status):
            if st:
                raise SystemExit(f"status {int(st)}: {spec} {targets} {c['items']}")
            value = float(d).hex()
            marked = bool(c.get("incoming") or c.get("model_fix"))
            if not marked:
                if value == c["dps"]:
                    count["same"] += 1
                    continue
                if set(c["items"]) & fix:
                    c["model_fix"] = args.fix_note
                    count["marked_model_fix"] += 1
                else:
                    c["incoming"] = args.incoming_note or True
                    count["marked_incoming"] += 1
            c["now"] = value
            count["now"] += 1
    print(hero, count)
    for case in data.get("refine", []):
        pieces = [p for p in full.pieces if p.code in set(case["items"])]
        space = Space(pieces, case["talent_pool"], case["glyph_pool"], picks_without=case["picks_without"],
                      picks_with=case["picks_with"], talent_names=full.talent_names, glyph_names=full.glyph_names)
        sub = {p.code: items[p.code] for p in pieces}
        e = getattr(mod, clsname)(space, sub, R.source_map(sub), 5, None, case["spec"])
        chunk = find_chunk(space, case["items"])
        equipped = tuple(sub[c] for c in space.decode(chunk)[0])
        got = e.refine(chunk, equipped, case["talent_pool"], case["glyph_pool"], case["picks_without"],
                       case["picks_with"], case["glyph_picks"])
        have = (float(got[0]).hex(), list(got[1]), list(got[2]), got[3], got[4])
        if have != (case["dps"], case["talents"], case["glyphs"], case["points"], case["fights"]):
            print("refine", case["spec"], case["items"], float.fromhex(case["dps"]), "->", float(got[0]))
            case["dps"], case["talents"], case["glyphs"], case["points"], case["fights"] = have
            case["frozen"] = args.refine_note
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
