# SOUNDHARDWARE.md — Superman Arcade (Taito, 1988)

## Purpose

This file is a focused handoff for understanding the **original arcade sound hardware** in Taito's *Superman* arcade game. It is intended to help an audio systems worker start from the real arcade architecture before designing any replacement, conversion, playback, or console-side audio driver.

This document intentionally avoids deep SNES/SPC700 design. The immediate goal is to understand what the arcade did.

---

## 1. Executive summary

*Superman* runs on **Taito X System** hardware and uses a dedicated sound subsystem built around:

- **Main CPU:** Motorola 68000.
- **Sound CPU:** Zilog Z80.
- **Protection / controller chip:** Taito C-Chip / NEC uPD78C11 class device is present in the game set metadata.
- **Sound generator:** Yamaha **YM2610 OPNB**.
- **Output:** documented as **mono** in Arcade Database metadata.
- **Sound communication:** Taito **TC0140SYT** style command interface between the 68000 and the Z80 sound CPU, as represented by MAME's Taito X driver.

The most important design takeaway: **do not think of this as simple streamed sample playback.** The original audio is a Z80-controlled YM2610 system using a mix of FM synthesis, SSG square/noise channels, and ADPCM sample playback.

---

## 2. Confirmed hardware facts

| Item | Confirmed / best-known value | Notes |
|---|---:|---|
| Game | *Superman* | Taito, 1988. |
| Hardware family | Taito X System | Also referred to by MAME driver source `taito/taito_x.cpp`. |
| Board / set IDs | `K1100390A`, prom stickers `B61` | Arcade Database lists these for *Superman*. |
| MAME driver PCB reference | `P0-039A` | MAME's source header lists *Superman* as `P0-039A`; MAME comments also mention `J1100145A` / `K1100331A` around a board-layout block. Treat physical board labels as something to verify if exact PCB reproduction matters. |
| Main CPU | Motorola 68000 | Nominally listed as 8 MHz by Arcade Database / System16 / VGMdb-style hardware pages. |
| Sound CPU | Zilog Z80 | Nominally listed as 4 MHz by Arcade Database / System16 / VGMdb-style hardware pages. |
| Audio chip | Yamaha YM2610 OPNB | Consistently listed for *Superman*. |
| YM2610 nominal clock | 8 MHz | YM2610 manual also describes an 8 MHz master clock. Some current MAME-derived metadata reports 7.63 MHz effective clock; see the clock caveat below. |
| Audio output | Mono | Arcade Database reports `Sound: Mono` and audio chips as `Speaker, YM2610 OPNB`. |
| External sample files | None | The audio samples are not external loose MAME “sample” files; they are part of the YM2610 ADPCM ROM data in the game set. |

### Clock caveat

Most hardware summaries list the Taito X system as:

- 68000 @ 8 MHz
- Z80 @ 4 MHz
- YM2610 @ 8 MHz

However, at least one current MAME-derived metadata page reports effective clocks as:

- MC68000: 7.63 MHz
- Z80: 3.81 MHz
- uPD78C11: 7.63 MHz
- YM2610 OPNB: 7.63 MHz

For design work, use **8 / 4 / 8 MHz as the nominal hardware identity**, but verify pitch and tempo against current MAME and, ideally, PCB capture before final tuning. If a port sounds slightly sharp or flat, this clock discrepancy is a likely cause.

---

## 3. Original audio architecture

High-level flow:

```text
68000 game program
    |
    | sound command / status through Taito TC0140SYT-style interface
    v
Z80 sound CPU
    |
    | writes YM2610 address/data registers
    v
Yamaha YM2610 OPNB
    |             |             |
    |             |             +-- ADPCM-B: 1 variable-rate sample channel
    |             +---------------- ADPCM-A: 6 fixed-rate sample channels
    +------------------------------ FM + SSG tone/noise channels

YM2610 digital FM/ADPCM path -> external DAC / analog mix
YM2610 SSG path              -> direct mono analog output path

Final board mix -> amplifier -> mono speaker
```

The key operational model is:

1. The 68000 decides that music or a sound effect should happen.
2. It writes a sound command through the Taito sound communication device.
3. The Z80 sound program receives or polls that command.
4. The Z80 sound program writes YM2610 registers to start music, trigger ADPCM samples, change instruments, update volume, or stop sounds.
5. The YM2610 generates the final sound mix from FM, SSG, and ADPCM sources.

