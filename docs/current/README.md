# Current Superman project

This directory is the onboarding path for the active Superman SNES/SA-1 port.

## First hour

1. Start with the [project overview and visual showcase](../../README.md).
2. Read [STATUS.md](STATUS.md) for the honest current verdict.
3. Read [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md) before selecting work.
4. Follow [BUILDING.md](BUILDING.md) to prepare private inputs and build
   `build/interp.sfc`.
5. Use [CONTROLS.md](CONTROLS.md) for a human playtest.
6. Select the appropriate gate from [VALIDATION.md](VALIDATION.md).
7. Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing CPU ownership, memory
   routing, rendering, input, sound, or timing.
8. Use [ENGINEERING_CHECKPOINT_20260811.md](ENGINEERING_CHECKPOINT_20260811.md)
   for the latest exact hashes, completed campaign work, and next decisions.

## Superman-specific deep dives

- [Private ROM inputs](ROM_INPUTS.md)
- [Video renderer and PPU plumbing](VIDEO_RENDERER.md)
- [Historical object-processor native campaign](../history/designs/OBJECT_PROCESSOR_CAMPAIGN_20260703.md)
- [C-Chip boot handshake](CCHIP_BOOT_HANDSHAKE.md)
- [C-Chip firmware analysis](CCHIP_FIRMWARE.md)
- [Arcade-to-TAD sound command map](SOUND_COMMAND_MAP.md)

Transferable interpreter, transpiler, graphics, audio, validation, scheduler, and
debugging material lives in the [toolchain path](../toolchain/README.md). Dated
campaigns and rejected candidates live in the [historical archive](../history/README.md).
