"""Per-class hybrid status for every hero/spec. One place the runner asks.

Statuses (same words as the docs status matrix):
  locked           - CPU sim only, the GPU path is never even imported (Arcane Mage).
  hybrid-timeline  - (retired for mage) CPU timeline + exact cache + GPU compile.
  hybrid-compile   - CPU timeline (module's own cache), GPU compile sums, CPU score
                     (Priest Shadow / Discipline / Holy).
  gpu-timeline     - batched next-event timeline generation (float64 clocks on CPU
                     when DirectML lacks f64) + GPU kind-score (Warrior/Paladin/Shaman/Priest x3, Mage fire/frost, Rogue x2).
  cpu-only         - runs under local-hybrid (device detect, v1 stat-kernel parity,
                     same payload), but fights are the module's own simulate. The
                     module sums damage inside simulate, so there is nothing to hand
                     to the GPU without a timeline/compile split in sunken_sim.

Every GPU engine has the same interface (farm.hybrid.engine.BatchFights):
dps_many(builds), greedy_points(build), finish_sextuple(...). The worker side
(farm.hybrid.engine.eval_span) and the parent parity gate (farm.hybrid.runner)
are class-agnostic; only make_engine() knows the classes.
"""

from __future__ import annotations

from farm.hybrid.lock import cpu_locked

LOCKED = "locked"
TIMELINE = "hybrid-timeline"
COMPILE = "hybrid-compile"
GPU_TIMELINE = "gpu-timeline"
CPU = "cpu-only"
STATUSES = (LOCKED, TIMELINE, COMPILE, GPU_TIMELINE, CPU)

# hero name in jobs -> sunken_sim module
MODULES = {
    "feral_druid": "feral_druid",
    "hunter": "hunter",
    "mage": "mage",
    "monk": "monk",
    "necromancer": "necromancer",
    "paladin": "paladin",
    "priest": "shadow",
    "rogue": "rogue",
    "shaman": "shaman",
    "siren": "siren",
    "tidewarrior": "tidewarrior",
    "tinker": "tinker",
    "warlock": "warlock",
    "warrior": "warrior",
    "windmaster": "windmaster",
    "witch_doctor": "witch_doctor",
}
PRIEST_SPECS = ("shadow", "discipline", "holy")

TIMELINE_SPECS = frozenset()  # mage fire/frost moved to GPU_TIMELINE_SPECS
PALADIN_SPECS = ("retribution", "protection", "holy")
SHAMAN_SPECS = ("restoration", "enhancement", "elemental")
WARRIOR_SPECS = ("protection", "arms", "fury")
ROGUE_SPECS = ("subtlety", "combat")
WARLOCK_SPECS = ("demonology", "destruction", "affliction")
FERAL_DRUID_SPECS = ("primal", "guardian", "savage")
BERSERKER_SPECS = ("headhunter", "poison", "fury")
MONK_SPECS = ("windwalker", "brewmaster", "mistweaver")
NECROMANCER_SPECS = ("bone", "blood", "essence")
SIREN_SPECS = ("sharpshooter", "watershaper", "seagrace")
TIDEWARRIOR_SPECS = ("myrmidon", "guardian")
TINKER_SPECS = ("engineering", "demolitions", "nanotech")
WINDMASTER_SPECS = ("upheaval", "storm", "combat")
WITCH_DOCTOR_SPECS = ("voodoo", "poison")
GPU_TIMELINE_SPECS = frozenset(
    {("warrior", spec) for spec in WARRIOR_SPECS}
    | {("paladin", spec) for spec in PALADIN_SPECS}
    | {("shaman", spec) for spec in SHAMAN_SPECS}
    | {("mage", "fire"), ("mage", "frost"), ("mage", "arcane")}  # arcane: only when unlocked (lock.py)
    | {("priest", spec) for spec in PRIEST_SPECS}
    | {("rogue", spec) for spec in ROGUE_SPECS}
    | {("hunter", "marksmanship"), ("hunter", "beast_mastery"), ("hunter", "survival")}
    | {("warlock", spec) for spec in WARLOCK_SPECS}
    | {("feral_druid", spec) for spec in FERAL_DRUID_SPECS}
    | {("monk", spec) for spec in MONK_SPECS}
    | {("necromancer", spec) for spec in NECROMANCER_SPECS}
    | {("siren", spec) for spec in SIREN_SPECS}
    | {("tidewarrior", spec) for spec in TIDEWARRIOR_SPECS}
    | {("tinker", spec) for spec in TINKER_SPECS}
    | {("windmaster", spec) for spec in WINDMASTER_SPECS}
    | {("witch_doctor", spec) for spec in WITCH_DOCTOR_SPECS}
)
HUNTER_SPECS = ("marksmanship", "beast_mastery", "survival")
COMPILE_SPECS = frozenset(
    # feral_druid moved to GPU_TIMELINE_SPECS
)

