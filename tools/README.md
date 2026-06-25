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
  `--bank1` is dead multi-bank scaffolding (unused — bank-$00 gaps suffice). The
  codegen rules (EA matrix, D1 signed-branch lowering, call-bridge sentinel) are
  game-agnostic; the reg-file/work-RAM/shadow addresses are the Superman SA-1 map.
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
- **`mame`** (`/home/chad/mame-mcp`): `ping/config_check/get_ioports/trace_memory_access/
  run_lua_script/run_lua_inline/capture_leaf_io`. Point `MAME_SYSTEM`/`MAME_ROMPATH`
  at any game.
- **`mesen`**: real SNES PPU/CPU — `read/write_memory`, `run_frames`,
  `reset_emulator`, screenshots, etc.

## Notes
- 68K is big-endian: read words (`read_u16`), not byte lanes.
- MAME 0.287 Lua: keep taps/notifier subscriptions in GLOBALS (else GC'd);
  `register_frame_done` not `add_machine_frame_notifier`; `-debug -debugger none`
  for headless tracing; PC reads back +2 (prefetch); breakpoints halt frames.
- Peony disassembler is single-threaded and very slow to write large output.
