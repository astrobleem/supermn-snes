#!/usr/bin/env python3
"""Pixel-validate vid_bg/vid_obj on REAL data. Builds a TESTFLAG=2 ROM (renders the
$7E shadow forever, no 68K interpreter), injects MAME's captured gameplay-frame state
(c_palette/c_spritecode_full/c_spriteylow from frame 3000) into the shadow byte-swapped
to the arcade big-endian order the store path would have written, then screenshots and
reports structure. Compare the screenshot to tools/mame-trace/snap/superman/*.png."""
import sys, os, tempfile, shutil
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession

MT = "/home/chad/supermn-snes/tools/mame-trace"
MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"

def bswap(b):  # swap each 16-bit LE word -> big-endian byte order (shadow layout)
    o = bytearray(len(b))
    for i in range(0, len(b) - 1, 2):
        o[i] = b[i+1]; o[i+1] = b[i]
    return bytes(o)

# TESTFLAG=2 ROM
base = open("/home/chad/supermn-snes/build/interp.sfc", "rb").read()
rom = bytearray(base); rom[0xF400] = 0x02; rom[0xF401] = 0x00
tf = tempfile.NamedTemporaryFile(suffix=".sfc", delete=False); tf.write(rom); tf.close()

pal = open(f"{MT}/c_palette.bin", "rb").read()            # 4096 B (2048 words, LE)
cod = open(f"{MT}/c_spritecode_full.bin", "rb").read()    # 16384 B ($E00000 region, LE)
yl  = open(f"{MT}/c_spriteylow.bin", "rb").read()         # 768 B (Y low bytes)

# sprite-Y shadow: word per sprite, Y in the odd (low) byte
ybuf = bytearray(0x400)
for i in range(min(len(yl), 0x200)):
    ybuf[2*i+1] = yl[i]

try:
    with McpSession(rom=tf.name, mesen=MESEN, port=7364, boot_wait=5.0) as m:
        m.run_frames(5)
        m.write_memory("snesWorkRam", 0x2000, bswap(pal).hex())   # SHADOW_PAL  $B0
        m.write_memory("snesWorkRam", 0x4000, bswap(cod).hex())   # SHADOW_COD  $E0 (sprite+BG)
        m.write_memory("snesWorkRam", 0x3000, bytes(ybuf).hex())  # SHADOW_D0   sprite Y
        m.write_memory("snesWorkRam", 0x10000, "01")  # go-flag $7F:0000
        m.run_frames(200) # render once (vid_bg is slow) then halt
        # structure
        on = sum(1 for n in range(128) if m.read_memory("snesSpriteRam", n*4+1, 1)[0] < 224)
        bgm = m.read_memory("snesVideoRam", 0, 0x800)
        bgnz = sum(1 for i in range(0, 0x800, 2) if bgm[i] or bgm[i+1])
        cg = m.read_memory("snesCgRam", 0, 512)
        ncol = len({cg[2*i] | (cg[2*i+1] << 8) for i in range(256)})
        print(f"on-screen OBJ sprites: {on}")
        print(f"BG tilemap nonzero entries (VRAM): {bgnz}")
        print(f"CGRAM distinct colors: {ncol}")
        shot = m.take_screenshot(format="path")
        print(f"screenshot: {shot}")
finally:
    os.remove(tf.name)
