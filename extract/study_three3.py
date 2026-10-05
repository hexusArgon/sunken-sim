from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

index = script.find("function Trig_ArmorDamage_Increase_Actions")
print("ARMOR ACTIONS", index)
print(script[index : index + 2500].replace("\n", " | ")[:2500])
print("\n\n==== 0.28 AS ====")
index = 0
shown = 0
while shown < 8:
    index = script.find("0.28", index)
    if index < 0:
        break
    window = script[max(0, index - 180) : index + 80]
    if "Attack" in window or "Crit" in window or "I0QN" in window:
        print(window.replace("\n", " | ")[:300])
        print()
        shown += 1
    index += 4
