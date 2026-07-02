# Superman (Taito X) → SNES/SA-1 — Project Status

Last updated: June 29, 2026. Per-area detail lives in the linked docs.

> **UPDATE 2026-07-01 — rts-class dispatch is RESOLVED; a transpiler flag bug was found + fixed.**
> The "rts-class dispatch fires 0×" blocker below is superseded: a bank-$00 `jsr choke_tramp` FETCH-
> CHOKEPOINT at the interpreter's `lh_off` routes the about-to-decode PC through the AOT table, so
> rts/branch-reached hot handlers dispatch natively regardless of reach. `$0CE4` (entry_ce4t) — the
> hottest cluster — now dispatches **bit-exact** (all 6 ce4 triples + 20-tick self-diff). An every-
> fetch cross-bank `jml` round-trip is FATAL; the bank-$00 `jsr`/`rts` trampoline is the fix. This
> exposed + fixed a **transpiler D1 gap**: escapes never wrote the 68K CCR memory an interp-caller
> reads after `rts` (stale flags → the trip1000 divergence); `transpile.py` now materializes the CCR at
> branch-to-exit edges (`emit_ccr_native`). ce4t regenerated from the fixed transpiler. Strategic
> picture UNCHANGED (still 24× over budget; codegen is the wall — the chokepoint is a dispatch enabler +
> correctness fix, not the 24×-closer). See [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) top
> block + memory `fetch-chokepoint-rts-escape`.

> **UPDATE 2026-07-01 (pt.4) — Phase-2 Campaign 2 COMPLETE: heavy-tick background loops shipped `5aea367`.**
> ALLSTREAM profile gate found 62% of the heavy tick's remaining interp = the $0008FA block-copy +
> the $0FB8 fill's **IRQ-slice mid-loop resume at $0FD2** (a NEW reach class: ISR-exit rte lands at a
> mid-loop PC — only the fetch-chokepoint catches it). entry_8fat + entry_fd2t shipped via choke_tramp
> arms (zero-shift). All gates GREEN (0 LIVE ×3 triples; MAME GREEN ×3; ESC=1 unchanged). **Heavy tick
> 12.3M → 6.35M cyc (−48%, ~70× → ~35× budget); moderate −14%; quiet noise.** Transpiler gap found
> (dbra-fallthrough CCR; hand-patched, proper fix TODO). See MAIN_PLANNING_HANDOFF.md pt.6 block.

> **UPDATE 2026-07-01 (pt.3) — Phase-2 Campaign 1 COMPLETE: scheduler SWITCH-IN shipped `2e39b98`.**
> `entry_swin` ($0796→movem-restore→rte, escbank $FB00 + swo_tramp arm) deployed & fully validated:
> gate-off bit-identical; single-tick vs MAME GREEN ×3 triples; 20-tick SP-aware self-diff 0 LIVE ×3;
> bit27 wake-up path closed synthetically (`tools/synth_swin_b27.py`); composition CHOKE+SWIN GREEN
> (heavy 12.78M→9.87M cyc). **Model correction:** the "19–28 restores/tick" below was a 2× sched_trace
> WINDOW artifact (trap never fires ⇒ ~2-tick stream) — true rate 11/4/1 per tick (mod/heavy/quiet),
> measured win ~0.5M cyc/tick (~6%) moderate. See the top of
> [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) + memory `scheduler-switchin-shipped`.

