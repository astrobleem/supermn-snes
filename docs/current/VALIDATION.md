# Validation commands and evidence scope

Run the smallest gate that can falsify the change, then add wider gates in proportion
to the risk. Assembly success alone is never a correctness result.

## Documentation and private-input tooling

```sh
python3 tools/check_doc_links.py
python3 -m py_compile tools/prepare_roms.py tools/transpile.py tests/test_prepare_roms.py
python3 -m unittest discover -v
python3 tools/prepare_roms.py /path/to/superman.zip --dry-run
python3 tools/prepare_roms.py /path/to/superman.zip --validate-only
```

These prove links, Python syntax/unit behavior, set authentication, deterministic
derivation, and existing-output identity. They do not prove the game runs.

## Build and layout

```sh
bash tools/build_interp.sh
python3 tools/audit_banks.py
stat -c '%s' build/interp.sfc
sha256sum build/interp.sfc
```

The normal build must produce a 4,194,304-byte ROM. `build_interp_rom.py` contains
exact-byte, seam, bank, boot-asset, and packing assertions; `audit_banks.py` is an
additional lower-bound overlap check for its covered escape-bank set. Follow a layout
change with a fresh cold boot and the relevant differential.

Use the diagnostic recorder only when required:

```sh
PC_RING=1 bash tools/build_interp.sh
# run the diagnostic
bash tools/build_interp.sh
```

The `PC_RING=1` ROM has measurable overhead and cannot support production performance
claims.

For a Stage-3 BSR/PC-relative-JSR escape route change, run the real-call
validator, not the generic OJMP/table harness:

```sh
python3 tools/test_stage3_call_site_routes.py
python3 tools/validate_stage3_player_bsr.py \
  --rom build/interp.sfc \
  --fixtures build/playtest-investigation-20260725/stage3-selector-scroll-snes-fixtures-v1 \
  --output build/validate-stage3-real-call-current.json
```

The `$02E42C` selector's JSR call site is determined by each fixture's stacked
return (`$0278E6` or `$02F2DE`). The result is a bounded exact MAME/native-off/
native-on semantic and natural-route differential; it does not prove virtual-
IRQ cadence, fresh Stage-3 progression, or rate.

## Interpreter semantics

With MAME 0.287 and Nexen MCP configured:

```sh
python3 tools/optest.py
python3 tools/opsweep.py
```

When the revision-4339 snap is not mounted at its historical path, stage its
exact payload under the gitignored build tree without replacing the installed
snap:

```sh
bash tools/stage_mame_0287.sh
```

`tools/mame_0287.py` and `tools/mame_0287_exec.sh` discover that staged
payload and still require the pinned 0.287 version and SHA-256; an arbitrary
host MAME cannot satisfy the oracle contract. `SUPERMN_MAME_EXE` and
`SUPERMN_MAME_LD_LIBRARY_PATH` remain explicit overrides for another extracted
layout.

Latest retained gates are 160/160 optest groups and 782/782 opsweep cells
(1,564/1,564 vectors). These prove covered instruction fixtures. They do not prove
every whole-game address path, RAM-resident instruction fetch, device mapping, or
fast-path region assumption.

## Native escape or HLE change

Minimum evidence:

1. prove the entry executes with an SA-1 execution hook in the actual `$92+` bank;
2. run the focused MAME fixture/differential;
3. run gate-off and gate-on on fresh adjacent states;
4. compare registers, CCR, terminal PC, mapped work RAM, and `$41` video shadow when
   relevant;
5. run a multi-tick gameplay/checkpoint soak; and
6. cold-boot the final exact ROM if the path affects scheduling, layout, input, combat,
   rendering, or sound.

The established adjacent-tick workflow is:

```sh
export SUPERMN_SCRATCH=/path/to/private/flytick-data
python3 tools/flyval.py 7000
```

The address/fixture argument is target-specific. Consult
[the transpiler workflow](../toolchain/TRANSPILER_WORKFLOW.md) before interpreting
stack residue or a sparse capture.

For the CE58 coroutine's native `$13BE`/D18A return-frame convention, retain the
exact-boundary state and run:

```sh
python3 tools/validate_13be_sentinel_route.py \
  --rom build/interp.sfc \
  --state build/playtest-investigation-20260725/fresh-campaign-rom567a-to1000-v4/states/retained-boundary-00850.mss \
  --nexen /mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen \
  --output build/validation-13be-sentinel-route-current.json
```

The repaired route must preserve task-5 context for all 44 fenced entries and
complete without margin exhaustion. This is a checkpoint boundary regression;
it is not fresh-boot or full-playthrough evidence.

## Rendering

Choose the focused validator for the changed path:

- `tools/validate_fast_obj_renderer.py`
- `tools/validate_obj_cache_vram.py`
- `tools/validate_paced_obj_sources.py`
- `tools/validate_vertical_scroll_bridge.py`
- `tools/capture_mesen211_transitions.py`
- `tools/trace_playtest_actions.py`

