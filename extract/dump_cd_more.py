from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def show(name, n=700):
    i = script.find(f"function {name} ")
    print("\n====", name, i)
    if i >= 0:
        print(script[i : i + n])

show("Trig_CDR_Cast_And_Spell_Types_Func034Func002Func004C")
show("Trig_CDR_Cast_And_Spell_Types_Func021Func006C")
show("Trig_CDR_Cast_And_Spell_Types_Func021C", 400)

# increased value sets
print("\n==== CDR_Increased_Value sets")
start = 0
shown = 0
while shown < 8:
    i = script.find("set udg_CDR_Increased_Value[", start)
    if i < 0:
        break
    print(script[max(0, i - 220) : i + 120].replace("\n", " | "))
    print("---")
    start = i + 20
    shown += 1
