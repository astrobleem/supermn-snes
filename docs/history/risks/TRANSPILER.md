# Risk Mitigation: 68000 → SA-1 (65816) Transpiler

Advisor note. Companion to PROJECT_PLAN.md §1 and PORT_PLAN.md.
Goal of this doc: stop the transpiler from becoming an open-ended sink, and
catch correctness bugs early instead of at "why won't the boss die" time.

> **The four "settle now" decisions (H1–H4) are settled in `docs/history/designs/TRANSPILER_DESIGN.md`**
> — condition-code/branch lowering, the direct-page register file, the
> endianness policy, and the filled-in address map (single source of truth).
> This doc remains the hazard analysis + acceptance gates. Note: the address-map
> stub at the bottom of this file had a digit-dropped error (`$0B0000`/`$0E0000`)
> — see `docs/history/designs/TRANSPILER_DESIGN.md` §D4 for the corrected, ground-truth addresses.

## Why this is the highest-risk item

A 68000→65816 transpiler is not a translation, it's a re-implementation of a
different CPU's semantics. The two chips disagree in ways that produce code that
*assembles and runs* but is subtly wrong — the worst failure mode, because it
looks like a game logic bug, not a translation bug. The current plan treats this
as "write a transpiler for the bulk, hand-optimize hot paths." That's the right
shape, but the risks below will eat the schedule if not front-loaded.

Current state per TECHNICAL_REFERENCE.md: **14% disassembly coverage.** You
cannot transpile what you haven't separated into code vs data. Raising coverage
is a prerequisite, not a later step.

## The specific hazards (ranked)

### H1 — Condition-code semantics differ (CRITICAL, silent)
This is the #1 source of silent wrongness. The carry/borrow convention is
**inverted** between the chips on subtraction:
- 68000 `SUB`/`CMP`: C set = a borrow occurred.
- 65816 `SBC`/`CMP`: C set = *no* borrow (C must be pre-set with `SEC`).

So a naive `BCC`/`BCS` mapping after a compare branches the wrong way. The 68K
also has an `X` (extend) flag with no 65816 equivalent, and `V` (overflow)
semantics that don't line up for all ops. **Every conditional branch is
suspect** until proven by differential test (H-test below).

### H2 — Register width: 32-bit → 16-bit (CRITICAL)
68K D0–D7 and A0–A7 are 32-bit; the 65816 A/X/Y are 16-bit. Any 32-bit
operation (`.l` suffix, address math, multiply results) must be emulated as
multi-precision sequences. Decisions to make and write down:
- Register file lives in direct page: e.g. D0–D7 → `$00–$1F` (4 bytes each),
  A0–A7 → `$20–$3F`. Direct-page access is the SA-1's fast path — use it.
- Which registers are actually used as full 32-bit? Profile the disassembly;
  many will be 16-bit-effective and can skip the high word.

### H3 — Endianness (HIGH, silent on data)
68K is big-endian. Pointer tables, multi-byte constants, level data, and the
68K vector table are all big-endian on disk. Two clean options — pick one
project-wide, don't mix:
- (Preferred) **Byte-swap data at conversion time** so the SA-1 sees native
  little-endian. Keep a manifest of every table you swap.
- Swap at access time in code (slower, error-prone). Avoid.

### H4 — Address space & banking (HIGH)
68K is flat 24-bit ($000000–$FFFFFF). 65816 is 24-bit but bank-segmented, and
LoROM/SA-1 mapping is not flat. Arcade hard-coded addresses ($0F0000 work RAM,
$0E0000 sprite RAM, $900000 C-Chip, $800001 sound) must each be re-pointed to a
SNES target. Build the address map **once, explicitly** (see table stub below)
and have the transpiler translate through it — never let raw 68K addresses leak
into output.

### H5 — Cycle budget (HIGH, discovered late)
SA-1 @ 10.74 MHz vs 68K @ 8 MHz looks like headroom, but instruction expansion
is brutal: one 68K 32-bit op can become 5–20 SA-1 instructions. A frame is
~178,000 SA-1 cycles at 60 Hz. The arcade MAIN_LOOP ($0008FA) drives 8
subsystems every frame. **You can blow the budget and only find out when the
game slows under load (many enemies).** Mitigation: instrument cycle counts per
ported function and track against a budget from day one (see gate G3).

### H6 — Indirect/computed control flow (HIGH, blocks coverage)
Jump tables (`jmp (a0)`, `move.l (table,d0.w*4),a0`), self-modifying code, and
data-dependent dispatch defeat static disassembly — this is *why* coverage is
14%. These must be resolved by tracing in MAME, not guessed.

### H7 — Stack frame conventions (MEDIUM)
68K `link`/`unlk`/`movem` build frames the 65816 has no direct equivalent for.
GAME_TICK ($003A92) and MAIN_LOOP use `link`/`movem` prologues. Define a fixed
calling convention for transpiled code and a mechanical `link`/`movem` lowering;
test it in isolation.

## De-risking strategy: prove the pipeline on a tiny slice first

