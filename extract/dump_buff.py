from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("B03T", "B03O", "B03R", "A0AU", "A0AO", "A0AT"):
    print("\n====", code, script.count(f"'{code}'"))
    start = 0
    n = 0
    while n < 6:
        i = script.find(f"'{code}'", start)
        if i < 0:
            break
        print(script[max(0,i-160):i+80].replace("\n"," | "))
        print("---")
        start = i + 6
        n += 1
