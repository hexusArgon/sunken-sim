from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for n in (1, 2, 3, 4):
    name = f"Trig_CDR_Cast_And_Spell_Types_Func034Func004Func004Func00{n}C"
    i = script.find(f"function {name} ")
    print("\n====", n)
    print(script[i : i + 500])

print("\n==== I06M contexts")
start = 0
for n in range(6):
    i = script.find("'I06M'", start)
    if i < 0:
        break
    print(script[max(0, i - 200) : i + 120].replace("\n", " | "))
    print("---")
    start = i + 6
