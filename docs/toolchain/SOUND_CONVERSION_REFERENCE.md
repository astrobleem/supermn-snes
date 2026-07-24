# Superman arcade VGM conversion reference

This is the long-form source/extraction reference. Use the concise
[current sound pipeline](SOUND_PIPELINE.md) for the chosen VGM-first workflow and
acceptance gates.

## Purpose

This document advises how to use the VGMRips *Superman* pack as source material for:

1. direct MML-first transcription for Terrific Audio Driver;
2. optional rough MIDI extraction as a piano-roll/transcription aid;
3. YM2610 ADPCM sample extraction;
4. preparing curated audio assets for an SNES SPC700 / Terrific Audio Driver workflow.

The target reader is an audio worker who needs to start converting the arcade soundtrack into editable musical data and usable sample assets. This is not a final SPC700 driver design. Treat it as source-conversion guidance.

Source pack:

```text
https://vgmrips.net/packs/pack/superman-taito-x-system
```

---

## 1. Important starting truth

A `.vgm` / `.vgz` file is not a MIDI file.

It is a timed log of sound-chip activity: register writes, waits, embedded sample-ROM blocks, loop metadata, and optional GD3 text tags. For this pack, the relevant chip family is Yamaha YM2610 / YM2610B. That means the music is made from some mixture of:

- FM synthesis channels;
- SSG square/noise channels;
- ADPCM-A fixed-rate sample channels;
- ADPCM-B / DELTA-T variable-rate sample channel.

Therefore:

- Use MIDI conversion only as a **transcription scaffold**.
- Use the original VGM playback as the **audible truth**.
- Use YM2610 register traces and data blocks as the **sample-boundary truth**.
- Do not expect any automatic converter to produce finished SNES-ready music.

The correct mental model is:

```text
VGZ/VGM rip
  -> reference playback WAVs
  -> VGM register/event traces
  -> direct MML drafts for TAD
  -> YM2610 sample-ROM extraction
  -> ADPCM decode to WAV
  -> curate / loop / rate-decision / BRR encode
  -> Terrific Audio Driver project assets

Optional side path:
  -> raw MIDI skeletons
  -> DAW piano-roll cleanup
  -> use cleaned MIDI only as transcription evidence for the MML
```

MIDI is not the goal. MML is the goal. MIDI is useful only when it helps the worker see notes and rhythm faster.

---

## 2. Pack facts to preserve

VGMRips identifies the pack as:

| Field | Value |
|---|---|
| Game | Superman |
| System | Taito X System |
| Sound chip on pack page | YM2610B |
| Developer / publisher | Taito |
| Release date listed by VGMRips | 1989-02 |
| Pack version | 1.00 |
| Pack date | 2013-01-29 |
| Listed composer credits | John Williams, Kazuyuki Ohnui, Masahiko Takaki, Shizuo Aizawa, Takami Asano |
| Listed total | 10:58 + 7:55 loop material |

Track list from the pack page:

| # | Track | Listed duration |
|---:|---|---:|
| 01 | Attract Mode | 0:17 |
| 02 | Coin | 0:05 |
| 03 | Main BGM 1 | 1:40 + 1:31 |
| 04 | Boss BGM 1 | 0:21 + 0:19 |
| 05 | Main BGM 2 | 0:33 + 0:13 |
| 06 | Boss BGM 2 | 0:24 + 0:23 |
| 07 | Round Clear | 0:08 |
| 08 | Main BGM 3 | 1:32 + 1:31 |
| 09 | Boss BGM 3 | 0:39 + 0:38 |
| 10 | Boss BGM 4 | 0:21 + 0:20 |
| 11 | Boss BGM 5 | 0:41 + 0:40 |
| 12 | Continue | 0:14 |
| 13 | Round 5-1 | 0:25 + 0:24 |
| 14 | Round 5-2 | 0:23 + 0:23 |
| 15 | Round 5-3 | 0:20 + 0:19 |
| 16 | Round 5-4 | 0:23 + 0:22 |
| 17 | Boss BGM 6 | 0:22 + 0:22 |
| 18 | Boss BGM 7 | 0:41 + 0:20 |
| 19 | Ending | 1:16 |
| 20 | Name Entry | 0:17 + 0:16 |
| 21 | Game Over | 0:08 |

The `+` notation means the rip has distinct non-loop and loop timing information. Preserve that information when creating looped SNES music.

### YM2610 vs YM2610B note

The earlier [sound-hardware survey](../history/forensics/SOUND_HARDWARE_SURVEY.md)
focuses on the arcade hardware and treats the chip as YM2610 OPNB. The VGMRips pack
page says YM2610B. For conversion work, check the VGM header in every file:

- VGM header offset `0x4C` stores the YM2610/YM2610B clock.
- Bit 31 set means YM2610B in the VGM spec.
- Mask bit 31 off to get the numeric clock.

For practical SNES conversion, the variant matters mainly if the rip uses FM channels only present on YM2610B. Do not assume; inspect the writes.

---

## 3. Recommended project directory

Use a predictable directory tree so the conversion is reproducible.

