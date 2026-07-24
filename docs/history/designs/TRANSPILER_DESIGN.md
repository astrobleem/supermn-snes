# Transpiler Design Decisions — 68000 → SA-1 (65816)

> **Historical design record.** The CPU/CCR/endianness reasoning remains essential,
> but this document's claim to be the current address-map authority is superseded.
> Its D4 table contains early inferred device labels. Use the
> [current address-map adaptation guide](../../toolchain/ADDRESS_MAP_ADAPTATION.md)
> and pinned MAME driver for integration; use this document for lowering rationale and
> the original escape contract.

Date: June 16, 2026
Status: **settled, coverage-independent.** These four decisions (D1–D4) plus the
address map are the ones `RISK_TRANSPILER.md` says to "settle now." None of them
depend on raising disassembly coverage, so they can be locked before the
trace/spike work. Items that *do* depend on coverage are marked **DEFERRED**.

This file is the single source of truth for CPU-semantics lowering and the
address map. The transpiler and the differential harness (gate G2) must agree
with it. Every rule here is a **hypothesis the G2 harness must confirm** — the
table is the spec, the harness is the proof.

Companion docs: `RISK_TRANSPILER.md` (hazard analysis + gates), `docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md`
(validated graphics addresses/decode), `PORT_PLAN.md`.

---

## D1 — Condition codes & branch lowering (hazard H1, CRITICAL/silent)

The carry flag means **different things depending on the operation that set it.**
A naive opcode→opcode mapper that ignores this provenance silently inverts every
unsigned comparison. The transpiler MUST track, per flag-set site, whether C came
from an **add-class** or **sub-class** operation.

### Carry after ADDITION — identical on both chips
68K `ADD/ADDI/ADDQ/ADDX` and 65816 `ADC` both set `C = carry-out of MSB`.
A 68K `BCC/BCS` consuming add-carry maps **1:1** to 65816 `BCC/BCS`. No swap.

### Carry after SUBTRACTION / COMPARE — INVERTED
- 68K `SUB/SUBI/SUBQ/CMP/CMPI/CMPA`: `C = 1` ⟺ a borrow occurred ⟺ unsigned `dest < src`.
- 65816 `SBC/CMP`: `C = 1` ⟺ **no** borrow ⟺ unsigned `acc ≥ operand`.

So for carry originating from a sub/compare, **swap the branch:**

| 68K branch (after SUB/CMP) | meaning | 65816 emits |
|---|---|---|
| `BCS` / `BLO` | dest `<` src (unsigned) | **`BCC`** |
| `BCC` / `BHS` | dest `≥` src (unsigned) | **`BCS`** |

(If the carry came from an ADD, do **not** swap — emit `BCC→BCC`, `BCS→BCS`.)

### Z and N — identical
`BEQ/BNE` (Z) and `BMI/BPL` (N) map 1:1 after both add and subtract.

### V (overflow) — the CMP trap
- 68K `CMP` sets V correctly, so signed branches work after it.
- **65816 `CMP` does NOT touch V** (6502 heritage: CMP affects only N, Z, C).
  You therefore cannot lower a 68K *signed* compare to a 65816 `CMP` and branch
  on V/N — V is stale.
- **Rule:** whenever the consumed branch is signed (`BGE/BLT/BGT/BLE`) or
  `BVC/BVS`, lower the comparison through a V-setting path: `SEC : SBC`
  (SBC does set V), not `CMP`.

### Branches with no 1:1 on the 65816 — synthesise
65816 has only `BPL BMI BVC BVS BCC BCS BNE BEQ BRA BRL`. The rest are macros
(carry already inverted per above where the source was a sub/compare):

- **`BHI`** (unsigned `>`, 68K `C̄∧Z̄`) — taken when `dest>src` ⟺ (post-CMP) C set ∧ Z clear:
  ```
        BEQ  .skip        ; equal → not higher
        BCS  target       ; ≥ and ≠  ⇒  >
  .skip:
  ```
- **`BLS`** (unsigned `≤`, 68K `C∨Z`) — taken when `dest≤src` ⟺ C clear ∨ Z set:
  ```
        BEQ  target       ; equal → ≤
        BCC  target       ; <     → ≤
  ```
- **`BGE/BLT/BGT/BLE`** (signed) — require `N⊕V`, which no single 65816 op tests.
  After a **V-setting** subtract (`SEC:SBC`), synthesise `N⊕V` and branch. These
  are the **highest-risk lowerings**; each gets a canned macro and each MUST pass
  the G2 harness on flag-sensitive random inputs before use.

