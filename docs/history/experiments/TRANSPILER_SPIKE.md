# Transpiler Spike — Result: G2 GREEN (68K → 65816, differentially verified)

Date: June 17, 2026
Outcome: **the 68000→SA-1/65816 transpilation pipeline is proven end-to-end on a
real leaf function, validated against MAME as an independent oracle.** This is
acceptance gate **G2** (RISK_TRANSPILER.md) green for the spike.

## What was proven

A real Superman 68K leaf — **`$000412`**, the RNG `state = (176·state) mod 32749`
at work-RAM `$F0170E` — was hand-transpiled to 65816 per `docs/history/designs/TRANSPILER_DESIGN.md`
and run on a real SNES PPU/CPU (Mesen). Its output matched MAME's 68K execution
on **22/22** input vectors, including signed/negative edge cases:

| 68K input | rem (stored word) | quotient (hi word of D7) | |
|---|---|---|---|
| 0, 1 | B0 | 0 | x==0→1 path |
| 1000 | 2FDF | 5 | normal |
| 32749 (=divisor) | 0 | B0 | exact divide, Z flag |
| 0x8000 (−32768) | F2F0 | FF50 | **signed** divs |
| 0xC000, 0xFFFF | F978/FF50 | FFA8/0 | **signed** |

Both the remainder *and* the quotient match — i.e. the full `muls.w`/`divs.w`/
`swap` semantics are reproduced, not just the stored result.

## The pipeline (each step is now a reusable tool)

1. **Trace** (`tools/mame-trace/trace68k.lua`, `run_trace68k.sh`): headless 68K
   PC+disasm trace via MAME's debugger.
2. **Analyze** (`tools/analyze_trace68k.py`): coverage, caller→callee call graph,
   pure-leaf finder, indirect/jump-table (H6) sites. Picked `$412`; also exposed
   that `GAME_LOGIC_ANALYSIS.md`'s `$8FA "MAIN_LOOP"` label is wrong (it's a
   memcpy helper) — labels there are guesses, confirm by trace.
3. **Golden capture** (MAME MCP `capture_leaf_io`, `goldens_412.txt`): injects
   inputs via a read-tap, records output + D7 + CCR. MAME is the independent
   oracle — avoids the self-referential trap that bit the early palette work.
4. **Transpile** (`src/spike412.pasm`): signed `muls`/`divs` lowered to software
   helpers (unsigned 16×16→32 multiply; unsigned 32÷16→16 long division with
   sign fix-up); the divide's compare/subtract uses the **D1** carry convention
   (65816 `cmp`/`bcc`/`sbc`: C set = no borrow); 32-bit values in direct page
   (**D2**). Assembled with Poppy.
5. **Differential harness** (`tools/spike_harness.py` + Mesen MCP): patch the
   transpiled code into the loaded ROM image (`snesPrgRom`, survives
   `reset_emulator` — no relaunch needed), drive a batch of inputs through WRAM,
   read outputs, compare to the MAME goldens. Result: **ALL GREEN**.

## Why this leaf was the right spike

Tiny and pure, but it stresses the hardest semantics first: signed 32÷16 divide
(no 65816 equivalent → software long division, exactly where the D1 carry
inversion bites) and the 32-bit `swap`. Getting this green de-risks the scariest
part of the transpiler before bulk work.

## Second function — $24D98 (also G2 GREEN)

To prove the tools generalize beyond a tidy self-contained RNG, a second, real
gameplay leaf was harnessed: **`$24D98`**, a timer-countdown/clamp over three
12-byte struct slots (fully A5-relative → fixed addresses). Hand-transpiled
(`src/spike24d98.pasm`) and verified against MAME on **12/12** vectors
(`tools/spike24d98_harness.py`, goldens `tools/mame-trace/goldens_24d98.txt`).

It exercises the D1 branch behavior `$412` did not, as direct transpilations:
- **signed `ble` (`<=0`)**: the 68K does `sub.w; tst.w D1; ble`. `tst.w` clears V,
  so `ble` is just `Z OR N` → 65816 `beq`/`bmi` after the subtract. Confirmed by
  the word-wrap vector `0x8000-1 = 0x7FFF` (V *would* flip a naive `ble`, but it
  is correctly **not** cleared).
- `btst` of a runtime bit index (id 0 and 2), set/clear paths.
- the `trap #1` path: its only *struct-region* effect is `f8=$B4`, so the
  differential matches without replicating the OS call.

New tooling proven along the way: gameplay trace with input injection
(`trace68k_play.lua` → 2483 distinct instr, 28 leaves); MAME MCP `get_ioports`,
`run_lua_inline`; region-I/O injection capture (`capture_24d98_inject.lua`).
Also found and fixed an analyzer gap (it didn't treat `trap`/`chk` as non-leaf),
and confirmed isolated execution via PC/register pokes **crashes** stock MAME
0.287 — so tap-observation of fixed addresses is the robust capture method.

## What this does NOT yet cover (next)

- **Coverage (G1):** the attract-mode trace hit only ~1800 distinct instruction
  addresses. Gameplay injection + longer runs are needed to approach 85% and to
  resolve the 57 indirect/jump-table sites.
- **More semantics:** a leaf exercising `cmp`+`bcc/bhi/bls` unsigned branches and
  signed `bge/blt` (the rest of D1) should be the second harnessed function.
- **Cycle budget (G3)** and the **interpreter-vs-transpile** strategy call remain
  open (RISK_TRANSPILER.md).
- Generalizing the transpilation from hand-written to tool-generated.
