# Roadmap — where we are and where we're heading

Last updated: June 29, 2026. Companion to [STATUS.md](STATUS.md) (current state)
and [METHODOLOGY.md](METHODOLOGY.md) (the reusable recipe).

> **UPDATE 2026-06-30 — [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) is authoritative for the
> latest plan.** Correction to the "Done + validated" claim below: the **rts convention class does
> NOT fire in gameplay** (only jmp-state and coroutine/rte-resume do); the table is real but
> rts-reached handlers bypass it. The bottleneck is the **coroutine scheduler**, not dispatch.
> Progress this session (steps A–D): `entry_c172` shipped (first coroutine escape), `lh_sched`
> shipped (native scheduler scan, −125 interp/tick), the `$AC`-charge question resolved, and the
> transpiler gained `move.l → -(An)` (push-long). Next targets: the residual scheduler re-entries
> ($0540/$0500), more coroutine bodies ($46DE/$11752 are transpiled + ready), and a fire-finder for
> rare jmp-state handlers. See handoff §4.

## DIRECTIONAL UPDATE (June 29) — from hand-escaping to AOT

The thesis below (*interpret-cold / transpile-hot*) is unchanged, but the **method**
pivoted. Hand-escaping one hot cluster at a time hit a wall: the transpiler already
produces bit-exact native code, but *every* cluster became a multi-hour hunt for how
its control transfer (jmp/rts/rte/coroutine) is reached, each needing a bespoke
dispatch hook. The pivot is **ahead-of-time (AOT) transpilation**: build ONE global
68K-PC→native table that all control flow consults (hit → native, miss → interpret),
demoting the interpreter to a cold-path fallback, and batch-transpile the CDL block
list through it. Dispatch stops being a per-case hunt and becomes one indirection.

**Done + validated (this phase):** the dispatch table (`xlat_dispatch` @ $94:F900,
blob @ $96:8000, `tools/gen_xlat_table.py`) with two convention classes unified onto
it bit-exact — jmp-state (via `ojmp_hook`) and rts (via `op_rts_norm`); plus the
`transpile.py --table` convention primitive. **Bottleneck moved** from dispatch
(solved) to per-function correctness + SA-1-side validation tooling: the hottest
cluster ($0CE4) dispatches but diverges (a timeline-coupled, escape-on-only reach).
**Remaining to playable:** (1) SA-1-side full-trace / step validation to diagnose
divergences and validate at scale; (2) convention-unify the jsr/coroutine classes;
(3) the `inext` chokepoint (convention-free, catches every transfer); (4) scale bank
allocation to $80–$9F + batch-transpile the CDL list; (5) divergence-bisection. See
the `aot-dispatch-table` memory + STATUS.md (June 29) for detail. The per-function
hot-list below remains the coverage target; execution now runs through the table.

## The plan in one screen

**The thesis (unchanged):** *interpret-cold / transpile-hot.* A hand-written 68000
interpreter runs the original game logic correctly on the SNES's SA-1 coprocessor; the
small set of functions that dominate each frame is replaced by native 65816 ("escapes"),
leaving the interpreter as the fallback for everything cold. This is the only path to
realtime — a pure interpreter is ~2,000× too slow; a full static recompile of a 512KB ROM
is infeasible and unverifiable.

### Where we WERE (start of this phase)
The cold side was done: a complete, MAME-verified MC68000 interpreter that boots Superman on
real SNES hardware, runs gameplay, renders video (real PPU), and reads input — running on the
**SA-1**. The native-escape **mechanism** existed (Phase B), but functions were **hand-transpiled**
one at a time, which tops out around icount ~60. The big hot functions (collision, video, the
$025xxx cluster) were too large to hand-do, and non-leaf functions (with calls) weren't handled
at all.

