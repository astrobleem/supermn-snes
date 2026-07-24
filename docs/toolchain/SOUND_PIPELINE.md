# VGM-to-TAD sound pipeline

The current direction is to use known-good YM2610 VGMs as the music performance and
patch oracle. Extracting a new FM register stream from live emulation is deferred.
This keeps the next work focused on audible SNES conversion rather than duplicating a
trace corpus that already exists.

## What VGM gives us

- ordered YM2610 register writes with sample-accurate waits;
- note, key-on, patch, volume, pan, and modulation evidence;
- embedded or referenced ADPCM sample-ROM blocks in many rips;
- a deterministic arcade-side render for A/B listening; and
- a reusable input to the existing profile and MML conversion tools.

VGM does not produce a finished SNES arrangement. TAD is sample-based, so FM/SSG
timbres must be rendered or redesigned as samples, pitches and loops must be authored,
and effects unsupported by the converter need explicit MML work.

## Private/source inputs

- legally obtained source VGMs or VGZ files;
- the user's authenticated game ROM set for any ROM-derived ADPCM data;
- the TAD compiler;
- an FM renderer such as the existing ymfm-based authoring path; and
- private working WAVs for rendered FM/SSG anchors.

Do not commit VGMs, arcade ROM blocks, derived copyrighted audio, or private WAVs.
Commit only original tooling, MML/metadata where legally appropriate, hashes, and
reproduction instructions.

For Superman, `tools/prepare_roms.py` deterministically rebuilds the 12 referenced
ADPCM-A drum WAVs. The current 45 `fm_p*.wav` authoring files are not derivable from
the ROM-only entry point; preserve them or rerun the documented VGM/ymfm authoring
process.

## Conversion flow

```sh
# Inspect timing, chips, and events.
python3 tools/sound/vgm_profile.py "/path/to/track.vgm"

# Convert the YM2610 stream to a first-pass TAD MML representation.
python3 tools/sound/vgm_ym2610.py "/path/to/track.vgm"

# Compile/check the consolidated project and pack the private audio blob.
tad-compiler check soundwork/tad/superman_all.terrificaudio
soundwork/tad/build_blob.sh
```

The exact authoring commands and tool outputs are described in
[tools/sound/README.md](../../tools/sound/README.md). The long-form extraction and
conversion reference is [SOUND_CONVERSION_REFERENCE.md](SOUND_CONVERSION_REFERENCE.md).

## Per-track acceptance

1. Confirm the VGM chip clock, duration, loop, and command stream.
2. Render an arcade reference from that exact VGM.
3. Transcribe timing, notes, rests, loops, dynamics, and channel allocation.
4. Choose or render source samples at practical root pitches. Add octave anchors only
   when an A/B test proves they improve the result.
5. Compile and confirm ARAM fit, song/sample IDs, and packed-ROM identity.
6. Capture SNES output and listen against the reference for melody, rhythm, octave,
   timbre, envelopes, percussion, looping, and dropouts.
7. Exercise the organic game command path so jingles/SFX do not replace music
   incorrectly.

Digital continuity is not musical fidelity. Superman's five-octave-anchor pass was
correctly generated and packed, yet the human verdict was no noticeable improvement.

## If live FM extraction becomes necessary

A self-captured source requires more than recording audio. Add retained MAME taps for
both YM2610 register ports and the time between writes; preserve chip clock, timer and
key state, banked ADPCM-A/B accesses, and sound-command context; serialize a
deterministic trace; then prove its rendered output matches MAME/VGM. Until a missing
or suspect VGM demands that work, the existing VGM corpus is the preferred oracle.