```text
soundwork/
  source/
    vgmrips_zip/
    vgz_original/
    vgm_unpacked/
  reference_wav/
    mix/
    optional_stems/
  midi/
    raw_vgm2mid/
    cleaned/
  traces/
    headers/
    vgm2txt/
    ym2610_registers/
    sample_events/
  sample_roms/
    adpcma_rom_bins/
    adpcmb_rom_bins/
  samples/
    adpcm_raw_windows/
    decoded_wav_raw/
    edited_wav/
    brr/
  tad/
    project_notes/
    instruments/
    mml_drafts/
  logs/
```

Always keep the original VGZ files unchanged. Every generated file should be rebuildable from those originals.

---

## 4. Tools worth having

### Minimum tool set

| Purpose | Tool / approach |
|---|---|
| Unpack VGZ | `gzip`, `7-Zip`, Python `gzip` module |
| Inspect VGM header/data | small Python scripts, `vgm2txt`, `vgm_sro` |
| Convert VGM to rough MIDI | Optional: VGMRips `VGM2MID` |
| Render reference audio | VGMPlay, VGM-compatible player with WAV export, MAME recording, or equivalent trusted emulator path |
| Decode YM2610 ADPCM | YM2610 ADPCM decoder tool, `superctr/adpcm`, custom decoder, or other verified YM2610 A/B decoder |
| Edit MIDI/audio | REAPER, Furnace, OpenMPT, Audacity, SoX, ffmpeg, or preferred DAW/editor |
| SNES sample prep | Terrific Audio Driver GUI / sample editor, `wav2brr` path used by TAD, BRR sample tools |

### VGMRips tools

`VGM2MID` is the obvious first pass because it exists specifically to convert VGM logs to MIDI sequence files. Use the full package plus the latest exe-only update from the VGMRips wiki page. It is old software; running it through Windows or Wine may be easier than trying to rebuild it.

`vgm_sro` is useful even if you do not use its optimized output. It scans sample-ROM usage and prints ROM regions before stripping unused data. Use it as a sanity check for whether the VGM contains YM2610 sample-ROM blocks and how much of them are actually used.

---

## 5. Step 1 — unpack VGZ to VGM

`.vgz` is normally gzip-compressed `.vgm`. Decompress every track before parsing.

Example shell flow:

```sh
mkdir -p source/vgm_unpacked

for f in source/vgz_original/*.vgz; do
  base="$(basename "$f" .vgz)"
  gzip -cd "$f" > "source/vgm_unpacked/${base}.vgm"
done
```

If `gzip` refuses the file, check whether the extension is misleading. The VGM spec expects players to handle both compressed and uncompressed files, but conversion scripts should be explicit.

---

## 6. Step 2 — inspect every VGM header

Before converting anything, produce a header report per track.

Minimum fields to record:

| Field | Why it matters |
|---|---|
| VGM version | Affects header interpretation and supported commands. |
| YM2610/YM2610B clock | Affects pitch/rate calculations. |
| YM2610B flag | Confirms whether the rip claims YM2610B. |
| Total sample count | Exact track duration at 44.1 kHz VGM timing. |
| Loop offset | Determines where loop data begins. |
| Loop sample count | Determines loop duration. |
| GD3 tags | Track name, game, system, author metadata. |
| VGM data offset | Parser start point. |

Use this Python snippet as a starting point:

```python
#!/usr/bin/env python3
import gzip
import struct
import sys
from pathlib import Path


def read_file(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def u32le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, offset)[0]


def main() -> None:
    for arg in sys.argv[1:]:
        path = Path(arg)
        data = read_file(path)
        if data[:4] != b"Vgm ":
            print(f"{path}: not a VGM file")
            continue

        version = u32le(data, 0x08)
        total_samples = u32le(data, 0x18)
        loop_offset = u32le(data, 0x1C)
        loop_samples = u32le(data, 0x20)
        data_offset_raw = u32le(data, 0x34)
        data_start = 0x40 if data_offset_raw == 0 else 0x34 + data_offset_raw

        ym2610_raw = u32le(data, 0x4C)
        ym2610b = bool(ym2610_raw & 0x80000000)
        ym2610_clock = ym2610_raw & 0x7FFFFFFF

        print(f"{path.name}")
        print(f"  version:        0x{version:08X}")
        print(f"  data_start:     0x{data_start:X}")
        print(f"  ym2610_clock:   {ym2610_clock}")
        print(f"  ym2610_variant: {'YM2610B' if ym2610b else 'YM2610'}")
        print(f"  total_samples:  {total_samples} ({total_samples / 44100:.3f}s)")
        print(f"  loop_offset:    0x{loop_offset:X}")
        print(f"  loop_samples:   {loop_samples} ({loop_samples / 44100:.3f}s)")
        print()


if __name__ == "__main__":
    main()
```

Expected command:

```sh
python3 tools/vgm_header_report.py source/vgm_unpacked/*.vgm > traces/headers/header_report.txt
```

---

## 7. Step 3 — render reference WAVs

Create a reference WAV for every VGM before touching MIDI.

The reference WAV is the conversion judge. Every cleaned MIDI, MML draft, BRR sample, and final SNES playback should be compared against it.

Recommended naming:

```text
reference_wav/mix/03_Main_BGM_1__vgm_reference.wav
reference_wav/mix/04_Boss_BGM_1__vgm_reference.wav
...
```

