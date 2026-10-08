"""Full single-target search.

Every priest talent triple, every glyph triple and every way to spend 5 skill
points is simulated. Every item is simulated when the six slots are filled and
again whenever a slot can be replaced. Nothing is ranked by reading tooltip text.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sunken_sim.library import MAP_PATH, Item, _extract, _parse_objects, load_items, map_script, map_strings
from sunken_sim.stacking import ORBS, allows_copies
from sunken_sim.shadow import (
    FIGHT,
    SKILL_POINTS,
    MIND_AMPLIFIER,
    Build,
    character,
    compile_events,
    score_compiled,
    simulate,
)

TALENTS = {
    "I0KF": "Dark Torment",
    "I0KG": "Smite",
    "I0PS": "Catharsis",
    "I0SB": "Answered Prayers",
    "I0HL": "Psychic Link",
    "I0PU": "Insanity",
    "I0MJ": "Empyreal Blaze",
    "I0KH": "Blinding Light",
    "I0HP": "Cosmic Horrors",
    "I0SA": "Clairvoyance",
    "I0PT": "Dark Evangelism",
    "I0SC": "Touch of the Naaru",
}
# Healing, incoming mitigation, survival, summons and effects that do not
# raise the hero's own damage stay out. See docs/guide.md.
GLYPHS = {
    "I0HC": "Animosity",
    "I0EN": "Arc Striking",
    "I0GZ": "Battle Frenzy",
    "I0H6": "Blood Violence",
    "I0EJ": "Fortune",
    "I07B": "Fortitude",
    "I0JA": "Glass Cannon",
    "I0H3": "Hellfire",
    "I0OF": "Mindhaste",
    "I0EK": "Supremacy",
    "I0H5": "Thunder",
    "I0AV": "Unsealed Power",
}

POINT_SPLITS = tuple(
    (crit, potency, luck, mastery)
    for crit in range(SKILL_POINTS + 1)
    for potency in range(SKILL_POINTS - crit + 1)
    for luck in range(SKILL_POINTS - crit - potency + 1)
    for mastery in [SKILL_POINTS - crit - potency - luck]
)

_ITEMS: tuple[Item, ...] = ()
_TARGETS = 1
_SPEC = "shadow"
_SIM_ENGINE = "priest"


def _score_stats(compiled: dict, stats: dict, potency: float, crit: float, mastery_stat: float, luck: float) -> float:
    return score_compiled(compiled, stats, potency, crit, mastery_stat, luck) / FIGHT


def _best_points(counter: dict, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    if counter.get("engine") == "mage":
        from sunken_sim.mage import best_points

        return best_points(counter, build)
    targets = counter.get("targets", 1)
    spec = counter.get("spec", _SPEC)
    bare = Build(build.talents, build.glyphs, build.items, 0, 0, 0, 0)
    stats = character(bare)
    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    compiled_by_crit: dict[int, dict] = {}
    for crit_points, potency_points, luck_points, mastery_points in POINT_SPLITS:
        compiled = compiled_by_crit.get(crit_points)
        if compiled is None:
            pointed = Build(build.talents, build.glyphs, build.items, 0, 0, crit_points, 0)
            fresh: dict = {"targets": targets}
            simulate(pointed, targets, fresh, spec=spec)
            compiled = compile_events(
                fresh["events"],
                bare,
                stats,
                spec,
                fresh.get("windows"),
            )
            compiled_by_crit[crit_points] = compiled
        dps = _score_stats(
            compiled,
            stats,
            stats["potency"] + 0.5 * potency_points,
            min(100.0, stats["crit"] + crit_points),
            stats["mastery"] + mastery_points,
            stats["luck"] + 0.01 * luck_points,
        )
        if dps > best_dps:
            best_dps = dps
            best = (crit_points, potency_points, luck_points, mastery_points)
    return best_dps, best


def _call_sim(build: Build, targets: int, counter: dict, bound: str | None = None):
    if _SIM_ENGINE == "mage":
        from sunken_sim.mage import simulate as mage_simulate

        return mage_simulate(build, targets, counter, bound, _SPEC)
    return simulate(build, targets, counter, bound, _SPEC)


def _init_worker(items: tuple[Item, ...], targets: int, spec: str, engine: str = "priest") -> None:
    global _ITEMS, _TARGETS, _SPEC, _SIM_ENGINE
    _ITEMS = items
    _TARGETS = targets
    _SPEC = spec
    _SIM_ENGINE = engine


def _evaluate(build: Build, targets: int) -> tuple[float, tuple[int, int, int, int]]:
    """One fight with zero skill points. Points are chosen once, on the winning build."""
    bare = Build(build.talents, build.glyphs, build.items, 0, 0, 0, 0)
    if _SIM_ENGINE == "mage":
        from sunken_sim.mage import simulate as mage_simulate

        return mage_simulate(bare, targets, spec=_SPEC).dps, (0, 0, 0, 0)
    return simulate(bare, targets, spec=_SPEC).dps, (0, 0, 0, 0)


_FIXED_TALENTS: frozenset[str] = frozenset()
_FIXED_GLYPHS: frozenset[str] = frozenset()


def _init_stage(
    items: tuple[Item, ...],
    targets: int,
    spec: str,
    engine: str,
    fixed_talents: frozenset[str],
    fixed_glyphs: frozenset[str],
) -> None:
    global _FIXED_TALENTS, _FIXED_GLYPHS
    _init_worker(items, targets, spec, engine)
    _FIXED_TALENTS = fixed_talents
    _FIXED_GLYPHS = fixed_glyphs


def _eval_talent_chunk(talent_sets: list[tuple[str, ...]]) -> tuple:
    best_dps = -1.0
    best = None
    for talents in talent_sets:
        build = Build(frozenset(talents), _FIXED_GLYPHS, _ITEMS, 0, 0)
        dps, points = _evaluate(build, _TARGETS)
        if dps > best_dps:
            best_dps = dps
            best = (dps, talents, points)
    return best


def _eval_glyph_chunk(glyph_sets: list[tuple[str, ...]]) -> tuple:
    best_dps = -1.0
    best = None
    for glyphs in glyph_sets:
        build = Build(_FIXED_TALENTS, frozenset(glyphs), _ITEMS, 0, 0)
        dps, points = _evaluate(build, _TARGETS)
        if dps > best_dps:
            best_dps = dps
            best = (dps, glyphs, points)
    return best


def _search_options(
    items: tuple[Item, ...],
    targets: int,
    options: list[tuple[str, ...]],
    stage: str,
    fixed_talents: frozenset[str],
    fixed_glyphs: frozenset[str],
) -> tuple:
    workers = max(1, (os.cpu_count() or 2) - 1)
    chunk = 400
    parts = [options[index : index + chunk] for index in range(0, len(options), chunk)]
    worker = _eval_talent_chunk if stage == "talents" else _eval_glyph_chunk
    best_dps = -1.0
    best = None
    print(f"симуляций {stage} {len(options)}", flush=True)
    from sunken_sim.history import release

    release()
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_stage,
        initargs=(items, targets, _SPEC, _SIM_ENGINE, fixed_talents, fixed_glyphs),
    ) as pool:
        for result in pool.map(worker, parts):
            if result is not None and result[0] > best_dps:
                best_dps = result[0]
                best = result
    assert best is not None
    return best


def _talent_picks(items: tuple[Item, ...] | list[Item]) -> int:
    if any(item.rawcode == MIND_AMPLIFIER for item in items):
        return 4
    return 3


def _best_talent_set(
    items: tuple[Item, ...],
    glyphs: frozenset[str],
    targets: int,
    talents: dict[str, str] | None,
) -> tuple[float, Build]:
    picks = _talent_picks(items)
    options = list(itertools.combinations(sorted(talents or TALENTS), picks))
    dps, chosen, points = _search_options(items, targets, options, "talents", frozenset(), glyphs)
    build = Build(frozenset(chosen), glyphs, items, points[1], points[3], points[0], points[2])
    return dps, build


def _best_glyph_set(items: tuple[Item, ...], talents: frozenset[str], targets: int) -> tuple[float, Build]:
    options = list(itertools.combinations(sorted(GLYPHS), 3))
    dps, chosen, points = _search_options(items, targets, options, "glyphs", talents, frozenset())
    build = Build(talents, frozenset(chosen), items, points[1], points[3], points[0], points[2])
    return dps, build


def _dps_of(build: Build) -> float:
    return _evaluate(build, 1)[0]


def _can_add(chosen: list[Item], candidate: Item, ignore: Item | None = None) -> bool:
    if not _equip_ok(chosen, candidate, ignore):
        return False
    if any(item.rawcode == candidate.rawcode and item is not ignore for item in chosen):
        return allows_copies(candidate.rawcode)
    return True


def _item_kind(item: Item) -> str:
    if item.rawcode in LEGENDARIES:
        return "leg"
    if item.rawcode in ORBS:
        return "orb"
    if allows_copies(item.rawcode):
        return "stack"
    return "one"


def _greedy_floor(catalog: list[Item], targets: int) -> tuple[float, tuple[Item, ...]]:
    chosen: list[Item] = []
    best_dps = 0.0
    for _slot in range(6):
        best_item = None
        best = -1.0
        for item in catalog:
            if not _can_add(chosen, item):
                continue
            dps, _points = _evaluate(Build(frozenset(), frozenset(), tuple(chosen + [item]), 0, 0, 0, 0), targets)
            if dps > best:
                best = dps
                best_item = item
        if best_item is None:
            break
        chosen.append(best_item)
        best_dps = best
    print(f"порог жадного набора {best_dps:.1f}", flush=True)
    return best_dps, tuple(chosen)


def _triples_seq(
    items: tuple[Item, ...],
    targets: int,
    spec: str,
    codes: tuple[str, ...],
    talents: frozenset[str],
    glyphs: frozenset[str],
    stage: str,
) -> tuple[float, tuple[str, ...]]:
    best_dps = -1.0
    best: tuple[str, ...] = ()
    picks = _talent_picks(items) if stage == "talents" else 3
    for chosen_codes in itertools.combinations(codes, picks):
        if stage == "talents":
            build = Build(frozenset(chosen_codes), glyphs, items, 0, 0, 0, 0)
        else:
            build = Build(talents, frozenset(chosen_codes), items, 0, 0, 0, 0)
        dps = simulate(build, targets, spec=spec).dps
        if dps > best_dps:
            best_dps = dps
            best = chosen_codes
    return best_dps, best


def _share() -> tuple[frozenset[int], int]:
    """Which slice residues this machine owns.

    SUNKEN_PARTS is the number of residues. SUNKEN_PART is one residue or a
    comma-separated list. A stronger machine lists several residues.
    """
    parts = int(os.environ.get("SUNKEN_PARTS", "1"))
    raw = os.environ.get("SUNKEN_PART", "0")
    chosen = frozenset(int(piece) for piece in raw.split(",") if piece.strip())
    if parts < 1 or not chosen or any(part < 0 or part >= parts for part in chosen):
        raise SystemExit(f"SUNKEN_PART={raw} SUNKEN_PARTS={parts}")
    return chosen, parts


def _part_label() -> str:
    chosen, parts = _share()
    if parts == 1 and chosen == frozenset({0}):
        return ""
    return "-".join(str(part) for part in sorted(chosen))


def _record_dir() -> Path:
    folder = Path(__file__).resolve().parents[1] / "extract" / "exhaustive"
    folder.mkdir(exist_ok=True)
    return folder


def _legacy_record_path(spec: str, targets: int) -> Path:
    label = _part_label()
    name = f"{spec}-{targets}.json" if not label else f"{spec}-{targets}-part{label}.json"
    return _record_dir() / name


def _record_path(spec: str, targets: int, items: list[Item] | None = None) -> Path:
    legacy = _legacy_record_path(spec, targets)
    if items is None:
        return legacy
    label = _part_label()
    key = hashlib.sha1(",".join(item.rawcode for item in items).encode()).hexdigest()[:12]
    stem = f"{spec}-{targets}-{key}" if not label else f"{spec}-{targets}-part{label}-{key}"
    return _record_dir() / f"{stem}.json"


def _saved_for_pool(path: Path, items: list[Item]) -> dict | None:
    if not path.exists():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    codes = {item.rawcode for item in items}
    names = {item.name for item in items}
    if any(token not in codes and token not in names for token in saved.get("items", [])):
        return None
    return saved


def _write_record(spec: str, targets: int, payload: dict, path: Path | None = None) -> None:
    import time

    if path is None:
        path = _record_path(spec, targets)
    lock = path.with_suffix(".lock")
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.05)
    try:
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            old_item = old.get("item_dps")
            new_item = payload.get("item_dps")
            if (
                isinstance(old_item, (int, float))
                and isinstance(new_item, (int, float))
                and old_item >= new_item
            ):
                return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        os.close(fd)
        os.remove(lock)


def _done_path(items: list[Item], spec: str, targets: int) -> Path:
    folder = Path(__file__).resolve().parents[1] / "extract" / "exhaustive"
    folder.mkdir(exist_ok=True)
    chosen, parts = _share()
    label = "-".join(str(part) for part in sorted(chosen))
    key = hashlib.sha1(",".join(item.rawcode for item in items).encode()).hexdigest()[:12]
    return folder / f"{spec}-{targets}-part{label}-{key}-done.txt"


def _load_done(path: Path) -> set[int]:
    if not path.exists():
        return set()
    found = set()
    for line in path.read_text(encoding="utf-8").split():
        if line.strip().isdigit():
            found.add(int(line))
    return found


def _mark_done(path: Path, index: int) -> None:
    path.parent.mkdir(exist_ok=True)
    lock = path.with_suffix(".lock")
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            import time

            time.sleep(0.05)
    try:
        done = _load_done(path)
        if index in done:
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{index}\n")
    finally:
        os.close(fd)
        os.remove(lock)


def _exhaustive_slice(task: tuple) -> tuple[int, float, int]:
    first, items, targets, spec, floor, talent_codes, glyph_codes, done_path, record_path = task
    kind = _item_kind(items[first])
    if kind == "stack":
        starts = range(1, 7)
    else:
        starts = (1,)
    seen = 0
    best = floor
    records = 0

    def consider(chosen: list[Item]) -> None:
        nonlocal seen, best, records
        seen += 1
        # DPS only. Saving every sextuple locks the shared history file across
        # the forked slices and does not fit on disk. Talent and glyph passes
        # still remember a fight.
        dps = simulate(
            Build(frozenset(), frozenset(), tuple(chosen), 0, 0, 0, 0),
            targets,
            spec=spec,
            use_history=False,
        ).dps
        if seen % 20000 == 0:
            print(f"срез {first} {seen} лучший {best:.1f}", flush=True)
        if dps <= best:
            return
        best = dps
        records += 1
        names = [item.name for item in chosen]
        print(f"новый набор {spec} {targets} {dps:.1f} {', '.join(names)}", flush=True)
        talent_dps, talents = _triples_seq(tuple(chosen), targets, spec, talent_codes, frozenset(), frozenset(), "talents")
        glyph_dps, glyphs = _triples_seq(tuple(chosen), targets, spec, glyph_codes, frozenset(talents), frozenset(), "glyphs")
        _write_record(
            spec,
            targets,
            {
                "dps": glyph_dps,
                "item_dps": dps,
                "talent_dps": talent_dps,
                "talents": list(talents),
                "glyphs": list(glyphs),
                "items": [item.rawcode for item in chosen],
            },
            Path(record_path),
        )

    def walk(start: int, left: int, has_leg: bool, has_orb: bool, chosen: list[Item]) -> None:
        if left == 0:
            consider(chosen)
            return
        for index in range(start, len(items)):
            item = items[index]
            tag = _item_kind(item)
            if tag == "leg" and has_leg:
                continue
            if tag == "orb" and has_orb:
                continue
            copies = left if tag == "stack" else 1
            for count in range(1, copies + 1):
                chosen.extend([item] * count)
                walk(index + 1, left - count, has_leg or tag == "leg", has_orb or tag == "orb", chosen)
                del chosen[-count:]

    for count in starts:
        if count > 6:
            break
        chosen = [items[first]] * count
        walk(
            first + 1,
            6 - count,
            kind == "leg",
            kind == "orb",
            chosen,
        )
    print(f"срез {first} конец {seen} лучший {best:.1f} новых {records}", flush=True)
    _mark_done(Path(done_path), first)
    return first, seen, records


def _exhaustive_item_sets(
    catalog: list[Item],
    targets: int,
    talent_codes: tuple[str, ...],
    glyph_codes: tuple[str, ...],
) -> list[Build]:
    items = list(catalog)
    floor, greedy = _greedy_floor(items, targets)
    workers = max(1, (os.cpu_count() or 2) - 1)
    chosen, parts = _share()
    done_path = _done_path(items, _SPEC, targets)
    done = _load_done(done_path)
    record_path = _record_path(_SPEC, targets, items)
    tasks = [
        (index, items, targets, _SPEC, floor, talent_codes, glyph_codes, str(done_path), str(record_path))
        for index in range(len(items))
        if index % parts in chosen and index not in done
    ]
    label = ",".join(str(part) for part in sorted(chosen))
    print(
        f"полный перебор шестёрок, срезов {len(tasks)}, уже сдано {len(done & set(range(len(items))))}, "
        f"части {label} из {parts}, процессы {workers}",
        flush=True,
    )
    from sunken_sim.history import release

    release()
    total = 0
    if tasks:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for first, seen, records in pool.map(_exhaustive_slice, tasks):
                total += seen
                print(f"сдан срез {first}, всего шестёрок {total}, новых {records}", flush=True)
    else:
        print("все срезы этого пула уже сданы", flush=True)
    saved = _saved_for_pool(record_path, items)
    if saved is None:
        saved = _saved_for_pool(_legacy_record_path(_SPEC, targets), items)
    if saved is None:
        return [Build(frozenset(), frozenset(), greedy, 0, 0, 0, 0)]
    by_code = {item.rawcode: item for item in items}
    by_name: dict[str, Item] = {}
    for item in items:
        by_name.setdefault(item.name, item)
    picked = []
    for token in saved["items"]:
        item = by_code.get(token) or by_name.get(token)
        if item is None:
            return [Build(frozenset(), frozenset(), greedy, 0, 0, 0, 0)]
        picked.append(item)
    item_dps = saved.get("item_dps")
    if isinstance(item_dps, (int, float)):
        print(f"лучшая шестёрка без талантов {item_dps:.1f}", flush=True)
    return [Build(frozenset(), frozenset(), tuple(picked), 0, 0, 0, 0)]


def _fill_item_sets(base: Build, catalog: list[Item], targets: int = 1, talent_codes: tuple[str, ...] | None = None) -> list[Build]:
    if _SIM_ENGINE == "mage":
        return _beam_item_sets(base, catalog, targets)
    codes = talent_codes or tuple(sorted(TALENTS))
    return _exhaustive_item_sets(catalog, targets, codes, tuple(sorted(GLYPHS)))


def _beam_item_sets(base: Build, catalog: list[Item], targets: int = 1) -> list[Build]:
    """Mage still uses a short list. Priest walks every legal sextuple."""
    beam: list[tuple[tuple[Item, ...], tuple[int, int, int, int]]] = [((), (0, 0, 0, 0))]
    width = 8
    for _slot in range(6):
        found: list[tuple[float, tuple[Item, ...], tuple[int, int, int, int]]] = []
        seen: set[tuple[str, ...]] = set()
        for chosen, points in beam:
            owned = list(chosen)
            for item in catalog:
                if not _can_add(owned, item):
                    continue
                trial_items = chosen + (item,)
                key = tuple(sorted(piece.rawcode for piece in trial_items))
                if key in seen:
                    continue
                seen.add(key)
                trial = Build(frozenset(), frozenset(), trial_items, 0, 0, 0, 0)
                dps, _points = _evaluate(trial, targets)
                found.append((dps, trial_items, (0, 0, 0, 0)))
        found.sort(key=lambda row: row[0], reverse=True)
        beam = [(items, points) for _dps, items, points in found[:width]]
        if not beam:
            break
    return [Build(base.talents, base.glyphs, items, 0, 0, 0, 0) for items, _points in beam]


def _fill_items(base: Build, catalog: list[Item], targets: int = 1) -> Build:
    return _fill_item_sets(base, catalog, targets)[0]


def _swap_items(base: Build, catalog: list[Item], targets: int = 1) -> Build:
    chosen = list(base.items)
    points = (base.crit_points, base.potency_points, base.luck_points, base.mastery_points)
    best_dps, points = _evaluate(base, targets)
    improved = True
    passes = 0
    while improved and passes < 8:
        improved = False
        passes += 1
        for slot in range(len(chosen)):
            for item in catalog:
                if item.rawcode == chosen[slot].rawcode:
                    continue
                if not _can_add(chosen, item, ignore=chosen[slot]):
                    continue
                trial_items = chosen.copy()
                trial_items[slot] = item
                trial = Build(base.talents, base.glyphs, tuple(trial_items), points[1], points[3], points[0], points[2])
                dps, new_points = _evaluate(trial, targets)
                if dps > best_dps + 0.05:
                    best_dps = dps
                    chosen = trial_items
                    points = new_points
                    improved = True
    return Build(base.talents, base.glyphs, tuple(chosen), points[1], points[3], points[0], points[2])


def search_pool(
    catalog: list[Item],
    seed: Build,
    targets: int = 1,
    spec: str = "shadow",
    talents: dict[str, str] | None = None,
    engine: str = "priest",
) -> tuple[Build, float]:
    global _SPEC, _SIM_ENGINE
    _SPEC = spec
    _SIM_ENGINE = engine
    finished = _finish_builds(seed, catalog, targets, talents)
    best_build, _zero_dps = max(finished, key=lambda row: row[1])
    counter = {"targets": targets, "spec": spec, "engine": engine, "full_points": True}
    _dps, points = _best_points(counter, best_build)
    final = Build(best_build.talents, best_build.glyphs, best_build.items, points[1], points[3], points[0], points[2])
    return final, _dps


def _finish_builds(
    seed: Build,
    catalog: list[Item],
    targets: int,
    talents: dict[str, str] | None,
) -> list[tuple[Build, float]]:
    item_sets = _fill_item_sets(seed, catalog, targets, tuple(sorted(talents or TALENTS)))
    print(f"предметов {len(item_sets)} шестёрок, пул {len(catalog)}, цели {targets}", flush=True)
    finished: list[tuple[Build, float]] = []
    for index, geared in enumerate(item_sets, start=1):
        print(f"шестёрка {index}/{len(item_sets)}", flush=True)
        _talent_dps, with_talents = _best_talent_set(geared.items, frozenset(), targets, talents)
        dps, with_glyphs = _best_glyph_set(with_talents.items, with_talents.talents, targets)
        print(f"  {dps:.1f}", flush=True)
        finished.append((with_glyphs, dps))
    return finished


def search_categories(
    catalog: list[Item],
    seed: Build,
    shop_ids: set[str],
    targets: int = 1,
    spec: str = "shadow",
    talents: dict[str, str] | None = None,
    engine: str = "priest",
) -> dict[str, tuple[Build, float]]:
    global _SPEC, _SIM_ENGINE
    _SPEC = spec
    _SIM_ENGINE = engine
    finished = _finish_builds(seed, catalog, targets, talents)
    best_build, _best_dps = max(finished, key=lambda row: row[1])
    counter = {"targets": targets, "spec": spec, "engine": engine, "full_points": True}
    pointed_dps, points = _best_points(counter, best_build)
    pointed = Build(
        best_build.talents,
        best_build.glyphs,
        best_build.items,
        points[1],
        points[3],
        points[0],
        points[2],
    )
    return {"mixed": (pointed, pointed_dps)}


def shop_codes() -> set[str]:
    body = _shop_body(_map_script())
    return set(re.findall(r"set udg_TasItemShop_Item='(....)'", body))


def _map_script() -> str:
    return map_script()


def _shop_body(script: str) -> str:
    funcs = list(re.finditer(r"(?m)^function\s+(\S+)\s+takes[^\n]*\n", script))
    body = ""
    for index, match in enumerate(funcs):
        if match.group(1) in (
            "Trig_ItemshopGUI_Init_Items_1_Actions",
            "Trig_ItemshopGUI_Init_Items_2_Actions",
        ):
            end = funcs[index + 1].start()
            body += script[match.start() : end]
    return body


LEGENDARIES = frozenset({"I052", "I048", "I053", "I04A", "I0HU", "I09E", "I044", "I0BR"})
EPIC_NAME_COLOR = "007c2abb"
EXCLUSIVE = (frozenset({"I07O", "I0NS", "I0NT"}),)


def _equip_ok(chosen: list[Item], candidate: Item, ignore: Item | None = None) -> bool:
    if candidate.rawcode in LEGENDARIES and any(
        item.rawcode in LEGENDARIES and item is not ignore for item in chosen
    ):
        return False
    for group in EXCLUSIVE:
        if candidate.rawcode in group and any(item.rawcode in group and item is not ignore for item in chosen):
            return False
    return True

_REPEATABLE = (
    "Item_Use",
    "Drops_Actions",
    "Dig_Actions",
    "Boss_Loot",
    "Boss_Deaths",
    "OnSpellcast",
    "PreDamage",
    "Deathrattle",
    "Recipes",
    "Select_Agi",
    "Select_Str",
    "Select_Int",
    "Blink_Item",
    "Arcpower",
    "Explosive_Set",
    "Transfusion",
    "Arcane_Pulse",
    "Trophies",
    "Skull_Split",
    "Final_Service",
    "Treasure_Bag",
    "Item_Effects",
    "Random_Item",
    "Triple_Kill",
    "Blinding_Night",
    "Eye_Sell",
    "Legendary_Sell",
    "Botanic_Bowl_Use",
)


def _legendary_ok(chosen: list[Item], candidate: Item, ignore: Item | None = None) -> bool:
    if candidate.rawcode not in LEGENDARIES:
        return True
    return not any(item.rawcode in LEGENDARIES and item is not ignore for item in chosen)


def single_copy_codes() -> set[str]:
    script = _map_script()
    funcs = [(match.start(), match.group(1)) for match in re.finditer(r"(?m)^function\s+(\S+)\s+takes", script)]

    def owner(pos: int) -> str:
        name = ""
        for start, fname in funcs:
            if start <= pos:
                name = fname
            else:
                break
        return name

    drop: set[str] = set()
    for pool in ("Common", "Uncommon", "Rare", "Epic", "Tomes", "Consumables"):
        drop.update(re.findall(rf"set udg_Drops_{pool}\[\d+\]='(.{{4}})'", script))
    sold = set(re.findall(r"set udg_TasItemShop_Item='(....)'", _shop_body(script)))
    sources: dict[str, list[str]] = {}
    pattern = re.compile(
        r"(?:BlzCreateItemWithSkin|CreateItemLoc|CreateItem|UnitAddItemToSlotById|UnitAddItemByIdSwapped|UnitAddItemById)\("
    )
    for match in pattern.finditer(script):
        found = re.search(r"'(.{4})'", script[match.start() : match.start() + 90])
        if not found:
            continue
        sources.setdefault(found.group(1), []).append(owner(match.start()))
    banned = set()
    for code, places in sources.items():
        if code in drop or code in sold or code in LEGENDARIES:
            continue
        if any(any(token in place for token in _REPEATABLE) for place in places):
            continue
        if len(places) == 1:
            banned.add(code)
    return banned


def class_item_codes() -> dict[str, set[str]]:
    script = _map_script()
    found: dict[str, set[str]] = {}
    for class_name, rawcode in re.findall(r"set udg_ClassItems_(\w+)\[\d+\]='(.{4})'", script):
        found.setdefault(class_name, set()).add(rawcode)
    return found


def is_quest_item(item: Item) -> bool:
    return "Quest Reward" in item.tip or "Quest Item" in item.tip


def _ignored_names_in(path: Path) -> set[str]:
    marker = "Эти вещи в пул не входят:"
    names: set[str] = set()
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip().rstrip(".")
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        index = 0
        while index < len(parts):
            if parts[index] == "Pridwen" and index + 1 < len(parts) and parts[index + 1].startswith("Guard of Tirion"):
                names.add("Pridwen, Guard of Tirion")
                index += 2
                continue
            names.add(parts[index])
            index += 1
    return names


def ignored_item_names(hero_class: str | None = None) -> set[str]:
    """Names the guides list as out of the pool.

    The general guide applies to every hero. Priest and mage guides add the
    attack weapons those casters skip.
    """
    docs = Path(__file__).resolve().parents[1] / "docs"
    names = _ignored_names_in(docs / "guide.md")
    extra = {"Priest": "priest.md", "Mage": "mage.md"}
    if hero_class in extra:
        names |= _ignored_names_in(docs / extra[hero_class])
    return names


def _guide_ignored(item: Item, names: set[str]) -> bool:
    plain = item.name.removesuffix(" (Recipe)")
    return item.name in names or plain in names


def epic_codes() -> set[str]:
    """Items whose name is the map's epic purple."""
    strings = map_strings()
    skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))
    found = set()
    for code, mods in skin.items():
        if "unam" not in mods:
            continue
        raw_id = str(mods["unam"][0])
        if not raw_id.startswith("TRIGSTR_"):
            continue
        raw = strings.get(int(raw_id.split("_")[1]), "")
        if EPIC_NAME_COLOR in raw.lower():
            found.add(code)
    return found


