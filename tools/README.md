# Tools index (reuse guide)

What each tool does and how reusable it is for the **next** game. See
[the reusable toolchain overview](../docs/toolchain/README.md) for the end-to-end
workflow. Legend:
**[G]** game-agnostic · **[P]** parameterized (env/args) · **[S]** Superman-specific
(swap addresses/input-field names to reuse).

## Private-input preparation

- **`prepare_roms.py`** [S/P] — the supported user entry point for a legally obtained
  MAME `superman` World set supplied as a ZIP or directory. It authenticates all 12
  ROMs by filename/size/SHA-1/SHA-256, rejects clones and ambiguity, reproduces the
  68K image, MAME-layout graphics image, organic C-Chip response, and 12 ADPCM-A drum
  WAVs, then verifies every output by pinned size/SHA-256 before atomic writes.
  Supports `--dry-run`, `--validate-only`, `--output-root`, and `--mame`. See
  [private ROM inputs](../docs/current/ROM_INPUTS.md); exact FM authoring WAV
  regeneration remains outside this ROM-only path.

## Tracing & coverage (gate G1)
- **`mame-trace/trace68k.lua`** [G] — headless 68K PC+disasm trace
  (`-debug -debugger none`). env `T68K_OUT/START/FRAMES`.
- **`mame-trace/trace68k_scenario.lua`** [P/S] — drive game states (attract,
  combat, pause, death, highscore) + trace a window. Uses MAME-standard input
  field names (`Coin 1`, `1 Player Start`, `P1 …`) → mostly portable; timings are
  Superman-tuned. env `SCENARIO/T68K_START/T68K_END`.
- **`mame-trace/pb_trace_multi.lua`** [G/P] — trace N evenly-spread windows across
  one `.inp` playback. env `PB_PREFIX/TOTAL/NWIN/WINLEN`.
- **`mame-trace/record_play.sh`** [G] — record YOUR playthrough (GUI MAME, same
  version you trace with) → `inp/<name>.inp`.
- **`mame-trace/playback_trace.sh`** [G] — play back an `.inp` + trace. env
  `INP/T68K_START/T68K_END`. NOTE: `-playback` path is relative to `-input_directory`.
- **`build_cdl.py`** [G/P] — traces → CDL: confirmed code + lengths + resolved
  jump-table targets. `CDL_ROM=<rom>` (default Superman). The G1 workhorse.
- **`analyze_trace68k.py`** [S] — coverage, caller→callee call graph, pure-leaf
  finder, indirect-jump sites. Constants (`IRQ_VECTORS`, work-RAM range) are
  Superman; swap for another game.
- **`measure_coverage.py`** [P] — reliable code vs data byte coverage of a Peony
  `.pasm` (real instrs vs `.db`/`dc.w`/`???`). 512KB ROM size hardcoded near top.

## Transpiler & bulk transpilation (the hot side)
- **`transpile.py`** [G core / S address-maps] — automated 68K→65816 transpiler.
  `transpile.py <hexaddr>` emits a native escape (`entry_<addr>`) operating on the
  interp's DP reg file; `--video` routes non-frame stores to the `$41` shadow;
  `--bank1`/`--bank2` target the SA-1 escape banks ($92/$94). The codegen rules
  (EA matrix, D1 signed-branch lowering, call-bridge sentinel) are game-agnostic;
  the reg-file/work-RAM/shadow addresses are the Superman SA-1 map. **Three entry
  conventions** (see `aot-dispatch-table` memory): default = jsr-hook (re-simulate
  the skipped return-push); `--coroutine` = no push, decode ends at the yield bra;
  `--table` = no push, faithful link/unlk/rts, for AOT/xlat dispatch where the real
  return is already on the stack at a materialized boundary. Decode bytes come from
  `data/superman_m68k.bin` so a first build no longer requires an older
  `build/interp.sfc`; a matching packed-ROM fallback and `SUPERMN_TRANSPILE_ROM`
  override remain available.
