# Palette + Sprite-Palette Verdict — Ground-Truth-Validated on a Real SNES PPU

Date: June 16, 2026
Method: reproduce a real Superman **gameplay** frame's foreground sprites on the
actual SNES PPU (Mesen, via the MCP server) and compare pixel colors against
MAME's own rendered screen for the same frame. This is the authoritative result;
it supersedes the earlier swatch-only proof (see "Correction" below).

## Headline findings

1. **Arcade palette decode (validated):** Taito X palette RAM at `$B00000` is
   `xRGB_555` — `bits14-10=R, bits9-5=G, bits4-0=B`. The MAME byte dump is
   **big-endian** (`read_u8(even)` = high byte), so the logical word is
   `W = (byte0<<8)|byte1`. MAME's on-screen RGB = `pal5bit(R/G/B)` of that W.
   Verified: this decode reproduces **47/47** unique colors in the MAME frame,
   and **100%** of our rendered sprite pixels use a color MAME actually displays.

2. **Arcade → SNES color conversion (validated):** SNES CGRAM is `xBGR_555`
   (blue high, red low), so `SNES = (B<<10)|(G<<5)|R` with `R=(W>>10)&1f,
   G=(W>>5)&1f, B=W&1f`. Confirmed on the real SNES PPU (Superman renders blue
   with a red cape, matching the arcade exactly).

3. **Sprites are colored per-bank at runtime, NOT per-tile.** The X1-001 sprite
   color field (X-word bits 11-15, range 0-31) selects one of 32 16-color
   palette banks; the tile is just a bank-agnostic 4bpp index
   (`pen = color*16 + index`, index 0 = transparent). Tile-aware offline
   quantization is the wrong model. (`x1_001.cpp` draw_sprites.)

4. **The sprite palette is DYNAMIC.** The game rewrites palette RAM per scene —
   the same bank number holds different colors at different times (proven: a
   bank with 29k uses across the trace was all-zero in a later frame's dump).
   There is no single static sprite palette to bake offline.

5. **≤ 7 banks are used simultaneously → the SNES's 8 OBJ palettes are enough
   with ZERO color reduction.** Runtime trace (frames 200-3000): 13 distinct
   banks used over time, but **max 7 in any single frame** (frame 1873, 136
   active sprites). So the correct port loads the ≤8 active banks into the 8 SNES
   OBJ palettes each frame and remaps the OAM palette field — no quantization.

## The proof (real SNES PPU)

`tools/build_snes_sprite_scene.py` takes one MAME-captured frame (sprite RAM +
palette + the assembled gfx1 region, all via `read_u16`) and builds a complete
SNES OBJ ROM (`build/objscene.sfc`):
- 16×16 planar sprites → SNES 4bpp packed tiles (110 sprites, 76 tiles),
- 6 arcade banks → 6 SNES OBJ palettes (`xRGB→xBGR`, no quant),
- arcade sprite RAM → SNES OAM (X/Y/tile/pal/flip, 16×16).

Rendered in Mesen and compared to MAME (`compare_mame_vs_snes.png`): foreground
sprites match in color and position. **34/34** distinct SNES sprite colors are
real arcade colors. Differences are only the unrendered background playfield
(drawn by the X1-001's *other* sprite path) and horizontal clipping (SNES 256px
vs arcade 384px).

## Correction to the earlier (June 16, AM) palette proof

The first "palette validated" pass built a swatch reference from the **same**
decode function it was testing, so it proved self-consistency, not correctness —
the classic trap. Under that, two real errors went unseen:
- the byte dump was read **little-endian** (it is big-endian), scrambling colors;
- the "R↔B swap fix" was reasoning from those byte-swapped values.

The swatch ROM *did* correctly prove the DMA/register data path on hardware; it
just couldn't prove the colors were right without external ground truth. The
fix: always validate against MAME's actual screen (now done).

## What this means for the port (sprite palette recipe)

- Mirror the arcade's palette-RAM writes: when game logic writes a sprite bank,
  convert `xRGB→xBGR` and DMA it into the matching SNES OBJ palette.
- Track the ≤8 active banks per frame → 8 OBJ palette slots; remap each sprite's
  OAM palette field through that bank→slot map.
- No offline palette quantization for sprites. `tools/optimize_palettes.py` is
  superseded for sprites (header note added).
- Fallback (only if a frame ever needs >8 banks — not observed): merge the two
  nearest banks. Document any such merge; don't do it silently.

## Background playfield (X1-001 "type0" path) — also solved & validated

The church/bricks background is the X1-001's **other** draw path
(`draw_background`, `spritecode[0x400+i]`=code, `[0x600+i]`=color), a
column-based tilemap: `numcol` columns (16 here) of 16×16 tiles, with per-column
scroll from `scrollram` (`$D00400`). Key finding from the runtime dump:

- In the captured Stage 1 frame, **`scrolly` is uniform and `scrollx` steps by
  exactly 32 per column** — i.e. the "per-column scroll" is just the hardware
  doing a single continuous horizontal scroll across 32px columns. **For that
  frame, the background is a standard scrolling tilemap** that maps directly
  to a SNES BG layer.
- Logical map = 32×16 grid of 16×16 tiles; 119 distinct tiles, **2 color banks**
  (18, 21) for this frame. Same `xRGB555` + bank color model as the sprites.

> **R14 correction (July 24, 2026):** the post-boss vertical section uses
> multiple simultaneous X1-001 `scrolly` groups, so the uniform Stage 1 dump
> was not a whole-game invariant. SNES BG1 has one global Y register; exact
> v134 follows arcade column 4 from the large center-playfield group. See
> `docs/handoff/V134_STAGE2_VERTICAL_SCROLL_20260724.md`. Exact per-column
> vertical fidelity remains open.

`tools/render_full_frame.py` renders backdrop+bg+fg and matches MAME (47/47
frame colors). `tools/build_snes_full_scene.py` builds a full SNES ROM
(`build/fullscene.sfc`, 6 banks): BG1 = the playfield (64×32 4bpp tilemap, 2 BG
palettes), OBJ = the foreground sprites (6 OBJ palettes). Rendered on the real
SNES PPU (`compare_full_mame_vs_snes.png`): **47/47 colors match MAME**; the SNES
256px screen shows the left 256px window of the arcade's 384px frame.

Both X1-001 paths now have a SNES home: **playfield → BG layer, sprites → OBJ.**

## Validated decode reference (for the transpiler / asset tools)

| Field | Source | Decode |
|---|---|---|
| sprite tile code | `$E00000 + 2i` (word i) | `code & 0x3FFF`; bit15=flipX, bit14=flipY |
| sprite X + color | `$E00000 + 0x400 + 2i` | `color=(w>>11)&0x1F`; `sx=(w&0xff)-(w&0x100)` |
| sprite Y | `$D00000 + 2i` | `m_spriteylow[i] & 0xff` |
| palette word | `$B00000 + 2i` | `xRGB555`; SNES=`(B<<10)|(G<<5)|R` |
| gfx tiles | gfx1 region, 16×16 4bpp | tilelayout; **plane[0]=MSB** |

68K is big-endian; dump via `read_u16` to avoid byte-lane confusion.
