import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("function Trig_PreDamage_Increase_Actions")
end = script.find("function Trig_PreDamage_Increase_Func001Func041C")
chunk = script[start:end]
idx = 0
while True:
    i = chunk.find("set udg_MagicalType_Bonus=", idx)
    if i < 0:
        break
    print(chunk[i : i + 80].replace("\n", " | "))
    idx = i + 10
print("--- physical ---")
idx = 0
while True:
    i = chunk.find("set udg_PhysicalType_Bonus=", idx)
    if i < 0:
        break
    print(chunk[i : i + 80].replace("\n", " | "))
    idx = i + 10
print("--- dynamic ---")
idx = 0
n = 0
while n < 6:
    i = chunk.find("set udg_MagicalType_Dynamic", idx)
    if i < 0:
        break
    print(chunk[i : i + 100].replace("\n", " | "))
    idx = i + 10
    n += 1