- **`stream_profile.py`** [P/S] — in-game hot-function profile from the interp's
  per-frame PC stream (MAME can't reach gameplay under `-debug`). Injects a gameplay
  tick, enables PC streaming (`$0718=0`), histograms by 64-byte function-region. The
  source of the ranked hot set to transpile next.
- **Lockstep escape validation** (fresh-adjacent-tick — NOT sparse capture):
  `record_playthrough.sh` (record a matched-config MAME playthrough) →
  `extract_flytick.py`/`extract_flyseq.py` (capture adjacent game-tick A/B states) →
  `flyval.py` / `val_*` (inject tick A, run hook-ON native vs OFF interpreted, require
  the live state to match tick B / each other). KEY: classify diffs vs `a7` (bridge
  sentinels below SP are dead, not bugs); diff the `$41` shadow for `--video` escapes.
  `$SUPERMN_SCRATCH` parameterizes the data dir.
- **Fetch-chokepoint + self-differential (2026-07-01)** — for rts/branch-reached escapes the
  chokepoint dispatches (e.g. ce4). `lockstep_choke.py` (`CHOKE=0/1` toggles the `$073A` chokepoint
  gate on the GREEN ESC=0 baseline; reports SA-1 cycles + interp instr + wramB diff) and
  `multitick_choke.py` (`NTICKS` N-tick run, dumps 64KB work RAM). The CLEAN gate is the
  **self-differential**: `CHOKE=0` dump vs `CHOKE=1` dump (MAME residuals cancel → isolates
  native-vs-interp for the escaped fn); 0 bytes (excl the `$40:7FE0` diag counter) = bit-exact.
  Root-cause helpers: `reg_probe.py` (dump the 68K register file + CCR flags at a trapped PC —
  found the ce4 exit-CCR bug), `find_writer.py` (write-hook: who writes an address this tick).

## AOT dispatch table (the pivot — unify escape dispatch)
The strategic shift from per-target dispatch hooks (one hardcoded cmp-chain per
escape: `ojmp_hook`/`ojmp_disp`, `ors_pre`, `ors_rte`/`cors_disp`, `jsrabs_hook2`,
`bsr_hookpush`) to ONE global 68K-PC→native table that all control flow consults.
See the [transpiler workflow](../docs/toolchain/TRANSPILER_WORKFLOW.md) and the
[historical planning handoff](../docs/history/campaigns/MAIN_PLANNING_HANDOFF.md) for
the design and later corrections.
- **`gen_xlat_table.py`** [G core / S addresses] — builds the table offline from the
  escape banks' `.sym` (entry_X native addrs) + the `transpiled from $XXXXXX`
  comments (68K PCs). Emits `src/xlat_table.bin`, a 2-level page table
  (`page[PC>>8]` → 256-entry sub-table of 3-byte native addrs; 0 = miss) placed by
  `build_interp_rom.py` at SA-1 **$96:8000**. `ALLOWED_PCS` = the validated set;
  `JMP_STATE_PCS` (no-push handlers) is GREEN, `TABLE_PCS` (`--table` called fns) is
  the in-progress class. Runtime mechanism: `xlat_dispatch` at escbank2 **$94:F900**
  (push+RTL dispatch — `jml [abs]` is Poppy-mis-sized); `ojmp_hook` and `op_rts_norm`
  both route through it (gate-check → jml $94F900 → native on hit, else jmp inext).
  **(corrected 2026-06-30: the rts-class table dispatch FIRES 0× in gameplay. `op_rts_norm`'s
  table route is real, but the hot rts-reached PCs ($CE4/$13BE) are entered via the scheduler's
  rte→rts chain that BYPASSES `op_rts_norm`, so `TABLE_PCS`/`ce4t` never dispatch — `ce4t` is
  dead weight in the table. The earlier "ce4t fires 63451×" was a corrupted $07xx in-memory-
  counter artifact; NEVER trust $07xx counters — measure with SA-1 exec-hooks. The families that
  DO fire: jah2 (jsr/bsr/jsr(An)), jmp-state (jmp(a0)→table), coroutine (rte-resume→table). See
  MAIN_PLANNING_HANDOFF.md.)**
- **`val_frame_diff.py`** [S] — the gate: capture at the $0708 IRQ jsr site, run one
  full per-frame tick escapes-ON vs OFF, diff work RAM ($40) + video shadow ($41),
  a7-aware. GREEN ⇒ the table-dispatched escapes are bit-exact vs interpretation.
- **AOT diagnostics** (built for the $0CE4 state-divergence; reusable):
  *dual-CPU `get_cpu_state('Snes'|'Sa1')` sampling* when a frame fails to trap
  (found the interp/escapes run on the SA-1; a hang at `$00:D15A=ispin` = idle, not a
  crash); *function-boundary differentials* (`/tmp/fnbound_ce4*.py` family) that trap
  $0CE4 entry, save state, and run interpret-vs-dispatch to a trap point + diff $40.
  KEY: the xlat table ROM ($96:8000) is **debugger-writable**, so you can toggle ONE
  escape's table entry at runtime (zero=interpret / restore=dispatch) while keeping
  all other escapes on — the only way to diff escape-on-only reaches.

## Differential transpiler harness (gate G2, historical spike)
- **`spike_harness.py` / `spike24d98_harness.py`** [S] — build WRAM input blobs +
  expected outputs from MAME goldens, and `check` Mesen output. Pattern is
  reusable; the field layouts are per-function.
- **`mame-trace/capture_412_tap.lua` / `capture_24d98_inject.lua`** [S] — golden
  capture via read-substitution / write-capture taps. Superseded for simple cases
  by the `mame` MCP `capture_leaf_io` tool [G].
- **`mame-trace/save_state.lua` / `trace_from_state.lua`** [G] — save-state seeding
  (save works; load+trace-in-one-debug-session has a notifier glitch — prefer
  `.inp` playback for deep states).

## Graphics

See [graphics conversion](../docs/toolchain/GRAPHICS_CONVERSION.md) and the
[palette evidence](../docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md).
- **`render_full_frame.py`, `render_arcade_sprites.py`, `build_snes_full_scene.py`,
  `build_snes_sprite_scene.py`** [S] — arcade decode + SNES reproduction +
  MAME diff. X1-001-specific; the decode/diff *approach* is general.
- **`optimize_palettes.py`** — SUPERSEDED for sprites (per-bank dynamic model).
- **`test_bg_blank_slot_invariant.py`** [S] — source/packed-ROM guard for the
  reserved blank physical BG slot zero, one-based prepared cache records, and
  the single direct staging-to-PPU map authority.
- **`capture_snes_input_framebuffers.py` / `capture_snes_direct_framebuffers.py`**
  [S] — checkpoint captures under real controller input. Movie replay in the
  first verifies each retained framebuffer is the next actual video frame and
  supports periodic states plus explicit cross-ROM video/cache migrations.
  Legacy Mesen's direct-controller request can advance zero, one, or two actual
  video frames, so the second is sampling-only and records each observed delta;
  it must never claim consecutive coverage. Its coherent-idle stop retains two
  additional samples by default so screenshot latency cannot expose the pre-DMA
  image. Both record interventions and are diagnostic acquisition, never
  gameplay acceptance.
- **`drain_mesen211_renderer.py` / `inspect_mesen211_bg_state.py`** [S] — focused
  legacy-Mesen checkpoint tools. The drain parks the paused SA-1 at its exact PC
  while the 5A22 empties renderer queues; the inspector then checks the selected
  dynamic column layout, final tile targets, reverse owners, intentional X1
  overlaps, stale targets, palette mapping, and native graphics bytes without
  advancing the state. Neither is fresh-boot or exact-MAME evidence.
- **`extract_x1_shadow_from_state.py`** [S] — read-only extraction of a paused
  checkpoint's logical X1 palette/Y/control/code planes for the established
  software renderer. It also records canonical raw BG planes and their exact
  byte comparison against live X1. Its output is a diagnostic reference, not an
  exact MAME frame.
- **`prove_prepared_bg_cache_reconstruction.py`** [S] — intervened causal test
  for a retained primary `$FFFE` queue entry. It inverts the exact prepared
  map/code-list/palette-map representation, requires the result to match paused
  live X1 code/color planes, writes only canonical raw caches `$2000/$2400`, and
  continues the same ROM with periodic screenshots. Its WRAM writes are always
  recorded; it can never issue organic or gameplay acceptance.
- **`validate_fresh_poststart_framebuffers.py`** [S] — records and replays a
  `StartWithoutSaveData` movie with organic coin and Start input. It retains
  fresh loading, actual title/credit milestones, every actual post-Start video frame,
  periodic states and BG graphics checks, and a mandatory-review contact sheet.
  Blank/repeated playfields, persistent vertical black bands, hidden BG1,
  absent BG ownership, partial tile DMA,
  nonconsecutive frames, and interpreter halts are machine-red after the default
  100-frame organic Stage-1 fade grace. A clear result
  remains acceptance-unknown until the contact sheet is manually inspected and
  the separate exact-MAME pixel/temporal gates pass.
- **`reanalyze_fresh_poststart_framebuffers.py`** [S] — re-verifies the ROM,
  movie, contact sheet, every retained PNG hash, and every recomputed framebuffer
  metric before reapplying the visual gate with a new grace threshold. It performs
  no emulator replay or runtime writes and cannot issue gameplay acceptance.
- **`analyze_snes_framebuffer_flashes.py`** [S] — repeated-tile/flash heuristic
  over a consecutive capture. `--skip-frames` is allowed only for a disclosed
  acquisition artifact such as a serialized pre-vblank image; a clear result is
  still acceptance-unknown without aligned MAME and temporal gates.
- **`validate_scroll_temporal_continuity.py`** [S] — offline horizontal-camera
  cadence gate for a consecutive Mesen capture. It authenticates every PNG,
  compares the renderer's unwrapped published source phase (with historical raw
  X1 fallback) with every intervening 60 Hz BG1HOFS change,
  rejects holds, reversals, oversized/accumulated motion, and residual background
  mismatch, and explicitly accounts for same-frame physical-map coordinate
  rebases. Current-schema captures also reconstruct every eligible absolute map
  basis as `slot4*32 + paired_phase - paired_raw_column4`; any cumulative/modal
  drift is red even if adjacent motion looks smooth. It is focused stutter evidence, not aligned-MAME, fresh-boot,
  gameplay, or performance acceptance.

