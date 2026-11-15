#!/usr/bin/env python3
"""Build docs/sim-html/index.html: Raid Summary (pool switcher + damage-by-source chart) from page data (sources/*.tsx).
Usage: python build_index.py <sim-html dir>"""
import re, json, sys, html, os
D = sys.argv[1] if len(sys.argv) > 1 else "."
SRC = os.path.join(D, "sources")

def const(f, name):
    s = open(os.path.join(SRC, f), encoding="utf8").read()
    m = re.search(r"^const " + name + r"\b[^=]*=\s*(.*?);\s*$", s, re.M)
    return json.loads(m.group(1))

def pct(v):
    if v is None: return None
    if isinstance(v, str): return float(v.rstrip("%"))
    return float(v)

POOLS = [("mixed", "Shop + drop"), ("shop", "Shop"), ("drop", "Drop")]
COL = {"Paladin": "#F48CBA", "Priest": "#FFFFFF", "Shaman": "#0070DD", "Mage": "#3FC7EB", "Druid": "#FF7C0A", "Berserker": "#C41E3A", "Hunter": "#AAD372", "Death Knight": "#9B2335", "Demon Hunter": "#A330C9", "Dragon Sentinel": "#33937F", "Feral Druid": "#D4A017"}
specs = []  # dict(cls, spec, page, level, pools{pool:{dps,total,mana,sources}})
# GPU run time per spec page (tools/sim_run_times.py)
RT_PATH = os.path.join(SRC, "run_times.json")
RUN_TIMES = json.load(open(RT_PATH, encoding="utf8")) if os.path.exists(RT_PATH) else {}

def add(cls, spec, page, level, runs_by_pool):
    pools = {}
    for p, _ in POOLS:
        r = runs_by_pool.get(p)
        if not r: continue
        pools[p] = dict(dps=float(r["dps"]), total=float(r["total"]), mana=pct(r.get("manaLeft")),
                        sources=[(n, float(v)) for n, v in r.get("sources", [])])
    key = page[:-len(".html")] + "-" + spec.lower().replace(" ", "_")
    specs.append(dict(cls=cls, spec=spec, page=page, level=level, pools=pools, rt=RUN_TIMES.get(key)))

# Mage: Fire, Frost, Arcane (full Top-150 GPU runs, level 15) from mage.tsx
for name, spec in (("DATA", "Fire"), ("FROST_DATA", "Frost"), ("ARCANE_DATA", "Arcane")):
    md = const("mage.tsx", name)
    add("Mage", spec, "mage.html", md["level"], {p: max(md["runs"][p], key=lambda r: float(r["dps"])) for p, _ in POOLS if p in md["runs"]})
# Paladin / Shaman / Berserker: three specs each (full Top-150 GPU runs, level 15) from paladin.tsx / shaman.tsx
for f, cls, page, names in [("paladin.tsx", "Paladin", "paladin.html", ("retribution", "protection", "holy")),
                            ("shaman.tsx", "Shaman", "shaman.html", ("restoration", "enhancement", "elemental")),
                            ("berserker.tsx", "Berserker", "berserker.html", ("headhunter", "poison", "fury")),
                            ("hunter.tsx", "Hunter", "hunter.html", ("marksmanship", "beast_mastery", "survival")),
                            ("death_knight.tsx", "Death Knight", "death_knight.html", ("frost", "blood", "unholy")),
                            ("demon_hunter.tsx", "Demon Hunter", "demon_hunter.html", ("havoc", "vengeance", "devourer")),
                            ("dragon_sentinel.tsx", "Dragon Sentinel", "dragon_sentinel.html", ("ruby", "obsidian", "emerald")),
                            ("feral_druid.tsx", "Feral Druid", "feral_druid.html", ("primal", "guardian", "savage"))]:
    for sp in names:
        d = const(f, sp.upper() + "_DATA")
        add(cls, sp.replace("_", " ").title(), page, d["level"], {p: max(d["runs"][p], key=lambda r: float(r["dps"])) for p, _ in POOLS if p in d["runs"]})
