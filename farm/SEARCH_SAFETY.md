# Item admission and checkpoints (schema 2)

Default: `admission_policy: "all"`. Every item sextuple reaches talent/glyph/ESC
optimization in both CPU and hybrid workers. Item-only DPS is not an upper bound
on a synergistic finished build. This default can cost substantially more work
than the previous bare top-10 filter; no speedup or new full-search result is claimed.
Talent selection, then glyph selection, then greedy ESC are still staged heuristics:
a completed item sweep is **not** proof of a global optimum.

The old, unsafe filter is available only with job JSON
`"admission_policy": "unsafe-bare-top10"` or `FARM_UNSAFE_BARE_GATE=1`.
An explicit job policy overrides the environment. Startup/status/result metadata
mark it UNSAFE HEURISTIC. Do not label its leaderboard exhaustive.

Snapshots store `item_observations`, each with chunk identity and DPS, separately
per overall/shop/drop category. Overlapping saves merge by identity, not by float.
Different chunks with equal DPS remain distinct. Replayed identities count once.
`item_bar` is retained as a derived display-only float array for old readers.
Anonymous legacy floats are never restored as active gate observations.

Schema-2 checkpoint and result filenames use a separate context suffix. The
context includes admission policy, job scope, a catalog/enumerator fingerprint,
and a conservative hash of scoring Python sources. Compatible schema-2 resumes
restore observations and finished spans. Old/incompatible checkpoints are not
trusted for done spans, nor silently imported; a new context starts from the job's
start. Original checkpoint/results remain untouched. This avoids preserving already
pruned chunks as supposedly evaluated. Source changes invalidate the context even
when unrelated to a hero; this conservative behavior costs reprocessing.
Do not edit scoring sources during a running farm: spawned processes can retain
older imported modules. Context fingerprints are captured at coordinator startup,
not a mechanism for hot-reloading or freezing workers.

Historical Shadow top100 result (3332.324551186275) skipped the admissible old
winner (3523.828806953591) at the bare gate. Checkpoint union also multiplied
repeated maxima. Fixing the code cannot repair its existing done watermark.
Any reliable replacement result needs a new controlled reprocessing with schema2
and a lossless item admission policy. No new full farm is part of this fix.
The restored Priest HTML is the historical top80 result, not a new exhaustive
2.5.2b result and not a measurement of patch damage impact.

Bounded regression suite:
```
.venv-dml\Scripts\python.exe -B -m unittest farm.test_admission farm.test_farm farm.test_hybrid
```
Real DirectML old-winner worker replay (one sextuple, not a farm): set
`FARM_ADMISSION_DML_TEST=1`, then run `farm.test_admission.ShadowDirectMLTest`.