### Where we ARE (now)
The hot side is now a **tool**, not handwork:
- **`tools/transpile.py`** — an automated 68K→65816 transpiler, validated bit-exact (it reproduces
  the hand oracles). It handles the full EA matrix, the D1 signed-branch lowering, `link`/`movem`,
  byte/word/long ops, shifts, `moveq`, `dbra`.
- **Call-bridge codegen** — non-leaf functions work: each call hands back to the interpreter and
  resumes via a sentinel continuation. Proven end-to-end on `$025110` (collision, **~12.6%**,
  544 instrs, 2 bridged calls).
- **`--video` codegen** — stores to the video banks route to the `$41` shadow. Proven on `$0020e8`
  (video, **~5.9%**), validated against the shadow itself.
- **8 hot functions transpiled + deployed** in free bank-$00 gaps, all bit-exact (no ROM-layout
  change — the multi-bank idea proved unnecessary).
- The **profiler** ranks the remaining hot set from the live interpreter's PC stream.

### Where we're going NEXT (the throughput grind)
1. **Transpile the rest of the hot set** (now mechanical): pick the next function from
   `stream_profile.py`, `transpile.py [--video]`, deploy in a gap, validate ON-vs-OFF=0.
2. **Hit the realtime cycle budget (G3)**: benchmark steps/frame + SA-1 cycles; transpile until
   the per-frame path fits ~150k SA-1 cycles, then add cycle-aware IRQ pacing for unattended play.
3. **Manage bank-$00 space** (a code-size pass, or a 2nd executable bank) as the gaps fill.
4. **Audio** (YM2610→TAD) in parallel; **integration** into one playable, full-level-validated ROM.

### Where we END UP (the deliverable)
A single playable **SA-1 cartridge ROM** of Superman: the per-frame hot path runs as native 65816,
the cold remainder is interpreted, video/input/audio all work, paced to (near-)arcade realtime, and
validated frame-for-frame against MAME. The interpreter + transpiler are then a **reusable
arcade→SNES toolchain** for the next 68000 target (pinned: Space Harrier).

---

## STATUS UPDATE (June 25) — Phases A, B & the transpiler tool are DONE
- **Phase A (drive to a live frame) — DONE.** Bit-exact vs MAME on attract + active gameplay;
  video + inputs + per-frame IRQ; runs on the SA-1. Correctness gate **opsweep 782/782**.
- **Phase B (hybrid hook) — DONE.** Native-escape PC-hook (jsr.l/jsr(An)/bsr), profiler, save-state.
- **Bulk transpilation — UNDERWAY (automated).** `transpile.py` + call-bridge + `--video`; 8 escapes
  deployed and validated, incl. the ~12.6% collision (bridged) and ~5.9% video (shadow). See the
  `transpiler-tool` / `bulk-transpile-phase` / `multibank-interp` memories.

The detailed (historical) phase plan follows.

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
2. **Transpile the hot paths** to native 65816. ✅ **The tool exists** —
   `tools/transpile.py` (call-bridge for non-leaf, `--video` for shadow stores),
   validated bit-exact. 8 escapes deployed (RNG, sprite/object builders, the ~12.6%
   collision, the ~5.9% video). The interpreter stays the fallback for cold code.
   Remaining: transpile the rest of the ranked hot set; the work is now mechanical.
3. **Validate every transpiled function** via the fresh-adjacent-tick lockstep
   (`flyval.py`/`val_*`): inject one MAME game-tick, run hook-ON vs OFF, require live
   state identical (a7-classify stack diffs; diff the `$41` shadow for video).
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
| **G1** | coverage ≥85% code/data separated | ⬆ in progress (10.2% confirmed floor) — not a blocker for the hybrid (interpreter is the cold fallback) |
| **G2** | differential harness green | ✅ done — automated transpiler validated bit-exact; every escape lockstep-checked vs the MAME-verified interpreter |
| **G3** | cycle budget <150k/frame | ⬆ in progress — hot mass being transpiled; needs a benchmark + the remaining hot set |
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
