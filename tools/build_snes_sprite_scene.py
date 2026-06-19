#!/usr/bin/env python3
"""
Reproduce a captured arcade frame's FOREGROUND sprites on the real SNES PPU.

Uses the now-ground-truth-validated decode (verified by render_arcade_sprites.py
matching MAME): 16x16 planar tiles (plane[0]=MSB), big-endian sprite RAM, color
field = bits 11-15, arcade xRGB555 palette. Converts to the SNES OBJ pipeline:
  - planar 16x16 -> 4 SNES 4bpp 8x8 tiles (N, N+1, N+16, N+17 layout),
  - arcade palette banks -> SNES OBJ palettes (xRGB555 -> xBGR555, no quant),
  - arcade sprites -> SNES OAM (X/Y/tile/pal/flip, 16x16 size).

Emits build/objscene.pasm (code + data) for Poppy. A separate step assembles +
wraps the ROM and screenshots it in Mesen to compare against the MAME frame.
"""
import struct
from pathlib import Path
from collections import Counter
import numpy as np

MT = Path("tools/mame-trace")
SCREEN_H = 240
YOFFS = 0x0e

# ---- arcade decode (validated) ----
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
            val = 0
            for p in range(4):
                bit = b + PLANE[p]
                val |= ((gfx[bit >> 3] >> (7 - (bit & 7))) & 1) << (3 - p)
            out[y, x] = val
    return out


def pack_snes_4bpp(tile8):
    """8x8 array of 0-15 -> 32-byte SNES 4bpp tile."""
    out = bytearray(32)
    for row in range(8):
        b0 = b1 = b2 = b3 = 0
        for col in range(8):
            v = int(tile8[row, col])
            sh = 7 - col
            b0 |= ((v >> 0) & 1) << sh
            b1 |= ((v >> 1) & 1) << sh
            b2 |= ((v >> 2) & 1) << sh
            b3 |= ((v >> 3) & 1) << sh
        out[row * 2] = b0
        out[row * 2 + 1] = b1
        out[16 + row * 2] = b2
        out[16 + row * 2 + 1] = b3
    return bytes(out)


def snes_color(W):
    """arcade xRGB555 word -> SNES xBGR555 word."""
    r = (W >> 10) & 0x1F
    g = (W >> 5) & 0x1F
    b = W & 0x1F
    return (b << 10) | (g << 5) | r