## Recovery profiling and architecture labs

- **`recovery_baseline.py`** [S] — production `TESTFLAG=0` cold boot, exact accelerator-arm
  observation, real virtual-mailbox coin/start inputs, counter-vs-hook validation, and honest
  separation of SNES video frames, Superman ticks, SA-1 cycles, and host throughput.
- **`mesen211_mcp_controller.sh`** [S] — exact legacy-Mesen compatibility launcher. It runs
  `/home/chad/Mesen2/bin/linux-x64/Release/Mesen` with a port-0 `SnesController` override and
  `--doNotSaveSettings`, preventing inherited controller configuration from invalidating real-input
  tests.
- **`capture_mesen211_transitions.py`** [S] — fresh-power-on or named-state Mesen 2.1.1 frame
  capture for title/transition compatibility. It records exact ROM/emulator/controller provenance,
  screenshots, checkpoints, PPU Mode/brightness/forced-blank/layer state, the boot-activity byte,
  BG1 H/V offsets, accepted/latest/raw/live X1-001 scroll state, integrated
  presented HOFS, displayed/pending map origin and full column maps, map-commit
  markers, DMA0 descriptor,
  halt/tick/render state, and a JSON manifest. For an
  explicitly checkpointed cross-version renderer lab, `--refresh-video-mirror` replaces and
  verifies saved `$7F:8000-$AFFF` from the selected ROM and records that intervention in
  provenance; it requires `--state`. The default fresh-power path performs no memory write. This
  is visual compatibility evidence, never gameplay stability or FPS evidence.