> **UPDATE 2026-07-01 (pt.2) — chokepoint generalized ($13BE, shipped `a013dee`); Phase-2 plan APPROVED.**
> Reconciled activity-spectrum budget (bit-exact): per-tick cost is scene-dependent 2.7M(quiet)..12.6M
> (heavy combat) cyc — worst-case ~70× budget. Measured-cost gate picked the first Phase-2 campaign:
> **native scheduler SWITCH-IN** (~19–28 restores/tick, ~0.9–1.5M cyc/tick), rejecting the structurally-
> tempting-but-COLD ce58 call-tree (0× measured). **NEXT ACTION: execute
> `/home/chad/.claude/plans/yes-please-enter-plan-splendid-brooks.md`** (self-contained, cost-confirmed;
> start at task #10). See the [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) "IMMEDIATE NEXT ACTION".

> **UPDATE 2026-06-30 — read [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md) for the
> authoritative current state.** Two things below are now CORRECTED:
> - **rts-class table dispatch fires 0× in gameplay** (verified with SA-1 exec-hooks). The "rts
>   class unified bit-exact / ce4t fires 63451×" claim was a corrupted `$07xx`-counter artifact;
>   `ce4t` never runs. Hot handlers ($CE4/$13BE) are reached via the scheduler's rte→rts chain,
>   which bypasses the table. Only the **jmp-state** and **coroutine (rte-resume)** classes fire.
> - The bottleneck is the **coroutine scheduler**, not dispatch. This session: shipped `entry_c172`
>   (first COROUTINE escape, table 12→13) and `lh_sched` (native scheduler disabled-task-skip via
>   loop_hook) — interpreted gameplay cost dropped ~125/tick ($0740 region 246→121). The `$AC`
>   frame-charge question (#73) is resolved (esc_ac_charge works; residual $1401 is vblank timing,
>   not $AC). See the handoff §1 + the `scheduler-escape-loophook` / `coroutine-shells-low-value`
>   / `rts-class-dispatch-nonfunctional` memories.

> **UPDATE 2026-06-30 (pt.3):** the scheduler is now understood as a coroutine CONTEXT-SWITCHER —
> `lh_sched` only collapsed the `$074C` scan; the switch-IN/OUT machinery is **~30% of the tick** and
> is the biggest collapsible lever (`tools/sched_trace.py`). A native switch-OUT was built — **body
> PROVEN bit-exact** but a ~44-byte integration divergence is unpinned, so it's **reverted (build is
> GREEN)**. STRATEGIC: the SA-1 cycle meter shows we're **24x over the 60fps budget** and **codegen
> (not coverage) is the wall** — see handoff §0. New single-yield differential toolchain + memories
> `scheduler-context-switch-lever` / `cycle-budget-realtime-gap`.

> **The engine is named Cambium** — the graft-union layer where rootstock and scion fuse. It is
> the whole graft system: the 68K **interpreter rootstock** (`src/interp.pasm`) + the transpiled
> native **scions** (escbank/escbank2, `tools/transpile.py`) + **the global AOT dispatch table that
> unites them** (`xlat_dispatch`). The name points at the dispatch union — that, not the codegen, is
> the crown jewel. Cambium belongs to the Game Garden botanical family (Poppy/Peony).

## CURRENT STATE (June 29) — DIRECTIONAL PIVOT to AOT; one dispatch table replaces per-target hooks; PoC proven

The project changes gear from **hand-escaping one hot cluster at a time** to **ahead-of-time
(AOT) transpilation**. The realization (forced by the per-cluster grind — see the `$D5A0` saga
below): the transpiler already produces bit-exact native code per function; the *one* hard,
recurring problem is **dispatch** — every hot cluster turned into a multi-hour hunt for how its
control transfer (jmp/rts/rte/coroutine) is reached, with a bespoke hook per case. AOT flips it:
build **ONE global 68K-PC→native-entry table** that all control flow consults (hit → run native,
miss → interpret). That converts "every dispatch is a custom hunt" into "one indirection," and is
the single piece that makes coverage *compose* instead of fighting back. The interpreter is
demoted from engine to cold-path fallback. Everything we'd been doing with hooks is a hand-rolled,
per-case version of that table.

- **Dispatch-table PoC — PROVEN bit-exact** (`val_frame_diff` GREEN; 3 escapes across 3 pages).
  The machinery, all reusing existing tools:
  - `tools/gen_xlat_table.py` builds a 2-level page table (page[PC>>8] → 256-entry sub-table of
    3-byte native addrs; 0 = miss) offline from the escape banks' `.sym` + the `transpiled from`
    comments. Placed at file `$2B0000` = **SA-1 `$96:8000`** (free MMC-window bank, verified
    live-readable by the executing CPU, not just the debugger).
  - `xlat_dispatch` (escbank2 `$94:F900`) indexes it; `ojmp_hook` now `jml`s there instead of its
    hardcoded cmp-chain → `ojmp_disp` re-scan. HIT → dispatch native, MISS → `jml inext`.
  - Two gotchas burned in: `jml [abs]` is **Poppy-mis-sized** (tracks 2 / emits 3 → branches land
    on a `BRK` → hang); use **push PBR + push (lo16−1) + RTL** instead. And diagnose dispatch hangs
    with a DIAG build that computes-but-always-misses (records to scratch, never jumps).
- **The table earns its keep immediately — it exposed a latent escape interaction.** Routing
  *real* dispatch through the table surfaced that `entry_d386`/`entry_d3b0` (`$D3` jmp-state
  handlers) each run bit-exact ALONE but **diverge when co-dispatched alongside `entry_d0d0`** — a
  shared `$D0`-`$D3` state-machine interaction the old per-target cmp-chain silently never
  exercised (it never co-dispatched them; cf. the vacuous-GREEN `$D5A0` had). Excluded from the
  table (→ interpreted, bit-exact) pending a separate debug. This is the AOT thesis in action.
