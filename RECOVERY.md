# Project recovery — canonicalization and evidence baseline

Started July 12, 2026. This is the active project-control document. It converts the repository
from overlapping optimistic handoffs into one evidence-backed engineering line.

## Canonical repository state

- Canonical upstream base: `origin/main` at PR #15 merge `73f1839`.
- Active recovery branch: `recovery/canonicalize-20260712`.
- Recovered truth documents: root `CONFESSION.md` and `AGENTS.md`.
- Old local tips and the unique stash are preserved as local `archive/*-pre-recovery-20260712`
  refs. Nothing has been deleted.
- The old `sound-p3` worktree remains locked and untouched as a safety archive. Its tracked tip is
  already an ancestor of `origin/main`; its only unique visible
  untracked file was `CONFESSION.md`, now copied byte-for-byte to the root. Its gitignored final
  sound assets were also unique and have now been recovered into the canonical checkout.

### Worktree policy during recovery

- Do all new work in `/home/chad/supermn-snes` on `recovery/canonicalize-20260712`.
- Treat `.claude/worktrees/sound-p3` as a frozen source archive. Do not build, edit, merge, or
  launch emulators from it.
- The worktree's tracked commits need no merge: `sound-p3` is already an ancestor of
  `origin/main`. Archive refs preserve its tip and the other pre-recovery tips independently.
- Keep the worktree locked as a safety archive through the recovery baseline. Its recorded Claude
  lock owner is no longer running, but removal is cleanup, not recovery work, and is unnecessary
  while the archive refs and recovered artifacts are intact.

## Evidence grades

### Strong evidence

- MC68000 instruction semantics: MAME differential gates, including the recorded 782/782 sweep.
- Per-function native escapes that individually passed firing plus lockstep/full-diff gates.
- C-Chip observed boot response and input-mailbox contract.
- TAD blob construction, ARAM fit, and byte-level transport/oracle checks.
- Specific Poppy `.org` overlap and stale-cross-bank-address bugs already reproduced and fixed.

### Partial evidence, not a project-level verdict

- Injected GAME_TICK cycle spans: valid for local comparisons, incomplete for end-to-end fps.
- Isolated palette/sprite/background render tests: validate conversion paths, not a settled cold boot.
- Sound trigger injection and byte matches: validate transport/data, not musical fidelity.
- `$0818` `$AC=$2000` soak samples: useful mitigation evidence, not a proof of crash freedom.

### Unproven or contradicted

- Playability or a credible 30/60 fps landing point.
- Exact same-state MAME graphics fidelity and a long-settle canonical Nexen capture.
- Complete/faithful sound by ear.
- Organic firing of every mapped music/SFX trigger.

## Canonical tools

- Arcade oracle: MAME 0.287 at `/snap/bin/mame`.
- SNES/SA-1/PPU oracle: MCP-enabled Nexen at
  `/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen`.
- Shared Python transport/client: `/home/chad/Mesen2/python`.
- Agent stdio shim: `tools/nexen_mcp_bridge.py`.
- Global MCP registrations: `mame` and `nexen-inproc`.

The older `/home/chad/Mesen2` emulator remains available for compatibility with historical scripts,
but new baseline evidence uses Nexen unless a documented emulator comparison is the purpose.

## Recovery gates

### R0 — Source and artifact provenance

- [x] Base recovery work on `origin/main`.
- [x] Preserve prior refs and unique stash.
- [x] Recover `CONFESSION.md` and add `AGENTS.md`.
- [x] Identify Nexen as the current project oracle and validate its MCP handshake/SA-1 cycle state.
- [x] Back up stale generated artifacts before regeneration.
- [x] Rebuild the merged 21-song TAD blob and ROM from the canonical source.
- [x] Record hashes, sizes, tool versions, source commit, and build log.

July 12 recovery evidence:

- Pre-regeneration outputs are preserved under `build/recovery-20260712/prebuild/`.
- A self-contained local snapshot of the recovered `soundwork/` tree is preserved as
  `build/recovery-20260712/soundwork-recovered.tar.gz` (5,093,199 bytes, SHA-256
  `60b6dcc3b4e0dc02caa08b2f08f914aeef6552d1ec8631533658d0e548574757`).
- The recovered 93,515-byte TAD blob rebuilt to SHA-256
  `a149d476371161993d70427c9c0f3148355df0ff7a4e20aad23915e9688e0f31`, byte-identical to
  the final `sound-p3` artifact. Its generated symbol file is also byte-identical.
