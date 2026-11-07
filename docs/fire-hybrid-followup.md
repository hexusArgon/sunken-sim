# Fire follow-up: bounded validation (2026-11-07)

## Runtime adoption — no Discord action

`farm/bot.py:652` calls the adapter on `asyncio.to_thread`: this does **not** give
its parent fresh Python imports for every job. The adapter imports the hybrid
runner lazily. If that import has happened before an on-disk update, parent parity
checks can still use old modules. Do not infer resident adoption from disk HEAD.
`farm/runner.py:628,738` uses a new `spawn` ProcessPoolExecutor per job; its worker
imports come from disk. A fresh offline adapter/process smoke test can prove this
route without touching Discord, but cannot inspect resident Python module state.
No resident bot restart or hot reload is part of this work.

## A real GPU scheduler on this machine

`generate_mage_timelines` explicitly redirects DirectML (`privateuseone`) clocks
to CPU float64. `FARM_HYBRID_GPU_TIMELINE=1` selects a vector CPU planner on this
hardware, not GPU clocks. A live precision probe shows why allocation alone is insufficient: nominal f64
DirectML addition loses 1e-12 increments and comparison at 1+1e-12 disagrees with
CPU float64. `gpu-clock-capability.json` records values and CPU controls. Thus
removing the redirect does not supply sufficiently precise clocks; using f32
changes event ordering/ties and is not justified by compile-stage parity.
Compare scalar CPU capture with vector CPU planning, not fictional GPU scheduling.

## Bounds: restricted proof attempt and refusal to prune

With fixed gear, talents, glyphs, binding, all sheet stats except potency, and a
verified potency-independent tape, `_score` is affine in potency. On a closed
potency interval the real-arithmetic maximum is at an endpoint. This statement
requires the same complete tape and constants; source verification and cache keys
are necessary conditions, not permission to prune an unresolved item loadout.
Blazing Soul violates the tape premise through `bomb_period`. Even WITHOUT it,
unresolved talents/glyphs/mastery/haste/mana can change casts, resources, procs,
and coefficients. Nor does a fixed-tape affine statement establish a floating-
point upper envelope for arbitrary unsupported stats or cancelling terms.

Therefore no endpoint bound is installed in item admission. Its upper bound
remains +infinity/no-prune. The legal bare-score counterexample stays a regression.
A finite bound for the trivial fixed-choice potency subproblem would not reduce
the current staged talent/glyph/ESC admission space. Exhaustively maximizing a
finite domain is sound but is the search itself, not a cheap bound.

The existing counterexample's full talents are I0KU/I0NZ/I0UP: it already contains
NO I0KR (Blazing Soul). Thus simply excluding Blazing Soul does not repair a bare
DPS admission bound; it only helps the much narrower fixed-choice potency proof.

## Opt-in joint refinement

`python -m farm.hybrid.mage_joint --input <bounded-bench.json> --output <joint.json>`
exhausts talents x glyphs (including no glyph) for top-1 by default, using exact CPU
scores at the staged winner's ESC vector; `--zero-esc` adds the zero-ESC slice. `--top` accepts 1..10.
This explicitly expensive, offline mode is NOT enabled in resident farm jobs.
It measures regret only in these supplied ESC slices. It does not exhaust all ESC
splits, establish a global item optimum, or claim that maximizing before ESC can
be interchanged with maximizing after ESC. The API accepts explicit legal vectors
for further bounded audits. Strict `>` preserves the first enumerated exact tie.

The current `esc_device.algebra_mode()` default is `auto`, despite older text
calling ESC algebra opt-in. The benchmark leaves this default unchanged on both
arms; this is recorded because warm router choice can otherwise confound timing.

Nested planner multiprocessing was considered, not enabled: the farm already
spawns up to `os.cpu_count()-1` workers by default (`runner.worker_count`). A
second process pool inside each worker would oversubscribe those cores and add
serialization, while the measured hotspot is the per-row Hydra insertion loop.
The candidate optimization preserves row order, first-free-slot choice, dtype,
reclamation/caps, and cadence, retaining the original Torch loop as its control.

## Search precision regression exposed by the real bounded workload

