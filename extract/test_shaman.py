"""Check shaman ability formulas and talent/spec interactions against the triggers."""

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import sunken_sim.shaman as shaman
from sunken_sim.library import Item, load_items
from sunken_sim.shaman import (
    TALENT_ANCESTRAL,
    TALENT_BLOODLUST,
    TALENT_CHAIN_REACTION,
    TALENT_FLASH,
    TALENT_FURY,
    TALENT_FUSION,
    TALENT_GUIDANCE,
    TALENT_LANDSLIDE,
    TALENT_MOLTEN_BLAST,
    TALENT_OVERCHARGE,
    TALENT_SPIRIT_CALL,
    TALENT_STORM_INFUSION,
    TALENT_STORM_WARD,
    TALENT_STORMSTRIKE,
    TALENT_THUNDERSTORM,
    TALENT_TIDAL_WAVES,
    TALENT_TOTEM_MASTERY,
    TALENT_WRATH,
    TALENTS,
    simulate,
)
from sunken_sim.shadow import Build, armor_taken

SPECS = ("restoration", "enhancement", "elemental")
TAKEN = armor_taken(15)
INT = 37
AGI = 21
CHAIN = 70.0 + 1.60 * INT
SHIELD = 20.0 + 0.30 * INT
LAVA = 100.0 + 2.50 * INT
AD = 13.0 + 0.75 * INT
LCL = (8.0 + 0.15 * AGI) / 100.0
FAILS: list[str] = []


def fail(text: str) -> None:
    FAILS.append(text)
    print("FAIL", text)


def close(actual: float, expected: float, label: str, tol: float = 1e-4) -> None:
    if abs(actual - expected) > tol:
        fail(f"{label}: {actual:.6f} != {expected:.6f}")


def build(talents=(), items=(), potency=0, mastery=0, crit=0, luck=0) -> Build:
    return Build(frozenset(talents), frozenset(), tuple(items), potency, mastery, crit, luck)


def fight(spec: str, talents=(), items=(), targets=5, seconds=30.0, potency=0, mastery=0, crit=0, luck=0, bound=None):
    shaman.FIGHT = seconds
    try:
        return simulate(build(talents, items, potency, mastery, crit, luck), targets, spec, bound)
    finally:
        shaman.FIGHT = 30.0


def source(report, name: str) -> float:
    return report.sources.get(name, 0.0)


def times(report, name: str) -> list[float]:
    return [moment for moment, spell in report.actions if spell == name]


def gear(code: str) -> Item:
    return Item(code, code, "")


def package(raw: float, count: int, overcharge: bool, scale: float = 1.0, weight: float = 1.0) -> float:
    if count <= 0 or weight <= 0:
        return 0.0
    primary = raw * (1.40 if overcharge else 1.0) * scale
    other = raw * scale
    hits = primary * weight
    if count > 1:
        hits += other * weight * (count - 1)
    return hits * TAKEN


