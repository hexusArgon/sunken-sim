from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func020Func006Func012C())then"
i = script.find(needle)
print(script[i : i + 500])
print("\n==== 024")
needle = "Func001Func024Func006Func008C())then"
i = script.find(needle)
print(script[i : i + 500])
