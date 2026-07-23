# Project recovery — canonicalization and evidence baseline

Started July 12, 2026; latest evidence reconciliation July 22, 2026. This is the active
project-control document. It converts the repository from overlapping optimistic handoffs into one
evidence-backed engineering line. **R7 supersedes R6's playable verdict after the first real user
playtest exposed broken combat and audibly incomplete music. R6 remains valid historical
performance/scheduler/renderer evidence for exact v105; R7 identifies the retained v124
combat-fixed technical demo and its new production result.**

## Canonical repository state

- Historical recovery base: `origin/main` at PR #15 merge `73f1839`.
- The completed recovery line became `main`; current recovery work is on
  `agent/playability-recovery`. Exact ROM hashes, rather than an old handoff's branch name, identify
  each measured candidate. v105 (`72d925ac…`) is historical; retained combat-fixed v124 is
  `777507c9…`.
- Recovered truth documents: root `CONFESSION.md` and `AGENTS.md`.
- Old local tips and the unique stash are preserved as local `archive/*-pre-recovery-20260712`
  refs. Nothing has been deleted.
- The old `sound-p3` worktree remains locked and untouched as a safety archive. Its tracked tip is
  already an ancestor of `origin/main`; its only unique visible
  untracked file was `CONFESSION.md`, now copied byte-for-byte to the root. Its gitignored final
  sound assets were also unique and have now been recovered into the canonical checkout.

### Historical worktree policy during consolidation (superseded)

These rules governed the July 12 consolidation. They are retained to explain the archive layout,
not as current branch instructions. The recovery line is now `main`, and the R6 candidate is the
dirty `main` worktree identified above.

- New recovery work was performed in `/home/chad/supermn-snes` on
  `recovery/canonicalize-20260712` before that line became `main`.
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
- R6's v105 power-on production measurement: exact tick-hook/counter agreement, real input,
  uninterrupted video-time cadence, cycle-stamped SA-1 work, request/ACK/true-render conservation,
  queue overflow telemetry, sound-ring health, task-stack floors, and survival through tick 2,230.
  This is strong timing/ordering evidence, not evidence that combat was usable.
- R7's v124 evidence: 35/35 `$012B6C` MAME cases, 4/4 live combat-spine differentials, visible
  Button 1/2 actions, enemy attack plus health loss in an 800-frame idle window, and a formal
  power-on 3,602-frame production run with current progress and intact safety checks.

### Partial evidence, not a project-level verdict

- Injected GAME_TICK cycle spans: valid for local comparisons, incomplete for end-to-end fps.
- Isolated palette/sprite/background render tests: validate conversion paths, not a settled cold boot.
- Sound trigger injection and byte matches: validate transport/data, not musical fidelity.
- `$0818` `$AC=$2000` soak samples: useful mitigation evidence, not a proof of crash freedom.

### Unproven or contradicted

- Playability, a complete playthrough, every stage/boss path, real-cartridge timing, or
  shippability. v105 met a narrow formal performance contract but failed the first human combat
  test. v124 repairs those demonstrated combat failures but misses both formal 30 Hz thresholds.
- Exact aligned same-state MAME graphics fidelity. R6 retains a long-settle canonical Nexen
  capture, but it is not yet paired to an arcade-oracle frame for a pixel verdict.
- Complete/faithful sound by ear. The first user playtest reports recognizable music that audibly
  cuts out; R7 diagnoses incomplete transcription/SFX authoring without claiming an audio fix.
- Organic firing of every mapped music/SFX trigger.

## Canonical tools

- Arcade oracle: MAME 0.287 at `/snap/bin/mame`.
- SNES/SA-1/PPU oracle: cycle-stamped MCP-enabled Nexen at
  `/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen`.
- Shared Python transport/client: `/home/chad/Mesen2/python`.
- Agent stdio shim: `tools/nexen_mcp_bridge.py`.
- Global MCP registrations: `mame` and `nexen-inproc`.

