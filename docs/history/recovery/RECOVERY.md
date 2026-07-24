# Project recovery — canonicalization and evidence baseline

> **Historical evidence ledger R0-R15.** It remains the provenance source for recovery
> claims, but it is no longer the active project-control document. Use
> [`docs/current/STATUS.md`](../../current/STATUS.md) and
> [`RELEASE_BLOCKERS.md`](../../current/RELEASE_BLOCKERS.md) for current work.

Started July 12, 2026; latest evidence reconciliation July 24, 2026. It converted the
repository from overlapping optimistic handoffs into one
evidence-backed engineering line. **R7 supersedes R6's playable verdict after the first real user
playtest exposed broken combat and audibly incomplete music. R6 remains valid historical
performance/scheduler/renderer evidence for exact v105; R7 identifies the retained v124
combat-fixed technical demo and its new production result. R8 repairs v124's charged-shot release
freeze. R9 accepts the tester's exact Mesen 2.1.1 rendering/audio reports, repairs their concrete
causes in v128, and records a remaining burst-render conservation failure; it does not replace
v124's formal performance measurement or restore the playable label. R10 records the user's
confirmation of those v128 repairs, fixes the newly exposed first-wall context corruption in v129,
adds a targeted octave-sample pass, and promotes the combined exact v130 ROM with a Mode 7 boot
activity screen. The wall/audio/boot additions remain awaiting human confirmation.**

**R11 accepts the second v130 human test: v130 is rejected after crate-throw and charged-silver-
enemy freezes, wrong animation tiles, an upper-left crop, and a dizziness-inducing rotating boot
logo. Exact v131 makes the supplied logo static, centers the 384x240 arcade view, and quarantines
displayed OBJ-cache slots before reclamation. Its focused cache/manifest/crate, fresh cold-boot,
and exact-Mesen liveness checks are green, but the exact charged silver-enemy kill, a human v131
run, timbre listening, renderer conservation, and formal performance gates remain open.**

**R12 accepts the next human correction: the supplied v131 response still freezes on crate throw,
drops Superman at the visible right edge, and renders incoherent title words. Exact v132 repairs a
misassembled `$023342` continuation, restores the X1-001 wrapped-right interval, and moves the
title's over-capacity legal-text rows to BG2. The repaired task root is exact in 18/18 focused
MAME/Nexen cases; exact-Mesen checkpoint replays pass the old crate terminal and visibly retain the
right boundary; and a final-ROM title checkpoint has six coherent lines. These remain bounded
results. A human v132 cold-boot run, the exact charged silver-enemy kill, first wall, timbre,
renderer conservation, full playthrough, and formal performance gates remain open.**

**R13 accepts the human v132 rejection: the readable title glyphs briefly became corrupted, the
no-input attract path stopped at `INSERT COIN`, and the centered crop showed only `CRE` of the
credit label. Exact v133 keeps the title BG2 character base live during ordinary BG uploads,
repairs a zero-length prepared-background insertion-sort terminal, and applies a signature-tight
48-pixel translation only to the bottom credit glyphs. A stock-Mesen-2.1.1 fresh-power lineage
keeps all 201 sampled title/credit masks stable and advances through the old frame-7,910 terminal
to frame 9,000 / tick 1,726 / render 1,493 at halt zero. Its Mode 7 boot performs the requested
one-shot non-rotating huge-to-fitted zoom. These are bounded title/attract/presentation results;
human gameplay/audio, renderer conservation, full playthrough, and formal performance remain
open.**

**R14 accepts the first long v133 gameplay result: the tester cleared the first boss and reached
the following vertical section, but the playfield did not scroll when Superman moved to the top.
The 68000 game was updating X1-001 per-column scrolly; all SNES BG consumers had hardcoded or
retained `BG1VOFS=0`. Exact v134 carries a center-playfield scrolly value through every
direct/queued snapshot and full/fast/incremental BG consumer, using MAME's `-1` no-flip offset plus
the eight-line centered crop. Its isolated real-65816/PPU lab is 8/8, an exact-Mesen Stage 1
checkpoint retains vertical zero with live ticks/renders and valid stacks, and a fresh-power title
sample remains coherent at vertical zero. Organic Stage 2 scrolling on the SNES still requires
human confirmation; no playability, full-playthrough, audio, renderer-conservation, or formal
performance verdict follows from these bounded results.**

**R15 accepts the exact v134 human rejection: gameplay and the no-credit main/attract path could
still freeze, the top score HUD was absent, and the five-anchor octave pass made no noticeable
audible difference. The supplied freeze and an organic v134 idle replay both contain erased SA-1
IRAM. A mistyped generated `$023342` branch encoded an 8-bit immediate on a live 16-bit path,
turning the following `$54` operand into accidental `MVN $A9,$FB` and zeroing the IRAM mirror.
Exact v135 routes that fixed-size site to an explicit `.a16/.i16` bridge and narrowly restores the
X1-001-wrapped top HUD. Its final-ROM exact-Mesen replay survives 2,400 frames across the old
terminal with live ticks/IRAM, and a checkpointed 88-record OBJ capture visibly contains all top
labels and scores. These are freeze/HUD response results, not crash freedom, musical improvement,
a full playthrough, or a new performance verdict.**

## Canonical repository state

- Historical recovery base: `origin/main` at PR #15 merge `73f1839`.
- The completed recovery line became `main`; current recovery work is on
  `agent/playability-recovery`. Exact ROM hashes, rather than an old handoff's branch name, identify
  each measured candidate. v105 (`72d925ac…`) is historical; formal combat-fixed v124 is
  `777507c9…`; charged-shot-fixed v127 is `1a8a5742…`; exact-Mesen-regression-fixed v128 is
  `7c4b757d…`; first-wall/octave-sample v129 is `8f240332…`; combined wall/audio/Mode-7 v130
  is the human-rejected `1ec22cbc…`; the v131 second-playtest response candidate is
  human-rejected `be0ed971…`; the v132 title/crate/right-edge response candidate is
  human-rejected `48d7c4d6…`; the v133 title/attract/boot response candidate is superseded by its
  human Stage 2 rejection at `15465fe6…`; and the v134 vertical-scroll response candidate is
  human-rejected `782ae58f…`. The current v135 IRAM-freeze/top-HUD response candidate is
  `5aac64b6…`.
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
- R8's v127 focused evidence: exact reproduction of v124's charged-release stall, a concrete
  `$92:EFFB`/fixed-`$92:F000` overlap, audited relocation of the full `$D3B0` body, three green
  real-controller charge durations through 1,200 post-release frames, retained normal attack/jump
  and enemy-offense behavior, fresh 160/160 plus 782/782 interpreter gates, and a green organic
  power-on-to-gameplay smoke.
- R9's exact v128 Mesen 2.1.1 compatibility evidence: fresh no-input post-TAITO title capture,
  real port-0 coin/Start, a 450-frame pre-round transition, grounded B charge/release through 360
  post-release frames, and a digitally continuous gameplay WAV, all tied to exact emulator and ROM
  hashes. Its checkpointed Nexen window is strong evidence that wake-before-DMA preserves the
  established scheduler ordering, while its 31 new queue coalesces are equally strong negative
  evidence against renderer completeness.
