# G1 — Disassembly Coverage (trace-driven CDL)

Date: June 17, 2026

> **Historical gate correction:** the original
> [transpiler risk study](../history/risks/TRANSPILER.md) proposed ≥85% coverage
> before bulk transpilation. That is not a current hybrid-architecture gate: the
> interpreter safely carries cold code. Trace-driven CDL remains valuable for reliable
> boundaries, computed targets, caller inventory, scenarios, and hot-path selection.

## Approach: the trace IS the CDL

A MAME execution trace is a *dynamic disassembler*: every line is a confirmed
code address, and consecutive executed PCs reveal exact instruction lengths (no
error-prone static 68K length decoder needed). Crucially, the trace records where
**indirect/computed jumps actually went** — the jump tables (`jmp (a0)`, computed
dispatch) that defeat static disassembly and are *the* reason coverage was stuck
(hazard H6). Those observed targets become reliable seeds.

Pipeline:
1. `tools/mame-trace/trace68k.lua` / `trace68k_play.lua` — headless 68K traces
   (boot/attract + gameplay with coin/start/movement injection).
2. `tools/build_cdl.py` — turns traces into a CDL: confirmed code instructions +
   byte-accurate lengths + **resolved indirect-jump targets**. Reliable: marks only
   executed code, no heuristic false positives.
3. Merge trace seeds with the vector-table handlers → `data/merged.cdl`.
4. Peony recursive descent from those seeds fills in whole functions
   (`--platform m68000 --cdl merged.cdl`).

## Results

| | blocks | code identified | ROM classified | jump tables |
|---|---|---|---|---|
| Baseline (`final_disasm.pasm`) | 483 | 17.3 KB (3.4%) | 4.0% | unresolved (H6) |
| Trace-driven (this work) | **14,372** | **223 KB (43.6%)** | **67.5%** | **231 resolved** |

Feeding the trace-driven CDL (confirmed code + resolved jump tables) to Peony's
recursive descent took identified code from **3.4% → 43.6%** (~13×) and total ROM
classification from 4% → 67.5%. (Measured with `tools/measure_coverage.py`, which
counts real instructions vs `.db`/`dc.w`/`???` data per emitted line.)

Honest caveat on the 43.6%: recursive descent occasionally wanders into data
(e.g. ASCII text `0x2020` decoded as `move.l -(a0),d0`), so 43.6% is an *upper*
estimate of code; the trace-confirmed 3.8% is the zero-false-positive lower bound.
True code coverage sits between, toward the upper end since descent is seeded by
real execution. Reaching a confident 85% means executing more of the code (more
states) so more of it is trace-confirmed rather than descent-inferred.

- **Pure execution coverage** (100% reliable lower bound) grew monotonically with
  game-state diversity:
  - 3 traces (boot/attract + gameplay): 3,720 instr / 2.5% / 146 jump targets
  - +4 states (deeper attract, vertical/jump combat, pause, idle-death→game-over→continue): 5,828 / 3.8% / 231
  - +2 states (**full attract cycle**, **high-score initials entry**): **6,432 instr / 4.3% / 255 jump targets**
- **Indirect jmp/jsr targets resolved: 146 → 255** as new states executed new
  dispatch code — the H6 blocker, resolved by observation. Each new game state
  adds confirmed code + new jump targets (monotonic).

### State coverage (the screens that normal play never hits)
- **Attract cycle** ✅ (title / demo / high-score table / story) — long no-coin trace.
- **High-score initials entry** ✅ (die → game-over → enter initials; up/down/button) — fresh NVRAM so the score qualifies.
- **Death / game-over / continue** ✅ (idle-death scenario).
- **Endgame / ending / boss / late levels** ❌ not reachable by blind scripted input.
  Needs either a recorded **input movie** (MAME `-record`/`-playback` of a human
  playthrough → deterministic, traces every state) or a **save state** parked at
  the target. Save-state primitives work (`save_state.lua` saves, `trace_from_state.lua`
  loads); the load+trace-in-one-debug-session has a notifier glitch, so the clean
  path is input-movie playback or a caller-provided state.