---

## 4. Yamaha YM2610 OPNB capability summary

The YM2610 is not a PCM-only chip. It combines multiple sound sources.

### 4.1 FM section

- **4 FM channels**.
- **4 operators per channel**.
- **8 algorithms**.
- Built-in **LFO** for amplitude and pitch modulation.
- Two programmable timers.
- Left/right output control at the chip level, even if the cabinet/game output is treated as mono.

Practical meaning: melodic music and some sustained effects are likely FM patches driven by the Z80 music engine, not samples.

### 4.2 SSG section

- **3 square-wave channels** plus white noise capability.
- SSG output is a direct analog mono-style output path, separate from the YM2610's FM/ADPCM serial DAC path.

Practical meaning: simple bleeps, noise bursts, percussion accents, or support tones may come from SSG rather than FM or ADPCM.

### 4.3 ADPCM-A section

- **6 ADPCM-A channels**.
- 4-bit ADPCM data.
- Fixed **18.5 kHz** sampling rate at the standard YM2610 clock.
- External ROM-backed sample playback.
- Start and end addresses are set externally with **256-byte resolution**.
- Event-driven key-on behavior.
- Per-channel level and left/right output control.

Practical meaning: short one-shot effects, percussion, impacts, voice-like snippets, and arcade-style sampled hits may use ADPCM-A.

### 4.4 ADPCM-B section

- **1 ADPCM-B channel**.
- 4-bit ADPCM data.
- Variable sampling rate, roughly **1.8 kHz to 55.5 kHz**.
- External ROM-backed sample playback.
- Start and end addresses use **256-byte resolution**.
- Repeat playback is possible.
- Output level and left/right output control are available.

Practical meaning: ADPCM-B is the better candidate for longer or pitch-variable sampled material.

### 4.5 Total source count

A useful mental model is **14 total internal sources**:

- 4 FM
- 3 SSG
- 6 ADPCM-A
- 1 ADPCM-B

Not every source is necessarily used heavily by *Superman*, but the original hardware allows that mix.

---

## 5. 68000-side sound command interface

MAME's Taito X driver maps the main 68000 sound interface for *Superman* like this:

| 68000 address | Function in MAME driver | Meaning |
|---:|---|---|
| `0x800001` | `tc0140syt.master_port_w` | Select/control sound communication port. |
| `0x800003` | `tc0140syt.master_comm_r` / `master_comm_w` | Main CPU reads/writes sound communication data. |

Practical interpretation:

- The 68000 does **not** write YM2610 registers directly.
- It sends compact command/status values through the Taito sound communication device.
- The Z80 owns the YM2610.
- Any faithful audio reconstruction should identify the command IDs that the 68000 sends and how the Z80 interprets them.

---

## 6. Z80 sound CPU memory map

MAME's Taito X sound map for the YM2610 games is the best starting point.

| Z80 address | MAME mapping | Purpose |
|---:|---|---|
| `0x0000-0x3FFF` | ROM | Fixed Z80 sound program area. |
| `0x4000-0x7FFF` | Banked ROM via `z80bank` | Switchable 16 KB window into the sound program region. |
| `0xC000-0xDFFF` | RAM | Z80 work RAM. |
| `0xE000-0xE003` | YM2610 read/write | Four YM2610 access ports: status/address/data style access. |
| `0xE200` | `tc0140syt.slave_port_w` | Z80 side of Taito sound communication port select/control. |
| `0xE201` | `tc0140syt.slave_comm_r` / `slave_comm_w` | Z80 side command/status data. |
| `0xE400-0xE403` | Pan writes, no-op in MAME | MAME labels this as `pan`; original board may have had panning/mixer control, but *Superman* is documented as mono. |
| `0xEA00` | no-op read | Unknown / unused in the emulation map. |
| `0xEE00` | no-op write | Unknown. |
| `0xF000` | no-op write | Unknown. |
| `0xF200` | sound bank switch | Writes select the Z80 bank using `data & 3`. |

### Bank switching

The sound bank switch is simple in MAME:

```c
bank = data & 3;
```

The Z80 has:

- fixed 16 KB at `0x0000-0x3FFF`
- one banked 16 KB window at `0x4000-0x7FFF`
- up to four bank entries selected by the low two bits