- R10's exact v130 focused evidence: six byte-exact background-reconcile fixtures, a real-input
  Mesen first-wall replay through tick 3,622 with halt zero and intact task stacks, an organic
  cold-boot-to-gameplay smoke, and an 1,800-frame idle-combat check that activates an enemy attack
  record and changes health 20→18. Its TAD compiler/ARAM byte oracle and continuous live capture
  validate the new octave-sample data path, not its perceived musical quality. Exact-Mesen captures
  also prove that the Mode 7 boot activity screen moves during the formerly black interval, clears
  before normal Mode 1 ownership, and preserves the green coin/Start/charged-shot sequence.
- R11's exact v131 focused evidence: static supplied-logo captures, exact centered-manifest
  predicates, displayed-slot reclamation quarantine, organic Nexen cold-boot reachability, and an
  exact-Mesen coin/Start/transition/two-charge sequence. The later human crate/right-edge/title
  rejection supersedes its response-candidate verdict, not those bounded results.
- R12's focused evidence: the exact v131 crate terminal was narrowed to a misassembled
  `$023342` continuation; the mode-correct task root matches MAME in 18/18 diagnostic-build
  variants; and the exact-Mesen production replay advances past the old freeze with valid stacks.
  Separate final-ROM exact-Mesen captures show coherent title text and a retained far-right player
  sprite. These are function/checkpoint results, not cold-boot stage stability or performance.
- R13's exact v133 focused evidence: a stock-Mesen-2.1.1 power-on lineage keeps the legal and credit
  nonblack masks stable for 201/201 title frames, passes v132's frame-7,910/tick-1,389 attract
  terminal, and remains live through frame 9,000 / tick 1,726 / completed render 1,493 at halt
  zero. A separate fresh-power capture shows the scale-only Mode 7 boot at huge, intermediate, and
  fitted sizes. This is title/idle-attract/boot evidence, not interactive stage or performance
  evidence.
- R14's exact v134 focused evidence: the production pack/layout gate is green; an 8/8 Nexen
  machine-code lab executes the shipped capture/apply helpers on the real 65816/PPU path, including
  two per-column Stage 2 values retained from MAME; an exact-Mesen Stage 1 checkpoint advances
  tick 1,192→1,258 and completed render 1,124→1,183 at halt zero while keeping `$F9` at
  `BG1VOFS=0` with 14 valid stacks; and an unmodified fresh-power Mesen title sample advances
  tick 285→385 / render 264→349 with `BG1VOFS=0`. This is bridge, regression, and title evidence,
  not an organic SNES Stage 2 run or performance evidence.
- R15's exact freeze evidence: the supplied v134 state and a separate organic idle replay both
  reduce the game tick/task mask and almost all SA-1 IRAM to zero without taking the reset path; a
  narrowed same-frame trace catches the live SA-1 at `$98:80B1`, DBR `$A9`, in the accidental
  block move. Exact v135 then replays 2,400 Mesen 2.1.1 frames across that terminal, advances tick
  2,107→2,519, ends with 475 nonzero IRAM bytes, halt zero, and no reset/IRAM-clear terminal.
  Separately, its checkpointed packed manifest grows from 75 to 88 records and visibly restores
  `1UP`, `HIGH SCORE`, `2UP`, and all score rows with 14 valid stacks. These are exact
  cause/regression and HUD results, not a whole-stage stability or renderer-conservation verdict.

### Partial evidence, not a project-level verdict

- Injected GAME_TICK cycle spans: valid for local comparisons, incomplete for end-to-end fps.
- Isolated palette/sprite/background render tests: validate conversion paths, not a settled cold boot.
- Sound trigger injection and byte matches: validate transport/data, not musical fidelity.
- `$0818` `$AC=$2000` soak samples: useful mitigation evidence, not a proof of crash freedom.

### Unproven or contradicted

- Playability, a complete playthrough, every stage/boss path, real-cartridge timing, or
  shippability. v105 met a narrow formal performance contract but failed the first human combat
  test. v124 repaired those combat failures but froze on charged-shot release and missed both
  formal 30 Hz thresholds. v127 repaired the demonstrated freeze. The user confirmed v128's
  recorded Mesen title/transition/charged-shot/music regressions, then exposed the first-wall crash.
  v130 repairs that focused wall path and adds the octave/boot work; v131/v132/v133 add bounded
  renderer/crate/title/attract corrections. The user then reached the post-boss vertical section
  on v133 and found its camera frozen. Exact v134 bridges the missing vertical state, but its human
  run supplied a later generic gameplay/attract freeze with erased SA-1 IRAM. Exact v135 repairs
  the reproduced erasure and restores the top HUD, but it still inherits the red burst-render
  conservation result and has passed neither the organic Stage 2 retest, a
  full-stage/full-playthrough test, nor a new formal rate/budget run.
- Exact aligned same-state MAME graphics fidelity. R6 retains a long-settle canonical Nexen
  capture, but it is not yet paired to an arcade-oracle frame for a pixel verdict.
- Complete/faithful sound by ear. The user now identifies excessive sample transposition as a
  concrete timbre defect. R10 regenerated and recompiled Main BGM MML with five first-stage octave
  anchors, and exact blob/ROM checks prove those bytes shipped. The later v134 listening test heard
  no noticeable difference, so that pass is now human-rejected rather than awaiting acceptance;
  ignored/placeholder SFX and missing pitch/LFO/portamento remain.
- Organic firing of every mapped music/SFX trigger.

## Canonical tools

- Arcade oracle: MAME 0.287 at `/snap/bin/mame`.
- SNES/SA-1/PPU oracle: cycle-stamped MCP-enabled Nexen at
  `/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen`.
- Shared Python transport/client: `/home/chad/Mesen2/python`.
- Agent stdio shim: `tools/nexen_mcp_bridge.py`.
- Global MCP registrations: `mame` and `nexen-inproc`.

The older `/home/chad/Mesen2` emulator remains available for compatibility with historical scripts
and exact user-report reproduction. R9 pins its Mesen 2.1.1 binary hash and controller
configuration; new baseline evidence otherwise uses Nexen unless a documented emulator comparison
is the purpose.
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
`docs/history/performance/R5_SCHEDULER_EXPERIMENTS.md`.

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

v124 was the retained combat-fixed playtest ROM and a stable near-30 Hz technical demo in the tested
window. R8 supersedes it as a playtest candidate after the charged-shot freeze below. Its formal
performance evidence remains current. It is **not playable under the repository contract** because
it misses both formal 30 Hz thresholds and still has known audible music/SFX incompleteness.

### R8 — Charged-shot release freeze and layout repair

#### User reproduction and failure signature

Holding Button 1 to charge Superman's energy shot and releasing it froze exact v124. The focused
real-controller reproduction reached the shot animation and projectile path, then advanced only 50
more game ticks/renders. By relative frame 130 it had a sustained stall; the retained trace ended
in an SA-1 address-zero `BRK`/`RTI` loop with no new game or render progress. MAME 0.287 remained
live under the organic hold/release, confirming that this was not intended arcade behavior.

#### Root cause and repair

The generated `$00D3B0` handler started at `$92:EFFB` and flowed through `$92:F18E`. The later
fixed `.org $F000` `jah2_ext` section silently overwrote `$92:F000-$92:F0C8`. This was the latent
overlap warned about in the older profile ledger; assembly success was not evidence that both
sections survived ROM packing.