The older `/home/chad/Mesen2` emulator remains available for compatibility with historical scripts,
but new baseline evidence uses Nexen unless a documented emulator comparison is the purpose.
The original `/home/chad/Nexen` tree is a preserved damaged archive after an unrecoverable system-
drive read; the clean source/build above and the host recovery copy live on `/mnt/sdc1`.

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
- **R4 re-record (2026-07-19):** after the F3 (`ea_extw`) and F4
  (`op_cmpw_d16_dn`) interpreter fixes, the canonical 4 MiB ROM rebuilds
  reproducibly at commit `4034f1e` to SHA-256
  `31c5dff4e7364f1dfd867e284798c5af5688e90cbe22fa69bc29bba249eed438`
  (build log `build/recovery-20260712/build-4034f1e.log`; supersedes
  `183c53f6...` and the intermediate F3-only `a36c33e6...`). Tool versions
  unchanged from the July 12 record.
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

- [x] Record audio from organic attract and gameplay triggers.
- [x] Verify which commands fired without injection.
- [ ] Listen to all 21 tracks against arcade references and log musical defects.
- [ ] Reclassify sound as data-correct, transport-correct, or musically accepted per track.

July 18 R4 evidence (`build/recovery-20260712/r4-sound-truth/`, hashes in its
`SHA256SUMS.txt`, full narrative in its `R4_REPORT.md`):

- Arcade organic ground truth (MAME latch taps from power-on): boot verbs
  `$ff/$00/$ef/$00`, first music `$05` at frame 805 (~13.4 s), demo SFX flood
  from ~1516, coin → `$00`+`$19` within 22 frames, start → `$32`+`$06`×3.
- **Port organic verdict was NEGATIVE — zero sound commands ever enqueued**
  across cold-boot sessions crossing the attract-music point, coin, start,
  gameplay, and a 40,709-tick soak. **ROOT CAUSE FOUND AND FIXED
  (2026-07-18): an interpreter defect** — `ea_extw` (the EA engine's
  extension-word fetch) added `#$00C1` to the PC bank unconditionally, so
  RAM-resident 68K code (bank `$F0`, e.g. the game's sound enqueuer at
  `$f01b20`) fetched its extension words from SNES bank `$B1` (open bus).
  Every EA-engine instruction executed from work RAM read garbage
  d16/immediates; the sound ring writes silently landed on junk addresses.
  Fix: byte-neutral stub at `$00:B83F` → bank-aware body `eaw5_fix` in
  escbank5 `$99:F700`. New production ROM SHA-256
  `a36c33e6d836321818b1c3764ca2659cc989360228d54a464df59ad38ed386b5`
  (supersedes `183c53f6...` — R0 provenance to be re-recorded at commit).
  Verified: organic `$ef/$00` boot verbs now enqueue + drain end-to-end on a
  production cold boot; the full organic session (`organic-fixed2/`) then
  fired attract `$05` at tick 729 and coin `$00`/`$19`/`$19` — arcade
  parity. The `rc_copy` boot-hardcoded attract song
  (`src/video.pasm` `Tad_LoadSong(1)`) masked the defect since P2/P3; its
  removal (arcade is silent until 13.4 s) is a pending cosmetic decision.
- **SECOND interpreter defect (F4) FOUND AND FIXED (2026-07-19)**: the same
  organic session exposed that round-start music (`$32`+`$06`×3) never
  fired. Root cause (R4_REPORT.md §5): `op_cmpw_d16_dn` — the fast-path
  handler for `cmp.w (d16,An),Dn` — read `$40:(An.lo16+d16)` (work RAM)
  unconditionally; the music dedupe compares against the ROM table at
  `$6ab4` via a2, read 0 instead of 6, false-matched, and skipped the send.
  Fix: byte-neutral stub at `$00:9F34` → bank-aware body `cmpw5_fix` in
  escbank5 `$99:F760`. New production ROM SHA-256
  `31c5dff4e7364f1dfd867e284798c5af5688e90cbe22fa69bc29bba249eed438`
  (supersedes `a36c33e6...`; R0 provenance to be re-recorded at commit).
  Verified armed: the full guard walk `$8dea→$8e18` executes and the ring
  receives the arcade-identical `$32 $06 $06 $06` burst. **FINAL organic
  session (`organic-fixed3/`, audio recorded): one no-injection cold boot
  produced the complete arcade chain — `$ef/$00` boot, `$05` attract (tick
  731), coin `$00/$19/$19`, round-start `$32`+`$06`×3 at 51 ticks after the
  start press (arcade parity). R4's organic-trigger gate is CLOSED.** Same-class
  UNAUDITED siblings flagged in R4_REPORT.md §5 and the gotchas doc
  (`op_movb_d16_dn`, cmpi-(d16,An) family). optest 154/154 and opsweep
  782/782 were green on the F3 ROM; re-run on the F4 ROM recorded in
  R4_REPORT.md (opsweep cannot catch this bug class — its An vectors are
  work-RAM addresses; a ROM-pointer optest vector is a noted gap).
