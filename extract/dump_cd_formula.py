from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("udg_CD_Temp_Int")
print("count", script.count("udg_CD_Temp_Int"))
# find a division by (1+udg_CDR) near an ability cooldown set
i = script.find("/(1.00+udg_CDR")
if i < 0:
    i = script.find("/(1+udg_CDR")
print("div", i)
print(script[i-250:i+120] if i>0 else "none")
print("--- second ---")
i2 = script.find("/(1+udg_CDR", i+10 if i>0 else 0)
print(script[i2-200:i2+80] if i2>0 else "none")