# Druid: Restoration, Balance; Priest: Shadow, Discipline, Holy (full Top-150 GPU runs, level from the data)
for f, name, cls, spec, page in [("druid.tsx", "RESTORATION_DATA", "Druid", "Restoration", "druid.html"),
                                 ("druid.tsx", "BALANCE_DATA", "Druid", "Balance", "druid.html"),
                                 ("priest.tsx", "DATA", "Priest", "Shadow", "priest.html"),
                                 ("priest.tsx", "DISCIPLINE_DATA", "Priest", "Discipline", "priest.html"),
                                 ("priest.tsx", "HOLY_DATA", "Priest", "Holy", "priest.html")]:
    d = const(f, name)
    add(cls, spec, page, d["level"], {p: max(d["runs"][p], key=lambda r: float(r["dps"])) for p, _ in POOLS if p in d["runs"]})

SRC_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#39c5cf", "#db61a2", "#e3b341", "#8b949e", "#56d364", "#ff9a5c", "#79c0ff"]
e = html.escape
fmt = lambda x: f"{x:,.1f}".replace(",", " ")
fmti = lambda x: f"{x:,.0f}".replace(",", " ")

def run_time(s):
    rt = s.get("rt")
    if not rt:
        return '<div class="rv tm">—</div>'
    m = int(round(rt["minutes"]))
    txt = (f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин")
    if rt.get("estimated"):
        txt = "≈ " + txt
    tip = " + ".join(f'{r["run"]}: {r["minutes"]:.1f} мин' for r in rt["runs"])
    return f'<div class="rv tm" title="{e(tip)}">{txt}</div>'

def source_chart(pool):
    rows = sorted([s for s in specs if pool in s["pools"] and s["pools"][pool]["sources"]], key=lambda s: -s["pools"][pool]["dps"])
    mx = max(sum(v for _, v in s["pools"][pool]["sources"]) for s in rows)
    out = ['<div class="srow shead"><div class="rl">Специализация</div><div>Урон по источникам</div><div class="rv">DPS</div><div class="rv">Время прогона</div></div>']
    for s in rows:
        src = s["pools"][pool]["sources"]; tot = sum(v for _, v in src)
        segs = "".join(f'<div class="seg" style="width:{v/mx*100:.3f}%;background:{SRC_COLORS[j % len(SRC_COLORS)]}" title="{e(n)}: {fmt(v)} DPS ({v/tot*100:.1f}%)"></div>' for j, (n, v) in enumerate(src))
        top = " · ".join(f'<span class="sw" style="background:{SRC_COLORS[j % len(SRC_COLORS)]}"></span>{e(n)} {fmt(v)}' for j, (n, v) in enumerate(src[:4]))
        out.append(f'<a class="srow" href="{e(s["page"])}"><div class="rl"><span style="color:{COL[s["cls"]]}">{e(s["spec"])} {e(s["cls"])}</span><span class="lv">ур. {s["level"]}</span></div>'
                   f'<div><div class="stack">{segs}</div><div class="slg">{top}{" · …" if len(src) > 4 else ""}</div></div><div class="rv mono">{fmt(tot)}</div>{run_time(s)}</a>')
    return "\n".join(out)

css = open(os.path.join(D, "build", "style.css"), encoding="utf8").read() if os.path.exists(os.path.join(D, "build", "style.css")) else ""
css += """
.card{display:block;background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:16px;color:var(--fg);text-decoration:none}
.card:hover{border-color:var(--accent)}.ct{font-size:20px;font-weight:650}.cs{color:var(--fg2);font-size:13px;margin-top:6px}.cn{color:var(--success);margin-top:10px;font-size:13px}
.sec{margin-top:26px;display:flex;flex-direction:column;gap:10px}
.pills{display:flex;gap:8px;flex-wrap:wrap}
.sumgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.sumgrid .stat-value{font-size:17px}
.chart{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:7px}
.rrow{display:grid;grid-template-columns:270px 1fr 80px;gap:12px;align-items:center;font-size:13px;color:var(--fg);text-decoration:none}
.srow{display:grid;grid-template-columns:270px 1fr 80px 100px;gap:12px;align-items:center;font-size:13px;color:var(--fg);text-decoration:none}
.rrow:hover .rl,.srow:hover .rl{text-decoration:underline}
.srow{cursor:pointer}
.shead{cursor:default;color:var(--fg3);font-size:11.5px;font-weight:400}.shead .rl{font-weight:400}
.tm{color:var(--fg2);white-space:nowrap}
.rl{display:flex;gap:8px;align-items:baseline;justify-content:flex-end;white-space:nowrap;font-weight:600}
.rk{color:var(--fg3);font-weight:400;min-width:18px;text-align:right}
.lv{color:var(--fg3);font-weight:400;font-size:11.5px}
.rt{background:#21262d;border-radius:3px;height:20px;overflow:hidden}
.rf{height:100%;border-radius:3px;opacity:.85}
.rv{text-align:right;font-size:12.5px}
.stack{display:flex;height:20px;background:#21262d;border-radius:3px;overflow:hidden}
.seg{height:100%;border-right:1px solid rgba(13,17,23,.6)}.seg:hover{filter:brightness(1.25)}
.slg{color:var(--fg2);font-size:11.5px;margin-top:3px}
.sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 4px -1px 0}
.pv{display:none}.pv.on{display:flex}
.note{color:var(--fg2);font-size:12.5px}
@media(max-width:800px){.rrow{grid-template-columns:150px 1fr 64px}.srow{grid-template-columns:150px 1fr 64px 76px}.lv{display:none}}
"""

pages = [("paladin", "Paladin"), ("priest", "Priest"), ("shaman", "Shaman"), ("mage", "Mage"), ("druid", "Druid"), ("berserker", "Berserker"), ("hunter", "Hunter"), ("death_knight", "Death Knight"), ("demon_hunter", "Demon Hunter"),
         ("dragon_sentinel", "Dragon Sentinel"), ("feral_druid", "Feral Druid")]
nav = '<nav class="topnav"><a href="index.html" class="cur">← Sunken City sims</a>' + "".join(f'<a href="{f}.html">{t}</a>' for f, t in pages) + "</nav>"

lv = sorted({s["level"] for s in specs})
shown = ", ".join(f'{s["spec"]} {s["cls"]} (ур. {s["level"]})' for s in sorted(specs, key=lambda s: -s["pools"]["mixed"]["dps"]))
pills = "".join(f'<button class="pill {"active" if p=="mixed" else ""}" data-pool="{p}">{t}</button>' for p, t in POOLS)
body = f"""{nav}<main class="page">
<h1 class="h1">Sunken City v2.5.2c — симы классов</h1>
<div class="note" style="margin-top:4px">30 секунд · 5 целей · лучший билд (место 1) каждой специализации из фарма. Цифры — из данных страниц классов (sources/*.tsx), ничего не досчитано. Время прогона — время GPU-прогонов топ-150, из которых собрана страница спека (вместе с прогонами Sulfuras / Nightfall; наведи курсор, чтобы увидеть состав).</div>
<div class="sec"><h2 class="h2">Raid Summary</h2><div class="pills">{pills}</div>

{"".join(f'<div class="pv {"on" if p=="mixed" else ""} chart" data-pool="{p}" style="flex-direction:column">{source_chart(p)}</div>' for p, _ in POOLS)}
</div>
</main>
<script>
document.querySelectorAll('.pill[data-pool]').forEach(function(b){{b.addEventListener('click',function(){{
var p=b.getAttribute('data-pool');
document.querySelectorAll('.pill[data-pool]').forEach(function(x){{x.classList.toggle('active',x===b)}});
document.querySelectorAll('.pv').forEach(function(v){{var on=v.getAttribute('data-pool')===p;v.classList.toggle('on',on);v.style.display=on?(v.classList.contains('sumgrid')?'grid':'flex'):'none'}});
}})}});
</script>"""
doc = f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sunken City sims</title><style>{css}</style></head><body>{body}</body></html>'
open(os.path.join(D, "index.html"), "w", encoding="utf8").write(doc)
print("index.html", len(doc), "specs:", shown)