### X (extend) flag
68K's X is a second carry used only by `ADDX/SUBX/NEGX/ROXL/ROXR`, preserved
across non-X ops so a multi-precision carry chain survives intervening
instructions. The 65816 has no X — multi-precision uses C directly via `ADC/SBC`.
Because we lower every 32-bit op into our own multi-precision sequence (D2), X
lives only *inside* those sequences. **Rule:** never emit a flag-clobbering
instruction between the low-half and high-half of a lowered 32-bit add/sub.

### CCR at a function boundary — materialization (implemented 2026-07-01)

The rules above lower each 68K branch to **native 65816 flags** at the branch
site. That is correct *inside* a transpiled function. But a 68K subroutine leaves
its CCR live across `rts`, and an escape's **caller may be interpreted** — the
interpreter reads the CCR from **memory** (`$60`=Z, `$6E`=C, `$70`=N, `$72`=V,
`$A2`=X; nonzero = set). A transpiled escape that only touches native flags leaves
that memory **stale at its `rts`** → the interp-caller's next conditional branch
reads the wrong flags. (This was a live bug: `entry_ce4t` diverged on the
`trip1000` state at `$F0104F` — root-caused to a stale exit CCR from a `subq`
that the caller branched on. See memory `fetch-chokepoint-rts-escape`.)

**Rule:** at every point where native code returns to the interpreter with a live
CCR — i.e. a **branch whose target is the epilogue/rts** — materialize the 68K CCR
memory from the live native flags, with provenance:
- **sub/cmp path** (`fsrc='signed'`, from `SEC:SBC`): `Z/N/V` = native, **`C = !nativeC`**
  (68K sub-borrow inversion), `X = C`.
- **move/logic/tst path** (`fsrc='tst'`): `Z/N` = native, `V = 0`, `C = 0`, `X` untouched.

Implementation (`tools/transpile.py`): `emit_ccr_native(e, fsrc)` emits the
materialization; the driver computes `e.exit_addrs` (the straight-line flag-
preserving epilogue run — `movem/unlk/lea/pea/nop/movea/link/adda/suba` + `rts`,
walked back from each `rts`, stopping at control flow); `emit_branch` inserts the
materialization on any taken-jump whose target is in `exit_addrs`. This is
**exit-only, per-path** — native flags are live at the branch edge, and hot loops
get **zero** materializations (the win is preserved).

**Scope/known gaps (2026-07-01):** (1) *fall-through* into the epilogue through
flag-clobbering glue (`dbra`/`movea`) is not yet materialized (needs value-reload
from the last flag-op's result reg — deferred, test-driven; no confirmed case).
(2) X-stickiness: `fsrc='signed'` conflates `subq` (X=C) with `cmp` (X untouched),
and an add-fed `tst`-class branch loses the add's real C — both rare (only matter
to a following `ADDX/SUBX/NEGX/ROXx` or a caller reading that exact C). Only
escapes that RETURN via `rts` and have a branch-to-exit edge are affected; coroutine/
jmp-state escapes (end in a tail-jump, no `rts`) never observe this.

---

## D2 — Register file: 32-bit 68K regs in direct page (hazard H2)