def test_short_windows() -> None:
    resto = fight("restoration", seconds=2.4)
    close(source(resto, "Chain Lightning"), package(CHAIN, 5, False), "resto chain, 5 целей, одно окно")
    close(source(resto, "Lesser Chain Lightning"), package(CHAIN, 3, False, 0.5, LCL), "resto lesser")
    close(source(resto, "Lightning Shield"), 4 * SHIELD * TAKEN, "resto shield, 3 входящих + удар")
    close(source(resto, "Автоатака"), AD * TAKEN, "resto автоатака")
    close(source(resto, "Feral Spirit"), 0.0, "духи ещё не взмахнули")
    close(source(resto, "Stormfury"), 0.0, "resto без stormfury")
    close(source(resto, "Lava Burst"), 0.0, "resto без lava")
    close(source(resto, "Liquid Magma"), 0.0, "resto без магмы")

    enh = fight("enhancement", seconds=2.4)
    raw = CHAIN * 1.08
    chance = LCL + 0.10
    close(source(enh, "Chain Lightning"), package(raw, 5, False), "enh chain ×1.08")
    close(source(enh, "Lesser Chain Lightning"), package(raw, 3, False, 0.5, chance), "enh lesser +10")
    close(source(enh, "Stormfury"), package(raw, 3, False, 0.30) + package(raw, 3, False, 0.30, chance), "enh stormfury")
    close(source(enh, "Автоатака"), source(resto, "Автоатака"), "enh автоатака как у resto")

    over = fight("enhancement", (TALENT_OVERCHARGE,), seconds=2.4)
    close(source(over, "Chain Lightning") / source(enh, "Chain Lightning"), 5.4 / 5.0, "overcharge только по основной из 5")
    close(source(over, "Lesser Chain Lightning") / source(enh, "Lesser Chain Lightning"), 3.4 / 3.0, "overcharge lesser 3 цели")
    close(source(over, "Stormfury") / source(enh, "Stormfury"), 3.4 / 3.0, "overcharge stormfury")
    close(source(over, "Автоатака"), source(enh, "Автоатака"), "overcharge не трогает автоатаку")
    close(source(over, "Lightning Shield"), source(enh, "Lightning Shield"), "overcharge не трогает щит")

    ward = fight("restoration", (TALENT_STORM_WARD,), seconds=2.4)
    close(source(ward, "Lightning Shield") / source(resto, "Lightning Shield"), 1.10, "storm ward ×1.10, лишние заряды ещё не потрачены")
    close(source(ward, "Chain Lightning"), source(resto, "Chain Lightning"), "storm ward не меняет chain")

    elemental = fight("elemental", seconds=1.0)
    close(source(elemental, "Lightning Shield"), 8 * SHIELD * 1.05 * TAKEN, "elemental shield ×1.05, 1 входящий + 7 зарядов")
    close(source(elemental, "Lava Burst"), LAVA * (1.0 + 0.08 * 7) * TAKEN, "lava ×(1+0.08×7)")
    close(source(elemental, "Feral Spirit"), 0.0, "elemental без духов")
    close(source(elemental, "Chain Lightning"), 0.0, "chain ещё не долетел до удара")

    fury = fight("elemental", (TALENT_FURY,), seconds=1.0)
    close(source(fury, "Lava Burst") / source(elemental, "Lava Burst"), 1.18, "elemental fury ×1.18")
    close(source(fury, "Lightning Shield"), source(elemental, "Lightning Shield"), "fury не меняет удары щита")

    ward_ele = fight("elemental", (TALENT_STORM_WARD,), seconds=1.0)
    close(source(ward_ele, "Lightning Shield"), 11 * SHIELD * 1.05 * 1.10 * TAKEN, "ward: 11 ударов щита, ×1.05 и ×1.10")
    close(source(ward_ele, "Lava Burst"), LAVA * (1.0 + 0.08 * 10) * TAKEN, "lava от 10 зарядов")

    both = fight("elemental", (TALENT_FURY, TALENT_STORM_WARD), seconds=1.0)
    close(source(both, "Lava Burst") / source(ward_ele, "Lava Burst"), 1.18, "fury поверх ward")
    close(source(both, "Lightning Shield"), source(ward_ele, "Lightning Shield"), "fury не меняет щит поверх ward")

    for targets, chain_n, lesser_n in ((1, 1, 1), (2, 2, 2), (4, 4, 3), (5, 5, 3)):
        row = fight("restoration", targets=targets, seconds=2.4)
        close(source(row, "Chain Lightning"), package(CHAIN, chain_n, False), f"chain цели {targets}")
        close(source(row, "Lesser Chain Lightning"), package(CHAIN, lesser_n, False, 0.5, LCL), f"lesser цели {targets}")


def test_mastery_points() -> None:
    for spec in SPECS:
        bare = fight(spec)
        pointed = fight(spec, mastery=10)
        if spec == "restoration":
            for name in bare.sources:
                close(source(pointed, name), source(bare, name), f"resto mastery не входит в {name}")
        elif spec == "enhancement":
            ratio = 1.13 / 1.08
            for name in ("Chain Lightning", "Lesser Chain Lightning", "Stormfury"):
                close(source(pointed, name) / source(bare, name), ratio, f"enh mastery {name}")
            for name in ("Автоатака", "Lightning Shield", "Feral Spirit"):
                close(source(pointed, name), source(bare, name), f"enh mastery не входит в {name}")
        else:
            close(source(pointed, "Chain Lightning"), source(bare, "Chain Lightning"), "elemental chain без mastery")
            close(source(pointed, "Автоатака"), source(bare, "Автоатака"), "elemental авто без mastery")
            close(source(pointed, "Lightning Shield") / source(bare, "Lightning Shield"), 1.11 / 1.05, "elemental shield mastery")
            close(source(pointed, "Lava Burst") / source(bare, "Lava Burst"), 1.08, "elemental lava mastery")
            close(source(pointed, "Liquid Magma") / source(bare, "Liquid Magma"), (38.5 + 10) / 38.5, "magma +10 mastery")


