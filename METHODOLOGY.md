# Arcade → SNES Port Playbook

Last updated: June 25, 2026. How we ported (are porting) Superman (Taito X, 68000) to
SNES/SA-1, written so the same recipe + tools apply to the **next** game (pinned: Gigandes
— see §"Pinned next target"; Space Harrier was dropped). Superman is the worked example; the
method is general. Companion: per-area docs
(`PALETTE_VERDICT.md`, `TRANSPILER_DESIGN.md`, `INTERPRETER_SPIKE.md`,
`TRANSPILER_TOOL_SCOPE.md`, `COVERAGE_G1.md`) and `STATUS.md`/`ROADMAP.md`.

**The core method, proven end-to-end on Superman:** *interpret-cold / transpile-hot.* Build a
complete 68000 **interpreter** in 65816 that runs the original ROM correctly on the SA-1; validate
it **bit-exact vs MAME**; then replace only the per-frame **hot** functions with native 65816 via an
**automated transpiler**, leaving the interpreter as the fallback for cold code. This sidesteps the
two traps of a naive port: a pure interpreter is ~2,000× too slow, and a full static recompile of a
512KB ROM (with computed jumps, self-modifying tables, protection) is infeasible *and* unverifiable.
The interpreter and the transpiler are the two big reusable assets — both are largely game-agnostic.

## 0a. Before debugging anything: the tribal-knowledge reference
`docs/INTERP_DEBUG_AND_GOTCHAS.md` — the interpreter's diagnostic-build debug interface (PC-ring
flight recorder, PC-freeze, halt codes, register-file map), the Poppy assembler traps
(silent `.org` overlap, A8 mode-inference resets, cross-file symbol landmines), emulator-
harness operational gotchas, and the coroutine-scheduler IRQ contract. Every item there
cost real time to learn; all of it transfers to the next port.

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
### 2b. De-risk with a leaf spike (gate G2, historical first step)
Before committing to the interpreter, prove the lowering on ONE pure leaf: hand-transpile it,
capture **MAME goldens** (`mame` MCP `capture_leaf_io` taps the function's fixed-address read,
records output+regs+CCR — no self-reference), patch the bytes into the loaded ROM (Mesen
`write_memory(snesPrgRom,…)`, survives `reset_emulator`), and diff. Superman: `$412` (RNG) and
`$24D98` (timer/clamp) green (`SPIKE_RESULT.md`). This validates D1–D4; it does NOT scale to a
512KB ROM. The spike is the precursor to the interpreter, not the product.

### 2c. Build the INTERPRETER (the cold side — the main reusable asset)
Write a 68000 interpreter in 65816 (`src/interp.pasm`): the 68K reg file in direct page (D2),
work RAM in BW-RAM, opcodes fetched big-endian from the ROM image, every EA through one engine.
This is what actually runs the game; it's a complete, reusable MC68000, not a Superman subset.
Validate it two ways:
- **`tools/opsweep.py`** — a SA-1-aware generated **op × addressing-mode sweep** vs MAME (full
  state diff per opcode). Superman gate: **782/782**. (Replaces the old `optest`.) This is your
  per-opcode correctness net.
- **Frame-boundary LOCK-STEP differential** — inject MAME's real 68K state, run ONE game-frame in
  the interpreter, diff work RAM vs MAME. This is the decisive harness: it caught **4 opcode bugs
  the op-sweep missed** (relative-branch bank carry; `movem.l (d16,An)` load+store; `lea (xxx).W`).
  Run it on busy attract AND deep gameplay states.
The interpreter boots the real ROM through its scheduler, protection handshake, and init, reaching
the live per-frame loop — bit-exact vs MAME (modulo the unmodeled sound CPU). For a new game, the
opcode core is unchanged; you swap the **address map + I/O handlers** (work-RAM bank, video-bank
routing, protection mailbox, input).

