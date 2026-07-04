# Boss BGM 1 — vgm2mml conversion notes

- Source VGM: `04 Boss BGM 1.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 20.81s; loop start 1.90s (tick 126); loop length 18.91s
- Tempo: **82 BPM**, auto-detected (mean grid error 0.196 tick); candidates [165, 152, 102]; folded 165->82 BPM into TAD's 40-157 range
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 59 | 1-5 | sm_fm0 |
| B | FM1 | 41 | 3-5 | sm_fm1 |
| C | FM2 | 67 | 4-5 | sm_fm2 |
| D | FM3 | 66 | 5-5 | sm_fm3 |
| E | ADPCM-A ch5 | 40 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_062a00 | 0x062A00-0x0651FF | 10240 | 28 | [5] |
| @11 sm_drum_067800 | 0x067800-0x069EFF | 9984 | 12 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
