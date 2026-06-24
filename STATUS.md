# Superman (Taito X) → SNES/SA-1 — Project Status

Last updated: June 24, 2026. Single source of "where we're at." Per-area detail
lives in the linked docs.

## CURRENT STATE (June 24) — supersedes older detail below
- **Interpreter is BIT-EXACT vs MAME** on busy attract AND deep active gameplay (frames
  400/450/900/1500; Superman moving, 14 active actors incl. enemies) — modulo only 1-2
  unmodeled sound-CPU bytes. Validated via a frame-boundary **lock-step differential harness**
  (`tools/lockstep.py`: inject MAME's 68K state, run one game-frame, diff work RAM). 4 real
  opcode bugs found+fixed this way (relative-branch bank carry; `movem.l (d16,An)` load+store;
  `lea (xxx).W`) — all invisible to the op×mode sweep.
- **Correctness gate is `opsweep` 782/782** (`tools/opsweep.py`, SA-1-aware). NOTE: the older
  `optest 154/154` claim is DEAD — optest predates the SA-1 move and reads `snesWorkRam`; it
  fails build-wide and is deprecated. Use opsweep.
- **Phase A (SA-1) DONE** and **Phase B (hybrid native-escape) DONE**: a PC-hook
  (`bsr_hookpush`) routes a hooked 68K call to a native 65816 routine (ends `jmp inext`, never
  touches the 68K stack); `$000412` RNG runs natively, **bit-identical** hook off/on. Profiler
  (`rank_hot.py`/`sample_pcring.py`/`analyze_trace68k.py`) + live save-state + speedup harness
  built. Foundation HARDENED for bulk transpile: a latent per-hit stack leak fixed; sound
  STATIC leaf classifier (`tools/leaf_check.py`); FOUNDATION CONTRACT documented in
  `interp.pasm`. See `TRANSPILER_DESIGN.md` §D5.
- **NEXT = bulk transpilation**: hand-transpile `rank_hot`'s hot SAFE-LEAFs (first: `$00CB9E`),
  add each to the escape chain, validate hook off/on, measure speedup. The interpreter is the
  cold-path fallback. Open: cycle-aware `$AC` for self-paced realtime; the sound CPU model.
- Inputs are WIRED + validated (held Right drives Superman bit-identically to MAME).

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
**Inputs are wired**: a manual `$4016` joypad read (`joy_read`) feeds the C-Chip input
mailbox — `$900001`→P1 (active-low Up/Down/Left/Right/Btn1=B·Y/Btn2=A·X/Start),
`$900005`→Coin (SNES Select). `readbyte` routes those addresses to the mappers once the
boot handshake completes (`$A8`=1 input phase, command `$62`≠1). Validated end-to-end on
real SNES (Mesen): injecting a coin flips the game's own mailbox copies (`$F016BD/C1/C5`,
`$F01C50/54`) `$FF`→`$FE`; idle stays clean `$FF`. A harness-only virtual-controller word
at `$00:0200` (cleared at reset; OR'd into `joy_read`) injects input in emulation since
Mesen `set_input` doesn't reach the manual read path here — harmless on hardware (`$4016`
is the real source).

