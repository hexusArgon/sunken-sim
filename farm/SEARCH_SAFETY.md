# Bare top-10 admission and identity-aware checkpoints (schema 2)

Production policy: `admission_policy: "bare-top10"` (default and only mode).
Every legal item sextuple first gets its item-only / bare DPS. Talent, glyph and
ESC refinement runs only when that score enters a current bare top-10 category.
The overall ten receives all source groups; pure shop also checks the shop ten,
pure drop also checks the drop ten. Admission in ANY relevant category is enough.
Underfilled categories accept ties; a full category rejects score <= its tenth.
All relevant categories update independently in scan order. This restores the
pre-d24a603 threshold, tie and category semantics for distinct chunks.

This is an intentional heuristic, not an upper-bound proof. A low bare score can
have strong talent/glyph/ESC synergy. No global optimum is guaranteed, even after
a complete item sweep. Historical Shadow winner3523.828806953591 was rejected at
bare1437.650818627451 below floor1466.4726078431374; that limitation is documented,
not hidden by changing the default back to all-admission. Talent/glyph/greedy ESC
selection remains staged as before.

Compatibility:
- Fresh job `unsafe-bare-top10` is accepted as an alias and normalized to `bare-top10`.
- Fresh job `all` is rejected clearly BEFORE catalog/device/work. It cannot bypass
  the user's restored gate. Other unknown policies are rejected too.
- The old `FARM_UNSAFE_BARE_GATE` switch is obsolete and ignored: neither0 nor1
  (nor any other value) enables all-admission. There is no all production mode.
- Fresh Fire bot/CLI/local jobs use one hybrid backend. Legacy auto/cpu/staged
  backend requests normalize to hybrid with explicit metadata; staged switches
  no longer select a CPU route. CPU oracle/planner/exact scoring and explicitly
  labeled emergency CPU fallbacks remain. Other class routes and worker/thread
  defaults are unchanged.

Identity-aware merge/dedup fixes are retained. Snapshots store chunk identities,
not anonymous threshold floats. Replaying one identity is not a new observation;
different chunks with equal DPS remain distinct. Anonymous legacy gate arrays
are not imported as active state. Direct fight diagnostics without a farm
coordinator have no shared gate; every production run_job creates validated slots.

Checkpoint/result namespaces retain policy, scope, schema, catalog and scoring
fingerprints. Alias normalization is ONLY for fresh configuration, never stored
metadata: old `all`, old alias-policy or incompatible source/catalog spans and
thresholds are not silently imported. Legacy files are not deleted or migrated.
New code uses its own context; existing running processes are not hot-reloaded.

Output top-10 merging is separate from the admission gate. `item_sweep_complete`
means all numbered sextuples were examined. `admission_is_lossless`,
`item_admission_complete`, and `global_optimum_proven` are false for this heuristic;
a complete sweep does not mean every sextuple received expensive refinement.

Bounded tests (no Discord client/network):
```
.venv-dml\Scripts\python.exe -B -m unittest farm.test_admission farm.test_farm farm.test_hybrid farm.test_discord_runner
```
Set `FARM_ADMISSION_DML_TEST=1` for the bounded CPU/DirectML counterexample test.
No full farm, process restart, historical-result replacement or ETA is part of
this restoration.

## bare-top50 (2026-11-12)

Default for Priest, Paladin, Shaman, Mage and Druid (`farm.admission.TOP50_HEROES`); every other hero keeps
`bare-top10`. The gate remembers the item-only top-50 sextuples of each category (Shop + drop, Shop only,
Random drop) and refines talents, glyphs and greedy ESC for a sextuple that enters them. While the run goes,
the 50 best finished builds of each list are kept (checkpoints too); when the whole span is done, only the
top-20 of each list is written and the other 30 are dropped (`FINAL_KEEP`). A stopped run writes what it has.
The policy name is part of the result/checkpoint suffix, so a bare-top10 checkpoint is never resumed as top-50.

