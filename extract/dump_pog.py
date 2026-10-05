from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("PoG count", script.count("udg_PoG_"))
idx = script.find("udg_PoG_Haste_Sum")
print(script[idx-500:idx+200])
print("\n==== I07O all contexts (short) ====")
start = 0
n = 0
while n < 13:
    i = script.find("'I07O'", start)
    if i < 0:
        break
    print(n, script[max(0,i-80):i+40].replace("\n"," | "))
    print("---")
    start = i + 6
    n += 1
