# AGENTS.md — Superman SNES engineering guide

This repository ports Taito's 68000-based Superman arcade game to SNES/SA-1 with an
interpret-cold / native-hot architecture. Treat it as a reverse-engineering project with two
independent oracles: MAME 0.287 for arcade truth and the MCP-enabled Nexen fork for SNES truth.

## Read this first

Project-state documents conflict. Use this precedence order:

1. `CONFESSION.md` — highest-authority correction to optimistic status claims. Treat its July 12
   accounting as the baseline. Only a later dated `RECOVERY.md` result that explicitly supersedes
   an individual claim can replace it; otherwise, where documents conflict, believe the confession.
   It was recovered from the old `sound-p3` worktree during repository consolidation.
2. `RECOVERY.md` — the active canonicalization and evidence ledger. Its dated R0-R8 results
   supersede the older campaign projections they explicitly close.
3. The newest branch/worktree-specific handoff and evidence (`docs/PROFILE_CAMPAIGN.md`,
   `MAIN_PLANNING_HANDOFF.md`, `supersoundhandoff.md`, and focused `docs/handoff/*`).
4. `STATUS.md` and `README.md` — current summary layers, but defer to the evidence ledgers above
   whenever their playable, performance, rendering, or sound wording drifts.
5. Older plans and risk documents — design/history only when superseded by later verdicts.

Before changing code, also read `BUILD.md`, `METHODOLOGY.md`, `tools/README.md`, and the focused
design document for the subsystem being touched. The interpreter debugging reference is
`docs/INTERP_DEBUG_AND_GOTCHAS.md`.

The historical recovery base was `origin/main` at the PR #15 merge (`73f1839` when consolidation
started); the completed recovery line subsequently became `main`. The previous local tips were
preserved under `archive/*-pre-recovery-20260712`, including the old stash tip. Inspect `git status`,
branches, worktrees, refs, and the current `RECOVERY.md` before choosing a base rather than trusting
an old handoff's branch name. Never merge, rebase, delete branches, or switch away from user work
without explicit instruction.

## Honest project state

- The port is interactive in controlled tests, but it is not playable or shippable. R6's exact
  v105 ROM did clear the formal 30 Hz cadence/budget test, but the first real user playtest found
  that player attacks and enemy offense were broken. The **playable** label is superseded; retain
  v105 only as historical performance/scheduler/renderer evidence.
- The combat root cause was the `$012B6C` HLE hardcoding return PC `$01177C` for a function with 34
  real BSR callers. Exact v124 ROM SHA-256
  `777507c9ecba8b7911dae882ea266cca7d173d918dde65b73f880acdb0451352` propagates the real return
  PC. It passes 35/35 focused MAME cases and 4/4 live combat-spine differentials; Button 1 visibly
  attacks, Button 2 visibly jumps, and an 800-frame idle check activates enemy attacks and changes
  health from 20 to 18 (two points of damage).
- Exact v124 also freezes when a charged Button 1 shot is released. Its `$00D3B0` native handler
  flowed from `$92:EFFB` across a later `.org $F000` island, which silently replaced 201 bytes.
  Exact v127 candidate SHA-256
  `1a8a5742536b6142a42387546524bb0e785fac508a01e6ff5e5c53027b06db35` relocates the complete
  body to audited `$94:B400` space. Real-controller 96/120/180-frame holds are green through up to
  1,200 frames after release, with continued ticks/renders, halt zero, and intact stack floors.
  A fresh `TESTFLAG=0` smoke organically arms production and reaches gameplay. This is focused
  charged-shot/cold-boot-reachability evidence, not a new FPS result or human-confirmed playability.
- v124's formal power-on production window recorded **1,783 game ticks in 3,602 SNES video
  frames = 29.700167 game-fps**, at **360,990.164 SA-1 cycles/tick**. It ended at tick 2,210 with
  halt zero, task mask `$FFF1`, 14 initialized task stacks, a 138-byte minimum margin, valid real
  input/sound ring, no renderer queue overflow, and progress in the final frame. It misses the
  30 Hz gate by 0.299833 fps and the 358K budget by 2,990.164 cycles/tick, so call it a stable
  near-30 Hz technical demo, never a playable candidate.
- R7 tested and rejected two tempting `$26A0` shortcuts. v125 and v126 passed their 10/10 exact
  differentials and checkpoint soaks, then halted `$DEAD` during formal power-on runs with 1,753
  and 604 frames of lost progress. Both are removed. The performance harness now requires recent
  tick/render progress and rejects derailed execution rather than trusting stale totals.
- The July 12 recovery ROM's **1.3237 game-fps after production arming** and roughly 8.10M SA-1
  cycles/tick remain the correct historical baseline for that ROM. Older 3-10x or 8-15 fps
  projections remain invalid because they measured partial injected windows and excluded
  end-to-end work.
