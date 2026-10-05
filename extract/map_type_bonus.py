from pathlib import Path
import re
import sys

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import pools_for

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
items = {item.rawcode: item.name for item in load_items()}
shop, drop, legs = pools_for(load_items())
pool = {item.rawcode for item in shop + drop + legs}
fn_cache = {}

def body_of(name):
    if name in fn_cache:
        return fn_cache[name]
    i = script.find(f"function {name} ")
    if i < 0:
        fn_cache[name] = ""
        return ""
    fn_cache[name] = script[i : script.find("endfunction", i)]
    return fn_cache[name]

def collect(name, depth=0):
    if depth > 5 or not name:
        return set(), set()
    body = body_of(name)
    codes = set(re.findall(r"UnitHasItemOfTypeBJ\([^,]+,'([A-Za-z0-9]{4})'", body))
    codes |= set(re.findall(r"GetItemTypeId\([^)]+\)=='([A-Za-z0-9]{4})'", body))
    heroes = set(re.findall(r"udg_Hero_(\w+)", body))
    for child in re.findall(r"(Trig_PreDamage_Increase_Func\w+)\(\)", body):
        c, h = collect(child, depth + 1)
        codes |= c
        heroes |= h
    return codes, heroes

def section(a, b):
    start = script.find(a)
    end = script.find(b, start + 10)
    return script[start:end]

chunks = {
    "magical": section("set udg_MagicalType_Bonus=1.00", "set udg_PhysicalType_Bonus=1.00"),
    "physical": section("set udg_PhysicalType_Bonus=1.00", "udg_DamageEventAmount*(udg_MagicalType_Bonus"),
}
for label, chunk in chunks.items():
    print("\n====", label)
    for m in re.finditer(
        r"if\((Trig_PreDamage_Increase_Func\w+)\(\)\)then\s*set udg_(?:Magical|Physical)Type_(Bonus|Dynamic)=\(udg_(?:Magical|Physical)Type_\2([+\*])",
        chunk,
    ):
        cond, which, op = m.group(1), m.group(2), m.group(3)
        expr = chunk[m.end() : m.end() + 70].split(")")[0]
        codes, heroes = collect(cond)
        if heroes and "Priest" not in heroes and not (codes & pool):
            continue
        if heroes and "Priest" not in heroes and not codes:
            continue
        shown = ", ".join(f"{c} {items.get(c, '?')}" + ("" if c in pool else " NOTPOOL") for c in sorted(codes))
        hero = ",".join(sorted(heroes)) if heroes else ""
        if not shown and not hero:
            continue
        print(f"{op}{expr} [{which}] {shown} {hero}")
