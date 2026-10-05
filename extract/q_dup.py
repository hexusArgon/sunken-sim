from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

needles = [
    "GetItemTypeId(GetManipulatedItem())",
    "UnitHasItemOfTypeBJ(GetTriggerUnit()",
    "duplicate",
    "Duplicate",
    "same item",
    "SameItem",
    "Item_Stack",
    "Stack",
]
print("UnitHasItemOfTypeBJ(GetTriggerUnit()", script.count("UnitHasItemOfTypeBJ(GetTriggerUnit()"))
print("GetItemTypeId(GetManipulatedItem())==GetItemTypeId", script.count("GetItemTypeId(GetManipulatedItem())==GetItemTypeId"))

# functions that mention both manipulated item and UnitHasItem of trigger unit nearby
idx = 0
shown = 0
while shown < 15:
    i = script.find("UnitHasItemOfTypeBJ(GetTriggerUnit(),GetItemTypeId(GetManipulatedItem()))", idx)
    if i < 0:
        i = script.find("UnitHasItemOfTypeBJ(GetTriggerUnit(), GetItemTypeId(GetManipulatedItem()))", idx)
    if i < 0:
        break
    print(script[max(0, i - 120) : i + 160].replace("\n", " | ")[:300])
    print("---")
    idx = i + 40
    shown += 1
print("shown dynamic", shown)

# broader: pickup trigger names
names = re.findall(r"function (Trig_\w*(?:Pickup|Acquire|Restrict|Unique|Stack)\w*)", script)
print("funcs", names[:40], "count", len(names))