- The canonical 4 MiB ROM rebuilt to SHA-256
  `183c53f6ae100a6ad7faec324f4f6c58c872292b3088b5e2b0d74ea798b69673`, byte-identical to
  the final `sound-p3` ROM. The stale pre-recovery main ROM was preserved separately and hashes
  to `1897699a4aa347e2d6b3d9ce642a404f77e5da63ab95a40346b80674d36b7806`.
- The final reproducibility build ran at recovery commit `9671faf`; no assembly source differed
  from the `origin/main` merge tree. Raw sound/build logs are
  `build/recovery-20260712/sound-build.log` and
  `build/recovery-20260712/build-9671faf.log`.
- Host tool versions: .NET `8.0.422` and `10.0.301`, Poppy `0.1.0`, Peony
  `1.0.0+aa8c392`, MAME `0.287`, TAD compiler `0.3.0`, Python `3.12.3`, and Capstone `5.0.7`.
  Nexen source is `177e8d567` and the tested binary SHA-256 is
  `476e3f60533575f2c9d835f0a3b59adce2f7efe383ff9e71b791020f8198776c`.

### R1 — Static and interpreter correctness

- [x] Run bank/layout assertions during the canonical build.
- [x] Run opsweep and optest against MAME 0.287.
- [x] Run the production gameplay smoke on the freshly built ROM.

The hardened Nexen run is green: `optest.py` passed 154/154 groups and `opsweep.py` passed
782/782 coverage cells (1,564 concrete vectors). Raw logs are `optest.log` and `opsweep.log` under
`build/recovery-20260712/`. An initial 144/154 optest run was retained too: it exposed two harness
defects, not opcode mismatches. A fixed shared MAME result path allowed concurrent-run contamination,
and `run_frames(1)` sometimes paused a value-dependent instruction mid-flight. Per-run result files
plus a fresh, bounded done-marker wait eliminated both failure modes; the previously failing signed
multiply case also passes under legacy Mesen as a compatibility check.

`tools/smoke_gameplay.py` also passed on the rebuilt ROM: its build-specific injected state ran one
`GAME_TICK` and returned to `$00070E`. This is a local execution-path gate only; it does not count as
a cold-boot, rendering, stability, or performance result.

### R2 — Honest cold-boot performance

- [x] Start from power-on with production `TESTFLAG=0`; do not load a save state or force gates.
- [x] Log when `$072E/$071A/$073A` arm and record the sound-ring signature that caused it.
- [x] Drive coin and Start through the real input mailbox.
- [x] Measure emulator video frames, wall time, SA-1 cycles, `$0760` game-tick count, instruction
  counter, task mask, halt state, and final PC in the same continuous run.
- [x] Cross-check that `$0760` is monotonic and corresponds to the `$0818` game-frame boundary.
- [x] Publish raw logs and separate emulated-game rate from host throughput.

The canonical Nexen run is under `build/recovery-20260712/baseline-nexen/`; its JSONL and runner
log both hash to SHA-256
`133cd8fb111a8b35814f66acb0ba02a0291f37e48e4cb198f8ee7da9f21c724c`. It started from a clean
checkout at recovery commit `e3b6420`, production ROM SHA-256 `183c53f6...`, `TESTFLAG=0`, and no
save state or state/gate poke. Production armed at video frame 5,043 with sound-ring pointer
`$00F01C20`; all six observed gates had their exact production values. An execution hook at the
actual `INC $0760` instruction (`$00:F5A3`) then matched 32 consecutive counter ticks 32-for-32
before being removed. The counter remained monotonic, and halt stayed zero through the final read.

Real input-mailbox events were: coin 1 at tick 106, release 115; coin 2 at 124, release 133; Start
at 146, release 156. The same run reached task mask `$3B40` at tick 197 and ended after the requested
post-detection window at frame 14,562 / tick 210. Final state included 2,601,985,631 SA-1 cycles,
3,054,765 interpreted-instruction counter units, 68K PC `$000818`, and SA-1 PC `$00811E`.

| Metric | Canonical Nexen | Legacy Mesen compatibility |
|---|---:|---:|
| Production arm frame | 5,043 | 5,111 |
| Gameplay detection tick | 197 | 198 |
| Final video frame / game tick | 14,562 / 210 | 14,579 / 210 |
| Post-arm game rate | **1.3237 fps** | **1.3308 fps** |
| Full power-on observed rate | 0.8665 fps | 0.8736 fps |
| Post-arm SA-1 cycles per tick | 8,099,238 | 8,055,299 |
| Host video throughput | 2.8446 fps | 13.0040 fps |
| Host wall time | 5,118.23 s | 1,115.18 s |

