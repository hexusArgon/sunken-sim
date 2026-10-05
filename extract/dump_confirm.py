from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
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
