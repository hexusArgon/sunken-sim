"""Opt-in exact OpenCL backend: Mage, Priest, Shaman, Paladin, Berserker (three specs each) and Druid (Restoration, Balance).

Every fight of such a job (bare scan, talents, glyphs, greedy ESC) runs on the
GPU in float64, bit for bit equal to the CPU oracle (farm.hybrid.mage_cl,
farm.hybrid.priest_cl,
farm.hybrid.shaman_cl, farm.hybrid.paladin_cl, farm.hybrid.druid_cl,
farm.hybrid.berserker_cl).  Nothing changes unless it is asked for:

* job field ``"backend": "opencl"`` or ``"opencl": true``
  (Fire also keeps ``"fire_backend": "opencl"`` / ``FARM_FIRE_BACKEND=opencl``);
* or the environment ``FARM_OPENCL=all`` (every spec above), or a comma list of
  heroes and hero:spec pairs, e.g. ``FARM_OPENCL=priest,mage:frost``.

``"opencl": false`` in the job always wins (the OpenCL route sets it itself when
its preflight fails and it hands the job back to the hybrid route).
"""
from __future__ import annotations

import os

SPECS = frozenset({
    ("mage", "fire"), ("mage", "frost"), ("mage", "arcane"),
    ("priest", "shadow"), ("priest", "discipline"), ("priest", "holy"),
    ("shaman", "restoration"), ("shaman", "enhancement"), ("shaman", "elemental"),
    ("paladin", "retribution"), ("paladin", "protection"), ("paladin", "holy"),
    ("druid", "restoration"), ("druid", "balance"),  # caster Druid only; feral_druid is another class
    ("berserker", "headhunter"), ("berserker", "poison"), ("berserker", "fury"),
    ("death_knight", "frost"), ("death_knight", "blood"), ("death_knight", "unholy"),
    ("demon_hunter", "havoc"), ("demon_hunter", "vengeance"), ("demon_hunter", "devourer"),
    ("dragon_sentinel", "ruby"), ("dragon_sentinel", "obsidian"), ("dragon_sentinel", "emerald"),
    ("feral_druid", "primal"), ("feral_druid", "guardian"), ("feral_druid", "savage"),
    ("hunter", "marksmanship"), ("hunter", "beast_mastery"), ("hunter", "survival"),
})
_OFF = ("", "0", "off", "no", "false", "none")
_ALL = ("1", "all", "on", "yes", "true")


def wanted(job: dict) -> bool:
    hero = str(job.get("hero", "")).strip().lower()
    spec = str(job.get("spec", "")).strip().lower()
    if (hero, spec) not in SPECS:
        return False
    flag = job.get("opencl")
    if flag is False:
        return False
    if flag is True:
        return True
    if str(job.get("backend") or "").strip().lower() == "opencl":
        return True
    if (hero, spec) == ("mage", "fire"):
        fire = str(job.get("fire_backend") or os.environ.get("FARM_FIRE_BACKEND", "")).strip().lower()
        if fire == "opencl":
            return True
        if job.get("fire_backend"):
            return False  # an explicit Fire backend in the job beats the farm-wide switch
    env = os.environ.get("FARM_OPENCL", "").strip().lower()
    if env in _OFF:
        return False
    if env in _ALL:
        return True
    names = {part.strip() for part in env.split(",") if part.strip()}
    return hero in names or f"{hero}:{spec}" in names
