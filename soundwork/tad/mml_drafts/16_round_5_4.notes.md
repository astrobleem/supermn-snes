# Round 5-4 — vgm2mml conversion notes

- Source VGM: `16 Round 5-4.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 22.49s; loop start 0.82s (tick 102); loop length 21.67s
- Tempo: **152 BPM**, auto-detected (mean grid error 0.219 tick); candidates [152, 84, 107]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 60 | 2-2 | fm_p47 |
| B | FM1 | 22 | 3-5 | fm_p41 |
| C | FM2 | 266 | 4-5 | fm_p30 |
| D | FM3 | 253 | 4-5 | fm_p30 |
| E | ADPCM-A ch5 | 63 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_069f00 | 0x069F00-0x06C4FF | 9728 | 60 | [5] |
| @11 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 3 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
