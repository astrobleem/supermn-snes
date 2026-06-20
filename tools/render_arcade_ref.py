#!/usr/bin/env python3
"""Pure-Python (no numpy/PIL) arcade full-frame decode from the captured c_*.bin,
ported from render_full_frame.py (which matched MAME 47/47 colors). Writes a PNG so
the interp's render can be compared to an independent renderer of the same data."""
import struct, zlib
MT = "tools/mame-trace"
W_, H_ = 384, 240
XOFF = [x if x < 8 else 256+(x-8) for x in range(16)]
YOFF = [y*32 if y < 8 else 512+(y-8)*32 for y in range(16)]
PLANE = [0, 8, 16, 24]
gfx = open(f"{MT}/gfx1.bin", "rb").read()
sc = struct.unpack("<8192H", open(f"{MT}/c_spritecode_full.bin", "rb").read())
yl = open(f"{MT}/c_spriteylow.bin", "rb").read()
ctrl = struct.unpack("<4H", open(f"{MT}/c_spritectrl.bin", "rb").read())
palw = struct.unpack("<2048H", open(f"{MT}/c_palette.bin", "rb").read())

def prgb(idx):
    W = palw[idx]; r=(W>>10)&0x1F; g=(W>>5)&0x1F; b=W&0x1F
    return ((r<<3)|(r>>2), (g<<3)|(g>>2), (b<<3)|(b>>2))

tcache = {}
def tile(code):
    if code not in tcache:
        out = [[0]*16 for _ in range(16)]; base = code*1024
        for y in range(16):
            yb = base+YOFF[y]
            for x in range(16):
                bb = yb+XOFF[x]; v = 0
                for p in range(4):
                    bit = bb+PLANE[p]; v |= ((gfx[bit>>3]>>(7-(bit&7)))&1)<<(3-p)
                out[y][x] = v
        tcache[code] = out
    return tcache[code]

fb = bytearray(W_*H_*3)
bd = prgb(0x1F0)
for i in range(W_*H_): fb[i*3:i*3+3] = bytes(bd)

def px(X, Y, rgb):
    if 0 <= X < W_ and 0 <= Y < H_:
        o = (Y*W_+X)*3; fb[o:o+3] = bytes(rgb)

def blit(code, color, fx, fy, sx, sy):
    t = tile(code); base = color*16
    for ty in range(16):
        for tx in range(16):
            idx = t[15-ty if fy else ty][15-tx if fx else tx]
            if idx == 0: continue
            rgb = prgb(base+idx)
            px((sx&0x1FF)+tx, (sy&0xFF)+ty, rgb)
            px((sx&0x1FF)-512+tx, (sy&0xFF)+ty, rgb)
            px((sx&0x1FF)+tx, (sy&0xFF)-256+ty, rgb)

c0,c2,c3 = ctrl[0],ctrl[1],ctrl[3]
numcol = c2 & 0x0F
if numcol == 1: numcol = 16
bank = 0x1000 if ((c2 ^ ((~c2)<<1)) & 0x40) else 0
startcol = (0x4 if c0&1 else 0) + (0x8 if c0&2 else 0)
upper = ctrl[2] + ctrl[3]*256
for col in range(numcol):
    scrollx = yl[0x200+col*0x10+4]; scrolly = yl[0x200+col*0x10]
    for offs in range(0x20):
        i = ((col+startcol)&0xF)*32+offs
        code = sc[i+0x400+bank]; color = sc[i+0x600+bank]
        sx = scrollx + (offs&1)*16; sy = -(scrolly-1) + (offs//2)*16
        if upper & (1<<col): sx -= 256
        blit(code&0x3FFF, (color>>11)&0x1F, code&0x8000, code&0x4000, sx, sy)
fg = []
for i in range(0x200):
    cw = sc[i]; xv = sc[0x200+i]
    if cw == 0xFFFF or (cw&0x3FFF) == 0: continue
    sx = (xv&0xFF)-(xv&0x100); sy = yl[i]
    if not (0 < sy < 240 and -16 < sx < 384): continue
    fg.append((i,cw,xv,sx,sy))
for i,cw,xv,sx,sy in sorted(fg, key=lambda t:-t[0]):
    py = H_-((sy+0x0e)&0xFF)
    blit(cw&0x3FFF, (xv>>11)&0x1F, cw&0x8000, cw&0x4000, sx, py)

def write_png(path, w, h, rgb):
    def chunk(t,d): c=t+d; return struct.pack(">I",len(d))+c+struct.pack(">I",zlib.crc32(c)&0xFFFFFFFF)
    raw=bytearray()
    for y in range(h): raw.append(0); raw += rgb[y*w*3:(y+1)*w*3]
    open(path,"wb").write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack(">IIBBBBB",w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b''))
write_png("/tmp/arcade_ref.png", W_, H_, fb)
print("wrote /tmp/arcade_ref.png", W_, "x", H_, "; distinct colors:", len({tuple(fb[i*3:i*3+3]) for i in range(W_*H_)}))
