from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

for needle in ("Drops_RareUnique", "Drops_UncommonUnique", "Drops_CommonUnique"):
    print("\n####", needle, script.count(needle))
    idx = 0
    n = 0
    while n < 5:
        i = script.find(needle, idx)
        if i < 0:
            break
        if "integer udg" in script[i - 30 : i] or "set udg_" + needle.split("_", 1)[-1] in script[max(0, i - 20):i + 40]:
            idx = i + len(needle)
            continue
        print(script[max(0, i - 90) : i + 140].replace("\n", " | ")[:280])
        print("---")
        idx = i + len(needle)
        n += 1
