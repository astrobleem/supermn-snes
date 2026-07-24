# Current Superman architecture

Superman is not a conventional source port. The SNES cartridge carries private
derived images of the original arcade program and graphics. The SA-1 executes the
original MC68000 program through an interpreter, while measured hot paths can dispatch
to native 65816 escapes.

```text
private 68000 ROM image
          |
          v
SA-1: MC68000 interpreter <----> native 65816 escapes/HLE
          |                              |
          +---------- emulated state ----+
                         |
              BW-RAM $40 / video $41
                 |               |
                 |               +----> 5A22 renderer ----> SNES PPU
                 +---- sound ring -----> 5A22 TAD host ----> SPC700

SNES controller ----> 5A22 input cache ----> emulated C-Chip mailbox
```

## Ownership

| Component | Primary responsibility |
|---|---|
| SA-1 | MC68000 interpreter, native escape dispatch, game state, render-manifest production |
| 5A22 | Cartridge boot, temporary Mode 7 screen, VBlank/NMI supervision, PPU DMA, input publication, TAD host processing |
| SPC700/TAD | Sample-based music and sound-effect playback |
| MAME 0.287 | Independent arcade behavior/register/memory oracle |
| Nexen | SNES/SA-1/PPU timing and target-machine oracle |
| Mesen 2.1.1 | Compatibility reproduction for the user's emulator and historical save states |

## Data and memory

- `data/superman_m68k.bin` is a private 512 KiB interleaved image of the original
  68000 program.
- Arcade program addresses `$000000-$07FFFF` are fetched from that image.
- Arcade work RAM `$F00000-$F03FFF` maps into SA-1 BW-RAM bank `$40`. The emulator's
  backing/differential tools may inspect a wider 64 KiB window, but only the MAME-mapped
  16 KiB is ordinary game RAM.
- Palette/X1-001 writes are routed into the `$41` video shadow and later converted into
  SNES CGRAM, VRAM, OAM, and scroll state.
- The 68000 register file and interpreter control cells live in SA-1 IRAM/direct page.
- Native code occupies bank `$00` islands and escape banks `$92+`; a generated
  translation table maps selected 68000 PCs to native entries.

## Execution model

The interpreter is the cold, correctness-first fallback. Native escapes are
optimizations and game-specific HLE only after:

1. the entry path is observed;
2. the native hook is proven to fire in its real execution bank;
3. native and interpreted state match on representative fixtures;
4. gate-off behavior remains unchanged; and
5. sustained scheduling/rendering remains live.

The game's cooperative task scheduler and IRQ cadence are part of observable game
behavior. The production path paces game logic at a nominal 30 Hz target on the 60 Hz
SNES display and queues complete render candidates for asynchronous 5A22 consumption.
Shortening the wait or changing wake/DMA order can reorder producer/consumer tasks and
has repeatedly caused delayed `$DEAD` halts.

## Audio model

The arcade Z80/YM2610 is not emulated on SNES. The 68000's command stream is captured
through the emulated TC0140SYT boundary and mapped to a consolidated TAD project.
VGMs provide the current music performance/patch oracle; FM is rendered into samples,
ADPCM-A drums are derived from the user's legal ROM, and TAD plays the result on SPC700.

## Read next

- [MC68000 interpreter](../toolchain/MC68000_INTERPRETER.md)
- [Transpiler workflow](../toolchain/TRANSPILER_WORKFLOW.md)
- [Address-map adaptation](../toolchain/ADDRESS_MAP_ADAPTATION.md)
- [Video renderer](VIDEO_RENDERER.md)
- [Scheduler and timing](../toolchain/SCHEDULER_TIMING.md)
- [VGM sound pipeline](../toolchain/SOUND_PIPELINE.md)