A synthetic or checkpointed test proves only its named invariant. Rendering acceptance
also needs an unmodified fresh boot, screenshots/PPU state, continued ticks/renders,
and eventually an aligned MAME frame comparison.

For the supplied legacy-Mesen Stage-3 checkpoint's stale PPU-scroll boundary,
the focused probe must preserve the serialized initial image, advance one neutral
vblank, require no game-tick advance, and then test for the blue strip. It must
not use movement as the recovery condition:

```sh
python3 tools/validate_stage3_scroll_input_probe.py \
  --rom build/interp.sfc \
  --state build/playtest/stage3.mss \
  --mesen tools/mesen211_mcp_controller.sh \
  --output build/validation-stage3-restore
python3 tools/test_stage3_scroll_restore_protocol.py
```

This state is not portable to Nexen (the latter restores its boot screen rather
than Stage 3), and MAME has no serialized SNES PPU register to compare. Label any
such result stale-save-state renderer evidence; it cannot close fresh Stage-3,
MAME-pixel, timing, or playthrough acceptance by itself.

## Scheduler, renderer ownership, and performance

The formal cold-boot harness is:

```sh
python3 tools/recovery_baseline.py \
  --rom build/interp.sfc \
  --gameplay-right-b \
  --uninterrupted-gameplay-frames 3600 \
  --output build/validation/production-coldboot
```

Use a fresh port and retain the complete output directory. A qualifying result must:

- start from power-on with `TESTFLAG=0`;
- arm production gates organically;
- drive the real port-0 controller/mailbox;
- validate `$0760` against `$00:F5A3`;
- include waits, IRQs, rendering, input, audio supervision, and transitions;
- cross the known scheduling event;
- check task-stack floors and recent tick/render progress; and
- identify the exact source and ROM hash.

Checkpoint tools such as `soak_gameplay_ordering.py` and `profile_continuous.py`
provide focused ordering/attribution evidence, never end-to-end fps.

### Save-state boundary contract

There are two deliberately different controller-campaign save-state classes:

- `post_entry_safe_snes_boundary` states are retained only after the active native or
  interpreted exact `$003A92` entry has rendezvoused at the next main-SNES pre-opcode
  boundary. Their event row must set `resumable_checkpoint=true`, set both
  exact-entry flags false, and authenticate the state hash and fresh-power-on ROM
  lineage. In interpreted mode, virtual PC may still read `$003A92` after the
  debugger exact stop has been removed and the SA-1 has advanced into the body. Such
  a state is accepted only with retained source-to-boundary SA-1 PC progress, all
  rendezvous checks green, zero additional IRAM `$0040` low-byte `$92` writes, and
  byte-identical repeated saves.
- `sa1_exact_entry_nested_forensic` and `iram_exact_entry_nested_forensic` states are
  snapshots inside the debugger's native or interpreted exact-stop delivery stack.
  Their event row sets `nested_sa1_entry_nonresumable=true` and
  `resumable_checkpoint=false`. They may preserve an exact observation, but
  reloading them is not evidence of production execution.

`tools/capture_snes_movie_ticks.py` requires a safe lineage log by default. Its
`--allow-forensic-nonresumable-state` option exists only to reproduce debugger/save
behavior and labels the result as nonresumable and unsuitable for a ROM-behavior
claim. Run `python3 tools/val_capture_state_resumability.py` after changing this
contract.

### Diagnostic cross-ROM checkpoint migration

Candidate iteration may explicitly use `--allow-resume-rom-migration` with an
authenticated `post_entry_safe_snes_boundary` state from a different ROM hash.
This is a diagnostic shortcut only. The runner authenticates the entire original
fresh-boot lineage and atomic checkpoint before any write, retains the fresh-root,
checkpoint-ROM, and selected-ROM hashes, and permits a changed native symbol table
only as a recorded compatibility exception.

The sole architectural mutation is the reset-equivalent refresh of executable
video-supervisor/renderer WRAM `$7F:8000-$7F:AFFF` from selected-ROM file offset
`$298000`. The paused 5A22 PC must not overlap a changed byte. Three audited 4 KiB
writes must exactly reproduce the selected ROM, after which CPU state, PPU/frame
state, game work RAM, SA-1 IRAM, VRAM, CGRAM, OAM, SPC RAM, and all WRAM outside
that 12 KiB window must remain byte-identical. No MAME-to-SNES game-state copy,
CPU-state transplant, or silent VTIME-layout conversion is allowed.

Use the nearest pre-divergence same-hash checkpoint for candidate diagnostics
(currently tick 14,500 for the tick-14,748 campaign mismatch), then replay only
the focused suffix. Checkpoints created by that run may continue the migrated
diagnostic lineage under the same candidate hash, but none becomes fresh-boot,
FPS, renderer/HUD acceptance, or release evidence. Any changed serialized-state
layout requires an explicit, separately guarded translator. A candidate that
passes focused migration still requires one fresh power-on acceptance campaign.

Run these regressions after changing the contract:

```sh
python3 tools/test_campaign_resume_lineage.py
python3 tools/test_campaign_rom_migration.py
```

