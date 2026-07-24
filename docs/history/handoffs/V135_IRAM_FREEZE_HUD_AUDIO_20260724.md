# v135 SA-1 IRAM-freeze and top-HUD response — July 24, 2026

## Human correction

The first exact-v134 human run supplied a frozen Mesen 2.1.1 save state and established four
pieces of current project truth:

- gameplay could still freeze;
- the same class of freeze could occur on the no-credit main/attract screen;
- the top score HUD was missing;
- the earlier source-octave audio pass produced no noticeable improvement to the tester.

The same run successfully picked up and threw a crate and released a charged energy ball without
freezing. Those are useful positive observations for that run, but they do not prove those paths
universally stable.

The supplied state is `build/playtest/frozen.mss`, SHA-256
`71b7939a43c5f4b8d983555add16793485eb9cb6a8b6122bd5df5a1e1e3c15f7`. It belongs to exact v134
ROM SHA-256 `782ae58fe5b6d05fd23bb0d50e306fc3186fe12c1cca7e1be8703286313f85c0`.

Exact v135 response-candidate ROM SHA-256:

`5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`

Packaged playtest ROM:

`build/playtest/superman-snes-v135-5aac64b6.sfc`

The correct label remains **interactive technical-demo response candidate, not playable or
shippable**.

## What the supplied freeze contained

The state is not a normal game halt and not a reset. At Mesen frame 27,131:

- the game tick and task mask are both zero;
- almost all 2 KiB of SA-1 IRAM is zero;
- the SA-1 is executing the zero-page `BRK`/`RTI` aftermath;
- the 5A22 video supervisor and the last rendered scene remain present; and
- the saved display contains the mixed-tile appearance expected after renderer/interpreter state
  was destroyed.

An exact-v134 neutral-input replay reproduced the same failure organically at frame 12,002.
Execution hooks saw neither the SA-1 reset entry nor the SNES SA-1 reset-control bit. A narrowed
write trace instead caught sequential zero writes through SA-1 bank `$A9`, the SA-1 IRAM mirror.

The final 10 ms replay burst caught the SA-1 at bank `$98`, PC `$80B1`, DBR `$A9`, while IRAM
nonzero bytes fell from 465 to 45 during the same video frame. Exact v134 contains these bytes at
`$98:80AE`:

`A9 C6 85 54 A9 FB ...`

The source intended a 16-bit `LDA #br23342_1` followed by `STA $54`. Poppy reset its inferred
accumulator width at generated branch label `Lf23342_1` and emitted an 8-bit immediate. The live
path still had M=16, so the CPU consumed `$85` as the immediate's high byte. The following `$54`
then became opcode `MVN`, with `$A9,$FB` as its bank operands, and the accidental block move
zeroed the live IRAM address space.

This rare branch is inside the shared native `$023342` task path. It explains why the failure was
not tied specifically to the crate, charged shot, or one particular title action.

Evidence:

- `build/user-playtest-v105-investigation/v134-user-frozen-state-initial-v1/`
- `build/user-playtest-v105-investigation/v134-idle-iram-wipe-trace-mesen211-v2/`
- `build/user-playtest-v105-investigation/v134-idle-iram-wipe-timedburst10ms-mesen211-v7/`

## Freeze repair

`src/escbank4.pasm` keeps the original 24-byte `$98:80AE-$80C5` footprint and all subsequent
continuation addresses fixed. That footprint now performs one long jump plus padding to a
previously unused `$98:8F5E-$8F79` bridge. The bridge declares `.a16` and `.i16` explicitly,
publishes the real `br23342_1=$80C6` return PC, pushes the existing bank-`$00FB` sentinel, and
enters the unchanged `$02380C` call path.

The production packer now asserts:

- the exact redirect bytes and 24-byte footprint;
- the exact 16-bit bridge encoding;
- the fixed `br23342_1=$80C6` and `br23342_2=$80D3` continuations; and
- zero seams on both sides of the new bridge.

### Exact-v135 regression

The final exact-v135 ROM replayed a last-healthy exact-v134 attract checkpoint for 2,400 Mesen
2.1.1 video frames:

| Measurement | Start | End |
|---|---:|---:|
| Mesen frame | 11,588 | 13,988 |
| Game tick | 2,107 | 2,519 |
| SA-1 IRAM nonzero bytes | 462 | 475 |
| Halt word | 0 | 0 |
| Task mask | `$FFCF` | `$FFFF` |

There were no reset, IRAM-clear, or terminal events, and sampled SA-1 PCs remained live. The run
passed v134's reproduced frame-12,002 terminal by 1,986 frames while ticks and task state
continued to change.

