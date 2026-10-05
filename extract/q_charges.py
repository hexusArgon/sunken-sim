from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("GetItemCharges", script.count("GetItemCharges"))
print("SetItemCharges", script.count("SetItemCharges"))
idx = 0
n = 0
while n < 8:
    i = script.find("GetItemCharges", idx)
    if i < 0:
        break
    print(script[max(0, i - 70) : i + 80].replace("\n", " | ")[:200])
    print("---")
    idx = i + 8
    n += 1
