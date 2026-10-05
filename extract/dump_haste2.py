from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = 0
shown = 0
needle = "Haste_Items"
while shown < 12:
    index = script.find(needle, index)
    if index < 0:
        break
    window = script[max(0, index - 80) : index + 160]
    if "set " in window and "CDR" in window or "Tooltip" in window or "1.00" in window or "/ 100" in window:
        print(window.replace("\n", " | ")[:280])
        print("---")
        shown += 1
    index += len(needle)
print("shown filtered", shown)
# haste tooltip function names
import re
print([n for n in sorted(set(re.findall(r"function (Trig_\w*Haste\w*)", script))) if "Tip" in n or "Stat" in n or "Setup" in n])