v127 retains `$92:EFFB` as the translation-table entry but makes it a `JML $94:B400` trampoline.
The complete original body is fixed at `$94:B400`, its indirect-call continuation at `$94:B580`,
and the following `$D226` handler at `$92:F18F`. The bank-$94 continuation uses its established
`$00FD` return sentinel while crossing to the bank-$92 indirect bridge. New pack assertions verify
both sides of every island plus the zero seams, and `tools/audit_banks.py` is green.

Exact v127 candidate ROM SHA-256:
`1a8a5742536b6142a42387546524bb0e785fac508a01e6ff5e5c53027b06db35`.

#### Focused validation

| Gate | v127 result |
|---|---:|
| B hold 96 / post-release observation | 300 ticks and 300 renders in 600 frames; green |
| B hold 120 / post-release observation | 300 ticks and 300 renders in 600 frames; green |
| B hold 180 / post-release observation | 600 ticks and 600 renders in 1,200 frames; green |
| `$D3B0` trampoline / `$94:B580` continuation after release | 2 / 2 hits in each case |
| Long-case halt / minimum stack margin | `$0000` / 138 bytes |
| Visible normal Button 1 / Button 2 actions | both green |
| Idle enemy offense | attack active; health 20 -> 18 over 800 frames |
| Current-ROM optest / opsweep | 160/160 / 782/782 cells |
| Escape-bank overlap audit | all banks green |
| `TESTFLAG=0` organic cold-boot smoke | gameplay settled; frame 5,711 / tick 291 / halt `$0000` |

The longest charge case runs from tick 1,029 to 1,718 and also takes live enemy damage from health
20 to 16. These are checkpointed behavior and safety checks, not FPS evidence.

The shortened power-on smoke organically armed every production gate at frame 5,242, drove coin and
Start through the real controller mailbox, and reached gameplay. At its frame-5,711 endpoint,
tick/render progress, sound ring, renderer state, supervisor mirror, and initialized stack floors
were healthy. Because this was sampled and intentionally ended after a short settle, it is
cold-boot reachability evidence, not a new formal rate measurement.

Primary focused evidence is under
`build/user-playtest-v105-investigation/charged-shot-v127-relocated-*`,
`visible-actions-v127-charged-shot-fix-v2/`, and
`idle-combat-v127-charged-shot-fix-v1/`. Cold-boot evidence is in
`production-v127-charged-shot-coldboot-smoke-v1/`. The root-cause narrative and exact commands are in
`docs/history/handoffs/CHARGED_SHOT_FREEZE_20260723.md`.

#### R8 verdict

v127 is the charged-shot-fixed playtest candidate, not a playable release. It still requires a
human confirmation of this exact ROM. v124's 29.700167 game-fps / 360,990.164 cycles-per-tick run
remains the latest formal performance result, and R7's audio defects remain open. Restore the word
playable only after one exact ROM clears the cold-boot rate/budget/ordering/renderer gates and a
real user confirms combat and audio behavior.

### R9 — Exact Mesen 2.1.1 rendering/audio regressions

#### User reports and exact reproduction

The follow-up tester named Mesen 2.1.1 and the precise title interval: after the TAITO logo fades,
before a credit. Exact v127 reproduced a roughly 40-video-frame cycle in which the title was visible
for about three frames and black for about 37. The same reported sequence also reproduced active-
display black bars during Clark's pre-round walk, mixed tiles around the transition, and gameplay
music replacement after the credit cue. These were port failures, not controller use or tester
confusion.

#### Renderer and audio repairs

The queued renderer's primary and secondary paths copied palette `$41:6800`, a retired production
snapshot that remained zero. They now copy the live `$41:2000` palette while the producer is held
off. The PPU DMA helper no longer wraps every transfer in an immediate forced-blank pulse. It
publishes the programmed descriptor through private WRAM `$7E:1F11`; NMI wakes the scheduler first,
services pending DMA in VBlank, then samples input. Large native background runs are split into
5.75 KiB VBlank chunks, while small consecutive transfers use byte-count-specific safe tail limits.
The packer reserves and verifies the new helper island.

Arcade command `$19` is a credit cue overlaid on the current YM2610 music. TAD track 2 cannot
overlay; loading it replaced the active song. The mapper now ignores `$19` while a song is selected
and preserves the standalone mapping only while silent. This fixes the demonstrated replacement,
not the known incomplete music/SFX transcription.

Exact v128 playtest-candidate ROM SHA-256:
`7c4b757ddf5c0297eb1b3aa65f4f6d74ecf289fdfa5f70d0d71811843906db57`.

#### Exact Mesen 2.1.1 compatibility result

The binary used was `/home/chad/Mesen2/bin/linux-x64/Release/Mesen`, SHA-256
`22f714b4e01358eb758750329124a620db9ea42cad0a7b69fc4fa6447442676f`.
The project wrapper explicitly selects a SNES controller on port 0.

| Gate | Exact-v128 result |
|---|---:|
| Fresh post-TAITO/no-credit samples | frames 5,650-5,800; 16/16 visible, brightness 15, no forced blank |
| Real input | one Select coin, then Start; no gameplay memory writes |
| Clark/round transition | 450 frames recorded; inspected montage has no black bars or mixed tiles |
| Grounded charged B hold / post-release | 272 actual frames / 360 frames |
| `$D3B0` entry / relocated continuation / tick hooks | 2 / 2 / 316 |
| Final frame / tick / render / halt | 7,935 / 1,403 / 1,342 / `$0000` |
| Gameplay WAV | 10.516 s; no internal 200 ms or 750 ms digital silence |

The fresh title state and the subsequent compatibility diagnostic are tied to the same exact ROM.
The second phase deliberately reloads that same-ROM title state so the regression sequence is
repeatable; it is checkpointed compatibility evidence, not a new cold-boot performance run or a
full stability/playability test.

Evidence:

- `build/user-playtest-v105-investigation/v128-tail-batching-mesen211-title-fresh-v1/`
- `build/user-playtest-v105-investigation/v128-tail-batching-mesen211-full-v1/`
- `docs/history/handoffs/MESEN211_PLAYTEST_REGRESSIONS_20260723.md`

#### Rejected ordering and residual renderer debt

An intermediate exact-Mesen-green ROM,
`0c9bf6d5c3c3b7fe1d7555d23f151dfb094be6042d7ca46bf41d36c6819eb482`,
serviced PPU DMA before the established scheduler wake. Its formal power-on Nexen run later halted
`$DEAD`, with no tick progress for the final 1,198 frames. It is rejected. Assembly success and a
green emulator screenshot sequence did not prove producer ordering.

Wake-before-DMA removes that halt. On exact v128, a checkpointed 1,200-video-frame Nexen window
crosses the old ordering region with 600 tick hooks/counter increments, 600 frame requests, 600
ACKs, halt zero, real Right+B input, intact production gates, an exact supervisor mirror, 14
initialized stacks, and a 138-byte minimum margin. It completes only 568 true renders and adds 31
queue coalesces, so the no-overflow/conservation gate is red. A 520-frame DMA trace narrows the loss
to cache-heavy bursts: 260 ticks, 257 renders, and three coalesces; a background transition spans
five frames, while one OBJ cache refill spans eight frames across 82 small DMA records.

This is a checkpointed ordering/renderer lab, not FPS evidence. The old-helper
`v128-tail-batching-late-500f-v1` checkpoint is explicitly invalid because its stacked return PC
points into code that moved; do not cite its zero-render result as current behavior.