### Oracle-continuation pre-failure retention

An explicit `--continue-oracle-divergences` run preserves coverage after its
first mismatch, but it must not let a later controller input replace the state
needed to reproduce that first result. When `--retain-input-prestate` (or a
selected `--retain-input-prestate-tick`) is active,
`replay_mame_controller_campaign.py` now immediately copies the current
pre-input state and SA-1 IRAM sidecar to a named
`pre-failure-<kind>-tick-<tick>.mss` artifact at each oracle observation. The
record retains source and copied SHA-256 values, and declares the snapshot an
exact-entry forensic state—not a resumable checkpoint.

The current active-ROM demonstration is
`build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2`: after
green comparisons through its tick-14,839 input boundary, the first downstream
mismatch is tick 14,841 and its immutable source artifact is
`states/pre-failure-input_response_compare-tick-14841.mss`. This is the
post-virtual-IRQ suffix of the exact Stage-3 three-way failure; it does not
replace the MAME/native-off/native-on root comparison at tick 14,746 or become
fresh-boot, rate, or full-playthrough evidence.

Run both regressions after changing the campaign harness:

```sh
python3 tools/test_campaign_pre_failure_state.py
python3 tools/test_stage3_post_irq_continuation_a976_evidence.py
```

### Fresh gameplay-root-off controller boundary

With `$071A/$073A` deliberately cleared after the matched fresh gameplay origin,
the native `$92:DB82` update hook is intentionally unreachable. A native-address
exact stop must therefore not be used to classify the disabled-root mode.
`tools/replay_mame_controller_campaign.py` switches to the project IRAM-edge
Nexen endpoint and its counted rising virtual-PC `$003A92` stop at IRAM `$0040`.
The narrowed cold-boot proof is retained at
`build/fresh-campaign-current-a976-native-off-first-entry-v6`: it is explicitly
`partial-green`, includes its direct stop reply in `events.jsonl`, and has no
attack, boss, death, Stage-3, rate, or full-campaign assertion. The opt-in
`--allow-incomplete-coverage` flag labels such a prefix rather than weakening the
default complete-controller coverage gate. It reports `partial-green` only
when no oracle discrepancy was observed; an explicitly continued discrepancy
is labelled `partial-with-oracle-divergences`. It does not mean all native
escapes are disabled; it affects the named gameplay-root gates only.

The companion fresh run
`build/fresh-campaign-current-a976-native-off-first-movement-v1` continues to
tick 1,060, retains the pre-input state, applies Left at tick 1,054, and has
two green MAME player comparisons (including X 64 to 61 at tick 1,056). It is
still a partial root-off differential; use the separate focused attack, crate,
boss, and Stage-3 tests for those claims.

Run the focused source/transport regression with:

```sh
python3 tools/test_campaign_native_off_exact_entry.py
```

The current active-ROM evidence regression additionally checks the retained
fresh artifact, exact edge contract, MAME-matched origin, and its explicit
coverage gaps:

```sh
python3 tools/test_gameplay_current_a976_evidence.py
```

This distinction invalidated a July 28 tick-7563 virtual-IRQ diagnosis that had been
derived by reloading an explicitly nonresumable exact-entry state. The retained
correction is [the exact-entry state forensic report](../history/forensics/NONRESUMABLE_EXACT_ENTRY_STATE_20260728.md).

## Sound

Required mechanical gates include:

```sh
python3 tools/sound/vgm_profile.py "/path/to/track.vgm"
python3 tools/sound/vgm_ym2610.py "/path/to/track.vgm"
tad-compiler check soundwork/tad/superman_all.terrificaudio
soundwork/tad/build_blob.sh
```

Also verify the exact TAD data in SPC ARAM and the packed ROM. Mechanical equality,
ARAM fit, a non-silent WAV, or the absence of 200 ms digital silence does not prove
musical fidelity. Acceptance requires listening against the arcade/VGM reference and
recording the per-track result.

## Stage 3 virtual-IRQ ordering

`tools/validate_stage3_irq_order.py` compares retained original-code MAME work
RAM with the same authenticated safe checkpoint under native-on and an explicit
native-off mode. It checks task-15 registers, SR/CCR/X, saved stack/return
state, game-owned records, virtual-IRQ state, and exact-run cadence. A red
result is a failed regression gate, never an accepted behavior result.

The current full-all-escape-off/native-on matrix is intentionally red at tick
14,746 and is retained at
`build/validation-stage3-irq-order-all-native-off-current-f369-v1.json`.
Re-run its artifact comparison with:

```sh
python3 tools/validate_stage3_irq_order.py \
  --mame-summary build/mame-current-f369-fresh-stage3-rng-first-divergence-v1/summary.json \
  --native-off-summary build/forensic-stage3-safe14743-all-native-off-exact-edge-v2/summary.json \
  --native-on-summary build/forensic-stage3-safe14743-native-on-exact-edge-v1/summary.json \
  --ticks 14744,14745,14746 \
  --output build/validation-stage3-irq-order-current.json
```

