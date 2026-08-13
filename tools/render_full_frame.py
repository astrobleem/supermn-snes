#!/usr/bin/env python3
"""
Full-frame arcade renderer: backdrop + background (X1-001 type0) + foreground
(type1). Validates the background tilemap decode against MAME for one frame.
Inputs (tools/mame-trace/, all via read_u16):
  gfx1.bin, c_spritecode_full.bin, c_spriteylow.bin, c_spritectrl.bin, c_palette.bin
"""
import argparse
import struct
from pathlib import Path
import numpy as np

MT = Path("tools/mame-trace")
W_, H_ = 384, 240
XOFF = [x if x < 8 else 256 + (x - 8) for x in range(16)]
YOFF = [y * 32 if y < 8 else 512 + (y - 8) * 32 for y in range(16)]
PLANE = [0, 8, 16, 24]


def decode_16x16(gfx, code):
    out = np.zeros((16, 16), np.uint8)
    base = code * 1024
    for y in range(16):
        yb = base + YOFF[y]
        for x in range(16):
            b = yb + XOFF[x]
            v = 0
            for p in range(4):
                bit = b + PLANE[p]
                v |= ((gfx[bit >> 3] >> (7 - (bit & 7))) & 1) << (3 - p)
            out[y, x] = v
    return out


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=MT)
    parser.add_argument(
        "--gfx",
        type=Path,
        default=MT / "gfx1.bin",
        help="authenticated private X1 graphics region",
    )
    parser.add_argument("--output", type=Path, default=Path("render_full_arcade.png"))
    parser.add_argument(
        "--mame",
        type=Path,
        help="optional exact 384x240 MAME screenshot for the historical comparison",
    )
    parser.add_argument(
        "--compare-output",
        type=Path,
        default=Path("render_full_compare.png"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    source = args.input_dir
    gfx = np.frombuffer(args.gfx.read_bytes(), np.uint8)
    sc = struct.unpack("<8192H", (source / "c_spritecode_full.bin").read_bytes())
    yl = (source / "c_spriteylow.bin").read_bytes()
    ctrl = struct.unpack("<4H", (source / "c_spritectrl.bin").read_bytes())
    palw = struct.unpack("<2048H", (source / "c_palette.bin").read_bytes())

    def prgb(idx):
        Wd = palw[idx]
        r = (Wd >> 10) & 0x1F; g = (Wd >> 5) & 0x1F; b = Wd & 0x1F
        return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))

    fb = np.zeros((H_, W_, 3), np.uint8)
    fb[:, :] = prgb(0x1F0)                         # backdrop = bitmap.fill(0x1f0)

    c0, c2, c3 = ctrl[0], ctrl[1], ctrl[3]
    flip = (c0 >> 6) & 1
    numcol = c2 & 0x0F
    if numcol == 1:
        numcol = 16
    bank = 0x1000 if ((c2 ^ ((~c2) << 1)) & 0x40) else 0
    startcol = (0x4 if c0 & 1 else 0) + (0x8 if c0 & 2 else 0)
    upper = ctrl[2] + ctrl[3] * 256
    BG_X, BG_Y = 0, -1                             # set_bg_yoffsets noflip = -1

    tilecache = {}
    def tile(code):
        if code not in tilecache:
            tilecache[code] = decode_16x16(gfx, code)
        return tilecache[code]

    def blit(code, color, fx, fy, sx, sy):
        t = tile(code)
        base = color * 16
        for ty in range(16):
            for tx in range(16):
                idx = int(t[15 - ty if fy else ty, 15 - tx if fx else tx])
                if idx == 0:
                    continue
                for X, Y in (((sx & 0x1FF) + tx, (sy & 0xFF) + ty),
                             ((sx & 0x1FF) - 512 + tx, (sy & 0xFF) + ty),
                             ((sx & 0x1FF) + tx, (sy & 0xFF) - 256 + ty)):
                    if 0 <= X < W_ and 0 <= Y < H_:
                        fb[Y, X] = prgb(base + idx)

    # ---- background (type0) ----
    for col in range(numcol):
        scrollx = yl[0x200 + col * 0x10 + 4]
        scrolly = yl[0x200 + col * 0x10]
        for offs in range(0x20):
            i = ((col + startcol) & 0xF) * 32 + offs
            code = sc[i + 0x400 + bank]
            color = sc[i + 0x600 + bank]
            fx = code & 0x8000; fy = code & 0x4000
            sx = scrollx + BG_X + (offs & 1) * 16
            sy = -(scrolly + BG_Y) + (offs // 2) * 16
            if upper & (1 << col):
                sx -= 256
            blit(code & 0x3FFF, (color >> 11) & 0x1F, fx, fy, sx, sy)

    # ---- foreground (type1) on top ----
    yb_fg = yl  # m_spriteylow[i] for i<0x200
    fg = []
    for i in range(0x200):
        cw = sc[i]; xv = sc[0x200 + i]
        if cw == 0xFFFF or (cw & 0x3FFF) == 0:
            continue
        sx = (xv & 0xFF) - (xv & 0x100); sy = yb_fg[i]
        if not (0 < sy < 240 and -16 < sx < 384):
            continue
        fg.append((i, cw, xv, sx, sy))
    for i, cw, xv, sx, sy in sorted(fg, key=lambda t: -t[0]):
        py = H_ - ((sy + 0x0e) & 0xFF)
        blit(cw & 0x3FFF, (xv >> 11) & 0x1F, cw & 0x8000, cw & 0x4000, sx, py)

    from PIL import Image
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(fb).save(args.output)
    if args.mame is None:
        print(f"wrote {args.output}")
        return
    mame = Image.open(args.mame).convert("RGB")
    combo = Image.new("RGB", (W_ * 2 + 8, H_), (40, 40, 40))
    combo.paste(mame, (0, 0)); combo.paste(Image.fromarray(fb), (W_ + 8, 0))
    args.compare_output.parent.mkdir(parents=True, exist_ok=True)
    combo.save(args.compare_output)
    # color membership
    mc = set(map(tuple, np.unique(np.array(mame).reshape(-1, 3), axis=0)))
    mine = np.unique(fb.reshape(-1, 3), axis=0)
    present = sum(1 for c in map(tuple, mine.tolist()) if c in mc)
    print(f"full-frame: {len(mine)} colors, {present}/{len(mine)} present in MAME")
    # exact pixel match
    m = np.array(mame).astype(int)
    diff = np.abs(fb.astype(int) - m).max(axis=2)
    print(f"exact pixel match to MAME: {100*(diff<=4).mean():.1f}%")
    print(f"wrote {args.compare_output}")


if __name__ == "__main__":
    main()