- The 21-track listening pairs are recorded and pre-screened (arcade refs
  via halted-68K latch stimulation; SNES side via frozen-interp mailbox
  injection, every drain confirmed, all tracks play full length). The by-ear
  pass and per-track classification remain open.

### R5 — Bounded performance-architecture decision

- [x] Profile continuous production attract and settled gameplay intervals with exact cycle-stamped,
  simultaneous hooks and no phase-boundary pauses.
- [x] Reconcile the canonical post-arm average with the inherited partial injected windows.
- [x] Prototype both supervisor-poll and WRAM-NMI real-vblank wake architectures in marked,
  off-production lab ROMs.
- [x] Drive both prototypes through real coin/start input and require gates, ring, halt, progress,
  task-mask, and saved-task-stack-floor health.
- [x] Choose explicitly among full-AOT, technical-demo, and stop outcomes.

R5 required a small Nexen instrumentation fix: recovery commit `6365acc39` adds the source SA-1's
exact 64-bit `cycleCount` to hook notifications. Its healthy-volume binary hashes to
`17d243c404b8ef32bbb1754a5b026584f2ae24cb047f54b9f250a6f4b721650a`. The profiler installs the
exact `$00:F5A3` clamp, `$00:B404` virtual-IRQ, and `$92:DC3B` game-entry hooks together and never
pauses between them.

The settled production gameplay result is 7,359,718 cycles/tick: 6,456,498 waiting from clamp to
virtual IRQ (87.73%), 7,163 in IRQ-to-entry dispatch (0.10%), and 896,057 from `$3A92` entry to the
next clamp (12.18%). Sixteen intervals range only from 7,359,190 to 7,360,482 cycles and occupy
41-42 SNES video frames, about 1.457 game ticks/s. The comparable attract result is 7,256,419 total
with a 6,467,122-cycle wait. This resolves the old 1.3-2.0M injected-window disagreement: those
windows stopped before the next wait completed. The 8,099,238-cycle/1.3237 fps R2 value remains the
canonical end-to-end post-arm average because it also includes initial post-arm and state-transition
cost.

Verified gameplay profile:
`build/recovery-20260712/r5-continuous-profile-gameplay-verified/profile.jsonl`, SHA-256
`83125a216f6cfb3d5ab9dd7fd1078e183eecefc09466fd6cdd7b97380f7b285f`. Its same-ROM, pre-hook
gameplay checkpoint hashes to
`0076df64b7902eb05ca6a29c1e38742a0cb4e3fb76722153e779cf3cbec08247`.

The isolated architecture result is decisively red:

| Lab variant | Short attract cycles/tick | Steady video frames/tick | Input-driven verdict |
|---|---:|---:|---|
| 5A22 supervisor-poll wake | 2,166,590 | 13 | `$080100` / `$DEAD` at tick 765 |
| WRAM-resident NMI wake | 926,918 | 5 | `$080100` / `$DEAD` at tick 767 |

Both failures preserved the six production gates and sound ring, initialized twelve task contexts,
and retained a minimum sampled saved-stack margin of 150 bytes while the task mask corrupted to
`$FFC1`. Waiting until the SA-1 reaches main idle is insufficient; waiting until the 5A22 supervisor
returns is also insufficient. The `$2000` delay is part of the effective coroutine producer/consumer
timing contract, not disposable spin. The NMI and poll JSONL evidence hashes are respectively
`536764a9696b9631e7bd987eafef86dad4c0188979c3786b4d43de9e6658a626` and
`986a40921361007116e70fbad85e6f22e032e5de0f1e6b173e6ff754c20ac288`.

