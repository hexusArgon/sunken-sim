from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
while True:
    i = script.find("'I0PU'", idx)
    if i < 0:
        break
    fn = script.rfind("function ", 0, i)
    header = script[fn : script.find("\n", fn)]
    print(header)
    idx = i + 6
