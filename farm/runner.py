"""Run a contiguous inclusive range and keep the top 10 DPS builds."""

from __future__ import annotations

import json
import multiprocessing
import os
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from farm.cpu import cpu_percent
from farm.paths import atomic_write, data_dir
from farm.protocol import grouped, status_text
from farm.space import Space

_SPACE: Space | None = None
_ITEMS: dict = {}
_SOURCES: dict[str, str] = {}
_HERO = ""
_SPEC = ""
_TARGETS = 1


def add_one(value: int) -> int:
    return value + 1


def note_finished(done_up_to: int, ahead: set[int], index: int) -> int:
    if index < done_up_to or index in ahead:
        return done_up_to
    if index != done_up_to:
        ahead.add(index)
        return done_up_to
    done_up_to += 1
    while done_up_to in ahead:
        ahead.remove(done_up_to)
        done_up_to += 1
    return done_up_to


class Board:
    def __init__(self) -> None:
        self.by_chunk: dict[int, dict] = {}

    def add(self, row: dict) -> None:
        stored = dict(row)
        stored.pop("place", None)
        self.by_chunk[int(stored["chunk"])] = stored
        ranked = sorted(self.by_chunk.values(), key=lambda item: (-item["dps"], item["chunk"]))
        self.by_chunk = {item["chunk"]: item for item in ranked[:10]}

    def rows(self) -> list[dict]:
        return sorted(self.by_chunk.values(), key=lambda item: (-item["dps"], item["chunk"]))

    def best(self) -> float | None:
        found = self.rows()
        if not found:
            return None
        return float(found[0]["dps"])


GROUPS = ("shop_random", "shop", "drop")
GROUP_KEY = {"shop_random": "top_shop_random", "shop": "top_shop", "drop": "top_random"}


def build_group(sources: list[str]) -> str | None:
    """Shop+Random, Shop only, or Random only. Legendaries fit in every list."""
    kinds = {source for source in sources if source != "legendary"}
    if kinds == {"shop", "drop"}:
        return "shop_random"
    if kinds == {"shop"}:
        return "shop"
    if kinds == {"drop"}:
        return "drop"
    return None


class Boards:
    def __init__(self) -> None:
        self.overall = Board()
        self.by_group = {group: Board() for group in GROUPS}

    def add(self, row: dict) -> None:
        self.overall.add(row)
        group = row.get("group")
        if group in self.by_group:
            self.by_group[group].add(row)

    def best(self) -> float | None:
        return self.overall.best()

    def ranked(self, board: Board) -> list[dict]:
        top = []
        for place, row in enumerate(board.rows(), start=1):
            stored = dict(row)
            stored["place"] = place
            top.append(stored)
        return top


def worker_count() -> int:
    raw = os.environ.get("FARM_WORKERS", "").strip()
    if raw:
        return max(1, int(raw))
    cores = os.cpu_count() or 1
    return max(1, cores - 1)


def _checkpoint_path(job_id: str):
    return data_dir() / "checkpoints" / f"{job_id}.json"


def _result_path(job: dict):
    name = (
        f"{job['worker']}-{job['hero']}-{job['spec']}-{job['pool']}-"
        f"{job['targets']}-{job['start']}-{job['end']}.json"
    )
    return data_dir() / "results" / name


def source_map(items: dict) -> dict[str, str]:
    from sunken_sim.search import LEGENDARIES, shop_codes

    sold = shop_codes()
    found = {}
    for code, item in items.items():
        if code in LEGENDARIES:
            found[code] = "legendary"
        elif str(getattr(item, "tip", "")).startswith("Shop Item") or code in sold:
            found[code] = "shop"
        else:
            found[code] = "drop"
    return found


def init_worker(space: Space, items: dict, sources: dict, hero: str, spec: str, targets: int) -> None:
    global _SPACE, _ITEMS, _SOURCES, _HERO, _SPEC, _TARGETS
    from sunken_sim.history import release

    release()
    _SPACE = space
    _ITEMS = items
    _SOURCES = sources
    _HERO = hero
    _SPEC = spec
    _TARGETS = targets