Single-fight tolerance is not enough for a greedy search. On legal Top-100 chunk 2,
the prior vector path (including historical 47e8d1b) picked 2 mastery / 6 luck
instead of the old CPU's 0 mastery / 8 luck, with the other ESC choices equal.
Its final DPS was 2006.3458333333333 instead of 2157.6422112651026. The leading
chunk ID stayed the same, so checking only the leaderboard's identity missed it.

The previous CPU canonicalization existed only under `FARM_FIRE_FINAL_GPU=1`.
`FARM_FIRE_EXACT_SELECTION` separates that correctness guard from the GPU final
arithmetic: CPU max/runner-up grouping now reuses the same conservative near-tie
and per-gear/chunk-winner exact CPU re-evaluation, without uploading approximate
scores back to the device just to find their maxima. The original GPU-final route
keeps its GPU owner reducer. This is not heuristic pruning or a proof about
arbitrary device rounding; it preserves the existing conservative guard policy.
The real chunk-2 regression tests old CPU talents/glyphs/ESC, CPU/Torch and
DirectML scoring, and fresh/reused results. Guarded final non-winning approximate
scores still need the usual 1e-4 parity check.

## Measured results and defaults

- `FARM_MAGE_FAST_HYDRA=1`: exact host insertion; `=0` retains the original loop.
- `FARM_FIRE_EXACT_SELECTION=1`: CPU owner grouping plus exact selection guards;
  `=0` is only a regression control, not a recommended correctness/performance mode.
- `FARM_FIRE_FINAL_GPU=0`: explicit `=1` remains a measured experiment.
- No new admission prune and no new process pool. No Discord restart.

Real Top-100 mixed unique sextuples, two consecutive ranges, 4 rows per range:

| Range | historical 47e8d1b | corrected guarded hybrid | old CPU |
|---|---:|---:|---:|
| 0..3 | 57.431 s | 43.935 s | 8.673 s |
| 100000000..100000003 | 56.111 s | 54.652 s | 15.215 s |

All corrected items/talents/glyphs/points match the old CPU. Maximum DPS relative
error is 5.55e-8. Historical first-range payload fails parity (the ESC counterexample
above), so these timings must not be sold as a same-quality end-to-end speedup.
The short range underfills the 16-row cross-build group; it is not steady-state
whole-farm throughput. CPU was faster on both of these bounded ranges.

Corrected throughput: 83.31 / 66.97 fights/s. Tape LRU hits: 8.42% / 9.55%; hits plus
in-batch clustering: 26.35% / 26.45%. Generated rows: 2955 / 2834. Vector timeline
fallback rows: 0 on these ranges; real overflow/step fallbacks are tested separately.
Scalar capture + GPU compile on range 0..3 took 7.095 s, but retains the legacy
process-global cache contract (entry-capped, not the per-engine 32 MiB/source-guarded LRU) and is not promoted on this small sample.

For an isolated planner A/B, fix ESC strategy off (not adaptive auto), same 2664
generated rows and identical complete result payload: 41.281 -> 29.152 s (1.416x).
This factor is ONLY the Hydra switch on that fixed workload, not a claim about the
complete corrected search or arbitrary item space. Earlier co-running diagnostic
runs are not used for that speedup.

With the SAME mandatory exact guards, warm median CPU/GPU final-stage timings:

| Batch | CPU final + CPU owner grouping | GPU final + GPU owner grouping |
|---:|---:|---:|
| 16 | 20.56 ms | 21.24 ms |
| 64 | 49.85 ms | 49.57 ms |
| 256 | 341.73 ms | 344.25 ms |
| 512 | 1009.72 ms | 942.89 ms |

GPU won modestly at 512 in this sample, but these measurements do not establish a
stable monotonic production threshold. No default auto-enabling rule is installed.
The earlier comparison to an UNGUARDED CPU final is not a valid production choice:
it omitted the correctness work that fixes the exposed ESC loss.

Top-1 joint audit: chunk 2, 364 talent combinations x 221 glyph choices (including
none), all 80444 tested at staged ESC. Two contiguous deterministic ranges cover
74496 + 5948 candidates without overlap; winner 2157.6422112651026, exact regret
0 at this one ESC vector. This does NOT prove zero regret after full ESC search.

Evidence is kept in the local `_tmp/fire_next7/` run and the delivered evidence
archive, not committed scratch files. Scripts use isolated FARM_DATA directories.
