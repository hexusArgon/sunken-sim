# Discord hybrid execution

`Farm.execute` calls `farm.discord_runner.run_job`, not the CPU runner directly.
The adapter calls the common parity-gated hybrid entry for supported heroes/specs;
worker nickname/job ID/channel/status/cancel box/protocol stay unchanged. Metadata
callbacks are not passed as Discord message bodies: ordinary string progress is
preserved and a backend banner is appended. The original CPU backend remains for
unsupported/locked specs, unavailable GPU, device errors or failed prep/fight
parity. The banner, stdout and result JSON `hybrid.fallback` identify the reason.
`gpu_fights` is never true when device detection returns CPU. Per-span worker
fallback can still occur after the parent checks: the banner explicitly allows it;
worker logs identify it. This is not a fallback-free/full-GPU promise.

`start_farm.cmd` now chooses the checkout's `.venv-dml\Scripts\python.exe` and
fails clearly if it is missing. Install this repo's requirements in that venv
(`.venv-dml\Scripts\python.exe -m pip install -r requirements.txt`). Installing
or changing source does NOT reload resident bot parents.

**Activation safety:** identify exact bot PID, parent/root/data-dir and local
active jobs before a restart. Do not interrupt a farm. Current `Farm.start` also
registers a command, ensures/pins controls and sends a startup Discord message;
normal leader/worker loops can edit/send too. Source changes alone are not runtime
deployment. Do not restart it under a no-outbound-message constraint; get approval
for those effects first. This change adds no automatic restart or startup send.

## Search safety

Both Discord backends use current `farm.runner.run_job`: lossless item admission
by default, schema2 source/catalog/policy namespace and legacy checkpoint isolation.
Do not opt into `unsafe-bare-top10`/`FARM_UNSAFE_BARE_GATE=1` for a trusted search.
See SEARCH_SAFETY.md. Talent→glyph→greedy ESC is still staged heuristic, not joint
exhaustive optimization. New scoring-source fingerprints conservatively isolate
older checkpoints; an unsafe completed run cannot become valid by merging/resume.

## Mage tape capacity

`_push` permits exactly MAX_EVENTS events and latches per-row overflow on the
next active append. Rejected rows stop, and conversion refuses rejected buffers.
`MAX_STEPS` with a still-live row also rejects it. The batch returns complete rows
and re-simulates only rejected rows through the exact CPU event path, preserving
Build/ESC/spec/targets/ring binding and output order. No rejected/truncated tape is
scored. Other kernel exceptions fall back to exact CPU for the batch. CPU fallback
failure propagates; no incomplete result is substituted. CPU capture bypasses the
timeline cache. This protection covers Fire/Frost/Arcane's shared Mage generator;
no balance mechanics were changed.

Per-process `mage_gpu_timeline.TIMELINE_COUNTS` and per-engine
`GpuFights.timeline_counts` report calls/requested_rows/vector_rows/
cpu_fallback_rows/event_capacity/step_limit/batch_exception:<type>. Reasons are
also printed when fallback occurs. These are worker-local cumulative diagnostics,
not an aggregate farm-wide counter. Empty batches do not increment them.

## Actual Fire CPU/GPU boundary and follow-ups (not implemented here)

1. Profile CPU timeline/planning and safe tape reuse first: default DirectML
   vector timeline explicitly uses CPU float64, and regenerates per dps_many call.
   The alternate GPU_TIMELINE=0 path already has a CPU tape cache. A default-path
   potency-only cluster requires proof that resources/policy/cadence and all stat
   reads are unchanged, including ring bindings, mana and crit/luck dependencies;
   simply dropping potency from a key is not sufficient. In particular Blazing
   Soul (I0KR) changes Living Bomb cadence via
   `period /= 1.15 + 0.50 * potency / 100` (mage.py:_bomb_period). Preserve derived
   bomb_period in the key or exclude those variants from potency-only sharing.
   The existing shared Mage AST cache-read guard already fails on the baseline;
   investigate that drift before expanding reuse. Reuse must pass fresh
   CPU/old-reference/event-reuse and capacity regressions.
2. Reduce device transfer/packing/allocation: compile_sums rebuilds target tensors
   and copies reductions back every batch. Cross-build batching already exists
   (default on, CROSS_ROWS16/CROSS_MAX_BUILDS1024, compile MAX_BATCH512); measure actual fill/VRAM and
   bound tape sizes before increasing it. Persistent device data is not present
   in this Mage path. No speedup estimate is established.
3. Move final `_score` and owner/ring max reduction onto device: current `_scores`
   iterates CPU `mage._score` after device sums; dps_many selects bindings on CPU.
   Preserve strict-first tie behavior and float32/float64 parity.
4. Profile enumerate/decode/sheet/policy/greedy decisions separately before moving
   planning. ESC algebra already defaults auto, guards/weights CPU float64; device
   weight-IR is an optional single-greedy path, not threaded through cross-build.
5. Only proven upper-bound pruning may become safe default. Bare DPS is not such
   a bound. Until a bound includes talent/glyph/ESC/item synergies, admit all items.

No full-GPU scheduler or full farm is part of this change.