Omit `--allow-red` in normal regression use so the command fails while the
defect remains. The tool does not generate captures and does not make a
fresh-boot, full-playthrough, or rate claim.

`tools/capture_stage3_irq_delivery.py` is the complementary physical native-on
probe. It loads the authenticated safe checkpoint, observes the third
`$025110` collision entry (the update that maps to tick 14,746), and then
stops at virtual-IRQ entry `$00:B404`. It makes no architectural writes beyond
the checkpoint's real held-input value, records the task frame, virtual-IRQ
state, collision/player hashes, and explicit `$025110` yield-hook hits, and is
intentionally red on the current candidate:

```sh
python3 tools/capture_stage3_irq_delivery.py \
  --rom build/interp-before-pool-dispatch-f369.sfc \
  --output build/capture-stage3-irq-delivery-current-f369 \
  --allow-red
```

The retained `...-v3/summary.json` shows task 15 still at `$02429C` and
logical PC `$0818` at IRQ entry, instead of MAME's `$0259B0`/`$0242BE` task
frame. This is a native-on checkpoint forensic only; retain the three-way
gate above for the actual native-off/native-on/original-code classification,
and do not treat either tool as fresh-boot or rate evidence.

`tools/capture_mame_25110_irq_phase.py` is the complementary original-code
cycle oracle. It cold-boots exact MAME 0.287 with the retained movie, uses
read-only program taps plus the debugger trace, and records MAME's
`totalcycles` value. With the exact MAME payload environment described in
[BUILDING.md](BUILDING.md), capture and validate it with:

```sh
python3 tools/capture_mame_25110_irq_phase.py \
  --output build/mame-25110-irq-phase-current
python3 tools/validate_mame_25110_irq_phase.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --output build/validation-mame-25110-irq-phase-current.json
python3 tools/analyze_mame_25110_cycle_trace.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --output build/analysis-mame-25110-irq-cycle-model-current.json
python3 tools/audit_m68k_cycle_model.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --m68kmake /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kmake.py \
  --m68k-list /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68k_in.lst \
  --output build/audit-m68k-cycle-model-current.json
python3 tools/validate_mame_25110_branch_timing.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --m68kmake /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kmake.py \
  --m68k-list /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68k_in.lst \
  --m68kcpu /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kcpu.cpp \
  --output build/validation-mame-25110-branch-timing-current.json
python3 tools/validate_mame_25110_variable_timing.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --m68kmake /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kmake.py \
  --m68k-list /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68k_in.lst \
  --m68kcpu /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kcpu.cpp \
  --m68kops /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kops.cpp \
  --output build/validation-mame-25110-variable-timing-current.json
python3 tools/validate_mame_25110_exception_arithmetic_timing.py \
  --summary build/mame-25110-irq-phase-current/summary.json \
  --m68kmake /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kmake.py \
  --m68k-list /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68k_in.lst \
  --m68kcpu /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kcpu.cpp \
  --m68kcpu-h /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kcpu.h \
  --m68kops /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/devices/cpu/m68000/m68kops.cpp \
  --output build/validation-mame-25110-exception-arithmetic-timing-current.json
python3 tools/validate_mame_superman_vblank_clock.py \
  --driver /home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/source/mame-mame0287/src/mame/taito/taito_x.cpp \
  --output build/validation-mame-superman-vblank-clock-current.json
python3 tools/validate_virtual_irq_timer_math.py \
  --vblank-report build/validation-mame-superman-vblank-clock-current.json \
  --branch-report build/validation-mame-25110-branch-timing-current.json \
  --output build/validation-virtual-irq-timer-math-current.json
```

The retained `...-v5` validator proves the exact four-tick oracle's IRQ
periods and interruption PCs, including tick 14,746 at `$02582E`. The reducer
must show path-dependent instruction costs before any timer source change is
accepted. The MAME source checkout in the final command is a development-only
oracle, not a new repository dependency: the audit reconstructs MAME's static
CPU-000 opcode table and compares it to the executable trace without assigning
every mismatch to a particular MAME-core mechanism. The retained
`...audit...-v6` report has 46,874 comparable ROM-resident instruction pairs:
38,888 (82.96%) use the static entry, while 7,986 disagree at branch/loop,
shift/rotate, MOVEM-register-count, or multiply/divide sites. It also retains
pre-instruction registers for all 46,900 trace rows and records the debugger's
consistent two-byte pipeline-PC skew. It explicitly excludes the 21
work-RAM-code pairs for which this debugger log does not retain an opcode
word. These tools are original-MAME timing evidence
only; retain the red three-way state gate above and do not promote the capture
to a SNES fix, fresh-boot Stage-3 proof, rate result, or playthrough.

The branch proof is a separate focused regression. It uses each retained
pre-instruction SR/Dn state and trace-PC successor to predict short Bcc
taken/not-taken (10/8 cycles), word Bcc taken/not-taken (10/12), and retained
DBcc loop-back/expired outcomes (10/14). Its green `...-v2` artifact checks
10,803 records with zero mismatches. It does not manufacture coverage for the
unobserved DBcc condition-true exit and does not replace the full static-table,
native-span, three-way, or fresh-boot validation.