- **`$D5A0` closed (the pivot's trigger).** An 8-instr leaf reached only by `bra` *inside* the
  already-escaped `$D5C4` handler (NOT a jmp-table target — the ojmp approach was structurally
  wrong); `entry_d5c4` was bailing to the interpreter at that branch. Fixed by `jml entry_d5a0`.
  Bit-exact. The hours this took (5 min to transpile, the rest dispatch archaeology) is the
  argument for the table.
- **NEXT (the AOT build-out, in order):** (1) convention-unify so the jsr/coroutine classes share
  one table (the jmp-state class is convention-uniform today); (2) move the lookup to the **`inext`
  chokepoint** — one edit catches every transfer, convention-free, and is cheap precisely because
  the interp is demoted; (3) scale bank allocation to `$80`-`$9F` (~20+ banks for full coverage);
  (4) batch-transpile from the CDL block list (`g1-coverage`); (5) build a **divergence-bisection**
  harness (first divergent block) to validate at scale; (6) debug the `d0d0`/`$D3` interaction.
  See `aot-dispatch-table` memory + task #70.

## CURRENT STATE (June 27) — realtime budget MEASURED; ~25 escapes deployed; both gates green

Bulk transpilation continued, and the **realtime budget is now measured** — the decisive
go/no-go number the project hinged on. Headline: **the per-frame game logic is only ~2,400
68K-instructions**, not the 28,672 IRQ-pacing countdown, so the SA-1 budget closes at full
native coverage with headroom. Playable (incl. 60fps) is realistic; the remaining work is
bounded — transpile the per-frame hot path toward ~99% native coverage.

- **Frame budget (measured, one gameplay frame; `f450n.tr` + `analyze_trace68k.py`).** Of
  ~13,000 68K-instr/frame, **~82% is the `$0818` idle spin** (the 68K spinning until the vblank
  IRQ); **real game logic is only ~2,391 instr/frame**. At full native (~18 cyc/instr transpiler
  codegen) that's ~43K SA-1 cycles vs the ~178K/frame budget — **~4× headroom, 60fps fits**. The
  deployed escapes cover **~40%** of real per-frame work; **~18 functions cover 99%** (→60fps).
  It's a coverage *cliff*: the interpreted tail dominates until ~99% (the interp measured
  ~16,500 cyc/instr, ~4× the old estimate). Tools: `tools/measure_fps.py`, `tools/onon_capture.py`.
- **`$0818` idle-spin COLLAPSED** (`loop_hook`): detect the spin → fire the vblank IRQ immediately
  instead of interpreting ~26K dead spins/frame (~10× faster). Measured game-fps now **0.27
  (escapes off) / 0.40 (escapes on)**, up from sub-0.05. Real 60Hz pacing comes from the 5A22-side
  vblank, not this wait.
- **~25 escapes wired** (was 8). The **escape bank** (ROM file `$290000` = SA-1 `$92:8000`) is a
  2nd executable SA-1 bank (32KB free) holding **18 transpiler escapes** (`transpile.py --bank1`);
  plus the bank-$00-gap escapes (`$025110` bridged collision, `$0020e8` video, the `entry_ce4`/
  `entry_111a` hand oracles, and leaves). The "bank-$00-full" problem is solved — multi-bank is no
  longer a blocker. See `escape-bank` memory.
- **Transpiler hardened + faster.** Fixed `move.l` with memory EAs and **`sub`-to-memory writeback**
  (it was emitted as a flagless `cmp` — a real bug a frame-sharing list-walker exposed). New
  **memory-access inlining**: `$40` BW-RAM ops inline `lda $400000,x` instead of a `jsl` helper call
  (−26 SA-1 cycles/op), applied to all 18 escape-bank escapes (verified behavior-preserving via
  ON-vs-ON `onon_capture`).
- **New validation — escape-vs-MAME ground truth** (`tools/val_cc10_mame.py` + `extract_exit.py`):
  inject a MAME-captured entry frame on the deterministic native base, run the escape to the trap,
  diff its work RAM against MAME's exit. Bypasses the non-deterministic synthetic-jsr OFF reference.
  (Gotcha: capture a leaf's exit at the RETURN address, not its `rts` — MAME read-taps are
  prefetch-stale and miss the last store.)
- **Both interp gates GREEN: `opsweep` 782/782** (op×EA grid) **+ `optest` 154/154** (curated
  per-opcode vs MAME). optest was ported to the SA-1 memory model (`Sa1Memory`/`snesMemory`) — the
  earlier "optest deprecated" note is RETIRED.
