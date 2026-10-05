from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 10:
    i = script.find("'I0JA'", start)
    if i < 0:
        break
    print(n, script[max(0, i - 80) : i + 160].replace("\n", " | ")[:280])
    print("---")
    start = i + 6
    n += 1
print("total", script.count("'I0JA'"))
