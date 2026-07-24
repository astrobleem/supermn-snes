# v134 Stage 2 vertical-scroll response — July 24, 2026

> **Superseded candidate notice:** the next human test rejected exact v134 after gameplay and
> no-credit attract freezes, missing top score HUD text, and no noticeable audible improvement
> from the earlier octave pass. Preserve the bounded vertical-scroll evidence below, but use
> [V135_IRAM_FREEZE_HUD_AUDIO_20260724.md](V135_IRAM_FREEZE_HUD_AUDIO_20260724.md) and
> `RECOVERY.md` R15 for the current exact-v135 response candidate.

## Human correction

The first long v133 gameplay run reached the vertical section after the first boss and exposed a
new hard failure: Superman could move to the top of the 256x224 window, but the playfield never
scrolled upward. This supersedes v133 as the current response candidate. It does not invalidate
v133's bounded title, attract, credit, or Mode 7 evidence.

Exact v134 production ROM SHA-256:

`782ae58fe5b6d05fd23bb0d50e306fc3186fe12c1cca7e1be8703286313f85c0`

Packaged playtest ROM:

`build/playtest/superman-snes-v134-782ae58f.sfc`

The correct project label remains **interactive technical demo, not playable or shippable**.
The tester must still confirm the vertical section organically on this exact hash.

## Root cause

The game was already writing X1-001 per-column vertical-scroll bytes to the video shadow at
CPU `$D00401 + column*$20`, mirrored on SNES at `$41:3401 + column*$20`. The SNES renderer
discarded them:

- the full BG upload wrote `BG1VOFS=0`;
- the unchanged-background fast path updated only `BG1HOFS`;
- the incremental-render completion path updated only `BG1HOFS`; and
- the two-byte render-queue scroll field carried only the raw horizontal-scroll word.

The frozen camera was therefore a renderer bridge omission, not evidence that the 68000 game
logic had stopped computing Stage 2 camera motion.

MAME 0.287's `x1_001.cpp` computes each column as
`sy = -(scrolly + yoffs) + row*16`. Superman configures the no-flip background Y offset as `-1`.
The established centered SNES crop begins eight arcade scanlines down, so the equivalent global
SNES offset is:

`BG1VOFS = (scrolly - 1 + 8) & $ff = (scrolly + 7) & $ff`

The older `BG1VOFS=0` happens to be correct for Stage 1's normal `$F9` value because
`($F9 + 7) & $ff = 0`; that coincidence hid the missing bridge until the vertical section.

## Stage 2's per-column behavior

The retained MAME drive at `build/stage2-scroll-oracle-cheat/drive.log` reaches the post-boss
vertical scene with invincibility and enemy/boss state edits. It is a behavior-oracle trace, not
an organic playthrough. It proves that Stage 2 does not keep all 16 X1-001 columns equal:

| MAME frame | columns 0-3 | columns 4-11 | columns 12-15 |
|---:|---:|---:|---:|
| 5,040 | `$B2` | `$6B` | `$F9` |
| 6,000 | `$F2` | `$EB` | `$F9` |
| 6,120 | `$7A` | `$FB` | `$F9` |
| 6,240 | `$02` | `$0B` | `$F9` |

The SNES has one global BG1 Y register and cannot reproduce independent per-column Y positions.
v134 follows arcade column 4, the first column of the large center-playfield group. In the two
retained wrap-adjacent examples this publishes `$F2` and then `$02`, so camera motion continues
through the eight-bit boundary. This is an explicit approximation; exact per-column fidelity
would require HDMA or a different renderer.

The exact post-TAITO title composition remains signature-gated to vertical zero. This prevents
later gameplay camera support from moving or destabilizing the title layer.

## Implementation

`src/video.pasm` now:

- packs accepted vertical offset in the low byte and the existing raw horizontal value in the
  high byte of the established two-byte scroll mailbox;
- captures that packed word in the legacy, paced-direct, primary-queue, and secondary-queue
  producer paths;
- applies both axes in full BG uploads, unchanged-background fast dispatch, and incremental
  completion; and
- performs two explicit `BG1VOFS` writes, avoiding the shared PPU scroll-latch failure reproduced
  by the isolated Nexen lab.

No render-queue structure grew. The snapshot substitutions are size-neutral, and the new helpers
occupy owned renderer islands. `tools/build_interp_rom.py` asserts the exact helper bytes, all four
producer call sites, all three consumer paths, the title guard, the PPU write sequence, and the
surrounding zero seams.

Both Mesen playtest tools now retain BG1 H/V offsets, the packed mailbox, sampled X1-001 Y values,
and title metadata in their result JSON.

## Exact-v134 evidence

| Gate | Result |
|---|---|
| Production build/layout | green; 4 MiB `TESTFLAG=0` ROM; all pack/layout assertions green |
| Nexen real-65816/PPU bridge lab | 8/8 |
| Stage 1 checkpoint regression | green; frame 7,512→7,645, tick 1,192→1,258, completed render 1,124→1,183, halt zero |
| Stage 1 vertical alignment | X1 sampled columns remain `$F9`; BG1 vertical remains zero |
| Stage 1 scheduler safety | 14/14 initialized task stacks valid; 138-byte minimum observed margin |
| Fresh Mesen 2.1.1 title sample | 11/11 samples at frames 5,700-5,900: Mode 1, brightness 15, no forced blank, halt zero, BG1 vertical zero |
| Fresh title liveness | tick 285→385; completed render 264→349; complete title/credit text remains visible |
| Organic Stage 2 on SNES | not run; requires human v134 retest |
| Formal rate/budget and audio listening | not run |

The isolated bridge report is
`build/user-playtest-v105-investigation/v134-vertical-scroll-final-nexen/report.json`. It executes
the production helpers on Nexen's real 65816 and PPU core. Its synthetic cases include Stage 1
`$F9→$00`, a general changing value, byte wrap, two per-column Stage 2 patterns from the MAME
trace, actual BG1 H/V publication, and the exact-title zero guard. This is component evidence,
not gameplay or performance evidence.

The Stage 1 Mesen 2.1.1 checkpoint result is
`build/user-playtest-v105-investigation/v134-vertical-scroll-stage1-mesen211-v3/results.json`.
It loads a retained state, refreshes the selected ROM's `$7F:8000-$AFFF` video mirror, and uses
real controller input. It is checkpointed liveness/alignment evidence, not cold-boot or FPS
evidence.

The fresh-power title capture is
`build/user-playtest-v105-investigation/v134-vertical-scroll-fresh-title-mesen211-v3/`.
It uses the stock Mesen 2.1.1 binary with SHA-256
`22f714b4e01358eb758750329124a620db9ea42cad0a7b69fc4fa6447442676f` and performs no runtime
memory pokes.

## Human retest target

Cold-boot the exact v134 hash and verify:

1. the existing title, attract, credit, and one-shot non-rotating boot zoom remain acceptable;
2. Stage 1 retains its established vertical alignment;
3. after the first boss, moving toward the top causes the Stage 2 playfield to move vertically;
4. the vertical scene does not show an unacceptable seam from the global center-column
   approximation; and
5. gameplay remains live through the remainder of that scene.

Wrong Superman attack-animation tiles, crate/silver-enemy/wall behavior on this exact hash,
musical timbre, renderer conservation, aligned MAME pixels, a full playthrough, and the formal
30 Hz / 358K gates remain open.
