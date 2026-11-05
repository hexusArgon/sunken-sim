import subprocess, json, sys, time
from pathlib import Path
sys.path.insert(0, '.')
from farm.hybrid.registry import KIND_HEROES
py = sys.executable
rows = []
for hero, (specs, _c) in KIND_HEROES.items():
    for spec in specs:
        t = time.time()
        p = subprocess.run([py, 'tools/run_hybrid_parity.py', '--hero', hero, '--spec', spec, '--n', '300', '--finish', '2'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        f = Path(f'farm-data-hybrid-smoke/parity-{hero}-{spec}-dml.json')
        if p.returncode or not f.exists() or f.stat().st_mtime < t:
            print(f'{hero}/{spec}: ERROR rc={p.returncode} {p.stderr[-800:]}', flush=True); continue
        d = json.loads(f.read_text(encoding='utf-8'))
        fin = max((x['rel'] for x in d['finish']), default=0.0)
        same = all(x['same_talents'] and x['same_glyphs'] and x['same_points'] for x in d['finish'])
        ok = d['fights']['ok'] and fin <= 1e-4 and same
        print(f"{hero}/{spec}: n={d['fights']['n']} max_rel={d['fights']['max_rel']:.2e} max_abs={d['fights']['max_abs']:.3g} finish_rel={fin:.2e} same={same} cpu={d['cpu_ms_per_fight']}ms gpu={d['hybrid_ms_per_fight']}ms {'OK' if ok else 'FAIL'}", flush=True)
