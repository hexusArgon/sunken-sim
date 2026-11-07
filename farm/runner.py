"""Run a contiguous inclusive range and keep the top 10 DPS builds.

A chunk is always scored as items only. Talents, glyphs and skill points run
when that item DPS enters the top 10 of the same category: Shop + drop against
the overall ten, Shop only against the shop ten, Random drop against the drop
ten. Each category remembers its own ten item-only scores. Until a category
has ten, every chunk of that category is fully scored.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from farm.cpu import cpu_percent
from farm.paths import atomic_write, data_dir, file_lock
from farm.protocol import grouped, status_text
from farm.space import Space

_SPACE: Space | None = None
_ITEMS: dict = {}
_SOURCES: dict[str, str] = {}
_HERO = ""
_SPEC = ""
_TARGETS = 1
_BAR = None
_STOP = None
BATCH = 16384
from farm import admission as A

TOP_BARE = 10
BAR_KEYS = ("overall", "shop", "drop")
BAR_LABEL = {
    "overall": "Shop + drop",
    "shop": "Только Shop Item",
    "drop": "Только Random drop",
}


class ItemBar:
    """The ten best item-only DPS values seen so far, highest first."""

    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = sorted((float(value) for value in scores or []), reverse=True)[:TOP_BARE]

    def claim(self, bare: float) -> bool:
        bare = float(bare)
        if len(self.scores) >= TOP_BARE and bare <= self.scores[-1]:
            return False
        self.scores.append(bare)
        self.scores.sort(reverse=True)
        del self.scores[TOP_BARE:]
        return True


def bars_for(group: str | None) -> tuple[str, ...]:
    """Shop only and Random drop keep their own item-only top 10. Shop + drop is the overall ten."""
    if group == "shop":
        return ("overall", "shop")
    if group == "drop":
        return ("overall", "drop")
    return ("overall",)


def _as_bars(raw) -> dict[str, list[float]]:
    found = {key: [] for key in BAR_KEYS}
    if isinstance(raw, dict):
        for key in BAR_KEYS:
            found[key] = [float(value) for value in raw.get(key) or []]
        return found
    if isinstance(raw, list):
        found["overall"] = [float(value) for value in raw]
    return found


def _bars_from_rows(rows: list[dict]) -> dict[str, list[float]]:
    seen: set[int] = set()
    found = {key: [] for key in BAR_KEYS}
    for row in rows:
        if "item_dps" not in row:
            continue
        chunk = row.get("chunk")
        if chunk is not None:
            if int(chunk) in seen:
                continue
            seen.add(int(chunk))
        score = float(row["item_dps"])
        found["overall"].append(score)
        group = row.get("group")
        if group in ("shop", "drop"):
            found[group].append(score)
    return found


class CategoryBars:
    """Item-only top 10 remembered separately for Shop + drop, Shop only and Random drop."""

    def __init__(self, raw=None) -> None:
        stored = _as_bars(raw)
        self.bars = {key: ItemBar(stored[key]) for key in BAR_KEYS}

    def claim(self, bare: float, group: str | None) -> bool:
        admitted = False
        for key in bars_for(group):
            if self.bars[key].claim(bare):
                admitted = True
        return admitted

    def snapshot(self) -> dict[str, list[float]]:
        return {key: list(self.bars[key].scores) for key in BAR_KEYS}


def claim_item_bars(bare: float, group: str | None, chunk: int | None = None) -> bool:
    # Safe default and legacy callers fail open. Only explicit unsafe jobs prune.
    if _BAR is None:
        return True
    slots, lock = _BAR
    if slots.get('__policy__', A.ALL) != A.UNSAFE or chunk is None or any(len(slots[k]) < 3 for k in BAR_KEYS):
        return True
    with lock:
        before = A.Observations(_observations(slots))
        if not before.claim(chunk, bare, group):
            return False
        for key, rows in before.snapshot().items():
            scores, count, identities = slots[key]
            for i, row in enumerate(rows):
                scores[i], identities[i] = row['dps'], row['chunk']
            count.value = len(rows)
        return True


def _observations(slots):
    return {key: [{'chunk': int(slots[key][2][i]), 'dps': float(slots[key][0][i])}
                  for i in range(slots[key][1].value)]
            for key in BAR_KEYS if len(slots[key]) >= 3}


def item_bar_snapshot(slots, lock):
    with lock:
        return _observations(slots)


def add_one(value: int) -> int:
    return value + 1


def note_span(done_up_to: int, ahead: list[tuple[int, int]], start: int, stop: int) -> int:
    """Mark [start, stop) finished. Later spans sit in ahead until the gap closes."""
    if stop <= start or stop <= done_up_to:
        return done_up_to
    if start < done_up_to:
        start = done_up_to
    ranges = [(left, right) for left, right in ahead if right > done_up_to]
    ranges.append((start, stop))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for left, right in ranges:
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    index = 0
    while index < len(merged) and merged[index][0] <= done_up_to:
        if merged[index][1] > done_up_to:
            done_up_to = merged[index][1]
        index += 1
    ahead.clear()
    ahead.extend((left, right) for left, right in merged if left >= done_up_to)
    return done_up_to


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
        + (f"top{int(job['top'])}-" if job.get("top") else "")
        + f"{job['targets']}-{job['start']}-{job['end']}.json"
    )
    if job.get('search_schema') == A.SCHEMA:
        name = name[:-5] + '-' + A.suffix(job) + '.json'
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


def init_worker(space: Space, items: dict, sources: dict, hero: str, spec: str, targets: int, bar, stop) -> None:
    global _SPACE, _ITEMS, _SOURCES, _HERO, _SPEC, _TARGETS, _BAR, _STOP
    from sunken_sim.history import release

    release()
    _SPACE = space
    _ITEMS = items
    _SOURCES = sources
    _HERO = hero
    _SPEC = spec
    _TARGETS = targets
    _BAR = bar
    _STOP = stop


def _compact(rows: list[dict]) -> list[dict]:
    boards = Boards()
    for row in rows:
        boards.add(row)
    kept: list[dict] = []
    seen: set[int] = set()
    pools = [boards.overall, *boards.by_group.values()]
    for board in pools:
        for row in board.rows():
            chunk = int(row["chunk"])
            if chunk in seen:
                continue
            seen.add(chunk)
            kept.append(row)
    return kept


def eval_span(start: int, stop: int) -> dict:
    """Score [start, stop) inside this process. Skip rows stay here."""
    from farm.score import finish_sextuple, item_dps

    assert _SPACE is not None
    hits: list[dict] = []
    fights = 0
    errors = 0
    error = ""
    done = start
    for index in range(start, stop):
        if (index & 1023) == 0 and _STOP is not None and _STOP.is_set():
            break
        try:
            item_codes, _talent_codes, _glyph_codes = _SPACE.decode(index)
            equipped = tuple(_ITEMS[code] for code in item_codes)
            sources = [_SOURCES.get(item.rawcode, "drop") for item in equipped]
            group = build_group(sources)
            bare = item_dps(_HERO, _SPEC, _TARGETS, equipped)
            fights += 1
            if not claim_item_bars(bare, group, index):
                done = index + 1
                continue
            dps, talent_codes, glyph_codes, points, extra = finish_sextuple(
                _HERO,
                _SPEC,
                _TARGETS,
                equipped,
                _SPACE.talents,
                _SPACE.glyphs,
                _SPACE.picks_without,
                _SPACE.picks_with,
                _SPACE.glyph_picks,
            )
            fights += extra
            if isinstance(points, dict):
                esc_full = dict(points)
            else:
                crit, potency, luck, mastery = points
                esc_full = {"crit": crit, "potency": potency, "luck": luck, "mastery": mastery}
            hits.append(
                {
                    "dps": dps,
                    "item_dps": bare,
                    "fights": extra + 1,
                    "chunk": index,
                    "group": group,
                    "items": [
                        {"name": item.name, "code": item.rawcode, "source": source}
                        for item, source in zip(equipped, sources)
                    ],
                    "talents": sorted(_SPACE.talent_names.get(code, code) for code in talent_codes),
                    "glyphs": sorted(_SPACE.glyph_names.get(code, code) for code in glyph_codes),
                    "points": esc_full,
                }
            )
        except Exception as exc:
            errors += 1
            if not error:
                error = f"{index}: {exc}"
        done = index + 1
    return {"start": start, "done": done, "fights": fights, "hits": _compact(hits), "errors": errors, "error": error}


def eval_index(index: int) -> dict | None:
    from farm.score import finish_sextuple, item_dps

    assert _SPACE is not None
    item_codes, _talent_codes, _glyph_codes = _SPACE.decode(index)
    try:
        equipped = tuple(_ITEMS[code] for code in item_codes)
    except KeyError as exc:
        raise RuntimeError(f"нет предмета {exc}") from exc
    sources = [_SOURCES.get(item.rawcode, "drop") for item in equipped]
    group = build_group(sources)
    bare = item_dps(_HERO, _SPEC, _TARGETS, equipped)
    if not claim_item_bars(bare, group, index):
        return {"chunk": index, "fights": 1, "skip": True}
    dps, talent_codes, glyph_codes, points, fights = finish_sextuple(
        _HERO,
        _SPEC,
        _TARGETS,
        equipped,
        _SPACE.talents,
        _SPACE.glyphs,
        _SPACE.picks_without,
        _SPACE.picks_with,
        _SPACE.glyph_picks,
    )
    if isinstance(points, dict):
        esc_full = dict(points)
    else:
        crit, potency, luck, mastery = points
        esc_full = {"crit": crit, "potency": potency, "luck": luck, "mastery": mastery}
    return {
        "dps": dps,
        "item_dps": bare,
        "fights": fights + 1,
        "chunk": index,
        "group": group,
        "items": [
            {"name": item.name, "code": item.rawcode, "source": source}
            for item, source in zip(equipped, sources)
        ],
        "talents": sorted(_SPACE.talent_names.get(code, code) for code in talent_codes),
        "glyphs": sorted(_SPACE.glyph_names.get(code, code) for code in glyph_codes),
        "points": esc_full,
    }


def _load_spans(raw) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for item in raw or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            spans.append((int(item[0]), int(item[1])))
        else:
            spans.append((int(item), int(item) + 1))
    return spans


def _empty_bars() -> dict[str, list[float]]:
    return {key: [] for key in BAR_KEYS}


def _remembered_bars(saved: dict, rows: list[dict]) -> dict[str, list[float]]:
    raw = saved.get("item_bar")
    if isinstance(raw, dict) and raw:
        return _as_bars(raw)
    if isinstance(raw, list) and raw:
        return _as_bars(raw)
    return _bars_from_rows(rows)


def _merge_bars(left, right):
    """Idempotent merge of attributed observations; legacy floats are ignored."""
    return A.merge(left, right)


def _job_checkpoint_path(job):
    # Preserve original files and invalid legacy done watermarks byte-for-byte.
    name = job['id']
    if job.get('search_schema') == A.SCHEMA:
        name += '-' + A.suffix(job)
    return _checkpoint_path(name)


def _load_checkpoint(job: dict, boards: Boards) -> tuple[int, list[tuple[int, int]], int, dict[str, list[float]]]:
    path = _job_checkpoint_path(job)
    if not path.exists():
        return int(job["start"]), [], 0, _empty_bars()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return int(job["start"]), [], 0, _empty_bars()
    if saved.get("search_schema") != A.SCHEMA or not _same_job(saved, job):
        return int(job["start"]), [], 0, _empty_bars()
    rows = list(saved.get("top") or [])
    for row in rows:
        boards.overall.add(row)
    for group, key in GROUP_KEY.items():
        for row in saved.get(key) or []:
            boards.by_group[group].add(row)
            rows.append(row)
    done_up_to = int(saved.get("done_up_to", job["start"]))
    spans: list[tuple[int, int]] = []
    for start, stop in _load_spans(saved.get("ahead")):
        done_up_to = note_span(done_up_to, spans, start, stop)
    return done_up_to, spans, int(saved.get("errors") or 0), A.Observations(saved.get("item_observations")).snapshot()


def _same_job(saved: dict, job: dict) -> bool:
    if A.metadata(saved) != A.metadata(job):
        return False
    for key in ("start", "end", "hero", "spec", "pool", "targets"):
        if str(saved.get(key)) != str(job.get(key)):
            return False
    if str(saved.get("preset") or "") != str(job.get("preset") or ""):
        return False
    # checkpoints keep the item limit as top_n ("top" there is the leaderboard)
    saved_n = saved.get("top_n") if "top_n" in saved else 0
    job_n = job.get("top_n") if "top_n" in job else job.get("top") if not isinstance(job.get("top"), list) else 0
    return int(saved_n or 0) == int(job_n or 0)


def _merge_checkpoint(payload: dict, saved: dict | None) -> dict:
    """Keep the further watermark. A slower process must not roll the file backwards."""
    if not saved:
        return payload
    if not _same_job(saved, payload):
        return payload
    merged = dict(payload)
    watermark = max(int(saved.get('done_up_to') or 0), int(payload.get('done_up_to') or 0))
    spans = []
    for left, right in _load_spans(saved.get('ahead')) + _load_spans(payload.get('ahead')):
        watermark = note_span(watermark, spans, left, right)
    merged['done_up_to'], merged['ahead'] = watermark, [list(s) for s in spans]
    merged["errors"] = max(int(saved.get("errors") or 0), int(payload.get("errors") or 0))
    if payload.get('search_schema') == A.SCHEMA:
        merged['item_observations'] = _merge_bars(saved.get('item_observations'), payload.get('item_observations'))
        merged['item_bar'] = A.Observations(merged['item_observations']).scores()  # display-only compatibility
    else:
        # Legacy snapshots have no identities: preserve the farther snapshot, never concatenate.
        farther = saved if int(saved.get('done_up_to') or 0) > int(payload.get('done_up_to') or 0) else payload
        merged['item_bar'] = _as_bars(farther.get('item_bar'))
    boards = Boards()
    for row in list(saved.get("top") or []) + list(payload.get("top") or []):
        boards.overall.add(row)
    for group, key in GROUP_KEY.items():
        bucket = boards.by_group[group]
        for row in list(saved.get(key) or []) + list(payload.get(key) or []):
            bucket.add(row)
        merged[key] = bucket.rows()
    merged["top"] = boards.overall.rows()
    return merged


def _save_checkpoint(
    job: dict,
    done_up_to: int,
    ahead: list[tuple[int, int]],
    boards: Boards,
    errors: int,
    item_bar: dict[str, list[float]],
) -> None:
    payload = {
        "start": job["start"],
        "end": job["end"],
        "hero": job["hero"],
        "spec": job["spec"],
        "pool": job["pool"],
        "targets": job["targets"],
        "preset": job.get("preset") or "",
        "top_n": int(job.get("top") or 0),
        "done_up_to": done_up_to,
        "ahead": [[left, right] for left, right in ahead],
        "errors": errors,
        "item_bar": A.Observations(item_bar).scores(),
        "item_observations": item_bar,
        **A.metadata(job),
        "top": boards.overall.rows(),
    }
    for group, key in GROUP_KEY.items():
        payload[key] = boards.by_group[group].rows()
    path = _job_checkpoint_path(job)
    try:
        with file_lock(path.with_name(path.name + ".lock")):
            saved = None
            if path.exists():
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    saved = None
            atomic_write(path, json.dumps(_merge_checkpoint(payload, saved), ensure_ascii=False))
    except OSError as exc:
        print(f"чекпоинт не записался: {exc}", flush=True)


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
        **A.metadata(job),
        'global_optimum_proven': False,
        'admission_is_lossless': job.get('admission_policy', A.ALL) == A.ALL,
        'item_admission_complete': job.get('admission_policy', A.ALL) == A.ALL and not stopped and not errors and done >= int(job['end']) - int(job['start']) + 1,
        "about": A.description(job),
        "top": boards.ranked(boards.overall),
        "top_shop_random": boards.ranked(boards.by_group["shop_random"]),
        "top_shop": boards.ranked(boards.by_group["shop"]),
        "top_random": boards.ranked(boards.by_group["drop"]),
    }
    path = _result_path(job)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return str(path)


def _sweep(done_up_to: int, ahead: list[tuple[int, int]]) -> int:
    spans: list[tuple[int, int]] = []
    for start, stop in list(ahead):
        done_up_to = note_span(done_up_to, spans, start, stop)
    ahead.clear()
    ahead.extend(spans)
    return done_up_to


def run_job(job: dict, box: dict, tick, eval_fn=None) -> dict:
    """eval_fn: optional span scorer (same contract as eval_span); None = old CPU path."""
    from sunken_sim.history import release

    from farm.catalog import load

    space, items = load(job["hero"], job["spec"], job["pool"], job.get("preset") or None, job.get("top") or None)
    job = A.configure(job, space, items)
    print('search admission: ' + A.description(job), flush=True)
    start = int(job["start"])
    end_ex = int(job["end"]) + 1
    total = end_ex - start
    boards = Boards()
    done_up_to, ahead, errors, remembered = _load_checkpoint(job, boards)
    done_up_to = _sweep(max(done_up_to, start), ahead)
    ctx = multiprocessing.get_context("spawn")
    lock = ctx.Lock()
    slots = {'__policy__': job['admission_policy']}
    for key, rows in A.Observations(remembered).snapshot().items():
        scores = ctx.Array('d', TOP_BARE)
        identities = ctx.Array('q', TOP_BARE)
        count = ctx.Value('i', len(rows))
        for i, row in enumerate(rows):
            scores[i], identities[i] = row['dps'], row['chunk']
        slots[key] = (scores, count, identities)
    last_tick = 0.0
    started = time.monotonic()
    fights = 0
    window_fights = 0
    window_at = started
    rate = None
    rate_max = None
    rate_min = None

    def finished() -> int:
        return (done_up_to - start) + sum(stop - begin for begin, stop in ahead)

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
            top=job.get("top") or None,
            admission_policy=job["admission_policy"],
        )
        try:
            tick(text)
        except Exception as exc:
            print(f"статус не обновился: {exc}", flush=True)
        if not final:
            _save_checkpoint(job, done_up_to, ahead, boards, errors, item_bar_snapshot(slots, lock))
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

    sources = source_map(items)
    release()
    span = end_ex - done_up_to
    pool_size = max(1, min(worker_count(), span))
    next_index = done_up_to
    pending: dict = {}
    shown = 0
    stop_event = ctx.Event()
    span_fn = eval_fn or eval_span

    def submit_more(pool: ProcessPoolExecutor) -> None:
        nonlocal next_index
        while next_index < end_ex and len(pending) < pool_size * 2 and not box.get("stop"):
            while any(begin <= next_index < stop for begin, stop in ahead):
                next_index = max(stop for begin, stop in ahead if begin <= next_index < stop)
            if next_index >= end_ex:
                break
            stop_at = min(end_ex, next_index + BATCH)
            for begin, stop in ahead:
                if next_index < begin < stop_at:
                    stop_at = begin
            pending[pool.submit(span_fn, next_index, stop_at)] = (next_index, stop_at, 0)
            next_index = stop_at

    with ProcessPoolExecutor(
        max_workers=pool_size,
        mp_context=ctx,
        initializer=init_worker,
        initargs=(space, items, sources, job["hero"], job["spec"], int(job["targets"]), (slots, lock), stop_event),
    ) as pool:
        while True:
            if box.get("stop"):
                stop_event.set()
            if not box.get("stop"):
                submit_more(pool)
            if not pending:
                break
            ready, _ = wait(set(pending), timeout=5, return_when=FIRST_COMPLETED)
            if not ready:
                emit()
                continue
            for future in ready:
                start_i, stop_i, attempts = pending.pop(future)
                if future.cancelled():
                    continue
                try:
                    payload = future.result()
                except Exception as exc:
                    if attempts < 1 and not box.get("stop"):
                        pending[pool.submit(span_fn, start_i, stop_i)] = (start_i, stop_i, attempts + 1)
                    else:
                        errors += 1
                        if errors <= 5:
                            print(f"чанк {start_i}: {exc}", flush=True)
                            traceback.print_exc()
                        done_up_to = note_span(done_up_to, ahead, start_i, stop_i)
                    continue
                fights += int(payload.get("fights") or 0)
                errors += int(payload.get("errors") or 0)
                if payload.get("error") and errors <= 5:
                    print(f"чанк {payload['error']}", flush=True)
                for row in payload.get("hits") or []:
                    boards.add(row)
                reached = int(payload.get("done") or start_i)
                if reached > start_i:
                    done_up_to = note_span(done_up_to, ahead, start_i, reached)
                if reached < stop_i and not box.get("stop"):
                    pending[pool.submit(span_fn, reached, stop_i)] = (reached, stop_i, 0)
            if time.monotonic() - last_tick >= 5:
                emit()
                shown = finished()
        if shown != finished():
            emit()

    done = finished()
    stopped = bool(box.get("stop")) and done < total
    path = _write_result(job, boards, done, stopped, errors)
    emit(final=True)
    _save_checkpoint(job, done_up_to, ahead, boards, errors, item_bar_snapshot(slots, lock))
    return {"path": path, "done": done, "left": total - done, "stopped": stopped, "errors": errors}