- **`gen_boot_screen.py`** [S] — deterministic 32 KiB Mode 7 SA-1 boot-screen generator. It embeds
  a compact indexed derivative of the supplied SA-1 logo, static status text, one palette-pulsed
  8x8 activity diamond, and 64 strictly increasing identity matrices for a one-shot
  huge-to-fitted zoom. A=D `$0020`→`$00C0` and B=C=0, so there is no rotation or shear; NMI latches
  the fitted state and never restarts the zoom. `build_interp_rom.py` regenerates and
  hash/layout/matrix-checks the asset before packing it at file `$300000-$307FFF`; no arcade
  graphics are used.
- **`validate_bg_reconcile_helpers.py`** [S] — byte-oracle for the native background-list promote
  and revert helpers. It covers empty, compact, and full paths and specifically guards the
  zero-length flag-ordering bug that crossed BW-RAM mirrors at the first breakable wall.
- **`trace_wall_context.py`** [S] — Mesen 2.1.1 real-controller first-wall replay with scheduler-
  context write hooks. It records the renderer manifest, every initialized task stack/floor, and
  suspicious saved-SP high-byte writes, plus player X/Y/action/input and presented BG1 H/V at
  every phase boundary. It writes no runtime memory by default. The explicit
  `--refresh-video-mirror` checkpoint lab verifies and installs the selected ROM's
  `$7F:8000-$AFFF` renderer code, while `--migrate-map-basis` derives the current absolute basis from the accepted
  source-column-4 slot, its paired raw X, and the unwrapped phase; it records the old/new paired
  phase and displayed-basis bytes. Initial/final 64 KiB game-work snapshots make
  purported same-tick oracle identity auditable. Any such run is cross-ROM diagnostic evidence
  only, never fresh-current acceptance or a stage soak.