The production ROM and canonical objects were never changed. Their SHA-256 values remain:

- `build/interp.sfc`: `183c53f6ae100a6ad7faec324f4f6c58c872292b3088b5e2b0d74ea798b69673`;
- `src/interp.bin`: `4be096af5abb16fd155da0bdb84df40f597e4815205bfde2e4931d45cf4b53bd`;
- `src/video.bin`: `01ef077ff426740b2f7fedc9fef83d65ce2f4a26657802d1edc7ed8b71b76132`;
- `src/escbank5.bin`: `52fdf25e67912ae478149cac8d208067e297670a7483b718cff8e984041229f3`.

The marked NMI lab ROM also rebuilt byte-identically to
`982131563e4d6fafc07d726adc0205d7293f6bdc6e188e190602910e54354e33`.

**Decision: honestly scoped technical demo.** There is no measured composable path to the 358K
30 Hz budget. Both whole-tick pacing prototypes are unsafe, and even a hypothetical safe zero-cost
wait leaves 896K active gameplay cycles (2.50x the entire budget). A future full-port campaign must
first survive the tick-765/767 ordering gate and measure a representative whole gameplay tick at or
below 358K with renderer/pacing included. Until then, the production clamp stays canonical and
per-function performance sprints remain frozen. Full evidence and negative iterations are in
`docs/R5_PERFORMANCE_ARCHITECTURE.md`.

### R6 — Production playability recovery

- [x] Reduce representative active game work below the 358K-cycle 30 Hz budget without removing
  architected 68000 side effects, IRQ density, or scheduler charges.
- [x] Move renderer comparison/preparation work to the SA-1 and retain immutable complete images
  across asynchronous 5A22 drawing.
- [x] Pace production from real vblank deadlines with no zero-frame tick and bounded repayment of
  measured transition overruns.
- [x] Start at power-on with `TESTFLAG=0`, arm only through production signatures, use the real
  controller path, and validate `$0760` against `$00:F5A3`.
- [x] Measure one uninterrupted gameplay window against emulated SNES video time with waits, IRQs,
  rendering, sound supervision, input, transitions, and continuous hook evidence included.
- [x] Prove request/ACK/true-render conservation, zero queue overflow, current ROM/WRAM mirror
  identity, sound-ring health, all task-stack floors, and survival well past ticks 765-767.

The recovery changed both halves of the machine before replacing the old clamp. Guarded native
paths in the expanded escape banks retain cold interpreter fallbacks and the observed 68K
CCR/register/stack/`$AC` contracts while removing the active object, scheduler, initializer, and
round-transition residual. The renderer now consumes an SA-1-built exact manifest: packed visible
OBJ records, an exact producer-unique BG change list, prepared large transitions, persistent
BG/OBJ caches with bounded reclamation, direct native-tile DMA, and a two-entry compressed queue.
The 5A22 never consumes a partial image.

Production pacing arms only after the organic game and 5A22-ready signatures. At `$0818`, the SA-1
finishes the manifest, publishes the stable shadow, masks hardware IRQ vectoring, and sleeps. The
WRAM NMI/IRQ supervisor waits for a two-vblank deadline, snapshots or queues the image, publishes
the real controller mailbox, wakes the SA-1, and lets the ordinary virtual-IRQ path run after the
wake. Transition overruns accrue video-frame debt; light ticks repay one frame at a time, with at
least one real vblank always required. The empirically necessary bound is ten frames.

This is materially different from promoting R5's 0.927M-cycle lab. R5 removed delay while active
work still exceeded the budget and failed the long ordering gate. R6 first reduced the work,
retained a real-vblank minimum and virtual-IRQ ordering, made renderer ownership explicit, and then
passed the exact gate that rejected R5.

#### Formal production result — July 22, 2026

