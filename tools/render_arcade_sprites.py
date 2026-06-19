#!/usr/bin/env python3
"""
Correct arcade (Taito X / X1-001) foreground-sprite renderer.

Validates the WHOLE sprite-graphics understanding in one image:
  - 16x16 sprite tile decode from the assembled gfx1 region (exact tilelayout),
  - sprite-RAM decode (code/flip/x/color, y from spriteylow),
  - per-sprite COLOR BANK palette indexing (color field -> palette bank),
  - correct xRGB555 -> RGB color (the R/B fix).

Inputs come from a MAME dump of one frame (tools/mame-trace/):
  gfx1.bin, gp_sprite_ram.bin, gp_sprite_y.bin, gp_palette.bin
Output: render_sprites_arcade.png  (compare against the MAME snapshot).
"""
import struct
from pathlib import Path
import numpy as np

MT = Path("tools/mame-trace")
SCREEN_W, SCREEN_H = 384, 240
YOFFS = 0x0e          # set_fg_yoffsets(-0x12, 0x0e) -> noflip = 0x0e
XOFFS = 0
TRANSPEN = 0          # pixel index 0 is transparent


def load_gfx():
    return np.frombuffer(Path(MT / "gfx1.bin").read_bytes(), dtype=np.uint8)


# precompute bit positions for a 16x16 sprite (relative to sprite base, in bits)
def build_bitpos():
    # MAME tilelayout: planes STEP4(0,8); x STEP8(0,1)+STEP8(256,1);
    # y STEP8(0,32)+STEP8(512,32); 1024 bits/char
    xoff = [x if x < 8 else 256 + (x - 8) for x in range(16)]
    yoff = [y * 32 if y < 8 else 512 + (y - 8) * 32 for y in range(16)]
    plane = [0, 8, 16, 24]
    return xoff, yoff, plane


XOFF, YOFF, PLANE = build_bitpos()


def decode_sprite(gfx, code):
    """Return 16x16 array of 4bpp indices for sprite `code`."""
    base = code * 1024  # bits
    out = np.zeros((16, 16), dtype=np.uint8)
    for y in range(16):
        yb = base + YOFF[y]
        for x in range(16):
            b = yb + XOFF[x]
            val = 0
            for p in range(4):
                bit = b + PLANE[p]
                byte = gfx[bit >> 3]
                v = (byte >> (7 - (bit & 7))) & 1
                val |= v << (3 - p)   # MAME gfx convention: planeoffset[0] = MSB
            out[y, x] = val
    return out


def read_palette():
    # c_palette.bin holds logical words (read_u16) stored LE -> Python LE == W.
    d = Path(MT / "c_palette.bin").read_bytes()
    w = struct.unpack("<%dH" % (len(d) // 2), d)
    # arcade xRGB555 -> RGB888
    pal = np.zeros((len(w), 3), dtype=np.uint8)
    for i, v in enumerate(w):
        r = (v >> 10) & 0x1F
        g = (v >> 5) & 0x1F
        b = v & 0x1F
        pal[i] = [(r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)]
    return pal


def read_sprites():
    # clean read_u16 dumps: logical values, stored LE
    code = struct.unpack("<512H", Path(MT / "c_sprite_code.bin").read_bytes())
    xw_ = struct.unpack("<512H", Path(MT / "c_sprite_x.bin").read_bytes())
    y = Path(MT / "c_sprite_y.bin").read_bytes()
    sprites = []
    for i in range(0x200):
        code_w = code[i]
        x_w = xw_[i]
        if code_w == 0xFFFF or (code_w & 0x3FFF) == 0:
            continue
        sy = y[i]                           # m_spriteylow[i] & 0xff
        sx = (x_w & 0xFF) - (x_w & 0x100)
        if not (0 < sy < 240 and -16 < sx < SCREEN_W):
            continue
        sprites.append(dict(
            i=i,
            code=code_w & 0x3FFF,
            flipx=bool(code_w & 0x8000),
            flipy=bool(code_w & 0x4000),
            color=(x_w >> 11) & 0x1F,
            sx=sx, sy=sy,
        ))
    return sprites


def main():
    gfx = load_gfx()
    pal = read_palette()
    sprites = read_sprites()
    print(f"{len(sprites)} active fg sprites")
    banks = sorted(set(s["color"] for s in sprites))
    print(f"color banks present: {banks}")

    fb = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    drawn = np.zeros((SCREEN_H, SCREEN_W), dtype=bool)
    # painter's: draw from high index to low (per x1_001: i = limit..0, low index on top)
    for s in sorted(sprites, key=lambda s: -s["i"]):
        tile = decode_sprite(gfx, s["code"])
        base = s["color"] * 16
        px = (s["sx"] + XOFFS) & 0x1FF
        py = SCREEN_H - ((s["sy"] + YOFFS) & 0xFF)   # x1_001: max_y - (sy+yoffs)
        for ty in range(16):
            for tx in range(16):
                idx = int(tile[15 - ty if s["flipy"] else ty,
                              15 - tx if s["flipx"] else tx])
                if idx == TRANSPEN:
                    continue
                X = px + tx
                Y = py + ty
                if 0 <= X < SCREEN_W and 0 <= Y < SCREEN_H:
                    fb[Y, X] = pal[base + idx]
                    drawn[Y, X] = True

    from PIL import Image
    Image.fromarray(fb).save("render_sprites_arcade.png")
    print(f"wrote render_sprites_arcade.png ({drawn.sum()} px drawn)")

    # side-by-side with the MAME snapshot
    try:
        mame = Image.open(sorted((MT / "snap/superman").glob("*.png"))[-1]).convert("RGB")
        combo = Image.new("RGB", (SCREEN_W * 2 + 8, SCREEN_H), (40, 40, 40))
        combo.paste(mame, (0, 0))
        combo.paste(Image.fromarray(fb), (SCREEN_W + 8, 0))
        combo.save("render_sprites_compare.png")
        print("wrote render_sprites_compare.png (MAME | our sprite render)")
    except Exception as e:
        print("compare skipped:", e)


if __name__ == "__main__":
    main()