An earlier freeze-fix-only ROM, SHA-256 `6b4cddae24dd3d1bcdcbc297060a40425cf442ab609be78bd7006384624e4dae`,
also survived a 6,000-frame replay and advanced tick 2,107→3,082. That longer result isolates the
bridge, but it is not the packaged v135 ROM and is not used as v135 whole-ROM evidence.

Final-ROM evidence:

`build/user-playtest-v105-investigation/v135-final-idle-iram-wipe-regression-mesen211-v2/`

These are deterministic checkpoint regressions for the reproduced IRAM erasure. They are not a
fresh cold boot, gameplay playthrough, crash-freedom proof, or performance measurement.

## Missing top HUD

The centered 384-to-256 crop introduced in v131 discarded two legitimate wrapped X1-001 HUD
regions:

- producer Y `$F2` contains `1UP`, `HIGH SCORE`, and `2UP`;
- producer Y `$E2` contains the three score rows;
- left-side source X values begin below `$040`; and
- right-side source X values extend through `$150`.

The old producer rejected Y `$F0-$FF` and its ordinary centered-X predicate rejected both side
regions. MAME's X1-001 renderer draws a vertically wrapped copy, so the lower half of these
16×16 character cells is visible at the top of the arcade frame.

v135 admits only Y `$F0-$F2` in addition to the old `$01-$EF` interval and applies narrow
HUD-only mappings:

- on Y `$E2/$F2`, raw left X below `$040` moves right by 48 pixels;
- on Y `$E2/$F2`, raw right X `$120-$16F` moves left by 24 pixels;
- centered `HIGH SCORE` records keep the ordinary crop;
- Y `$E2` maps to SNES OAM row 8; and
- Y `$F0-$F2` uses the sprite-wrap copy, exposing its glyph pixels at rows 0-7.

All non-HUD records replay the exact existing `$031-$13F` gameplay predicate. The earlier
signature-tight bottom `CREDIT` translation is unchanged.

### Exact-v135 HUD evidence

A selected-ROM checkpoint replay in stock Mesen 2.1.1 advanced frame 7,645→7,799 and game tick
1,258→1,335 at halt zero. All 14 initialized task stacks remained valid with a 138-byte minimum
observed margin. After the exact v135 renderer mirror was selected, the packed OBJ manifest grew
from 75 to 88 records. The final paused-state analyzer independently decoded those 88 records and
found all three label groups and all three score groups at their intended top-screen positions.
The final screenshot visibly contains `1UP`, `HIGH SCORE`, `2UP`, their score rows, and the
existing complete `CREDIT 3`.

Evidence:

- `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/results.json`
- `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/final.png`
- `build/user-playtest-v105-investigation/v135-hud-full-top-band-mesen211-v3/final-obj-analysis.json`

This replay explicitly refreshes the selected ROM's video mirror and is checkpointed HUD/liveness
evidence. The queue-backed state did not reach the direct-DMA equivalence hook, so that attempted
gate is not counted. This is not a cold-boot renderer-conservation or aligned-pixel verdict.

## Was the MML recompiled?

Yes. Commit `9b39f95` regenerated and changed the Main BGM MML and Terrific Audio project data,
including:

- `soundwork/tad/mml_drafts/03_main_bgm_1.mml`;
- `soundwork/tad/mml_drafts/08_main_bgm_3.mml`;
- their `.terrificaudio` projects; and
- the FM instrument/source-octave configuration.

The resulting compiled `soundwork/tad/build/audio-data.bin` is 96,065 bytes, SHA-256
`64f58ef6086d690428dc67805e1fe74ecfdc7118bfb8f1a0a2edf7885054eb1a`. Those exact bytes occur
in v135 at ROM file offset `$2D002B`.

That proves regeneration, compilation, and ROM packing. It does not prove the pass sounded better.
The user's v134 listening result—no noticeable difference—is now the authoritative outcome for
that five-anchor pass. v135 does not change the MML, samples, instruments, or compiled audio blob.
The audio work remains musically rejected/incomplete and needs an arcade-reference listening and
transcription pass rather than another claim based on byte checks.

## Human retest target

Cold-boot exact v135 and check:

1. leave the no-credit title/attract sequence running past the former freeze;
2. confirm the full top score HUD remains visible during gameplay;
3. play through ordinary attacks, crate use, charged shots, the first wall, and the first boss;
4. confirm whether Stage 2 now scrolls vertically;
5. note any remaining wrong animation tiles or new mixed-tile frames; and
6. treat the music as unchanged from v134 for this build.

No v135 result restores the word **playable**. Renderer conservation, exact graphics fidelity,
attack-animation tiles, musical transcription/timbre, full-stage and full-playthrough stability,
and the formal 30 Hz / 358K gates remain open.
