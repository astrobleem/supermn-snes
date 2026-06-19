---
name: vgm-to-tad-mml
description: Convert YM2610/OPNB (and similar OPN-family) VGM/VGZ chiptune rips into Terrific Audio Driver (TAD) SNES MML drafts plus compile-checkable .terrificaudio projects, and extract/decode ADPCM-A sample data. Use when the user wants to port arcade VGM music to SNES/SPC700, convert a VGMRips pack to MML, build TAD song/instrument data from VGM register logs, or decode YM2610 ADPCM drums. Triggers include "convert these VGMs to MML", "port this arcade soundtrack to SNES", "VGM to TAD", "decode the YM2610 samples", or pointing at .vgz/.vgm files with SNES/TAD context. Built and verified for the Superman (Taito X System) pack; the YM2610 path is general.
---

# VGM → TAD MML conversion (YM2610 / OPN family)

Convert arcade VGM register logs into editable SNES MML for the Terrific Audio Driver. The
heavy mechanical work — decoding every note at correct pitch, timing, tempo/quantization, the
loop point, and drum placement — is automated. Timbre, dynamics, and final tempo confirmation
are a human/agent musical pass afterward.

The tools live in `tools/sound/` (Python 3, stdlib only). On Windows run with `PYTHONUTF8=1`.

## Before anything: understand what you're converting

A `.vgm`/`.vgz` is a timed log of sound-chip register writes, **not** MIDI. Confirm the chip
and what it actually uses before trusting any layout assumption:

```bash
python3 tools/sound/vgm_header_report.py soundwork/source/vgm_unpacked/*.vgm
python3 tools/sound/vgm_profile.py "soundwork/source/vgm_unpacked/<track>.vgm"
```

`vgm_profile.py` is the ground-truth scout: it reports which FM / SSG / ADPCM-A / ADPCM-B
channels and registers the track really uses. (For the Superman pack the answer is: 4 FM
voices + ADPCM-A percussion, no SSG, no ADPCM-B — a clean fit for TAD's 8 voices.)

## Run the pipeline

One command (unpack zip → header report → convert all → compile-check → extract drums):

```bash
python3 tools/sound/convert_pack.py --zip <pack>.zip --out soundwork \
    --tad <path-to>/tad-compiler.exe --check --samples
```

Or per track, iterating:

```bash
V="soundwork/source/vgm_unpacked/<track>.vgm"
python3 tools/sound/vgm_ym2610.py  "$V"          # validate: notes cluster on semitones
python3 tools/sound/vgm2mml.py     "$V" -o soundwork/tad/mml_drafts   # --bpm N if rhythm wrong
python3 tools/sound/vgm_extract_adpcm.py "$V" -o soundwork/samples    # drum WAVs
tad-compiler check  soundwork/tad/mml_drafts/<stem>.terrificaudio
tad-compiler song2spc -o out.spc soundwork/tad/mml_drafts/<stem>.terrificaudio s<stem>
```

## What the converter emits per track

- `<stem>.mml` — 8-voice MML (FM voices A–D, ADPCM-A drum voices E+) with octaves, rests,
  ties, bar comments, and the loop marker `L`. Compiles as-is against the stub project.
- `<stem>.notes.md` — tempo (and how found), loop point, per-voice summary, the FM-instrument
  and drum-sample work lists, and the auto-conversion's known limits.
- `<stem>.terrificaudio` — a TAD project binding every instrument to a **placeholder** sample
  with correct octave ranges. Compiles + fits ARAM immediately; swap `source`/`freq` for real
  samples. (`instruments/placeholder.wav` + a per-track `*.sfx_stub.txt` are written too.)

## The manual pass (do not skip — it's the musical part)

1. **Confirm tempo.** Auto-detect can pick a half/double tempo. If a draft's rhythm reads
   wrong against the reference VGM render, re-run `vgm2mml.py --bpm N`.
2. **Build FM instruments.** Render each FM patch to a looped WAV (MAME/ymfm), or substitute a
   similar sample. Set `freq` to true pitch; keep octave ranges tight.
3. **Build drums.** `vgm_extract_adpcm.py` decodes Yamaha ADPCM-A (not generic IMA) to WAV;
   trim short (≤~250 ms), don't normalize each independently, encode to BRR.
4. **Balance & polish.** FM velocity isn't transcribed (flat `v`); set per-voice volumes,
   echo, vibrato/portamento by ear against the reference.

## Key facts (for debugging the decoder)

- OPN pitch: `f = fnum * clock / (144 * 2^(21-block))`; `fnum=((hi&7)<<8)|lo`, `block=(hi>>3)&7`.
  Decoded notes should land on equal-tempered semitones (`vgm_ym2610.py` reports cents error).
- YM2610 FM uses key-on selectors {1,2,5,6} (channels 0/4 of each part are disabled).
- ADPCM-A key-on: port-1 register 0x00, per set channel bit, keys **on when bit 7 == 0**.
- ADPCM-A sample ROM = VGM type-0x82 data blocks; payload = `u32 rom_size, u32 start, bytes`.

## Full bring-up context

`supersoundhandoff.md` is the end-to-end TAD integration runbook (vendoring TAD, engine glue,
instrument building, track order, rights notes). `CONVERTSOUND.md` / `SOUNDHARDWARE.md` cover
the VGM/ADPCM formats and the arcade hardware.
