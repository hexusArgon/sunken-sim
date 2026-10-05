from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("I0AV", "I0PU", "I0PS"):
    print("\n####", code, script.count(f"'{code}'"))
    start = 0
    n = 0
    while n < 4:
        i = script.find(f"'{code}'", start)
        if i < 0:
            break
        window = script[max(0, i - 60) : i + 40].replace("\n", " | ")
        if "PreDamage" in window or "Damage" in window or "Type_Bonus" in window or "Glyph" in window or "Talent" in window:
            print(n, window[:200])
            n += 1
        start = i + 6
