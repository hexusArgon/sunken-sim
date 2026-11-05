"""Per-class hybrid status for every hero/spec. One place the runner asks.

Statuses (same words as the docs status matrix):
  locked           - CPU sim only, the GPU path is never even imported (Arcane Mage).
  hybrid-timeline  - pilot: CPU timeline with an exact timeline cache, GPU compile
                     sums, CPU closed-form score (Mage Fire / Frost).
  hybrid-compile   - CPU timeline (module's own cache), GPU compile sums, CPU score
                     (Priest Shadow / Discipline / Holy).
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
CPU = "cpu-only"
STATUSES = (LOCKED, TIMELINE, COMPILE, CPU)

# hero name in jobs -> sunken_sim module
MODULES = {
    "berserker": "berserker",
    "death_knight": "death_knight",
    "demon_hunter": "demon_hunter",
    "dragon_sentinel": "dragon_sentinel",
    "druid": "druid",
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

TIMELINE_SPECS = frozenset({("mage", "fire"), ("mage", "frost")})
PALADIN_SPECS = ("retribution", "protection", "holy")
SHAMAN_SPECS = ("restoration", "enhancement", "elemental")
WARRIOR_SPECS = ("protection", "arms", "fury")
WARLOCK_SPECS = ("demonology", "destruction", "affliction")
ROGUE_SPECS = ("subtlety", "combat")
HUNTER_SPECS = ("marksmanship", "beast_mastery", "survival")
COMPILE_SPECS = frozenset(
    {("priest", spec) for spec in PRIEST_SPECS}
    | {("paladin", spec) for spec in PALADIN_SPECS}
    | {("shaman", spec) for spec in SHAMAN_SPECS}
    | {("warrior", spec) for spec in WARRIOR_SPECS}
    | {("warlock", spec) for spec in WARLOCK_SPECS}
    | {("rogue", spec) for spec in ROGUE_SPECS}
    | {("hunter", spec) for spec in HUNTER_SPECS}
)

# Port order for the cpu-only classes. Each needs the same split as mage/priest
# (simulate -> event list -> compile -> score) inside sunken_sim, with an
# events-equality test against the old simulate before any GPU work.
PORT_ORDER = (
    ("druid", "after hunter"),
)


def _norm(hero: str, spec: str) -> tuple[str, str]:
    return str(hero).strip().lower(), str(spec).strip().lower()


def status(hero: str, spec: str) -> str:
    key = _norm(hero, spec)
    if cpu_locked(*key):
        return LOCKED
    if key in TIMELINE_SPECS:
        return TIMELINE
    if key in COMPILE_SPECS:
        return COMPILE
    return CPU


def gpu_engine_for(hero: str, spec: str) -> bool:
    return status(hero, spec) in (TIMELINE, COMPILE)


def make_engine(device, hero: str, spec: str, targets: int):
    """GPU batch engine for a spec, or ValueError for cpu-only / locked specs."""
    hero, spec = _norm(hero, spec)
    kind = status(hero, spec)
    if kind == TIMELINE:
        from farm.hybrid.fight import GpuFights

        return GpuFights(device, hero, spec, targets)
    if kind == COMPILE:
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
    COMPILE: "CPU timeline (module _TIMELINE), GPU compile sums, CPU score (priest/paladin/shaman/warrior/warlock/rogue/hunter)",
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