#### R9 verdict

At the close of R9, v128 was the exact-Mesen regression-fixed playtest candidate. It closes the demonstrated
post-TAITO palette flicker, active-display blank bars/partial transition upload, credit-triggered
song replacement, and charged-release liveness sequence. It remains **not playable or shippable**:
burst render conservation is red, musical fidelity is still unvalidated/incomplete, no full
playthrough exists, and this exact hash has neither a new formal power-on 30 Hz result nor a human
confirmation. v124 remains the latest formal rate/budget evidence.

### R10 — First-wall corruption, octave anchors, and live boot activity

#### Human v128 result and new reports

The next user run supplied the human confirmation R9 lacked for its four concrete regressions:
on exact v128 in Mesen 2.1.1, the post-TAITO title no longer flickered, the pre-round horizontal
bars were gone, a charged shot released without freezing, and gameplay music played again. That
accepts those specific v128 repairs, not the project as a whole.

The same run exposed two new defects. Attacking the first breakable wall froze the game with mixed
tiles, and several FM instruments sounded as though one recording was being transposed too far
across octaves. The tester also reported no enemy damage in that encounter. Controlled evidence
below shows that offense exists, but does not dismiss the encounter-specific report.

#### First-wall root cause and repair

Exact v128 reproduces the wall failure with halt `$DEAD`, PC `$1000B0`, opcode `$F800`, mixed tiles,
and corrupted saved task contexts. The corruption came from the zero-length paths in both
`rmb_bg_promote` and `rmb_bg_revert`: `BEQ` followed `CMP #$0100`, so it tested the compare flags
instead of the length loaded from `$41:013A`. A zero-length list entered the compact loop, wrapped
16-bit Y, crossed DBR `$41` into `$42`, and reached the 128 KiB BW-RAM mirror at physical bank
`$40`, overwriting coroutine contexts. Both helpers now branch on zero immediately after `LDA`.

`tools/validate_bg_reconcile_helpers.py` is byte-exact for promote and revert with empty, compact,
and full inputs (6/6). On exact v130, `tools/trace_wall_context.py` replays the same real-controller
wall checkpoint through frame 12,372 / tick 3,622 with halt zero, 14 valid initialized task
stacks, a 136-byte minimum margin, 2,740 recorded context writes, and no suspicious high-byte
saved-SP write. This closes the reproduced wall corruption path only; it is not a stage or
playthrough soak.

The exact-v130 idle-offense window starts at frame 5,976 / tick 423 / health 20 and ends after
1,800 video frames at frame 7,776 / tick 1,324 / health 18 with an active enemy attack record and
halt zero. The starting cold-boot checkpoint caught Superman just before landing; he reached arcade
Y `$0070` during the window. The offense result is therefore behavior evidence, not a claim that
every enemy/collision encounter is correct.

#### Note-aware octave samples

The old FM renderer assigned one sample to ranges spanning as many as three to five octaves. The
pipeline now accepts explicitly configured source-octave variants, validates each numeric patch ID
against the exact 31-byte YM2610 identity, rejects variants that do not serve actual target-track
notes, enforces a BRR budget, and makes `vgm2mml.py` select the nearest source-note anchor at each
key-on. `tools/sound/fm_octave_variants.json` adds five Main BGM 1 anchors:
`p16@o5`, `p21@o4`, `p11@o6`, `p22@o6` (also used by identical `p18`), and `p14@o4`.
The extra BRR payload is 2,376 bytes; all 40 old base WAVs remain byte-identical.

The consolidated project now has 45 FM instruments plus 12 drums. `tad-compiler check` and the
combined blob build pass. Exact-v130 SPC ARAM matches the expected 47,886-byte common block
(`55999723…`) and 8,196-byte song-3 block (`2d0d603a…`) byte for byte, with 1,030 bytes before the
`$F000` echo buffer. An organic 29.985-second capture advances 902 ticks, remains active from start
to end, has no internal 200 ms or 750 ms quiet interval, and ends at halt zero. These checks prove
generation, fit, load, transport, and digital continuity—not that the new timbres sound right.

#### Mode 7 boot activity screen

The formerly black multi-minute initialization now displays original, non-arcade-derived assets:
a red/gold/blue SA-1 shield rotates in Mode 7 behind `SUPERMAN ROM LOADED`,
`SA-1 68000 CORE ACTIVE`, and `ARCADE BOOT IN PROGRESS`. The 5A22 owns this temporary display;
each NMI advances a phase through a 64-entry matrix table over 128 VBlanks while the SA-1
continues the unchanged original boot.
The changing animation is a liveness indicator, not a fabricated progress percentage or a claim
about which internal RAM/ROM test is executing.

The generated 32 KiB asset SHA-256 is
`7abed7112d3f1ef36c2191f307f2b02674321af9e24a7081d408df7ec34d8f04` and contains 56 static text
sprites. A fresh exact-Mesen power-on samples frames 150-450 in Mode 7 at brightness 15, forced
blank clear, halt zero, tick zero, and 11 distinct screenshot hashes; the activity byte changes
from `$82` at frame 150 to `$98` at 300 and `$AE` at 450. At the game-renderer handoff, the boot
activity byte is cleared before normal ownership; Mode 1 begins by frame 5,150, reaches tick 135 /
render 130 by frame 5,400, and never leaves a forced-blank pulse.

#### Exact v130 combined result

Exact v130 playtest-candidate ROM SHA-256:
`1ec22cbc92ad7beef0e20d8af6ff12f57023b7c437311f4bc6be56ce37cdd928`.

| Gate | Exact-v130 result |
|---|---:|
| Build/layout | 4 MiB production ROM; pack/layout assertions green |
| `TESTFLAG=0` power-on | gates arm organically; real coin/Start; gameplay settled |
| Cold-boot endpoint | frame 5,976 / tick 423 / halt `$0000`; 154-byte minimum observed stack margin |
| Post-TAITO title | 201 exact-Mesen samples; Mode 1, brightness 15, no forced blank, halt zero |
| Coin/Start/charge sequence | all 10 checks green; charged entry/continuation/tick hooks 2/2/321 |
| Mesen sequence endpoint | frame 7,946 / tick 1,408 / render 1,347 / halt `$0000` |
| Mesen gameplay WAV | 10.682 s active; no internal 200 ms or 750 ms quiet interval |
| First-wall context replay | frame 12,372 / tick 3,622 / 14 valid stacks / halt `$0000` |
| Idle enemy offense | health 20→18; attack record active; halt `$0000` |
| Organic audio capture | 29.985 s / 902 ticks / no 200 ms or 750 ms internal quiet interval |
| SPC ARAM oracle | common and Main BGM 1 byte-exact; 1,030-byte headroom |

The power-on run is a reachability/settle smoke. Its short post-arm ratios are not a formal
performance result, and none of the checkpointed rows above are FPS evidence.

Primary evidence:

- `build/user-playtest-v105-investigation/production-v130-mode7-wall-audio-coldboot-settle-v1/`
- `build/user-playtest-v105-investigation/v130-wall-bg-reconcile-helpers-v1/`
- `build/user-playtest-v105-investigation/v130-mode7-boot-mesen211-early-v3/`
- `build/user-playtest-v105-investigation/v130-mode7-boot-mesen211-handoff-v2/`
- `build/user-playtest-v105-investigation/v130-mode7-title-post-taito-mesen211-v1/`
- `build/user-playtest-v105-investigation/v130-mesen211-full-reported-sequence-v1/`
- `build/user-playtest-v105-investigation/v130-wall-context-regression-mesen211-v1/`
- `build/user-playtest-v105-investigation/idle-combat-v130-mode7-wall-audio-v1/`
- `build/user-playtest-v105-investigation/v130-organic-octave-audio-v1/`
- `docs/history/handoffs/FIRST_WALL_OCTAVE_AUDIO_AND_BOOT_20260723.md`

#### R10 verdict

v130 supersedes v128 as the combined first-wall/audio/boot **playtest candidate**. Automated and
controlled checks close the reproduced wall corruption, prove encounter AI can attack, prove the
new audio data loads continuously, and prove the Mode 7 indicator hands the display back cleanly.
They do not establish a complete stage, a crash-free playthrough, musical fidelity, exact MAME
pixel fidelity, renderer conservation, or the formal 30 Hz budget. The tester still needs to hit
the first wall, listen to the first-stage instruments, and judge the boot screen on this exact
hash. The correct project label remains **interactive technical demo, not playable or shippable**.

### R11 — Second v130 playtest and renderer/view/boot response

#### Human v130 rejection

The second v130 run did not reach the first wall. Picking up and throwing a crate froze first; in
another attempt, killing a silver enemy with a held charged punch/energy shot froze. Superman's
punch/kick animation sometimes displayed unrelated tiles, the SNES view showed the upper-left
part of the arcade scene instead of its center, and the rotating boot shield caused dizziness.
These reports supersede R10's v130-candidate verdict. Exact v130 is human-rejected.

#### Static supplied logo and centered playfield

`/home/chad/data/sa1-logo.png` is a usable 1536x1024 RGB source image with SHA-256
`091e5831c949a8c686e35ff8ba1e77fccd4bbbf0b6ed173c821bd9494516b3c6`. The generator embeds a
reproducible 120x80, 92-color indexed derivative; the private source path is not required at build
time. All 64 Mode 7 matrices are identical and NMI never writes M7A-D. It changes only one palette
color for an 8x8 amber activity diamond. In the fresh exact-Mesen capture at frames 200 and 300,
the changed-pixel bounding box is exactly that diamond `(228,192)-(236,200)`; the logo is static.

MAME 0.287 reports a 384x240 screen, so the centered 256x224 SNES window begins at arcade `(64,8)`.
At R11, BG1 added 64 horizontal pixels and used vertical scroll zero; R14 later supersedes that
zero-only policy for the post-boss vertical section. Legacy and packed OBJ consumers subtract 64
from X and use `232 - ((sy + 14) & 255)` modulo 256. The producer keeps signed
non-negative X in the 16-pixel overlap interval `49..255`. MAME register inspection confirmed that
X1-001 bit 8 is the signed-X bit, not a right-side extension.

The exact centered packed manifest is independently rebuilt at 20 settled production boundaries:
all six-byte record lengths, bytes, visibility decisions, and source ordering match with zero
manifest mismatch. One raw work-plane handoff transient is deliberately reported but is outside
the `--manifest-only` gate; this is checkpointed predicate evidence, not FPS.

#### Displayed-slot reclamation quarantine

The exact v130 bad-animation checkpoint showed an internally exact code-to-VRAM mapping while OAM
still referred to the preceding cache generation. The high-water reclaimer could place those
displayed physical slots back on the free stack, allocate them to new codes, and upload replacement
pixels before the new OAM DMA. The PPU then briefly drew the old Superman/enemy OAM with unrelated
new pixels.

The reclaimer now decodes every physical slot named by the displayed OAM and marks it unavailable
before rebuilding the hash/free stack. A first attempt used `$7E8602,Y`, but 65816 has no
absolute-long,Y encoding; Poppy silently encoded a bank-local access. The validator caught the
displayed slots in the free list, and the retained implementation uses absolute-long,X with the
OAM cursor preserved in direct page.

Two forced-full-cache variants on the final ROM are green: all 12 physical slots named by the
20-entry displayed OAM prefix are marked; none enters the 104-slot free stack or 12-slot upload
queue; and the hash, VRAM, CGRAM, OAM, PPU state, and positioned OAM render remain byte-identical.
This proves the focused reclamation invariant, not organic full-stage stability.

#### Exact v131 evidence and remaining target

Exact v131 response-candidate ROM SHA-256:
`be0ed971b90ce4ce48e0c6b1ad3356eba41c5b12484c11506154ce40dbe8c1aa`.

| Gate | Exact-v131 result |
|---|---:|
| Build/layout | 4 MiB production ROM; pack/layout and bank audits green |
| Static logo | exact Mesen frames 200/300 differ only in the 8x8 activity diamond |
| Centered producer predicate | 20/20 boundaries; packed bytes/order exact |
| Displayed-slot quarantine | 12/12 marked; displayed/free and displayed/upload intersections empty |
| `TESTFLAG=0` cold boot | organic gates and real coin/Start; frame 5,982 / tick 426 / halt `$0000` |
| Fresh Mesen title samples | frames 5,650-5,800; brightness 15; no forced blank; progress continues |
| Mesen transition and two charges | frame 8,177 / tick 1,524 / render 1,472 / halt `$0000` |
| Encounter offense | health 20→18 in the fresh same-hash sequence |
| Focused crate hold/throw | visible action states 10→7; tick 1,483 / halt `$0000`; renders continue |

The crate replay begins from an exact-v130 Mesen gameplay checkpoint, then explicitly refreshes the
state-restored `$7F:8000-$AFFF` supervisor/renderer mirror from the selected exact-v131 ROM before
driving the real controller sequence. It is focused current-renderer evidence, not an organic v131
stage run. The fresh same-hash Mesen sequence proves two ordinary charged releases remain live, but
it does not reproduce the tester's exact charged shot killing a silver enemy. That target-specific
freeze remains open until reproduced or human-cleared.

Primary evidence:

- `build/user-playtest-v105-investigation/v131-final-static-logo-mesen211-v1/`
- `build/user-playtest-v105-investigation/v131-centered-obj-manifest-nexen-v3/`
- `build/user-playtest-v105-investigation/v131-obj-displayed-slot-quarantine-nexen-v10/`
- `build/user-playtest-v105-investigation/v131-final-coldboot-settle-v2/`
- `build/user-playtest-v105-investigation/v131-final-title-mesen211-v1/`
- `build/user-playtest-v105-investigation/v131-final-mesen211-full-sequence-v1/`
- `build/user-playtest-v105-investigation/v131-box-regression-mesen211-v1/`
- `docs/history/handoffs/V130_SECOND_PLAYTEST_20260723.md`

#### R11 verdict

v131 supersedes human-rejected v130 only as the current **response candidate**. The static boot
logo, centered transform, manifest predicate, displayed-slot cache invariant, fresh boot, generic
charge path, encounter offense, and focused crate path have bounded evidence. The exact
silver-enemy charged kill, the first wall on this hash, a human v131 run, musical timbre, renderer
conservation, aligned MAME pixels, a full stage/playthrough, and formal 30 Hz gates remain open.
The correct label remains **interactive technical demo, not playable or shippable**.

