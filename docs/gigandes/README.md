# Gigandes onboarding

Gigandes is the next proving ground for the reusable porting toolchain. It is a 1989
East Technology game on the Taito X hardware family, with an 8 MHz MC68000, X1-001
video, TC0140SYT sound communication, and an 8 MHz YM2610. MAME 0.287 reports a
384×240, 60 Hz raster display and two 8-way, two-button players.

The pinned hardware and map source is MAME 0.287's
[`taito_x.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/taito/taito_x.cpp).
Do not silently update the driver revision during bring-up.

## Reuse unchanged

- the MC68000 opcode/effective-address/exception core;
- the SA-1 direct-page register and split-CCR convention;
- big-endian BW-RAM helpers;
- optest/opsweep semantic gates;
- MAME trace/CDL and adjacent-state differential methods;
- the transpiler's CPU lowering core and fail-loud policy;
- Nexen inspection of SA-1, 5A22, VRAM, CGRAM, OAM, and PPU state; and
- the high-level VGM-to-TAD workflow.

Reuse means shared code plus a fresh integration proof. Gigandes must not inherit
Superman native escapes, HLE addresses, state fixtures, or performance claims.

## Game-specific work

| Concern | Gigandes fact or required adaptation |
|---|---|
| Program | Four 128 KiB ROMs form a 512 KiB MC68000 region with byte lanes defined by MAME |
| Work RAM | Taito X base map uses `$F00000-$F03FFF`; still revalidate reads, writes, and clear behavior |
| Video | Same X1-001 family ranges, but asset layout, object usage, banks, scroll groups, crop, and effects require new traces |
| Input/protection | `$900000-$90000F` is a direct input/coin device; Gigandes does **not** use Superman's C-Chip replay |
| DIP switches | `$500000-$500007`; DSWA bit 4 must remain off because MAME documents a hit-time hang when enabled |
| Watchdog/frame writes | `$400000` and `$600000` accept per-frame writes in MAME; preserve observed behavior |
| Sound | Same TC0140SYT boundary at `$800001/$800003`, but new command map, Z80 program, VGMs, ADPCM-A, and ADPCM-B |
| IRQ | Gigandes uses MC68000 IRQ level 2; Superman uses level 6 |
| Presentation | Arcade is 384×240 while the normal SNES view is 256 pixels wide; crop/framing is a first-class design decision |
| Timing | Arcade refresh and task cadence must be measured; do not inherit Superman's 30-tick product gate |

## Parent-set input inventory

Begin with the MAME 0.287 parent set `gigandes`, not the `gigandesa` earlier clone.
The new private-input preparer should authenticate filename, size, SHA-1, and SHA-256.
These MAME manifest facts are safe metadata; ROM contents remain private.

| Region | File | Size | MAME SHA-1 |
|---|---|---:|---|
| maincpu | `east_1.10a` | 131,072 | `1cac0a0e591b63142d8d249c67f803256fb28c2a` |
| maincpu | `east_3.5a` | 131,072 | `9255d7e0ab568ad7a894421d3260fa80b8a0a5d0` |
| maincpu | `east_2.8a` | 131,072 | `2efff9fd51b28fd1fb46d16b359f0991af91054e` |
| maincpu | `east_4.3a` | 131,072 | `49db488a36f6c74729825bdf0214bcd30773eaf4` |
| audiocpu | `east_5.17d` | 65,536 | `e4730df984e9686c538df5fc626b795bda1db939` |
| gfx1 | `east_8.3f` | 524,288 | `7ce66cd8bca7dd214367beae067727c8735c0f7e` |
| gfx1 | `east_7.3h` | 524,288 | `cff2caf1eb0dda8a1b8283b9950b908b102f61de` |
| gfx1 | `east_9.3j` | 524,288 | `f348ac752a571902c55f36e21aa3fb9ef97528e3` |
| gfx1 | `east_6.3k` | 524,288 | `0b6d73f2c6e6c1ad5fcb2a9edf50069cd0691483` |
| YM2610 ADPCM-B | `east-11.16f` | 524,288 | `e781f24761b7a923388f4cda64c7b31388fd64c5` |
| YM2610 ADPCM-A | `east-10.16e` | 524,288 | `b29f30a8ff1286c65b741353b6551918a45bcafe` |

MAME places the program files at region offsets `$000000/$000001` and
`$040000/$040001`, and the graphics files into a 2 MiB `gfx1` region. Generate the
assembled images according to those region directives and verify them against MAME;
do not concatenate filenames in table order.

## Known oracle risks

MAME's own driver notes describe cave-demo background glitches, apparent two-bank
flicker, missing background scroll, and high-score garbage as possible X1-001
emulation flaws. Treat MAME CPU/video RAM as strong evidence, but do not enshrine that
specific rendered defect as desired hardware behavior without another source.

There is also a timing discrepancy inside the pinned source: the active MAME machine
configuration and `-listxml` expose 60 Hz, while the P0-057A/P1-046A PCB notes cite
58 Hz. Measure real game/IRQ behavior and resolve that provenance before defining the
Gigandes production cadence.

The earlier clone also has a documented bogus test mode. Parent-set bring-up avoids
that extra ambiguity.

## Begin here

Follow [BRINGUP.md](BRINGUP.md) in order. The first milestone is not a screenshot; it
is an authenticated private program image that reaches a deterministic early MAME
boundary under the unchanged interpreter with Gigandes-specific map handling.
