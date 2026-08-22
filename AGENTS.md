# AGENTS.md — Superman SNES engineering guide

This repository ports Taito's MC68000-based Superman arcade game to SNES/SA-1 with an
interpret-cold / native-hot architecture. Treat it as reverse engineering with two
independent oracles: MAME 0.287 for arcade truth and the MCP-enabled Nexen fork for
SNES/SA-1/PPU truth.

## Read first

Use this order:

1. [`docs/current/STATUS.md`](docs/current/STATUS.md) — the sole authority for current
   project status and exact accepted claims.
2. [`docs/current/RELEASE_BLOCKERS.md`](docs/current/RELEASE_BLOCKERS.md) — prioritized
   remaining work and decisions.
3. [`docs/current/BUILDING.md`](docs/current/BUILDING.md) and
   [`docs/current/VALIDATION.md`](docs/current/VALIDATION.md).
4. The focused current or reusable subsystem document under `docs/current/` or
   `docs/toolchain/`.
5. Dated evidence under [`docs/history/`](docs/history/README.md) only when provenance,
   a prior failure, or a rejected approach matters.

Historical documents retain point-in-time words such as “current,” “playable,” and
“next.” They never override the current status. The old detailed agent/status guide is
preserved at
[`docs/history/status/AGENTS_GUIDE_PRE_REORG_20260724.md`](docs/history/status/AGENTS_GUIDE_PRE_REORG_20260724.md).

`main` is the sole active project branch and the GitHub default. Work directly on
`main`; do not create or push feature branches or additional worktrees unless Chad
explicitly asks for one. Pre-recovery tips that are not part of the project line are
preserved as `archive/*` tags, not branches. The frozen historical `sound-p3` worktree
is detached and is not a development base.

Inspect `git status`, worktrees, refs, and the current evidence before changing state.
Never merge, rebase, delete refs, or switch away from user work without explicit
instruction.

## Honest baseline

- There is no promoted human-test ROM. Ordinary build `7506f496…` crosses
  predecessor `d61100e4…`'s fallback-NMI BRK failure in a bounded exact-hash
  fresh-power movie replay through frame 6,322 with terminal liveness intact.
  Its entrance scene/playfield is aligned-MAME exact for ticks 304-339, but the
  full composite remains red by 576 top-HUD pixels per frame and broader behavior
  gates remain open; it is not playable or shippable.
- v124 is the latest formal production run:
  1,783 ticks / 3,602 video frames = 29.700167 game-fps and 360,990.164 SA-1
  cycles/tick. It misses the 30 Hz and 358K gates.
- Retained MC68000 semantic gates are optest 160/160 and opsweep 782/782, plus focused
  differentials. They do not prove every whole-program address path.
- Renderer conservation, organic Stage 2, attack-animation tiles, audio fidelity,
  aligned MAME pixels, full playthrough, current-candidate performance, and hardware
  acceptance remain open.

Do not describe a lab interaction as playable, a byte match as listened-to audio, an
injected span as end-to-end fps, or an old capture as current behavior.

## Repository and private inputs

- `src/interp.pasm`: MC68000 interpreter and bank-$00 dispatch/debug machinery.
- `src/escbank*.pasm`: native/HLE escape banks.
- `src/video.pasm`: 5A22 video supervisor and render path.
- `tools/`: build, differential, profiling, transpilation, and trace harnesses.
- `soundwork/tad/`: TAD project, private generated audio blob, and musical notes.
- `data/`, `build/`, and parts of `src/*.bin`: generated or private-derived artifacts.

Never commit or redistribute arcade ROM material. Preserve private inputs unless the
user explicitly asks to regenerate them:

- `data/superman_m68k.bin` — 512 KiB;
- `tools/mame-trace/gfx1.bin` — 2 MiB;
- `data/cchip_boot_response.bin` — 256 bytes;
- private FM authoring WAVs and evidence captures.

Use:

```sh
python3 tools/prepare_roms.py /path/to/superman.zip
```

