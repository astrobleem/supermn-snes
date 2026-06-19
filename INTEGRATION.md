# supersoundhandoff — integration guide

This package adds a **VGM → Terrific Audio Driver (TAD) MML converter** to the Superman SNES
port, plus the bring-up runbook for actually getting the game making sound. It contains only
**new files** — nothing in your existing repo is modified.

## What's in here

```
supersoundhandoff.md                      ← READ FIRST: the TAD bring-up runbook for Superman
INTEGRATION.md                            ← this file
tools/sound/                              ← the converter (Python 3, stdlib only)
    README.md                             ← tool reference + per-track workflow
    vgmlib.py                             ← VGM/VGZ parser (shared)
    vgm_header_report.py                  ← header/metadata report
    vgm_profile.py                        ← ground-truth chip-usage profiler
    vgm_ym2610.py                         ← YM2610 decoder (FM notes + ADPCM-A triggers)
    vgm2mml.py                            ← THE converter: VGM -> MML + project stub
    vgm_extract_adpcm.py                  ← reconstruct + decode ADPCM-A drum samples
    make_check_project.py                 ← multi-song compile-check helper
    convert_pack.py                       ← one-command pipeline driver
.claude/skills/vgm-to-tad-mml/SKILL.md    ← Claude Code skill that drives the pipeline
example/                                  ← sample converter output for "03 Main BGM 1"
```

## How to install

Extract this zip at the **repo root** (`E:\gh\supermn-snes`). It drops `tools/sound/`,
`.claude/skills/vgm-to-tad-mml/`, `supersoundhandoff.md`, and `INTEGRATION.md` into place.

The `example/` folder is self-contained converter output for "03 Main BGM 1" (MML + notes +
project + a placeholder sample). It compiles as-is to prove the format:
`tad-compiler check example/03_main_bgm_1.terrificaudio` → *"valid and will fit in audio-RAM"*.
Keep or delete it.

## How to run it

You need:
1. The VGMRips pack — `VGM_SOUND_SUPERMAN.zip` (already in the repo root).
2. A `tad-compiler.exe` — vendor `tools/tad/` from the OutRun project
   (`E:\gh\snes-outrun-sa1\tools\tad`) or download the TAD release. Needed only for the
   compile-check / SPC export, not for generating MML.

```bash
# Windows: prefix with PYTHONUTF8=1
python3 tools/sound/convert_pack.py --zip VGM_SOUND_SUPERMAN.zip --out soundwork \
    --tad ../snes-outrun-sa1/tools/tad/tad-compiler.exe --check --samples
```

This unpacks the rips, writes a header report, converts all 21 tracks to MML + a
compile-checkable `.terrificaudio` each, runs `tad-compiler check` on every one, and decodes
the ADPCM-A drum samples. Output lands under `soundwork/` (add it to `.gitignore` — it's
regenerated, and the rips/decoded audio are copyrighted; see the rights note in
`supersoundhandoff.md` §8).

## Status / what's proven

- All **21 tracks** convert and **`tad-compiler check` passes (21/21) and fits in audio-RAM**.
- FM pitch decoding is validated (decoded notes cluster on equal-tempered semitones).
- The full chain **VGM → MML → `.spc`** has been exercised with `song2spc`.

## What's automated vs. what's manual

The converter is a **scaffold generator**. It accurately does the mechanical work: every FM
note (correct pitch + timing), tempo estimation + quantization, the loop point, and ADPCM-A
drum placement. It does **not** invent timbres, dynamics, or vibrato — those are the musical
pass. Each track's `notes.md` lists exactly what to fill in, and `supersoundhandoff.md` is the
end-to-end runbook (vendor TAD → build instruments → hand-tune → compile → integrate).

## Next step

Open `supersoundhandoff.md` and follow the Quick-start checklist, starting with **03 Main
BGM 1**.