The host-throughput row measures emulator/debugger speed, not port speed; the two emulator builds
and hook lifetimes differ. The game-rate rows use game ticks per emulated SNES video time. The
canonical post-arm result is one game tick per 45.33 video frames: **45.3x short of 60 Hz and 22.7x
short of the project's 30 Hz retarget**. The confession's inherited ~0.5 fps observation was
directionally honest, but this instrumented two-emulator result supersedes it.

### R3 — Gameplay rendering truth

- [x] Reach a gameplay state and observe it past the level-palette fade from the same cold boot.
- [x] Capture `$41:4800` tile codes, `$41:4C00` colors, CGRAM, VRAM, OAM, PPU layer enables,
  and screenshot together.
- [x] Compare with a same-state MAME reference or state why exact state alignment is unavailable.
- [x] Decide whether the missing background is state progression, shadow generation, transfer,
  PPU configuration, or renderer logic.

The 12/13-tick post-detection Nexen and Mesen captures are the same early fade state. Their BG code
shadow, BG color shadow, CGRAM, OAM, 4 KiB BG tilemap, and every tile graphic referenced by that
tilemap are byte-identical. Relevant PPU configuration also agrees: mode 1, brightness 15, BG1+OBJ
enabled, BG1 map at word `$0000`, and BG characters at word `$1000`. Their screenshots are
pixel-identical except for 192 pixels on the live bottom scanline. Full-VRAM differences are confined
to unreferenced/uninitialized ranges `$1000-$1FFF` and `$8000-$FFFF`.

At that early point the tile geometry is already present, but BG palettes 0 and 1 contain only black
and 27 copies of dark gray `$0842`; the other BG palettes are zero. That explains the near-black
image without invoking an emulator renderer failure. A second production cold boot under legacy
Mesen continued for 108 ticks after gameplay detection (`baseline-mesen-extended/`). Its unchanged
BG shadows rendered as the recognizable tan wall/pillar and lower wall once the palette fade
completed; CGRAM grew from 15 to 75 unique colors and the screenshot contains 37 RGB colors. The
extended JSONL hashes to `319f0dddbfcff1303c703a3c9d263c2791ed33384ed41af1b4485f93bf96cddb`;
the final screenshot hashes to
`cb16122f763a20c6113b2fa7e5ae0fdf8e4e368b029299b29744a352c67210de`.

Therefore the short capture's missing background was **state progression through the palette
fade**, not absent shadows, failed transfer, disabled layers, or Nexen renderer logic. The extended
run used coarse input pulses and is rendering evidence only; its timing fields do not replace the
canonical Nexen performance result. A same-state MAME comparison is unavailable because no aligned
cold-boot MAME state/reference capture was preserved, so arcade pixel fidelity and player placement
remain separate, open validation questions. A 90-tick post-gameplay window is now the harness
default to prevent this early-fade misclassification.

### R4 — Sound truth

- [ ] Record audio from organic attract and gameplay triggers.
- [ ] Verify which commands fired without injection.
- [ ] Listen to all 21 tracks against arcade references and log musical defects.
- [ ] Reclassify sound as data-correct, transport-correct, or musically accepted per track.

### R5 — Bounded performance-architecture decision

- [ ] Profile a representative continuous, production gameplay interval and attribute the observed
  ~8.10 million SA-1 cycles per tick across interpreted work, native/HLE bodies, bridges/scheduler,
  5A22 rendering/contention, frame pacing, and idle time.
- [ ] Reconcile that continuous-run cost with the inherited 1.3–2.0 million-cycle injected windows;
  do not optimize from the old windows until the missing factor is measured.
- [ ] Prototype the highest-leverage architectural change and require a measured, composable path
  to the 358K-cycle 30 Hz budget. Per-function escape work remains frozen meanwhile.
- [ ] Choose explicitly among a semantic/full-AOT campaign, an honestly scoped technical demo, or
  stopping the port while preserving the interpreter/toolchain work.

## Decision rule after the baseline

Performance is the project gate, and R2 fired it decisively. Do not spend the next campaign polishing
sound, palette timing, or isolated escapes. R5 is the active campaign: first explain the full-run
8.10M-cycle tick, then require measured architectural leverage before committing to a rewrite.
Choose explicitly among:

1. a larger semantic/HLE rewrite with a measured path to the target rate;
2. a reduced-scope technical demo with honest acceptance criteria; or
3. stopping the port while preserving the reusable interpreter/toolchain work.

No option will be framed as success until its observable user experience meets its stated target.