def main():
    gfx = np.frombuffer((MT / "gfx1.bin").read_bytes(), dtype=np.uint8)
    code = struct.unpack("<512H", (MT / "c_sprite_code.bin").read_bytes())
    xw = struct.unpack("<512H", (MT / "c_sprite_x.bin").read_bytes())
    yb = (MT / "c_sprite_y.bin").read_bytes()
    pal = struct.unpack("<2048H", (MT / "c_palette.bin").read_bytes())

    active = []
    for i in range(0x200):
        cw = code[i]
        xv = xw[i]
        if cw == 0xFFFF or (cw & 0x3FFF) == 0:
            continue
        sx = (xv & 0xFF) - (xv & 0x100)
        sy = yb[i]
        if not (0 < sy < 240 and -16 < sx < 384):
            continue
        active.append(dict(i=i, code=cw & 0x3FFF, flipx=bool(cw & 0x8000),
                           flipy=bool(cw & 0x4000), bank=(xv >> 11) & 0x1F,
                           sx=sx, sy=sy))

    # bank -> OBJ palette slot
    banks = sorted(set(s["bank"] for s in active))
    bank2slot = {b: i for i, b in enumerate(banks)}
    assert len(banks) <= 8, f"{len(banks)} banks > 8 OBJ palettes"

    # distinct codes -> 16x16 sprite slot (limit to fit two name tables = 128)
    codes = [c for c, _ in Counter(s["code"] for s in active).most_common()]
    MAXSLOTS = 120
    codes = codes[:MAXSLOTS]
    code2slot = {c: s for s, c in enumerate(codes)}
    dropped = [s for s in active if s["code"] not in code2slot]
    if dropped:
        print(f"NOTE: dropping {len(dropped)} sprites whose tile exceeds slot budget")
    active = [s for s in active if s["code"] in code2slot]
    print(f"{len(active)} sprites, {len(codes)} tiles, banks {banks} -> slots {bank2slot}")

    # ---- VRAM: 16-wide tile grid; sprite slot s -> base tile T = row*16+col ----
    NTILES = len(codes) * 4
    rows_needed = ((len(codes) + 7) // 8) * 2          # 8 sprites per 2 rows
    vram = bytearray(16 * rows_needed * 32)            # 16 tiles/row * 32 bytes
    for c, slot in code2slot.items():
        col = 2 * (slot % 8)
        row = 2 * (slot // 8)
        big = decode_16x16(gfx, c)
        quads = {(0, 0): big[0:8, 0:8], (1, 0): big[0:8, 8:16],
                 (0, 1): big[8:16, 0:8], (1, 1): big[8:16, 8:16]}
        for (dc, dr), q in quads.items():
            T = (row + dr) * 16 + (col + dc)
            vram[T * 32:T * 32 + 32] = pack_snes_4bpp(q)

    # ---- CGRAM: OBJ palettes in upper half (entries 128..255) ----
    cgram = bytearray(512)
    for b in banks:
        slot = bank2slot[b]
        for e in range(16):
            W = pal[b * 16 + e]
            col = 0 if e == 0 else snes_color(W)        # index0 transparent
            off = (128 + slot * 16 + e) * 2
            cgram[off] = col & 0xFF
            cgram[off + 1] = (col >> 8) & 0xFF
    # backdrop black
    cgram[0] = cgram[1] = 0

    # ---- OAM: 110 sprites ----
    oam = bytearray(512 + 32)
    for n, s in enumerate(active):
        slot = code2slot[s["code"]]
        col = 2 * (slot % 8)
        row = 2 * (slot // 8)
        T = row * 16 + col
        px = s["sx"]
        py = (SCREEN_H - ((s["sy"] + YOFFS) & 0xFF)) - 16    # match arcade anchor
        # X 9-bit: on-screen if 0..255 else push offscreen-left
        if 0 <= px < 256:
            xlow, xsign = px, 0
        else:
            v = px - 512
            xlow, xsign = v & 0xFF, 1
        attr = 0
        attr |= 0x30                                  # priority 3 (front)
        attr |= (bank2slot[s["bank"]] & 7) << 1       # palette
        attr |= (T >> 8) & 1                          # name table
        if s["flipx"]:
            attr |= 0x40
        if s["flipy"]:
            attr |= 0x80
        oam[n * 4 + 0] = xlow
        oam[n * 4 + 1] = py & 0xFF
        oam[n * 4 + 2] = T & 0xFF
        oam[n * 4 + 3] = attr
        # high table: 2 bits/sprite -> xsign(bit0) + size large(bit1)
        hi = (xsign & 1) | 0x02
        oam[512 + (n >> 2)] |= hi << ((n & 3) * 2)
    # remaining sprites: park offscreen (Y=240)
    for n in range(len(active), 128):
        oam[n * 4 + 1] = 0xF0

    # ---- emit pasm ----
    def blk(label, data):
        lines = [f"{label}:"]
        for i in range(0, len(data), 16):
            lines.append("    .byte " + ",".join("$%02X" % b for b in data[i:i+16]))
        return "\n".join(lines)

    asm = f"""; AUTO-GENERATED by tools/build_snes_sprite_scene.py
; Reproduces a captured Superman arcade frame's foreground sprites on SNES OBJ.
.snes
INIDISP=$2100
OBSEL=$2101
OAMADDL=$2102
OAMADDH=$2103
BGMODE=$2105
VMAIN=$2115
VMADDL=$2116
VMADDH=$2117
TM=$212C
CGADD=$2121
NMITIMEN=$4200
MDMAEN=$420B
DMAP0=$4300
BBAD0=$4301
A1T0L=$4302
A1T0H=$4303
A1B0=$4304
DAS0L=$4305
DAS0H=$4306

.bank 0
.org $8000
reset:
    clc
    xce
    sei
    rep #$30
    ldx #$1fff
    txs
    sep #$20
    lda #$80
    sta INIDISP
    stz NMITIMEN
    lda #$01
    sta BGMODE
    stz OBSEL              ; OBJ tiles @VRAM $0000, 8x8/16x16 size, gap=0

    ; OBJ tiles -> VRAM word $0000
    stz VMADDL
    stz VMADDH
    lda #$80
    sta VMAIN
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    lda #<vram_data
    sta A1T0L
    lda #>vram_data
    sta A1T0H
    stz A1B0
    lda #<{len(vram)}
    sta DAS0L
    lda #>{len(vram)}
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; CGRAM
    stz CGADD
    lda #$00
    sta DMAP0
    lda #$22
    sta BBAD0
    lda #<cgram_data
    sta A1T0L
    lda #>cgram_data
    sta A1T0H
    stz A1B0
    lda #<512
    sta DAS0L
    lda #>512
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; OAM
    stz OAMADDL
    stz OAMADDH
    lda #$00
    sta DMAP0
    lda #$04
    sta BBAD0
    lda #<oam_data
    sta A1T0L
    lda #>oam_data
    sta A1T0H
    stz A1B0
    lda #<544
    sta DAS0L
    lda #>544
    sta DAS0H
    lda #$01
    sta MDMAEN

    lda #$10
    sta TM                 ; enable OBJ on main screen
    lda #$0F
    sta INIDISP
loop:
    wai
    bra loop
nmi:
    rti
irq:
    rti

{blk("vram_data", vram)}

{blk("cgram_data", cgram)}

{blk("oam_data", oam)}

.org $FFE0
.word $0000,$0000,irq,irq,$0000,nmi,reset,irq
.org $FFF0
.word $0000,$0000,irq,$0000,$0000,nmi,reset,irq
"""
    Path("build").mkdir(exist_ok=True)
    Path("build/objscene.pasm").write_text(asm)
    print(f"wrote build/objscene.pasm (vram {len(vram)}B, {len(active)} sprites)")


if __name__ == "__main__":
    main()