### R12 — v131 rejection and title/crate/right-edge response

#### Human v131 correction

The next user run supersedes R11's v131 response-candidate verdict. Throwing the crate still
froze, Superman disappeared at the visible right edge of the centered window, and the title words
were incoherent. These are direct Mesen 2.1.1 observations against the supplied candidate.

#### Title OBJ-capacity repair

The arcade title's six legal-text rows contain 149 overlapping 16x16 OBJ records. That exceeds
both the SNES 128-OBJ frame cap and its 34 OBJ tiles per scanline limit, so no cache or ordering
repair could preserve that representation exactly.

The producer now recognizes the exact post-TAITO composition with three distant code/Y signatures,
removes only the six text rows from its packed manifest, and tags the immutable snapshot. The 5A22
copies the same packed private glyph tiles to BG2 and draws the six rows there, leaving 97 title
artwork objects in OAM. Two over-width legal lines are fit to 32 columns by omitting one trailing
comma and replacing `AND` with `&`; every word is now complete. A first Poppy build encoded the
same-bank long font-table read in bank zero; the final source explicitly selects physical bank
`$E9`.

The final production ROM's stock-Mesen-2.1.1 run starts from power-on and uses no runtime pokes.
Frames 5,680/5,700/5,720/5,740 remain Mode 1 with BG1+BG2+OBJ, brightness 15, no forced blank, and
halt zero; ticks advance 275→305 and completed renders 254→281. Visual inspection confirms all six
lines are coherent.

#### Crate continuation repair

Exact v131 stops at tick 1,288 after reaching `$98:80C9`, then executes `RTI` into `$00:0000`.
Poppy reset mode inference at generated label `br23342_1`. The intended 16-bit
`LDA #br23342_2; STA $40` became `A9 D1 85 40`; under M=16, `$85` was consumed as the high
immediate and `$40` executed as `RTI`. Explicit `.a16/.i16` declarations produce
`A9 D3 80 85 40 A9 FB 00 85 42 4C 00 84`. ROM packing now asserts the labels and full byte string.

The `$02429C` task root is exact in 18/18 retained-fixture variants against MAME 0.287: all D/A
registers, CCR, interrupt mask, mapped work RAM, and bounded native-return residue match. This gate
correctly uses a `PC_RING=1` diagnostic ROM; an earlier production-ROM invocation ran past the
NOPed terminal hook and is not counted. The normal production build was restored byte-for-byte
afterward.

The production-ROM exact-Mesen replay starts immediately before the old crate failure and advances
tick 1,265→1,480 and completed renders 1,164→1,370. Halt remains zero, all 13 initialized task
stacks are valid, and the minimum margin is 138 bytes. Two speculative interpreter return guards
failed this same replay and were removed; they are not part of v132.

#### Wrapped right edge

R11's raw-X conclusion was incomplete. X1-001 bit 8 is signed, but the device renders the sprite
in both 512-pixel buckets. Raw `$100-$13F` therefore supplies arcade X `256..319`, the rightmost 64
pixels of the centered crop. The producer and validators now retain raw `$031-$13F`, and the
legacy/packed consumers no longer sign-extend that wrapped-right interval before subtracting the
64-pixel crop origin.

An exact-Mesen drive advances tick 1,480→1,572 and renders 1,370→1,411 with halt zero and valid
stacks. A captured intermediate visibly retains Superman at the far-right boundary behind the
copper pipe; his later coordinate 336 is legitimately beyond the crop. A synthetic boundary gate
retains `$031/$0FF/$100/$13F` and rejects `$030/$140`.

One packed-snapshot mirror-refresh run records a stale first consumer followed by seven exact
samples. Its aggregate remains red 7/8 and is retained as negative evidence; it does not close the
inherited renderer-conservation failure.

#### Exact v132 evidence and remaining target

Exact v132 response-candidate production SHA-256:
`48d7c4d6c6a431e8c2066410e325888d70aec9d15b7261903ddc4f8effd476a2`.

| Gate | Exact-v132 result |
|---|---:|
| Production build/layout | 4 MiB ROM; pack/layout assertions green; rebuild byte-identical |
| `$02429C` diagnostic differential | 18/18 exact MAME/Nexen variants |
| Crate failure replay | tick 1,265→1,480; render 1,164→1,370; halt `$0000`; stacks valid |
| Wrapped-right drive | far-right player visible; tick 1,480→1,572; halt `$0000` |
| Fresh-power-on title | six coherent rows; frames 5,680-5,740; Mode 1 BG1+BG2+OBJ; halt `$0000` |
| Title-state coin/Start continuation | overlay clears; pre-round frame 6,491 / tick 681; halt `$0000`; stacks valid |
| Packed-snapshot refresh diagnostic | red 7/8; first consumer stale |
| Formal FPS / complete playthrough | not run |

Primary evidence:

- `build/user-playtest-v105-investigation/v131-fresh-crate-throw-crash-v1/`
- `build/user-playtest-v105-investigation/v132-final-2429c-mode-fix-differential-v4.json`
- `build/user-playtest-v105-investigation/v132-final-crate-mode-fix-mesen211-v2/`
- `build/user-playtest-v105-investigation/v132-final-right-edge-mesen211-v2/`
- `build/user-playtest-v105-investigation/v132-title-fontdma-final-mesen211-fresh-v1/`
- `build/user-playtest-v105-investigation/v132-final-title-coin-start-handoff-mesen211-v2/`
- `build/user-playtest-v105-investigation/v132-final-packed-obj-right-edge-nexen-v2/`
- `docs/history/handoffs/V132_TITLE_CRATE_RIGHT_EDGE_20260723.md`

#### R12 verdict

v132 supersedes human-rejected v131 only as the current **response candidate**. The reproduced
crate continuation, title capacity, and wrapped-right visibility defects have bounded evidence.
The tester must still cold-boot this exact hash and verify all three. The exact charged shot
killing a silver enemy, first wall on this hash, timbre, renderer conservation, aligned MAME
pixels, full stage/playthrough, and formal performance remain open. The correct label remains
**interactive technical demo, not playable or shippable**.

### R13 — v132 title/attract rejection and non-rotating zoom response

#### Human v132 correction

The first exact-v132 human run supersedes R12's response-candidate verdict. The legal text was now
readable, but briefly became pixelated about once per second. With no input, attract music began
and the game then froze on `INSERT COIN`. The lower-right counter was also clipped to `CRE`. The
tester requested that the temporary SA-1 Mode 7 screen start with a very large logo and shrink,
without restoring the rotation that caused dizziness.

#### Title BG2 register ownership

The v132 framewise reproduction showed that the title font, tilemap, source palette, staged
palette, and live CGRAM were byte-stable during the corrupt frame. The actual transient was
`BG12NBA`: ordinary `bg_upload` selected `$01` while the previous completed BG2 title remained
visible, so BG2 temporarily read character base `$0000` instead of its font at `$6000`. The title
overlay restored `$61` only when the next multi-video-frame render completed.

The ordinary uploader now retains `$61` throughout. In the exact-v133 stock-Mesen-2.1.1
fresh-power capture, every frame from 5,700 through 5,900 remains visible at brightness 15 and halt
zero. Tick advances 285→385 and completed render 264→349. The legal rows and credit region each
have one identical nonblack-pixel mask across all 201/201 frames, including the formerly corrupt
frame 5,756. Whole-screen one-pixel variants are confined to the title sparkle.

