# Superman Sound — Bootstrapping the Terrific Audio Driver (TAD)

> Audience: the agent/engineer who will add music + SFX to **SUPERMN-SNES**.
> Superman has **no audio implemented yet** (`audio/songs`, `audio/samples`, `src/sound`
> are empty). This doc is the runbook to go from the arcade VGM rips to SNES music.
>
> Two worked references exist and are worth studying:
> - **SNES-OUTRUN-SA1** (`E:\gh\snes-outrun-sa1`) — a sibling project that already ships a
>   TAD soundtrack converted from arcade **YM2151** VGMs. Its `outrunsound.md`, `tools/tad/`,
>   and `audio/*.terrificaudio` are the closest analog to what you're building.
> - **SNES Super Monkey Island** — the canonical full TAD integration (MIDI→MML→SPC),
>   referenced throughout OutRun's `outrunsound.md`.
>
> The hard part — **decoding the YM2610 VGMs into compilable MML** — is already done for you
> by the converter in `tools/sound/` (see §4). Read this top-to-bottom once, then use the
> **Quick-start checklist** at the end.

---

## 0. TL;DR

1. **Vendor TAD** from OutRun: copy `tools/tad/` (compiler + driver/loader binaries +
   `wav2brr.exe`) and the `tad_interface.65816` + `.h` engine glue.
2. **Convert the VGMs** with `tools/sound/convert_pack.py` (already written + verified):
   VGM → 8-voice MML draft + a compile-checkable `.terrificaudio` per track. All 21 tracks
   already compile and fit in audio-RAM.
3. **Build instruments**: the arcade is **FM + ADPCM-A samples**. Render the 4 FM patches to
   looped WAVs (or substitute), and extract/decode the ADPCM-A drums with
   `tools/sound/vgm_extract_adpcm.py`. Drop them into each `.terrificaudio`.
4. **Hand-tune** each MML against the reference VGM render (tempo, octaves, balance, echo).
5. **Compile** with `tad-compiler ca65-export`/`64tass-export` → one ROM blob + a
   `LoadAudioData` callback. **Integrate**: `Tad_Init` once at boot, `Tad_Process` once per
   frame, `Tad_LoadSong` to change tracks, `Tad_QueueSoundEffect` for SFX.
6. **Audition** standalone with `song2spc` before wiring in-game.

---

## 1. What the arcade actually is (and why it maps cleanly to SNES)

Superman (Taito X System, 1989) uses a **Yamaha YM2610 (OPNB)** — see `SOUNDHARDWARE.md`.
The VGM pack reports **YM2610B @ 8 MHz**. The chip has 4 FM + 3 SSG + 6 ADPCM-A + 1 ADPCM-B
sources, but **empirical profiling of all 21 rips** (`vgm_profile.py`) shows the music only
ever uses:

| Source | Used? | Maps to |
|---|---|---|
| **4 FM channels** (4-op) | **yes** — key-on selectors {1,2,5,6} | 4 TAD instrument voices |
| **ADPCM-A** (6 sample ch) | **yes** — percussion / drum kit | TAD sample instruments |
| SSG (3 square/noise) | **no** (zero writes in this pack) | — |
| ADPCM-B (DELTA-T) | **no** (init writes only, empty ROM block) | — |

So every track is **4 melodic FM voices + an ADPCM-A drum track** — a near 1:1 fit for the
SNES S-DSP's 8 voices. This is why the auto-converter can do so much: there is no SSG timbre
to approximate and no DELTA-T streaming to special-case.

> **Pitch math (for reference / debugging).** OPN F-number → Hz, verified against ymfm:
> `f = fnum * clock / (144 * 2^(21 - block))`, where `fnum = ((hi&7)<<8)|lo`, `block=(hi>>3)&7`.
> Decoded notes land on equal-tempered semitones to within a few cents across the whole pack,
> which validates the law. ADPCM-A key-on is register 0x00 on port 1: for each set channel
> bit, the channel keys **on when bit 7 is 0** (bit 7 = 1 is key-off/dump).

---

## 2. What TAD is (short version)

**Terrific Audio Driver** (undisbeliever, zlib) = an SPC700 sound driver + a host compiler.
- **SPC700 side**: precompiled `audio-driver.bin` (~3.25 KB) + `loader.bin` (116 B). Vendored
  binaries; you never edit them. They live in the SNES's 64 KB Audio-RAM (ARAM).
- **65816 side**: a small set of `Tad_*` routines (boot, per-frame process, load song, queue
  SFX). OutRun/SMI's `tad_interface.65816` is reusable WLA-DX.
- **Host compiler** (`tad-compiler.exe`): turns a JSON project + MML + samples into the
  binary blobs the driver consumes, and generates a `LoadAudioData` callback + song enums.

**ARAM model**: 64 KB total = loader + driver + echo buffer + **common audio data (all
instrument/SFX samples) + exactly one resident song**. Usable budget for samples + the
biggest song ≈ **~55 KB**. `tad-compiler check` is the authority on whether it fits — the
converter's output already passes for all 21 Superman tracks.