68K `D0–D7`, `A0–A7` are 32-bit; 65816 `A/X/Y` are 16-bit. Hold the 68K register
file in **direct page** (the SA-1's 2-cycle fast path), little-endian:

```
DP base + $00 : D0   (low word @ +0, high word @ +2)
          $04 : D1
          ...
          $1C : D7
          $20 : A0
          ...
          $3C : A7    ← 68K stack pointer; see note
```
`Dn` at `base+4n`, `An` at `base+$20+4n`. 64 bytes total. Keep DP fixed at this
base so every register access is direct-page.

**Operand sizes:**
- `.b` → low byte at `base+4n`.
- `.w` → low word at `base+4n` (16-bit, M=0).
- `.l` → two 16-bit ops: low word `base+4n`, high word `base+4n+2`, carry-chained
  (and per D1's X rule, nothing flag-clobbering between halves).

**A7 / stack — do NOT alias to hardware S.** 68K A7 is manipulated by
`link/unlk/movem/pea` and word/long pushes, and the 68K pushes return addresses
**big-endian** onto that same stack. Keep A7 as the DP pseudo-register at
`base+$3C`; implement 68K stack ops as explicit, endian-correct memory accesses
through it into a dedicated 68K-stack region in BW-RAM. Reserve the hardware `S`
for the *transpiled-function* call/return convention only (hazard H7). Mixing the
two silently corrupts frames.

**DEFERRED (trace-driven):** which `Dn` are ever used as full 32-bit. Many are
16-bit-effective and can skip the high word + carry chain. The layout above is
the safe superset; the per-register narrowing is a profiling pass during the
spike, gated on coverage.

---

## D3 — Endianness policy (hazard H3)

68K data is big-endian on disk (code operands, pointer tables, level data,
constants, vector table). **Policy: byte-swap at conversion time** so the SA-1
sees native little-endian. Never swap at access time. Keep a manifest
(`data/endian_manifest.*`, gate G4) listing every converted table + element type.

Rules by type:
- **16-bit word value:** swap the 2 bytes.
- **32-bit long value:** reverse all 4 bytes (`B3 B2 B1 B0` → `B0 B1 B2 B3`).
- **Pointer/address table (32-bit):** TWO transforms — (1) byte-reverse, AND
  (2) re-point each entry through the **D4 address map**. A raw 68K address must
  never survive into runtime output.
- **Byte / packed-pixel arrays:** no swap. (gfx tiles are handled by the asset
  pipeline, not here — see `docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md`.)
- **Mixed structs:** swap field-by-field per layout; record the layout in the
  manifest.

A table not on the manifest is presumed unconverted = a bug (G4).

---

## D4 — Address map (hazard H4) — SINGLE SOURCE OF TRUTH

The transpiler translates **every** 68K effective address through this table;
raw 68K addresses never leak into output. Arcade addresses below are the
**ground-truth** values used by the validated MAME trace scripts and the
hardware-validated graphics path (`docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md`).

> **Correction:** the stub in `RISK_TRANSPILER.md` listed `$0B0000` / `$0E0000`
> / `$0F0000` — those **dropped a leading digit and are wrong.** The real
> addresses are `$B00000` / `$E00000` / `$F00000`, confirmed by the trace
> scripts that produced MAME-matching output. Use this table, not that stub.

| 68K address | Size | Meaning | SNES / SA-1 target | Source / confidence |
|---|---|---|---|---|
| `$000000–$07FFFF` | 512KB | 68K program ROM | SNES ROM `$00–$0F:8000+` (LoROM/SA-1) | transpiled, not byte-copied |
| `$300000` | — | watchdog / frame strobe | NOP / frame-sync | inferred (GAME_LOGIC) — CONFIRM |
| `$400000` | — | input port | joypad shim via C-Chip | inferred — CONFIRM |
| `$500000–$500007` | — | DIP / input | config constants / joypad shim | per MAME driver (RISK_CCHIP V3) |
| `$600000` | — | control / frame reg | NOP / frame-sync | inferred — CONFIRM |
| `$700000` | — | **NOT a C-Chip port** for superman (GAME_LOGIC error, RISK_CCHIP V3) | — | not mapped |
| `$800001 / $800003` | — | sound cmd / status (TC0140SYT) | SPC700 APU `$2140–$2143` (or TAD) | see CONVERTSOUND |
| `$900000–$9007FF` | C-Chip shared RAM (P1/P2/coins mailbox `$900001/3/5`) | input mailbox: write mapped SNES pads each frame | **CLOSED** — CCHIP_FIRMWARE.md PORT RESOLUTION |
| `$900800–$900FFF` | ASIC regs (`$900803` self-test status) | return **$01 (OK)** / patch the gate — no MCU emulation, no PRNG | **CLOSED** |
| `$B00000–$B00FFF` | 4KB (2048×w) | Palette RAM (xRGB555) | CGRAM shadow → DMA; xRGB→xBGR | **VALIDATED** (PALETTE_VERDICT) |
| `$D00000–$D005FF` | 1.5KB | sprite Y-low (type1) + tilemap/scroll (type0) | shadow OAM + BG scroll | **VALIDATED** |
| `$D00400` | — | scroll RAM (really one continuous scroll) | BG H/V scroll regs | **VALIDATED** (bg finding) |
| `$D00600–$D00607` | — | X1-001 video control | PPU reg / port setup | **trace-confirmed** addr |
| `$E00000–$E03FFF` | 16KB | sprite code + X+color (type1) / code+color (type0) | shadow OAM + BG tilemap (VRAM) | **VALIDATED** (both paths) |
| `$F00000–$F03FFF` | **16KB (CONFIRMED)** | Work RAM | SA-1 BW-RAM `$40:0000+` (big-endian) | **CONFIRMED 16KB** — not 64KB; `$F0FF00` etc. are UNMAPPED |

Confidence legend: **VALIDATED** = reproduced on real SNES PPU matching MAME;
**trace-confirmed** = address verified by a working MAME trace tap; **inferred**
= from `GAME_LOGIC_ANALYSIS.md` static analysis, treat as hypothesis until traced.

**DEFERRED (trace-driven):** exact Work-RAM extent; the precise split of
`$300000/$400000/$500000/$600000/$700000` between inputs, DSW, C-Chip and frame
strobes (GAME_LOGIC's labels are static guesses — confirm by trace, same
discipline that corrected the palette work).

---

## D5 — Native-escape hook mechanism (the bulk-transpile interface) — BUILT (June 24)

Phase B replaced the "transpiler tool emits a whole program" model with a **hybrid
native-escape hook**: the interpreter runs everything; for a hooked 68K subroutine, a
hand-/tool-transpiled native 65816 routine runs *instead*. This is what bulk transpilation
extends. It supersedes D2's earlier H7 "reserve hardware S for a transpiled call/return
convention" — escapes do NOT use a call/return convention; they REPLACE the routine and fall
back into the interpreter's fetch loop. The contract (also in `src/interp.pasm`, before
`bsr_hookpush`):

**Dispatch.** `bsr_hookpush` byte-neutrally replaces `op_bsr`/`op_jsr_pcrel`'s `jsr push32r`.
It resolves the 24-bit call target; if the hook is enabled (`$071A`!=0) and the target is in
an INLINE immediate-compare chain, it sets the 68K PC to the return address and `jmp`s the
native routine. Otherwise it does the normal 68K-stack push. (An abs-indexed jump table was
tried and abandoned — DBR/PBR-fragile on the SA-1; use the immediate chain.)

**Six rules for adding an escape (each = one more transpiled function):**
1. **SAFETY** — only hook targets that `tools/leaf_check.py` reports **SAFE-LEAF** (a STATIC
   all-paths CFG walk: no call / indirect jmp / device I/O on ANY path). The trace-based leaf
   flag in `analyze_trace68k.py` is UNSOUND for this — it marked `$24D98` (trap) and `$25110`/
   `$0129C6` (calls) as leaves because one trace only hit their leaf path.
2. **STACK** — the native routine must end `jmp inext` and NEVER `rts`/touch the 68K stack. On
   a HIT the dispatch `pla`s op_bsr's 65816 return so S stays balanced. (The earlier
   `jsr hook_check; jmp native` form leaked 4 bytes/hit → crash after ~64; `multi_hit.py` is
   the stress test.)