def eval_index(index: int) -> dict:
    from sunken_sim.shadow import Build

    from farm.score import score_build

    assert _SPACE is not None
    item_codes, talent_codes, glyph_codes = _SPACE.decode(index)
    try:
        equipped = tuple(_ITEMS[code] for code in item_codes)
    except KeyError as exc:
        raise RuntimeError(f"нет предмета {exc}") from exc
    build = Build(frozenset(talent_codes), frozenset(glyph_codes), equipped, 0, 0, 0, 0)
    dps, points, fights = score_build(_HERO, _SPEC, _TARGETS, build)
    crit, potency, luck, mastery = points
    sources = [_SOURCES.get(item.rawcode, "drop") for item in equipped]
    return {
        "dps": dps,
        "fights": fights,
        "chunk": index,
        "group": build_group(sources),
        "items": [
            {"name": item.name, "code": item.rawcode, "source": source}
            for item, source in zip(equipped, sources)
        ],
        "talents": sorted(_SPACE.talent_names.get(code, code) for code in talent_codes),
        "glyphs": sorted(_SPACE.glyph_names.get(code, code) for code in glyph_codes),
        "points": {"crit": crit, "potency": potency, "luck": luck, "mastery": mastery},
    }


def _load_checkpoint(job: dict, boards: Boards) -> tuple[int, set[int], int]:
    path = _checkpoint_path(job["id"])
    if not path.exists():
        return int(job["start"]), set(), 0
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return int(job["start"]), set(), 0
    same = all(saved.get(key) == job.get(key) for key in ("start", "end", "hero", "spec", "pool", "targets", "preset"))
    if not same:
        return int(job["start"]), set(), 0
    for row in saved.get("top") or []:
        boards.overall.add(row)
    for group, key in GROUP_KEY.items():
        for row in saved.get(key) or []:
            boards.by_group[group].add(row)
    ahead = {int(index) for index in saved.get("ahead") or []}
    return int(saved.get("done_up_to", job["start"])), ahead, int(saved.get("errors") or 0)


def _save_checkpoint(job: dict, done_up_to: int, ahead: set[int], boards: Boards, errors: int) -> None:
    payload = {
        "start": job["start"],
        "end": job["end"],
        "hero": job["hero"],
        "spec": job["spec"],
        "pool": job["pool"],
        "targets": job["targets"],
        "preset": job.get("preset") or "",
        "done_up_to": done_up_to,
        "ahead": sorted(ahead),
        "errors": errors,
        "top": boards.overall.rows(),
    }
    for group, key in GROUP_KEY.items():
        payload[key] = boards.by_group[group].rows()
    atomic_write(_checkpoint_path(job["id"]), json.dumps(payload, ensure_ascii=False))


def _write_result(job: dict, boards: Boards, done: int, stopped: bool, errors: int) -> str:
    payload = {
        "worker": job["worker"],
        "hero": job["hero"],
        "spec": job["spec"],
        "pool": job["pool"],
        "targets": job["targets"],
        "start": job["start"],
        "end": job["end"],
        "done": done,
        "stopped": stopped,
        "errors": errors,
        "about": (
            "Чанк — одна шестёрка предметов, таланты и глифы. DPS после лучших пяти очков. "
            "top — общий топ-10. top_shop_random — и магазин, и случайный дроп. "
            "top_shop — только магазин. top_random — только случайный дроп. "
            "Легендарки входят в любой из трёх списков."
        ),
        "top": boards.ranked(boards.overall),
        "top_shop_random": boards.ranked(boards.by_group["shop_random"]),
        "top_shop": boards.ranked(boards.by_group["shop"]),
        "top_random": boards.ranked(boards.by_group["drop"]),
    }
    path = _result_path(job)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return str(path)


def _sweep(done_up_to: int, ahead: set[int]) -> int:
    while done_up_to in ahead:
        ahead.remove(done_up_to)
        done_up_to += 1
    return done_up_to