**8 voices**: MML channels **A–H** map to the 8 S-DSP voices.

---

## 3. The pipeline end to end

```
   *.vgz / *.vgm  (VGMRips Superman pack — YM2610 register logs)
        │   tools/sound/convert_pack.py   (or the individual tools in §4)
        ▼
   <track>.mml                 8-voice MML draft (4 FM + ADPCM-A drum voices, loop marker)
   <track>.notes.md            tempo/loop/instrument assumptions + what to fill in
   <track>.terrificaudio       compile-checkable project (placeholder samples)
   <track>.sfx_stub.txt        minimal SFX stub so the project compiles
        │
        │   build real instruments:
        │     - 4 FM voices  -> render YM2610 patch to looped WAV (or substitute)
        │     - drums        -> tools/sound/vgm_extract_adpcm.py -> decoded WAV -> BRR
        ▼
   edit <track>.terrificaudio (swap placeholder `source`/`freq` for real samples)
        │   tad-compiler check / song2spc  (audition)
        ▼
   tad-compiler ca65-export/64tass-export -> audio blob + LoadAudioData + song enums
        │   incbin + assemble (the Superman build)
        ▼
   superman.sfc  ── engine calls Tad_Init / Tad_Process / Tad_LoadSong / Tad_QueueSoundEffect
```

---

## 4. The converter (`tools/sound/`) — already built & verified

All scripts are plain Python 3 (stdlib only; on Windows run with `PYTHONUTF8=1`). They were
validated against the full 21-track pack: every track converts and **`tad-compiler check`
passes (21/21) and fits in ARAM.**

| Script | Purpose |
|---|---|
| `vgmlib.py` | VGM container/command parser (shared primitive). |
| `vgm_header_report.py` | Per-track version/clock/duration/loop/GD3 report. |
| `vgm_profile.py` | **Ground-truth profiler** — which FM/SSG/ADPCM channels each track uses. Run before trusting any assumption. |
| `vgm_ym2610.py` | YM2610 decoder: FM note events (pitch + timing) + ADPCM-A drum triggers + sample windows. Has a `_validate` mode that checks notes cluster on semitones. |
| `vgm2mml.py` | **The converter** — VGM → MML draft + notes.md + `.terrificaudio` stub. |
| `vgm_extract_adpcm.py` | Reconstruct the ADPCM-A sample ROM, cut each sample window, decode YM2610 ADPCM-A → 16-bit WAV. |
| `make_check_project.py` | Build a compile-checkable project binding all instruments to a placeholder (multi-song variant). |
| `convert_pack.py` | One command: unpack zip → header report → convert all → check → (opt) extract samples. |

### One-command run

```bash
python3 tools/sound/convert_pack.py --zip VGM_SOUND_SUPERMAN.zip --out soundwork \
    --tad ../snes-outrun-sa1/tools/tad/tad-compiler.exe --check --samples
```

