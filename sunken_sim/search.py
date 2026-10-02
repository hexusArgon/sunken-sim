"""Full single-target search.

Every priest talent triple, every glyph triple and every way to spend 5 skill
points is simulated. Every item is simulated when the six slots are filled and
again whenever a slot can be replaced. Nothing is ranked by reading tooltip text.
"""

from __future__ import annotations

import itertools
import os
import re
from concurrent.futures import ProcessPoolExecutor

from sunken_sim.library import Item, load_items
from sunken_sim.shadow import (
    FIGHT,
    SKILL_POINTS,
    Build,
    character,
    compile_events,
    score_compiled,
    simulate,
)

TALENTS = {
    "I0J6": "Prayer of Mending",
    "I0KF": "Dark Torment",
    "I0KG": "Smite",
    "I0HJ": "Divine Empowerment",
    "I0PS": "Catharsis",
    "I0PW": "Echo of Light",
    "I0SB": "Answered Prayers",
    "I0HL": "Psychic Link",
    "I0MR": "Tears of the Gods",
    "I0PU": "Insanity",
    "I0PV": "Power Word: Shield",
    "I0J1": "Holy Waters",
    "I0MJ": "Empyreal Blaze",
    "I0KH": "Blinding Light",
    "I0HP": "Cosmic Horrors",
    "I0SA": "Clairvoyance",
    "I0PT": "Dark Evangelism",
    "I0SC": "Touch of the Naaru",
}
GLYPHS = {
    "I0HC": "Animosity",
    "I0EN": "Arc Striking",
    "I0HA": "Astral Shift",
    "I0GZ": "Battle Frenzy",
    "I0OH": "Beastfury",
    "I0H6": "Blood Violence",
    "I0H1": "Bloodthirst",
    "I0HB": "Class Mastery",
    "I0EJ": "Fortune",
    "I0NB": "Commandership",
    "I0E8": "Crippling",
    "I0EI": "Dampening",
    "I0EM": "Deep Healing",
    "I0NA": "Devotion",
    "I0HD": "Diamond Skin",
    "I07B": "Fortitude",
    "I0JA": "Glass Cannon",
    "I0H3": "Hellfire",
    "I0CB": "Lightforce",
    "I0H2": "Magic Find",
    "I0GY": "Mana Shield",
    "I0OF": "Mindhaste",
    "I0EH": "Protecting",
    "I01H": "Provoking",
    "I0EL": "Recovery",
    "I0H4": "Renewal",
    "I0H0": "Replenishment",
    "I0OG": "Siphoning",
    "I0EK": "Supremacy",
    "I0H5": "Thunder",
    "I0OI": "Trepidation",
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


def _score_stats(compiled: dict, stats: dict, potency: float, crit: float, mastery_stat: float, luck: float) -> float:
    return score_compiled(compiled, stats, potency, crit, mastery_stat, luck) / FIGHT


def _best_points(counter: dict, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    bare = Build(build.talents, build.glyphs, build.items, 0, 0, 0, 0)
    stats = character(bare)
    compiled = compile_events(counter["events"], bare, stats)
    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    for crit_points, potency_points, luck_points, mastery_points in POINT_SPLITS:
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


def _init_worker(items: tuple[Item, ...], targets: int) -> None:
    global _ITEMS, _TARGETS
    _ITEMS = items
    _TARGETS = targets


def _eval_chunk(combos: list[tuple[tuple[str, ...], tuple[str, ...]]]) -> tuple:
    best_dps = -1.0
    best = None
    for talents, glyphs in combos:
        build = Build(frozenset(talents), frozenset(glyphs), _ITEMS, 0, 0)
        counter: dict = {"targets": _TARGETS}
        simulate(build, _TARGETS, counter)
        dps, points = _best_points(counter, build)
        if dps > best_dps:
            best_dps = dps
            best = (dps, talents, glyphs, points)
    return best


def _best_talents(items: tuple[Item, ...], targets: int = 1) -> tuple[float, Build]:
    talent_sets = list(itertools.combinations(sorted(TALENTS), 3))
    glyph_sets = list(itertools.combinations(sorted(GLYPHS), 3))
    combos = [(talents, glyphs) for talents in talent_sets for glyphs in glyph_sets]
    workers = max(1, (os.cpu_count() or 2) - 1)
    chunk = 2500
    parts = [combos[index : index + chunk] for index in range(0, len(combos), chunk)]
    best_dps = -1.0
    best_combo = None
    print(f"симуляций талантов и глифов {len(combos)}", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(items, targets)) as pool:
        for index, result in enumerate(pool.map(_eval_chunk, parts), start=1):
            if result is not None and result[0] > best_dps:
                best_dps = result[0]
                best_combo = result
            if index % 40 == 0:
                print(f"  {index}/{len(parts)} лучший {best_dps:.1f}", flush=True)
    assert best_combo is not None
    _dps, talents, glyphs, points = best_combo
    build = Build(frozenset(talents), frozenset(glyphs), items, points[1], points[3], points[0], points[2])
    return best_dps, build


def _dps_of(build: Build) -> float:
    counter: dict = {"targets": 1}
    simulate(build, 1, counter)
    return _best_points(counter, build)[0]


def _fill_items(base: Build, catalog: list[Item], targets: int = 1) -> Build:
    chosen: list[Item] = []
    points = (base.crit_points, base.potency_points, base.luck_points, base.mastery_points)
    for _slot in range(6):
        best_item = None
        best_dps = -1.0
        owned = {item.rawcode for item in chosen}
        for item in catalog:
            if item.rawcode in owned or not _equip_ok(chosen, item):
                continue
            trial = Build(base.talents, base.glyphs, tuple(chosen + [item]), points[1], points[3], points[0], points[2])
            counter: dict = {"targets": targets}
            simulate(trial, targets, counter)
            dps, new_points = _best_points(counter, trial)
            if dps > best_dps:
                best_dps = dps
                best_item = item
                points = new_points
        if best_item is None:
            break
        chosen.append(best_item)
    return Build(base.talents, base.glyphs, tuple(chosen), points[1], points[3], points[0], points[2])


def _swap_items(base: Build, catalog: list[Item], targets: int = 1) -> Build:
    chosen = list(base.items)
    points = (base.crit_points, base.potency_points, base.luck_points, base.mastery_points)
    counter: dict = {"targets": targets}
    simulate(base, targets, counter)
    best_dps, points = _best_points(counter, base)
    improved = True
    passes = 0
    while improved and passes < 4:
        improved = False
        passes += 1
        for slot in range(len(chosen)):
            owned = {item.rawcode for index, item in enumerate(chosen) if index != slot}
            for item in catalog:
                if item.rawcode in owned or item.rawcode == chosen[slot].rawcode:
                    continue
                if not _equip_ok(chosen, item, ignore=chosen[slot]):
                    continue
                trial_items = chosen.copy()
                trial_items[slot] = item
                trial = Build(base.talents, base.glyphs, tuple(trial_items), points[1], points[3], points[0], points[2])
                counter = {"targets": targets}
                simulate(trial, targets, counter)
                dps, new_points = _best_points(counter, trial)
                if dps > best_dps + 0.05:
                    best_dps = dps
                    chosen = trial_items
                    points = new_points
                    improved = True
    return Build(base.talents, base.glyphs, tuple(chosen), points[1], points[3], points[0], points[2])


def search_pool(catalog: list[Item], seed: Build, targets: int = 1) -> tuple[Build, float]:
    geared = _fill_items(seed, catalog, targets)
    geared = _swap_items(geared, catalog, targets)
    print(f"предметы готовы, {len(catalog)} в пуле, цели {targets}", flush=True)
    _dps, with_gear = _best_talents(geared.items, targets)
    print("таланты с предметами готовы", flush=True)
    if with_gear.talents != geared.talents or with_gear.glyphs != geared.glyphs:
        geared = _swap_items(with_gear, catalog, targets)
    else:
        geared = with_gear
    counter: dict = {"targets": targets}
    simulate(geared, targets, counter)
    dps, points = _best_points(counter, geared)
    final = Build(geared.talents, geared.glyphs, geared.items, points[1], points[3], points[0], points[2])
    return final, dps


def shop_codes() -> set[str]:
    body = _shop_body(_map_script())
    return set(re.findall(r"set udg_TasItemShop_Item='(....)'", body))


def _map_script() -> str:
    from pathlib import Path

    script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
    return script.replace("\r\n", "\n").replace("\r", "\n")


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


def pools_for(catalog: list[Item], hero_class: str = "Priest") -> tuple[list[Item], list[Item], list[Item]]:
    shop, drop, legendaries = split_catalog(catalog)
    foreign = set().union(*(codes for name, codes in class_item_codes().items() if name != hero_class))

    def allowed(item: Item) -> bool:
        return item.rawcode not in foreign and not is_quest_item(item)

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
