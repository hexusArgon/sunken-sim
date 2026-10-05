from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_Shadow_Word_Pain_Loop_Func003A")
print(script[index : index + 1500])
print("\n==== mastery stat priest ====")
index = 0
shown = 0
while shown < 8:
    index = script.find("udg_Mastery_Stat[", index)
    if index < 0:
        break
    window = script[max(0, index - 150) : index + 80]
    if "Priest" in window or "Shadow" in window or "0.00" in window:
        print(window.replace("\n", " | ")[:260])
        print("---")
        shown += 1
    index += 12
print("shown", shown)
