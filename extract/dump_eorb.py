from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 20:
    i = script.find("Elemental_Orb", start)
    if i < 0:
        break
    print(n, script[max(0,i-90):i+140].replace("\n"," | "))
    print("---")
    start = i + 12
    n += 1
print("ElementalOrb")
start = 0
n = 0
while n < 8:
    i = script.find("ElementalOrb", start)
    if i < 0:
        break
    print(n, script[max(0,i-90):i+160].replace("\n"," | "))
    print("---")
    start = i + 10
    n += 1
