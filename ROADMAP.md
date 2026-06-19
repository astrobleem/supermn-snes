# Roadmap — where we're heading next

Last updated: June 18, 2026. Companion to [STATUS.md](STATUS.md) (current state)
and [METHODOLOGY.md](METHODOLOGY.md) (the reusable recipe).

## Context: what just got finished

The **68000 interpreter is complete** — the full legal MC68000 instruction set
(47/47 operation groups), each implemented and validated one-at-a-time against
MAME via `tools/optest.py` (154/154 differential vectors green), with a full-boot
regression after every batch. It boots Superman on a real SNES and settles into
its steady-state idle loop at PC `$0818`. See [INTERPRETER_SPIKE.md](INTERPRETER_SPIKE.md).

That closes out the "cold" side of the **interpret-cold / transpile-hot** hybrid.
We can now execute original 68K game logic correctly on hardware; the remaining
work is making it *do something visible*, then making it *fast enough*.

---

## Phase A — Drive the interpreter to a live in-game frame  ⬅ NEXT

The interpreter runs instructions correctly but currently treats most I/O writes
as no-ops (only `$F0xxxx` work RAM is backed). To get a playable frame we need to
connect the running 68K to the SNES it lives on:

1. **Video write capture → SNES PPU.** Intercept the game's writes to the X1-001/
   X1-002 video space and route them through the *already-validated* graphics path
   (palette decode + the two draw paths — see [PALETTE_VERDICT.md](PALETTE_VERDICT.md)).
   Start by trapping the write addresses in `writebyte`/`writeword`/`writelong`
   and mirroring sprite/tilemap/palette state into VRAM/CGRAM/OAM.
2. **Per-frame VBLANK IRQ.** The interpreter already has `take_irq` (level-6
   autovector). Drive it once per SNES frame and confirm the game advances its
   frame counter in work RAM, diffed against MAME.
3. **Inputs.** Feed controller state through the C-Chip input mailbox
   (already designed — see [CCHIP_BOOT_HANDSHAKE.md](CCHIP_BOOT_HANDSHAKE.md)).
4. **Acceptance:** one in-game frame rendered on real SNES (Mesen) that matches
   MAME's frame for the same inputs/state. This is the first "it's alive" gate.

**Nature of the work:** I/O plumbing and a frame loop — *not* new opcodes. The
instruction set is done.

## Phase B — Performance: profile, then transpile hot paths

Pure interpretation has overhead (a ~217-comparison linear decode per instruction
plus per-op dispatch). The open question is the **G3 cycle budget (<150k SA-1
cycles/frame)**. Plan:

1. **Profile** which 68K functions dominate per-frame execution (the trace/CDL
   pipeline already identifies hot code).
2. **Transpile the hot paths** to native 65816. The spike already proved this
   works — `$412` (Lehmer RNG) and `$24D98` (timer/clamp) are differentially
   verified ([SPIKE_RESULT.md](SPIKE_RESULT.md)). Generalize that hand-process
   into a tool; the interpreter stays the fallback for cold code.
3. **Expand G2** (the differential harness) across the D1 branch-lowering matrix
   as functions land, so every transpiled function is verified vs MAME.
4. Consider a faster interpreter dispatch (hashed/jump-table) *only if* profiling
   shows decode is the bottleneck — it was explicitly out of scope until now.

## Phase C — Disassembly coverage (G1) + endianness manifest (G4)

- Push G1 from the reliable 10.2% confirmed-code floor toward the ≥85% code/data
  separation gate (more playthroughs + full recursive-descent %). See
  [COVERAGE_G1.md](COVERAGE_G1.md).
- Produce the **G4 endianness manifest** (which data regions are byte-swapped) —
  policy is already set in D3 ([TRANSPILER_DESIGN.md](TRANSPILER_DESIGN.md)).

## Phase D — Audio (YM2610 → SNES)

Convert the YM2610 (FM + ADPCM) music/SFX to the SNES audio path (TAD/MML). The
analysis is done and a `vgm-to-tad-mml` skill exists; see
[CONVERTSOUND.md](CONVERTSOUND.md) and [SOUNDHARDWARE.md](SOUNDHARDWARE.md).
Can proceed in parallel with A–C.

## Phase E — Integration & distribution

Combine interpreter + transpiled hot paths + graphics + audio + input into a
single playable SA-1 ROM; verify full levels against MAME; package.

---

## Acceptance gates (from [RISK_TRANSPILER.md](RISK_TRANSPILER.md))

| Gate | What | State |
|---|---|---|
| **G1** | coverage ≥85% code/data separated | ⬆ in progress (10.2% confirmed floor) |
| **G2** | differential harness green | ✅ done (2 functions; framework reusable) |
| **G3** | cycle budget <150k/frame | ⬜ not started (Phase B) |
| **G4** | endianness manifest | ⬜ not started (policy set in D3) |

## Known limitations / backlog

- **Interpreter does not reject invalid EA encodings.** Opcodes with illegal
  effective-address fields (e.g. mode 7/reg 5–7, or PC-relative/immediate for
  alterable-only ops) are *executed* (reg>3 treated as `#imm`) rather than
  trapping to the illegal vector. General to all EA ops, pre-existing, and the
  game never hits it (boot-validated). A fix needs a systematic per-op
  allowed-modes validation layer — deferred; not required for Superman.
- **STOP** is modeled as "load SR + continue" rather than truly halting until
  interrupt — fine for single-step and boot; revisit if a hot path relies on it.

## Reuse beyond Superman

The interpreter is now a *complete, MAME-verified MC68000*, not a Superman-specific
subset. It's the reusable core for future 68000 arcade→SNES ports — the pinned
next target is **Space Harrier** (Mode 7 floor + sprite ladders; see project
memory). Revisit once the Superman toolchain (video plumbing + transpiler tool)
has hardened here.
