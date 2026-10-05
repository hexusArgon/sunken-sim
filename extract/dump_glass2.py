from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func035Func024C())then"
i = script.find(needle)
print("call", i)
print(script[i : i + 250] if i >= 0 else "no 024C call")
needle = "Func001Func035Func024Func002C())then"
i = script.find(needle)
print("\ncall2", i)
print(script[max(0, i - 100) : i + 200] if i >= 0 else "no")
