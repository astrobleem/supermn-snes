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

The original MC68000 program already drives the game's tasks, combat, objects, and
stage progression through the interpreter plus native hot-path escapes. An older
README's “bulk game-logic port underway” row was a superseded phase snapshot, not the
current roadmap. Remaining work is whole-game correctness and stability, renderer
fidelity/conservation, Stage 2 presentation, audio fidelity, performance revalidation,
hardware acceptance, and a complete playthrough.

The current v135 ROM is 4 MiB with SHA-256
`5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`.
It fixes a reproduced IRAM-erasure freeze and restores the top HUD, but it has not
passed a fresh full-stage or full-game playtest. Renderer conservation, attack
animation tiles, organic Stage 2 scrolling, musical fidelity, aligned MAME pixels,
formal current-candidate performance, and hardware acceptance remain open.

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
| A or X | Button 2: jump |

The arcade game has two action buttons; there is no separate kick input. See
[controls and playtesting](docs/current/CONTROLS.md).

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
