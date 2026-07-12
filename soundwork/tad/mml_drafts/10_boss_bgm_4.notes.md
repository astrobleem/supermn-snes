# Boss BGM 4 — vgm2mml conversion notes

- Source VGM: `10 Boss BGM 4.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 20.39s; loop start 0.69s (tick 48); loop length 19.70s
- Tempo: **84 BPM**, auto-detected (mean grid error 0.185 tick); candidates [84, 183, 114]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 97 | 2-3 | fm_p40 |
| B | FM1 | 73 | 2-5 | fm_p25 |
| C | FM2 | 76 | 4-5 | fm_p30 |
| D | FM3 | 75 | 3-4 | fm_p30 |
| E | ADPCM-A ch5 | 38 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_069f00 | 0x069F00-0x06C4FF | 9728 | 31 | [5] |
| @11 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 7 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