This strongly suggests the Z80 sound program is laid out in 16 KB pages. If the project disassembles the sound program, preserve bank context in every symbol, table, and call graph.

---

## 7. ROMs relevant to sound

Current MAME-derived ROM metadata for the parent set lists these files:

| ROM label | Size | Likely role |
|---|---:|---|
| `b61_09.a10` | 128 KB | Main program ROM region. Not sound-specific. |
| `b61_07.a5` | 128 KB | Main program ROM region. Not sound-specific. |
| `b61_08.a8` | 128 KB | Main program ROM region. Not sound-specific. |
| `b61_13.a3` | 128 KB | Main program ROM region. Not sound-specific. |
| `b61_10.d18` | 64 KB | **Likely Z80 sound program ROM.** Size matches a 64 KB Z80 region split into 16 KB fixed + banked pages. Verify against MAME XML/source before naming symbols. |
| `b61-14.f1` | 512 KB | Graphics ROM. Not sound-specific. |
| `b61-15.h1` | 512 KB | Graphics ROM. Not sound-specific. |
| `b61-16.j1` | 512 KB | Graphics ROM. Not sound-specific. |
| `b61-17.k1` | 512 KB | Graphics ROM. Not sound-specific. |
| `b61-01.e18` | 512 KB | **Likely YM2610 ADPCM sample ROM.** Verify exact ADPCM-A vs ADPCM-B address use by tracing YM2610 register writes. |
| `b61_11.m11` | 8 KB | C-Chip / protection/controller ROM data, not an audio sample ROM. |

The two files to prioritize for sound reverse engineering are:

1. `b61_10.d18` — likely Z80 sound program.
2. `b61-01.e18` — likely YM2610 sample data.

Do not treat this table as permission to distribute ROM data. It is only a map for internal preservation/reimplementation work.

---

## 8. What the original sound program probably does

The exact command IDs and music engine format need to be extracted from the Z80 program. Based on the hardware map, the engine probably includes these responsibilities:

- Poll or receive commands from the 68000 through TC0140SYT.
- Maintain music state and sound-effect priority state.
- Write YM2610 FM patch registers.
- Trigger ADPCM-A and/or ADPCM-B samples by writing start/end address registers and key-on values.
- Manage YM2610 timers or tempo counters.
- Switch Z80 ROM banks at `0xF200` when reading music data, tables, or engine code outside the fixed 16 KB region.
- Possibly write to panning/mixer registers at `0xE400-0xE403`; MAME currently treats those writes as no-ops for this driver.

### Command-level work that still needs to be done

Build a command table from gameplay and program analysis. At minimum, capture commands for:

- boot / reset
- attract-mode music
- coin insert
- start / player join
- round start
- round clear
- boss start
- player punch
- player kick
- heat vision / projectile attack
- enemy hit
- player damage
- item pickup
- special crystal pickup
- throw object
- explosion
- life lost
- continue countdown
- game over
- ending

---

## 9. Important source inconsistencies and traps

### 9.1 YM2610 is the target, not YM2151 and not YM2203

Taito X System games vary by title. Some use YM2610; Daisenpu / Twin Hawk variants are associated with YM2151 + DAC in hardware summaries. *Superman* is consistently listed as **YM2610** by Arcade Database, System16, MAME's Taito X source summary, and the Taito board ID list.

A MAME source comment block around a PCB layout contains text that appears to mention `YM2203` and `3.000 MHz` near a section labelled *Superman*. That conflicts with the rest of the driver, the ROM metadata, and other hardware references. Treat that specific `YM2203` line as a likely misplaced/legacy/comment artifact unless verified against a physical *Superman* PCB.

### 9.2 DAC identification needs physical verification

Generic YM2610 documentation says the YM2610 uses a compatible external DAC such as YM3016 for FM/ADPCM output, while SSG has its own analog output. A MAME PCB-layout comment near the contested layout block lists `YM3014`, but that same block has other inconsistencies.

For a gameplay-faithful audio recreation, the exact DAC package is less important than correct YM2610 behavior and final mix. For an analog-circuit-faithful recreation, verify the physical PCB.

### 9.3 Mono output changes how panning should be interpreted

The YM2610 has left/right output control, and MAME's Z80 map labels `0xE400-0xE403` as `pan`. However, Arcade Database lists *Superman* audio as **mono**.

Therefore:

- preserve YM2610 left/right register writes in traces,
- but expect the cabinet output to collapse to mono,
- and do not build a stereo interpretation unless supported by PCB/manual evidence.

### 9.4 The John Williams Superman theme is part of the audio identity

Arcade history metadata notes that the game begins with the John Williams *Superman: The Movie* score. This matters for content review, rights review, and any public release. Technically, the opening music should be treated as a high-priority reference track for verifying FM/ADPCM timing, pitch, and instrumentation.

---

## 10. Preservation priorities for an audio implementation

A worker starting from the original hardware should preserve these behaviors in order:

1. **Command timing:** when the 68000 asks the Z80 to start/stop/switch sounds.
2. **Sound priority:** what happens when multiple effects compete with music or each other.
3. **YM2610 register behavior:** FM, SSG, ADPCM-A, ADPCM-B writes should be traceable to original behavior.
4. **Sample boundaries:** ADPCM start/end addresses should match original playback windows.
5. **Pitch and tempo:** use the clock caveat to tune against MAME/PCB reference.
6. **Mono mix balance:** final relative level between FM, SSG, ADPCM-A, and ADPCM-B matters more than theoretical stereo positioning.
7. **Music restart rules:** determine whether stage music restarts, resumes, ducks, or layers during boss/player events.

---

## 11. Recommended first tasks

### Task A — Produce a sound command log

Use MAME debugger/instrumentation or a custom build to log:

- 68000 writes to `0x800001` and `0x800003`
- Z80 reads/writes at `0xE200` and `0xE201`
- frame number / CPU cycle / game state when each command occurs

Output should be a CSV or Markdown table:

```text
frame, 68k_pc, command_port, command_value, z80_pc, observed_effect, notes
```

### Task B — Produce a YM2610 register trace

Log all Z80 accesses to `0xE000-0xE003`:

```text
time, z80_pc, ym_port, address, data, inferred_block, audible_effect
```

Then group writes by:

- FM patch setup
- note on/off
- SSG tone/noise
- ADPCM-A trigger
- ADPCM-B trigger
- volume/pan
- timer/tempo

### Task C — Build a sample catalog

From YM2610 ADPCM register writes, identify:

- start address
- end address
- channel
- ADPCM-A vs ADPCM-B
- approximate duration
- where it is heard in gameplay
- whether it is one-shot, looped, or retriggered

Expected output:

```text
sample_id, ym_block, channel, start, end, bytes, duration, first_seen, description
```

### Task D — Build an event-to-audio table

Tie game events to commands and YM writes:

```text
game_event, command_id, music_id, sfx_id, priority, interrupts_music, notes
```

This table is the bridge between game code and any new playback driver.

---

## 12. Minimal acceptance checklist

The original arcade hardware study is “good enough to hand to an audio driver implementer” when the worker can answer:

- What command starts each music cue?
- What command starts each common SFX?
- Which YM2610 sections are used for music?
- Which YM2610 sections are used for sound effects?
- Which ROM contains the Z80 sound program?
- Which ROM contains ADPCM sample data?
- How many Z80 banks are used, and what code/data lives in each?
- Is the final implementation mixed as mono?
- Are clock/pitch differences accounted for?
- Are John Williams-theme rights risks documented for any release build?

---

## 13. Source notes

Primary source types used for this document:

- MAME project / MAME Taito X driver: hardware documentation through emulation source.
- Arcade Database: MAME metadata, technical listing, chip list, board ID, audio mono status.
- System16: Taito X System hardware summary.
- Taito board ID list: `B61` entry showing 68000 + Z80 + C-Chip + YM2610.
- Yamaha YM2610 application manual translation: YM2610 feature behavior.
- NeoGeo Development Wiki YM2610 notes: useful practical description of YM2610 outputs and ADPCM buses.

Useful URLs:

- https://github.com/mamedev/mame/blob/master/src/mame/taito/taito_x.cpp
- https://adb.arcadeitalia.net/dettaglio_mame.php?game_name=superman
- https://www.system16.com/hardware.php?id=649
- https://www.mikesarcade.com/cgi-bin/spies.cgi?action=url&page=TaitoBoardList.txt&type=info
- https://vgmrips.net/wiki/Taito_X_System
- https://ajworld.net/neogeodev/ym2610am_en.html
- https://wiki.neogeodev.org/index.php/YM2610