The variable-cost reducer is another separate focused regression. Its green
`...-v2` artifact checks all 830 retained MOVEM register lists and all 452
retained data-register shift/rotate counts, using the source-authenticated
CPU-000 handlers plus the executable trace. The exception/arithmetic sentinel
checks all 44 retained `TRAP #n` vector totals and all six observed
multiply/divide operand rows. The latter is intentionally trace-specific; it
does not claim general multiply/divide timing coverage or replace the full
native-span, three-way, and fresh-boot gates.

The vblank-clock reduction is the nominal-deadline companion to that trace. It
authenticates MAME's verified 8 MHz M68000, 57.43 Hz screen, level-6
`HOLD_LINE`, and the exact `139300 + 100/5743` cycle deadline. Its `...-v1`
artifact requires a fractional phase accumulator plus boundary delivery; it
does not substitute a source-derived timing claim for executable MAME trace
comparison.

The timer-math regression is a pre-implementation guard for the documented
2-cycle-unit representation. It proves fractional reload carry and deadline
overshoot arithmetic only; it cannot make a source edit, checkpoint, or rate
claim green.

The opt-in source diagnostic has a separate, deliberately narrow fresh-boot
liveness gate. Build a copied diagnostic artifact and run it as follows:

```sh
VTIME=1 bash tools/build_interp.sh
cp build/interp.sfc build/interp-vtime-diagnostic.sfc
python3 tools/validate_vtime_liveness.py \
  --rom build/interp-vtime-diagnostic.sfc \
  --output build/validate-vtime-liveness-current
```

The gate records the timer workspace (including native-ledger fields), adjacent
bytes, SA-1 trace tail, halt, interpreter-step count, and legacy `$AC`/pending
fields. It advances long requests in re-paused 120-frame slices by default,
or can use `--single-frame-after 1` around an experimental activation point.
It atomically retains host-side completed-request progress between slices, so a
slow MCP call cannot masquerade as a timer conclusion; that progress is not an
emulator-state snapshot. The current 24-frame liveness result is green at
`build/validate-vtime-esc9-liveness-chunked-v5/summary.json`, but it is not a
MAME differential, a Stage 3 state test, a native-off/native-on comparison, a
boot-readiness proof, or a rate result. The full fresh one-credit native-off
and native-on VTIME probes are both red; see
[VIRTUAL_IRQ_TIMING.md](VIRTUAL_IRQ_TIMING.md).

When a VTIME diagnostic is too slow for the campaign harness's default
four-frame pre-game coin pulses, classify the boundary before changing ROM
input semantics. The fixed probe is:

```sh
python3 tools/probe_vtime_credit_pulses.py \
  --rom build/interp-vtime-2429c-root-b758-v3.sfc \
  --output build/probe-vtime-credit-pulses-current \
  --hold-frames 8 --gap-frames 8
```

The retained v3 result is green 8/8 at
`build/probe-vtime-credit-pulses-3dc-v3-long8-v1/summary.json`. This authorizes
only a longer pre-game diagnostic bootstrap. It does not alter the later
tick-aligned MAME controller movie or prove VTIME timing, gameplay, or rate.
Fresh controls must also pass origin RNG and exact-entry cadence. Settle 155
misses the expected origin RNG by one Lehmer recurrence, settle 95 misses by
20, and the original settle-158 run passed origin RNG but observed only 6 of
29 requested gameplay `$92:DB82` entries over frames 5,650--8,106. Its compact
reports are
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-fresh-to3000-native-on-v1/watcher-report.json`,
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait95-fresh-to3000-native-on-v1/watcher-report.json`,
and
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait158-fresh-to3000-native-on-v1/watcher-report.json`.
Do not classify that symptom as throughput without a terminal 5A22 snapshot.
The superseding diagnosis found nested NMI/DMA replay and asynchronous
renderer-scratch corruption. Current source must retain all three guards:

- preserve both saved status bytes in `nmi_pacing_wram`;
- clear `$1F11` before writing `MDMAEN` in `service_pending_dma0`;
- preserve direct-page `$D0` around `nmi_video_keepalive`'s `bg_scroll` call.

Run `python3 tools/validate_pacing_input_order.py` after any related edit; it
byte-checks the fixed NMI slot, DMA ordering, and keepalive wrapper. The
resulting opt-in `e00fb0cb…` ROM has bounded partial-green fresh native-on and
diagnostic-tool native-off runs through tick 250, plus fresh native-on through
tick 1,100 with 98/98 retained exact-entry spans and no divergence. Its first
authenticated checkpoint continuations are sampled-player-green through tick
14,750, with 2,745/2,745 green player references, 12/12 green death/respawn
references, all listed action/button gaps closed, and retained
tick-14,743--14,747 boundary states. Those sampled fields are not task-frame
lockstep: exact work-RAM comparison first turns red at tick 14,746, the
false-hit marker at 14,839, and player state at 14,840. Review the compact
reports under
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-*`.
The exact attribution report is
`build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json`.
Re-run the retained phase reduction after changing VTIME ownership or any
pre-task-15 accelerated path:

```sh
python3 tools/validate_vtime_stage3_phase.py \
  --mame-meta build/mame-stage3-irq-phase-current-a976-14743-14747-v2/meta.jsonl \
  --root-entry build/capture-vtime-irq-boundary-e00f-14745-root-entry-v5/summary.json \
  --root-terminal build/capture-vtime-irq-boundary-e00f-14745-terminal-handoff-v8/summary.json \
  --route-trace build/capture-vtime-irq-boundary-e00f-14745-child-route-trace-v9/summary.json \
  --pre-root-trace build/capture-vtime-irq-boundary-e00f-14745-pre-root-entry-trace-v10/summary.json \
  --coverage-audit build/audit-vtime-accelerated-boundaries-b758-v3.json \
  --attribution build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json \
  --output /tmp/validate-vtime-stage3-phase.json
```

Green means the negative diagnosis remains reproduced: 114,978 cycles are
missing before `$02429C`, `$025110` is genuinely interpreted, and 185 of 192
known pre-root entry hits are outside the selected ledgers. It is not VTIME or
gameplay acceptance. The retained report is
`build/validate-vtime-stage3-phase-e00f-v2.json`.
Run `python3 tools/test_campaign_resume_input_edge.py` before changing resume
input scheduling. A safe checkpoint represents the completed tick before its
recorded `resume_mame_tick`; when that resume tick is an input edge, restore
the pre-edge buttons, reach the exact entry, then compare/apply the edge once
at that tick. The proof artifact is
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume9998-to10010-input-edge-v1/watcher-report.json`.
Longer runs should use the newest retained safe checkpoint created after tick
14,747; its authenticated event row records `resume_mame_tick` 14,748 and
state SHA-256
`1b1eec1f30e8ce27c71359d34b13864cff31b41db1fc006508ba601ffdfd4b61`.
Preserve that exact value, ROM hash, lineage events, native mode, and
exact-entry tooling provenance. This does not waive fresh ordinary-ROM
validation or turn
sampled/transition coverage into per-tick lockstep.

After changing the VTIME-only Stage-3 `$02429C` copy, regenerate its exact
original-block inventory and run both local-closure guards:

```sh
python3 tools/test_stage3_2429c_charge_blocks.py
python3 tools/audit_stage3_2429c_charge_blocks.py \
  --output build/audit-stage3-2429c-charge-blocks-current.json
python3 tools/test_stage3_2429c_handoff_protocol.py
python3 tools/audit_stage3_2429c_handoff_protocol.py \
  --output build/audit-stage3-2429c-handoff-protocol-current.json
python3 tools/test_vtime_esc5_charge_table.py
python3 tools/test_gen_vtime_esc5_root.py
python3 tools/test_stage3_2429c_common_clock_closure.py
python3 tools/audit_stage3_2429c_common_clock_closure.py \
  --output build/audit-stage3-2429c-common-clock-closure-current.json
python3 tools/test_mame_2429c_empty_fusion.py
python3 tools/validate_mame_2429c_empty_fusion.py \
  --output build/validate-mame-2429c-empty-fusion-current.json
```

Green pins the retained 35-block shape and eleven child-handoff sites in both
forms: the ordinary bank-$99 root retains its three-callee fusion and private
routes, while the VTIME-only bank-$F3 copy consumes the ordinal table, flushes
every parent transfer, interprets each child, and dispatches all eleven genuine
returns. This is local diagnostic closure only. The fusion reducer still
describes the ordinary production arm and supplies only its observed
no-crossing bulk cost and fallback rule.

The current exact runtime gates for a copied VTIME ROM are:

```sh
python3 tools/validate_vtime_esc5_root_handoff.py \
  --rom build/interp-vtime-diagnostic.sfc \
  --fixtures build/gen-2429c-distinct-arm-fixtures-current-a976-v2 \
  --output build/validate-vtime-esc5-root-handoff-current.json
python3 tools/validate_vtime_esc5_root_due_path.py \
  --rom build/interp-vtime-diagnostic.sfc \
  --fixtures build/gen-2429c-distinct-arm-fixtures-current-a976-v2 \
  --output build/validate-vtime-esc5-root-due-current.json
```

The first proves an exact parent flush, interpreted child entry, genuine stack
return, F3 continuation, and native-gate restore. The second synthetically
seeds one unit before a deadline and proves ordinal-one unwind to original PC
`$02429C`. Neither is fresh boot, hardware phase, gameplay, rate, or global
common-clock acceptance. The full local exact-MAME differential remains the
separate `tools/validate_2429c_native.py --entry-native` gate.

To reduce only the root's already-observed original-MAME branch paths, run:

```sh
python3 tools/validate_mame_2429c_branch_timing.py \
  --output build/validate-mame-2429c-branch-timing-current.json
