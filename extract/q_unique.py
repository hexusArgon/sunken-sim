from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

def show(name, n=1200):
    i = script.find(f"function {name} ")
    print("\n====", name, i)
    if i >= 0:
        print(script[i : i + n])

show("Trig_Backpack_Items_Acquire_Actions", 1500)
show("Trig_Register_Unique_Epics_Actions", 1500)
show("Trig_Shop_Restricted_Items_Actions", 800)
