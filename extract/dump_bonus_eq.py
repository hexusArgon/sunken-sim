from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for needle in [
    "udg_MagicalType_Bonus=1",
    "udg_MagicalType_Bonus=0",
    "udg_MagicalType_Dynamic=0",
    "udg_MagicalType_Dynamic=1",
    "udg_PhysicalType_Bonus=1",
    "udg_PhysicalType_Bonus=0",
]:
    print(needle, script.count(needle))
    i = script.find(needle)
    if i >= 0:
        print(script[max(0, i - 80) : i + 90].replace("\n", " | "))
        print("---")
