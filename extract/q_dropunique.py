from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

i = script.find("bj_forLoopAIndexEnd=udg_Drops_EpicUnique")
print("FIRST LOOP")
print(script[i - 400 : i + 700])
print("\n\n==== inventory count ====")
idx = 0
n = 0
while n < 6:
    j = script.find("UnitInventoryCount", idx)
    if j < 0:
        break
    print(script[max(0, j - 80) : j + 100].replace("\n", " | ")[:220])
    print("---")
    idx = j + 10
    n += 1