For looped songs, render at least:

- the non-loop intro;
- one full loop;
- a few seconds after the loop restarts, if the player can render that.

Make a short text file per track:

```text
track: 03 Main BGM 1
audio reference: reference_wav/mix/03_Main_BGM_1__vgm_reference.wav
vgm total: 1:40 + 1:31 per VGMRips
observed loop: [fill in exact sample/time]
notes: [tempo feel, key, instrumentation, sample hits]
```

---

## 8. Step 4 — optional rough MIDI conversion

Use `VGM2MID` as a first-pass extractor only when it saves time. Do not make MIDI a mandatory intermediate format.

For this project, the preferred target is **TAD MML**, not General MIDI. Terrific Audio Driver songs are written in MML, and TAD can also express exact sample-rate playback with commands such as `PR32000`, `PR16000`, `P$1000`, and `s[number]`. A VGM-to-MIDI tool can help find notes, but it cannot preserve the arcade chip's complete register intent.

Expected workflow:

1. Convert `.vgz` to `.vgm` first.
2. Run VGM2MID on the `.vgm` file.
3. Import the generated MIDI into a DAW.
4. Align it with the reference WAV.
5. Treat the MIDI as note/timing evidence, not a finished arrangement.

Example command names will vary by environment, but the flow is:

```text
VGM2MID.exe "source/vgm_unpacked/03 Main BGM 1.vgm"
```

Put raw output here:

```text
midi/raw_vgm2mid/03_Main_BGM_1.raw.mid
```

### Expected problems in the raw MIDI

Do not be surprised by any of these:

| Problem | Reason | Fix |
|---|---|---|
| Wrong instruments | VGM knows chip registers, not General MIDI patches. | Manually assign temporary instruments. Later replace with TAD sample instruments. |
| Percussion mapped as pitched notes | ADPCM triggers are not GM drum events. | Create a custom drum/sample map. |
| Missing vibrato / LFO feel | YM2610 LFO and FM modulation do not map cleanly to MIDI. | Add pitch bend, vibrato, tremolo, or MML effects by ear. |
| Bad note lengths | Chip key-on/off and envelope release do not equal MIDI note durations. | Edit note-off timing against reference WAV. |
| Channels merged | Older converters may emit format 0 MIDI or awkward channel grouping. | Convert to MIDI format 1 if needed; split by channel. |
| Tempo not useful | VGM timing is sample waits at 44.1 kHz, not bars/beats. | Derive musical tempo manually by aligning to reference WAV. |
| FM patches absent | MIDI cannot represent YM2610 4-op patches directly. | Rebuild as SNES samples/instruments. |

### Raw MIDI cleanup rules

For each track:

1. Import the raw MIDI and reference WAV into the same DAW project.
2. Find the musical downbeat and set a temporary tempo grid.
3. Do **light quantization only**. If it starts sounding unlike the VGM, revert.
4. Separate lanes by original source type when possible:
   - FM melodic / harmonic parts;
   - SSG parts;
   - ADPCM percussion / hits;
   - ADPCM-B long or special samples.
5. Mark loop start and loop end using VGM loop metadata and the VGMRips duration notation.
6. Export a cleaned MIDI with simple, obvious track names.

Cleaned MIDI naming:

```text
midi/cleaned/03_Main_BGM_1.cleaned.mid
midi/cleaned/03_Main_BGM_1.loop_notes.md
```

The `.loop_notes.md` file should contain:

```text
track: 03 Main BGM 1
intro length: [bars / samples / time]
loop length: [bars / samples / time]
loop start marker: [bar:beat or sample]
loop end marker: [bar:beat or sample]
known issues: [anything not matching the VGM]
```

## 8A. Preferred path — VGM trace directly to TAD MML

It absolutely makes sense to skip MIDI for many tracks. Use direct MML when the raw MIDI output is messy, when the cue is short, or when the track relies heavily on chip-specific behavior that MIDI will flatten.

Recommended direct path:

```text
VGM waits + register writes
  -> per-channel event trace
  -> human-readable note/sample event table
  -> TAD MML draft
  -> compare TAD preview/SPC render against reference WAV
```

The event trace should preserve both **exact VGM time** and **musical time**. VGM timing is expressed as waits against a 44.1 kHz sample timeline. MML wants musical lengths or tick lengths. Keep both because exact time is useful for validation, while musical time is useful for maintainable MML.

Minimum event-trace fields:

```text
track,event_time_samples,event_time_seconds,source_block,source_channel,
register_context,note_name_or_hz,tad_channel,tad_instrument_or_sample,
velocity_or_level,gate_or_duration,loop_role,notes
```

Suggested source-to-TAD mapping:

| Arcade source | Direct MML interpretation | Notes |
|---|---|---|
| YM2610 FM melodic channel | TAD instrument plus normal notes or `PF<freq>`/`P<pitch>` where needed | Best when the worker creates looped BRR instruments from rendered FM notes. |
| YM2610 SSG square channel | Small looped BRR square/noise-like instrument, or TAD noise command where appropriate | Preserve pitch and rhythmic role; exact chip timbre can be approximated. |
| ADPCM-A drum/hit | TAD sample with a single sample-rate entry, played with `s0` | Usually better as a TAD **sample**, not pitched instrument. |
| ADPCM-B long/special sample | TAD sample with computed rate entries | If too large, remake or abbreviate for SNES. |
| One-off jingle or UI cue | Hand-authored MML directly from trace/reference | MIDI is usually unnecessary. |

