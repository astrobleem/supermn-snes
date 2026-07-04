# Boss BGM 3 — vgm2mml conversion notes

- Source VGM: `09 Boss BGM 3.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 38.51s; loop start 0.69s (tick 72); loop length 37.82s
- Tempo: **128 BPM**, auto-detected (mean grid error 0.211 tick); candidates [124, 128, 169]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 201 | 2-3 | sm_fm0 |
| B | FM1 | 269 | 3-6 | sm_fm1 |
| C | FM2 | 109 | 3-4 | sm_fm2 |
| D | FM3 | 60 | 3-3 | sm_fm3 |
| E | ADPCM-A ch5 | 92 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_062a00 | 0x062A00-0x0651FF | 10240 | 36 | [5] |
| @11 sm_drum_067800 | 0x067800-0x069EFF | 9984 | 36 | [5] |
| @12 sm_drum_075800 | 0x075800-0x0778FF | 8448 | 8 | [5] |
| @13 sm_drum_079a00 | 0x079A00-0x07B4FF | 6912 | 12 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
