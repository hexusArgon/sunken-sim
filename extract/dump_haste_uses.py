from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 15:
    i = script.find("udg_Haste_Items", start)
    if i < 0:
        break
    print(n, script[max(0,i-60):i+90].replace("\n"," | "))
    print("---")
    start = i + 14
    n += 1
print("total", script.count("udg_Haste_Items"))
