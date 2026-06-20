# Superman (Taito X) → SNES/SA-1 — Project Status

Last updated: June 19, 2026. Single source of "where we're at." Per-area detail
lives in the linked docs.

## TL;DR
Discovery/validation phase is done and *grounded against ground truth* (MAME for
the arcade, real SNES PPU for the target). The graphics path is reproduced
end-to-end; the 68K→SA-1 transpiler is de-risked with a working differential
harness (gate G2 green); disassembly coverage (G1) has a reliable trace-driven
pipeline and a full beat-the-game playthrough trace. **The 68000 interpreter now
boots Superman all the way to its live per-frame game loop on real SNES hardware**
— past the cooperative scheduler, the C-Chip GWK routine download, and full init;
both scheduler tasks run (`tmask=$0003`, matches MAME), the per-frame frame counter
increments, and work RAM evolves every frame. The interpret-cold/transpile-hot
hybrid is fully de-risked on the "cold" side. **Video plumbing is now live**: the
interpreter mirrors every 68K video-bank write into SNES `$7E` shadow RAM and, once
per game-frame, renders to the real PPU — **palette → CGRAM is byte-exact (100%)** and
**arcade OBJ sprites + the BG1 playfield render on hardware** (tile decode validated
128/128 vs the Python oracle). The game is no longer blind. Remaining video polish:
OBJ tile dedup (currently 64-sprite cap, no dedup) and a proper LRU tile cache /
per-frame decode cap (BG has a direct-mapped 64-slot cache); pixel-diff vs MAME at a
real-gameplay frame is blocked by interpreter speed (it can't reach gameplay frame
~3000 cheaply). See `VIDEO_PLUMBING.md`. Not yet started: bulk transpilation, audio.

## Workstream status

| Area | State | Evidence / doc |
|---|---|---|
| **Graphics pipeline** | ✅ validated on real SNES PPU vs MAME | `PALETTE_VERDICT.md` |
| **Transpiler design (D1–D4)** | ✅ settled | `TRANSPILER_DESIGN.md` |
| **Transpiler spike (gate G2)** | ✅ GREEN — 2 functions differentially verified | `SPIKE_RESULT.md` |
| **68K interpreter** | ✅ **BOOTS TO LIVE GAME LOOP** on real SNES — past the cooperative scheduler, C-Chip GWK routine download, and init; both tasks run (`tmask=$0003`), per-frame counter increments, PC cycles 26+ game addresses/sec. Legal MC68000 ISA + the boot-exercised addressing modes added this session. Clears the **C-Chip boot handshake** (replay, not emulation). | `INTERPRETER_SPIKE.md`, `VIDEO_PLUMBING.md` |
| **Disassembly coverage (gate G1)** | ⬆ in progress — reliable pipeline + full playthrough | `COVERAGE_G1.md` |
| **Tooling (MAME/Mesen MCP, trace/CDL)** | ✅ built & validated | below |
| **C-Chip** | ✅ SOLVED — patch + input mailbox + **boot handshake replay**, still **no MCU emulation** | `CCHIP_BOOT_HANDSHAKE.md`, `CCHIP_FIRMWARE.md` |
| **Audio (YM2610→TAD)** | 🔬 analyzed; `vgm-to-tad-mml` skill exists | `CONVERTSOUND.md`, `SOUNDHARDWARE.md` |
| **Bulk game-logic port** | ⬜ not started (gated on G1) | `PORT_PLAN.md` |

## Graphics — done
Arcade palette decode (`xRGB555` big-endian) and the **two X1-001 draw paths**
(foreground→SNES OBJ, background playfield→SNES BG) are reproduced on a real SNES
PPU and match MAME pixel colors (47/47). Sprite palette is per-bank/dynamic, ≤7
banks/frame → 8 OBJ palettes suffice, no quantization. See `PALETTE_VERDICT.md`.