Outputs land under `soundwork/` (gitignore it — it's regenerated; the rips are copyrighted).

### Per-track / iterative

```bash
# decode + sanity-check the chip usage of one track
python3 tools/sound/vgm_profile.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm"
python3 tools/sound/vgm_ym2610.py  "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm"

# convert one track (auto tempo) ; override tempo if the rhythm reads wrong
python3 tools/sound/vgm2mml.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm" \
    -o soundwork/tad/mml_drafts --bpm 125

# extract its drums
python3 tools/sound/vgm_extract_adpcm.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm" \
    -o soundwork/samples
```

### What the converter does and does NOT do

**Does** (accurately, mechanically): every FM note at correct pitch, note on/off timing,
tempo estimation + quantization to a musical grid, the loop point, ADPCM-A drum placement,
and a project that compiles. **Does not** (these are the human's job — they're musical, not
mechanical): FM timbre (you supply instruments), per-note volume/velocity (FM TL isn't
transcribed; voices emit a flat `v`), vibrato/LFO and pitch bends, and confirming the
auto-detected tempo. Each draft's `notes.md` lists exactly what to fill in.

> **Tempo caveat.** Tempo is auto-detected by snapping onsets to a grid; it can land on a
> half/double of the intended tempo (the converter folds it into TAD's 40–157 BPM range).
> If a draft's rhythm reads wrong, re-run with `--bpm N`. The arcade tracks land roughly
> 110–135 BPM (main themes) and higher for boss cues.

---

## 5. Building instruments

### 5a. FM voices (4 per song)

TAD is a sample engine; FM has no samples. Two routes (same as OutRun faced — see
`outrunsound.md` §4c):

- **Render the YM2610 FM patch** to a short sustained WAV with a marked loop point, add as a
  TAD `instrument`, set `freq` to the rendered note's true pitch, tighten `first_octave`/
  `last_octave` to the range the converter reports per voice. Most authentic.
- **Substitute** a generic sample (an FM-ish brass/bass/lead from any BRR pack, or OutRun's
  rendered YM2151 instruments as a starting point). Faster, less authentic; swap later.

A practical renderer: load the VGM in a YM2610-capable tool (MAME, or ymfm), solo one FM
channel, capture a held note, loop it. The OutRun project already ported **ymfm** for YM2151;
ymfm also implements **OPN/YM2610** (`ymfm_opn.*`) if you want to script the render.

### 5b. ADPCM-A drums

`vgm_extract_adpcm.py` reconstructs the sample ROM from the VGM's type-0x82 blocks, cuts each
distinct sample window (start/end from the chip's ADPCM-A registers), and decodes **Yamaha
ADPCM-A** (not generic IMA — see `CONVERTSOUND.md` trap #1) to 16-bit mono WAV at the native
~18.5 kHz. Then:

1. Trim to the actual hit; keep drums short (≤~250 ms — long tails blow the ARAM budget).
2. Don't normalize every sample independently (preserve the kit's relative balance).
3. Encode to BRR via TAD's `wav2brr` / GUI; bind to the `sm_drum_XXXXXX` names the MML uses.

The converter's `notes.md` table lists each drum's ROM window, byte size, hit count, and the
instrument name to bind.

### 5c. The `.terrificaudio` the converter emits

It already lists every instrument the MML references, with **placeholder** sources (a
synthesized sine) and **correct per-instrument octave ranges**. You only change `source` and
`freq` to your real samples — ranges and the song wiring are done. (Octave ranges are kept
minimal; remember a sample can pitch **down** many octaves but only ~2 **up**, so set each
instrument's `freq` near its top octave.)

---

## 6. Engine integration (the only code you write)

Identical in shape to OutRun's `outrunsound.md` §6 (vendor `tad_interface.65816`, call
`Tad_Init` once at boot with IRQ off, `Tad_Process` once per frame, implement the
`Tad_LoadAudioData` flat-table callback, `Tad_LoadSong`/`Tad_QueueSoundEffect`). Two
Superman-specific notes:

- **APU ports `$2140–$2143` are the main S-CPU's.** Keep `Tad_Process` and all TAD↔SPC
  comms on the **main CPU**. (Superman has a C-Chip emulation subsystem, not an SA-1, so the
  SA-1 caveat from OutRun doesn't apply — but the "APU is main-CPU only" rule still does.)
- **Pick a stable bank** reachable by `JSL` for the driver/loader `incbin` + `Tad_*`.

Song ids come from the generated enum include (`TAD_SONG_*`). Map them to game events
(attract, main BGM 1–3, boss cues, round clear, continue, game over, ending) — the natural
event list is in `SOUNDHARDWARE.md` §8.

---

## 7. Suggested conversion order

Per `CONVERTSOUND.md` §14 (prove the pipeline on one long BGM + a couple of short cues first):

1. **03 Main BGM 1** — main identity (and includes Williams material; see rights note).
2. **08 Main BGM 3** — long loop, second stage identity.
3. Short cues: **02 Coin**, **07 Round Clear**, **12 Continue**, **21 Game Over**.
4. Boss BGMs (reuse the instrument set).
5. Round 5-x cues, then **01 Attract**, **20 Name Entry**, **19 Ending**.

---

## 8. Rights note

Tracks **3, 8, 19** contain John Williams' *Superman* film theme (per the pack notes and
`CONVERTSOUND.md` §17). Decoded samples and transcribed arrangements may be protected. Fine
for private technical conversion; get a rights review before any public release.

---

## 9. Quick-start checklist

1. [ ] Copy `tools/tad/` + `tad_interface.65816`/`.h` from OutRun (`E:\gh\snes-outrun-sa1`).
2. [ ] `python3 tools/sound/convert_pack.py --zip VGM_SOUND_SUPERMAN.zip --out soundwork --tad <tad-compiler> --check` → confirm 21/21 pass.
3. [ ] Pick the audio bank; `incbin` driver + loader; get the build assembling with placeholder audio.
4. [ ] `Tad_Init` at boot (IRQ off) + `Tad_Process` in NMI → verify it boots, no hang.
5. [ ] Take **03 Main BGM 1**: extract drums (`vgm_extract_adpcm.py`), build/borrow 4 FM instruments, swap them into `03_main_bgm_1.terrificaudio`.
6. [ ] `tad-compiler song2spc` it → listen. Hand-tune tempo/octaves/balance vs the reference VGM render. Iterate.
7. [ ] `ca65-export`/`64tass-export` → blob + asm + inc; wire the makefile; implement `Tad_LoadAudioData`.
8. [ ] Load it in-game (`Tad_LoadSong`). Then add the rest of the tracks + SFX.
9. [ ] Keep `tad-compiler check` green; stay on one sample pool (don't reach for groups unless it fails).

---

*The converter is in `tools/sound/` with a README. The worked TAD integration is in
`E:\gh\snes-outrun-sa1` (`outrunsound.md`). The VGM/ADPCM format details are in
`CONVERTSOUND.md`; the arcade hardware in `SOUNDHARDWARE.md`.*
