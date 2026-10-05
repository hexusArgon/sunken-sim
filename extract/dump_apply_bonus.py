from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("MagicalType_Bonus))")
print("close paren", script.count("MagicalType_Bonus))"))
# find multiplication
idx = script.find("udg_DamageEventAmount=(udg_DamageEventAmount*")
print("mult assigns", script.count("udg_DamageEventAmount=(udg_DamageEventAmount*"))
start = 0
n = 0
while n < 8:
    i = script.find("MagicalType_Bonus", start)
    if i < 0:
        break
    if "DamageEventAmount" in script[i : i + 80] or "DamageEventAmount" in script[max(0, i - 120) : i]:
        print(script[max(0, i - 150) : i + 40].replace("\n", " | "))
        print("---")
        n += 1
    start = i + 10
print("near damage", n)
