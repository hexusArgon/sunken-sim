"""Shadow sextuples that always include Sulfuras and five items from the top 80.

Other legendaries in that eighty cannot be worn with Sulfuras, so they are not
enumerated. Every sextuple is scored with empty talents and glyphs. Talents,
glyphs and skill points run only for the final item-only top 10 of each
category. The canvas changes only when that finished fight beats the build
already shown for the same pool.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from farm.paths import atomic_write, data_dir
from farm.protocol import grouped
from farm.runner import build_group, note_span, worker_count
from farm.space import Piece, Space

ROOT = Path(__file__).resolve().parents[1]
TOP = ROOT / "extract" / "shadow-top100.json"
CANVAS_COPY = Path(
    r"C:\Users\eseid\.cursor\projects\c-Users-eseid-sunken-sim\canvases\priest-sims.canvas.tsx"
)
POOL_KEY = {"overall": "5-mixed", "shop": "5-shop", "drop": "5-drop"}
KEEP = 10
BATCH = 8192

_SPACE: Space | None = None
_ITEMS: dict = {}
_SOURCES: dict[str, str] = {}
_SULF = None


def top_partners(by_code: dict) -> tuple[list[Piece], object]:
    from sunken_sim.search import LEGENDARIES, _item_kind
    from sunken_sim.shadow import SULFURAS

    rows = json.loads(TOP.read_text(encoding="utf-8"))
    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        code = row["rawcode"]
        if code in seen:
            continue
        seen.add(code)
        ordered.append(code)
        if len(ordered) == 80:
            break
    if len(ordered) < 80:
        raise RuntimeError(f"в топе {len(ordered)} предметов, нужно 80")
    if SULFURAS not in ordered:
        raise RuntimeError("Sulfuras нет в топ-80 Shadow")
    missing = [code for code in ordered if code not in by_code]
    if missing:
        raise RuntimeError("нет предметов: " + ", ".join(missing))
    partners = []
    for code in ordered:
        if code in LEGENDARIES:
            continue
        item = by_code[code]
        partners.append(Piece(code, _item_kind(item), name=item.name))
    partners.sort(key=lambda piece: piece.code)
    return partners, by_code[SULFURAS]


def init_worker(space: Space, items: dict, sources: dict, sulf_code: str) -> None:
    global _SPACE, _ITEMS, _SOURCES, _SULF
    _SPACE = space
    _ITEMS = items
    _SOURCES = sources
    _SULF = items[sulf_code]


def eval_span(start: int, stop: int) -> dict:
    from farm.score import item_dps

    assert _SPACE is not None and _SULF is not None
    rows = []
    errors = 0
    error = ""
    for index in range(start, stop):
        try:
            codes, _talents, _glyphs = _SPACE.decode(index)
            equipped = tuple(_ITEMS[code] for code in codes) + (_SULF,)
            sources = [_SOURCES.get(item.rawcode, "drop") for item in equipped]
            bare = item_dps("priest", "shadow", 5, equipped)
            rows.append((bare, index, build_group(sources)))
        except Exception as exc:
            errors += 1
            if not error:
                error = f"{index}: {exc}"
    rows.sort(reverse=True)
    return {"start": start, "done": stop, "rows": rows[: KEEP * 4], "errors": errors, "error": error}


def _checkpoint_path() -> Path:
    return data_dir() / "checkpoints" / "sulfuras-shadow-priest.json"


def _keep(board: list[tuple[float, int, str | None]], row: tuple[float, int, str | None]) -> None:
    board.append(row)
    board.sort(reverse=True)
    del board[KEEP:]


def _consider(boards: dict[str, list], bare: float, index: int, group: str | None) -> None:
    from farm.runner import bars_for

    row = (bare, index, group)
    for key in bars_for(group):
        held = boards[key]
        if len(held) >= KEEP and bare <= held[-1][0]:
            continue
        _keep(held, row)


def _load() -> tuple[int, list[tuple[int, int]], dict[str, list], int]:
    path = _checkpoint_path()
    empty = {key: [] for key in ("overall", "shop", "drop")}
    if not path.exists():
        return 0, [], empty, 0
    saved = json.loads(path.read_text(encoding="utf-8"))
    boards = {key: [tuple(row) for row in saved.get("boards", {}).get(key) or []] for key in empty}
    ahead = [(int(left), int(right)) for left, right in saved.get("ahead") or []]
    return int(saved.get("done") or 0), ahead, boards, int(saved.get("errors") or 0)


def _save(done: int, ahead: list[tuple[int, int]], boards: dict[str, list], errors: int, total: int) -> None:
    payload = {
        "done": done,
        "ahead": [[left, right] for left, right in ahead],
        "total": total,
        "errors": errors,
        "boards": {key: [list(row) for row in rows] for key, rows in boards.items()},
    }
    atomic_write(_checkpoint_path(), json.dumps(payload))


def _finish(space: Space, items: dict, boards: dict[str, list]) -> dict:
    from farm.catalog import SHADOW_TALENTS
    from farm.score import finish_sextuple
    from sunken_sim.search import GLYPHS, TALENTS
    from sunken_sim.shadow import SULFURAS

    talents = list(SHADOW_TALENTS)
    glyphs = sorted(GLYPHS)
    scored: dict[int, dict] = {}
    finished = []
    for key, rows in boards.items():
        for bare, index, group in rows:
            if index not in scored:
                codes, _t, _g = space.decode(index)
                equipped = tuple(items[code] for code in codes) + (items[SULFURAS],)
                dps, talent_codes, glyph_codes, points, _fights = finish_sextuple(
                    "priest", "shadow", 5, equipped, talents, glyphs, 3, 4, 3
                )
                crit, potency, luck, mastery = points
                scored[index] = {
                    "dps": dps,
                    "item_dps": bare,
                    "chunk": index,
                    "group": group,
                    "items": [item.rawcode for item in equipped],
                    "talents": list(talent_codes),
                    "glyphs": list(glyph_codes),
                    "talent_names": [TALENTS[code] for code in talent_codes],
                    "glyph_names": [GLYPHS[code] for code in glyph_codes],
                    "points": {"crit": crit, "potency": potency, "luck": luck, "mastery": mastery},
                }
                print(f"добивка {dps:.1f} чанк {index}", flush=True)
            row = dict(scored[index])
            row["pool"] = key
            row["item_dps"] = bare
            finished.append(row)
    return {"finished": finished}


def run(limit: int | None = None) -> dict:
    from sunken_sim.library import load_items
    from sunken_sim.search import GLYPHS
    from sunken_sim.shadow import SULFURAS
    from farm.catalog import SHADOW_TALENTS
    from farm.runner import source_map

    by_code = {item.rawcode: item for item in load_items()}
    partners, sulf = top_partners(by_code)
    space = Space(partners, list(SHADOW_TALENTS), sorted(GLYPHS), slots=5)
    total = space.total if limit is None else min(space.total, limit)
    items = {piece.code: by_code[piece.code] for piece in partners}
    items[SULFURAS] = sulf
    sources = source_map(items)
    print(
        f"Sulfuras + топ-80: партнёров {len(partners)}, шестёрок {grouped(space.total)}, считаю {grouped(total)}",
        flush=True,
    )
    done, ahead, boards, errors = _load()
    if done > total:
        done = total
        ahead = []
    next_index = done
    pending: dict = {}
    started = time.monotonic()
    workers = max(1, min(worker_count(), max(1, total - done)))
    ctx = multiprocessing.get_context("spawn")

    def completed() -> int:
        return done + sum(right - left for left, right in ahead)

    def emit() -> None:
        elapsed = max(time.monotonic() - started, 1e-6)
        rate = (completed() - done_at_start) / elapsed
        best = boards["overall"][0][0] if boards["overall"] else None
        print(
            f"посчитано {grouped(completed())} / {grouped(total)} "
            f"лучший без талантов {best if best is not None else '-'} "
            f"{rate:.0f} шестёрок/с",
            flush=True,
        )

    done_at_start = completed()
    if done < total:
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=ctx,
            initializer=init_worker,
            initargs=(space, items, sources, SULFURAS),
        ) as pool:
            while next_index < total or pending:
                while next_index < total and len(pending) < workers * 2:
                    while any(begin <= next_index < end for begin, end in ahead):
                        next_index = max(end for begin, end in ahead if begin <= next_index < end)
                    if next_index >= total:
                        break
                    stop_at = min(total, next_index + BATCH)
                    for begin, end in ahead:
                        if next_index < begin < stop_at:
                            stop_at = begin
                    pending[pool.submit(eval_span, next_index, stop_at)] = (next_index, stop_at, 0)
                    next_index = stop_at
                if not pending:
                    break
                ready, _ = wait(set(pending), timeout=20, return_when=FIRST_COMPLETED)
                if not ready:
                    emit()
                    continue
                for future in ready:
                    start_i, stop_i, attempts = pending.pop(future)
                    try:
                        payload = future.result()
                    except Exception as exc:
                        if attempts < 1:
                            pending[pool.submit(eval_span, start_i, stop_i)] = (start_i, stop_i, attempts + 1)
                        else:
                            errors += 1
                            print(f"срез {start_i}: {exc}", flush=True)
                            traceback.print_exc()
                            done = note_span(done, ahead, start_i, stop_i)
                        continue
                    errors += int(payload.get("errors") or 0)
                    if payload.get("error") and errors <= 8:
                        print(f"чанк {payload['error']}", flush=True)
                    for bare, index, group in payload.get("rows") or []:
                        _consider(boards, float(bare), int(index), group)
                    done = note_span(done, ahead, start_i, int(payload.get("done") or stop_i))
                _save(done, ahead, boards, errors, total)
                emit()
        _save(done, ahead, boards, errors, total)
    print("добиваю топ-10 талантами и глифами", flush=True)
    result = {
        "done": completed(),
        "total": total,
        "space": space.total,
        "errors": errors,
        "item_top": {key: [list(row) for row in rows] for key, rows in boards.items()},
    }
    if limit is None and completed() >= space.total:
        result.update(_finish(space, items, boards))
    atomic_write(
        data_dir() / "results" / "sulfuras-shadow-priest.json",
        json.dumps(result, ensure_ascii=False, indent=2),
    )
    return result


def _build_of(row: dict, by_code: dict):
    from sunken_sim.shadow import Build

    points = row["points"]
    return Build(
        frozenset(row["talents"]),
        frozenset(row["glyphs"]),
        tuple(by_code[code] for code in row["items"]),
        points["potency"],
        points["mastery"],
        points["crit"],
        points["luck"],
    )


def publish(result: dict) -> list[str]:
    """Replace a canvas pool only when the Sulfuras fight is ahead of it."""
    import sys

    sys.path.insert(0, str(ROOT / "extract"))
    from build_spec_canvas import write_all
    from run_hp import payload
    from sunken_sim.library import load_items
    from sunken_sim.search import shop_codes

    saved_path = ROOT / "extract" / "target-sims.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.exists() else {}
    by_code = {item.rawcode: item for item in load_items()}
    shop_ids = shop_codes()
    grouped_rows: dict[str, list] = {key: [] for key in POOL_KEY}
    for row in result.get("finished") or []:
        grouped_rows[row["pool"]].append(row)
    updated = []
    for group, key in POOL_KEY.items():
        rows = sorted(grouped_rows[group], key=lambda row: -row["dps"])
        if not rows:
            print(f"{key}: топ пуст", flush=True)
            continue
        best = rows[0]
        old = saved.get(key)
        old_dps = float(old["dps"]) if old else float("-inf")
        print(f"{key}: Sulfuras {best['dps']:.1f}, канвас {old_dps:.1f}", flush=True)
        if best["dps"] <= old_dps:
            continue
        label = {"5-mixed": "mixed", "5-shop": "shop", "5-drop": "drop"}[key]
        saved[key] = payload(label, _build_of(best, by_code), shop_ids, 5)
        updated.append(key)
    if not updated:
        print("канвас не менялся: Sulfuras не обошёл текущие бои", flush=True)
        return []
    saved_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    write_all()
    source = ROOT / "canvases" / "priest-sims.canvas.tsx"
    if CANVAS_COPY.parent.exists():
        shutil.copyfile(source, CANVAS_COPY)
    print("канвас обновлён: " + ", ".join(updated), flush=True)
    return updated


def main() -> None:
    raw = os.environ.get("SULF_LIMIT", "").strip()
    limit = int(raw) if raw else None
    result = run(limit)
    if limit is None and result["done"] >= result["space"]:
        publish(result)


if __name__ == "__main__":
    main()
