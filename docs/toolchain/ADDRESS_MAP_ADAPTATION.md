# Address-map adaptation

The MC68000 core is reusable only if every memory access reaches the correct game
adapter. Build the address map from the pinned MAME driver and live traces; do not
infer it from a disassembly label or copy it from a related game.

## Required map inventory

For each region record:

- inclusive MC68000 range and lane mask;
- read, write, and read-after-write behavior;
- byte/word/long alignment;
- reset value and side effects;
- target backing store or target-side handler;
- confidence: driver, trace, differential, or hypothesis; and
- tests that fail if the mapping regresses.

Keep four concerns separate:

1. **program fetch** — ROM and any RAM-resident code;
2. **ordinary data** — work RAM and immutable tables;
3. **device state** — input, sound, watchdog, protection, palette, and video RAM;
4. **presentation shadow** — state staged for the 5A22/PPU rather than written
   directly by SA-1 game logic.

## Current Superman map

| Arcade range | Meaning | Current target treatment |
|---|---|---|
| `$000000-$07FFFF` | 512 KiB program ROM | private packed ROM image |
| `$300000/$400000/$600000` | per-frame ignored/control writes | observed no-op/frame-strobe handling |
| `$500000-$500007` | DIP/input reads | fixed configuration/input adapter |
| `$800001/$800003` | TC0140SYT port/communication | sound command/status adapter |
| `$900000-$9007FF` | C-Chip shared RAM | deterministic boot replay and input mailbox |
| `$900800-$900FFF` | C-Chip ASIC registers | observed status contract |
| `$B00000-$B00FFF` | xRGB555 palette RAM | `$41` video shadow |
| `$D00000-$D00607` | X1-001 Y/scroll/control | `$41` video shadow |
| `$E00000-$E03FFF` | X1-001 object/tile state | `$41` video shadow |
| `$F00000-$F03FFF` | 16 KiB work RAM | big-endian bytes in BW-RAM `$40` |

The old `$0B0000/$0E0000/$0F0000` spellings dropped a hexadecimal digit and are
wrong. The exact Superman C-Chip contract is documented separately because it does
not transfer to Gigandes.

## Adapter implementation rules

- Route stores by the **destination region**, not by the source instruction form.
- Do not assume an address register's region without a fixture covering every caller.
- Use the same map for interpreter helpers, transpiled helpers, HLE, DMA copies, and
  differential tooling.
- Preserve unmapped/open-bus or ignored-write behavior where game code observes it.
- Publish device side effects at the same logical boundary as the arcade program.
- Treat byte lanes explicitly; TC0140SYT and input devices frequently use only one
  lane of a 16-bit bus.

## New-game checklist

1. Pin the MAME version and driver source revision.
2. Export the driver's maps, ROM regions, CPU clocks, screen timing, and IRQ level.
3. Trace every mapped region during boot, attract, coin/start, and gameplay.
4. Implement ROM and work RAM first; leave device accesses loud/diagnostic.
5. Add input and watchdog behavior, then sound, video, and protection.
6. Compare MAME and SA-1 state at a deterministic boundary after each region lands.
7. Only then enable the scheduler and native hot paths.

See [Gigandes onboarding](../gigandes/README.md) for the first concrete second-game
map and [DEBUGGING.md](DEBUGGING.md) for the ROM-pointer fast-path failure class.
