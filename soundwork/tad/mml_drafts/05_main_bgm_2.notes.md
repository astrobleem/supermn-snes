# Main BGM 2 — vgm2mml conversion notes

- Source VGM: `05 Main BGM 2.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 32.19s; loop start 19.58s (tick 2178); loop length 12.61s
- Tempo: **139 BPM**, auto-detected (mean grid error 0.233 tick); candidates [152, 165, 170]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 222 | 2-3 | fm_p28 |
| B | FM1 | 71 | 4-6 | fm_p29 |
| C | FM2 | 43 | 3-6 | fm_p31 |
| D | FM3 | 271 | 4-5 | fm_p30 |
| E | ADPCM-A ch4 | 6 | 4-4 | (drum kit, see below) |
| F | ADPCM-A ch5 | 115 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_060000 | 0x060000-0x0629FF | 10752 | 23 | [5] |
| @11 sm_drum_062a00 | 0x062A00-0x0651FF | 10240 | 30 | [5] |
| @12 sm_drum_067800 | 0x067800-0x069EFF | 9984 | 19 | [5] |
| @13 sm_drum_069f00 | 0x069F00-0x06C4FF | 9728 | 41 | [5] |
| @14 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 8 | [4, 5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