Do **not** transpile the whole 512KB and then debug. Spike it:

1. **Pick one pure, leaf function** with no I/O and no C-Chip — a math/physics
   helper (PHYSICS $024588 or COLLISION $028F92 are candidates once isolated).
2. Transpile it by hand *and* through the tool; diff the two. Disagreements are
   your transpiler's bug list.
3. Only generalize the transpiler once one real function is byte-faithful.

### The single most important tool: a differential test harness (G-H)
MAME is your golden reference. Build a harness that:
1. Runs the original 68K function in MAME (or a standalone Musashi 68K core)
   with N randomized input states (registers + relevant RAM).
2. Runs the transpiled SA-1 version in Mesen (you have Mesen2 + MCP) with the
   same inputs mapped through the address map.
3. Compares **all** outputs: touched RAM, returned registers, and flags that the
   caller consumes.

If the two diverge on any input, you have a concrete repro before the bug is
buried under ten other ported functions. This harness is the project's safety
net — build it before bulk transpilation, not after.

## Strategy choice to settle now: transpile vs interpret vs hybrid
The plan assumes full transpilation. Consider a **hybrid** to cut risk:
- **Interpret** cold/rare code (menus, init, dialog) with a small 68K
  interpreter on the SA-1. Slower per-instruction but trivially correct and it
  gets the game *running end-to-end* fast, which unblocks everything else.
- **Transpile + hand-optimize** only the hot path (MAIN_LOOP and its 8
  subsystems) where cycles matter.

This converts "the whole game must transpile perfectly before anything boots"
(a cliff) into "boot on the interpreter, then speed up hot spots" (a ramp).
Recommend at least prototyping the interpreter — it's the cheapest path to a
playable build and a second golden reference for the transpiler.

## UPDATE (June 24): hybrid native-escape built; gates partly reframed
The "transpile the bulk, hand-optimize hot paths" model became a **hybrid native-escape
hook** (`docs/history/designs/TRANSPILER_DESIGN.md` §D5): the MAME-verified interpreter runs everything, and hot
SAFE-LEAF subroutines are replaced by native 65816 one at a time. Consequences for the gates:
- **G1 (≥85% coverage) is NOT a prerequisite for the hybrid** — the interpreter is the cold
  fallback, so uncovered code still runs correctly. G1 matters only for a full static
  transpile (not the current plan).
- **G2 is now LIVE**, not just isolated spikes: `$412` runs through the hook in the live game,
  bit-identical hook off/on. The differential harness is `tools/lockstep.py` (whole-frame) +
  the hook-off/on diff. The interpreter itself is **bit-exact vs MAME** across gameplay.
- **G3 (cycle budget):** still open, and note `$4A` per-frame is `$AC`-gated (the main-loop
  spin absorbs steps a native escape frees), so the metric is wall-clock/cycles via
  `speedup_bench.py`, meaningful only once HOT leaves are hooked.
- The "14% coverage" line below is stale (see G1 = 10.2% confirmed floor).

## Acceptance gates (don't advance until green) — status June 17, 2026
- **G1 — Coverage** ≥85% executed code separated from data, via MAME-trace CDL.
  ⬆ IN PROGRESS. Reliable trace-driven pipeline built (`tools/build_cdl.py`); a
  full beat-the-game playthrough trace + scripted states give **10.2% confirmed
  code (zero false positives) and 779 indirect-jump targets resolved** (was 0 —
  the H6 blocker). Peony descent from these seeds = 35,047 blocks / ≥67.5% ROM
  classified. See `docs/toolchain/TRACE_COVERAGE.md`. (The old "14%" was unreliable linear-sweep.)
- **G2 — Differential harness green.** ✅ DONE. Built MAME-oracle harness; two
  real 68K leaves hand-transpiled to 65816 and verified on a real SNES PPU —
  `$412` (RNG: signed muls/divs/swap, 22/22) and `$24D98` (timer/clamp: signed
  ble/btst/loop, 12/12). See `SPIKE_RESULT.md`.
- **G3 — Cycle budget** <~150k SA-1 cycles/frame for the ported MAIN_LOOP path.
  ⬜ NOT STARTED.
- **G4 — Endianness manifest** exists and every converted table is on it.
  ⬜ NOT STARTED (policy settled in `docs/history/designs/TRANSPILER_DESIGN.md` §D3).

## Address map — MOVED & CORRECTED
The fillable stub that was here had a digit-dropped error (`$0B0000`/`$0E0000`/
`$0F0000` should be `$B00000`/`$E00000`/`$F00000`). The authoritative, ground-
truth-validated address map now lives in **`docs/history/designs/TRANSPILER_DESIGN.md` §D4** — edit it
there, not here.

## Fallbacks
- If full transpilation stalls: ship the **interpreter** build as the baseline
  and transpile incrementally. A slow-but-correct Superman beats a fast-but-
  broken one.
- If cycle budget fails on hot paths: hand-write those subsystems as native
  65816/SA-1 from the disassembly's *intent*, not its instructions.