### 2d. Transpile the HOT path with the TOOL (interpret-cold / transpile-hot)
The interpreter alone is far too slow (~2,000×). Make it realtime by replacing only the functions
that dominate each frame with native 65816 "escapes," via the **automated transpiler**:
1. **PC-hook** intercepts a hooked 68K call (`jsr.l`/`jsr(An)`/`bsr`) and jumps to the native
   `entry_<addr>`, which ends `jmp inext` (never touches the 68K stack). One table entry per escape.
2. **`tools/transpile.py <addr>`** capstone-decodes the function and emits the escape on the reg
   file: full EA matrix, the D1 signed-branch lowering, `link`/`movem` (incl. the `movem.w`
   sign-extension), byte/word/long, shifts, `moveq`, `dbra`. Two extension paths:
   - **call-bridge** (non-leaf): each `jsr`/`bsr` hands back to the interpreter via a `$00FF:cont`
     sentinel return; the callee runs interpreted; `op_rts_sentinel` resumes the native code.
   - **`--video`**: non-frame stores route through the IO-aware writer to the video shadow.
3. **Validate each escape** by the fresh-adjacent-tick **lockstep** (`flyval.py`/`val_*`): inject one
   MAME game-tick, run hook-ON (native) vs OFF (interpreted), require the **live** state identical
   (classify stack diffs vs `a7` — bridge sentinels below SP are dead; diff the video shadow for
   `--video`). Pick targets with `tools/stream_profile.py` (the in-game hot-function profile).
4. **Deploy** the escape in free **bank-$00 gaps** (no ROM-layout change needed for the foreseeable
   hot set). Grind the ranked hot set until the per-frame path fits the realtime cycle budget (G3).
Superman: 8 escapes live incl. the ~12.6% collision (bridged) and ~5.9% video (shadow stores).
*(escape counts here are dated phase snapshots — "deployed" ≠ "fires in gameplay"; do not treat
as a current total. See `MAIN_PLANNING_HANDOFF.md` for the authoritative current set.)*
See `TRANSPILER_TOOL_SCOPE.md` + the `transpiler-tool`/`bulk-transpile-phase` memories.

**Evolution (AOT) — when per-escape hand-deployment stops scaling.** Hand-escaping one cluster at a
time tops out because *dispatch*, not transpilation, becomes the wall: each cluster needs a bespoke
hook to catch how its control transfer (jmp/rts/rte/coroutine) is reached. The fix is **one global
68K-PC→native dispatch table** that all control flow consults (hit → native, miss → interpret),
then **batch-transpile the CDL block list** through it, demoting the interpreter to a cold fallback.
Per-escape hooks collapse into one table lookup; coverage *composes* instead of fighting back. Key
pieces (Superman, `aot-dispatch-table` memory): `tools/gen_xlat_table.py` (offline 2-level page table
→ a free SA-1 bank), `xlat_dispatch` (one indirection; route every dispatch site through it),
`transpile.py --table` (faithful link/unlk/rts, no re-sim push, for table dispatch at a materialized
boundary). Caveats learned: the table FORCES real dispatch, which exposes latent escapes the hooks
silently never exercised (great — but plan for it); a function reached via multiple paths can have
different stack frames; and validating table-dispatched faithful escapes needs SA-1-side trace
tooling, which is the real gate to batch coverage. See `ROADMAP.md` (June-29 update) + STATUS.md.

**(corrected 2026-06-30, verified via SA-1 exec-hooks):** of the dispatch families, **jah2**
(jsr/bsr/jsr(An)), **jmp-state** (jmp(a0)→table), and **coroutine** (rte-resume→table) FIRE in
gameplay; the **rts-class table dispatch FIRES 0×** — the hot rts-reached handlers ($CE4/$13BE)
are entered via the scheduler's rte→rts chain that BYPASSES the table, so the `ce4t` table entry
is dead weight (the earlier "ce4t fires 63451×" was a corrupted $07xx in-memory-counter artifact;
NEVER trust $07xx counters — use exec-hooks). So *dispatch* is no longer the wall: the real
bottleneck is the **coroutine scheduler + handler chains** (~1900 genuinely-interpreted 68K instr
per GAME_TICK). Latest escapes: `entry_c172` (first coroutine escape, via `--coroutine` +
rte-resume) and `lh_sched` (hand-written native scheduler scan via `loop_hook`, not transpiled).
See `MAIN_PLANNING_HANDOFF.md` (authoritative).

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

