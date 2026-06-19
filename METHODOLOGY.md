# Arcade → SNES Port Playbook

How we ported (are porting) Superman (Taito X, 68000) to SNES/SA-1, written so the
same recipe + tools apply to the **next** game. Superman is the worked example;
the method is general. Companion: per-area docs (`PALETTE_VERDICT.md`,
`TRANSPILER_DESIGN.md`, `SPIKE_RESULT.md`, `COVERAGE_G1.md`) and `STATUS.md`.

## 0. The one rule: ground-truth validation
Never validate a decode against the same code path that produced it (that "proves"
self-consistency, not correctness — it's what made an early palette proof
confidently wrong). Always check against an **independent oracle**:
- **Arcade side → MAME** (the original running correctly).
- **SNES side → real PPU/CPU via Mesen** (not a reimplementation).
Two MCP servers make these first-class: **`mame`** (`/home/chad/mame-mcp`) and
**`mesen`**. If a result isn't checked against one of these, treat it as a guess.

## 1. Graphics pipeline (decode → reproduce → diff)
1. Dump the arcade's gfx/palette/sprite-RAM from MAME (Lua taps / `read_u16`;
   68K is big-endian — read words, not byte-lanes).
2. Decode to RGB and **diff against MAME's own rendered frame** (count exact color
   matches). This catches byte-order/plane-order/palette-format bugs.
3. Rebuild the frame on a **real SNES PPU** (Mesen) and diff pixels vs MAME again.
Superman result: arcade `xRGB555` (big-endian) → SNES `xBGR555`; both X1-001 draw
paths reproduced (foreground→OBJ, playfield→BG), 47/47 colors. See `PALETTE_VERDICT.md`.
Gotcha: sprite palettes are per-bank/dynamic at runtime — mirror the arcade's
palette writes per frame, don't quantize offline.

## 2. CPU port: 68000 → SA-1 (65816)
### 2a. Settle the semantics first (`TRANSPILER_DESIGN.md`)
- **D1 — condition codes:** carry is INVERTED on subtract/compare (68K C=borrow,
  65816 C=no-borrow) → swap BCC/BCS for sub-derived carry; identical for add.
  `tst;ble` clears V → lowers to `beq/bmi`. 65816 CMP doesn't set V → signed
  compares need `SEC;SBC`. Every branch is suspect until the harness proves it.
- **D2 — registers:** 68K 32-bit Dn/An live in direct page (SA-1 fast path);
  32-bit ops = multi-precision sequences. Don't alias A7 to hardware S.
- **D3 — endianness:** byte-swap data at conversion time; manifest every table.
- **D4 — address map:** translate every 68K EA through one table; never let a raw
  68K address reach output. (Superman: `$B00000/$D00000/$E00000/$F00000` — confirm
  per game from the MAME driver; docs lie.)
### 2b. Prove it on a spike before bulk work (gate G2)
Pick ONE pure leaf, hand-transpile it, and run a **differential harness**:
1. **MAME goldens** — `mame` MCP `capture_leaf_io` injects test inputs via a read
   tap at the function's fixed-address read and records output+regs+CCR. MAME is
   the oracle (no self-reference).
2. **SNES side** — patch the transpiled bytes into the loaded ROM via Mesen
   `write_memory(snesPrgRom,…)` (survives `reset_emulator` → iterate with NO
   relaunch), drive inputs through WRAM, read outputs.
3. Compare. Iterate until green across vectors incl. signed/edge cases.
Superman: `$412` (RNG) and `$24D98` (timer/clamp) both green. See `SPIKE_RESULT.md`.
Tip: process a batch ONCE then halt — a forever-loop re-applies in-place edits.

## 3. Disassembly coverage (gate G1): the trace IS the CDL
Static disassembly stalls on indirect/computed jumps (jump tables = hazard H6).
The execution trace resolves them by observation.
1. **Trace** 68K execution headlessly: `mame ... -debug -debugger none
   -autoboot_script trace68k.lua` (the debugger `trace` command logs PC+disasm;
   loops auto-compact).
2. **`tools/build_cdl.py`** turns traces into a CDL: confirmed code + exact
   instruction lengths (from consecutive PCs — no static length decoder needed) +
   **resolved indirect-jump targets**. Game-agnostic via `CDL_ROM=…`.
