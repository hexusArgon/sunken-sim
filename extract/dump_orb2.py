from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Trig_PreDamage_Items_Glyphs_Func002Func005Func012Func027C()"
index = script.find(needle)
print(script[index - 100 : index + 1500])