to authenticate the supported World set and reproduce the program, graphics, C-Chip
response, and 12 ADPCM-A drums. Exact FM WAV regeneration remains a separate private
VGM/ymfm workflow. See [`docs/current/ROM_INPUTS.md`](docs/current/ROM_INPUTS.md).

Generated outputs and captures can be irreplaceable evidence. Do not delete or
overwrite them casually.

## Toolchain on this host

- .NET 8: `/home/chad/.dotnet8` — legacy Mesen and Python client.
- .NET 10: `/home/chad/.dotnet10` — Nexen, Poppy, Peony, Pansy.
- Poppy:
  latest corrected fork:
  `/home/chad/poppy-astrobleem-latest/src/Poppy.CLI/bin/Release/net10.0/poppy.dll`
  at `astrobleem/poppy` commit `ec005c196eedabf7d0c25ff6336398c427dd43ac`,
  CLI DLL SHA-256
  `715b14431478b62433498cc516c1cbbb8f418c1d7b39a8e71098ed98d9c9167e`.
  The old upstream checkout remains
  `/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll`
  at `fa44a809…`. The previous corrected pinned checkout
  `/home/chad/poppy-astrobleem-0d84bf5d` is retained to reproduce the
  `d01db972…` ROM lineage. Do not switch assemblers in the middle of an
  exact-ROM-hash campaign: pin the compiler commit/DLL hash, rebuild
  intentionally, and rerun ROM-pack plus bounded exact-hash gates.
  The pinned fork still has the distinct conditional-target-after-`RTS` width
  bug filed as Poppy #391; current source works around it and exact-byte guards
  the affected helper. Do not generalize that issue to unrelated failures.
  `tools/build_interp.sh` rejects any other DLL hash unless the operator explicitly
  sets `ALLOW_UNPINNED_POPPY=1` for historical reproduction or compiler adoption.
- Peony:
  `/home/chad/peony/src/Peony.Cli/bin/Release/net10.0/Peony.Cli.dll`.
- Pansy source: `/home/chad/pansy`.
- Nexen project oracle:
  `/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen`.
- Legacy Mesen 2.1.1:
  `/home/chad/Mesen2/bin/linux-x64/Release/Mesen`.
- `mesen_mcp`: `/home/chad/Mesen2/python`.
- MAME 0.287: `/snap/bin/mame`.
- MAME MCP: `/home/chad/mame-mcp`.
- TAD compiler:
  `/home/chad/terrific-audio-driver/target/release/tad-compiler`.
- Python 3 with Capstone MC68000 support.
- Local SNES/SA-1 hardware-reference library: `/home/chad/snesmanual/`. Route
  targeted excerpts through [`docs/toolchain/SNES_REFERENCE_LIBRARY.md`](docs/toolchain/SNES_REFERENCE_LIBRARY.md);
  do not load whole OCR manuals into playback-agent context or copy the source books into
  the repository.

The expected global MCP registrations are `mame` and `nexen-inproc`. Nexen uses
`tools/nexen_mcp_bridge.py`; the transport retains historical `MESEN_*` variable
names. Legacy Mesen needs `DOTNET_ROOT=/home/chad/.dotnet8`. The original
`/home/chad/Nexen` checkout has a damaged source object; do not build or profile from
it.

## Working rules

- Do not build merely to orient. Builds rewrite gitignored binaries and ROM outputs.
- When implementation is requested, use `bash tools/build_interp.sh` and validate in
  proportion to the touched risk. Assembly success is not correctness.
- Prefer MAME/Nexen differentials over visual plausibility.
- Measure native escape firing with SA-1 execution hooks in the actual `$92+` bank.
  A bank-$00 hook can falsely report zero.
- Do not trust `$07xx` IRAM counters without proving ownership. Game state can
  overwrite them.
- The diagnostic PC ring is IRAM `$0400-$05FF`, pointer `$48`. Production packing
  NOPs per-fetch calls. Use `PC_RING=1 bash tools/build_interp.sh` only for recorder or
  freeze diagnosis, and rebuild normally afterward.
- Pause Nexen before coherent grouped reads. Use fresh ports after wedged runs. Long
  scripts may need `socket_timeout=120`.
