from pathlib import Path
import re, sys
sys.stdout.reconfigure(encoding="utf-8")

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
wts = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts").read_text(encoding="utf-8", errors="replace")

for needle in (
    "GetInventoryIndexOfItemTypeBJ",
    "UnitInventoryCount",
    "EpicUnique",
    "udg_Drops_EpicUnique",
    "only one of",
    "do not stack",
    "does not stack",
    "Auras with the same name",
):
    print(needle, script.count(needle) if "stack" not in needle.lower() and "only" not in needle else (script+wts).lower().count(needle.lower()))

print("\n==== epic unique uses ====")
idx = 0
n = 0
while n < 8:
    i = script.find("EpicUnique", idx)
    if i < 0:
        break
    print(script[max(0, i - 100) : i + 120].replace("\n", " | ")[:240])
    print("---")
    idx = i + 8
    n += 1

print("\n==== wts does not stack samples ====")
low = wts.lower()
idx = 0
n = 0
while n < 6:
    i = low.find("does not stack", idx)
    if i < 0:
        i = low.find("do not stack", idx)
    if i < 0:
        break
    print(wts[max(0, i - 80) : i + 80].replace("\n", " ")[:200])
    print("---")
    idx = i + 10
    n += 1
print("stack mentions", n)