python3 tools/test_mame_2429c_native_child_timing.py
python3 tools/validate_mame_2429c_native_child_timing.py \
  --output build/validate-mame-2429c-native-child-timing-current.json
```

Its report retains unobserved `$02429C` dynamic PCs as a coverage gap; do not
use a green subset result to admit the root or its children to VTIME. The
native-child companion likewise retains every unobserved child dynamic PC and
does not validate the native fusion or handoff policy.

The retained wide-movie negative-coverage guard is:

```sh
python3 tools/test_mame_2429c_wide_coverage.py
```

It verifies that the 141-entry original-MAME window still has the same missing
root/child arms. It is not a replacement for targeted distinct-arm MAME
fixtures or a three-way SNES timing comparison.

The current active-ROM checkpoint-local MAME/native route result is guarded by
`python3 tools/test_validate_2429c_current_evidence.py`. It must remain scoped
to its IRQ-masked, no-deadline handler fixture and never substitute for the
fresh Stage-3 IRQ-order gate.

The controlled distinct-arm fixtures are deterministic pre-execution inputs:
each is an explicit small work-RAM mutation set derived from the retained
organic tick-14,741 entry. They are the reproducible pre-failure source for
the `$02429C` native semantic tests, rather than a claim that a newly saved
Nexen `.mss` is transparent. In particular, the experimental `--prestate-dir`
save/reload runs perturb this direct-injection harness; their snapshots are
for forensic inspection only and must not be used as comparison evidence.
Use a clean replay from the documented fixture files for the actual oracle
gate.

The terminal-byte-CCR candidate is guarded by:

```sh
python3 tools/test_build_2429c_tstb_ccr_candidate.py
python3 tools/test_2429c_tstb_ccr_regression.py
```

The first guard builds only from hash-pinned predecessor `5c7e…` and rejects
any drift outside the two branch sites and their tail island. The second pins
the `$02429C`/`$0259CA` `TST.B` publication tails, packed bytes, the
`$0259FC → $99:97FD` private return mapping, isolated `a976…` exact 9/9,
fresh 10,000-tick campaign, and fresh one-credit HUD/art result. It is a
semantic and bounded campaign regression—not a Stage-3 timing, rate, boss,
or full-playthrough gate. The separate dirty-source `b758…` image is rejected
and is retained only as source/packing provenance.

The active-ROM Stage-3 failure and local cadence evidence are guarded by:

```sh
python3 tools/test_stage3_irq_order_current_a976_evidence.py
```

It requires the exact MAME/native-off/native-on task-frame gate to remain
explicitly red at tick 14,746 and the current checkpoint-local native-on and
all-native-off cycle counts to remain over budget. It also pins the fresh
campaign endpoint screenshot whose intact city artwork excludes the reported
large vertical blue bar on this organic path. It guards a known blocker and a
Nexen visual baseline, not a fix, fresh-ROM FPS measurement, MAME-pixel match,
or full-playthrough result.

The active ordinary-enemy, boss, and organic crate campaign evidence is
guarded by:

```sh
python3 tools/test_gameplay_current_a976_evidence.py
```

It pins the active image hash, the Nexen and legacy-Mesen fresh one-credit HUD
gates, ordinary-enemy 4/4 damage matrix, boss 118/118 health/hit sequences,
same-hash fresh-checkpoint lineage, carried versus
Button-1-thrown crate health transitions, and the Up+Right carried-flight
contact result. The underlying crate validators compare every retained logical
entry's M68K registers, CCR/X, stack/return state, work RAM, collision records,
enemy health, task state, gate state, and SNES IRQ cadence across native-off
and native-on against original MAME. It is bounded organic checkpoint evidence
rather than a fresh full-playthrough, MAME physical-IRQ cadence, or FPS gate.

Before using `tools/validate_2429c_native.py` for any new three-way fixture,
run `python3 tools/test_validate_2429c_mame_oracle.py`. The tool now refuses
the mutable `/snap/bin/mame` launcher and requires the project-pinned MAME
0.287 identity (including its recovered library environment). Do not relabel a
0.289 run as an arcade oracle.

The generic native-parent/interpreter-child ownership helper retains an
assembled diagnostic guard:

```sh
python3 tools/test_vtime_native_handoff.py
python3 tools/validate_vtime_native_handoff.py \
  --rom build/interp-vtime-native-handoff-diagnostic-v1.sfc \
  --output build/validate-vtime-native-handoff-runtime-current
python3 tools/test_validate_vtime_native_handoff_runtime.py
```

It verifies only the generic `$F2:FE40` helper's owner selection, failure
policy, long BW-RAM stores, and synthetic direct sequence. The `$02429C`
diagnostic now uses its own exact F3 flush/return path; this generic guard does
not substitute for the two root-specific runtime checks above.

The companion helper-bearing interpreter-only image has a deliberately
expected-red fresh controller guard:

```sh
python3 tools/test_vtime_interpreter_only_native_handoff_prompt.py
```

It pins the retained `598f0acc…` diagnostic report's zero-credit/failed-pixel
result after one real Select edge. It is neither a production-ROM HUD result
nor a MAME-comparable gameplay, timing, or Stage-3 test.

Before extending any VTIME seam, inventory the direct legacy countdown writers:

```sh
python3 tools/audit_vtime_legacy_ac_writers.py \
  --output build/audit-vtime-legacy-ac-writers-current.json
