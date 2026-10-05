from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

needles = [
    "udg_Haste_Stat[",
    "udg_Haste_Items[",
    "0.006",
    "A0MH",
]
for needle in ("set udg_Haste_Stat", "set udg_CDR[", "0.006*"):
    print("\n====", needle, script.count(needle))
    index = 0
    shown = 0
    while shown < 6:
        index = script.find(needle, index)
        if index < 0:
            break
        print(script[max(0, index - 120) : index + 220].replace("\n", " | ")[:340])
        print()
        shown += 1
        index += len(needle)
