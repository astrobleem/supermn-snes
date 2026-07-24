# Superman (Taito X System) → SNES / SA-1

A port of the 1988 Taito arcade game **Superman** (Motorola 68000 CPU, X1-001/X1-002
video, YM2610 + C-Chip) to the **Super Nintendo with the SA-1** coprocessor.

The strategy is a **interpret-cold / transpile-hot hybrid**: a hand-written 68000
interpreter (in 65816 assembly) boots and runs the original game logic on real SNES
hardware, while hot paths are migrated to native 65816 over time. Every component is
validated **differentially against ground truth** — MAME for the arcade side, a real
SNES PPU (via Nexen) for the target side.

> ## Production status (July 23, 2026) — v132 playtest response, not playable
>
> The first real v105 user playtest invalidated its **playable** label: the formal 30 Hz timing
> result was genuine, but a bad `$012B6C` HLE return broke player attacks and enemy offense, and
> the recognizable soundtrack is audibly incomplete. Exact v124 repaired those demonstrated
> combat paths, but the next playtest found that releasing a held Button 1 energy charge froze it.
> v127 repaired the silently overwritten `$D3B0` handler. v128 then repaired the tester's exact
> Mesen 2.1.1 title flicker, pre-round bars, charged-shot, and music-replacement regressions; the
> tester has now human-confirmed all four of those focused repairs.
>
> That same playtest exposed a first-wall mixed-tile freeze and over-transposed instrument samples.
> v130 repaired that wall corruption, added five octave anchors, and added a rotating Mode 7 boot
> screen. Its second human test rejected it before the wall: crate throw and a charged shot killing
> a silver enemy froze, Superman showed wrong animation tiles, the view was cropped from the
> upper-left, and the rotation caused dizziness.
>
> The next human run rejected that v131 response too: crate throw still froze, Superman
> disappeared at the visible right edge, and the title words were incoherent. Exact v132
> response-candidate SHA-256:
> `48d7c4d6c6a431e8c2066410e325888d70aec9d15b7261903ddc4f8effd476a2`.
>
> v132 fixes a Poppy mode-inference error at generated `$023342` continuation `br23342_1`: an
> intended 16-bit immediate had consumed the following `$85` opcode, then executed `$40` as `RTI`
> and jumped to zero in the crate path. The repaired task root passes 18/18 focused MAME/Nexen
> cases, and an exact-Mesen replay advances past the old tick-1,288 freeze through tick 1,480 with
> halt zero and valid task stacks. It also restores X1-001's wrapped raw-X `$100-$13F` interval,
> visibly retaining Superman at the far-right crop boundary.
>
> The arcade title's six legal rows use 149 OBJ records, exceeding both SNES frame and scanline
> limits. A signature-gated BG2 overlay now renders those glyphs while leaving 97 logo/artwork
> objects in OAM. A final-ROM stock-Mesen-2.1.1 run from power-on shows all six lines coherent
> across frames 5,680-5,740 with ticks and renders advancing. A continuation from that same-ROM
> title state accepts held Select/Start, removes the overlay, and reaches the pre-round Superman
> sequence at tick 681 with halt zero and eight valid initialized task stacks. This is bounded
> title/input/transition evidence, not a gameplay or performance run; a mirror-refresh
> packed-render diagnostic is red 7/8 because its first sample is stale. v132 carries v130's sound
> data unchanged, so the timbre report remains open.
>
> No new rate is inferred from those smoke/checkpoint tests. v124's clean-power-on window remains
> the latest formal measurement: **1,783 game ticks in 3,602 SNES frames = 29.7002 game-fps** at
> **360,990.164 cycles/tick**. That misses the explicit 30 Hz / 358K gates, and the inherited
> burst-render gate is also red. The title, crate, and right edge need a human v132 cold-boot
> retest; the first wall, exact silver-enemy event, timbre, full stage/playthrough, and formal
> performance remain open. The honest status is **interactive technical demo, not playable or
> shippable**. See [RECOVERY.md](RECOVERY.md) R12,
> [the focused handoff](docs/handoff/V132_TITLE_CRATE_RIGHT_EDGE_20260723.md), and
> [CONFESSION.md](CONFESSION.md).
>
> Playtest controls: **Select** = coin, **Start** = start, **B/Y** = arcade Button 1
> (punch/fire), **A/X** = arcade Button 2 (jump). The arcade game has no separate kick input.
>
> **R4 (sound truth) closed July 19**: two interpreter fast-path bank bugs — silently
> killing *every* organic sound trigger since the beginning — were found and fixed
> (`ea_extw` RAM-PC ext-word fetch; `op_cmpw_d16_dn` ROM-operand read). A single
> no-injection production cold boot now produces the complete arcade organic command
> chain: boot verbs, attract music at the arcade-correct moment, coin jingles, and the
> round-start `$32`+`$06`×3 burst 51 ticks after START — arcade parity. Canonical ROM
> SHA-256 `31c5dff4…` (reproducible at commit `4034f1e`). Full narrative:
> `build/recovery-20260712/r4-sound-truth/R4_REPORT.md` (evidence dir is local-only).