Source base is `main` commit `f34fc4c8e0e16ac1d7792a881b18d5b3dd97ded0` with the current dirty
R6 working tree. The exact 4 MiB production candidate is v105, SHA-256
`72d925ac1817965f62ebcfdf8cb53a6ebb135423b7b6a97b37990254e46f85b3`, `TESTFLAG=0`. A source-hash
manifest is retained beside the candidate ROM; this result must not be attributed to the clean
base commit.

The same run organically initialized production pacing by frame 5,236, matched 150 tick-hook
events to 150 `$0760` increments, drove both coin pulses and Start on exact tick boundaries through
Nexen port 0/manual `$4016`, detected gameplay at frame 5,685/tick 278, and held real Right+B with
the injection word at zero. The formal window began after settling at frame 5,985/tick 428 and
paused once at frame 9,588/tick 2,230.

| Uninterrupted production gameplay metric | v105 result |
|---|---:|
| Emulated SNES video frames | 3,603 |
| Real game ticks / nominal game rate | 1,802 / **30.008326 Hz** |
| SA-1 cycles / mean per tick | 643,822,163 / **357,281.999** |
| Frame requests / ACK transactions / true draws | **1,802 / 1,802 / 1,802** |
| Non-unit ACK steps / queue overflows | **0 / 0** |
| Maximum transaction request-ACK debt / ACK silence | 3 / 3 video frames |
| Final halt / task mask / initialized task contexts | `$0000` / `$FFA7` / 16 |
| Minimum final saved-stack margin | 136 bytes |
| Final sound-ring pointer / input mailbox / injection | `$00F01C3B` / `$8100` / `$0000` |

All 26 named uninterrupted-window checks passed, and the separate 150-boundary hook/counter
prerequisite also passed. Together they cover the 30 Hz rate, mean representative cycle budget,
tick-counter/hook match, frame-request-per-tick, unit ACK sequencing, render-completion
conservation, zero queue drops, intact gates/pacing, exact ROM mirror/supervisor, real input,
sound-ring bounds, halt, ordering window, and task-stack floors. The transaction debt bound is
three because a request write is observed before NMI can place that candidate into either of the
two retained queue slots; it is not permission to skip a sequence.

Primary evidence directory:
`build/playability-20260720/deadline-debt10-manifest-v105-direct-ownership-coldboot-uninterrupted-3600f-v1/`.
Important retained hashes:

- `baseline.jsonl`: `ba5ad1079a5ca4a5d20b3f19f60a0d25588a3564ccb90dcf27a5b14e4d0d9399`;
- `uninterrupted_gameplay_hooks.jsonl`:
  `f3c5e8a9947063b01ab711451fa4b78189c3567f756728e31852d512a485db42`;
- `renderer_debt_trace.jsonl`:
  `ef85936834e9f3bdd068efd155eedca964449fbcbeb83af3a9d63ae457fa7030`;
- `final.mss`: `99dd545572eaaed566ac33fe6976a565bc6187ce9e8893bc911b0ebd3a94af62`;
- settled screenshot: `1657fe7bf5a5ae9482f909db448a0d00d153ed8f0b7b050202dee4bc761528b5`.

An independent same-ROM checkpoint profile began at gameplay tick 278 and collected 950 complete
clamp intervals through tick 1,229. Its frame deltas were 13 one-frame, 924 two-frame, and 13
three-frame intervals: exactly 1,900 video frames, with debt peaking at ten and returning to zero.
Mean/median/min/max were 357,366.195 / 357,366 / 257,536 / 543,765 SA-1 cycles. Renderer ACK
advanced 951, halt remained zero, task mask reached `$FFA7`, input was real, and the WRAM mirror
remained exact. This is corroborating checkpoint evidence, not the formal fps result. Its
`profile.jsonl` hashes to
`a0a997b2cf6658e4d9df3557cf64eddd5b667e59b9f8ca9f8f344ff3bb72e01f`.

The last v104 cold boot already met the tick/cycle/input/ordering gates, but two ACK writes skipped
one sequence each (`864->866`, `1016->1018`) because an NMI could replace an even direct snapshot
before the worker claimed it. v105 treats `$7E:1F1E != $3302` as queue-owned even when the renderer
busy word is zero. That is why v105 has 1,802 unit ACKs and draws rather than merely a matching
final ACK word. The validator now rejects non-unit ACK steps and persistent queue drops directly.

