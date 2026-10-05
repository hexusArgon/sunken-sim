from pathlib import Path
import re

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")

# Find Weakness item vs talent
print("I0JU count", script.count("'I0JU'"))
start = 0
n = 0
while n < 12:
    i = script.find("'I0JU'", start)
    if i < 0:
        break
    window = script[max(0, i - 140) : i + 80].replace("\n", " | ")
    print(n, window[:260])
    print("---")
    start = i + 6
    n += 1

print("\n==== duplicate / already carrying phrases ====")
for needle in (
    "already have",
    "already owns",
    "only have one",
    "cannot carry more",
    "ItemCount",
    "CountItems",
):
    print(needle, script.lower().count(needle.lower()) if needle != "ItemCount" else script.count(needle))
