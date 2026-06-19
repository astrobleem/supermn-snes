#!/usr/bin/env python3
"""
Render arcade vs SNES comparison from MAME sprite dump.

Uses the REAL X1-001A sprite format from MAME source (x1_001.cpp):

Sprite RAM at $E00000 (16KB, accessed as 16-bit words):
  Words 0x000-0x1FF: sprite code (tile + flip flags)
    bits 0-12: tile code (0-16383)
    bit 14: flip Y
    bit 15: flip X
  Words 0x200-0x3FF: sprite X + color
    bits 0-7: X position (signed, bit 8 = sign)
    bits 11-15: color (palette index, 0-31)

Sprite Y at $D00000 (bytes 0x000-0x1FF):
  8-bit Y coordinates

Sprite control at $D00600 (bytes 0-7):
  Ctrl[0]: bit 0-1 = start column offset, bit 6 = screen flip
  Ctrl[2-3]: background scroll/high bits

Drawing order: sprites drawn from index m_spritelimit down to 0
(painter's algorithm, highest index = highest priority = drawn last/on top)
"""

import struct
import sys
import numpy as np
from pathlib import Path

# === Configuration ===
SPRITE_RAM_FILE = "tools/mame-trace/sprite_ram.bin"
SPRITE_Y_FILE = "tools/mame-trace/sprite_y.bin"
PALETTE_FILE = "tools/mame-trace/frame_palette.bin"
SNES_CGRAM_FILE = "data/palettes/sprites/sprites_16x16.cgram"
SNES_TILES_FILE = "data/palettes/sprites/sprites_16x16.tiles"
SNES_ASSIGN_FILE = "data/palettes/sprites/sprites_16x16.palassign"
ORIG_TILES_FILE = "data/tiles/sprites_16x16.bin"

SCREEN_W = 384
SCREEN_H = 240
TILE_SIZE = 8
NUM_SPRITES = 512


