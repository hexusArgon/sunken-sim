import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import pools_for

items = load_items()
by = {item.rawcode: item for item in items}
shop, drop, legs = pools_for(items)
pool = shop + drop + legs
print("=== cdr_pct or cooldown_add ===")
for item in pool:
    if item.cdr_pct or item.cooldown_add:
        print(f"{item.rawcode} {item.name} pct={item.cdr_pct} add={item.cooldown_add}")
        for line in item.tip.split("\n"):
            if "cooldown" in line.lower() or "Haste" in line:
                print("   ", line)
print("\nI07P", by.get("I07P").name if "I07P" in by else None)
print(by["I07P"].tip if "I07P" in by else "")
print("\nI048", by.get("I048").name if "I048" in by else None)
if "I048" in by:
    for line in by["I048"].tip.split("\n"):
        if "cooldown" in line.lower() or "Haste" in line or "Mastery" in line:
            print("  ", line)
print("\nI06M")
print(by["I06M"].tip if "I06M" in by else "missing")
print("in pool", any(i.rawcode == "I06M" for i in pool))
print("\nI00D diamond")
if "I00D" in by:
    print(by["I00D"].name)
    print(by["I00D"].tip[:500])
    print("in pool", any(i.rawcode == "I00D" for i in pool))
print("\nI0FW I0QT")
for code in ("I0FW", "I0QT"):
    if code in by:
        print(code, by[code].name, "in pool", any(i.rawcode == code for i in pool))
        print(by[code].tip[:400])
