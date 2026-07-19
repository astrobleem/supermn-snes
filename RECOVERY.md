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

## Decision rule after the baseline

Performance remains the project gate, and R5 has now fired the no-go rule for a playable 30 Hz port
on the measured architecture. Preserve the project as an interactive technical demo and a reusable
MC68000 interpreter/transpiler/differential toolchain. Graphics fidelity and the unfinished audio
listening pass may be pursued only under that honest scope; they do not change the playability
verdict. Reopening a full-port campaign requires new whole-system evidence that clears both the
ordering and 358K-cycle gates above, not a projection from partial functions.
