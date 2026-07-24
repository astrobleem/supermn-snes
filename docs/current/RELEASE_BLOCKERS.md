# Superman release blockers

The current v135 candidate is not playable or shippable. This file lists what must
change or be proven before either label can return.

## Priority 0 — correctness and stability

1. **Fresh v135 cold boot and no-credit attract soak.** Leave the title/attract path
   running past the old frame-12,002 IRAM-erasure terminal. Require continuing ticks,
   renders, nonzero IRAM, halt zero, valid task masks, and all initialized stack floors.
2. **Human Stage 1 and Stage 2 retest.** Exercise ordinary attacks, charged release,
   crate pickup/throw, the first wall, the first boss, and the post-boss vertical section
   on the exact v135 hash.
3. **Complete at least one full playthrough.** Every stage, boss, continue, game-over,
   and ending path remains outside the current stability claim.
4. **Resolve wrong player-animation tiles.** Superman has displayed unrelated tiles
   during punch/attack animation. The displayed-slot quarantine fixed one cache hazard,
   but no current human result closes the symptom.
5. **Close renderer conservation.** The retained 1,200-frame burst test completed only
   568 true renders for 600 ticks/requests/ACKs and recorded 31 new coalesces. A future
   candidate must preserve scheduler ordering without silently dropping complete images.
6. **Reproduce or clear the charged-shot silver-enemy kill.** Generic charged releases
   work, but the exact human-reported target-specific freeze was never reproduced.

## Priority 1 — fidelity

1. **Stage 2 camera fidelity.** The current SNES bridge follows arcade column 4 and
   publishes one global BG1 vertical offset. The arcade scene uses several simultaneous
   X1-001 column offsets. Test the approximation organically and decide whether HDMA or
   another per-column renderer is required.
2. **Aligned MAME pixel comparison.** Recognizable output and isolated palette/tile
   oracles are not an exact same-state frame verdict. Capture aligned arcade and SNES
   states and quantify pixels, viewport, sprites, palette, and scroll.
3. **Music transcription and timbre.** Keep VGM as the source oracle, but compare all
   21 tracks by ear. Preserve pitch bends, LFO, portamento, dynamics, sample tails, and
   octave/timbre choices instead of accepting byte transport as musical proof.
4. **Real sound effects.** Enemy IDs remain ignored and most effects are placeholders.
   Validate priority and interaction with music, not only isolated playback.
5. **Boot latency and presentation.** The Mode 7 zoom/heartbeat makes the long original
   initialization visible, but startup remains long and the indicator is liveness rather
   than progress.

## Priority 2 — release evidence

1. **Formal performance on the final candidate.** Start from power-on with
   `TESTFLAG=0`, arm organically, use real input, include pacing/rendering/audio, cross
   the ordering event, and retain the raw log. The current formal reference is v124 at
   29.700167 game-fps and 360,990.164 cycles/tick, which fails both gates.
2. **Fresh full interpreter/layout gates after risky changes.** Run semantic
   differentials, bank/seam assertions, cold boot, focused lockstep, and the relevant
   renderer/sound checks.
3. **Real-hardware scope.** Decide whether emulator-only is an acceptable release
   target. No FXPak/real SA-1 result is recorded.
4. **Build reproducibility.** Parameterize hardcoded host paths and make the selected
   VGM/ymfm FM-authoring workflow reproducible enough for a fresh legal-input checkout.
5. **Rights review.** ROM-derived data stays private. Public distribution also needs a
   decision about music rights, including the John Williams-derived cues.

## Decisions Chad still owns

- Whether the Stage 2 center-column approximation is acceptable or exact per-column
  rendering is required.
- Whether to keep the boot-time `Tad_LoadSong(1)` convenience or match the arcade's
  delayed organic attract command.
- Whether real-hardware validation is mandatory for the first release.

The repository's performance contract is currently 30 game ticks/s on a 60 Hz SNES
display with a 358,000-SA-1-cycle representative-tick budget. Older 60 Hz/150K/178K
campaign targets are historical, not an unresolved status conflict.
