import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_PreDamage_Items_Glyphs_Func002Func005Func012Func027Func003Func002C")
print(script[index : index + 1600])
