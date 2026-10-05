from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_Shadow_Word_Pain_Loop_Actions")
print(script[index : index + 900])
print("\n==== mastery shadow ====")
index = script.find("0.006")
print("count nearby")
shown = 0
while shown < 5 and index >= 0:
    print(script[max(0, index - 200) : index + 180].replace("\n", " | ")[:400])
    print("---")
    shown += 1
    index = script.find("0.006", index + 5)