- Feeding trace seeds + jump-table targets to Peony's recursive descent yields
  **14,372 disassembled blocks vs 483** — a ~30× expansion, driven reliably by
  real execution rather than a linear sweep (the old baseline mis-disassembled
  data as code, e.g. `move.b d0,d0` over the vector table).

## What it takes to reach 85%

The limiter is **game-state diversity**: gameplay revisits the same main-loop code,
so the executed-PC set plateaus (~2.5%) without reaching new states. Each new state
(more levels, boss, menus, death, continue) executes new code → new seeds → more
jump tables resolved → more descent coverage. The pipeline is in place and
monotonic: every additional trace only adds confirmed code. Reaching 85% is a
matter of driving the game through more states (longer scripted input / save-state
seeding), not new tooling.

## Tools
- `tools/build_cdl.py` — trace → CDL (+ jump-table resolution).
- `tools/measure_coverage.py` — reliable code vs data byte coverage of a .pasm.
- `data/traced.cdl`, `data/merged.cdl`, `data/traced_lengths.json`.

### Update — Twin Galaxies .inp recordings (player playthroughs)
Two MAME .inp high-score recordings (`62559` MAME 0.185, `86488`/score 2,000,600
MAME 0.193) were played back + traced. They DESYNC in 0.287 (recorded on older
MAME → input/timing mismatch; the 2M run dies at ~17.5k on a later level), but
even desynced they reach **new levels my scripted traces never hit**:
- + both playbacks: **9,803 confirmed instr / 6.6% / 418 jump targets**
  (from 6,432 / 4.3% / 255 — a +52% / +64% jump).

A *fresh* recording made in 0.287 (`tools/mame-trace/record_play.sh`) will play
back faithfully (same version) all the way to the ending → full-run coverage.

### Update — full player playthrough + service menu (the breakthrough)
A complete beat-the-game recording made IN MAME 0.287 (`inp/superman_play.inp`,
131,376 frames / ~36 min: full game → ending → 2nd game → death → game-over) plays
back FAITHFULLY (99%, no desync — same version). Traced 20 windows across it.
Plus the service/test menu (DIP "Service Mode" on). Accumulated 46 traces:

| stage | confirmed instr | % ROM | jump tables resolved |
|---|---|---|---|
| scripted states only | 6,432 | 4.3% | 255 |
| + Twin Galaxies recordings (desynced) | 9,803 | 6.6% | 418 |
| + full player playthrough | 14,980 | 10.1% | 765 |
| + service/test menu | **15,148** | **10.2%** | **779** |

10.2% is the zero-false-positive floor (literally executed). Peony descent from the
765-target merged CDL expanded to **35,047 blocks** (vs 14,372 / 483 baseline).
Levels covered: brick street, aerial-city, canyon, green-hills, Clark-Kent story
scenes, ending, 2nd-game/game-over, service menu.

Service menu entry: DIP "Service Mode" On + reset (MAME: Tab→Dip Switches, or set
the field via Lua).

### Peony output-writer limitation (record so we don't re-run it)
The full 35,047-block descent (765-target merged CDL) **analyzes fine but cannot
be serialized** — both `--format poppy` and `--format asm` writes were killed by
timeout (>40 min, truncated). Peony's output writer is single-threaded and scales
badly with block count. So the reportable measured descent figure stays the
14,372-block run: **43.6% code / 67.5% ROM classified**. The full run is necessarily
higher (35k vs 14k blocks; CDL input classifies 64.4%) but is unmeasurable via
Peony today. Reliable executed floor (writer-independent): **10.2% / 779 jump
tables** from `build_cdl.py`. Fix belongs upstream (Peony writer perf), not here.
