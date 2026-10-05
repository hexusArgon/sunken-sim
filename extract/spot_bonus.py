from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
# vest
i = chunk.find("0.50*I2R(udg_Mastery_Stat")
print("VEST", chunk[i - 120 : i + 180])
# for a code, find the set line's preceding if and print function
for code, label in [("I048", "atiesh"), ("fgrd", "glaive"), ("I044", "gore")]:
    pass
# print condition functions that mention these codes inside the bonus section's called funcs
for code in ("I048", "fgrd", "tlum", "I0JO", "I044", "I055"):
    i = 0
    print("\n##", code)
    n = 0
    while n < 3:
        j = script.find(f"'{code}'", i)
        if j < 0:
            break
        fn = script.rfind("\nfunction ", 0, j)
        header = script[fn + 1 : script.find("\n", fn + 1)]
        if "PreDamage_Increase" in header:
            print(header)
            print(script[j - 180 : j + 40].replace("\n", " | ")[:240])
            n += 1
        i = j + 5