When writing MML, prefer readable note lengths once the tempo/grid is known. Use exact tick lengths only when the source timing is awkward or when a cue is too short to justify grid cleanup.

Example MML-first workflow for one track:

1. Render the VGM to reference WAV.
2. Dump a register/event trace.
3. Mark loop start/end from VGM metadata.
4. Identify each active YM2610 source: FM, SSG, ADPCM-A, ADPCM-B.
5. Build or choose TAD instruments/samples.
6. Hand-enter the track in MML, channel by channel.
7. Preview/export from TAD and compare against the reference WAV.
8. Only open MIDI if a visual piano roll would speed up correction.

MIDI remains useful as a temporary view, but the worker should not spend time polishing a MIDI file that will be thrown away. The deliverable that matters is the `.mml` plus its sample/instrument manifest.

---

## 9. Step 5 — extract YM2610 sample ROM blocks from VGM

Best source for sampled material is the YM2610 data itself, not a rendered mix WAV.

The VGM data stream can include data blocks. Relevant block types:

| VGM data block type | Meaning |
|---:|---|
| `0x82` | YM2610 ADPCM ROM data, usually ADPCM-A material |
| `0x83` | YM2610 DELTA-T ROM data, ADPCM-B material |

A ROM data block payload starts with:

```text
uint32_le rom_size
uint32_le start_address
byte[]    data_at_start_address
```

So the extractor must allocate a ROM region of `rom_size`, then copy each data block into it at `start_address`.

### ROM dump script

Use this as a first extractor. It dumps reconstructed YM2610 sample-ROM regions from one or more VGM files.

```python
#!/usr/bin/env python3
import gzip
import struct
import sys
from pathlib import Path
from collections import defaultdict


def read_vgm(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != b"Vgm ":
        raise ValueError(f"not a VGM: {path}")
    return data


def u32le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, offset)[0]


def data_start(data: bytes) -> int:
    raw = u32le(data, 0x34)
    return 0x40 if raw == 0 else 0x34 + raw


def command_size(cmd: int, data: bytes, pos: int) -> int:
    # pos is after the command byte.
    if cmd in (0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
               0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
               0xA0, 0xB0, 0xB1, 0xB3, 0xB4, 0xB5, 0xB6,
               0xB7, 0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD,
               0xBE, 0xBF):
        return 2
    if cmd == 0x50:
        return 1
    if cmd == 0x61:
        return 2
    if cmd in (0x62, 0x63):
        return 0
    if 0x70 <= cmd <= 0x7F:
        return 0
    if cmd == 0x67:
        # handled outside
        return -1
    if cmd == 0x68:
        # PCM RAM write command: 0x66 cc oo oo oo ss ss ss dd...
        # Not expected for YM2610 ROM blocks. Skip conservatively if encountered.
        if pos + 10 > len(data):
            return len(data) - pos
        size = u32le(data, pos + 6)
        return 10 + size
    if 0x90 <= cmd <= 0x95:
        return {0x90: 4, 0x91: 4, 0x92: 5, 0x93: 10, 0x94: 1, 0x95: 4}[cmd]
    if cmd == 0x66:
        return 0
    raise ValueError(f"unhandled VGM command 0x{cmd:02X} at 0x{pos-1:X}")


def extract_blocks(path: Path):
    data = read_vgm(path)
    pos = data_start(data)
    blocks = []

    while pos < len(data):
        cmd_pos = pos
        cmd = data[pos]
        pos += 1

        if cmd == 0x66:
            break

        if cmd == 0x67:
            if pos + 6 > len(data) or data[pos] != 0x66:
                raise ValueError(f"bad data block at 0x{cmd_pos:X} in {path}")
            pos += 1
            block_type = data[pos]
            pos += 1
            size = u32le(data, pos)
            pos += 4
            payload = data[pos:pos + size]
            pos += size

            if block_type in (0x82, 0x83):
                if len(payload) < 8:
                    continue
                rom_size, start = struct.unpack_from("<II", payload, 0)
                block_data = payload[8:]
                blocks.append((block_type, rom_size, start, block_data))
            continue

        skip = command_size(cmd, data, pos)
        if skip < 0:
            raise ValueError(f"unexpected negative skip at 0x{cmd_pos:X}")
        pos += skip

    return blocks


def main() -> None:
    outdir = Path("sample_roms")
    outdir.mkdir(exist_ok=True)

    for arg in sys.argv[1:]:
        path = Path(arg)
        by_type = defaultdict(list)
        for block in extract_blocks(path):
            by_type[block[0]].append(block)

        for block_type, blocks in sorted(by_type.items()):
            rom_size = max(b[1] for b in blocks)
            rom = bytearray(rom_size)
            for _, _, start, block_data in blocks:
                rom[start:start + len(block_data)] = block_data

            label = "adpcma" if block_type == 0x82 else "adpcmb_deltat"
            outpath = outdir / f"{path.stem}.{label}.rom.bin"
            outpath.write_bytes(rom)
            print(f"{path.name}: wrote {outpath} ({len(rom)} bytes, {len(blocks)} blocks)")


if __name__ == "__main__":
    main()
```