def run_job(job: dict, box: dict, tick) -> dict:
    from sunken_sim.history import release

    from farm.catalog import load

    start = int(job["start"])
    end_ex = int(job["end"]) + 1
    total = end_ex - start
    boards = Boards()
    done_up_to, ahead, errors = _load_checkpoint(job, boards)
    done_up_to = _sweep(max(done_up_to, start), ahead)
    last_tick = 0.0
    started = time.monotonic()
    fights = 0
    window_fights = 0
    window_at = started
    rate = None
    rate_max = None
    rate_min = None

    def finished() -> int:
        return (done_up_to - start) + len(ahead)

    def emit(final: bool = False) -> None:
        nonlocal last_tick, window_fights, window_at, rate, rate_max, rate_min
        now = time.monotonic()
        elapsed = now - started
        span = now - window_at
        if span >= 1 and fights > window_fights:
            rate = (fights - window_fights) / span
            rate_max = rate if rate_max is None else max(rate_max, rate)
            rate_min = rate if rate_min is None else min(rate_min, rate)
            window_fights = fights
            window_at = now
        done = finished()
        remaining = None
        if done and elapsed > 0 and total > done:
            remaining = elapsed * (total - done) / done
        text = status_text(
            worker=job["worker"],
            hero=job["hero"],
            spec=job["spec"],
            pool=job["pool"],
            targets=int(job["targets"]),
            start=start,
            end=int(job["end"]),
            done=done,
            left=total - done,
            best=boards.best(),
            errors=errors,
            final=final,
            stopped=bool(box.get("stop")) and done < total,
            elapsed=elapsed,
            remaining=remaining,
            rate=rate,
            rate_max=rate_max,
            rate_min=rate_min,
            cpu=cpu_percent(),
        )
        try:
            tick(text)
        except Exception as exc:
            print(f"статус не обновился: {exc}", flush=True)
        if not final:
            _save_checkpoint(job, done_up_to, ahead, boards, errors)
        print(
            f"{job['worker']} посчитано {grouped(done)} осталось {grouped(total - done)} "
            f"лучший {boards.best() if boards.best() is not None else '-'}",
            flush=True,
        )
        last_tick = time.monotonic()

    if box.get("stop") and finished() == 0:
        return {"path": "", "done": 0, "left": total, "stopped": True, "errors": errors}
    emit()
    if box.get("stop"):
        done = finished()
        path = _write_result(job, boards, done, True, errors)
        emit(final=True)
        return {"path": path, "done": done, "left": total - done, "stopped": True, "errors": errors}
    if done_up_to >= end_ex:
        path = _write_result(job, boards, finished(), False, errors)
        emit(final=True)
        return {"path": path, "done": finished(), "left": 0, "stopped": False, "errors": errors}

    space, items = load(job["hero"], job["spec"], job["pool"], job.get("preset") or None)
    sources = source_map(items)
    release()
    ctx = multiprocessing.get_context("spawn")
    span = end_ex - done_up_to
    pool_size = max(1, min(worker_count(), span))
    next_index = done_up_to
    pending: dict = {}
    shown = 0

    def submit_more(pool: ProcessPoolExecutor) -> None:
        nonlocal next_index, done_up_to
        while next_index < end_ex and len(pending) < pool_size * 2 and not box.get("stop"):
            index = next_index
            next_index += 1
            if index in ahead:
                continue
            pending[pool.submit(eval_index, index)] = index
        done_up_to = _sweep(done_up_to, ahead)

    with ProcessPoolExecutor(
        max_workers=pool_size,
        mp_context=ctx,
        initializer=init_worker,
        initargs=(space, items, sources, job["hero"], job["spec"], int(job["targets"])),
    ) as pool:
        while True:
            if not box.get("stop"):
                submit_more(pool)
            if not pending:
                break
            if box.get("stop"):
                for future in list(pending):
                    if future.cancel():
                        pending.pop(future, None)
                if not pending:
                    break
            ready, _ = wait(set(pending), timeout=5, return_when=FIRST_COMPLETED)
            if not ready:
                emit()
                continue
            for future in ready:
                index = pending.pop(future)
                if future.cancelled():
                    continue
                try:
                    row = future.result()
                except Exception as exc:
                    errors += 1
                    if errors <= 5:
                        print(f"чанк {index}: {exc}", flush=True)
                        traceback.print_exc()
                    row = None
                if row is not None:
                    boards.add(row)
                    fights += int(row.get("fights") or 0)
                done_up_to = note_finished(done_up_to, ahead, index)
            done_up_to = _sweep(done_up_to, ahead)
            if time.monotonic() - last_tick >= 5:
                emit()
                shown = finished()
        if shown != finished():
            emit()

    done = finished()
    stopped = bool(box.get("stop")) and done < total
    path = _write_result(job, boards, done, stopped, errors)
    emit(final=True)
    _save_checkpoint(job, done_up_to, ahead, boards, errors)
    return {"path": path, "done": done, "left": total - done, "stopped": stopped, "errors": errors}
