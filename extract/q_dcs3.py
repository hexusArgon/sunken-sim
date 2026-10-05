from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
n = 0
while n < 10:
    i = script.find("UnitItemInSlot", idx)
    if i < 0:
        break
    window = script[max(0, i - 60) : i + 180]
    if "DCS" in window or "DamageBonus" in window:
        print(window.replace("\n", " | ")[:260])
        print("---")
        n += 1
    idx = i + 12
print("hits", n)
# LoadInteger item damage
print("LoadInteger", script.count("LoadInteger"))
i = script.find("DamageBonus")
print(script[i - 80 : i + 120].replace("\n", " | ")[:220])
