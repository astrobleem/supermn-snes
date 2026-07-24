# Mesen 2.1.1 playtest regressions — July 23, 2026

This handoff records the exact-emulator follow-up to the first v127 human playtest. The tester used
Mesen 2.1.1 and reported four distinct failures:

1. after the TAITO logo faded, the no-credit title screen flickered;
2. after coin/Start, the pre-round Clark walk showed black horizontal bars;
3. gameplay music disappeared or cut out; and
4. releasing a charged Button 1 shot still appeared to freeze and scramble tiles.

The reports were real. The first three had additional renderer/audio causes beyond R8's charged-shot
code-overlap repair. The exact ROM described below is a new **v128 playtest candidate**, not a
playable release.

## Exact candidate and emulator

- ROM: `build/interp.sfc`
- ROM SHA-256:
  `7c4b757ddf5c0297eb1b3aa65f4f6d74ecf289fdfa5f70d0d71811843906db57`
- Build mode: `TESTFLAG=0`
- Mesen binary: `/home/chad/Mesen2/bin/linux-x64/Release/Mesen`
- Mesen version: 2.1.1
- Mesen binary SHA-256:
  `22f714b4e01358eb758750329124a620db9ea42cad0a7b69fc4fa6447442676f`
- Controller transport: real Mesen port-0 controller override; no gameplay memory injection

`tools/mesen211_mcp_controller.sh` pins the controller type explicitly. Without that override the
MCP launch can inherit a non-controller port configuration, making real Select/Start/action input
appear dead.

## Root causes and repairs

### Post-TAITO title flicker

The production queue captured palette data from retired snapshot `$41:6800`. Production pacing no
longer populated that area, so a queued render could replace the live palette with zeroes. In exact
Mesen this produced roughly three visible title frames followed by about 37 black frames, repeating
while no credit was inserted.

Both renderer queue paths now copy the stable live palette at `$41:2000`. A fresh power-on capture
sampled frames 5,650 through 5,800 every ten frames, after the TAITO fade and before any input. All
16 captures have brightness 15, forced blank clear, halt zero, and a visible title/starfield.
Animation changes the screenshot hashes; the former long black interval is absent.

Evidence:
`build/user-playtest-v105-investigation/v128-tail-batching-mesen211-title-fresh-v1/`.

### Black horizontal bars and mixed transition tiles

The renderer's old DMA helper set `INIDISP=$80` immediately before every PPU DMA and restored
brightness immediately afterward. At production cadence those forced-blank pulses occurred during
active display, which exact Mesen correctly showed as horizontal black bars. Large coalesced
background uploads could also extend beyond VBlank, leaving partial or mixed VRAM data.

The helper now publishes DMA0 through private WRAM flag `$7E:1F11`. NMI services the descriptor in
VBlank after the established scheduler wake, large background runs are split into 5.75 KiB chunks,
and consecutive sub-1 KiB transfers use size-aware VBlank-tail limits. Packer assertions reserve
and audit the new `$E9:8A00-$E9:8AC3` helper island.

The exact-Mesen transition capture covers 450 video frames from real coin/Start through Clark's
walk and the round transition. Its inspected montage contains neither horizontal black bars nor
mixed tiles:
`build/user-playtest-v105-investigation/v128-tail-batching-mesen211-full-v1/montage-transition.png`.

### Music replacement after credit

Arcade command `$19` is a short credit cue mixed over the current music. The TAD transcription of
track 2 is standalone: loading it while another song was active replaced that song, then left
gameplay without the intended background track when the cue ended.

`snd_map` now leaves `$19` alone while `TadPrivate_nextSong` is nonzero. The existing `$19` mapping
is retained when no song is active, so the standalone cue remains testable. On the exact candidate,
the gameplay charge/release WAV is active for 10.51 of 10.516 seconds and contains no internal
200 ms or 750 ms digital-silence run.

This proves digital continuity, not musical accuracy. The known incomplete transcription, trimmed
samples, placeholder or ignored SFX, and missing pitch/LFO/portamento work remain open and have not
passed a by-ear comparison.

### Charged-shot release

R8's `$00D3B0` relocation remains present. The exact-Mesen sequence starts from a grounded idle
state, holds real B for 272 actual emulator frames, releases it, and observes another 360 frames.
The `$D3B0` entry and relocated continuation each fire twice, while 316 game-tick hooks occur.
The final state is frame 7,935 / tick 1,403 / render 1,342 with halt zero and both tick and renderer
progress after release. The inspected montage shows the energy projectile leaving Superman while
the player, enemies, and scene continue:
`build/user-playtest-v105-investigation/v128-tail-batching-mesen211-full-v1/montage-charge-release.png`.

Full exact-Mesen result:
`build/user-playtest-v105-investigation/v128-tail-batching-mesen211-full-v1/results.json`.

## Scheduler/renderer ordering result

Moving PPU DMA before the scheduler wake made an intermediate ROM look correct in Mesen but broke
the established producer ordering. Intermediate ROM
`0c9bf6d5c3c3b7fe1d7555d23f151dfb094be6042d7ca46bf41d36c6819eb482`
eventually halted `$DEAD` during a 3,600-frame production cold-boot run, with 1,198 frames of lost
tick progress. It is rejected.

The retained ordering is wake, pending DMA, then controller sample. A checkpointed 1,200-video-frame
Nexen window on the exact current ROM records:

| Metric | Result |
|---|---:|
| Game ticks / frame requests / ACKs | 600 / 600 / 600 |
| True completed renders | 568 |
| Final request/ACK debt / tick/ACK debt | 1 / 0 |
| Halt / minimum initialized-stack margin | `$0000` / 138 bytes |
| Real Right+B mailbox / production gates / WRAM mirror | green / green / exact |
| New renderer queue coalesces | **31 — red gate** |

The loss is burst-local, not steady-state. A traced 520-frame window records 260 ticks, 257 renders,
and three new coalesces. A prepared background transition occupies five frames; the worst observed
OBJ cache rebuild occupies eight frames because it emits 82 small DMA records. This remaining burst
bottleneck is why v128 is not promoted to playable even though the exact Mesen regression sequence
is green.

Primary Nexen evidence:

- `build/user-playtest-v105-investigation/v128-tail-batching-ordering-1200f-v1/`
- `build/user-playtest-v105-investigation/v128-tail-batching-dma-trace-520f-v1/`

`v128-tail-batching-late-500f-v1` must not be used: its checkpoint was captured inside the old
helper and restored with a stacked return address into relocated code. Its zero-render result is a
checkpoint-migration artifact, not current-ROM execution.

## Verdict

Exact v128 repairs the demonstrated Mesen 2.1.1 title flicker, transition bars/tile corruption,
credit-triggered music replacement, and charged-shot release stall in the recorded sequence. It
still fails the no-render-coalescing gate in a checkpointed Nexen burst window, has no new formal
power-on rate/budget result, and has not passed a human playtest of this exact hash. v124's
29.700167 game-fps / 360,990.164 cycles-per-tick run remains the latest formal performance evidence.

Current label: **exact-Mesen regression-fixed playtest candidate; interactive technical demo, not
playable or shippable**.
