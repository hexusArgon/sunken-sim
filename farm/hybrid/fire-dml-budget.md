# Fire DirectML process budget

Fresh Fire jobs still use the single hybrid route and the shared running **bare-top10** heuristic. CPU oracle/planner, exact winner guards, source/tape invalidation, ESC, merge/checkpoint semantics are unchanged.

RX6800XT measurements found long native DirectML waits with15 live device owners. Serializing compile dispatch did not remove the stalls. The identical212992–213247 bare input (256×243 event shape) completed in0.392s with one device context and exact CPU scores. This establishes a context-count sensitivity, not a proven driver deadlock/root-cause fix.

Containment: a job-owned, spawn-shared one-token budget is allocated only for Fire+DirectML. Only one worker creates a GPU engine; other workers use the existing **explicit CPU oracle fallback**, before importing/initializing a device. The full configured worker pool remains unchanged (normally15 on16 logical cores); this does NOT mean15 GPU contexts. No standalone CPU job backend is reintroduced.

Metadata records `fire_dml_process_budget=1`, `pool_workers`, actual CPU/hybrid/mixed execution and fallback reason. No CPU work is presented as GPU-only. Tokens are held for the worker/job lifetime, fail closed after a failed owner, and are not a cache or a cross-job resource. No environment override bypasses the budget. Non-Fire classes and non-DML paths are unchanged.

Limits: this is operational containment, not a single-GPU RPC service or repair of the native backend. Concurrent independent jobs do not share this job-local budget. Resident bots are not reloaded by a commit; only fresh processes adopt it. No full-run ETA follows from a short cold benchmark.

## Explicit job-local resource cap (t278)
`fire_dml_workers: 6` requests up to six live worker owners; omitted stays1. Integer1..6 only; seven and above are rejected because measured native waits begin at7 on this device. Other specs are unchanged. Denied workers retain CPUoracle fallback before deviceinit.
For explicit counts>1 the identical item/fight preflight runs in an isolated short-lived child. It must exit cleanly before the worker pool starts; coordinator holds no GPUhandle. Failure refuses the explicit multi-GPU job, never silently launches a CPU-only farm. Per-PID returned-span telemetry distinguishes actualGPU/CPU paths.
This is resource scheduling only: baretop10, search order, candidates, tie policy and exact guards are unchanged. Source fingerprints remain strict. An older checkpoint requires an explicitly audited resource-only migration: archive original, verify numerical-source/AST invariants and parity, copy every saved field unchanged except new scoring fingerprint, then validate native loader restores all spans/bars/boards. No generic source-signature bypass exists.