3. **Drive state diversity** — coverage = states reached: scripted scenarios
   (`trace68k_scenario.lua`: attract/combat/pause/death/highscore), the service
   menu (Service-Mode DIP), and especially a **full playthrough** (§4).
4. **Expand** with Peony recursive descent from the CDL seeds (fills whole
   functions). `tools/measure_coverage.py` reports reliable code vs data bytes.
Superman: 10.2% confirmed (zero false positives), 779 jump tables resolved,
35,047 descent blocks. See `COVERAGE_G1.md`.

## 4. Reaching deep states: input-movie playback
Blind scripted input can't beat a game; isolated execution crashes stock MAME.
The reliable way to trace late levels/boss/ending:
- Record a human playthrough **in the SAME MAME version you trace with** (e.g.
  `tools/mame-trace/record_play.sh`, MAME 0.287) → faithful playback, no desync.
- Cross-version recordings (e.g. Twin Galaxies .inp from old MAME) DESYNC but
  still reach new levels — useful, partial.
- Playback + windowed trace: `pb_trace_multi.lua` (env TOTAL/NWIN/WINLEN) over
  `-playback <inp>` (path is relative to `-input_directory`, not cwd).
- `mameInpFileTools` (github luxocrates) can *author/convert* .inp from an input
  log if you have a TAS/longplay but no GUI recording.

## 5. Audio (YM2610 → SNES/TAD)
Use the `vgm-to-tad-mml` skill: YM2610 VGM rips → Terrific Audio Driver MML +
ADPCM-A decode. FM is rendered to samples (TAD is sample-based). See `CONVERTSOUND.md`.

## 6. Protection (C-Chip etc.)
Analyze the protocol from the MAME driver; patch out checks or emulate via a
mailbox/state machine on the SA-1. See `RISK_CCHIP.md`, `CCHIP_FIRMWARE.md`.

---

## Super-scaler games (OutRun / Space Harrier) — what actually works
From Chad's SA-1 OutRun port (corrects the naive "SNES can't scale → impossible"):
- **Bake sprite ladders, don't scale at runtime.** ROM is cheap now; pre-render
  every zoom step of every sprite into ROM. This beats runtime scaling outright.
- **SA-1 CC Type 2 is NOT useful for this** — it's a blitter (great for SCUMM-style
  bitmap pushes), too costly per-sprite-per-frame for scaling. Ladders win.
- **SA-1's real job is the road / per-scanline 3D math** — chew the scanline table
  (curve, crest, width, the second/fork road) while the 5A22 **races the beam**.
- **Roads = HDMA line-scroll** (per-scanline H-scroll + palette for rumble stripes).
  **Mode 7 with per-line matrix did NOT look right for a road** — use HDMA.
So the constraint isn't "can it scale?" but "ROM budget for ladders + can SA-1
grind the road math in time + can you race the beam."

## 📌 Pinned next target: Space Harrier
Looks tractable with the above: checkerboard **floor → Mode 7**, enemies/obstacles
→ **baked sprite ladders**, SA-1 for the per-scanline floor/scaling math. Never got
a faithful SNES port. Revisit after Superman's toolchain is battle-tested.

---

## Starting a NEW game port — checklist
1. Confirm tractability: 68000 (or simpler) + tile/sprite, moderate sprite counts,
   color depth that fits 15-bit/16-per-palette, no *required* hardware scaling
   (or budget ladders). Super-scalers OK per the recipe above.
2. Get the ROM + MAME driver; build the address map from the driver (don't trust docs).
3. Graphics: §1 decode→reproduce→diff loop.
4. CPU: §2 settle D1–D4, then a leaf spike + differential harness.
5. Coverage: §3 trace-driven CDL + §4 a faithful playthrough recording.
6. Audio §5, protection §6 in parallel.
Reusable as-is across games: the `mame`/`mesen` MCP loops, `trace68k.lua`,
`build_cdl.py` (`CDL_ROM=`), `measure_coverage.py`, `capture_leaf_io`, the playback
infra. Game-specific (swap addresses/fields): the scenario injections and the
$F0xxxx work-RAM references. See `tools/README.md`.
