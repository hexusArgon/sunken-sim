import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_Shadow_Word_Pain_Loop_Func003Func002C")
print(script[index:index+500])
print("\n==== haste gain sample ====")
index = script.find("function Trig_Haste_Gain_Actions")
print(script[index:index+600])
print("\n==== I0NT add ====")
index = script.find("Func001Func006Func011C())then")
print(script[index:index+280])
index = script.find("Func001Func006Func013C())then")
print(script[index:index+280])
