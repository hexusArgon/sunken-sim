from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("I07O", "I0NS", "I0NT"):
    print("====", code)
    index = script.find(f"UnitAddItemByIdSwapped('{code}'")
    print(script[max(0, index - 200) : index + 120].replace("\n", " | ")[:400])
    print()
