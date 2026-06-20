#!/usr/bin/env python3
"""Stage-3b: validate decode_tile (on-SNES tile decode) vs the Python reference
decode_16x16+pack8 for a fixed code. The interp's vid_frame currently decodes code
$0100 into $7E:8400 (TEMP test hook)."""
import sys, os
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession

GFX = open("/home/chad/supermn-snes/tools/mame-trace/gfx1.bin", "rb").read()
YOFF = [y*32 if y < 8 else 512+(y-8)*32 for y in range(16)]
XOFF = [x if x < 8 else 256+(x-8) for x in range(16)]

def decode_16x16(code):
    out = [[0]*16 for _ in range(16)]; base = code*1024
    for y in range(16):
        yb = base + YOFF[y]
        for x in range(16):
            b = yb + XOFF[x]; v = 0
            for p in range(4):
                bit = b + [0, 8, 16, 24][p]
                v |= ((GFX[bit >> 3] >> (7-(bit & 7))) & 1) << (3-p)
            out[y][x] = v
    return out

def pack8(t8):
    o = bytearray(32)
    for r in range(8):
        bb = [0, 0, 0, 0]
        for c in range(8):
            v = t8[r][c]; s = 7-c
            for p in range(4): bb[p] |= ((v >> p) & 1) << s
        o[r*2] = bb[0]; o[r*2+1] = bb[1]; o[16+r*2] = bb[2]; o[16+r*2+1] = bb[3]
    return bytes(o)

def sub(big, y0, x0): return [[big[y0+r][x0+c] for c in range(8)] for r in range(8)]

code = 0x100
big = decode_16x16(code)
exp = pack8(sub(big, 0, 0)) + pack8(sub(big, 0, 8)) + pack8(sub(big, 8, 0)) + pack8(sub(big, 8, 8))

with McpSession(rom="/home/chad/supermn-snes/build/interp.sfc",
                mesen="/home/chad/Mesen2/bin/linux-x64/Release/Mesen",
                port=7355, boot_wait=5.0) as m:
    for i in range(13): m.run_frames(200)
    tm = m.read_memory("snesWorkRam", 0x10002, 2)
    print(f"tmask=${(tm[0]<<8)|tm[1]:04X}")
    hw = bytes(m.read_memory("snesWorkRam", 0x8400, 128))
    print(f"exp[:16]={exp[:16].hex()}")
    print(f" hw[:16]={hw[:16].hex()}")
    print(f"exp[64:80]={exp[64:80].hex()}")
    print(f" hw[64:80]={hw[64:80].hex()}")
    diffs = [i for i in range(128) if exp[i] != hw[i]]
    print(f"decode_tile code=${code:04X}: {'MATCH 128/128' if not diffs else f'{len(diffs)}/128 mismatch at {diffs[:10]}'}")