- **`trace_fresh_bg_tile_dma_deadline.py`** [S] — fresh-movie native-record verifier and passive
  two-frame DMA path trace. It can check one physical owner/VRAM record at an exact movie frame,
  or retain owner publication, helper/direct/publish, `MDMAEN`, pending flag, `HVBJOY`, and
  `OPVCT` events around a selected boundary. It diagnosed the VBlank-high/`OPVCT=$0000` line-0
  race without storing a full playback transcript. It performs no runtime memory writes and is
  focused diagnostic evidence, not framebuffer or playthrough acceptance.
- **`trace_snes_bg_dma_input.py`** [S] — checkpointed lossless framebuffer and renderer-DMA
  trace. In addition to BG upload/chunk hooks, it records the NMI presentation arbiter,
  BG cursor step, OBJ publisher/base DMA, the 16-bit frame request/ACK pair, and writes to
  OAM due/valid/once-per-NMI state. This is the focused regression harness for presentation
  deadlocks such as an ACK of `$0100` being misread as zero in 8-bit mode; it remains
  checkpoint diagnostic evidence rather than fresh-power acceptance.
- **`trace_playtest_actions.py`** [S] — exact-Mesen real-controller action-schedule diagnostic for
  crate/attack/encounter reproduction. It records player animation/action state, tick/render/halt,
  stack floors, BG1 H/V plus packed/X1-001 scroll state, screenshots, and checkpoints.
  `--refresh-video-mirror` explicitly injects the selected ROM's `$7F:8000-$AFFF` renderer mirror
  after a compatible older checkpoint is loaded and records that intervention; such a result is
  focused cross-version evidence, never organic cold-boot or FPS evidence.
- **`validate_vertical_scroll_bridge.py`** [S] — isolated Nexen real-65816/PPU lab for the shipped
  vertical-scroll capture and apply helpers. It covers Stage 1 wrap-to-zero, general motion,
  byte wrap, MAME-derived Stage 2 per-column patterns, sparse-to-full map seeding,
  isolated-gap and paired absolute map changes, raw-phase unwrapping, actual BG1 H/V
  register publication, and the exact-title zero guard. Its scroll shadow is synthetic; it is not gameplay, cold boot,
  stability, or performance evidence.
- **`validate_obj_cache_vram.py`** [S] — paused-checkpoint oracle for every persistent OBJ-cache
  hash claim. It reconstructs each physical 16x16 slot from PPU VRAM, compares it with the exact
  preconverted ROM record, and conditionally checks manifest-to-OAM tile alignment. It diagnoses
  cache content; it does not prove display-generation lifetime by itself.
- **`validate_fast_obj_renderer.py`** [S] — reference-vs-fast renderer differential. Its
  forced-full-cache mode also stops immediately after displayed-OAM slot protection and proves
  that every displayed physical slot is marked and absent from both the rebuilt free stack and
  upload queue.
- **`validate_paced_obj_sources.py`** [S] — samples the production `$0818` handoff and independently
  rebuilds the OBJ visibility predicate. `--packed-obj-manifest --manifest-only` validates the
  current bit-15-tagged six-byte Y/code/X records, bounded length, bytes, and source order while
  reporting—but not gating on—unrelated raw-plane handoff transients.
- **`validate_mesen211_playtest.py`** [S] — replays the reported real-controller sequence in exact
  Mesen 2.1.1: coin, Start, Clark/round transition, grounded B charge/release, tick/native hooks,
  screenshots/states, and digital-audio capture/silence analysis. It intentionally labels its
  result checkpointed compatibility evidence; musical fidelity still requires listening against
  the arcade reference.
