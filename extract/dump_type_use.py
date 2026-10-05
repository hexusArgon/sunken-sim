from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 15:
    i = script.find("MagicalType_Bonus", start)
    if i < 0:
        break
    window = script[max(0, i - 40) : i + 70].replace("\n", " | ")
    if "set udg_MagicalType_Bonus=(" in window or "DamageEventAmount" in window or "*" in window:
        print(n, window)
        print("---")
        n += 1
    start = i + 16
print("shown", n, "total", script.count("MagicalType_Bonus"))
