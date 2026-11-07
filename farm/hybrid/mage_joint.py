"""Opt-in exhaustive Fire talents x glyphs at explicit ESC vectors.

This is a bounded refinement, NOT exhaustive ESC allocation or item search.
The default scorer is the old CPU oracle, preserving first-wins exact ties.
`candidate_start` resumes a deterministic suffix; it never marks that suffix as
a complete-domain audit on its own.
"""
from __future__ import annotations
import itertools
from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
from sunken_sim.shadow import Build, MIND_AMPLIFIER, SKILL_POINTS


def refine(equipped, talent_codes, glyph_codes, picks_without, picks_with,
           glyph_picks, targets=5, point_vectors=None, many=None, batch_size=128, max_seconds=None, candidate_start=0):
    """Enumerate every talent/glyph pair for each explicitly supplied ESC vector.

    Empty glyphs are included: the existing staged search may retain no glyphs.
    Default no ESC. Caller-supplied vectors may be partial but must obey map caps.
    `many` is a diagnostic hook; only the default CPU oracle is exact by contract.
    """
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    vectors = [empty_points()] if point_vectors is None else list(point_vectors)
    if not vectors:
        raise ValueError('at least one ESC vector required')
    checked = []
    for vector in vectors:
        if set(vector) - set(ESC_ATTRS):
            raise ValueError('unknown ESC attribute')
        points = empty_points(); points.update(vector)
        if any(type(v) is not int or not 0 <= v <= ESC_CAP for v in points.values()) or sum(points.values()) > SKILL_POINTS:
            raise ValueError('invalid ESC allocation')
        checked.append(points)
    picks = picks_with if any(i.rawcode == MIND_AMPLIFIER for i in equipped) else picks_without
    talents = list(itertools.combinations(talent_codes, picks))
    glyphs = [()] + list(itertools.combinations(glyph_codes, glyph_picks)) if glyph_picks else [()]
    if not talents:
        raise ValueError('empty talent domain')
    total_candidates = len(talents)*len(glyphs)*len(checked)
    if type(candidate_start) is not int or not 0 <= candidate_start < total_candidates:
        raise ValueError('invalid candidate_start')
    if many is None:
        from farm.hybrid.registry import cpu_dps
        many = lambda builds: [cpu_dps('mage', 'fire', targets, b) for b in builds]
    import time
    started = time.monotonic()
    best = None; evaluated = 0; pending = []
    complete = True
    candidate_index = 0
    def flush():
        nonlocal best, evaluated
        scores = list(many([row[0] for row in pending]))
        if len(scores) != len(pending):
            raise ValueError('scorer length mismatch')
        import math
        for (build, ts, gs, pts), value in zip(pending, scores):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError('non-finite score')
            evaluated += 1
            if best is None or value > best['dps']:
                best = dict(dps=value, talents=ts, glyphs=gs, points=dict(pts))
        pending.clear()
    for ts in talents:
        if not complete: break
        for gs in glyphs:
            if not complete: break
            base = Build(frozenset(ts), frozenset(gs), equipped, 0, 0)
            for pts in checked:
                candidate_index += 1
                if candidate_index <= candidate_start: continue
                pending.append((apply_points(base, pts), ts, gs, pts))
                if len(pending) >= batch_size:
                    flush()
                    if max_seconds is not None and time.monotonic() - started >= max_seconds:
                        complete = False
                        break
    if pending:
        flush()
    return dict(best=best, evaluated=evaluated, talent_combos=len(talents), glyph_combos=len(glyphs),
                esc_vectors=len(checked), exhaustive_esc=False, complete=(candidate_start == 0 and evaluated == total_candidates),
                candidate_start=candidate_start, range_complete=(candidate_start+evaluated == total_candidates),
                total_candidates=total_candidates)

def main():
    """python -m farm.hybrid.mage_joint --input bounded-bench.json --output joint.json"""
    import argparse,json,time
    from pathlib import Path
    from farm.catalog import load
    from farm.score import finish_sextuple
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--top',type=int,default=1);parser.add_argument('--targets',type=int,default=5)
    parser.add_argument('--max-seconds',type=float,default=240.)
    parser.add_argument('--zero-esc',action='store_true',help='also enumerate the zero-ESC slice')
    args=parser.parse_args()
    if not 1 <= args.top <= 10:parser.error('--top must be 1..10 (bounded refinement)')
    data=json.loads(Path(args.input).read_text(encoding='utf8'))
    rows=data.get('result',data).get('hits',[])
    space,items=load('mage','fire','mixed',None,100)
    reports=[]
    for row in sorted(rows,key=lambda r:(-r['dps'],r['chunk']))[:args.top]:
        equipped=tuple(items[i['code']] for i in row['items'])
        call=(equipped,space.talents,space.glyphs,space.picks_without,space.picks_with,space.glyph_picks)
        start=time.perf_counter()
        staged=finish_sextuple('mage','fire',args.targets,*call)
        # Exhaustive T/G at staged ESC; optional zero slice. Not exhaustive ESC.
        vectors=([empty_points()] if args.zero_esc else [])+[staged[3]]
        result=refine(*call,targets=args.targets,point_vectors=vectors,max_seconds=args.max_seconds)
        reports.append(dict(chunk=row['chunk'],staged=staged,joint=result,
                            regret_lower_bound=max(0.,result['best']['dps']-staged[0]),
                            regret_exact=(result['best']['dps']-staged[0] if result['complete'] else None),elapsed=time.perf_counter()-start))
        Path(args.output).write_text(json.dumps(reports,indent=2),encoding='utf8')
    print(json.dumps(reports,indent=2))

if __name__=='__main__':main()
