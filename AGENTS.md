# AGENTS.md — Superman SNES engineering guide

This repository ports Taito's 68000-based Superman arcade game to SNES/SA-1 with an
interpret-cold / native-hot architecture. Treat it as a reverse-engineering project with two
independent oracles: MAME 0.287 for arcade truth and the MCP-enabled Nexen fork for SNES truth.

## Read this first

Project-state documents conflict. Use this precedence order:

1. `CONFESSION.md` — highest-authority correction to optimistic status claims. Where it
   conflicts with any banner, believe the confession. It was recovered from the old
   `sound-p3` worktree during repository consolidation.
2. The newest branch/worktree-specific handoff and evidence (`docs/PROFILE_CAMPAIGN.md`,
   `MAIN_PLANNING_HANDOFF.md`, `supersoundhandoff.md`, and focused `docs/handoff/*`).
3. `STATUS.md` and `README.md` — useful history and architecture, but their playable,
   performance, rendering, and sound wording is too optimistic.
4. Older plans and risk documents — design/history only when superseded by later verdicts.

Before changing code, also read `BUILD.md`, `METHODOLOGY.md`, `tools/README.md`, and the focused
design document for the subsystem being touched. The interpreter debugging reference is
`docs/INTERP_DEBUG_AND_GOTCHAS.md`.

The canonical recovery base is `origin/main` at the PR #15 merge (`73f1839` when consolidation
started). The previous local tips were preserved under `archive/*-pre-recovery-20260712`, including
the old stash tip. Inspect `git status`, branches, worktrees, and refs before choosing a base. Never
merge, rebase, delete branches, or switch away from user work without explicit instruction.

## Honest project state

- The port is interactive in controlled tests, but it is not playable or shippable.
- The canonical recovery cold boot measures **1.3237 game-fps after production arming** and 0.8665
  across power-on, about 8.10M SA-1 cycles per tick (45.3x short of 60 Hz; 22.7x short of 30 Hz).
  Its `$0760` counter matched the real `$0818` boundary hook 32-for-32, and legacy Mesen reproduced
  the rate within 1%. Older 3–10x or 8–15 fps claims measure partial injected windows and exclude
  important end-to-end work. Use `RECOVERY.md` and the raw baseline, not those projections.
- The legal MC68000 interpreter and shipped per-function native escapes have strong differential
  evidence: opsweep 782/782 and MAME lockstep work are real. The performance problem is not solved.
- The level background is now reproducible from a production cold boot after its palette fade. A
  12/13-tick post-detection state is legitimately near-black, byte/pixel-matches across Nexen and
  Mesen, and must not be called a persistent renderer defect. A Mesen same-boot run continued 108
  ticks and rendered the tan wall/pillar with 75 CGRAM colors. Exact MAME pixel fidelity and a
  long-settle canonical Nexen capture remain unproven; see `RECOVERY.md` R3.
- The TAD sound port is merged upstream and its data/blob/trigger paths are byte- and
  oracle-validated, but it has never received a by-ear listening pass. Most SFX are placeholders;
  pitch bends/LFO/portamento remain untranscribed; organic trigger firing is not fully proven.
- The `$0818` `$AC=$2000` clamp is a mitigation for coroutine/IRQ ordering hazards, not a root-cause
  fix or crash-free proof.
- C-Chip work is genuinely resolved for the observed game contract: deterministic boot replay,
  status gate, and input mailbox. Read `CCHIP_BOOT_HANDSHAKE.md` and `CCHIP_FIRMWARE.md`.

Do not describe a lab interaction as playable, a byte match as listened-to audio, an injected
tick cost as end-to-end fps, or an old reference capture as current behavior.

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
- Nexen MCP fork (project oracle):
  `/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen`
- Older Mesen MCP checkout (legacy/compatibility): `/home/chad/Mesen2/bin/linux-x64/Release/Mesen`
- `mesen_mcp`: `/home/chad/Mesen2/python`
- MAME: `/snap/bin/mame`, pinned to 0.287
- MAME MCP: `/home/chad/mame-mcp`
- TAD compiler: `/home/chad/terrific-audio-driver/target/release/tad-compiler`
- Python 3 with Capstone M68K support

The global Codex MCP registrations should be `mame` and `nexen-inproc`. Nexen uses the project
shim `tools/nexen_mcp_bridge.py`; its transport still reads the historical `MESEN_*` environment
variable names. Legacy Mesen needs `DOTNET_ROOT=/home/chad/.dotnet8`; Nexen harnesses use .NET 10
or the self-contained publish above.

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
  them. The always-on PC ring is at IRAM `$0400-$05FF`, pointer `$48`.
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
