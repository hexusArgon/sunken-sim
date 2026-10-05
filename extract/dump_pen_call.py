from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 8:
    i = script.find("call CalculateArmorPenetration", start)
    if i < 0:
        break
    print(n, script[i-350:i+80].replace("\n"," | "))
    print("---")
    start = i + 20
    n += 1
