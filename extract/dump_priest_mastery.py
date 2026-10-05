from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 30:
    i = script.find("udg_Mastery_Stat[", start)
    if i < 0:
        break
    window = script[max(0, i-180): i+80]
    if "Priest" in window or "A0MH" in window or "Shadow" in window or "Mind" in window:
        print(n, window.replace("\n", " | ")[:400])
        print("---")
        n += 1
    start = i + 16
print("done windows", n)
