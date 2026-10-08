"""The chunk space for one hero, spec and item pool."""

from __future__ import annotations

import hashlib
import json
import os
import pickle

from farm.paths import data_dir
from farm.protocol import grouped
from farm.space import Piece, Space

CACHE_VERSION = 2
# Same eight talents as the current Shadow search.
SHADOW_TALENTS = ("I0HL", "I0HP", "I0KF", "I0PS", "I0PU", "I0SA", "I0SB", "I0SC")
RUNEMASTERY = "I0Q8"

_MEMORY: dict[tuple[str, str, str, str], tuple[Space, dict]] = {}
PRESETS = {"retribution-top89": "paladin-retribution-top89.json"}


def load(hero: str, spec: str, pool: str, preset: str | None = None) -> tuple[Space, dict]:
    key = (hero, spec, pool, preset or "")
    cached = _MEMORY.get(key)
    if cached is not None:
        return cached
    space, items = _from_disk(hero, spec, pool, preset)
    _MEMORY[key] = (space, items)
    return space, items


def _from_disk(hero: str, spec: str, pool: str, preset: str | None = None) -> tuple[Space, dict]:
    pieces, talents, glyphs, talent_names, glyph_names, items, picks_with = _parts(hero, spec, pool, preset)
    digest = _digest(pieces, talents, glyphs, picks_with, items)
    label = preset or pool
    path = data_dir() / "cache" / f"{hero}-{spec}-{label}-{digest}.pkl"
    if path.exists():
        try:
            with path.open("rb") as handle:
                space, stored = pickle.load(handle)
            if isinstance(space, Space) and space.total >= 0:
                print(f"пространство {hero} {spec} {pool}: {grouped(space.total)} чанков", flush=True)
                return space, stored
        except Exception:
            pass
    space = Space(
        pieces,
        talents,
        glyphs,
        picks_without=3,
        picks_with=picks_with,
        talent_names=talent_names,
        glyph_names=glyph_names,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as handle:
        pickle.dump((space, items), handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)
    print(f"пространство {hero} {spec} {pool}: {grouped(space.total)} чанков", flush=True)
    return space, items


def _parts(hero: str, spec: str, pool: str, preset: str | None = None):
    from sunken_sim.library import load_items
    from sunken_sim.mage import TALENTS as MAGE_TALENTS
    from sunken_sim.search import GLYPHS, TALENTS, _item_kind, pools_for
    from sunken_sim.shadow import MIND_AMPLIFIER

    catalog = load_items()
    by_code = {item.rawcode: item for item in catalog}
    if preset:
        return _preset_parts(hero, spec, preset, by_code)
    class_name = {"priest": "Priest", "mage": "Mage", "paladin": "Paladin"}[hero]
    shop, drop, legendaries = pools_for(catalog, class_name)
    if hero == "priest" and spec == "shadow":
        shop, drop, legendaries = _shadow_top(shop, drop, legendaries)
    chosen = {"mixed": shop + drop + legendaries, "shop": shop + legendaries, "drop": drop + legendaries}[pool]
    ordered: dict[str, object] = {}
    for item in chosen:
        ordered.setdefault(item.rawcode, item)
    if hero == "priest":
        amp = by_code.get(MIND_AMPLIFIER)
        if amp is None:
            raise RuntimeError("в карте нет Mind Amplifier X-8000")
        ordered.setdefault(MIND_AMPLIFIER, amp)
    if len(ordered) < 6:
        raise RuntimeError(f"в пуле {pool} меньше шести предметов")
    pieces = []
    items = {}
    for code in sorted(ordered):
        item = ordered[code]
        pieces.append(
            Piece(
                code,
                _item_kind(item),
                amp=code == MIND_AMPLIFIER,
                name=item.name,
            )
        )
        items[code] = item
    if hero == "mage":
        talents = sorted(code for code in MAGE_TALENTS if code != RUNEMASTERY)
        talent_names = MAGE_TALENTS
        picks_with = 3
    elif hero == "paladin":
        from sunken_sim.paladin import TALENTS as PALADIN_TALENTS

        talent_names = PALADIN_TALENTS
        talents = sorted(PALADIN_TALENTS)
        picks_with = 3
    else:
        talent_names = TALENTS
        talents = sorted(SHADOW_TALENTS if spec == "shadow" else TALENTS)
        missing = [code for code in talents if code not in talent_names]
        if missing:
            raise RuntimeError(f"нет имён талантов: {', '.join(missing)}")
        picks_with = 4
    glyphs = sorted(GLYPHS)
    return pieces, talents, glyphs, talent_names, dict(GLYPHS), items, picks_with


def _preset_parts(hero: str, spec: str, preset: str, by_code: dict):
    from pathlib import Path

    from sunken_sim.paladin import TALENTS as PALADIN_TALENTS
    from sunken_sim.search import GLYPHS, _item_kind
    from sunken_sim.shadow import MIND_AMPLIFIER

    filename = PRESETS.get(preset)
    if filename is None:
        raise RuntimeError(f"нет набора {preset}")
    path = Path(__file__).resolve().parents[1] / "extract" / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("hero") != hero or data.get("spec") != spec:
        raise RuntimeError(f"набор {preset} собран для {data.get('hero')} {data.get('spec')}")
    missing = [code for code in data["items"] if code not in by_code]
    if missing:
        raise RuntimeError("нет предметов: " + ", ".join(missing))
    unknown = [code for code in data["talents"] if code not in PALADIN_TALENTS]
    if unknown:
        raise RuntimeError("нет талантов: " + ", ".join(unknown))
    pieces = []
    items = {}
    for code in sorted(set(data["items"])):
        item = by_code[code]
        pieces.append(Piece(code, _item_kind(item), amp=code == MIND_AMPLIFIER, name=item.name))
        items[code] = item
    if len(pieces) < 6:
        raise RuntimeError(f"в наборе {preset} меньше шести предметов")
    talents = sorted(data["talents"])
    picks_with = 4 if any(piece.amp for piece in pieces) else 3
    return pieces, talents, sorted(GLYPHS), PALADIN_TALENTS, dict(GLYPHS), items, picks_with


def _shadow_top(shop, drop, legendaries):
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "extract" / "shadow-top100.json"
    if not path.exists():
        raise RuntimeError("нет extract/shadow-top100.json")
    allowed = {row["rawcode"] for row in json.loads(path.read_text(encoding="utf-8"))}
    shop = [item for item in shop if item.rawcode in allowed]
    drop = [item for item in drop if item.rawcode in allowed]
    legendaries = [item for item in legendaries if item.rawcode in allowed]
    kept = {item.rawcode for item in shop + drop + legendaries}
    missing = sorted(allowed - kept)
    if missing:
        raise RuntimeError("топ-100 нет в пуле: " + ", ".join(missing))
    return shop, drop, legendaries


def _digest(pieces, talents, glyphs, picks_with, items) -> str:
    digest = hashlib.sha1()
    digest.update(f"v{CACHE_VERSION}|{picks_with}|".encode())
    for piece in pieces:
        item = items[piece.code]
        digest.update(f"{piece.code}|{piece.kind}|{int(piece.amp)}|{item.tip}\0".encode())
    digest.update(("|".join(talents) + "\0" + "|".join(glyphs)).encode())
    return digest.hexdigest()[:16]