- Mesen/Nexen/optest harnesses use localhost sockets. Ordinary Codex shell commands
  run with network restricted and can block `127.0.0.1` even after the host
  AppArmor/bubblewrap loopback fix is installed. The Luna playback-watcher role
  therefore sets `sandbox_workspace_write.network_access=true`; launch localhost-
  dependent playback through that role. Do not weaken or repeatedly retry the Sol
  shell, and do not treat `Errno 1` or a loopback timeout as ROM evidence.
- Retain MAME Lua taps in globals. Snap MAME cannot read `.claude` paths; keep runnable
  scripts and artifacts under the project. Use `SDL_VIDEODRIVER=dummy` headlessly.
- Never use `pkill -f mame`; inspect and terminate the exact process.

## Renderer development loop

Do not use the final promotion matrix as the renderer implementation loop.

- Nexen is the active SNES oracle. Legacy Mesen is historical compatibility
  evidence only; do not launch it, replay its movies, or create an active blocker
  from a Mesen-only failure unless Chad explicitly requests historical reproduction.
- Use the game's neutral-input attract mode as the default renderer workload. It
  naturally exercises scrolling, actors, animation, attacks, tile loading, palettes,
  OAM, and scene transitions without recording controller input.
- One iteration is one bounded Nexen attract-mode run to the first renderer invariant
  failure or named milestone. Default to at most 600 observed video frames after the
  selected boundary. Use hooks/counters to reach a later boundary without retaining
  every intervening frame.
- Retain compact scene-generation ledgers and the first failing frame. Capture only
  sparse milestone screenshots or a small contact sheet. Do not record movies, dump
  every-frame PNGs, or run multi-thousand-frame input replays during renderer
  implementation.
- Diagnose and fix the first violated invariant before widening coverage. Reuse an
  existing exact-hash artifact when it already covers the question; do not rerecord
  an unchanged prefix.
- A long playback, new input movie, every-frame framebuffer campaign, or final
  coin/Start/walk/attack/fence matrix requires Chad's explicit approval. Those are
  final acceptance activities, not routine development steps.

## Fail-closed human-test ROM handoff

This policy is mandatory. It exists because narrow background-continuity gates were
repeatedly overstated as whole-ROM visual checks while visible boot, object-motion,
and interaction regressions remained.

- `build/interp.sfc` is always an **unverified ordinary build**. Never hand it to Chad
  as a test candidate and never manually copy or rename it to a `*-test.sfc` file.
- `tools/promote_human_test_rom.py` is the sole path allowed to create a human-test
  ROM. Its exact-hash evidence manifest must pass every required scenario. Missing,
  incomplete, stale, cross-hash, `unknown`, or red evidence is a hard failure.
- Required bounded fresh-power scenarios are: centered and unclipped cold-boot
  presentation; title/credit/Start; walking right; walking left; stationary and
  moving attacks; every-frame scroll continuity; intact-fence collision, attack,
  break animation, and post-break passage; aligned full-composite framebuffer
  comparison covering background, objects, and HUD; and recorded Sol visual review
  of the required screenshots/contact sheets.
- A background-only, tile-cache-only, state-only, liveness-only, or still-image gate
  can never satisfy a composite or behavior scenario. No green result may be widened
  beyond the scenario and exact frame range named by its report.
- Every scenario report must identify the full ROM SHA-256, start from fresh power
  without a save state or runtime memory mutation, retain explicit frame coverage,
  list zero failures, and authenticate its visual artifacts. Rebuilding creates a new
  hash and invalidates every prior promotion report for the successor.
- After Chad explicitly authorizes final promotion playback, it belongs to the Luna
  playback watcher, with raw logs and frame data on disk. Sol reads the compact
  discrepancy report and opens the mandatory visual artifacts. Promotion remains
  blocked until that review is recorded green. This does not authorize long playback
  during ordinary renderer development.
- Handoff wording must come from the promotion record. If a scenario is not in that
  record, describe it as **NOT CHECKED**, never inferred clear. If promotion fails,
  preserve the ROM as rejected evidence outside the top of `build/`; do not present a
  convenience test copy.