**Speed work — SA-1 enablement underway** (the interpreter runs ~14 68K-instr/real-frame,
~2,000× too slow; transpiling the per-frame path on the SA-1's 10.74 MHz CPU is the only
path to realtime — see `expressive-jumping-sparrow` plan). **A0 DONE**: the ROM is now a
real SA-1 cart (RomType `$FFD6=$33`, BW-RAM via SramSize `$FFD8=$07`=128 KB) and the 5A22
still boots the interpreter via a LoROM mirror of the interp into ROM `$0-$7FFF` (the SA-1
map exposes `$00:8000` as LoROM, breaking the HiROM layout otherwise). **A1 DONE**: the
SA-1 coprocessor is fully brought up and verified — it runs code from the mirror, writes
shared IRAM, write/reads BW-RAM (`$40` work RAM + `$41` shadow, both CPUs coherent), reads
high ROM banks (`$C1`/`$C9`/`$E9`), and the 5A22 still boots (`tmask=$0003`). Five fixes
cracked it (CIWP `$222A=$FF` first; Poppy 8-bit immediates via `sep #$20`; SA-1 `stp` to
free the ROM bus; BW-RAM via SramSize not ExpansionRamSize; SBWE `$2226=$80`). Added a
`get_cpu_state` tool to the Mesen MCP (SA-1 PC/regs) — decisive for debugging. **A2 DONE**:
the interpreter now RUNS ON THE SA-1 (work RAM `$7F→$40` BW-RAM, 65816 stack in IRAM, the
5A22 bootstraps the SA-1 then idles) and boots to the live loop **~5.7× faster** (80 vs 14
68K-steps/frame) with zero transpilation. **A3 in progress**: the video shadow moved
`$7E→$41` BW-RAM (SA-1 writes it), a 5A22 supervisor reads `$41` and drives the PPU on an
IRAM frame-signal — the dual-CPU render works (CGRAM/VRAM populated). Found+fixed a real
pre-existing bug (op_bitop BTST/etc. used the iloop's `$88/$8A` IRQ/countdown as scratch →
spurious frame IRQs kept the game in attract; moved iloop state to private `$AA/$AC`). The
fix advances the game far past attract. **A3 grind (June 21): fixed a MAJOR cross-bank
return bug** — `push32` hard-coded the pushed return's high 16 bits to `$00` and `op_rts`
did `stz $42`, truncating 68K addresses to bank 0; any `jsr`/`bsr` returning into banks
1-7 (the program is 512 KB) crashed on RTS. Fixed via `push32r` (return bank = PC bank
`$42` + carry) + `op_rts` popping the bank byte; added general EA-engine handlers
(`op_move_g`/`op_clr_g`/`op_pea_g`/`op_cmpib_g`). **The game now runs 165k → 718k
68K-instructions, reaches a steady IRQ-driven idle loop (`$0818`), and executes BANK-1 code
(`$01:370C`) — impossible before.** Next halt: `$066D` = `ADDI.W #imm,(d16,An)` (keep
grinding general ADDI/SUBI/etc.). Known follow-up: `op_jsr_abs`/`op_jsr_an` still force the
JSR *target* to bank 0 — needed for direct cross-bank calls. Then A3 cadence, then Phase B
(hybrid hook + transpiler). See `sa1-bringup`. Not started: audio.

ROM layout (4 MB HiROM): interp `$C0:8000` · 68K image `$C1:0000`–`$C8` · arcade tiles
`gfx1` `$C9:0000`–`$E8` · video subsystem `$E9:8000` (file `$298000`).

## Workstream status

| Area | State | Evidence / doc |
|---|---|---|
| **Graphics pipeline** | ✅ validated on real SNES PPU vs MAME | `PALETTE_VERDICT.md` |
| **Transpiler design (D1–D4)** | ✅ settled | `TRANSPILER_DESIGN.md` |
| **Transpiler spike (gate G2)** | ✅ GREEN — 2 functions differentially verified | `SPIKE_RESULT.md` |
| **68K interpreter** | ✅ **BIT-EXACT vs MAME** on busy attract + active gameplay (lock-step diff; 4 opcode bugs fixed). Runs on the **SA-1**. Correctness gate **opsweep 782/782** (`tools/opsweep.py`). (optest is deprecated — pre-SA-1, reads `snesWorkRam`.) Clears the **C-Chip boot handshake** (replay, not emulation). | `INTERPRETER_SPIKE.md`, `lockstep-harness-progress` memory |
| **Phase A — SA-1** | ✅ **DONE** — cart runs on SA-1 (work RAM in BW-RAM `$40`, shadow `$41`, dual-CPU video). | `sa1-bringup` memory |
| **Phase B — native-escape hook** | ✅ **DONE** — PC-hook routes hooked 68K calls to native 65816; `$412` RNG native, bit-identical. Profiler + save-state + speedup harness. Foundation hardened (leak fixed, `leaf_check.py`, FOUNDATION CONTRACT). | `TRANSPILER_DESIGN.md` §D5 |
| **Video plumbing** | ✅ **COMPLETE** — 68K video-bank writes → `$7E` shadow → real PPU each game-frame. Palette byte-exact, tile decode 128/128, OBJ+BG render the correct arcade frame; OBJ/BG tile dedup, cross-frame BG cache, vblank-safe DMA. Render subsystem in ROM bank `$E9` (`src/video.pasm`). | `VIDEO_PLUMBING.md` |
| **Disassembly coverage (gate G1)** | ⬆ in progress — reliable pipeline + full playthrough | `COVERAGE_G1.md` |
| **Tooling (MAME/Mesen MCP, trace/CDL)** | ✅ built & validated | below |
| **C-Chip** | ✅ SOLVED — patch + input mailbox + **boot handshake replay**, still **no MCU emulation** | `CCHIP_BOOT_HANDSHAKE.md`, `CCHIP_FIRMWARE.md` |
| **Audio (YM2610→TAD)** | 🔬 analyzed; `vgm-to-tad-mml` skill exists | `CONVERTSOUND.md`, `SOUNDHARDWARE.md` |
| **Bulk transpilation (native escapes)** | ⬅ **NEXT** — mechanism BUILT (Phase B); hand-transpile hot SAFE-LEAFs into the escape chain. The interpreter is the cold-path fallback (no ≥85% coverage prerequisite for the hybrid). | `TRANSPILER_DESIGN.md` §D5 |

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
