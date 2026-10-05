from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("DiamondRing count", script.count("DiamondRing"))
print("I00D count", script.count("'I00D'"))
start = 0
n = 0
while n < 25:
    i = script.find("DiamondRing", start)
    if i < 0:
        break
    print(n, script[max(0, i - 70) : i + 90].replace("\n", " | ")[:200])
    print("---")
    start = i + 11
    n += 1
