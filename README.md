# Superman for SNES / SA-1

This project ports Taito's 1988 Superman arcade game to the Super Nintendo with an
SA-1 coprocessor. It is unusual because it runs the original MC68000 game program
through a hand-written 65816 interpreter, then replaces measured hot paths with native
65816 while translating Taito X video and YM2610 sound to SNES hardware.

MAME 0.287 is the arcade oracle. The MCP-enabled Nexen fork is the SNES/SA-1/PPU
oracle.

## Honest current state

The port boots, accepts real controller input, renders recognizable gameplay, and
plays VGM-derived TAD audio in controlled tests. It is an **interactive technical-demo
response candidate, not playable or shippable**.

The best evidence-backed ordinary candidate is the preserved 4 MiB `a976…`
image, SHA-256
`a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60`.
It has a fresh controller campaign through tick 10,000, but it is not a full-stage,
full-game, performance, or release result. A normal build of current source produces
the distinct, unpromoted ordinary image `2dadd12c…`; diagnostic VTIME images and
checkpoint migrations do not inherit the ordinary candidate's acceptance evidence.
See the [August 11 engineering checkpoint](docs/current/ENGINEERING_CHECKPOINT_20260811.md)
for the exact ROM identities, long campaign coverage, save-state workflow, and the
focused v7 input-order repair.

Renderer conservation, attack-animation tiles, organic Stage 2 scrolling, musical
fidelity, aligned MAME pixels, formal current-candidate performance, and hardware
acceptance remain open.

The latest end-to-end measurement satisfying the evidence protocol is older v124:
29.700167 game-fps and 360,990.164 SA-1 cycles/tick. It misses the current 30 Hz and
358,000-cycle gates.

Read the [authoritative status](docs/current/STATUS.md) and
[release blockers](docs/current/RELEASE_BLOCKERS.md) before changing code.

## Build

No copyrighted arcade ROM data is included. Supply a legally obtained MAME 0.287
`superman` World ROM set.

```sh
python3 tools/prepare_roms.py /path/to/superman.zip
bash tools/build_interp.sh
sha256sum build/interp.sfc
```

The ROM is written to `build/interp.sfc`. Exact FM authoring WAVs are a separate
private VGM/ymfm pipeline input; the ROM preparer derives the program, graphics,
C-Chip response, and drums but does not invent replacements for those WAVs.

See [complete build and toolchain setup](docs/current/BUILDING.md) and
[private-input details](docs/current/ROM_INPUTS.md).

## Controls

| SNES | Arcade action |
|---|---|
| Select | Coin |
| Start | Start |
| D-pad | Move |
| B or Y | Button 1: punch/fire; hold and release for charged shot |
| A or X | Button 2: kick |

The arcade game has two action buttons: punch/fire and kick. Pressing Up makes
Superman fly; there is no jump action. See [controls and playtesting](docs/current/CONTROLS.md).

## Documentation

The [documentation index](docs/README.md) has four paths:

1. current Superman status, build, controls, validation, and blockers;
2. reusable MC68000 arcade-to-SNES toolchain;
3. concrete Gigandes onboarding; and
4. preserved historical evidence, failed experiments, and forensics.

New toolchain work should start with
[the reusable architecture](docs/toolchain/README.md). The next-game effort should
start with [Gigandes bring-up](docs/gigandes/BRINGUP.md). Historical claims do not
override `docs/current/STATUS.md`.

## Legal boundary

Original project source and documentation may be tracked. Arcade ROMs, assembled ROM
regions, VGM/source audio where redistribution is not authorized, derived samples, and
SNES ROM builds remain private and gitignored.
