"""Paladin buttons, talents and base stats from the map."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import map_script, map_strings
from sunken_sim.search import class_item_codes

script = map_script()
strings = map_strings()
out = []

def add(title, text):
    out.append(f"\n==== {title} ====\n{text}\n")

# full specialization tooltip
for number, text in strings.items():
    if "Retribution:" in text and "Paladin" not in text and "Specializations" in text:
        add(f"spec tooltip {number}", text)
    if text.startswith("|cfff6b687Specializations|r") or "Retribution:" in text and "Protection:" in text:
        add(f"specs {number}", text[:2500])

# ability names that look like paladin spells
needles = (
    "Crusader Strike",
    "Divine Storm",
    "Blessed Hammer",
    "Holy Light",
    "Divine Protection",
    "Judgement",
    "Judgment",
    "Consecration",
    "Avenging Wrath",
    "Shield of the Righteous",
    "Word of Glory",
    "Hammer of Wrath",
    "Blade of Justice",
    "Templar",
    "Holy Shock",
    "Beacon of Light",
    "Divine Toll",
    "Wake of Ashes",
    "Final Verdict",
    "Justicar",
    "Righteous",
)
for needle in needles:
    hits = [(n, t.split("\n")[0][:120]) for n, t in strings.items() if needle in t.split("\n")[0] or t.startswith(needle)]
    # names only: short strings
    short = [(n, t.replace("\n", " | ")[:180]) for n, t in strings.items() if t.strip().startswith(needle) or re.search(rf"^{re.escape(needle)}\b", re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", t))]
    if short:
        add(needle, "\n".join(f"{n}: {t}" for n, t in short[:8]))

codes = class_item_codes()
pala = sorted(codes.get("Paladin", []))
add("class items", ", ".join(pala) + f" count {len(pala)}")

# hero variable mentions
for name in ("udg_Hero_Paladin", "Paladin_Spell", "HeroPaladin"):
    add(name, f"count {script.count(name)}")

path = Path(__file__).with_name("paladin-notes.txt")
path.write_text("".join(out), encoding="utf-8")
print("wrote", path, "chars", path.stat().st_size)