#### Empty prepared-background sort

The rejected v132 idle-attract capture stops around frame 7,910 at tick 1,389 / completed render
1,170 with halt zero, task mask `$4003`, and physical SA-1 PC `$9E:DF9F` in
`rpb_sort_shift`. `rpb_sort_outer` initialized Y to two, then used equality against the byte length
at `$0146`. For a zero-length prepared background, Y had already passed the terminal and the
insertion sort wrapped through the 16-bit address space. MAME 0.287 continued changing state
through the corresponding no-input interval, so this was a port-side terminal error.

The terminal is now unsigned `Y >= length` (`BCS`), which also correctly treats one-entry lists as
already sorted. ROM packing asserts the exact comparison/branch bytes. The exact-v133
fresh-power lineage continues from the title through the old terminal:

| Video frame | Game tick | Completed render | Halt | Task mask |
|---:|---:|---:|---:|---:|
| 7,910 | 1,389 | 1,171 | `$0000` | `$4003` |
| 7,940 | 1,405 | 1,187 | `$0000` | `$4003` |
| 9,000 | 1,726 | 1,493 | `$0000` | `$FDFF` |

The screenshots advance from `INSERT COIN` into the demo and `GAME OVER`; this is a bounded
no-input attract result, not a playthrough.

#### Credit-label exception

The established centered crop keeps ordinary raw X `$031-$13F`. The title credit records instead
place codes `$007D-$0080/$008B` at bottom-row Y `$0A`, raw X `$120-$160`; the crop therefore
discarded the latter glyphs. Only those code/Y/X signatures now move left 48 pixels while being
packed. Adjacent solid-border records and every ordinary title/gameplay object retain the existing
crop. The exact title and attract screenshots show complete `CREDIT 0`, with the final digit at
screen X 249..254. All three Python renderer oracles pass the same 6/6 focused
credit/adjacent/gameplay/boundary cases.

#### One-shot Mode 7 zoom

The generated boot matrix table now contains 64 strictly increasing identity matrices from
A=D=`$0020` to A=D=`$00C0`; B=C=0 in every entry. NMI consumes the table once, latches the fitted
state, and never restarts it. The activity diamond's palette pulse continues after the logo
settles. The final boot asset SHA-256 is
`e8d6b5f6c3d77d646eaa695c47d1e74c2c040a56e24d359fa067c3d749ea8734`.

An exact-v133 fresh-power Mesen capture shows an extreme close-up at frame 17, an intermediate
size at frame 50, and the fitted static logo by frame 86. The packer asserts both matrix endpoints,
all zero off-diagonal coefficients, strict monotonicity, and code/data seams.

#### Exact v133 evidence and remaining target

Exact v133 response-candidate production SHA-256:
`15465fe67b458eee08eeb2fe235362e5986378f22f60bf96b1d22e662a53cac5`.

| Gate | Exact-v133 result |
|---|---:|
| Production build/layout | 4 MiB ROM; pack/layout assertions green |
| Fresh title framewise capture | 201 frames; legal/credit masks stable 201/201; halt `$0000` |
| Fresh-lineage idle attract | frame 5,900→9,000; tick 385→1,726; render 349→1,493; halt `$0000` |
| Old v132 terminal | passed at frame 7,910 / tick 1,389; continued scenes/ticks/renders |
| Credit predicate | 6/6 focused cases in each of three renderer validators |
| Fresh Mode 7 zoom | frames 17/50/86 show huge/intermediate/fitted; no rotation |
| Formal FPS / interactive stage / audio listening | not run |

Primary evidence:

- `build/user-playtest-v105-investigation/v132-human-reject-title-framewise-v1/`
- `build/user-playtest-v105-investigation/v132-human-reject-idle-attract-coarse-v1/`
- `build/user-playtest-v105-investigation/v133-final-fresh-title-mesen211-v1/`
- `build/user-playtest-v105-investigation/v133-final-fresh-lineage-attract-mesen211-v1/`
- `build/user-playtest-v105-investigation/v133-final-boot-zoom-mesen211-fresh-v1/`
- `docs/history/handoffs/V133_TITLE_ATTRACT_BOOT_20260723.md`

#### R13 verdict

v133 supersedes human-rejected v132 only as the current **response candidate**. The demonstrated
brief title corruption, idle-attract terminal, credit clipping, and requested non-rotating zoom
have bounded exact-Mesen evidence. Wrong player-animation tiles, crate/silver-enemy/wall behavior
on this hash, musical fidelity, renderer conservation, aligned MAME pixels, a complete
stage/playthrough, and formal performance remain open. The correct label remains **interactive
technical demo, not playable or shippable**.

### R14 — v133 Stage 2 vertical-scroll rejection and v134 response

#### Human v133 correction

The tester cleared the first boss on v133 and reached the following vertical section. Superman and
the rest of the scene remained interactive, but moving to the top did not move the playfield
upward. This is the first human report beyond Stage 1 and supersedes v133's response-candidate
verdict.

#### Missing X1-001-to-BG1 bridge

The arcade game had not stopped producing camera state. X1-001 scrolly lives at CPU
`$D00401 + column*$20`, mirrored at SNES `$41:3401 + column*$20`. The SNES renderer discarded it:
the full uploader wrote `BG1VOFS=0`, while the fast and incremental paths updated only
`BG1HOFS`; the existing two-byte snapshot/queue field carried only horizontal state.

MAME 0.287 computes `sy = -(scrolly + yoffs) + row*16`, and Superman sets the no-flip background
Y offset to `-1`. With the centered crop beginning at arcade Y=8, the corresponding SNES value is
`(scrolly + 7) & $ff`. Stage 1's `$F9` maps to zero, explaining why the omission remained hidden.

A retained MAME drive with explicit invincibility and enemy/boss state edits reaches the vertical
scene and shows multiple simultaneous column groups. At frames 6,000 and 6,120, columns 4-11
advance `$EB→$FB`; their SNES offsets are `$F2→$02`. Because SNES BG1 has one global Y register,
v134 explicitly follows arcade column 4, the first column of that large center-playfield group.
This restores global camera motion but does not claim exact per-column fidelity; an exact port of
those simultaneous offsets would require HDMA or a different renderer.

The accepted vertical byte is packed into the low byte of the established two-byte scroll mailbox;
the original raw horizontal byte stays in the high byte. All four legacy/direct/primary/secondary
snapshot producers and all full/fast/incremental consumers use that packed word, so no queue grows.
The exact post-TAITO title signature forces vertical zero. ROM packing asserts the helper bytes,
four producer calls, three consumer calls, two-write PPU publication, title guard, and owned-island
seams.

#### Exact v134 evidence and remaining target

Exact v134 response-candidate production SHA-256:
`782ae58fe5b6d05fd23bb0d50e306fc3186fe12c1cca7e1be8703286313f85c0`.

| Gate | Exact-v134 result |
|---|---:|
| Production build/layout | 4 MiB ROM; pack/layout assertions green |
| Nexen real-65816/PPU bridge lab | 8/8, including two MAME-derived per-column Stage 2 values |
| Exact-Mesen Stage 1 checkpoint | frame 7,512→7,645; tick 1,192→1,258; render 1,124→1,183; halt `$0000` |
| Stage 1 alignment/safety | sampled scrolly `$F9`; `BG1VOFS=0`; 14/14 stacks valid; 138-byte minimum margin |
| Fresh-power Mesen title sample | 11/11 frames 5,700-5,900 at `BG1VOFS=0`; tick 285→385; render 264→349; halt `$0000` |
| Organic SNES Stage 2 / formal FPS / audio listening | not run |