Fresh final-ROM semantic gates are also retained in the candidate directory: `optest.py` passed
160/160 groups (log SHA-256
`93470844f97da4f349f14c2a273673f5b9a5705139691e7ebb5739a42acfda41`) and `opsweep.py` passed
782/782 cells / 1,564 vectors against MAME 0.287 (log SHA-256
`f0e935df41e7fb7ab344ea4fc576cf2840fb2d3e23bfd4c47fa8ccff2f05e2d6`). Focused MAME and
whole-tick differentials for retained native candidates remain recorded under
`build/playability-20260720/`; R6 does not claim unvisited whole-game paths are proven.

#### R6 verdict

The exact v105 candidate clears the repository's defined representative 30 Hz playability and
tick-765/767 ordering gates. It may be called an **evidence-backed playable production candidate**.
It may not yet be called shippable, full-playthrough validated, pixel-perfect to MAME, or musically
accepted. The performance margin is small, so any change to interpreter work, native `$AC` charge,
pacing, renderer ownership, input ordering, audio supervision, or layout must rerun the full cold-
boot gate against its new ROM hash.

**R7 correction:** the paragraph above records the July 22 R6 conclusion but is no longer current.
The formal cadence evidence was real; the inference that it was playable was falsified by the first
human combat/audio playtest described below.

### R7 — User-playtest truth and combat recovery

#### The v105 playable verdict failed

The first real user test initially saw a long black screen, then eventually inserted a coin,
started the round, saw Superman/enemies/backgrounds, moved normally, and heard recognizable music.
It also found three playability failures that R6 had not tested:

- neither expected attack button produced an attack;
- enemies appeared inert and did not damage Superman; and
- the music audibly lost continuity or cut out.

The tester was not operating the ROM incorrectly. Select inserts a coin, Start starts, B/Y map to
arcade Button 1 (punch/fire), and A/X map to arcade Button 2 (jump). The original arcade game has
no independent kick input.

#### Combat root cause and repair

The HLE/native replacement for 68000 function `$012B6C` always returned to `$01177C`. That happened
to fit one historical fixture, but the ROM has 34 BSR callers with distinct saved return PCs.
Resuming the wrong combat handler explains both the missing player attack transitions and inert
enemy behavior. The retained repair returns through the actual saved `$40/$42` PC for normal HLE
entries and normalizes only the legacy `$99:B5B9` native entry to `$01177C`.

Exact retained v124 ROM SHA-256 is
`777507c9ecba8b7911dae882ea266cca7d173d918dde65b73f880acdb0451352`.
Current evidence tied to that hash:

- `$012B6C->$012B84->$00CE4` is green against MAME 0.287 for **35/35** caller/fixture
  combinations, covering every discovered BSR return plus the legacy native entry;
- the retained `$0122A4` combat spine is green for **4/4** live reference/candidate fixtures with
  exact D/A registers, CCR, terminal PC, and full 64 KiB work RAM;
- Button 1 and Button 2 each change visible output in the expected punch/fire and jump action
  checks; and
- an uninterrupted 800-video-frame idle-combat window activates an enemy attack record and changes
  player health **20 -> 18** with halt zero.

The retained performance work also includes guarded exact paths for `$CAF6`, `$111A`, `$023A0C`,
`$0122A4`, narrow `$002BE2`, and an order-preserving `$0026A0` body. Final-hash focused gates are
green: `$CAF6` 19/19, `$111A` 21/21, `$023A0C` 6/6, `$002BE2` 6/6, `$0026A0` 10/10, and the full
opcode gates optest 160/160 plus opsweep 782/782 cells / 1,564 vectors.

#### Formal v124 production result

`tools/recovery_baseline.py` booted v124 from power-on with `TESTFLAG=0`, armed the production gates
organically, validated the real `$00:F5A3` boundary against the game counter, used Nexen port 0 and
the ROM's real manual `$4016` mailbox, settled gameplay, and then ran one uninterrupted production
window:

