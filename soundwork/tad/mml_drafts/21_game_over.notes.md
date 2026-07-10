# Game Over — vgm2mml conversion notes

- Source VGM: `21 Game Over.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 7.52s; loop start 0.00s (tick 0); loop length 0.00s
- Tempo: **76 BPM**, auto-detected (mean grid error 0.175 tick); candidates [76, 93, 144]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 26 | 2-2 | fm_p06 |
| B | FM1 | 20 | 3-5 | fm_p57 |
| C | FM2 | 20 | 4-5 | fm_p57 |
| D | FM3 | 20 | 4-5 | fm_p57 |
| E | ADPCM-A ch3 | 3 | 4-4 | (drum kit, see below) |
| F | ADPCM-A ch4 | 26 | 4-4 | (drum kit, see below) |
| G | ADPCM-A ch5 | 20 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_065200 | 0x065200-0x0677FF | 9728 | 26 | [4] |
| @11 sm_drum_06c500 | 0x06C500-0x06F8FF | 13312 | 1 | [3] |
| @12 sm_drum_075800 | 0x075800-0x0778FF | 8448 | 5 | [5] |
| @13 sm_drum_077900 | 0x077900-0x0799FF | 8448 | 15 | [5] |
| @14 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 2 | [3] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
