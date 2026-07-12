# Round Clear — vgm2mml conversion notes

- Source VGM: `07 Round Clear.vgm`
- Chip: YM2610B @ 8000000 Hz
- Duration: 7.32s; loop start 0.00s (tick 0); loop length 0.00s
- Tempo: **93 BPM**, auto-detected (mean grid error 0.155 tick); candidates [93, 76, 110]
- Grid: ZenLen 192, snapped to 1/32-note grid, 4/4 assumed

## Voices

| MML | Source | Notes/Hits | Octaves | Instrument stub |
|----|--------|-----------:|---------|-----------------|
| A | FM0 | 27 | 2-3 | fm_p10 |
| B | FM1 | 5 | 4-5 | fm_p37 |
| C | FM2 | 5 | 3-5 | fm_p37 |
| D | FM3 | 47 | 4-5 | fm_p33 |
| E | ADPCM-A ch4 | 5 | 4-4 | (drum kit, see below) |
| F | ADPCM-A ch5 | 20 | 4-4 | (drum kit, see below) |

## FM instruments to build (4 melodic voices)

Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a looped WAV, or substitute a similar SNES sample. Set `freq` to the sample's true pitch and tighten `first_octave`/`last_octave` to the range above.

## ADPCM-A drum samples to extract

Extract these windows from the type-0x82 sample-ROM blocks (see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.

| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |
|-----------|-----------|------:|-----:|-----------|
| @10 sm_drum_060000 | 0x060000-0x0629FF | 10752 | 14 | [5] |
| @11 sm_drum_062a00 | 0x062A00-0x0651FF | 10240 | 5 | [5] |
| @12 sm_drum_079a00 | 0x079A00-0x07B4FF | 6912 | 3 | [4] |
| @13 sm_drum_07b500 | 0x07B500-0x07F1FF | 15616 | 3 | [4, 5] |

## Known limitations of the auto-conversion

- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a held note are not transcribed (add `MP`/portamento by ear).
- Note velocity/volume is not derived from FM TL; all voices emit a flat `v` — balance against the reference WAV.
- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.
- Drum durations are gate-only (until next hit); they retrigger as one-shots.
- 4/4 time is assumed for bar comments only; it does not affect playback.