## Transpiler — design settled + spike green (G2)
- **Design (`TRANSPILER_DESIGN.md`)**: D1 carry/branch lowering (carry inverted on
  sub/compare; `tst;ble`→`beq/bmi`), D2 32-bit regs in direct page, D3 byte-swap
  endianness, D4 the corrected address map (`$B00000/$D00000/$E00000/$F00000` —
  the old docs had a digit-dropped version).
- **Spike (`SPIKE_RESULT.md`)**: two real 68K leaves hand-transpiled to 65816 and
  verified against MAME goldens on a real SNES — **$412** (Lehmer RNG: signed
  `muls`/`divs`/`swap`, 22/22) and **$24D98** (timer/clamp: signed `ble`, `btst`,
  loop, trap-path, 12/12). The differential harness (the safety net the risk doc
  demanded) works end-to-end.

## Disassembly coverage (G1) — reliable pipeline, climbing
The MAME execution trace *is* the CDL: confirmed code only, exact lengths from the
trace, and it resolves the indirect jumps (H6) that froze static disassembly.
Driven by scripted states + a faithful **full beat-the-game playthrough** (your
0.287 recording, 131k frames) + service menu:
- **10.2%** of the ROM is confirmed-executed code (15,148 instr) — zero false
  positives, up from a reliable 3.4% baseline.
- **779 indirect jump-table targets resolved** (was 0 — the H6 blocker).
- Peony recursive descent from these seeds → **35,047 blocks** (vs 483 baseline);
  measured byte-coverage on a prior smaller run was 43.6% code / 67.5% ROM
  classified. See `COVERAGE_G1.md`.

## Acceptance gates (from `RISK_TRANSPILER.md`)
- **G1 — coverage ≥85% code/data separated:** ⬆ in progress (reliable 10.2% floor;
  descent ~67.5% classified; needs full descent %, maybe more playthroughs).
- **G2 — differential harness green:** ✅ done (2 functions).
- **G3 — cycle budget <150k/frame:** ⬜ not started.
- **G4 — endianness manifest:** ⬜ not started (policy set in D3).

## Tooling built this phase
- **MAME MCP** (`/home/chad/mame-mcp`, server `mame`): added `capture_leaf_io`
  (golden-vector oracle) + `run_lua_inline`. See memory `mame-mcp`.
- **Mesen MCP** (`mesen`): real SNES PPU validation; ROM patched via `snesPrgRom`
  + `reset_emulator` (survives reset) for restart-free harness iteration.
- **Trace/coverage**: `tools/mame-trace/trace68k*.lua` (+ playback/scenario/service
  variants), `tools/build_cdl.py`, `tools/analyze_trace68k.py`,
  `tools/measure_coverage.py`, save-state (`save_state.lua`/`trace_from_state.lua`)
  and `.inp` playback (`playback_trace.sh`) infra.
- **Disassembler**: Peony (`/home/chad/peony`, build `Peony.Cli`, .NET 10) — note:
  single-threaded, very slow to write large disassemblies.

## Recommended next steps
The interpret-cold/transpile-hot **hybrid is fully de-risked on the cold side**
(the interpreter is now a complete, MAME-verified MC68000). The strategy: boot
and run on the interpreter, then transpile hot paths. Detailed plan in
**[ROADMAP.md](ROADMAP.md)**. In short:
1. **Video plumbing** (the boot + frame loop now run — see `VIDEO_PLUMBING.md`):
   route the 68K hardware-bank writes (sprites `$B00000`, tilemaps/regs
   `$300000/$400000/$600000`) — currently no-op'd — to the validated SNES PPU
   path, and wire real inputs into the C-Chip mailbox (`$900001/3/5`). This is
   I/O plumbing, not opcodes. Confirm a frame matches MAME.
2. **Profile, then transpile hot paths** to native 65816 (generalize the spike's
   hand-transpilation into a tool); expand G2 across the D1 branch matrix.
3. Finish G1 coverage + the G4 endianness manifest; convert audio (YM2610→TAD)
   in parallel.
