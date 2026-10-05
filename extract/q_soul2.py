from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for needle in (
    "Func012Func017C())then",
    "Func013Func011Func002C())then",
):
    i = script.find(needle)
    print("\n====", needle, i)
    print(script[i : i + 500] if i >= 0 else "no")
