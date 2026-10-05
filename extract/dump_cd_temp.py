from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

needles = [
    "set udg_CD_Temp_Int[",
    "set udg_CDR_Flat_Int[",
    "udg_CDR_Flat_Int[udg_CDR_AbilityArray]",
]
for needle in needles:
    print("\n########", needle, script.count(needle))
    start = 0
    shown = 0
    while shown < 12:
        i = script.find(needle, start)
        if i < 0:
            break
        print(script[max(0, i - 180) : i + 160].replace("\n", " | "))
        print("---")
        start = i + len(needle)
        shown += 1