3. **SCRATCH** — native routines use ONLY transient DP `$80–$9E`. NEVER clobber the 68K
   register file `$00–$3F` (except the result regs the real routine writes — per D2 layout),
   the flags `$60–$7F`, or `$A0–$AC`. Read/write work RAM via `$40:xxxx` long addressing; ROM
   via `readbyte`.
4. **FLAGS** — set the interp CCR slots the routine's last flag-setting op would (Z@`$60`
   nonzero=set, C@`$6E`, N@`$70`, V@`$72`) per D1, if the caller consumes them.
5. **ENABLE** — `$071A`=0 (off) by default so the lock-step hook-off/on differential works
   (`lockstep.py` argv3). Production sets `$071A`=1 once (e.g. at boot).
6. **VALIDATE** — every new escape: hook-off vs hook-on differential must be **bit-identical**
   (work RAM + reg file), and `multi_hit.py` must stay balanced across many hits. Measure the
   win with `speedup_bench.py` (NOTE: `$4A` per-frame is `$AC`-gated — the main-loop spin
   absorbs freed steps — so the metric is wall-clock/cycles, and only HOT leaves show a number).

**Reference escape:** `entry412` = `$000412` Lehmer RNG, reusing the G2-verified `rng_core`
math with scratch relocated to `$80–$94`. Bit-identical hook off/on.

**Target selection:** `tools/rank_hot.py` joins per-entry trace cost (inv×icount) + the live
PC-ring histogram + the SAFE-LEAF flag. First bulk target: `$00CB9E` (SAFE-LEAF, 31 instr,
~10 calls/frame, `bsr`-called).

---

## How these gate the rest

- D1–D4 are settled now → they unblock the **spike** (one leaf function,
  hand-vs-tool transpile, G2 harness) without waiting on coverage.
- The DEFERRED items (32-bit register profiling, jump-table resolution,
  Work-RAM extent, input/DSW split) are exactly what the MAME CDL trace produces.
  They feed back into this file as they're confirmed.
- Gates (from `RISK_TRANSPILER.md`): **G1** coverage ≥85%, **G2** differential
  harness green on the spike, **G3** cycle budget <150k/frame, **G4** endianness
  manifest complete. D1–D4 are prerequisites for G2; none of them clears G1.