- R5's negative scheduler result remains valid history: its NMI/WAI and supervisor-wake labs
  failed the producer-ordering event at ticks 765-767. The retained v124 architecture keeps the
  R6 paced scheduler/renderer ownership design and survives through tick 2,210, but its whole
  production tick still misses the explicit rate and cycle gates.
- The legal MC68000 interpreter and shipped native escapes have strong differential evidence:
  current-v127 optest 160/160, opsweep 782/782, plus focused MAME and Nexen differentials are real.
  This is still not proof of every whole-program address-space path; R4's bank-assumption bugs
  remain the warning against promoting focused vectors into universal correctness.
- A settled production-cold-boot Nexen capture renders the recognizable level background, HUD,
  player, and enemies while rendering continues through the formal run. Exact aligned MAME pixel
  fidelity remains open; visual plausibility alone is not the fidelity oracle.
- The TAD sound port is merged upstream and its data/blob paths are byte- and oracle-validated.
  R4 proved the organic boot, attract, coin, and round-start command chain, but the real user
  playtest reports audible cutting-out. A current organic capture shows no TAD stop/reload/drop or
  200 ms digital silence; the likely audible causes are incomplete transcription, trimmed samples,
  ignored enemy SFX IDs, placeholder SFX, and missing pitch/LFO/portamento work. It has not passed
  by-ear musical validation.
- The `$0818` `$AC=$2000` clamp remains the gate-off fallback. The organically armed production
  path uses the paced scheduler above; neither path proves a full playthrough crash-free.
- C-Chip work is genuinely resolved for the observed game contract: deterministic boot replay,
  status gate, and input mailbox. Read `CCHIP_BOOT_HANDSHAKE.md` and `CCHIP_FIRMWARE.md`.

Do not describe a lab interaction as playable, a byte match as listened-to audio, an injected
tick cost as end-to-end fps, or an old reference capture as current behavior.

## Performance and completion evidence contract

The word `fps` is reserved for an end-to-end production measurement. A credible performance claim
must identify the source commit and ROM hash; start from power-on with `TESTFLAG=0`; prove the
production gates armed organically; use the real input mailbox; validate the game-tick counter
against the actual `$0818` boundary hook; measure against emulated SNES video time; include waits,
IRQs, rendering, and state transitions; and retain the raw log. Otherwise report only the local
span in cycles and label it injected, checkpointed, isolated, or lab as appropriate.

- A same-run local speedup is evidence about that span only. Do not multiply it into a projected
  project fps or call it progress toward realtime until the production cold-boot gate is rerun.
- Save-state interaction, forced gates, mailbox-triggered audio, and short isolated ticks can prove
  specific behavior. None of them proves playability, stability, or end-to-end speed.
- Any pacing or scheduler replacement must survive the known gameplay ordering event beyond ticks
  765-767 with halt, PC, task mask, sound ring, gate values, and every initialized task-stack floor
  checked. A short green soak is not enough.
- The 30 Hz gate is a representative whole gameplay tick at or below 358K SA-1 cycles with pacing
  and rendering included. v124 survives the ordering gate but misses both the rate and cycle
  thresholds. A credible future candidate must clear those formal gates and then pass an actual
  human combat/audio playtest before the word **playable** is restored.

## Repository and private inputs

- `src/interp.pasm`: 68000 interpreter and bank-$00 dispatch/debug machinery.
- `src/escbank*.pasm`: native/HLE escape banks.
- `src/video.pasm`: 5A22 video supervisor and render path.
- `tools/`: build, differential, profiling, transpilation, and trace harnesses.
- `soundwork/tad/`: TAD port, projects, generated audio blob, and musical notes.
- `data/`, `build/`, and parts of `src/*.bin`: generated or private-derived artifacts.

Never commit or redistribute arcade ROM material. Preserve `/home/chad/superman-arcade/` and the
derived, gitignored inputs unless the user explicitly asks to regenerate them:

- `data/superman_m68k.bin` (512 KiB)
- `tools/mame-trace/gfx1.bin` (2 MiB)
- `data/cchip_boot_response.bin` (256 bytes)

Generated outputs and captures may be valuable evidence. Do not delete or overwrite them casually.

## Toolchain on this host

- .NET 8: `/home/chad/.dotnet8` (legacy Mesen build and the Python client package)
- .NET 10: `/home/chad/.dotnet10` (Nexen, Poppy, Peony, Pansy)
- Poppy: `/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll`
- Peony: `/home/chad/peony/src/Peony.Cli/bin/Release/net10.0/Peony.Cli.dll`
- Pansy source: `/home/chad/pansy`
- Nexen MCP fork (project oracle, healthy-volume R5 build):
  `/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen`