def test_potency_not_inside_overcharge() -> None:
    base = fight("enhancement")
    pot = fight("enhancement", potency=5)
    over = fight("enhancement", (TALENT_OVERCHARGE,))
    both = fight("enhancement", (TALENT_OVERCHARGE,), potency=5)
    close(
        source(both, "Chain Lightning") - source(over, "Chain Lightning"),
        source(pot, "Chain Lightning") - source(base, "Chain Lightning"),
        "potency chain не умножается overcharge",
    )
    close(
        source(both, "Lesser Chain Lightning") - source(over, "Lesser Chain Lightning"),
        source(pot, "Lesser Chain Lightning") - source(base, "Lesser Chain Lightning"),
        "potency lesser не умножается overcharge",
    )


def test_spec_gates() -> None:
    bare = {spec: fight(spec) for spec in SPECS}
    expect_zero = {
        "restoration": ("Lava Burst", "Liquid Magma", "Stormfury"),
        "enhancement": ("Lava Burst", "Liquid Magma"),
        "elemental": ("Feral Spirit", "Stormfury"),
    }
    for spec, names in expect_zero.items():
        for name in names:
            close(source(bare[spec], name), 0.0, f"{spec} без {name}")
    if not (source(bare["enhancement"], "Chain Lightning") > source(bare["restoration"], "Chain Lightning")):
        fail("enhancement chain не сильнее restoration")
    if not (source(bare["elemental"], "Lava Burst") > 0 and source(bare["elemental"], "Liquid Magma") > 0):
        fail("elemental не бьёт lava и магмой")

    inert = {
        "restoration": (
            TALENT_FURY,
            TALENT_MOLTEN_BLAST,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        ),
        "enhancement": (
            TALENT_FURY,
            TALENT_MOLTEN_BLAST,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        ),
        "elemental": (
            TALENT_SPIRIT_CALL,
            TALENT_STORM_INFUSION,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        ),
    }
    for spec, codes in inert.items():
        for code in codes:
            row = fight(spec, (code,))
            close(row.dps, bare[spec].dps, f"{TALENTS[code]} на {spec}")


def test_storm_infusion_timing() -> None:
    for spec in ("restoration", "enhancement"):
        early = fight(spec, seconds=6.0)
        early_talent = fight(spec, (TALENT_STORM_INFUSION,), seconds=6.0)
        close(source(early_talent, "Lesser Chain Lightning"), source(early, "Lesser Chain Lightning"), f"{spec} infusion до второго chain")
        later = fight(spec, seconds=12.0)
        later_talent = fight(spec, (TALENT_STORM_INFUSION,), seconds=12.0)
        raw = CHAIN * (1.08 if spec == "enhancement" else 1.0)
        base_p = 0.1575
        infused_p = 0.23625
        delta = 4 * package(raw, 3, False, 0.5, infused_p - base_p)
        close(
            source(later_talent, "Lesser Chain Lightning") - source(later, "Lesser Chain Lightning"),
            delta,
            f"{spec} infusion только на живых духах",
        )
    close(fight("elemental", (TALENT_STORM_INFUSION,)).dps, fight("elemental").dps, "elemental infusion")


def test_fusion_and_crit() -> None:
    bare = fight("restoration", seconds=2.4)
    fused = fight("restoration", (TALENT_FUSION,), seconds=2.4)
    close(source(fused, "Chain Lightning") / source(bare, "Chain Lightning"), 1.25, "fusion на ударе chain")
    close(source(fused, "Автоатака") / source(bare, "Автоатака"), 1.25, "fusion на автоатаке")
    close(source(fused, "Lesser Chain Lightning") / source(bare, "Lesser Chain Lightning"), 1.25, "fusion на lesser")

    wrath = fight("restoration", (TALENT_WRATH,))
    plain = fight("restoration")
    close(source(wrath, "Chain Lightning"), source(plain, "Chain Lightning"), "wrath crit не критует спеллы без вещи")
    if not (source(wrath, "Автоатака") > source(plain, "Автоатака")):
        fail("wrath не поднял автоатаку")
    spell = gear("spellcrit")
    spell.spell_crit = True
    with_item = fight("restoration", items=(spell,))
    with_both = fight("restoration", (TALENT_WRATH,), items=(spell,))
    if not (source(with_both, "Chain Lightning") > source(with_item, "Chain Lightning")):
        fail("wrath + spell crit не поднял chain")

    elemental = fight("elemental", (TALENT_WRATH,))
    close(source(elemental, "Chain Lightning"), source(fight("elemental"), "Chain Lightning"), "elemental wrath не меняет chain")
    if not (source(elemental, "Lava Burst") > source(fight("elemental"), "Lava Burst")):
        fail("elemental wrath не поднял lava")