Run:

```sh
python3 tools/dump_vgm_ym2610_roms.py source/vgm_unpacked/*.vgm > logs/dump_vgm_ym2610_roms.log
```

Then deduplicate identical ROM dumps:

```sh
sha1sum sample_roms/*.rom.bin | sort > logs/sample_rom_sha1.txt
```

If no YM2610 data blocks are found, use the arcade ROM sample file identified in the
[sound-hardware survey](../history/forensics/SOUND_HARDWARE_SURVEY.md) as the likely
sample ROM source and trace playback from MAME instead.

---

## 10. Step 6 — build a sample event catalog

Extracting the ROM is not enough. The ROM is a bank of ADPCM bytes. You need start/end addresses from YM2610 register writes to identify actual samples.

### Relevant VGM commands

| VGM command | Meaning |
|---:|---|
| `0x58 aa dd` | YM2610 port 0 register write: register `aa`, data `dd` |
| `0x59 aa dd` | YM2610 port 1 register write: register `aa`, data `dd` |
| `0x61 nn nn` | wait `n` samples |
| `0x62` | wait 735 samples, 1/60 sec |
| `0x63` | wait 882 samples, 1/50 sec |
| `0x7n` | wait `n + 1` samples |
| `0x67` | data block |
| `0x66` | end of sound data |

VGM wait values are at 44,100 samples per second for timing purposes.

### ADPCM-A register model

ADPCM-A has six fixed-rate sample channels. On YM2610, ADPCM-A address/data writes are on the second register port in the common Neo-Geo-style map; in VGM terms these usually appear as `0x59` writes.

Important ADPCM-A registers:

| Register | Meaning |
|---:|---|
| `0x00` | Dump / ADPCM-A channel on bits |
| `0x01` | ADPCM-A total level |
| `0x08`-`0x0D` | Output select / channel level for channels 0-5 |
| `0x10`-`0x15` | Start address LSB for channels 0-5 |
| `0x18`-`0x1D` | Start address MSB for channels 0-5 |
| `0x20`-`0x25` | End address LSB for channels 0-5 |
| `0x28`-`0x2D` | End address MSB for channels 0-5 |

Address calculation:

```text
start = ((start_msb << 8) | start_lsb) << 8
end   = (((end_msb << 8) | end_lsb) << 8) | 0xFF
```

Each ADPCM-A sample window is 256-byte aligned. The end address is inclusive at the hardware level.

For each ADPCM-A channel, track the last written start/end/level values. When register `0x00` starts a channel, record a sample event:

```text
time_samples, track, block=ADPCM-A, channel, start, end, bytes, level, trigger_value
```

The exact interpretation of the dump/start bit should be verified by listening and comparing with the reference WAV. Practical method: log every write to `0x00`, then correlate changes with audible ADPCM events.

### ADPCM-B / DELTA-T register model

ADPCM-B is one variable-rate sample channel. In VGM terms these usually appear as `0x58` writes.

Important ADPCM-B registers:

| Register | Meaning |
|---:|---|
| `0x10` | Start / repeat / reset control |
| `0x11` | Left/right control |
| `0x12` | Start address LSB |
| `0x13` | Start address MSB |
| `0x14` | End address LSB |
| `0x15` | End address MSB |
| `0x19` | Delta-N LSB |
| `0x1A` | Delta-N MSB |
| `0x1B` | Output level / EG control |
| `0x1C` | ADPCM flag control |

Address calculation:

```text
start = ((start_msb << 8) | start_lsb) << 8
end   = (((end_msb << 8) | end_lsb) << 8) | 0xFF
```

Approximate ADPCM-B sample rate from Delta-N:

```text
delta_n = (delta_msb << 8) | delta_lsb
rate_hz = ym2610_clock_hz * delta_n / (144 * 65536)
```

At an 8 MHz chip clock, maximum rate is about 55.5 kHz. Record the computed rate for every ADPCM-B trigger; the same byte range may be played at different rates.

### Sample catalog output

Create a single CSV for all extracted sample events:

```text
sample_event_id,track,time_samples,time_seconds,ym_block,channel,start_hex,end_hex,byte_count,rate_hz,level,trigger_reg,trigger_data,sha1,description,notes
```

Then create a deduplicated sample table:

```text
sample_id,ym_block,start_hex,end_hex,byte_count,default_rate_hz,used_by_tracks,used_as,keep_for_snes,notes
```

This table is more important than the raw dump. It tells the SNES audio worker what sounds actually matter.

---

## 11. Step 7 — decode ADPCM windows to WAV

After you identify a sample window, cut the raw ADPCM bytes and decode them.

Example cut operation in Python:

```python
from pathlib import Path

rom = Path("sample_roms/03_Main_BGM_1.adpcma.rom.bin").read_bytes()
start = 0x012300
end = 0x0127FF
Path("samples/adpcm_raw_windows/sample_001.adpcma.bin").write_bytes(rom[start:end + 1])
```