- Older Mesen MCP checkout (legacy/compatibility): `/home/chad/Mesen2/bin/linux-x64/Release/Mesen`
- `mesen_mcp`: `/home/chad/Mesen2/python`
- MAME: `/snap/bin/mame`, pinned to 0.287
- MAME MCP: `/home/chad/mame-mcp`
- TAD compiler: `/home/chad/terrific-audio-driver/target/release/tad-compiler`
- Python 3 with Capstone M68K support

The global Codex MCP registrations should be `mame` and `nexen-inproc`. Nexen uses the project
shim `tools/nexen_mcp_bridge.py`; its transport still reads the historical `MESEN_*` environment
variable names. Legacy Mesen needs `DOTNET_ROOT=/home/chad/.dotnet8`; Nexen harnesses use .NET 10
or the self-contained publish above. The original `/home/chad/Nexen` checkout is preserved but
has a damaged git pack/source object from the failing system drive; do not build or profile from it.

## Working rules

- Do not build just to orient or inspect. Building rewrites gitignored binaries and ROM outputs.
- When implementation is requested, use the documented build path (`bash tools/build_interp.sh`)
  and validate in proportion to the touched risk. Never claim success from assembly alone.
- MAME is the 68000/game-behavior oracle; Nexen is the SNES/SA-1/PPU oracle. Prefer differential
  evidence over visual plausibility or emulator-only reasoning.
- Measure native escape firing with SA-1 execution hooks at the actual execution bank. Escape-bank
  bodies execute at `$92+`; a bare bank-$00 HOOKTEST can falsely report zero. Calibrate with a
  known-firing same-bank hook.
- Do not trust `$07xx` IRAM counters unless their ownership was proven; game state can overwrite
  them. The diagnostic PC ring is at IRAM `$0400-$05FF`, pointer `$48`, but production ROM packing
  NOPs its per-fetch calls. Build with `PC_RING=1 bash tools/build_interp.sh` only when the recorder
  or PC-freeze is required; that instrumented ROM is not valid for production performance claims.
- Pause Nexen before coherent multi-read inspection. Use fresh ports after wedged runs. Long scripts
  may need `socket_timeout=120` and background execution with output polling.
- MAME Lua taps must be retained in globals. Snap MAME cannot read `.claude` paths; keep runnable
  trace scripts/artifacts under the project. Use `SDL_VIDEODRIVER=dummy` for headless MAME.
- Never use `pkill -f mame`; it can kill the invoking shell. Target an exact process only after
  inspecting it.

## Assembly and layout hazards

- Poppy silently permits `.org` overlap; later sections overwrite earlier bytes. Audit every seam
  after layout changes and keep the ROM-pack assertions green.
- Do not insert code casually into the middle of `interp.pasm`: long branches can wrap silently and
  bank-$00 is tightly packed. Prefer escape banks or size-neutral stubs.
- Poppy mode inference can reset at labels after returns. Add explicit `.a8`/`.a16` and `.i16` where
  required, and byte-audit immediates.
- Use explicit long-bank calls/jumps across escape banks. Grep all `.pasm` files for hardcoded
  addresses after relocating an interpreter label; cross-file constants do not relocate.
- Work RAM is big-endian from the emulated 68K's perspective. Preserve CCR/X semantics, stack
  residue, return conventions, and observable register side effects. The transpiler must fail loud
  on unsupported semantics rather than emit plausible code.
- The coroutine scheduler has tiny task stacks and an IRQ-density contract. Do not accelerate IRQ
  delivery or alter `$AC` pacing without proving stack floors, producer/consumer order, and sustained
  cold-boot behavior.

## Validation expectations

Choose gates based on the change, but state exactly which ran and what they prove:

- Interpreter semantics: `tools/opsweep.py` and focused opcode tests against MAME.
- Escape/transpiler changes: prove the native hook fires, gate-off behavior is unchanged, and
  lockstep/full-diff adds no live divergence in representative light and combat states.
- Bank/layout changes: assemble, audit bank seams/overlaps, cold-boot smoke, then relevant lockstep.
- Rendering changes: use a fresh boot when the NAT/save state strands the 5A22 supervisor; inspect
  shadow data and PPU state as well as screenshots.
- Performance changes: same-run cycle deltas for local spans, plus an end-to-end cold-boot wall-time
  measurement before making playability/fps claims.
- Sound changes: compiler/ARAM checks and byte oracles are necessary but not sufficient; capture and
  listen by ear against the arcade reference before calling it musically validated.

Record negative results and failed assumptions. This project has repeatedly lost time when a partial
measurement was promoted into a project-level verdict.

## Documentation hygiene

When work changes project truth, update the focused evidence document and add a short correction to
the visible handoff/status layer. Preserve historical sections, but mark them superseded rather than
silently rewriting the record. If a new result conflicts with `CONFESSION.md`, reconcile it with
fresh evidence and update the confession-level truth explicitly.