python3 tools/test_vtime_legacy_ac_writers.py
```

The expected current result is a blocked promotion, not a green implementation:
the audit must still expose every unmigrated `$AC` writer rather than letting a
partial native or scheduler conversion masquerade as a common clock.

Run the companion boundary audit before treating any VTIME ledger extension as
clock coverage:

```sh
python3 tools/audit_vtime_accelerated_boundaries.py \
  --expected-rom-sha256 5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9 \
  --output build/audit-vtime-accelerated-boundaries-current.json
python3 tools/test_vtime_accelerated_boundaries.py
```

It combines the authenticated one-update Stage-3 entry trace with the declared
bootstrap loop, scheduler, idle-pacing, renderer, and native/HLE boundaries.
The expected current result is again a promotion block: selected `$025110`,
`$02429C`, and player ledgers do not close the other 12 boundaries, and
bootstrap loops absent from the Stage-3 trace must remain in the migration
plan.

Before changing the `$025110` virtual-cycle table, regenerate and inspect its
charge map and its exact-MAME deferred-charge rule:

```sh
python3 tools/audit_native_charge_blocks.py \
  --output build/audit-native-charge-blocks-current.json
python3 tools/gen_vtime_esc3_charge_table.py \
  --manifest build/gen-vtime-esc3-charge-table-current.json
python3 tools/validate_mame_25110_charge_blocks.py \
  --output build/validation-mame-25110-charge-blocks-current.json
python3 tools/validate_mame_25110_deferred_charge.py \
  --audit build/audit-native-charge-blocks-25110-current.json \
  --table-manifest build/gen-vtime-esc3-charge-table-current.json \
  --output build/validation-mame-25110-deferred-charge-current.json
```

The audit must retain 226 assembled/source charge sites and 545 decoded
instructions. The generator must reject a non-terminal or unsupported dynamic
instruction. The MAME deferred-charge reducer must preserve the observed
variable Stage-3 costs (including `$02582A` 22/24 and `$0259B0` 26/30) and
predict each retained complete block from its post-state; neither result is a
hardware-phase or full-program acceptance gate.

Exercise the two VTIME-native wiring regressions only on a copied diagnostic
ROM. Both use retained pre-failure states and make no fresh-playthrough claim:

```sh
python3 tools/validate_vtime_25110_due_path.py \
  --rom build/interp-vtime-diagnostic.sfc \
  --prestate build/validate-25110-vtime-native-ledger-exact-v2-artifacts/states/native-on/fresh-retained-third-25110-entry-stable.mss \
  --output build/validate-vtime-25110-due-path-current

SUPERMN_VALIDATE_PACED=1 python3 tools/validate_25110_native.py \
  --rom build/interp-vtime-diagnostic.sfc \
  --fixture-dir build/validate-25110-current-fresh-boundary-10153-v3-fixtures \
  --cases 1 --retain-prestates --vtime-active \
  --output build/validate-25110-vtime-native-ledger-exact-current.json
```

The first test is synthetic one-unit-before-deadline wiring only. The second
seeds a no-deadline clock and compares MAME/native-off/native-on local state;
it does not establish the real IRQ phase or Stage 3 rate.

The bank-$9F player-ledger extension has separate diagnostic-only coverage.
Use the retained `68c9…` image rather than `build/interp.sfc`, which is the
ordinary `5c7e…` production artifact:

```sh
python3 tools/validate_vtime_esc9_due_path.py \
  --rom build/interp-vtime-current-5c7e-esc9-ledger-v2.sfc \
  --output build/validate-vtime-esc9-ledger-due-current
python3 tools/validate_vtime_esc9_finish_gateway.py \
  --rom build/interp-vtime-current-5c7e-esc9-ledger-v2.sfc \
  --output build/validate-vtime-esc9-finish-gateway-current
```

The first stops at the real `$0126EA` BSR into `$013282` and forces the first
player block across a deadline. The second directly enters the pack-injected
OJMP gateway and forces a pending block across the shared finish path. Both
retain pre-failure states and prove only their named diagnostic wiring. They do
not establish an organic handoff route, common native/HLE timing, three-way
MAME equivalence, a Stage-3 rate, fresh gameplay, or production acceptance.

## Human playtest

Use the exact ROM hash and route in [CONTROLS.md](CONTROLS.md). Human findings are
project evidence even before automation reproduces them. Record bounded positive
observations as bounded observations; do not promote them to complete-stage,
crash-free, playable, or shippable claims.

The current fresh-boot results and retained pre-failure state are summarized in
[GAMEPLAY_CAMPAIGN_20260801.md](GAMEPLAY_CAMPAIGN_20260801.md).