> ⚠️ **No copyrighted ROM data is included.** This repository contains only original
> source, tooling, and documentation. You must supply your own legally-obtained
> Superman arcade ROM set to build or run anything. See [Building](#building).

## Where things stand

| Area | State |
|---|---|
| **68000 interpreter** | ✅ **Complete legal MC68000 instruction set** — bit-exact vs MAME on attract + active gameplay (lock-step diff), runs on the **SA-1**, boots Superman + renders video + reads input on real SNES. Retained current-line correctness gates **opsweep 782/782 + optest 160/160**. |
| Graphics pipeline | ⚠️ v132 retains the centered 384x240 crop's wrapped right edge, moves the over-capacity title text to BG2, keeps the supplied boot logo static, and inherits displayed-slot quarantine; focused title/right-edge evidence is green, but human confirmation, the inherited 568/600 burst-render result with 31 coalesces, and aligned MAME pixel fidelity remain open |
| **Transpiler (automated tool)** | ✅ **`tools/transpile.py`** — 68K→65816, validated bit-exact; **call-bridge** (non-leaf) + **`--video`** (shadow stores) + inlined BW-RAM access |
| **Bulk game-logic port** | ⬆ **underway (automated)** — **~25 escapes deployed** (18 in the SA-1 escape bank + bank-$00 gaps), covering **~40%** of the real per-frame work; incl. the ~12.6% collision (bridged) and ~5.9% video. *(Phase snapshot — these counts conflate "deployed in the bank" with "actually fires in gameplay" and are superseded by [MAIN_PLANNING_HANDOFF.md](MAIN_PLANNING_HANDOFF.md); the live bottleneck is the coroutine scheduler + handler chains, not dispatch coverage.)* |
| **30 Hz playability budget** | ❌ **not cleared by the latest formal run (v124)** — power-on gameplay window is **29.7002 game-fps / 360,990.164 mean SA-1 cycles/tick**; v132 has no new formal rate result and inherits the red burst-render gate |
| C-Chip boot handshake | ✅ solved via patch + input mailbox + download replay (no MCU emulation) |
| Disassembly coverage (G1) | ⬆ trace-driven CDL pipeline; full playthrough trace (not a hybrid blocker) |
| Audio (YM2610 → SNES TAD) | ⚠️ **organic transport works; musical fidelity is unconfirmed** — v132 carries v130's `$19` repair and five first-stage octave anchors unchanged; ARAM is byte-exact and the organic capture has no ≥200 ms silence, but the timbres need listening and ignored enemy SFX, placeholder SFX, trimmed samples, and untranscribed pitch/LFO/portamento remain |

See **[CONFESSION.md](CONFESSION.md)** for the authoritative correction and
**[RECOVERY.md](RECOVERY.md)** for the active recovery campaign. `STATUS.md` and
`ROADMAP.md` retain useful historical evidence but are not authoritative where they conflict.

## The 68000 interpreter

`src/interp.pasm` is a hand-written 65816 interpreter that executes real 68000
opcodes on a real SNES (validated in Nexen against MAME as the arcade oracle).
It now implements the **complete legal MC68000 instruction set** — not just the
subset Superman happens to use — so it is reusable for future arcade→SNES ports.

- 68000 registers live in the 65816 direct page; on the SA-1, work RAM (`$F0xxxx`)
  maps to BW-RAM bank `$40` (video shadow in `$41`); opcodes are fetched big-endian
  from the ROM image at `$C10000+PC`.
- New/generic ops route through a shared effective-address (EA) engine; the
  original game-path handlers are left untouched.
- Exceptions (TRAP, divide-by-zero → vec 5, CHK → vec 6, TRAPV → vec 7,
  ILLEGAL → vec 4) push correct stack frames and vector through the ROM table.

**Validated against MAME** by two single-instruction gates — `tools/opsweep.py`
(op×addressing-mode grid, **782/782**) and `tools/optest.py` (curated per-opcode
vectors vs MAME, **160/160**) — plus a frame-boundary **lock-step differential** harness
(inject MAME's 68K state, run a game-frame, diff work RAM — this caught 4 opcode bugs the
op sweep missed). The hot path is then migrated to native 65816 by **`tools/transpile.py`**,
each escape checked bit-exact against the interpreter (and the hottest against MAME
ground truth directly via `tools/val_cc10_mame.py`). See
**[INTERPRETER_SPIKE.md](INTERPRETER_SPIKE.md)** and **[TRANSPILER_TOOL_SCOPE.md](TRANSPILER_TOOL_SCOPE.md)**.

## Key documents

- **[CONFESSION.md](CONFESSION.md)** — highest-authority correction to project status
- **[RECOVERY.md](RECOVERY.md)** — active consolidation and baseline campaign
- **[docs/PROFILE_CAMPAIGN.md](docs/PROFILE_CAMPAIGN.md)** — native/render campaign and historical
  R6 timing evidence
- **[docs/handoff/V132_TITLE_CRATE_RIGHT_EDGE_20260723.md](docs/handoff/V132_TITLE_CRATE_RIGHT_EDGE_20260723.md)**
  — exact v132 title-capacity, crate-continuation, wrapped-right, and remaining playtest scope
- **[docs/handoff/V130_SECOND_PLAYTEST_20260723.md](docs/handoff/V130_SECOND_PLAYTEST_20260723.md)**
  — historical exact-v131 static-logo, initial centered-crop, displayed-cache, and rejection context
- **[docs/handoff/FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md](docs/handoff/FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md)**
  — historical exact-v130 wall-context, octave-audio, rotating Mode 7 boot, and cold-boot evidence
- **[docs/handoff/MESEN211_PLAYTEST_REGRESSIONS_20260723.md](docs/handoff/MESEN211_PLAYTEST_REGRESSIONS_20260723.md)**
  — historical v128 exact-Mesen title/transition/audio/charge evidence and residual render-debt verdict
- **[docs/R5_PERFORMANCE_ARCHITECTURE.md](docs/R5_PERFORMANCE_ARCHITECTURE.md)** — historical
  continuous profile and the two rejected pre-R6 pacing labs
- **[STATUS.md](STATUS.md)** — detailed historical state (superseded where noted)
- **[ROADMAP.md](ROADMAP.md)** — next steps and milestones
- **[BUILD.md](BUILD.md)** — toolchain (the "Game Garden" suite: Poppy/Peony), dependencies, and **migration guide**
- **[METHODOLOGY.md](METHODOLOGY.md)** — the reusable arcade→SNES recipe
- **[TRANSPILER_DESIGN.md](TRANSPILER_DESIGN.md)** — 68K→SA-1 lowering decisions
- **[INTERPRETER_SPIKE.md](INTERPRETER_SPIKE.md)** — interpreter design & validation
- **[PALETTE_VERDICT.md](PALETTE_VERDICT.md)** — graphics path validation
- **[CCHIP_BOOT_HANDSHAKE.md](CCHIP_BOOT_HANDSHAKE.md)** / **[CCHIP_FIRMWARE.md](CCHIP_FIRMWARE.md)** — C-Chip resolution
- **[tools/README.md](tools/README.md)** — tool reuse guide

## Building

> Requires a legally-obtained Superman arcade ROM set (not distributed here).

1. Place the ROM set where the tools expect it (extract the 68K image to
   `data/superman_m68k.bin`; see `tools/build_interp_rom.py`).
2. Toolchain: Poppy, Python 3, MAME 0.287 (arcade oracle), and the MCP-enabled Nexen
   fork with the shared `mesen_mcp` Python client (SNES/SA-1/PPU validation).
3. Build the interpreter ROM:
   ```sh
   bash tools/build_interp.sh      # assembles src/interp.pasm -> build/interp.sfc
   ```
4. Run the interpreter regression gates (need MAME + Nexen MCP running):
   ```sh
   python3 tools/opsweep.py        # SA-1-aware op×addressing-mode grid vs MAME (782/782)
   python3 tools/optest.py         # curated per-opcode vectors vs MAME (160/160)
   ```
5. Transpile a hot 68K function to a native escape:
   ```sh
   python3 tools/transpile.py 025110            # -> a native entry_25110 escape (.pasm)
   python3 tools/transpile.py 0020e8 --video    # video function (shadow stores)
   ```

## Repository layout

```
src/        65816 source (interp.pasm = the 68000 interpreter; main, spikes)
tools/      build scripts, the optest harness, trace/CDL pipeline, analysis
tools/sound/  YM2610 VGM -> SNES (TAD/MML) conversion
data/       extracted assets (gitignored — derived from the arcade ROM)
build/      build outputs (gitignored)
*.md        design notes, risk docs, verdicts, status
```

## Handoff (July 19, 2026)

This section is the complete picture for anyone (including a future maintainer or
agent) picking the project up.

### What you have

- **Canonical branch**: `main` (= the `recovery/canonicalize-20260712` line). Canonical
  ROM: `build/interp.sfc`, SHA-256 `31c5dff4e7364f1dfd867e284798c5af5688e90cbe22fa69bc29bba249eed438`,
  reproducible via `bash tools/build_interp.sh` at commit `4034f1e` (R0 provenance in
  [RECOVERY.md](RECOVERY.md)). Pre-recovery tips are preserved as local `archive/*` refs.
- **A complete, oracle-validated MC68000 interpreter** on the SA-1 (opsweep 782/782,
  optest 160/160, lock-step differentials), ~25 validated native escapes, a working
  transpiler, and the full validation harness suite (`tools/README.md`).
- **Working demo**: boots the real game from the real 68K reset vector, renders, takes
  input, plays music organically, runs gameplay — at ~1.3 game-fps.
- **Oracles**: MAME 0.287 (arcade) and the MCP-enabled Nexen fork (SNES/SA-1/PPU).
  Emulator-harness tribal knowledge: [docs/INTERP_DEBUG_AND_GOTCHAS.md](docs/INTERP_DEBUG_AND_GOTCHAS.md)
  — read it first; every item in it cost hours-to-days.

### What is settled (do not re-litigate without new evidence)

- **30/60 fps is out of reach for this architecture** — R5's verdict
  ([docs/R5_PERFORMANCE_ARCHITECTURE.md](docs/R5_PERFORMANCE_ARCHITECTURE.md)): the idle
  clamp protects a real producer/consumer ordering contract; both faster pacing designs
  derail deterministically. The credible (unproven) path to realtime is contiguous
  AOT/HLE compilation of whole call trees, a ground-up campaign (~2.7× ISA floor).
- **C-Chip**: solved via boot patch + input mailbox; no MCU emulation needed.
- **Sound architecture**: 68K single-byte triggers → SA-1 ring copy → 5A22 TAD/SPC.
  Organic path verified end-to-end on the canonical ROM (R4).

### Open items, in priority order

1. **By-ear music sign-off** (owner: Chad): listening pairs in
   `build/recovery-20260712/r4-sound-truth/{arcade-ref,snes-tracks}/` and the organic
   session WAV in `.../organic-fixed3/`. Classification table in `R4_REPORT.md` §4.
2. **rc_copy boot-hardcode decision**: `src/video.pasm` still hardcodes
   `Tad_LoadSong(1)` at power-on (predates the organic path; arcade is silent until
   ~13 s). Removing it is a one-liner + rebuild + one organic re-check.
3. **F4-class sibling audit**: `op_movb_d16_dn`, the cmpi-`(d16,An)` family, and any
   other `$400000,x` fast-path READ whose An can hold a ROM pointer (two bugs of this
   class each silently corrupted the game for months — see the gotchas doc, "FAST-PATH
   DATA reads" section, which includes the forensic recipe that cracks them).
4. **Crash-freedom soak**: the `$AC=$2000` clamp has long soak evidence but no proof;
   an hours-long armed free-run on the release ROM would harden the demo claim.
5. **Same-state MAME graphics fidelity**: still an open validation (the pre-recovery
   reference capture was lost); needs a fresh MAME state transplant + pixel diff.
6. **SFX authoring** (optional content phase): the arcade SFX vocabulary (`$1b–$7f`)
   is mapped but unauthored; only 2 placeholder SFX exist.
7. **Real-hardware test** (optional): the demo targets emulators; FXPak/SA-1 hardware
   has never been tried.

### The next port

The toolchain (interpreter core, transpiler, harnesses, methodology) is deliberately
game-agnostic. The pinned next target is **Gigandes** (Taito X, same 68K architecture) —
see [METHODOLOGY.md](METHODOLOGY.md) for the reusable recipe and the gotchas doc for
everything that transfers.

## License / legal

Original source and documentation in this repository are the author's own work.
The Superman arcade game and its ROM/graphics/audio data are property of their
respective rights holders and are **not** included or distributed here. This is a
preservation / reverse-engineering project for interoperability and education.
