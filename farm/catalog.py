"""The chunk space for one hero, spec and item pool."""

from __future__ import annotations

import hashlib
import json
import os
import pickle

from farm.paths import data_dir
from farm.protocol import grouped
from farm.space import Piece, Space

CACHE_VERSION = 3
# Same eight talents as the current Shadow search.
SHADOW_TALENTS = ("I0HL", "I0HP", "I0KF", "I0PS", "I0PU", "I0SA", "I0SB", "I0SC")
RUNEMASTERY = "I0Q8"

_MEMORY: dict[tuple, tuple[Space, dict]] = {}
PRESETS = {
    "shadow-top80": "priest-shadow-top80.json",
    "discipline-top80": "priest-discipline-top80.json",
    "priest-holy-top80": "priest-holy-top80.json",
    "frost-top80": "mage-frost-top80.json",
    "arcane-top80": "mage-arcane-top80.json",
    "fire-top80": "mage-fire-top80.json",
    "retribution-top80": "paladin-retribution-top80.json",
    "protection-top80": "paladin-protection-top80.json",
    "paladin-holy-top80": "paladin-holy-top80.json",
    "restoration-top80": "shaman-restoration-top80.json",
    "enhancement-top80": "shaman-enhancement-top80.json",
    "elemental-top80": "shaman-elemental-top80.json",
    # legacy aliases kept for old jobs / local runs
    "retribution-top79": "paladin-retribution-top79.json",
    "retribution-top89": "paladin-retribution-top89.json",
    "protection-top89": "paladin-protection-top89.json",
}


def load(hero: str, spec: str, pool: str, preset: str | None = None, top: int | None = None) -> tuple[Space, dict]:
    top = int(top) if top else None
    key = (hero, spec, pool, preset or "", top or 0)
    cached = _MEMORY.get(key)
    if cached is not None:
        return cached
    if preset and preset.startswith("force:"):
        # top-N pool with these items always worn (farm.forced_pair), e.g. "force:I0BR+I04F"
        from farm.forced_pair import ForcedPieces

        if not top:
            raise RuntimeError("для force: нужен top")
        base, items = load(hero, spec, pool, None, top)
        forced = tuple(code for code in preset[len("force:"):].split("+") if code)
        space = ForcedPieces(base.pieces, base.talents, base.glyphs, forced=forced,
                             picks_without=base.picks_without, picks_with=base.picks_with,
                             glyph_picks=base.glyph_picks, talent_names=base.talent_names,
                             glyph_names=base.glyph_names)
        print(f"пространство {hero} {spec} {pool} {preset}: {grouped(space.total)} чанков", flush=True)
        _MEMORY[key] = (space, items)
        return space, items
    space, items = _from_disk(hero, spec, pool, preset, top)
    _MEMORY[key] = (space, items)
    return space, items


def _from_disk(hero: str, spec: str, pool: str, preset: str | None = None, top: int | None = None) -> tuple[Space, dict]:
    pieces, talents, glyphs, talent_names, glyph_names, items, picks_with = _parts(hero, spec, pool, preset, top)
    pieces = _scan_order(hero, pieces)
    picks_without = min(3, len(talents))
    picks_with = min(picks_with, len(talents))
    digest = _digest(pieces, talents, glyphs, picks_with, items)
    label = preset or (f"{pool}-top{top}" if top else pool)
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
        picks_without=picks_without,
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


def _parts(hero: str, spec: str, pool: str, preset: str | None = None, top: int | None = None):
    from sunken_sim.library import load_items
    from sunken_sim.mage import TALENTS as MAGE_TALENTS
    from sunken_sim.search import GLYPHS, TALENTS, _item_kind, pools_for
    from sunken_sim.shadow import MIND_AMPLIFIER

    catalog = load_items()
    by_code = {item.rawcode: item for item in catalog}
    if top:
        return _top_parts(hero, spec, pool, int(top), by_code)
    if preset:
        return _preset_parts(hero, spec, preset, by_code)
    if hero not in ("priest", "mage", "paladin", "shaman"):
        raise RuntimeError(f"для {hero} укажи top (10…250)")
    class_name = {"priest": "Priest", "mage": "Mage", "paladin": "Paladin", "shaman": "Shaman"}[hero]
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
    elif hero == "shaman":
        from sunken_sim.shaman import TALENTS as SHAMAN_TALENTS

        talent_names = SHAMAN_TALENTS
        talents = sorted(SHAMAN_TALENTS)
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


def _top_parts(hero: str, spec: str, pool: str, top: int, by_code: dict):
    from farm.top import MIND_AMPLIFIER, top_items, top_talents
    from sunken_sim.search import GLYPHS, _item_kind

    if MIND_AMPLIFIER not in by_code:
        raise RuntimeError("в карте нет Mind Amplifier X-8000")
    codes = top_items(hero, spec, top, pool, known=set(by_code))
    talents = top_talents(hero, spec)
    if not talents:
        raise RuntimeError(f"у {hero} {spec} нет талантов выше голого героя")
    from farm.top import _talent_names

    talent_names = _talent_names(hero)
    pieces = []
    items = {}
    for code in sorted(set(codes)):
        item = by_code[code]
        pieces.append(Piece(code, _item_kind(item), amp=code == MIND_AMPLIFIER, name=item.name))
        items[code] = item
    if len(pieces) < 6:
        raise RuntimeError(f"в топ-{top} меньше шести предметов")
    picks_with = 4 if any(piece.amp for piece in pieces) else 3
    return pieces, talents, sorted(GLYPHS), talent_names, dict(GLYPHS), items, picks_with


def _preset_parts(hero: str, spec: str, preset: str, by_code: dict):
    from pathlib import Path

    from sunken_sim.mage import TALENTS as MAGE_TALENTS
    from sunken_sim.paladin import TALENTS as PALADIN_TALENTS
    from sunken_sim.search import GLYPHS, TALENTS, _item_kind
    from sunken_sim.shaman import TALENTS as SHAMAN_TALENTS
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
    talent_names = {
        "mage": MAGE_TALENTS,
        "paladin": PALADIN_TALENTS,
        "priest": TALENTS,
        "shaman": SHAMAN_TALENTS,
    }[hero]
    unknown = [code for code in data["talents"] if code not in talent_names]
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
    picks_with = 3 if hero == "mage" else (4 if any(piece.amp for piece in pieces) else 3)
    return pieces, talents, sorted(GLYPHS), talent_names, dict(GLYPHS), items, picks_with


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


def _scan_order(hero: str, pieces: list) -> list:
    """Dragon Sentinel: items with their own branch in the GPU kernel come first.

    The unranking changes the lowest piece indices slowest, so neighbouring chunks (one GPU wave) then share
    these items and run the same branches. The set of builds and every build's DPS are unchanged; only the chunk
    numbering (and with it the cache digest) is different.
    """
    if hero != "dragon_sentinel":
        return pieces
    from farm.hybrid.dragon_sentinel_cl import SPECIAL_BITS

    key = [piece for piece in pieces if piece.code in SPECIAL_BITS]
    rest = [piece for piece in pieces if piece.code not in SPECIAL_BITS]
    return key + rest


def _digest(pieces, talents, glyphs, picks_with, items) -> str:
    digest = hashlib.sha1()
    digest.update(f"v{CACHE_VERSION}|{picks_with}|".encode())
    for piece in pieces:
        item = items[piece.code]
        digest.update(f"{piece.code}|{piece.kind}|{int(piece.amp)}|{item.tip}\0".encode())
    digest.update(("|".join(talents) + "\0" + "|".join(glyphs)).encode())
    return digest.hexdigest()[:16]