## Assembly and layout hazards

- The old upstream Poppy silently permits `.org` overlap; later sections overwrite
  earlier bytes. The latest corrected `astrobleem/poppy` fork rejects this class,
  but seam audits and ROM-pack assertions remain mandatory defense in depth for
  hand-packed banks, private blobs, and exact-ROM lineage changes.
- Do not insert code casually into the middle of `interp.pasm`; long branches can wrap
  silently and bank `$00` is tightly packed. Prefer escape banks or size-neutral
  stubs.
- Old upstream Poppy mode/layout bugs around labels, `REP`/`SEP`, expressions,
  macros, invalid long operands, bank-byte expressions, and width hazards are now
  fixed or diagnosed in the corrected fork. Retain explicit `.a8`/`.a16` and
  `.i16` plus byte audits because this project depends on exact packed bytes.
  Do not attribute a new runtime failure to Poppy unless the build records the
  wrong DLL hash, a minimized current-fork reproduction exists, or a pack/seam
  assertion demonstrates bad emitted bytes.
- Use explicit long-bank calls/jumps across escape banks. Search all `.pasm` files for
  hardcoded addresses after relocating an interpreter label.
- MC68000 work RAM is big-endian. Preserve CCR/X, stack residue, return conventions,
  and observable register side effects.
- The transpiler must fail loud on unsupported semantics.
- The coroutine scheduler has tiny task stacks and an IRQ-density contract. Do not
  alter `$AC`, wake order, or IRQ delivery without proving stack floors,
  producer/consumer order, and sustained cold-boot behavior.

The full forensic detail is in
[`docs/toolchain/DEBUGGING.md`](docs/toolchain/DEBUGGING.md).

## Performance evidence contract

Reserve `fps` for an end-to-end production measurement that identifies commit and ROM
hash, starts at power-on with `TESTFLAG=0`, arms organically, uses the real input
mailbox, validates the `$0818` boundary hook, measures emulated SNES video time,
includes waits/IRQs/rendering/transitions, and retains raw logs.

- A same-run local speedup describes that span only.
- Save states, forced gates, injected audio, and short isolated ticks prove only their
  named behavior.
- Any scheduler replacement must survive the historical ordering event beyond ticks
  765-767 with halt, PC, task mask, sound/input state, recent render progress, and
  every initialized task-stack floor checked.
- The current Superman gate is 30 complete gameplay ticks/s at no more than 358K SA-1
  cycles/tick, with pacing and rendering included, followed by a human combat/audio
  playtest.

See [`docs/toolchain/SCHEDULER_TIMING.md`](docs/toolchain/SCHEDULER_TIMING.md).

## Validation expectations

- Interpreter semantics: `tools/optest.py`, `tools/opsweep.py`, and focused MAME
  fixtures.
- Escape/transpiler: prove the real-bank hook fires; compare native-on/off; preserve
  gate-off behavior; add multi-tick and cold-boot checks as risk requires.
- Bank/layout: assemble, audit seams/overlaps, cold-boot, then relevant lockstep.
- Rendering: inspect producer shadow, manifest, VRAM/CGRAM/OAM/PPU, screenshots,
  conservation, and continued execution.
- Performance: local cycle deltas plus a qualifying cold-boot run before any fps
  claim.
- Sound: compiler/ARAM/byte checks plus human A/B listening against arcade/VGM.

Record negative results and failed assumptions. When work changes project truth,
update `docs/current/STATUS.md`, the focused evidence report, and the visible blocker
or handoff layer in the same change. Preserve superseded claims as dated history.

## Gigandes boundary

The next major goal is reusing this machinery for Gigandes. Start at
[`docs/gigandes/README.md`](docs/gigandes/README.md) and follow
[`docs/gigandes/BRINGUP.md`](docs/gigandes/BRINGUP.md). Keep the MC68000 core shared;
make program images, maps, IRQ, inputs, video policy, command maps, fixtures, and
acceptance budgets explicitly game-specific.
