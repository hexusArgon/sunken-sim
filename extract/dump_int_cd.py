import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("udg_Ability_Int_CD[udg_CDR_AbilityArray]=")
print(script[i:i+350])
print("--- floor ---")
i = script.find("Ability_Int_CD[udg_CDR_AbilityArray]=0.50")
print(script[max(0,i-200):i+80])
