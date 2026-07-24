# MAME/Nexen differential validation

This project uses two independent truth sources:

- **MAME 0.287** supplies arcade MC68000, address-map, device, and rendered-game
  behavior.
- **Nexen** supplies SNES 5A22/SA-1/PPU execution, memory, timing, and screenshots.

Mesen 2.1.1 is additionally important for reproducing the user's emulator reports and
old save states. It is compatibility evidence, not the primary SA-1 timing oracle.

## Evidence ladder

| Gate | Proves | Does not prove |
|---|---|---|
| Single-op fixture | Covered MC68000 semantics | Whole-game mapping or control flow |
| Focused function differential | Covered entry/path/caller state | Other callers or later scheduling |
| Adjacent-tick lockstep | One representative live game boundary | Cold boot or long-term stability |
| Checkpointed soak | Sustained behavior from named state | Organic route to that state |
| Fresh cold-boot scenario | Boot, transitions, and tested scenario | Full playthrough |
| Formal production run | End-to-end rate and invariants for exact ROM | Musical/pixel fidelity or human playability |
| Human playtest | Real interaction and perceptual defects | Root cause without reproduction |

Always label an observation at the narrowest applicable level.

## CPU and escape comparison

Capture MAME state at a deterministic MC68000 boundary, inject the equivalent state
on SA-1, execute to the next boundary, and compare:

- D0-D7, A0-A7, PC, SR/CCR/X;
- live stack bytes and return residue;
- mapped work RAM;
- device-visible state;
- video shadow for rendering functions; and
- terminal reason and instruction/cycle counts as diagnostics.

When comparing native-on with native-off, start from the same adjacent state.
Sparse states can hide a caller, flag, or address-region assumption.

## Rendering comparison

Pause Nexen before coherent multi-read inspection. Compare the producer shadow and
manifest as well as PPU VRAM, CGRAM, OAM, registers, and final pixels. An unaligned
MAME screenshot or a visually plausible frame is not a pixel oracle.

## Timing comparison

Hooks can distort timing. Use non-pausing notification timestamps for phase
attribution and a power-on uninterrupted run for production rate. Never infer project
fps by multiplying an isolated speedup.

## Harness discipline

- Pin MAME to 0.287; recordings can desynchronize across versions.
- Retain MAME Lua taps/notifiers in globals so garbage collection does not remove them.
- Use the same MAME set, DIP state, inputs, and boundary on both sides.
- Start Nexen on a fresh port after a wedged session and pause before grouped reads.
- Record source commit, ROM hash, emulator build, interventions, start/end counters,
  raw logs, and output hashes.
- A refreshed save-state mirror or injected gate must be disclosed in the result.

The runnable inventory is in [tools/README.md](../../tools/README.md), detailed
operational traps are in [DEBUGGING.md](DEBUGGING.md), and current Superman gate
commands are in [current validation](../current/VALIDATION.md).
