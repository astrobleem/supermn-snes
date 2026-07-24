# Authoritative Superman project status

Last evidence review: July 24, 2026.

This is the only authoritative project-status summary. Dated reports under
`docs/history/` retain the evidence and failed experiments behind it, but their
“current,” “playable,” and “next” labels are historical.

## Verdict

The port is an **interactive technical-demo response candidate**. It is **not
playable, release-ready, or shippable**.

The current candidate is v135:

- production ROM size: 4,194,304 bytes;
- SHA-256:
  `5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`;
- implementation commit: `b3b6e21` (later ROM-preparation work does not change the
  candidate bytes);
- usual build output: `build/interp.sfc`;
- preserved local playtest copy:
  `build/playtest/superman-snes-v135-5aac64b6.sfc`.

Both local ROM copies matched that exact hash during this documentation audit.
Neither binary is tracked by Git.

## What v135 proves

- It repairs the reproduced v134 SA-1 IRAM erasure. A generated `$023342` path had
  been assembled with an 8-bit immediate while live execution was M=16, turning the
  following `$54` operand into accidental `MVN $A9,$FB`.
- An exact-Mesen 2.1.1 regression advanced from frame 11,588 to 13,988 and game tick
  2,107 to 2,519 across the old terminal, with halt zero and live IRAM/task state.
- A separate checkpointed renderer test restored the cropped top HUD: its 88-record
  packed OBJ manifest and screenshot contain `1UP`, `HIGH SCORE`, `2UP`, all score
  rows, and the full credit label. All 14 initialized stacks remained valid with a
  138-byte minimum margin. That test disclosed a 12 KiB same-ROM video-mirror refresh;
  it is not an organic fresh-boot result.

Those are bounded cause-and-regression results. They do not prove a fresh cold boot,
an organic Stage 2 run, a complete stage, general crash freedom, renderer
conservation, or a full playthrough.

## Evidence audit used for this status

The July 24 documentation audit checked the claims above against the retained raw
artifacts, not only prior prose:

| Claim | Raw evidence checked |
|---|---|
| v135 size/hash | `build/interp.sfc` and the preserved playtest copy: both 4,194,304 bytes and exact SHA-256 above |
| v135 old-terminal liveness | `build/user-playtest-v105-investigation/v135-final-idle-iram-wipe-regression-mesen211-v2/terminal-events.json`: frame 11,588→13,988, tick 2,107→2,519, halt zero, no terminal event |
| v135 HUD | `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/results.json` plus final screenshot: tick 1,258→1,335, render 1,183→1,259, 88 records, 14 valid stacks, 138-byte minimum, disclosed mirror refresh |
| v124 production | exact local v124 ROM hash plus `build/user-playtest-v105-investigation/production-v124-26a0-ordered-coldboot-uninterrupted-3600f-v1/baseline.jsonl` and its hashed hook/debt streams |
| Interpreter counts | retained `optest-final.log` SHA-256 `93470844…` and `opsweep-final.log` SHA-256 `f0e935df…`, reconciled in Recovery R6/R7 |

Those `build/` paths are private local evidence and are not required to exist in a
fresh clone. The committed recovery/handoff documents below retain their hashes and
scope.

## Latest formal performance evidence

No v135 formal performance run exists. The latest end-to-end measurement satisfying
the evidence protocol is exact v124, SHA-256
`777507c9ecba8b7911dae882ea266cca7d173d918dde65b73f880acdb0451352`.
It began at power-on with `TESTFLAG=0`, armed production organically, used the real
controller mailbox, validated the real `$00:F5A3` tick boundary, included waits,
IRQs, rendering, input, sound supervision, and state transitions, and crossed the
known scheduler-ordering region.

| Metric | Formal v124 result |
|---|---:|
| Emulated SNES video frames | 3,602 |
| Game ticks | 1,783 |
| Game rate | **29.700167 game-fps** |
| SA-1 cycles | 643,645,462 |
| Mean SA-1 cycles/tick | **360,990.164** |
| Requests / unit ACKs / true draws | 1,783 / 1,782 / 1,782 |
| Final tick / halt / task mask | 2,210 / `$0000` / `$FFF1` |
| Initialized task stacks / minimum margin | 14 / 138 bytes |

It failed both formal gates: `29.700167 < 30` and `360,990.164 > 358,000`.
The one-request endpoint lag was an in-flight transaction, not a skipped ACK.
This remains useful near-30 Hz scheduler/performance evidence, not a playable
verdict for v124 or v135.

## Subsystem status

| Area | Current truth |
|---|---|
| MC68000 interpreter | Implements the legal MC68000 instruction set and runs on SA-1. Latest retained semantic gates are optest 160/160 and opsweep 782/782 cells (1,564/1,564 vectors), plus focused lockstep evidence. This is not proof of every unvisited whole-program address path. |
| Native escapes/HLE | Many focused and live differentials are green. Repeated human failures show that a correct local differential does not prove whole-game control flow, layout, or stability. |
| Combat | The v124 `$012B6C` return-PC repair passed 35/35 focused MAME cases and 4/4 live combat-spine differentials; attack, jump, and controlled enemy damage work. Later candidates inherited those paths, but the exact charged-shot kill of a silver enemy has never been independently reproduced or cleared. |
| Stability | v135 closes one reproduced common IRAM-erasure cause. It has not passed a fresh cold-boot attract/gameplay soak, a complete stage, or a full playthrough. |
| Rendering | The game is recognizable and v135 restores the top HUD. Burst conservation remains red: the retained exact-v128 checkpoint produced 568 true renders for 600 ticks/requests/ACKs and 31 new queue coalesces. Wrong Superman attack-animation tiles remain reported. |
| Stage 2 scrolling | v134/v135 carry one center-column X1-001 vertical value to global SNES BG1 scroll. The real Stage 2 scene has multiple simultaneous column values; organic behavior and visual acceptability remain untested. |
| Audio | Organic command transport and TAD loading work. The VGM-derived five-octave-anchor pass was genuinely regenerated, compiled, and packed, but the human verdict was “no noticeable improvement.” Music/SFX remain musically incomplete. |
| Private-input preparation | `tools/prepare_roms.py` authenticates the World ROM set and exactly derives the 68K image, graphics image, C-Chip response, and 12 drums. The 45 FM authoring WAVs still require the external VGM/ymfm pipeline or the preserved private set. |
| Hardware | Emulator evidence exists for Nexen and exact Mesen 2.1.1. No real-cartridge/FXPak SA-1 acceptance result is recorded. |

## Current release blockers

The concise prioritized list is in [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md). The
highest-risk items are:

1. fresh v135 human and automated cold-boot/attract/gameplay stability;
2. renderer conservation and wrong attack-animation tiles;
3. organic Stage 2 scrolling;
4. by-ear VGM-to-TAD transcription/timbre and real SFX;
5. a new formal power-on performance run on the eventual candidate; and
6. a complete playthrough, aligned MAME graphics comparison, and release-hardware scope.

## Evidence sources

- [R15 freeze/HUD/audio handoff](../history/handoffs/V135_IRAM_FREEZE_HUD_AUDIO_20260724.md)
- [Recovery ledger R0-R15](../history/recovery/RECOVERY.md)
- [Confession/correction ledger](../history/recovery/CONFESSION.md)
- [Performance campaign](../history/performance/PROFILE_CAMPAIGN.md)
- [v124 formal baseline entry](../history/recovery/RECOVERY.md#formal-v124-production-result)

When new evidence changes a statement above, update this file and the focused evidence
report in the same change. Preserve the old report as dated evidence.