- **`validate_charged_shot.py`** [S] — checkpointed real-controller B hold/release regression.
  It records the `$D3B0` charged-shot native entry and relocated continuation, game-tick/render
  progress, projectile state, production gates, task-stack floors, screenshots, and a first-stall
  state/CPU trace. This is charged-shot liveness evidence, never cold-boot or FPS evidence.
- **`soak_gameplay_ordering.py`** [S] — checkpointed real-input scheduler/renderer ordering soak.
  It checks tick-hook/counter agreement, request/ACK/true-render conservation, queue-overflow
  deltas, gates, supervisor mirror, sound/input state, and task-stack floors. `--dma-trace` adds
  execution hooks for the published/direct DMA branches so cache-burst losses can be attributed.
  Any checkpoint mirror refresh is recorded as an intervention; the result is not cold-boot/FPS
  evidence.
- **`profile_continuous.py`** [P/S] — simultaneous, non-pausing phase hooks using the R5 Nexen
  `cycleCount` notification stamp. Profiles clamp -> virtual IRQ -> `$3A92` -> next clamp without
  the stop-at-each-hook distortion that invalidated older phase accounting. It rejects cross-loads
  that do not preserve the production gate block; `--drive-gameplay` reaches and settles gameplay
  through the documented mailbox before installing hooks.
- **`profile_tick_ring.py`** [S] — checkpoint-only whole-tick attribution from the diagnostic
  per-fetch PC ring. It fails loud on the normal production ROM; first build with
  `PC_RING=1 bash tools/build_interp.sh`, and restore the normal build afterward. Ring-instrumented
  cycle totals are diagnostic overhead measurements, never production performance evidence.
- **`build_idle_vsync_lab.py`** [S] — builds a marked, isolated `$0818` pacing experiment without
  touching canonical assembly, objects, or ROM. `--nmi-wake` uses a WRAM-resident 5A22 NMI to wake
  a masked SA-1 `WAI` only after active coroutine work reaches the main idle context.
- **`soak_idle_vsync_lab.py`** [S] — no-hook long soak for the marked poll/NMI labs. Drives the normal
  coin/start mailbox, checks all production gates/ring/halt/progress, and compares each initialized
  task's saved SP against the actual 68K ROM floor table at `$0882`. The default target passes the
  historical `$9F05`/`$A005` coroutine-corruption window.

The results and negative iterations are in
[R5 scheduler experiments](../docs/history/performance/R5_SCHEDULER_EXPERIMENTS.md).
These lab tools are evidence harnesses, not a production build path.

## MCP servers (the two oracles — the most reusable thing here)
- **`mame`** (`/home/chad/mame-mcp`): **25 tools** in two families — *stateless* one-shot
  (`ping`/`config_check`/`audit_romset`/`get_ioports`/`trace_memory_access`/`capture_leaf_io`/
  `run_lua_script`/`run_lua_inline`/`trace_cchip_superman`) and a *live persistent session*
  (`mame_launch` then `mame_read/write_memory`, `mame_run_frames`, `mame_get/set_reg`,
  `mame_save/load_state`, `mame_send_input`, `mame_capture_game_tick`, `mame_drive_to_gameplay`,
  `mame_exec_lua_live`, …). Full table in `mame-mcp/README.md`. Point `MAME_SYSTEM`/`MAME_ROMPATH`
  at any game.
- **`nexen-inproc`**: SNES PPU/CPU + SA-1 oracle through `nexen_mcp_bridge.py` —
  `read/write_memory`, `run_frames`, hooks, CPU state/cycle count, screenshots, etc. The active
  recovery binary lives on the healthy volume; see
  [building](../docs/current/BUILDING.md) rather than assuming the old
  `/home/chad/Nexen` checkout is usable.

## Notes
- **Debugging the interpreter, Poppy, and harness traps: see
  [the gotchas reference](../docs/toolchain/DEBUGGING.md).**
  (diagnostic-build flight recorder, PC-freeze, `$07xx`-counter rule, `.org` overlap guards,
  MAME/Mesen gotchas).
- 68K is big-endian: read words (`read_u16`), not byte lanes.
- MAME 0.287 Lua: keep taps/notifier subscriptions in GLOBALS (else GC'd);
  `register_frame_done` not `add_machine_frame_notifier`; `-debug -debugger none`
  for headless tracing; PC reads back +2 (prefetch); breakpoints halt frames.
- Peony disassembler is single-threaded and very slow to write large output.