## 📌 Pinned next target: Gigandes (decided 2026-06-29)
**Gigandes** (Taito, 1989) is the next port after Superman — chosen specifically to **harden the
AOT transpiler** on a second real game. It runs on **Taito-X hardware, the SAME family as Superman**,
so the entire §2 CPU toolchain transfers *directly*: the MC68000 interpreter, `transpile.py` + the
**AOT dispatch table** (§2d evolution), opsweep/optest gates, the lock-step/`val_frame_diff`
differentials, and the §3 trace-driven CDL coverage pipeline. A different code corpus stresses the
transpiler/dispatch coverage in ways one title can't — that's the point. The §1 graphics path is
single-screen 2D (not super-scaler), so it reuses the Superman decode-→reproduce-→diff recipe too.
Sequencing: finish Superman first (the AOT build-out), then start Gigandes on the hardened toolchain.

**Space Harrier is DROPPED** as the next target (was the prior pick): it runs **dual 68000s** (main +
sub), making the port overly ambitious for now. The super-scaler / Mode-7-floor + baked-sprite-ladder
recipe above stays valid reference for a possible later super-scaler title, just not the immediate one.
See the `gigandes-target` memory.

---

## Starting a NEW game port — checklist
1. Confirm tractability: 68000 (or simpler) + tile/sprite, moderate sprite counts,
   color depth that fits 15-bit/16-per-palette, no *required* hardware scaling
   (or budget ladders). Super-scalers OK per the recipe above.
2. Get the ROM + MAME driver; build the **address map from the driver** (don't trust docs).
3. Graphics: §1 decode→reproduce→diff loop.
4. CPU: §2a settle D1–D4 → §2b a leaf spike to de-risk the lowering → **§2c bring up the
   interpreter** (swap the address map + I/O handlers; validate `opsweep` + lock-step vs MAME)
   → **§2d transpile the hot path** with `transpile.py`, validate each escape, deploy in gaps.
5. Coverage: §3 trace-driven CDL + §4 a faithful playthrough recording (informs the hot set; the
   hybrid does NOT need ≥85% coverage — the interpreter is the cold fallback).
6. Audio §5, protection §6 in parallel.

### What's reusable (audit)
**Game-agnostic, reuse as-is:**
- The two oracle loops — **`mame`/`mesen` MCP servers** (point `MAME_SYSTEM`/`MAME_ROMPATH` + ROM).
- **`src/interp.pasm`** — a *complete MC68000 interpreter*. The opcode core + EA engine + exception
  model are general; only the address map (`map_snes`), I/O handlers (protection, video routing,
  input), and the SA-1 boot glue are game-specific.
- **`tools/transpile.py`** — the codegen core (EA matrix, D1 lowering, call-bridge, `--video`) is
  general; the reg-file/work-RAM/`$41`-shadow addresses are *our SA-1 convention*, not the game's,
  so they carry over. New games may need new opcodes added on demand (the tool fails loud).
- **`tools/opsweep.py`** (interpreter correctness sweep), the **lock-step harness** (inject-and-diff
  vs MAME), **`tools/stream_profile.py`** (hot-set profiler), the fresh-adjacent-tick **`flyval`**
  escape validator, the escape-in-bank-gap deploy recipe.
- **`build_cdl.py`** (`CDL_ROM=`), `measure_coverage.py`, `trace68k.lua`, `capture_leaf_io`, the
  `.inp` playback infra.

**Game-specific, swap per game:** the address map + work-RAM/video-bank references; the I/O handlers
(C-Chip → another game's protection; X1-001 video → the new chip's draw model — e.g. Space Harrier
is a super-scaler, see above, NOT X1-001); the scenario/input injections; the graphics decode. See
`tools/README.md` for the per-tool reuse legend.
