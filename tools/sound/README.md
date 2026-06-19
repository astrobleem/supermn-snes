# tools/sound — Superman VGM → TAD MML converter

Converts the VGMRips **Superman (Taito X System, YM2610B)** soundtrack into
**Terrific Audio Driver** MML drafts + compile-checkable projects for the SNES port.

These are the tools referenced by `supersoundhandoff.md`. Plain Python 3, stdlib only.
On Windows, prefix commands with `PYTHONUTF8=1` (GD3 tags / output are UTF-8).

## Quick start

```bash
# Everything: unpack -> header report -> convert all 21 tracks -> compile-check -> drums
python3 tools/sound/convert_pack.py --zip VGM_SOUND_SUPERMAN.zip --out soundwork \
    --tad ../snes-outrun-sa1/tools/tad/tad-compiler.exe --check --samples
```

`--tad` points at a `tad-compiler.exe` (vendor it from the OutRun project or the TAD repo).
Omit `--check`/`--samples` to skip those stages. Output goes under `soundwork/` — gitignore
it; it's regenerated and the rips are copyrighted.

## The tools

| Script | What it does |
|---|---|
| `vgmlib.py` | VGM/VGZ container + command-stream parser (shared library). |
| `vgm_header_report.py` | `… *.vgm` → version, clock, duration, loop, GD3 title per track. |
| `vgm_profile.py` | Ground-truth: which FM/SSG/ADPCM channels & registers each track uses. |
| `vgm_ym2610.py` | YM2610 decoder → FM note events + ADPCM-A drum triggers. Run directly to validate note pitch clustering. |
| `vgm2mml.py` | **The converter.** VGM → `<track>.mml` + `<track>.notes.md` + `<track>.terrificaudio` (+ sfx stub). |
| `vgm_extract_adpcm.py` | Reconstruct ADPCM-A sample ROM, cut windows, decode Yamaha ADPCM-A → WAV. |
| `make_check_project.py` | Bind all instruments of one-or-more MMLs to a placeholder sample for a multi-song compile check. |
| `convert_pack.py` | Driver that chains the above over the whole pack. |

## Typical iterative loop (one track)

```bash
V="soundwork/source/vgm_unpacked/03 Main BGM 1.vgm"
python3 tools/sound/vgm_profile.py "$V"            # sanity: 4 FM + ADPCM-A, no SSG
python3 tools/sound/vgm_ym2610.py  "$V"            # sanity: notes cluster on semitones
python3 tools/sound/vgm2mml.py     "$V" -o soundwork/tad/mml_drafts   # add --bpm N if rhythm reads wrong
python3 tools/sound/vgm_extract_adpcm.py "$V" -o soundwork/samples    # drum WAVs
tad-compiler check soundwork/tad/mml_drafts/03_main_bgm_1.terrificaudio
tad-compiler song2spc -o /tmp/x.spc soundwork/tad/mml_drafts/03_main_bgm_1.terrificaudio s03_main_bgm_1
```

## What you get per track

- **`.mml`** — 8-voice MML: 4 FM voices (A–D) + ADPCM-A drum voices (E–…), with octaves,
  rests, ties, bar comments, and the loop marker `L`. Compiles as-is against the stub project.
- **`.notes.md`** — tempo (and how it was found), loop point, per-voice note/octave summary,
  the FM-instrument and ADPCM-A-drum work lists, and the auto-conversion's known limits.
- **`.terrificaudio`** — a TAD project binding every instrument the MML uses to a
  **placeholder** sample with correct octave ranges. Compiles + fits ARAM immediately; you
  swap `source`/`freq` for real samples. (`instruments/placeholder.wav` + a per-track
  `*.sfx_stub.txt` are generated alongside.)

## Converter flags (`vgm2mml.py`)

- `--bpm N` — override auto-detected tempo (folded into TAD's 40–157 BPM range).
- `--grid N` — quantization subdivision (default 32 = snap to 1/32 notes; use 16 for
  simpler rhythms, 48/64 to preserve faster figures).
- `--zenlen N` — MML whole-note tick resolution (default 192).

## Accuracy & limits

Verified on all 21 tracks: every track converts and `tad-compiler check` passes (21/21,
fits in audio-RAM). FM pitch is validated by confirming decoded notes cluster on
equal-tempered semitones (within a few cents). The converter is a **scaffold generator**:
pitch/timing/loop/drum-placement are mechanical and accurate; timbre, per-note dynamics,
vibrato, and final tempo confirmation are the human's musical pass (each `notes.md` says
which). See `supersoundhandoff.md` for the full bring-up runbook.
