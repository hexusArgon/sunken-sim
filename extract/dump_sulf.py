from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 8:
    i = script.find("'I0QT'", start)
    if i < 0:
        break
    print(n, script[max(0, i - 120) : i + 200].replace("\n", " | ")[:320])
    print("---")
    start = i + 6
    n += 1
print("count", script.count("'I0QT'"))
print("I0BL", script.count("'I0BL'"))
print("tgrh", script.count("'tgrh'"))
print("ofr2", script.count("'ofr2'"))