def test_items_and_cds() -> None:
    wolf = (gear("I0S7"),)
    for spec in ("restoration", "enhancement"):
        bare = fight(spec)
        extra = fight(spec, items=wolf)
        close(source(extra, "Feral Spirit") / source(bare, "Feral Spirit"), 1.5, f"{spec} ghost wolf ×1.5 духов")
    close(fight("elemental", items=wolf).dps, fight("elemental").dps, "elemental ghost wolf без Feral Spirit")

    gloves = (gear("I0O8"),)
    for spec in SPECS:
        close(fight(spec, items=gloves).dps, fight(spec, (TALENT_BLOODLUST,)).dps, f"{spec} перчатки = талант bloodlust")

    epaulets = (gear("I0O9"),)
    bare = fight("restoration")
    pads = fight("restoration", items=epaulets)
    if not (source(pads, "Lesser Chain Lightning") > source(bare, "Lesser Chain Lightning")):
        fail("epaulets не подняли lesser")
    close(source(pads, "Chain Lightning"), source(bare, "Chain Lightning"), "epaulets не меняют активный chain")

    helm = (gear("I0S8"),)
    bare_shields = times(fight("elemental"), "Lightning Shield")
    helm_shields = times(fight("elemental", items=helm), "Lightning Shield")
    if not (len(helm_shields) > len(bare_shields) or helm_shields[1] < bare_shields[1] - 2):
        fail(f"шлем Ten Storms не снял кулдаун щита: {helm_shields} vs {bare_shields}")

    belt = (gear("I0O6"),)
    bare_actions = fight("elemental").actions
    belt_actions = fight("elemental", items=belt).actions

    def gaps(actions) -> list[float]:
        found = []
        for index, (moment, spell) in enumerate(actions):
            if spell != "Lightning Shield":
                continue
            nxt = next((later for later, name in actions[index:] if name == "Lava Burst"), None)
            if nxt is not None:
                found.append(nxt - moment)
        return found

    bare_gaps = gaps(bare_actions)
    belt_gaps = gaps(belt_actions)
    if not bare_gaps or max(bare_gaps) < 2:
        fail(f"без пояса lava и так сразу после щита: {bare_gaps}")
    if not belt_gaps or max(belt_gaps) > 1:
        fail(f"пояс не сбрасывает lava: {belt_gaps}")

    blast = times(fight("elemental", (TALENT_MOLTEN_BLAST,)), "Lightning Shield")
    plain = times(fight("elemental"), "Lightning Shield")
    if not (plain[1] - blast[1] > 3):
        fail(f"molten blast не срезал щит: {blast} vs {plain}")


def test_thunder_and_flash() -> None:
    bare = fight("enhancement")
    thunder = fight("enhancement", (TALENT_THUNDERSTORM,))
    over = fight("enhancement", (TALENT_THUNDERSTORM, TALENT_OVERCHARGE))
    strike = fight("enhancement", (TALENT_THUNDERSTORM, TALENT_STORMSTRIKE))
    close(source(bare, "Thunderstorm"), 0.0, "без таланта грозы нет")
    if not (source(thunder, "Thunderstorm") > 0):
        fail("гроза не нанесла урон")
    close(source(over, "Thunderstorm"), source(thunder, "Thunderstorm"), "overcharge не добавляет событий грозы")
    if not (source(strike, "Thunderstorm") > source(thunder, "Thunderstorm")):
        fail("stormstrike не добавил событий грозы")
    flash = fight("enhancement", (TALENT_FLASH,))
    close(source(flash, "Chain Lightning"), source(bare, "Chain Lightning"), "flash не меняет урон chain")
    if not (source(flash, "Lightning Shield") > source(bare, "Lightning Shield")):
        fail("flash не вернул заряды щита")


