# Graphics conversion and renderer adaptation

The transferable graphics method is **decode → reproduce → compare**. The specific
X1-001 renderer, crop, caches, and scroll bridges are game integration, not generic
MC68000 machinery.

## Asset path

1. Authenticate the source graphics ROMs and reproduce MAME's assembled graphics
   region byte-for-byte.
2. Decode the driver's exact plane, bit, X/Y offset, and tile-stride layout.
3. Convert indexed pixels offline into SNES planar tiles without assigning scene
   colors prematurely.
4. Pack converted assets with explicit hashes and ROM-range assertions.
5. At runtime, translate the arcade object/tile state into bounded SNES BG/OAM
   manifests and upload only through the declared PPU owner.

For Superman, `tools/mame-trace/gfx1.bin` is MAME's 2 MiB assembled `gfx1` region.
The X1-001 source tiles are 16×16 4bpp with plane 0 as the most-significant indexed
bit.

## Palette rule

Superman's palette RAM is xRGB555. Convert each word to SNES xBGR555 by swapping the
red and blue fields. Sprite tile data remains palette-bank-neutral: X1-001 object
attributes select dynamic banks at runtime.

The validated Superman frame used no more than seven simultaneous OBJ banks, so eight
SNES OBJ palettes were sufficient for that fixture. This does not establish a
universal bound for Gigandes or every Superman scene; trace each new corpus.

## X1-001 presentation

The family exposes two related paths:

- a column/tile playfield represented by object RAM and scroll values, mapped to an
  SNES BG layer; and
- foreground sprite strips, mapped to SNES OAM and a persistent converted-tile cache.

Reuse the decoder and manifest approach for Gigandes, but revalidate tile banks,
visibility, priority, flips, coordinate wrapping, simultaneous palette-bank count,
scroll groups, and screen crop. Related hardware is not evidence of identical game
usage.

## Validation ladder

1. Compare decoded indexed tiles with MAME's source region and driver layout.
2. Capture palette, video RAM, and control registers from one exact MAME frame.
3. Render a software reference from those bytes.
4. Build an SNES scene from the same bytes and inspect VRAM/CGRAM/OAM in Nexen.
5. Align the MAME and SNES visible regions and pixel-diff the result.
6. Run the organic renderer while checking bounded manifests, cache/VRAM identity,
   request/ACK/true-render conservation, no overflow, and continued game progress.
7. Repeat across title, transitions, each stage type, bosses, effects, and HUD.

The current Superman renderer still fails the conservation and aligned-pixel release
gates; a recognizable screenshot is not enough.

## Evidence and implementation references

- [Palette and frame evidence](GRAPHICS_PALETTE_EVIDENCE.md)
- [Sprite-scaling trace verdict](SPRITE_SCALING_EVIDENCE.md)
- [Current Superman video renderer](../current/VIDEO_RENDERER.md)
- [Historical object-processor campaign](../history/designs/OBJECT_PROCESSOR_CAMPAIGN_20260703.md)
- `tools/render_full_frame.py`
- `tools/build_snes_full_scene.py`
- `tools/build_snes_sprite_scene.py`
- `tools/validate_obj_cache_vram.py`
- `tools/validate_fast_obj_renderer.py`
- `tools/validate_paced_obj_sources.py`
