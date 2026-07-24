# First-wall, octave-audio, and Mode 7 boot handoff — July 23, 2026

> **Superseded candidate notice:** the second human test rejected exact v130 after crate-throw and
> charged-silver-enemy freezes, wrong animation tiles, an upper-left crop, and dizziness from this
> document's rotating shield. Preserve the wall/audio evidence below, but use
> [V133_TITLE_ATTRACT_BOOT_20260723.md](V133_TITLE_ATTRACT_BOOT_20260723.md) and
> `RECOVERY.md` R13 for the current exact-v133 response candidate. The intermediate v131 and v132
> responses were also human-rejected.

## Verdict

Exact v130 playtest-candidate ROM SHA-256:

`1ec22cbc92ad7beef0e20d8af6ff12f57023b7c437311f4bc6be56ce37cdd928`

Packaged local ROM:

`build/playtest/superman-snes-v130-mesen211-1ec22cbc.sfc`

This ROM combines:

- the first-wall scheduler-context corruption repair;
- five note-aware source-octave FM variants;
- the retained v128 title/transition/charged-shot/music fixes; and
- an original Mode 7 activity screen during the formerly black initialization interval.

Controlled checks are green for the reproduced wall path, enemy offense, boot-screen handoff,
coin/Start/charged-shot sequence, audio continuity, and SPC ARAM bytes. This is still an
**interactive technical demo, not playable or shippable**. The first wall, perceived timbre, and
boot presentation require a human run of this exact hash. Renderer conservation, a formal 30 Hz
result, aligned MAME pixels, and a full playthrough remain open.

## User evidence accepted

The user confirmed on exact v128 in Mesen 2.1.1 that:

- post-TAITO title flicker was gone;
- the pre-round horizontal bars were gone;
- charged-shot release no longer froze; and
- gameplay music played again.

That same test found the first-wall freeze and identified excessive octave transposition as a
likely timbre problem. The user also received no enemy damage in that encounter. The focused
offense check below proves that at least one encounter path can attack and damage Superman; it does
not invalidate the report or prove every enemy.

## First-wall root cause

The v128 wall checkpoint fails at halt `$DEAD`, PC `$1000B0`, opcode `$F800`, with mixed tiles and
corrupt saved task contexts.

Both `rmb_bg_promote` and `rmb_bg_revert` had this ordering:

1. load background-list length;
2. compare it with `$0100`;
3. branch to the full path if greater/equal;
4. store the compact length;
5. `BEQ` done.

The `BEQ` consumed flags from the compare, not the load. A zero-length list entered the compact
copy loop, Y wrapped, DBR `$41` crossed into `$42`, and the SA-1's 128 KiB BW-RAM mirror reached
physical bank `$40`, where scheduler contexts live. The size-neutral repair moves `BEQ done`
immediately after each `LDA length`.

Validation:

- `tools/validate_bg_reconcile_helpers.py`: 6/6 byte-exact cases
  (promote/revert × empty/compact/full).
- `tools/trace_wall_context.py`: exact-v130 real-controller replay reaches frame 12,372 /
  tick 3,622, halt zero, 14 valid initialized stacks, 136-byte minimum margin, 2,740 recorded
  context writes, and zero suspicious high-byte writes.
- Evidence:
  `build/user-playtest-v105-investigation/v130-wall-bg-reconcile-helpers-v1/` and
  `build/user-playtest-v105-investigation/v130-wall-context-regression-mesen211-v1/`.

This is a focused replay from an exact-Mesen checkpoint, not a whole-stage soak.

## Enemy-offense check

Starting from the exact-v130 organic cold-boot gameplay state, the idle harness ran 1,800 SNES
video frames:

| Field | Start | End |
|---|---:|---:|
| Video frame | 5,976 | 7,776 |
| Game tick | 423 | 1,324 |
| Health | 20 | 18 |
| Halt | `$0000` | `$0000` |

An enemy attack record became active. The starting checkpoint caught Superman just before landing
(`Y=$FFD0`); he reached arcade ground Y `$0070` during the run, so the harness's
`player_landed_at_arcade_y_0070` start-state predicate is the only false verdict field. The offense,
damage, target-window, and no-halt predicates are true.

Evidence:
`build/user-playtest-v105-investigation/idle-combat-v130-mode7-wall-audio-v1/`.

## Octave-aware audio work

The old renderer could assign one sample across three to five octaves. The new path:

- accepts optional source-octave variants in `tools/sound/fm_octave_variants.json`;
- requires a numeric patch ID and exact 31-byte YM2610 patch identity;
- verifies that each variant serves notes actually present in the target track;
- enforces the configured BRR cap and rejects closer-timbre aliases;
- keeps base normalization independent of variants; and
- makes `tools/sound/vgm2mml.py` choose the closest source-note anchor per key-on.

Main BGM 1 adds:

| Patch | Anchor | Notes |
|---|---:|---|
| `p16` | o5 | dedicated upper-range source |
| `p21` | o4 | dedicated lower-range source |
| `p11` | o6 | dedicated upper-range source |
| `p22` | o6 | shared with byte-identical `p18` |
| `p14` | o4 | dedicated lower-range source |

The variants consume 2,376 BRR bytes under a 2,400-byte config cap. All 40 prior base FM WAVs
remain byte-identical. The consolidated project contains 45 FM instruments and 12 drums.

Exact TAD/ARAM result:

| Region | Address | Bytes | SHA-256 | Match |
|---|---:|---:|---|---|
| Common | `$10E8` | 47,886 | `55999723116264ba74cb9542fb7afc6bc1dc16ded8479b6088a190e21d643b14` | yes |
| Main BGM 1 | `$CBF6` | 8,196 | `2d0d603ada6c67a353905ee704e26e9977f7ef8d211d37a766fc60baa91322b7` | yes |

