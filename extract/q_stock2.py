from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
n = 0
while n < 6:
    i = script.find("AddItemToStock", idx)
    if i < 0:
        break
    print(script[max(0, i - 80) : i + 160].replace("\n", " | ")[:280])
    print("---")
    idx = i + 10
    n += 1
