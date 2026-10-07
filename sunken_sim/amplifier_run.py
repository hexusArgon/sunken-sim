"""Sextuples that include Mind Amplifier X-8000.

The item is not part of the top-100 list. This pass fixes one copy in the
first slot and walks the other five from a pool. Shop does not get a drop item.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sunken_sim.library import Item
from sunken_sim.search import (
    GLYPHS,
    _best_points,
    _can_add,
    _evaluate,
    _item_kind,
    _triples_seq,
)
from sunken_sim.shadow import MIND_AMPLIFIER, Build, simulate

WORKERS = 4


def _write(path: Path, payload: dict) -> None:
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
            if old.get("item_dps", -1) >= payload["item_dps"]:
                return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        os.close(fd)
        os.remove(lock)


def amplifier_slice(task: tuple) -> tuple[int, int, int]:
    second, items, targets, spec, floor, talent_codes, glyph_codes, record = task
    amp = items[0]
    if amp.rawcode != MIND_AMPLIFIER or _item_kind(amp) != "one":
        raise RuntimeError(amp.rawcode)
    item = items[second]
    amp_tag = _item_kind(amp)
    tag = _item_kind(item)
    if (tag == "leg" and amp_tag == "leg") or (tag == "orb" and amp_tag == "orb"):
        return second, 0, 0
    seen = 0
    best = floor
    records = 0
    path = Path(record)

    def consider(chosen: list[Item]) -> None:
        nonlocal seen, best, records
        seen += 1
        dps = simulate(
            Build(frozenset(), frozenset(), tuple(chosen), 0, 0, 0, 0),
            targets,
            spec=spec,
            use_history=False,
        ).dps
        if seen % 20000 == 0:
            print(f"усилитель {second} {seen} лучший {best:.1f}", flush=True)
        if dps <= best:
            return
        best = dps
        records += 1
        names = [piece.name for piece in chosen]
        print(f"новый набор amplifier {targets} {dps:.1f} {', '.join(names)}", flush=True)
        talent_dps, talents = _triples_seq(
            tuple(chosen), targets, spec, talent_codes, frozenset(), frozenset(), "talents"
        )
        glyph_dps, glyphs = _triples_seq(
            tuple(chosen), targets, spec, glyph_codes, frozenset(talents), frozenset(), "glyphs"
        )
        _write(
            path,
            {
                "dps": glyph_dps,
                "item_dps": dps,
                "talent_dps": talent_dps,
                "talents": list(talents),
                "glyphs": list(glyphs),
                "items": [piece.rawcode for piece in chosen],
            },
        )

    def walk(start: int, left: int, has_leg: bool, has_orb: bool, chosen: list[Item]) -> None:
        if left == 0:
            consider(chosen)
            return
        for index in range(start, len(items)):
            piece = items[index]
            piece_tag = _item_kind(piece)
            if piece_tag == "leg" and has_leg:
                continue
            if piece_tag == "orb" and has_orb:
                continue
            copies = left if piece_tag == "stack" else 1
            for count in range(1, copies + 1):
                chosen.extend([piece] * count)
                walk(
                    index + 1,
                    left - count,
                    has_leg or piece_tag == "leg",
                    has_orb or piece_tag == "orb",
                    chosen,
                )
                del chosen[-count:]

    copies = 5 if tag == "stack" else 1
    for count in range(1, copies + 1):
        chosen = [amp] + [item] * count
        walk(
            second + 1,
            5 - count,
            amp_tag == "leg" or tag == "leg",
            amp_tag == "orb" or tag == "orb",
            chosen,
        )
    print(f"усилитель {second} конец {seen} лучший {best:.1f} новых {records}", flush=True)
    return second, seen, records


def _greedy(amplifier: Item, others: list[Item], targets: int) -> tuple[float, tuple[Item, ...]]:
    chosen = [amplifier]
    best_dps = _evaluate(Build(frozenset(), frozenset(), tuple(chosen), 0, 0, 0, 0), targets)[0]
    for _slot in range(5):
        best_item = None
        best = -1.0
        for item in others:
            if not _can_add(chosen, item):
                continue
            dps = _evaluate(
                Build(frozenset(), frozenset(), tuple(chosen + [item]), 0, 0, 0, 0),
                targets,
            )[0]
            if dps > best:
                best = dps
                best_item = item
        if best_item is None:
            break
        chosen.append(best_item)
        best_dps = best
    return best_dps, tuple(chosen)


def _finish(
    catalog: list[Item],
    targets: int,
    talent_codes: tuple[str, ...],
    record: Path,
) -> Build:
    if not record.exists():
        return Build(frozenset(), frozenset(), _greedy(catalog[0], catalog[1:], targets)[1], 0, 0, 0, 0)
    saved = json.loads(record.read_text(encoding="utf-8"))
    by_code = {item.rawcode: item for item in catalog}
    items = tuple(by_code[code] for code in saved["items"])
    return Build(frozenset(saved["talents"]), frozenset(saved["glyphs"]), items, 0, 0, 0, 0)


def search_with_amplifier(
    catalog: list[Item],
    targets: int,
    talent_codes: tuple[str, ...],
    record: Path,
) -> tuple[Build, float]:
    import sunken_sim.search as search

    search._SPEC = "shadow"
    search._SIM_ENGINE = "priest"
    if catalog[0].rawcode != MIND_AMPLIFIER:
        raise RuntimeError("amplifier is not first")
    floor, _seed = _greedy(catalog[0], catalog[1:], targets)
    print(f"порог жадного набора с усилителем {floor:.1f}", flush=True)
    glyph_codes = tuple(sorted(GLYPHS))
    tasks = [
        (index, catalog, targets, "shadow", floor, talent_codes, glyph_codes, str(record))
        for index in range(1, len(catalog))
    ]
    print(
        f"комбинации с {catalog[0].name}, срезов {len(tasks)}, процессы {WORKERS}",
        flush=True,
    )
    from sunken_sim.history import release

    release()
    record.parent.mkdir(exist_ok=True)
    total = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for second, seen, records in pool.map(amplifier_slice, tasks):
            total += seen
            print(f"сдан усилитель {second}, всего шестёрок {total}, новых {records}", flush=True)
    geared = _finish(catalog, targets, talent_codes, record)
    if not geared.talents:
        talent_dps, talents = _triples_seq(
            geared.items, targets, "shadow", talent_codes, frozenset(), frozenset(), "talents"
        )
        glyph_dps, glyphs = _triples_seq(
            geared.items, targets, "shadow", glyph_codes, frozenset(talents), frozenset(), "glyphs"
        )
        geared = Build(frozenset(talents), frozenset(glyphs), geared.items, 0, 0, 0, 0)
        print(f"таланты на жадном наборе {glyph_dps:.1f}", flush=True)
        del talent_dps
    counter = {"targets": targets, "spec": "shadow", "engine": "priest", "full_points": True}
    dps, points = _best_points(counter, geared)
    final = Build(
        geared.talents,
        geared.glyphs,
        geared.items,
        points[1],
        points[3],
        points[0],
        points[2],
    )
    return final, dps