def read_arcade_palette(path):
    """Read arcade palette (xRGB_555, 2048 entries)."""
    with open(path, "rb") as f:
        data = f.read()
    palette = np.zeros((2048, 3), dtype=np.uint8)
    for i in range(min(2048, len(data) // 2)):
        # big-endian dump (read_u8(even)=high); arcade xRGB_555.
        # See optimize_palettes.read_arcade_palette / PALETTE_VERDICT.md.
        w = (data[i * 2] << 8) | data[i * 2 + 1]
        r = (w >> 10) & 0x1F
        g = (w >> 5) & 0x1F
        b = w & 0x1F
        palette[i] = [r, g, b]
    return palette


def read_snes_cgram(path):
    """Read SNES CGRAM (8 palettes × 16 colors × 2 bytes, BGR555)."""
    with open(path, "rb") as f:
        data = f.read()
    palettes = np.zeros((8, 16, 3), dtype=np.uint8)
    for p in range(8):
        for c in range(16):
            offset = (p * 16 + c) * 2
            lo = data[offset]
            hi = data[offset + 1]
            val = lo | (hi << 8)
            r = val & 0x1F
            g = (val >> 5) & 0x1F
            b = (val >> 10) & 0x1F
            palettes[p, c] = [r, g, b]
    return palettes


def read_snes_tiles(path):
    """Read SNES bitplane tiles (32 bytes per 8×8 tile)."""
    with open(path, "rb") as f:
        data = f.read()
    num_tiles = len(data) // 32
    tiles = np.zeros((num_tiles, 8, 8), dtype=np.uint8)
    for t in range(num_tiles):
        offset = t * 32
        for row in range(8):
            bp0 = data[offset + row * 2]
            bp1 = data[offset + row * 2 + 1]
            bp2 = data[offset + 16 + row * 2]
            bp3 = data[offset + 16 + row * 2 + 1]
            for px in range(8):
                idx = (
                    ((bp0 >> (7 - px)) & 1)
                    | (((bp1 >> (7 - px)) & 1) << 1)
                    | (((bp2 >> (7 - px)) & 1) << 2)
                    | (((bp3 >> (7 - px)) & 1) << 3)
                )
                tiles[t, row, px] = idx
    return tiles


def decode_sprite_ram(sprite_ram_raw, sprite_y_raw):
    """Decode X1-001A sprite RAM into sprite objects.
    
    sprite_ram_raw: 16384 bytes from $E00000
    sprite_y_raw: 1536 bytes from $D00000
    
    Returns list of sprite dicts with keys:
      code, flipx, flipy, x, y, color
    """
    # Parse sprite RAM as 16-bit LE words
    num_words = len(sprite_ram_raw) // 2
    sprite_ram = np.frombuffer(sprite_ram_raw, dtype='<u2')
    
    sprites = []
    for i in range(min(NUM_SPRITES, num_words // 2)):
        # char_pointer[i] = sprite_ram[i] (words 0x000-0x1FF)
        # x_pointer[i] = sprite_ram[0x200 + i] (words 0x200-0x3FF)
        if i >= len(sprite_ram) or 0x200 + i >= len(sprite_ram):
            break
            
        code_word = int(sprite_ram[i])
        x_word = int(sprite_ram[0x200 + i])
        
        # Y coordinate from sprite_y_raw
        y_val = sprite_y_raw[i] if i < len(sprite_y_raw) else 0xFF
        
        # Decode
        code = code_word & 0x3FFF
        flipx = (code_word >> 15) & 1
        flipy = (code_word >> 14) & 1
        
        # X position: bits 0-7, with bit 8 as sign
        sx = x_word & 0xFF
        if x_word & 0x0100:
            sx = sx - 256  # sign extend
        
        # Color: bits 11-15
        color = (x_word >> 11) & 0x1F
        
        sprites.append({
            'index': i,
            'code': code,
            'flipx': flipx,
            'flipy': flipy,
            'x': sx,
            'y': y_val,
            'color': color,
        })
    
    return sprites


def render_sprites(sprites, palette, tile_data, screen_w, screen_h):
    """Render sprites to a framebuffer.
    
    Sprites are drawn from highest index to lowest (painter's algorithm).
    The X1-001A draws from m_spritelimit down to 0.
    
    palette: (n_colors, 3) uint8 RGB (0-31 per channel)
    tile_data: (n_tiles, 8, 8) uint8 indices
    """
    fb = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)
    
    # Draw from highest index to lowest (painter's algorithm)
    for i in range(len(sprites) - 1, -1, -1):
        spr = sprites[i]
        code = spr['code']
        x = spr['x']
        y = spr['y']
        color = spr['color']
        flipx = spr['flipx']
        flipy = spr['flipy']
        
        # Skip offscreen sprites
        if y >= screen_h or y == 0:
            continue
        if x <= -TILE_SIZE or x >= screen_w:
            continue
        
        # Get the tile
        if code >= len(tile_data):
            continue
        tile = tile_data[code]
        
        # Get palette for this sprite
        # The color field is a palette bank offset
        # In the arcade, the palette is indexed as: color_base + pixel_index
        pal_offset = color * 16  # Each palette bank is 16 colors
        
        for ty in range(TILE_SIZE):
            for tx in range(TILE_SIZE):
                # Apply flip
                src_x = (TILE_SIZE - 1 - tx) if flipx else tx
                src_y = (TILE_SIZE - 1 - ty) if flipy else ty
                
                px = x + tx
                py = y + ty
                
                if 0 <= px < screen_w and 0 <= py < screen_h:
                    idx = int(tile[src_y, src_x])
                    if idx != 0:  # transparent
                        # Map pixel index through palette
                        pal_idx = pal_offset + idx
                        if pal_idx < len(palette):
                            fb[py, px] = palette[pal_idx]
    
    return fb


def scale_to_8bit(fb5):
    """Convert 5-bit framebuffer to 8-bit for PNG output."""
    return (fb5.astype(np.uint16) * 8).astype(np.uint8)


def main():
    print("Reading data files...")
    
    # Read arcade data
    with open(SPRITE_RAM_FILE, "rb") as f:
        sprite_ram = f.read()
    with open(SPRITE_Y_FILE, "rb") as f:
        sprite_y = f.read()
    arcade_palette = read_arcade_palette(PALETTE_FILE)
    
    # Read SNES data
    cgram = read_snes_cgram(SNES_CGRAM_FILE)
    snes_tiles = read_snes_tiles(SNES_TILES_FILE)
    with open(SNES_ASSIGN_FILE, "rb") as f:
        assignments = f.read()
    
    # Read original tiles for arcade rendering
    orig_tiles = read_snes_tiles(ORIG_TILES_FILE)
    
    print(f"Sprite RAM: {len(sprite_ram)} bytes ({len(sprite_ram)//2} words)")
    print(f"Arcade palette: {len(arcade_palette)} entries")
    print(f"SNES CGRAM: {cgram.shape}")
    print(f"SNES tiles: {snes_tiles.shape}")
    print(f"Original tiles: {orig_tiles.shape}")
    
    # Decode sprite RAM
    print("Decoding sprite RAM...")
    sprites = decode_sprite_ram(sprite_ram, sprite_y)
    print(f"  {len(sprites)} sprites decoded")
    
    # Count non-offscreen sprites
    visible = sum(1 for s in sprites if 0 < s['y'] < SCREEN_H and -TILE_SIZE < s['x'] < SCREEN_W)
    print(f"  {visible} visible sprites")
    
    # Render arcade frame
    print("Rendering arcade frame...")
    arcade_fb = render_sprites(sprites, arcade_palette, orig_tiles, SCREEN_W, SCREEN_H)
    
    # Render SNES frame
    print("Rendering SNES frame...")
    # For SNES, we need to map arcade palette indices to SNES palette slots
    # The arcade color field (0-31) maps to a palette bank
    # The SNES uses 8 palettes of 16 colors each
    # Our optimized palette has already done this mapping
    
    # For the SNES render, we use the remapped tiles + CGRAM
    # But we need to map the arcade sprite color field to the SNES palette
    # The assignments file tells us which SNES palette each tile uses
    
    # Actually, for a proper comparison, we should render using the same
    # sprite positions but with our optimized palette
    snes_fb = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    
    for i in range(len(sprites) - 1, -1, -1):
        spr = sprites[i]
        code = spr['code']
        x = spr['x']
        y = spr['y']
        flipx = spr['flipx']
        flipy = spr['flipy']
        
        if y >= SCREEN_H or y == 0:
            continue
        if x <= -TILE_SIZE or x >= SCREEN_W:
            continue
        
        # Use remapped SNES tiles
        if code >= len(snes_tiles):
            continue
        tile = snes_tiles[code]
        
        # Get SNES palette for this tile
        if code < len(assignments):
            pal_id = int(assignments[code])
        else:
            pal_id = 0
        
        for ty in range(TILE_SIZE):
            for tx in range(TILE_SIZE):
                src_x = (TILE_SIZE - 1 - tx) if flipx else tx
                src_y = (TILE_SIZE - 1 - ty) if flipy else ty
                
                px = x + tx
                py = y + ty
                
                if 0 <= px < SCREEN_W and 0 <= py < SCREEN_H:
                    idx = int(tile[src_y, src_x])
                    if idx != 0:
                        if pal_id < 8 and idx < 16:
                            snes_fb[py, px] = cgram[pal_id, idx]
    
    # Save comparison
    from PIL import Image
    
    arcade_img = Image.fromarray(scale_to_8bit(arcade_fb))
    arcade_img.save("comparison_arcade.png")
    print("Saved: comparison_arcade.png")
    
    snes_img = Image.fromarray(scale_to_8bit(snes_fb))
    snes_img.save("comparison_snes.png")
    print("Saved: comparison_snes.png")
    
    # Side by side
    h = max(arcade_img.height, snes_img.height)
    w = arcade_img.width + snes_img.width + 10
    combined = Image.new("RGB", (w, h), (0, 0, 0))
    combined.paste(arcade_img, (0, 0))
    combined.paste(snes_img, (arcade_img.width + 10, 0))
    combined.save("comparison_sidebyside.png")
    print("Saved: comparison_sidebyside.png")
    
    # Stats
    arcade_nonblack = np.sum(np.any(arcade_fb > 0, axis=2))
    snes_nonblack = np.sum(np.any(snes_fb > 0, axis=2))
    total = SCREEN_H * SCREEN_W
    print(f"\nArcade: {arcade_nonblack}/{total} non-black pixels ({100*arcade_nonblack/total:.1f}%)")
    print(f"SNES:   {snes_nonblack}/{total} non-black pixels ({100*snes_nonblack/total:.1f}%)")
    print(f"Arcade unique colors: {len(np.unique(arcade_fb.reshape(-1, 3), axis=0))}")
    print(f"SNES unique colors:   {len(np.unique(snes_fb.reshape(-1, 3), axis=0))}")
    
    print("Done!")


if __name__ == "__main__":
    main()