| Uninterrupted production gameplay metric | v124 result |
|---|---:|
| Emulated SNES video frames | 3,602 |
| Real game ticks / nominal game rate | 1,783 / **29.700167 Hz** |
| SA-1 cycles / mean per tick | 643,645,462 / **360,990.164** |
| Requests / unit ACK transactions / true draws | 1,783 / 1,782 / 1,782 |
| Maximum transaction debt / ACK silence | 2 / 3 video frames |
| Final tick / halt / task mask | 2,210 / `$0000` / `$FFF1` |
| Final SA-1 PC / 68K PC | `$0083C0` / `$0006C4` |
| Initialized task contexts / minimum saved-stack margin | 14 / 138 bytes |
| Final sound-ring pointer / input mailbox / injection | `$00F01C3D` / `$8100` / `$0000` |

The one-request endpoint lag is an in-flight final transaction, not a skipped ACK: ACK steps were
unit increments, debt stayed within two, queue drops remained zero, and the last tick/render hooks
were zero/one frames old. Halt stayed zero, all initialized stacks remained above their floors,
the ROM/WRAM supervisor mirror was exact, and the known ordering window was crossed with continued
work through tick 2,210.

The run failed exactly the rate and representative-cycle checks:

- **29.700167 < 30 game-fps** by 0.299833; and
- **360,990.164 > 358,000 cycles/tick** by 2,990.164.

Primary evidence:
`build/user-playtest-v105-investigation/production-v124-26a0-ordered-coldboot-uninterrupted-3600f-v1/`.
The uninterrupted hook stream hashes to
`5782ac9392e5eec76e4539ccc0ecd2df9b597e6b580839e8465df5e626fae83a`; the renderer-debt trace
hashes to `f7ae81eded6cd37aca525d56b3df76875d56a335732c06578e97d6047e61f1d8`.

Two faster-looking `$26A0` variants were rejected, not retained:

- v125's direct-return shortcut passed 10/10 exact cases and a 3,600-frame checkpoint soak, then
  halted `$DEAD` in the formal power-on run and accumulated 1,753 frames without tick progress
  (15.3082 game-fps endpoint average).
- v126's packed byte/ROR mask also passed 10/10 and a 1,800-frame checkpoint soak, then halted
  `$DEAD` with 604 frames without tick progress (24.3198 game-fps endpoint average).

Those failures exposed a validator weakness: an old tick total above 800 could make
`known_ordering_event_survived` look green after execution had already stopped. The harness now
also requires recent tick progress, recent render progress, and a non-derailed SA-1 PC. Both unsafe
variants are removed; the exact v124 source rebuild reproduces hash `777507c9…`.

#### Audio classification

An organic gameplay WAV stayed on TAD song 3 and showed no stop/reload, command drop, or digital
silence interval of at least 200 ms. That rules out one narrow transport-failure theory, not the
user's audible symptom. Enemy SFX IDs `$1D/$25/$5B/$27` were observed but ignored/unmapped; most
SFX remain placeholders, pitch bends/LFO/portamento are not transcribed, and several samples are
trimmed to roughly 0.35-0.5 seconds. The honest classification is **recognizable but musically
incomplete**. No audio-fidelity fix is claimed in R7.

#### R7 verdict

v124 is the retained combat-fixed playtest ROM and a stable near-30 Hz technical demo in the tested
window. It is **not playable under the repository contract** because it misses both formal 30 Hz
thresholds, has not passed a human confirmation of repaired combat, and still has known audible
music/SFX incompleteness. Restore the word playable only after one exact ROM clears the cold-boot
rate/budget/ordering/renderer gates and a real user confirms combat and audio behavior.

## Decision rule after the baseline

R7 supersedes R6's playable label while preserving its exact v105 performance evidence. Preserve
the production evidence contract: local/checkpoint improvements remain local evidence, while a new
playability claim requires another power-on uninterrupted run plus a human combat/audio playtest.
Continue under the honest label **interactive technical demo, not playable or shippable**. v124 is
the retained safe playtest hash; do not resurrect v125/v126 or project a local speedup into fps.
