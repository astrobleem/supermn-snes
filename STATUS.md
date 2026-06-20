# Superman (Taito X) → SNES/SA-1 — Project Status

Last updated: June 20, 2026. Single source of "where we're at." Per-area detail
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
hybrid is fully de-risked on the "cold" side. **Video plumbing is complete**: the
interpreter mirrors every 68K video-bank write into SNES `$7E` shadow RAM and, once
per game-frame, renders to the real PPU — **palette→CGRAM byte-exact (100%)**, tile
decode **128/128** vs the Python oracle, and **OBJ sprites + the BG1 playfield render a
recognizable arcade frame** (injecting a captured MAME gameplay frame produces the
church/GAME-OVER scene with Superman, validated vs an independent Python renderer). All
four polish items are done: OBJ tile dedup (sprites share tiles, up to 128 OAM),
cross-frame BG tile cache (persistent hash + VRAM, skips re-decode), vblank-safe
forced-blank DMA, and the integration validation. The render subsystem was relocated to
ROM bank `$E9` (`src/video.pasm`) to free interp-bank space; `map_snes` (hot store
dispatch) stays in-bank, reached + 3 `jsl`/`jml` wrappers. See `VIDEO_PLUMBING.md`.
**Next: inputs** (wire SNES pad → C-Chip mailbox so the game responds) and **speed**
(profile + transpile hot paths — the interpreter runs ~18 interp-steps per real frame).
Not yet started: bulk transpilation, audio.

ROM layout (4 MB HiROM): interp `$C0:8000` · 68K image `$C1:0000`–`$C8` · arcade tiles
`gfx1` `$C9:0000`–`$E8` · video subsystem `$E9:8000` (file `$298000`).

## Workstream status

| Area | State | Evidence / doc |
|---|---|---|
| **Graphics pipeline** | ✅ validated on real SNES PPU vs MAME | `PALETTE_VERDICT.md` |
| **Transpiler design (D1–D4)** | ✅ settled | `TRANSPILER_DESIGN.md` |
| **Transpiler spike (gate G2)** | ✅ GREEN — 2 functions differentially verified | `SPIKE_RESULT.md` |
| **68K interpreter** | ✅ **BOOTS TO LIVE GAME LOOP** on real SNES — past the cooperative scheduler, C-Chip GWK routine download, and init; both tasks run (`tmask=$0003`), per-frame counter increments. Legal MC68000 ISA (optest 154/154). Clears the **C-Chip boot handshake** (replay, not emulation). | `INTERPRETER_SPIKE.md` |
| **Video plumbing** | ✅ **COMPLETE** — 68K video-bank writes → `$7E` shadow → real PPU each game-frame. Palette byte-exact, tile decode 128/128, OBJ+BG render the correct arcade frame; OBJ/BG tile dedup, cross-frame BG cache, vblank-safe DMA. Render subsystem in ROM bank `$E9` (`src/video.pasm`). | `VIDEO_PLUMBING.md` |
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
(the interpreter is a complete, MAME-verified MC68000) **and now renders video**.
The boot, frame loop, and PPU output all work. Detailed plan in
**[ROADMAP.md](ROADMAP.md)**. In short, in priority order:
1. **Inputs** — wire SNES controller state into the C-Chip input mailbox
   (`$900001/3/5`, active-low) so the game actually responds. The read path
   already returns `$FF` (idle) there; map the joypad to it (and keep the GWK
   boot-handshake replay intact). This makes it interactive and is the gate for
   any "does it play like MAME" check. I/O plumbing, not opcodes.
2. **Speed: profile, then transpile hot paths** to native 65816. The interpreter
   runs ~18 interp-steps per real frame — far below realtime — so reaching real
   gameplay (and a frame-synced pixel-diff vs MAME) is gated on speed. Capture a
   Mesen save-state at the live loop to skip the ~2200-frame boot per test, profile
   the hot 68K paths (boot delay loops, frame-work, VBLANK ISR), and generalize the
   `$412`/`$24D98` hand-transpilation spike into a tool. Expand G2 across the D1
   branch matrix.
3. Finish G1 coverage + the G4 endianness manifest; convert audio (YM2610→TAD)
   in parallel.

Video follow-ups (optional, low priority): OBJ cross-frame cache (sprites still
re-decode each frame; BG already caches), and a frame-synced per-pixel diff vs
MAME once the interpreter is fast enough to reach a gameplay frame.