- **NEXT** = transpile the named hot functions toward 99% per-frame coverage (path to playable):
  `$003A92` (the GAME_TICK dispatcher, ~15 indirect-jump sites/frame), `$001008`, `$00158E`,
  `$0008C2`, `$004A9E`, `$00C9F8`. ~6 → ~90% (~10fps); ~12 more → 99% (60fps). See `ROADMAP.md`.

## CURRENT STATE (June 25) — superseded by the June 27 state above; transpiler AUTOMATED, bulk transpilation underway

The interpret-cold/transpile-hot hybrid is now a **working production pipeline**, not just a
mechanism. An **automated 68K→65816 transpiler** (`tools/transpile.py`) replaces hand work, and
the hottest gameplay functions are transpiled to native 65816 and **deployed in the live ROM**.

- **Transpiler tool — BUILT + validated bit-exact.** Capstone-decodes a 68K function and emits a
  native escape (`entry_<addr>`) operating on the interpreter's DP register file. It reproduces
  the hand-written, MAME-validated oracles `entry_ce4`/`entry_111a` byte-for-behavior (flyval
  ON-vs-OFF=0). Codegen covers the full EA matrix, the signed-branch lowering (D1), `link`/`movem`
  (incl. the `movem.w` sign-extension), byte/word/long ops, shifts, `moveq`, `dbra`, and two
  extension paths:
  - **Call-bridge** (non-leaf functions): each `jsr`/`bsr` hands control back to the interpreter
    via a `$00FF:cont` sentinel return (`op_rts_sentinel` resumes the native continuation); the
    callee runs interpreted. Validated end-to-end.
  - **`--video`**: non-frame stores route through `writeword`/`writebyte` → the `$41` video shadow
    (`$B0/$D0/$E0`), `$40` for work RAM. Validated by diffing the shadow, not just work RAM.
- **Hot functions transpiled + deployed** (all bit-exact vs the MAME-validated interpreter, all in
  free **bank-$00 gaps** — no ROM-layout change needed):
  | escape | 68K fn | ~%frame | kind |
  |---|---|---|---|
  | `entry412` | `$000412` | RNG | leaf |
  | `entry_cb9e`/`entry_15b4`/`entry_3e6a` | sprite pos / block copy / classifier | — | leaf |
  | `entry_ce4` | `$000CE4` | ~12.5% | hottest in-game (sprite/object builder) |
  | `entry_111a` | `$00111A` | ~5.9% | 2-stream sprite builder |
  | **`entry_25110`** | `$025110` | **~12.6%** | collision detect — **2 bridged `jsr.l`** |
  | **`entry_20e8`** | `$0020e8` | **~5.9%** | video render — **`$41` shadow stores** |
- **Validation harness:** the fresh-adjacent-tick lockstep pipeline (`flyval.py`/`val_*` +
  `record_playthrough.sh`/`extract_flytick.py`) injects one MAME game-tick, runs it hook-ON
  (native) vs OFF (interpreted), and requires the live state to match. KEY refinements this phase:
  classify diffs vs the stack pointer (bridge sentinels below `a7` are dead, not a bug); compare
  the `$41` video shadow for video functions.
