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
2. `RECOVERY.md` — the active canonicalization and evidence ledger. Its dated R0-R6 results
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

- The exact R6 v105 production candidate is **playable at the project's 30 Hz gate**, but it is
  not shippable and has not completed a full-game playthrough or real-hardware qualification. Its
  ROM SHA-256 is `72d925ac1817965f62ebcfdf8cb53a6ebb135423b7b6a97b37990254e46f85b3`;
  do not transfer this verdict to another build without rerunning the production evidence gate.
- The v105 fresh-power-on, `TESTFLAG=0` run armed production organically, used the real controller
  path, and sustained **30.008326 game ticks/s** over 3,603 SNES video frames / 1,802 game ticks.
  It averaged **357,281.999 SA-1 cycles/tick**, below the 358K gate, and reached gameplay tick
  2,230 with halt zero, task mask `$FFA7`, all 16 task stacks initialized, and a 136-byte minimum
  stack margin. The real `$0818` hook and game counter matched 150-for-150.
- Renderer conservation is part of that verdict: 1,802 requests, 1,802 unit-step ACK transactions,
  1,802 true render completions, zero queue drops, bounded transaction debt, and empty queues at
  the endpoint. v104 met the timing and ordering gates but silently coalesced two direct snapshots;
  it is rejected. v105 adds the missing direct-snapshot ownership guard.
- The July 12 recovery ROM's **1.3237 game-fps after production arming** and roughly 8.10M SA-1
  cycles/tick remain the correct historical baseline for that ROM. R6 supersedes that performance
  verdict only for the exact v105 hash. Older 3-10x or 8-15 fps projections remain invalid because
  they measured partial injected windows and excluded end-to-end work.
- R5's negative scheduler result also remains valid history: its NMI/WAI and supervisor-wake labs
  failed the producer-ordering event at ticks 765-767. R6 is materially different: it reduces
  active work, retains at least one real vblank per tick, delivers an ordered ordinary virtual IRQ,
  and uses bounded primary/secondary renderer ownership. The same-ROM checkpoint profile crossed
  ticks 765-767 and the uninterrupted cold boot continued through tick 2,230 without the derail.
- The legal MC68000 interpreter and shipped native escapes have strong differential evidence. On
  v105, fresh MAME gates passed optest 160/160 and opsweep 782/782 cells (1,564/1,564 shots). This
  is still not proof of every whole-program address-space path; R4's bank-assumption bugs are the
  standing warning against promoting focused vectors into universal correctness.
- A settled production-cold-boot Nexen capture now renders the recognizable level background, HUD,
  and player scene while the formal run conserves every render transaction. Exact aligned MAME
  pixel fidelity remains open; visual plausibility alone is not the fidelity oracle.
- The TAD sound port is merged upstream and its data/blob paths are byte- and oracle-validated.
  R4's final no-injection production cold boot proved the organic boot, attract, coin, and
  round-start command chain end-to-end after the two interpreter bank fixes. The 21 comparison
  pairs are recorded, but the by-ear listening/classification pass is still open; most SFX are
  placeholders, and pitch bends/LFO/portamento remain untranscribed.
- The `$0818` `$AC=$2000` clamp remains the gate-off fallback. The organically armed v105 path uses
  the paced scheduler above; neither path by itself proves a full playthrough crash-free.
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
  and rendering included. Exact v105 clears both that budget and the ordering gate and may be called
  a playable candidate. Any relevant code or ROM change must rerun the full cold-boot contract;
  until it does, describe the changed build as an unqualified technical demo rather than inheriting
  v105's verdict.

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
