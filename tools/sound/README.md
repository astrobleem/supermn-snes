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

## P3 real-sample pipeline (replaces the placeholder sine)

Sound-port P3 turned the drafts into real audio. Four new tools, run in this order:

| Script | What it does |
|---|---|
| `vgm_fm_patches.py` | Capture + dedupe every YM2610 FM patch at key-on across all VGMs (carrier-TL/volume normalized out) → `soundwork/samples/fm_patches.json` with per-(track,voice) usage + note histograms. |
| `patch_render.cpp` | Standalone ymfm-based renderer: one captured patch → held-note mono WAV at the chip's native rate. Build: `g++ -O2 -std=c++17 -I ymfm/src patch_render.cpp ymfm/src/ymfm_opn.cpp ymfm/src/ymfm_adpcm.cpp ymfm/src/ymfm_ssg.cpp -o patch_render` (clone https://github.com/aaronsgiles/ymfm). |
| `render_fm_patches.py` | For each *dominant* patch of some (track, FM-voice): render at the modal pitch, resample to 64 (or 32, for o7-reaching patches — the S-DSP 4× pitch ceiling) samples/period, keep a short attack + amplitude-flattened crossfaded 8-period loop, classify the FM envelope → TAD `gain`/`adsr`. Emits `instruments/fm_pNN.wav` + `fm_instruments.json`. |
| `prep_drums.py` | Trim/fade/downsample the 12 unique decoded ADPCM-A windows to an ARAM-fitting budget → `instruments/sm_drum_XXXXXX.wav` + `drums_report.json`. |
| `build_common_project.py` | Consolidate everything into ONE shared-pool project `superman_all.terrificaudio` (47 instruments, 21 songs, merged SFX file) and rewrite each MML's `@0-@3` bindings to its dominant-patch instruments. |

```bash
# full P3 regen (after unpacking VGMs to soundwork/source/vgm_unpacked)
python3 tools/sound/vgm_fm_patches.py soundwork/source/vgm_unpacked/*.vgm -o soundwork/samples/fm_patches.json
python3 tools/sound/render_fm_patches.py --renderer /path/to/patch_render
python3 tools/sound/prep_drums.py
python3 tools/sound/vgm2mml.py soundwork/source/vgm_unpacked/*.vgm -o soundwork/tad/mml_drafts \
    --fm-map soundwork/tad/mml_drafts/instruments/fm_instruments.json
python3 tools/sound/build_common_project.py
soundwork/tad/build_blob.sh          # check + ca65-export + generated glue symbols
```

### Polish stage (per-note timbre + dynamics)

The initial P3 pass bound each (track, FM-voice) to its *dominant* patch with a flat
`v10`. The polish stage restores per-note fidelity:

- `render_fm_patches.py --extra-budget N` renders the highest-impact **non-dominant**
  patches too (default ~4 KB of extra BRR) and **aliases** every remaining patch to its
  nearest rendered timbre (weighted register distance: algorithm ≫ MUL/TL ≫ envelope
  rates). `fm_instruments.json` gains `ident_to_inst` (every captured patch → an
  instrument that exists) + `inst_render_tl`.
- `vgm2mml.py --fm-map fm_instruments.json` re-walks each VGM with the patch capture
  (same 44100 Hz timeline; keyons matched by exact `(voice, onset_sample)`) and emits
  **per-note `@` instrument switches** and **`v1..16` velocities** from each keyon's
  carrier TL (`amp = 10^(-0.75·ΔTL/20)` vs the instrument's render TL; v14 = pack-wide
  loudest so the average note lands near the old flat v10). Instrument octave ranges
  tighten to only the notes each instrument actually plays.

ARAM budget (verified by `tad-compiler check`, which validates per-song fit): common data
(FM + drums + tables/SFX) + largest song + 4 KB echo + driver must stay ≤ 64 KB — after
the polish stage this is nearly full; `check` is the gate when tuning `--extra-budget` /
drum caps. Remaining by-ear items: echo/vibrato taste, FM pitch-bends (`MP`), long drum
tails capped (in-game hits retrigger gate-style, masking this).

## Concurrent live-gameplay validation (P3 close-out, 2026-07-10)

Everything above was first validated with the SA-1 idle. Validating with the game actually
RUNNING (Mesen cold boot — restored by the TESTFLAG relocation in interp.pasm) surfaced,
in order:

- **loop_hook failures ROOT-CAUSED and fixed** (flight-recorder + freeze-point + bisect,
  2026-07-10, no MAME lockstep needed — the interp's built-in PC ring at IRAM `$0400` and
  the `$0710` PC-freeze did it): (a) the boot RAM-test failure was an **`.org` overlap**
  — the lh flow chain grew past `$F601` and the later `.org $F602` gm_verify silently
  assembled over it (truncating lh_3fea's `sec/rts` and burying lh_adbe + gm_memclr;
  same overgrowth once buried the TESTFLAG). lh_3fea/lh_adbe/gm_verify now live in
  escbank5 behind stubs, gm_memclr in the vacated space, with build-time slack guards.
  (b) The generics also got correctness fixes: gm_verify now ACTUALLY verifies (a
  gameplay compare loop's early-mismatch exit matters — mismatch → interp runs the real
  loop), all collapses set exit CCR (dbra-fallthrough class) and guard `count==0`.
  (c) The `$080100` gameplay derail bisected to the **`$0818` idle-spin collapse alone**
  (forced-IRQ vs escape-inflated `$AC` pacing corrupts a coroutine entry — identical
  with a streak gate, so the arm is disabled with the repro documented in loop_hook).
  SHIP CONFIG: `snd_vframe` arms lh (minus `$0818`) + all escapes at ring-init; boots
  instantly and soaks 36000f clean.
- **The 5A22 sound layer now runs from the `$7F` WRAM mirror** (rc_copy window widened to
  `$1B00`, TAD internal `jsl`s forced `|$7F0000` via `regen.sh`), matching the pt.20/21
  "concurrent 5A22 code lives in WRAM" rule.
- **Instrumentation self-clobber lesson**: sound_tick's 16-bit W-debug store at `$7E:1F19`
  also wrote `$1F1A` — which was the call counter, so the counter read 0 forever and
  produced a long false "sound_tick never runs / stores vanish under concurrency"
  diagnosis (fixed: counter moved to `$1F1C`). Verify instrument addresses don't overlap
  16-bit stores before trusting them.
- **The transport is CLEAN under full concurrency**: a continuous 5A22 sampler of the
  `$41:0120` mailbox (250×/frame, game + escapes running) always read the true value —
  the P2-era "stale `$41` reads" do not reproduce on the live path. Attract music plays
  audibly while the game boots and runs (peak ~7.5k with SA-1 hot).
- **Attract Mode (track 01) is a 17 s one-shot** (the rip has no loop data) — recordings
  taken minutes into a run are silent because the song ENDED, not because audio broke.
  The arcade re-triggers `$05` each attract cycle (with a `$00` between), so in-game
  behavior is correct.

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
