# Tools index (reuse guide)

What each tool does and how reusable it is for the **next** game. See
`../METHODOLOGY.md` for the end-to-end recipe. Legend:
**[G]** game-agnostic · **[P]** parameterized (env/args) · **[S]** Superman-specific
(swap addresses/input-field names to reuse).

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
  return is already on the stack at a materialized boundary.
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
See `STATUS.md` (June 29) + the `aot-dispatch-table` memory for the full design.
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

## Graphics (validated, see PALETTE_VERDICT.md)
- **`render_full_frame.py`, `render_arcade_sprites.py`, `build_snes_full_scene.py`,
  `build_snes_sprite_scene.py`** [S] — arcade decode + SNES reproduction +
  MAME diff. X1-001-specific; the decode/diff *approach* is general.
- **`optimize_palettes.py`** — SUPERSEDED for sprites (per-bank dynamic model).

## MCP servers (the two oracles — the most reusable thing here)
- **`mame`** (`/home/chad/mame-mcp`): **25 tools** in two families — *stateless* one-shot
  (`ping`/`config_check`/`audit_romset`/`get_ioports`/`trace_memory_access`/`capture_leaf_io`/
  `run_lua_script`/`run_lua_inline`/`trace_cchip_superman`) and a *live persistent session*
  (`mame_launch` then `mame_read/write_memory`, `mame_run_frames`, `mame_get/set_reg`,
  `mame_save/load_state`, `mame_send_input`, `mame_capture_game_tick`, `mame_drive_to_gameplay`,
  `mame_exec_lua_live`, …). Full table in `mame-mcp/README.md`. Point `MAME_SYSTEM`/`MAME_ROMPATH`
  at any game.
- **`mesen`**: real SNES PPU/CPU — `read/write_memory`, `run_frames`,
  `reset_emulator`, screenshots, etc.

## Notes
- **Debugging the interp / Poppy / harness traps: see `../docs/INTERP_DEBUG_AND_GOTCHAS.md`**
  (flight recorder, PC-freeze, `$07xx`-counter rule, `.org` overlap guards, MAME/Mesen gotchas).
- 68K is big-endian: read words (`read_u16`), not byte lanes.
- MAME 0.287 Lua: keep taps/notifier subscriptions in GLOBALS (else GC'd);
  `register_frame_done` not `add_machine_frame_notifier`; `-debug -debugger none`
  for headless tracing; PC reads back +2 (prefetch); breakpoints halt frames.
- Peony disassembler is single-threaded and very slow to write large output.