### Decoder choices

Use a decoder that specifically understands Yamaha YM2610 ADPCM-A and ADPCM-B. Do not treat these as generic IMA ADPCM.

Known useful options:

| Tool | Notes |
|---|---|
| YM2610 ADPCM decoder tool from NeoGeo dev resources | Decodes A and B type samples to WAV. Good if Windows tooling is acceptable. |
| `superctr/adpcm` | Command-line ADPCM encoder/decoder library; supports Yamaha ADPCM-A decode/encode and Yamaha ADPCM-B decode/encode. |
| Custom decoder | Acceptable if validated against known YM2610 output. |

Example intent using `superctr/adpcm` style command names:

```sh
# Yamaha ADPCM-A decode
adpcm ad samples/adpcm_raw_windows/sample_001.adpcma.bin samples/decoded_wav_raw/sample_001.raw.pcm

# Yamaha ADPCM-B decode
adpcm bd samples/adpcm_raw_windows/sample_020.adpcmb.bin samples/decoded_wav_raw/sample_020.raw.pcm
```

Check the exact output format of the decoder you use. If it outputs raw signed PCM instead of WAV, wrap it as mono WAV with the correct sample rate.

ADPCM-A typical rate at 8 MHz:

```text
~18518 Hz, mono
```

Example raw PCM to WAV with SoX:

```sh
sox -r 18518 -e signed-integer -b 16 -c 1 sample_001.raw.pcm sample_001.wav
```

For ADPCM-B, use the rate computed from Delta-N:

```sh
sox -r 24000 -e signed-integer -b 16 -c 1 sample_020.raw.pcm sample_020.wav
```

Use the actual computed rate instead of `24000`.

---

## 12. Step 8 — prepare samples for SNES / TAD

The SNES cannot use YM2610 ADPCM directly. The practical conversion path is:

```text
YM2610 ADPCM window
  -> decoded mono WAV
  -> edited mono WAV
  -> BRR sample
  -> TAD sample/instrument entry
```

### Editing rules before BRR conversion

For each decoded sample:

1. Trim only obvious leading/trailing junk or silence.
2. Do not normalize everything to 0 dB. Preserve relative loudness where possible.
3. Record original YM2610 level values in the sample catalog.
4. Remove DC offset only if visible/audible.
5. Fade tiny clicks only if they are decode/window artifacts, not intentional arcade transients.
6. Convert to mono.
7. Downsample only after listening. Short hits often survive lower rates; cymbal/noise/voice-like samples may not.
8. For looped instruments, find a stable loop before BRR encoding.
9. Keep both the raw decoded WAV and edited WAV.

Recommended filenames:

```text
samples/decoded_wav_raw/a_001_012300_0127ff_hit_raw.wav
samples/edited_wav/a_001_012300_0127ff_hit_edited.wav
samples/brr/a_001_012300_0127ff_hit.brr
```

### BRR rate and the 32 kHz rule

Do **not** blindly resample every source to 32 kHz. The SNES/TAD world uses 32 kHz as the native playback reference, but a BRR file itself does not carry a meaningful embedded sample rate. The playback pitch/rate is determined by the S-DSP pitch value that TAD generates.

Terrific Audio Driver's documentation uses 32,000 Hz as the native reference: `PR32000` plays the current BRR sample at native 32 kHz (`P$1000`), while `PR16000` plays it at 16 kHz (`P$0800`). TAD instruments also ask for the sample's source frequency **when played at 32,000 Hz**, and TAD samples ask for a list of sample rates the sample can be played at.

Practical rule:

| Asset type | Best TAD type | Rate decision |
|---|---|---|
| ADPCM-A drums / one-shots | TAD **sample** | Keep decoded PCM at the original YM2610 ADPCM-A rate when it sounds correct; set the TAD sample-rate entry to that rate. Do not inflate to 32 kHz unless quality demands it. |
| ADPCM-B / DELTA-T one-shots | TAD **sample** | Use the rate computed from Delta-N. If the same byte range is played at multiple Delta-N values, add multiple sample-rate entries. |
| Rendered FM/SSG pitched instrument | TAD **instrument** | Usually resample/prepare the source so the captured note sounds at its intended pitch when played at 32 kHz, then enter that note's frequency as the instrument source frequency. |
| Rendered FM/SSG phrase | TAD sample or avoided | Use sparingly. If kept, set the sample-rate entry to the intended playback rate. |

Why avoiding blanket 32 kHz conversion matters:

- ADPCM-A material from YM2610 is commonly around 18.5 kHz on an 8 MHz chip. Resampling that to 32 kHz increases sample length and BRR memory cost by roughly 73% before compression behavior is considered.
- One-shot drums do not need to be pitched across octaves. TAD's **sample** type is a better fit because it stores only the rates actually used.
- Pitched instruments are different. For a bass/lead/brass instrument, a 32 kHz prepared root sample is easier to reason about because TAD's instrument frequency is defined at 32 kHz playback.

Useful formulas:

```text
S-DSP pitch value = round(playback_rate_hz * 4096 / 32000)

If an unchanged sample originally sounds at F_orig when played at R_orig:
source_frequency_for_TAD_instrument = F_orig * 32000 / R_orig

If the sample is resampled to 32000 while preserving pitch:
source_frequency_for_TAD_instrument = F_orig
```

