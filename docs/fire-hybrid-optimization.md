# Fire hybrid execution: scope, safety and tuning

The scheduler/planner remains CPU float64. DirectML compiles event-weight sums;
this is not a full-GPU simulation or a proof of a global optimum.

## Defaults and lifetime

- `FARM_FIRE_TAPE_CACHE=1` (default): per-engine 128-entry / 32 MiB conservative
  logical-budget LRU of immutable tapes, never a disk or cross-job singleton.
  This new LRU covers the default vector scheduling path. Explicit legacy
  `FARM_HYBRID_GPU_TIMELINE=0` keeps its existing capture/cache path; that legacy
  cache is not converted by this change. The estimate is not process RSS.
  Immutable tapes do not enter the legacy global
  event-array cache, so eviction really releases the engine-owned references.
- Keys retain ordered complete item attributes, talents, glyphs, ring binding,
  every sheet field except proven-safe potency. Crit/luck stay baked. In particular
  **Blazing Soul I0KR changes bomb_period with potency**; the derived period stays
  in the key, so those potency trials cannot share a tape.
- Source/body proofs and PID/spec/targets/function/config epochs invalidate reuse.
  Mutable dict/regex policies are included. Unknown code, including wrapped
  monkeypatches or mechanics edits, gets fresh unclustered tapes. The reviewed
  source fingerprints must be deliberately renewed after a mechanics change.
- `FARM_FIRE_DEVICE_POOL=1` (default): per-engine/PID/device input and constant
  tensors, 32 MiB exact resident tensor-payload cap, LRU eviction. Backend allocator
  and graph memory are not covered by that payload figure. In-place upload failure
  discards stale buffers and uploads fresh data; unsupported compile ops use exact
  CPU scoring with counters. Outputs synchronize before pooled inputs are reused.
- Compile batches retain order, at most 512 timelines, and a conservative 64 MiB
  padded-working-graph estimate. An oversized individual row is scored on CPU.
  This estimate is not a hard guarantee on total VRAM or backend graph caches.
- `FARM_MAGE_FAST_PUSH=1` (default): exact host NumPy-view writes in the CPU
  scheduler, replacing the profiled repeated tiny Torch masked assignments.
  Device tensors retain the original Torch path; `=0` is the verified control.
  Event/step overflow still rejects the tape and replays complete CPU events.
- `FARM_FIRE_FINAL_GPU=0` (default): GPU final linear DPS and GPU ring reduction are
  implemented and tested, but opt-in because the fixed-workload measurements were
  slower with guards. Enable `=1` only for an explicit measured experiment.
  Sheet/raw/armor coefficients remain CPU work. The GPU evaluates their final
  linear form and ring maxima without copying the full weighted-sum matrix back.
  Near ties use fresh CPU evaluation. Each gear-group chunk winner is also CPU
  canonicalized, preserving first ties across chunk/phase boundaries. Individual
  non-winning GPU values are approximate, not bit-identical CPU floats. Source
  fingerprint/domain/unsupported-op failures use exact CPU fallback. The existing
  separate ESC algebra planner/scorer is not rewritten by this final-score flag.

Engine telemetry: `tape_cache.counts`, `device_pool.counts`, `timeline_counts`,
`score_counts` expose generated/hit/clustered/evicted/unverified rows, resident
payload, allocation/reuse, compile batches, overflow/fallback and exact guards.

## Search admission and the unimplemented finite upper bound

Safe admission remains `all`, schema 2. A bare item score is **not** an admissible
bound on later talents/glyphs/ESC: `test_mage_bounds` gives a legal Top100 Fire
counterexample. Blazing Soul changes cadence, and other choices change casts,
resources and proc/state transitions. A fixed-tape affine score is not a bound
on those unresolved timelines. No new finite general item-admission bound has
been proved or enabled in this change; unsupported spaces continue without that
prune. Do not replace this with a constant multiplier or label a heuristic safe.

`unsafe-bare-top10` remains an explicitly named opt-in legacy heuristic, never an
exhaustive claim. Identity-aware snapshot merge/legacy checkpoint isolation from
d24a603 is unchanged. New production source changes alter the scoring fingerprint;
incompatible old done spans must not silently become valid under new code.
Even with all item combinations admitted, staged talents, then glyphs, then greedy
ESC do not establish the global joint optimum. Previously invalid Shadow/Top100
searches are not repaired by relabelling checkpoints; missing work must be rerun.

## Measurement and operations

Use fixed identical inputs, complete device synchronization, separate cache-cold
and warm timings and report counters/guard frequency. Repeated tapes are a reuse
microbenchmark, not an estimate of full-farm throughput over unique item sextuples.
No full farm or bot restart is part of these changes. Resident processes can retain
old imports; disk commits are not evidence of hot deployment. Discord's adapter
imports the hybrid runner lazily, and fresh spawned workers import from disk, but
actual runtime adoption must be verified on the user's next job without duplicating
or interrupting it.


## Follow-up validation and corrected selection

See [fire-hybrid-followup.md](fire-hybrid-followup.md) for real unique-sextuple
benchmarks and the precision counterexample found beyond single-fight parity.
`FARM_MAGE_FAST_HYDRA=1` adds bitwise-equivalent host first-free-slot writes.
`FARM_FIRE_EXACT_SELECTION=1` now applies the conservative near-tie/chunk-winner
CPU canonicalization even with GPU final disabled, using CPU owner grouping.
Disabling GPU final no longer disables that correctness guard. The unsafe
`FARM_FIRE_EXACT_SELECTION=0` control can reproduce a pre-existing ESC selection
loss; it is not a recommended default. GPU final arithmetic remains opt-in.
Actual GPU clocks are still not enabled: the live DirectML f64 arithmetic probe
fails precision even though nominal f64 tensor allocation succeeds.