def pools_for(catalog: list[Item], hero_class: str = "Priest") -> tuple[list[Item], list[Item], list[Item]]:
    shop, drop, legendaries = split_catalog(catalog)
    foreign = set().union(*(codes for name, codes in class_item_codes().items() if name != hero_class))

    epics = epic_codes()
    ignored = ignored_item_names(hero_class)

    def allowed(item: Item) -> bool:
        return (
            item.rawcode not in foreign
            and not is_quest_item(item)
            and not _guide_ignored(item, ignored)
            and (item.rawcode in epics or item.rawcode in LEGENDARIES)
        )

    legendaries = [item for item in legendaries if allowed(item)]
    return (
        [item for item in shop if allowed(item)],
        [item for item in drop if allowed(item)],
        legendaries,
    )


def split_catalog(catalog: list[Item]) -> tuple[list[Item], list[Item], list[Item]]:
    sold = shop_codes()
    banned = single_copy_codes()

    def is_shop(item: Item) -> bool:
        return item.tip.startswith("Shop Item") or item.rawcode in sold

    shop = [item for item in catalog if is_shop(item) and item.rawcode not in LEGENDARIES and item.rawcode not in banned]
    drop = [
        item
        for item in catalog
        if not is_shop(item) and item.rawcode not in LEGENDARIES and item.rawcode not in banned
    ]
    legendaries = [item for item in catalog if item.rawcode in LEGENDARIES]
    return shop, drop, legendaries