Examples:

```text
ADPCM-A one-shot decoded at 18518 Hz:
  Keep as mono 16-bit WAV at 18518 Hz.
  Import/encode to BRR.
  Define as a TAD sample with sample_rates = [18518].
  In MML, play it with s0 through that sample definition.

Same one-shot resampled to 32000 Hz:
  Costs more memory.
  Define sample_rates = [32000].
  In MML, PR32000 or s0 gives native playback.

FM bass note sampled as C2 at 65.406 Hz and prepared at 32000 Hz:
  Define it as a TAD instrument.
  Set source frequency to 65.406 Hz, or the nearest value supported by the tool.
  Limit its note range to the octaves actually used in the song.
```

### Turning an arcade instrument/sample into BRR

Use this decision tree:

1. Identify the source type.
   - ADPCM-A or ADPCM-B means the source is already a sample window in the YM2610 ROM data.
   - FM or SSG means you must render or recreate the instrument yourself.
2. Decode or render to mono WAV.
3. Decide whether this asset is a TAD **sample** or **instrument**.
4. Decide playback rate before encoding.
5. Make the WAV TAD-safe: mono, 16-bit PCM, length multiple of 16 samples, loop point multiple of 16 if looping, clean zero-crossing/start behavior.
6. Encode/import through TAD's BRR path or GUI.
7. Record the chosen rate/frequency in the manifest.

Example SoX prep commands:

```sh
# Preserve a decoded ADPCM-A one-shot at its natural rate.
sox raw_decoded_adpcma.wav -r 18518 -e signed-integer -b 16 -c 1 samples/edited_wav/kick_18518.wav

# Prepare a higher-rate version only if listening proves it is worth the memory.
sox raw_decoded_adpcma.wav -r 32000 -e signed-integer -b 16 -c 1 samples/edited_wav/kick_32000.wav

# Prepare a rendered FM/SSG instrument root sample for straightforward TAD instrument setup.
sox fm_bass_C2_render.wav -r 32000 -e signed-integer -b 16 -c 1 samples/edited_wav/fm_bass_C2_32000.wav
```

The manifest must say exactly what happened:

```text
sample_id: a_001_kick
source: YM2610 ADPCM-A
source_window: 0x012300-0x0127ff
decoded_rate_hz: 18518
tad_type: sample
tad_sample_rates: [18518]
brr_file: samples/brr/a_001_kick.brr
loop: none
used_by: 03 Main BGM 1, 04 Boss BGM 1
notes: kept natural rate; not resampled to 32k to save ARAM
```

### TAD-specific practical constraints

Terrific Audio Driver is sample-based and MML-based, and it combines samples plus sound effect data into common audio data. The README notes no sample swapping in the normal model, and the project has finite audio RAM. So do not import the whole YM2610 sample ROM.

Curate aggressively:

- Keep iconic percussion/hit samples.
- Keep short UI/game samples: coin, round clear, continue, game over.
- Keep any Superman-specific recognizable stingers.
- For redundant drums, keep the cleanest/most flexible version.
- For long ADPCM-B samples, decide whether they are worth the space.
- For music-only one-shots, consider replacing them with compact SNES-native approximations if they cost too much.

Use TAD's project check / GUI to confirm the final audio data fits.

---

## 13. FM and SSG are not “samples” until you make them samples

The YM2610 FM and SSG parts do not live in the ADPCM ROM blocks. They are generated by chip registers.

For SNES/TAD, the practical choices are:

### Option A — resample FM/SSG instruments

Render clean single-note samples from the original chip sound, loop them, and use them as TAD instruments.

Good for:

- basses;
- brass-like FM leads;
- organ-like tones;
- simple square/noise colors;
- sustained pads or drones.

Bad for:

- very expressive FM patches whose timbre changes heavily by note or velocity;
- fast FM algorithm changes;
- complex pitch/LFO behavior.

### Option B — approximate with SNES-native sample design

Build a similar SNES instrument rather than directly sampling the YM2610.

Good for:

- square waves;
- noise hits;
- generic basses;
- simple sustained tones.

### Option C — render short phrases

Render an entire phrase or riff as a sample.

Use sparingly. This can sound accurate but burns memory quickly and reduces musical flexibility.

### Recommended approach for Superman

Use VGM2MID to recover notes, then build a small custom SNES sample set:

- a few FM-style bass/lead/brass samples;
- square/noise samples for SSG-like parts;
- decoded YM2610 ADPCM drums/hits;
- a small number of special stingers.

This will feel more like a real SNES adaptation than a giant sample dump.

---

## 14. Track conversion priority

Suggested order:

| Priority | Track(s) | Reason |
|---:|---|---|
| 1 | 03 Main BGM 1 | Main gameplay identity; also likely includes recognizable Williams material. |
| 2 | 08 Main BGM 3 | Major stage/gameplay cue with longer loop. |
| 3 | 19 Ending | Important presentation cue; check rights risk. |
| 4 | 02 Coin, 07 Round Clear, 12 Continue, 21 Game Over | Short cues validate SFX/music event handling and samples. |
| 5 | Boss BGMs | Reuse instrument set; good stress test for loops and percussion. |
| 6 | Round 5-1 through 5-4 | Short late-game cues; useful after the instrument library is stable. |
| 7 | 01 Attract Mode, 20 Name Entry | Presentation polish. |

