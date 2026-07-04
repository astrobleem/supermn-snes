# Round 5-2 — vgm2mml conversion notes

- Source VGM: `14 Round 5-2.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 22.75s; loop start 0.69s (tick 84); loop length 22.06s
- Tempo: **152 BPM**, auto-detected (mean grid error 0.171 tick); candidates [152, 92, 133]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 41 | 1-5 | sm_fm0 |
| B | FM1 | 129 | 1-3 | sm_fm1 |
| C | FM2 | 131 | 4-6 | sm_fm2 |
| D | FM3 | 130 | 4-5 | sm_fm3 |
| E | ADPCM-A ch5 | 29 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_06f900 | 0x06F900-0x0727FF | 12032 | 1 | [5] |
| @11 sm_drum_075800 | 0x075800-0x0778FF | 8448 | 13 | [5] |
| @12 sm_drum_077900 | 0x077900-0x0799FF | 8448 | 1 | [5] |
| @13 sm_drum_079a00 | 0x079A00-0x07B4FF | 6912 | 14 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