# Ledger kind-score heroes (sunken_sim/ledger.py + farm/hybrid/kindscore.py):
# hero -> (specs, engine class in farm/hybrid/<hero>.py)
KIND_HEROES = {
    "monk": (('windwalker', 'brewmaster', 'mistweaver'), "MonkFights"),
    "necromancer": (('bone', 'blood', 'essence'), "NecromancerFights"),
    "siren": (('sharpshooter', 'watershaper', 'seagrace'), "SirenFights"),
    "tidewarrior": (('myrmidon', 'guardian'), "TidewarriorFights"),
    "tinker": (('engineering', 'demolitions', 'nanotech'), "TinkerFights"),
    "windmaster": (('upheaval', 'storm', 'combat'), "WindmasterFights"),
    "witch_doctor": (('voodoo', 'poison'), "WitchDoctorFights"),
}
COMPILE_SPECS = COMPILE_SPECS | frozenset(
    (hero, spec) for hero, (specs, _cls) in KIND_HEROES.items() for spec in specs
)

# Port order for the cpu-only classes. Each needs the same split as mage/priest
# (simulate -> event list -> compile -> score) inside sunken_sim, with an
# events-equality test against the old simulate before any GPU work.
PORT_ORDER = (
    # feral_druid done (kind-score GPU)
)


def _norm(hero: str, spec: str) -> tuple[str, str]:
    return str(hero).strip().lower(), str(spec).strip().lower()


def status(hero: str, spec: str) -> str:
    key = _norm(hero, spec)
    if cpu_locked(*key):
        return LOCKED
    if key in TIMELINE_SPECS:
        return TIMELINE
    if key in GPU_TIMELINE_SPECS:
        return GPU_TIMELINE
    if key in COMPILE_SPECS:
        return COMPILE
    return CPU


def gpu_engine_for(hero: str, spec: str) -> bool:
    return status(hero, spec) in (TIMELINE, COMPILE, GPU_TIMELINE)


def make_engine(device, hero: str, spec: str, targets: int):
    """GPU batch engine for a spec, or ValueError for cpu-only / locked specs."""
    hero, spec = _norm(hero, spec)
    kind = status(hero, spec)
    if kind == TIMELINE:
        from farm.hybrid.fight import GpuFights

        return GpuFights(device, hero, spec, targets)
    if kind in (COMPILE, GPU_TIMELINE):
        if hero == "mage":
            from farm.hybrid.fight import GpuFights

            return GpuFights(device, hero, spec, targets)
        if hero == "paladin":
            from farm.hybrid.paladin import PaladinFights

            return PaladinFights(device, hero, spec, targets)
        if hero == "shaman":
            from farm.hybrid.shaman import ShamanFights

            return ShamanFights(device, hero, spec, targets)
        if hero == "warrior":
            from farm.hybrid.warrior import WarriorFights

            return WarriorFights(device, hero, spec, targets)
        if hero == "warlock":
            from farm.hybrid.warlock import WarlockFights

            return WarlockFights(device, hero, spec, targets)
        if hero == "rogue":
            from farm.hybrid.rogue import RogueFights

            return RogueFights(device, hero, spec, targets)
        if hero == "hunter":
            from farm.hybrid.hunter import HunterFights

            return HunterFights(device, hero, spec, targets)
        if hero == "feral_druid":
            from farm.hybrid.feral_druid import FeralDruidFights

            return FeralDruidFights(device, hero, spec, targets)
        if hero in KIND_HEROES:
            import importlib

            engine = getattr(importlib.import_module(f"farm.hybrid.{hero}"), KIND_HEROES[hero][1])
            return engine(device, hero, spec, targets)
        from farm.hybrid.priest import PriestFights

        return PriestFights(device, hero, spec, targets)
    if kind == LOCKED:
        from farm.hybrid.lock import assert_gpu_allowed

        assert_gpu_allowed(hero, spec)
    raise ValueError(f"{hero}/{spec}: {kind}, no GPU fight engine")


def cpu_dps(hero: str, spec: str, targets: int, build) -> float:
    """Reference for every parity gate: the farm's own CPU fight (farm.score._fight)."""
    from farm.score import _fight

    return _fight(hero, spec, targets, build)


def specs_of(hero: str) -> tuple[str, ...]:
    import importlib

    if hero == "priest":
        return PRIEST_SPECS
    module = importlib.import_module(f"sunken_sim.{MODULES[hero]}")
    return tuple(getattr(module, "SPECS"))


_NOTES = {
    LOCKED: "CPU sim, GpuLocked, torch never imported",
    TIMELINE: "CPU timeline + exact timeline cache, GPU compile sums, CPU score",
    GPU_TIMELINE: "batched next-event timeline (f64 clocks; DirectML kind-score); Warrior/Paladin/Shaman/Priest x3, Mage fire/frost, Rogue x2, Druid x2, Hunter x3, Warlock x3, Feral Druid x3, Berserker x3, Death Knight x3, Demon Hunter x3, Dragon Sentinel x3, Monk x3, Necromancer x3, Siren x3, Tidewarrior x2, Tinker x3, Windmaster x3, Witch Doctor x2",
    COMPILE: "CPU timeline (module _TIMELINE), GPU compile sums, CPU score (none — kind-heroes done)",
    CPU: "local-hybrid runner + v1 stat parity; fights = module simulate (no compile split yet)",
}


def matrix() -> list[dict]:
    rows = []
    for hero in sorted(MODULES):
        for spec in specs_of(hero):
            kind = status(hero, spec)
            rows.append({"hero": hero, "spec": spec, "status": kind, "note": _NOTES[kind]})
    return rows


if __name__ == "__main__":
    from collections import Counter

    table = matrix()
    for row in table:
        print(f"{row['hero']:16} {row['spec']:14} {row['status']:16} {row['note']}")
    print(dict(Counter(row["status"] for row in table)))