Primary evidence:

- `build/stage2-scroll-oracle-cheat/drive.log`
- `build/user-playtest-v105-investigation/v134-vertical-scroll-final-nexen/report.json`
- `build/user-playtest-v105-investigation/v134-vertical-scroll-stage1-mesen211-v3/`
- `build/user-playtest-v105-investigation/v134-vertical-scroll-fresh-title-mesen211-v3/`
- `docs/history/handoffs/V134_STAGE2_VERTICAL_SCROLL_20260724.md`

#### R14 verdict

v134 supersedes human-rejected v133 only as the current **response candidate**. The missing
vertical-scroll transport and its Stage 1/title regressions have bounded exact-core evidence. The
organic post-boss scene, visual acceptability of the global center-column approximation, wrong
player-animation tiles, crate/silver-enemy/wall behavior on this hash, musical fidelity, renderer
conservation, aligned MAME pixels, a complete playthrough, and formal performance remain open.
The correct label remains **interactive technical demo, not playable or shippable**.

### R15 — v134 SA-1 IRAM-freeze/HUD/audio rejection and v135 response

#### Human v134 correction

The tester supplied `build/playtest/frozen.mss` after a gameplay freeze and reported that v134
also froze when left on the no-credit main screen. The same test successfully threw a crate and a
charged energy ball, found the top score HUD incomplete, and heard no noticeable improvement from
R10's source-octave audio pass. The state is SHA-256
`71b7939a43c5f4b8d983555add16793485eb9cb6a8b6122bd5df5a1e1e3c15f7`; those observations
human-reject exact v134 without erasing its bounded Stage 2 bridge evidence.

#### Accidental block move through SA-1 IRAM

The supplied state has game tick zero, task mask zero, and almost all 2 KiB of SA-1 IRAM zero,
while the independent video supervisor and last scene remain. It is neither a normal `$DEAD` halt
nor an SA-1 reset. An exact-v134 neutral-input replay independently reaches the same IRAM-erased
terminal at Mesen frame 12,002. Reset-entry and reset-control hooks remain silent.

A narrowed same-frame replay catches sequential zero writes through bank `$A9` and the SA-1 at
`$98:80B1`, DBR `$A9`. Poppy had reset accumulator-width inference at generated branch
`Lf23342_1`. Exact v134 bytes `$A9 $C6 $85 $54 $A9 $FB` intended a 16-bit load/store, but the
live M=16 CPU consumed `$85` as the immediate high byte and then decoded operand `$54` as `MVN`.
The accidental block move erased the IRAM mirror. Because this is a shared `$023342` task branch,
it accounts for both gameplay and attract failures without assigning the freeze to one object.

v135 replaces that exact 24-byte site with a long jump and padding to unused `$98:8F5E-$8F79`.
The out-of-line bridge pins `.a16/.i16`, preserves `br23342_1=$80C6` and
`br23342_2=$80D3`, publishes the real return PC, and enters the unchanged `$02380C` callee.
Exact ROM assertions cover the redirect, bridge bytes, continuation addresses, and both seams.

#### Top-HUD wrap

The centered producer had rejected arcade Y `$F0-$FF` and side X values outside `$031-$13F`.
That removed the X1-001 wrapped rows containing `1UP`, `HIGH SCORE`, `2UP`, and all three score
rows. v135 admits only the additionally visible `$F0-$F2` interval and compacts only fixed HUD
rows `$E2/$F2`: left X below `$040` moves right 48 pixels, right X `$120-$16F` moves left 24,
and centered records retain the normal crop. A fixed 5A22 helper maps `$E2` to OAM row 8 and
`$F0-$F2` through the top sprite wrap. Ordinary gameplay and the existing bottom-credit predicate
remain unchanged.

#### Exact v135 evidence

Exact v135 response-candidate production SHA-256:
`5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`.

| Gate | Exact-v135 result |
|---|---:|
| Production build/layout | 4 MiB ROM; pack/layout assertions green |
| Exact-Mesen old-terminal replay | 2,400 video frames, frame 11,588→13,988; no terminal |
| SA-1 liveness | tick 2,107→2,519; IRAM nonzero 462→475; halt `$0000`; task mask `$FFCF→$FFFF` |
| Checkpointed HUD replay | frame 7,645→7,799; tick 1,258→1,335; render 1,183→1,259; halt `$0000` |
| HUD population/safety | packed OBJ records 75→88; all labels/scores visible; 14/14 stacks valid; 138-byte minimum margin |
| MML/blob provenance | prior MML was regenerated/compiled; 96,065-byte blob SHA `64f58ef…` is packed at `$2D002B` |
| Human audio verdict | no noticeable improvement from the five-anchor pass; v135 audio unchanged |
| Cold boot / organic Stage 2 / full stage / formal FPS | not run |

The freeze replay uses a last-healthy exact-v134 checkpoint with the final v135 ROM selected. It
passes the reproduced frame-12,002 terminal by 1,986 frames and retains changing ticks/IRAM. The
HUD replay explicitly refreshes the selected ROM's video mirror; its final paused-state analyzer
decodes all 88 packed records, and its screenshot shows the complete top labels/scores plus
`CREDIT 3`. The queue-backed checkpoint did not hit the direct-DMA equivalence hook, so that
attempt is not counted.

Primary evidence:

- `build/user-playtest-v105-investigation/v134-user-frozen-state-initial-v1/`
- `build/user-playtest-v105-investigation/v134-idle-iram-wipe-trace-mesen211-v2/`
- `build/user-playtest-v105-investigation/v134-idle-iram-wipe-timedburst10ms-mesen211-v7/`
- `build/user-playtest-v105-investigation/v135-final-idle-iram-wipe-regression-mesen211-v2/`
- `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/`
- `docs/history/handoffs/V135_IRAM_FREEZE_HUD_AUDIO_20260724.md`

#### R15 verdict

v135 supersedes human-rejected v134 only as the current **response candidate**. It repairs the
reproduced common IRAM erasure and restores the observed missing HUD rows, but the final exact hash
has not completed a human stage, a fresh cold-boot soak, organic Stage 2, renderer conservation,
or a formal rate/budget run. The audio pass is now human-rejected rather than “awaiting listening.”
The correct label remains **interactive technical demo, not playable or shippable**.

## Decision rule after the baseline

R15 supersedes R14's v134-response verdict while preserving R7's exact v124 formal performance
evidence, R8's charged-shot diagnosis, R9's renderer-conservation failure, and R10-R14's bounded
wall/audio/boot/cache/title/attract/scroll evidence. Preserve the production evidence contract:
local/checkpointed/idle-attract improvements remain scoped evidence, while a new playability claim
requires another power-on uninterrupted gameplay run plus a human combat/audio playtest. Continue
under the honest label **interactive technical demo, not playable or shippable**. v135 is the
current response candidate; do not resurrect human-rejected v130/v131/v132/v133/v134, the
rejected pre-wake DMA ordering, v125/v126, or project a local result into FPS.
