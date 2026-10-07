import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_TasItemShop_Item='I07O'\nset udg_TasItemShop_Mats")
print("idx", i)
print(script[i-200:i+700])