- **Profiler** (`tools/stream_profile.py`) ranks the real in-game hot set from the interpreter's
  per-frame PC stream (MAME can't reach gameplay under `-debug`). Used to pick `$025110`/`$0020e8`.
- **Key finding:** the **multi-bank interpreter is NOT needed** — bank $00 has ~6.7KB of free
  gaps; the unoptimized escapes deploy there. (A multi-bank attempt is documented as superseded.)
- **NEXT = keep transpiling the hot set toward the G3 cycle budget** (realtime) + measure it.

<details><summary>Earlier CURRENT STATE (June 24) — superseded by the above</summary>
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
</details>

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
`gfx1` `$C9:0000`–`$E8` · video subsystem `$E9:8000` (file `$298000`) · **escape bank**
`$92:8000` (file `$290000`, 2nd executable SA-1 bank holding the transpiler escapes).

## Workstream status

| Area | State | Evidence / doc |
|---|---|---|
| **Graphics pipeline** | ✅ validated on real SNES PPU vs MAME | `PALETTE_VERDICT.md` |
| **Transpiler design (D1–D4)** | ✅ settled | `TRANSPILER_DESIGN.md` |
| **Transpiler spike (gate G2)** | ✅ GREEN — 2 functions differentially verified | `SPIKE_RESULT.md` |
| **68K interpreter** | ✅ **BIT-EXACT vs MAME** on busy attract + active gameplay (lock-step diff; 4 opcode bugs fixed). Runs on the **SA-1**. Correctness gates **opsweep 782/782 + optest 154/154** (`tools/opsweep.py` op×EA grid + `tools/optest.py` per-opcode vs MAME — both SA-1-correct). Clears the **C-Chip boot handshake** (replay, not emulation). | `INTERPRETER_SPIKE.md`, `lockstep-harness-progress` memory |
| **Phase A — SA-1** | ✅ **DONE** — cart runs on SA-1 (work RAM in BW-RAM `$40`, shadow `$41`, dual-CPU video). | `sa1-bringup` memory |
| **Phase B — native-escape hook** | ✅ **DONE** — PC-hook routes hooked 68K calls (jsr.l / jsr(An) / bsr) to native 65816; `$412` RNG native, bit-identical. Profiler + save-state + speedup harness. Foundation hardened (leak fixed, `leaf_check.py`, FOUNDATION CONTRACT). | `TRANSPILER_DESIGN.md` §D5 |
| **Transpiler TOOL (automated)** | ✅ **BUILT + validated** — `tools/transpile.py` emits native escapes from 68K functions; reproduces the hand oracles bit-exact. Call-bridge (non-leaf) + `--video` (shadow stores). | `TRANSPILER_TOOL_SCOPE.md`, `transpiler-tool` memory |
| **Video plumbing** | ✅ **COMPLETE** — 68K video-bank writes → `$7E` shadow → real PPU each game-frame. Palette byte-exact, tile decode 128/128, OBJ+BG render the correct arcade frame; OBJ/BG tile dedup, cross-frame BG cache, vblank-safe DMA. Render subsystem in ROM bank `$E9` (`src/video.pasm`). | `VIDEO_PLUMBING.md` |
| **Disassembly coverage (gate G1)** | ⬆ in progress — reliable pipeline + full playthrough | `COVERAGE_G1.md` |
| **Tooling (MAME/Mesen MCP, trace/CDL)** | ✅ built & validated | below |
| **C-Chip** | ✅ SOLVED — patch + input mailbox + **boot handshake replay**, still **no MCU emulation** | `CCHIP_BOOT_HANDSHAKE.md`, `CCHIP_FIRMWARE.md` |
| **Audio (YM2610→TAD)** | 🔬 analyzed; `vgm-to-tad-mml` skill exists | `CONVERTSOUND.md`, `SOUNDHARDWARE.md` |
| **Bulk transpilation (native escapes)** | ⬆ **UNDERWAY (automated)** — **~25 escapes live**: 18 in the **escape bank** (`$92:8000`, file `$290000`) + bank-$00 gaps; incl. the ~12.6% collision (bridged), ~5.9% video (shadow), a list-walker. **~40% of real per-frame work covered**; ~18 functions → 99%. The interpreter is the cold-path fallback. | `escape-bank` / `transpiler-tool` / `bulk-transpile-phase` memory |

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
- **G3 — cycle budget <150k/frame:** ⬆ **MEASURED** — real per-frame work is only ~2,391
  68K-instr (the $0818 spin is collapsed); ~43K SA-1 cyc at full native coverage (well under the
  178K/frame budget). ~40% covered now → ~0.4 game-fps; path to 99% (60fps) mapped. Not yet *met*
  (needs the hot-set transpiled), but the budget provably closes.
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
The cold side (interpreter) and the hot side (automated transpiler + bridge + video
codegen) are both built and validated. The remaining work is **throughput** — transpile
enough of the per-frame hot path to hit the realtime cycle budget. Detailed plan in
**[ROADMAP.md](ROADMAP.md)**. In short, in priority order:
1. **Keep transpiling the hot set** — the profiler (`stream_profile.py`) ranks the
   remaining in-game hot functions ($0028d4 video, $00267a, the $025xxx cluster
   siblings, etc.). Transpile each (`transpile.py [--video]`), deploy in a bank-$00 gap,
   validate ON-vs-OFF=0 (a7-classify stack diffs; diff `$41` for video). Mechanical now.
2. **Measure G3 (cycle budget <150k SA-1 cycles/frame).** With the hot mass native,
   benchmark steps/frame and the SA-1 cycle count; decide if the cold interpreter tail
   needs a faster dispatch or more transpilation to reach realtime. Then realtime IRQ
   pacing (cycle-aware `$AC`).
3. **Watch bank-$00 space** — ~6.7KB of gaps, partially consumed. As more functions
   land, either a transpiler code-size pass (An-addr caching; non-frame reads are ~6
   instrs each) or revisit a 2nd executable bank (see `multibank-interp` memory).
4. **Audio (YM2610→TAD)** in parallel; then **integration** — full playable ROM,
   full-level validation vs MAME, G1 coverage + G4 manifest as needed.