Start with one long BGM and two short cues. Do not process all 21 tracks deeply before the first one proves the pipeline.

---

## 15. Suggested conversion deliverables per track

For each track, produce:

```text
[track].vgm                         original decompressed source
[track].reference.wav               trusted rendered audio
[track].event_trace.csv             VGM-derived register/note/sample events
[track].raw.mid                     Optional VGM2MID output
[track].cleaned.mid                 Optional DAW-cleaned MIDI
[track].loop_notes.md               loop start/end and tempo notes
[track].source_breakdown.md         FM / SSG / ADPCM observations
[track].mml_draft.mml               first TAD MML draft
[track].mml_notes.md                assumptions, hand edits, and mismatch notes
```

For sample extraction, produce global files:

```text
sample_catalog_events.csv           every observed sample trigger
sample_catalog_deduped.csv          unique sample windows
sample_rom_sha1.txt                 ROM dump hashes
sample_decode_notes.md              decoder settings and known bad windows
sample_keep_list.md                 what should go into TAD and why
```

---

## 16. Quality checks

### MIDI quality check

A cleaned MIDI is acceptable when:

- tempo grid aligns to the reference WAV;
- loop start/end are documented;
- important melody/bass/harmony notes are correct;
- percussion/sample triggers are rhythmically correct;
- known converter errors are listed;
- no one mistakes General MIDI playback for the final sound.

### Sample quality check

An extracted sample is acceptable when:

- its start/end address came from YM2610 writes, not guessing;
- its ADPCM-A vs ADPCM-B type is known;
- its decode rate is documented;
- it has been compared to the reference VGM playback;
- raw and edited versions are both preserved;
- BRR conversion does not introduce unacceptable clicking or pitch error;
- its TAD memory cost is known.

### TAD readiness check

A sample/instrument is ready for TAD when:

- the source WAV is mono;
- loop points are set if needed;
- pitch root/frequency is documented;
- expected octave range is limited;
- ADSR/GAIN starting point is noted;
- the sample is actually used by at least one converted track or sound effect.

---

## 17. Rights and release caution

This pack includes music connected to John Williams' *Superman* film theme according to VGMRips comments. Also, decoded samples and transcribed arrangements may still be protected game/audio content.

For private technical conversion, preserve the source accurately. For any public release, get a rights review before shipping music, samples, or recognizable arrangements.

---

## 18. Known traps

1. **Do not decode YM2610 ADPCM as generic IMA ADPCM.** It will sound wrong.
2. **Do not normalize every sample independently.** You will destroy the original mix balance.
3. **Do not trust raw VGM2MID output blindly.** It is a map, not the territory.
4. **Do not assume every VGZ contains the full sample ROM.** Some VGMs may contain only used regions.
5. **Do not assume all samples are music samples.** VGMRips music packs may omit gameplay-only SFX.
6. **Do not import a full 512 KB arcade ADPCM ROM into TAD.** Curate.
7. **Do not ignore loop metadata.** The pack's `intro + loop` timing is important.
8. **Do not overfit to stereo.** The arcade hardware documentation for *Superman* treats cabinet output as mono.
9. **Do not collapse FM/SSG/ADPCM into one rendered sample unless there is no other practical choice.** You want editable SNES music, not just baked audio.
10. **Do not resolve the YM2610 vs YM2610B discrepancy by assumption.** Read the VGM header and inspect actual channel usage.

---

## 19. Source references

Use these as the first references when validating this conversion path:

- VGMRips pack page: `https://vgmrips.net/packs/pack/superman-taito-x-system`
- VGM specification: `https://vgmrips.net/wiki/VGM_Specification`
- VGMRips VGM2MID page: `https://vgmrips.net/wiki/Vgm2mid`
- VGMRips vgm_sro page: `https://vgmrips.net/wiki/Vgm_sro`
- Terrific Audio Driver repository: `https://github.com/undisbeliever/terrific-audio-driver`
- Terrific Audio Driver overview blog: `https://undisbeliever.net/blog/20231231-terrific-audio-driver.html`
- YM2610 ADPCM decoder notes: `https://wiki.neogeodev.org/index.php?title=ADPCM_codecs`
- YM2610 application manual translation: `https://www.ajworld.net/neogeodev/ym2610am2.html`
- `superctr/adpcm` command-line ADPCM library: `https://github.com/superctr/adpcm`

---

## 20. Immediate next action

Do this first:

1. Download the VGMRips ZIP.
2. Unpack VGZ to VGM.
3. Run the header report.
4. Render `03 Main BGM 1` to reference WAV.
5. Dump its YM2610 sample-ROM blocks.
6. Build a first sample-event catalog for that one track.
7. Create a direct MML draft for the first 8-16 bars.
8. Use raw MIDI only if the MML worker needs piano-roll help.

Only after `03 Main BGM 1` proves the MML/sample pipeline should the worker batch-convert the rest of the pack.