def test_pipe_sulfuras_diamond() -> None:
    catalog = {item.rawcode: item for item in load_items()}
    pipe = catalog["I00L"]
    stats = shaman.sheet(build(items=(pipe,)))
    close(stats["cast_stun_lock"], 0.3, "Pipe of Deew стан 0,3 с")
    close(stats["flat_cdr"], 1.5, "Pipe of Deew −1,5 с кулдауна")
    stun = Item("stun", "Stun", "", cast_stun_chance=1.0, cast_stun_duration=0.3)
    bare_times = times(fight("restoration", seconds=2.0), "Lightning Shield")
    stun_times = times(fight("restoration", items=(stun,), seconds=2.0), "Lightning Shield")
    close(stun_times[0] - bare_times[0], 0.3, "стан отодвигает следующий каст на 0,3 с")

    sulf = Item("I0BR", "Sulfuras", "")
    row = fight("restoration", items=(sulf,), seconds=2.4)
    worn = shaman.sheet(build(items=(sulf,)))
    close(source(row, "Sulfuras"), worn["int"] * TAKEN * 5, "Sulfuras всплеск с каста на следующую атаку")
    close(source(row, "Sulfuras (удар)"), 0.10 * worn["ad"] * TAKEN, "Sulfuras дополнительный удар 10%")

    ring = Item("I00D", "Diamond Ring", "")
    for spec, spells in (
        ("restoration", ("Chain Lightning", "Lightning Shield", "Feral Spirit", "Totemic Call")),
        ("elemental", ("Chain Lightning", "Lightning Shield", "Lava Burst", "Totemic Call")),
    ):
        trials = [fight(spec, items=(ring,), bound=spell) for spell in spells]
        best = max(trials, key=lambda report: report.dps)
        chosen = fight(spec, items=(ring,))
        close(chosen.dps, best.dps, f"Diamond Ring берёт лучшую кнопку {spec}")
        if chosen.bound_spell != best.bound_spell:
            fail(f"Diamond Ring {spec} привязал {chosen.bound_spell}, лучшая {best.bound_spell}")
        if chosen.bound_spell not in spells:
            fail(f"Diamond Ring {spec} привязал {chosen.bound_spell}")
    bound = times(fight("restoration", items=(ring,), bound="Chain Lightning", seconds=6.0), "Chain Lightning")
    close(bound[1], 4.9, "Diamond Ring −30% базы Chain Lightning")


def test_combinations() -> None:
    inert = {
        "restoration": {
            TALENT_FURY,
            TALENT_MOLTEN_BLAST,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        },
        "enhancement": {
            TALENT_FURY,
            TALENT_MOLTEN_BLAST,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        },
        "elemental": {
            TALENT_SPIRIT_CALL,
            TALENT_STORM_INFUSION,
            TALENT_LANDSLIDE,
            TALENT_TIDAL_WAVES,
            TALENT_GUIDANCE,
            TALENT_ANCESTRAL,
            TALENT_CHAIN_REACTION,
        },
    }
    codes = tuple(TALENTS)
    checked = 0
    for spec in SPECS:
        dead = inert[spec]
        bare = fight(spec).dps
        for size in (1, 2, 3):
            for combo in itertools.combinations(codes, size):
                checked += 1
                full = fight(spec, combo).dps
                alive = tuple(code for code in combo if code not in dead)
                expected = fight(spec, alive).dps if alive else bare
                if abs(full - expected) > 1e-6:
                    names = ", ".join(TALENTS[code] for code in combo)
                    fail(f"{spec} [{names}] {full:.4f} != {expected:.4f}")
                    return
        wrath = fight(spec, (TALENT_WRATH,))
        longer = fight(spec, (TALENT_WRATH, TALENT_TOTEM_MASTERY))
        if spec == "restoration":
            close(source(longer, "Chain Lightning"), source(wrath, "Chain Lightning"), "resto wrath+totem не меняет chain")
            if not (source(longer, "Автоатака") > source(wrath, "Автоатака")):
                fail("resto totem mastery не удлинил крит wrath")
        elif spec == "enhancement":
            if not (source(longer, "Chain Lightning") > source(wrath, "Chain Lightning")):
                fail("enh totem mastery не удлинил mastery wrath")
        elif not (source(longer, "Liquid Magma") > source(wrath, "Liquid Magma")):
            fail("elemental totem mastery не удлинил магму wrath")
    print("combinations", checked)


def main() -> None:
    test_short_windows()
    test_mastery_points()
    test_potency_not_inside_overcharge()
    test_spec_gates()
    test_storm_infusion_timing()
    test_fusion_and_crit()
    test_items_and_cds()
    test_thunder_and_flash()
    test_pipe_sulfuras_diamond()
    test_combinations()
    print("fails", len(FAILS))
    if FAILS:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
