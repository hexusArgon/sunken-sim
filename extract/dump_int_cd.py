from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("udg_Ability_Int_CD[udg_CDR_AbilityArray]=")
print(script[i:i+350])
print("--- floor ---")
i = script.find("Ability_Int_CD[udg_CDR_AbilityArray]=0.50")
print(script[max(0,i-200):i+80])
