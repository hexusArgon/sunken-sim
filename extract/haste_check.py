from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items, map_script
from sunken_sim.search import pools_for

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

amounts = {
    "Func003": 3,
    "Func004": 4,
    "Func005": 5,
    "Func006": 6,
    "Func007": 7,
    "Func008": 8,
    "Func009": 9,
    "Func010": 10,
    "Func011": 11,
    "Func012": 12,
    "Func013": 13,
    "Func014": 14,
    "Func015": 15,
    "Func016": 16,
    "Func017": 18,
}
by_code = {}
for func, amount in amounts.items():
    i = script.find(f"function Trig_Haste_Gain_{func}Func002C ")
    if i < 0:
        i = script.find(f"function Trig_Haste_Gain_{func}C ")
    chunk = script[i : script.find("endfunction", i)]
    for code in re.findall(r"'([A-Za-z0-9]{4})'", chunk):
        by_code[code] = amount

items = {item.rawcode: item for item in load_items()}
shop, drop, legs = pools_for(list(items.values()))
pool = {item.rawcode: item for item in shop + drop + legs}
print("mapped", len(by_code), "priest pool", len(pool))
mismatch = []
missing = []
extra = []
for code, item in pool.items():
    tip = int(round(item.haste))
    got = by_code.get(code)
    if tip and got != tip:
        mismatch.append((item.name, code, tip, got))
    if tip and got is None:
        missing.append((item.name, code, tip))
for code, amount in by_code.items():
    item = pool.get(code)
    if item and not item.haste:
        extra.append((item.name, code, amount))
print("mismatch", len(mismatch))
for row in mismatch[:30]:
    print(" ", row)
print("tooltip haste but no trigger", missing[:20])
print("trigger haste but tooltip 0", extra[:20])
print("orb", by_code.get("I07O"), by_code.get("I0NS"), by_code.get("I0NT"))