The song ends 1,030 bytes before the `$F000` echo buffer. The organic exact-v130 capture lasts
29.985 seconds, advances 902 ticks, stays active from start to end, has no internal 200 ms or
750 ms quiet interval, and ends at halt zero. WAV SHA-256:
`0e888414d740c1035b607dbbbd7adf033e7338ec52797442c7d20f8b9587a4f7`.

Evidence:
`build/user-playtest-v105-investigation/v130-organic-octave-audio-v1/`.

These results prove compilation, fit, upload, and digital continuity. They do not prove that the
octave choices sound right; compare by ear with the arcade reference.

## Mode 7 boot activity

`tools/gen_boot_screen.py` creates a 32 KiB original asset; no arcade graphics are used. It
contains:

- a 96×96 red/gold/blue SA-1 shield/diamond;
- a 64-entry Mode 7 matrix animation traversed over 128 VBlanks;
- 56 static 8×8 OBJ text sprites;
- Mode 7 map/tile data, OBJ font tiles, OAM, and CGRAM.

Asset SHA-256:
`7abed7112d3f1ef36c2191f307f2b02674321af9e24a7081d408df7ec34d8f04`.

Visible text:

```text
SUPERMAN ROM LOADED
SA-1 68000 CORE ACTIVE
ARCADE BOOT IN PROGRESS
```

The 5A22 owns the temporary screen. NMI advances the matrix phase while the SA-1 continues the
original interpreter boot. `$7E:1F1B` uses bit 7 as the active flag and the low seven bits as the
phase. The game renderer clears it before taking PPU ownership. After handoff, the extra NMI work
is only a call plus the inactive flag check.

Fresh Mesen 2.1.1 evidence:

| Frame | Mode | Activity | Tick | Render | Halt |
|---|---:|---:|---:|---:|---:|
| 150 | 7 | `$82` | 0 | 0 | 0 |
| 300 | 7 | `$98` | 0 | 0 | 0 |
| 450 | 7 | `$AE` | 0 | 0 | 0 |
| 5,000 | 7 | `$F4` | 0 | 0 | 0 |
| 5,125 | 7 | `$F1` | 0 | 0 | 0 |
| 5,150 | 1 | `$00` | 10 | 5 | 0 |
| 5,400 | 1 | `$00` | 135 | 130 | 0 |

Brightness is 15 and forced blank is clear throughout those captures. The early interval has 11
distinct screenshot hashes across 11 samples. The status text is static and the animation is a
real liveness heartbeat; it is not a decoded percentage or a claim that a particular arcade
RAM/ROM self-test is active.

Evidence:

- `build/user-playtest-v105-investigation/v130-mode7-boot-mesen211-early-v3/`
- `build/user-playtest-v105-investigation/v130-mode7-boot-mesen211-handoff-v2/`
- `build/user-playtest-v105-investigation/v130-mode7-title-post-taito-mesen211-v1/`

The uncited `v130-mode7-boot-mesen211-early-v1/` attempt requested a frame already passed while
the MCP client connected; it is a harness-range failure, not emulator evidence.

## Exact combined-ROM regression results

Mesen 2.1.1 binary SHA-256:
`22f714b4e01358eb758750329124a620db9ea42cad0a7b69fc4fa6447442676f`.

- Fresh `TESTFLAG=0` Nexen power-on organically arms production, drives the real coin/Start
  mailbox, and settles gameplay at frame 5,976 / tick 423 / halt zero. Minimum observed saved-stack
  margin is 154 bytes.
- The exact-Mesen post-TAITO capture contains 201 samples at Mode 1, brightness 15, forced blank
  clear, boot flag clear, and halt zero.
- The same-v130 title state passes all ten real-input coin/Start/Clark/charge checks. Charged-shot
  entry/continuation/tick hooks are 2/2/321; the endpoint is frame 7,946 / tick 1,408 / render
  1,347 / halt zero.
- Its 10.682-second charged-shot gameplay WAV is active throughout and has no internal 200 ms or
  750 ms quiet interval.

Evidence:

- `build/user-playtest-v105-investigation/production-v130-mode7-wall-audio-coldboot-settle-v1/`
- `build/user-playtest-v105-investigation/v130-mesen211-full-reported-sequence-v1/`

The cold-boot run is a short reachability/settle smoke. The Mesen, wall, idle-offense, and audio
runs are checkpointed or focused. None is a formal FPS result.

## Human retest checklist

Use the exact packaged ROM above in Mesen 2.1.1:

1. Confirm the Mode 7 shield keeps moving during the long initialization and disappears cleanly
   when the game first renders.
2. Wait for the no-credit title after TAITO; verify the prior black flicker remains absent.
3. Insert a coin with Select, press Start, and verify the pre-round walk has no horizontal bars.
4. Hold B/Y to charge, release the energy shot, and verify play continues.
5. Attack the first breakable wall repeatedly and verify it breaks without a freeze or mixed tiles.
6. Stand near early enemies long enough to determine whether attacks/damage feel reliable.
7. Listen closely to Main BGM 1 across low and high notes and report which instruments still sound
   stretched, wrong-octave, or discontinuous.

Controls: Select=coin, Start=start, B/Y=arcade Button 1 (punch/fire), A/X=arcade Button 2 (jump).
The arcade game has no separate kick button.

Do not call the result playable from this checklist alone. A playable verdict still needs a formal
power-on 30 Hz/cycle/ordering/renderer pass on the same exact ROM and a materially longer human
combat/audio playtest.
