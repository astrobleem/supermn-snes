# Main BGM 3 — vgm2mml conversion notes

- Source VGM: `08 Main BGM 3.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 91.97s; loop start 1.56s (tick 162); loop length 90.42s
- Tempo: **130 BPM**, auto-detected (mean grid error 0.238 tick); candidates [76, 90, 152]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 376 | 2-5 | fm_p17 |
| B | FM1 | 331 | 4-6 | fm_p21 |
| C | FM2 | 617 | 3-7 | fm_p15 |
| D | FM3 | 433 | 2-7 | fm_p20 |
| E | ADPCM-A ch5 | 316 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @14 sm_drum_060000 | 0x060000-0x0629FF | 10752 | 145 | [5] |
| @15 sm_drum_062a00 | 0x062A00-0x0651FF | 10240 | 88 | [5] |
| @16 sm_drum_065200 | 0x065200-0x0677FF | 9728 | 26 | [5] |
| @17 sm_drum_067800 | 0x067800-0x069EFF | 9984 | 9 | [5] |
| @18 sm_drum_069f00 | 0x069F00-0x06C4FF | 9728 | 25 | [5] |
| @19 sm_drum_06f900 | 0x06F900-0x0727FF | 12032 | 5 | [5] |
| @20 sm_drum_077900 | 0x077900-0x0799FF | 8448 | 4 | [5] |
| @21 sm_drum_079a00 | 0x079A00-0x07B4FF | 6912 | 4 | [5] |
| @22 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 10 | [5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
