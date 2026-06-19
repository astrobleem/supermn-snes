#!/usr/bin/env python3
"""
Reproduce a full Superman arcade frame on the real SNES PPU:
  - BG1 = the X1-001 'type0' playfield (church/bricks) as a 64x32 4bpp tilemap,
  - OBJ = the 'type1' foreground sprites (Superman, enemy, text, ...).
All from one MAME-captured frame, using the ground-truth-validated decode.

Layout: code in bank 0; each big data blob in its own ROM bank ($xx:8000) so the
loader DMAs from clean fixed addresses. Run via tools/drive ephemeral Mesen.
"""
import struct
from pathlib import Path
from collections import Counter
import numpy as np

MT = Path("tools/mame-trace")
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


def pack8(t8):
    o = bytearray(32)
    for r in range(8):
        b0 = b1 = b2 = b3 = 0
        for c in range(8):
            v = int(t8[r, c]); s = 7 - c
            b0 |= ((v >> 0) & 1) << s; b1 |= ((v >> 1) & 1) << s
            b2 |= ((v >> 2) & 1) << s; b3 |= ((v >> 3) & 1) << s
        o[r*2] = b0; o[r*2+1] = b1; o[16+r*2] = b2; o[16+r*2+1] = b3
    return bytes(o)


def snes_color(W):
    r = (W >> 10) & 0x1F; g = (W >> 5) & 0x1F; b = W & 0x1F
    return (b << 10) | (g << 5) | r


def main():
    gfx = np.frombuffer((MT / "gfx1.bin").read_bytes(), np.uint8)
    sc = struct.unpack("<8192H", (MT / "c_spritecode_full.bin").read_bytes())
    yl = (MT / "c_spriteylow.bin").read_bytes()
    palw = struct.unpack("<2048H", (MT / "c_palette.bin").read_bytes())

    tcache = {}
    def quads(code):
        if code not in tcache:
            big = decode_16x16(gfx, code)
            tcache[code] = (pack8(big[0:8, 0:8]), pack8(big[0:8, 8:16]),
                            pack8(big[8:16, 0:8]), pack8(big[8:16, 8:16]))
        return tcache[code]

    # ================= BACKGROUND (BG1) =================
    # logical 32x16 grid of 16x16 tiles; gx=col*2+(offs&1), gy=offs//2
    bg_cells = {}   # (gx,gy) -> (code, color, flipx, flipy)
    bg_banks = set()
    for col in range(16):
        for offs in range(0x20):
            i = col * 32 + offs
            code = sc[i + 0x400]
            color = sc[i + 0x600]
            c = code & 0x3FFF
            if c == 0:
                continue
            gx = col * 2 + (offs & 1)
            gy = offs // 2
            bank = (color >> 11) & 0x1F
            bg_cells[(gx, gy)] = (c, bank, bool(code & 0x8000), bool(code & 0x4000))
            bg_banks.add(bank)
    bg_banks = sorted(bg_banks)
    bg_bank2pal = {b: i for i, b in enumerate(bg_banks)}     # BG palettes 0..

    bg_codes = sorted(set(v[0] for v in bg_cells.values()))
    bg_code2tile = {c: i * 4 for i, c in enumerate(bg_codes)}   # base 8x8 tile
    bg_tiles = bytearray(len(bg_codes) * 4 * 32)
    for c, t0 in bg_code2tile.items():
        q = quads(c)
        for k in range(4):
            bg_tiles[(t0 + k) * 32:(t0 + k) * 32 + 32] = q[k]

    # BG1 tilemap 64x32 (two 32x32 screens side by side)
    def map_index(tx, ty):
        # SNES 64x32: screen0 cols0-31 at 0, screen1 cols32-63 at +0x400
        sx = 0 if tx < 32 else 1
        return sx * 0x400 + ty * 32 + (tx & 31)
    bgmap = bytearray(64 * 32 * 2)
    for (gx, gy), (c, bank, fx, fy) in bg_cells.items():
        t0 = bg_code2tile[c]
        pal = bg_bank2pal[bank]
        # 4 quadrants -> 4 SNES 8x8 cells
        for (dx, dy, tk) in ((0, 0, 0), (1, 0, 1), (0, 1, 2), (1, 1, 3)):
            tx = (gx * 2 + dx) & 63
            ty = (gy * 2 + dy) & 31
            tile = t0 + tk
            ent = (tile & 0x3FF) | (pal << 10)
            if fx: ent |= 0x4000
            if fy: ent |= 0x8000
            mi = map_index(tx, ty)
            bgmap[mi * 2] = ent & 0xFF
            bgmap[mi * 2 + 1] = (ent >> 8) & 0xFF

    # ================= FOREGROUND (OBJ) =================
    active = []
    for i in range(0x200):
        cw = sc[i]; xv = sc[0x200 + i]
        if cw == 0xFFFF or (cw & 0x3FFF) == 0:
            continue
        sx = (xv & 0xFF) - (xv & 0x100); sy = yl[i]
        if not (0 < sy < 240 and -16 < sx < 384):
            continue
        active.append(dict(code=cw & 0x3FFF, fx=bool(cw & 0x8000), fy=bool(cw & 0x4000),
                           bank=(xv >> 11) & 0x1F, sx=sx, sy=sy))
    obj_banks = sorted(set(s["bank"] for s in active))
    obj_bank2pal = {b: i for i, b in enumerate(obj_banks)}
    obj_codes = [c for c, _ in Counter(s["code"] for s in active).most_common()][:120]
    obj_code2slot = {c: i for i, c in enumerate(obj_codes)}
    active = [s for s in active if s["code"] in obj_code2slot]

    rows = ((len(obj_codes) + 7) // 8) * 2
    obj_tiles = bytearray(16 * rows * 32)
    for c, slot in obj_code2slot.items():
        col = 2 * (slot % 8); row = 2 * (slot // 8)
        q = quads(c)
        for (dx, dy, tk) in ((0, 0, 0), (1, 0, 1), (0, 1, 2), (1, 1, 3)):
            T = (row + dy) * 16 + (col + dx)
            obj_tiles[T * 32:T * 32 + 32] = q[tk]

    oam = bytearray(512 + 32)
    for n, s in enumerate(active):
        slot = obj_code2slot[s["code"]]
        col = 2 * (slot % 8); row = 2 * (slot // 8)
        T = row * 16 + col
        px = s["sx"]; py = (240 - ((s["sy"] + 0x0e) & 0xFF)) - 16
        if 0 <= px < 256:
            xl, xsgn = px, 0
        else:
            xl, xsgn = (px - 512) & 0xFF, 1
        attr = 0x30 | ((obj_bank2pal[s["bank"]] & 7) << 1) | ((T >> 8) & 1)
        if s["fx"]: attr |= 0x40
        if s["fy"]: attr |= 0x80
        oam[n*4] = xl; oam[n*4+1] = py & 0xFF; oam[n*4+2] = T & 0xFF; oam[n*4+3] = attr
        oam[512 + (n >> 2)] |= ((xsgn & 1) | 0x02) << ((n & 3) * 2)
    for n in range(len(active), 128):
        oam[n*4+1] = 0xF0

    # ================= CGRAM =================
    cgram = bytearray(512)
    for b in bg_banks:                       # BG palettes 0.. at entries 0..
        pal = bg_bank2pal[b]
        for e in range(16):
            col = 0 if e == 0 else snes_color(palw[b*16 + e])
            off = (pal*16 + e) * 2
            cgram[off] = col & 0xFF; cgram[off+1] = (col >> 8) & 0xFF
    for b in obj_banks:                      # OBJ palettes at entries 128..
        pal = obj_bank2pal[b]
        for e in range(16):
            col = 0 if e == 0 else snes_color(palw[b*16 + e])
            off = (128 + pal*16 + e) * 2
            cgram[off] = col & 0xFF; cgram[off+1] = (col >> 8) & 0xFF
    # backdrop = arcade fill color 0x1f0
    bd = snes_color(palw[0x1F0]); cgram[0] = bd & 0xFF; cgram[1] = (bd >> 8) & 0xFF

    print(f"BG: {len(bg_codes)} tiles ({len(bg_tiles)}B), banks {bg_banks}->pal {list(bg_bank2pal.values())}")
    print(f"OBJ: {len(active)} sprites, {len(obj_codes)} tiles, banks {obj_banks}")

    blobs = {"bgtiles": bytes(bg_tiles), "bgmap": bytes(bgmap),
             "objtiles": bytes(obj_tiles), "cgram": bytes(cgram), "oam": bytes(oam)}
    for k, v in blobs.items():
        assert len(v) <= 0x8000, f"{k} too big for one bank: {len(v)}"
    Path("build").mkdir(exist_ok=True)
    meta = {}
    for bank, (k, v) in enumerate(blobs.items(), start=1):
        Path(f"build/blob_{k}.bin").write_bytes(v)
        meta[k] = dict(bank=bank, size=len(v))
    Path("build/fullscene_meta.json").write_text(__import__("json").dumps(meta))
    print("blobs:", {k: (m["bank"], m["size"]) for k, m in meta.items()})

    # scroll: playfield placed at screen (126, 8) -> hofs=-126, vofs=-8 (10-bit)
    hofs = (-126) & 0x3FF
    vofs = (-8) & 0x3FF
    Path("build/fullscene_scroll.txt").write_text(f"{hofs} {vofs}\n")
    emit_pasm(meta, len(bg_tiles), len(bgmap), len(obj_tiles), hofs, vofs)


def emit_pasm(meta, bgtiles_len, bgmap_len, objtiles_len, hofs, vofs):
    # DMA sources: bank N data at CPU $N:8000
    def src(k): return meta[k]["bank"], 0x8000
    bgt_bank, bgt_addr = src("bgtiles")
    bgm_bank, bgm_addr = src("bgmap")
    obt_bank, obt_addr = src("objtiles")
    cg_bank, cg_addr = src("cgram")
    oam_bank, oam_addr = src("oam")
    asm = f"""; AUTO-GENERATED by tools/build_snes_full_scene.py
.snes
INIDISP=$2100
OBSEL=$2101
OAMADDL=$2102
BGMODE=$2105
BG1SC=$2107
BG12NBA=$210B
BG1HOFS=$210D
BG1VOFS=$210E
VMAIN=$2115
VMADDL=$2116
VMADDH=$2117
CGADD=$2121
TM=$212C
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
    sta BGMODE              ; mode 1
    lda #$01
    sta BG1SC               ; BG1 map @word $0000, 64x32
    lda #$01
    sta BG12NBA             ; BG1 char base = word $1000
    stz OBSEL
    lda #$02
    sta OBSEL               ; OBJ tiles @word $4000, gap0, 8/16

    lda #$80
    sta VMAIN

    ; BG tilemap -> VRAM word $0000
    stz VMADDL
    stz VMADDH
    jsr dma_vram_setup
    lda #<{bgm_addr}
    sta A1T0L
    lda #>{bgm_addr}
    sta A1T0H
    lda #${bgm_bank:02X}
    sta A1B0
    lda #<{bgmap_len}
    sta DAS0L
    lda #>{bgmap_len}
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; BG tiles -> VRAM word $1000
    lda #$00
    sta VMADDL
    lda #$10
    sta VMADDH
    jsr dma_vram_setup
    lda #<{bgt_addr}
    sta A1T0L
    lda #>{bgt_addr}
    sta A1T0H
    lda #${bgt_bank:02X}
    sta A1B0
    lda #<{bgtiles_len}
    sta DAS0L
    lda #>{bgtiles_len}
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; OBJ tiles -> VRAM word $4000
    lda #$00
    sta VMADDL
    lda #$40
    sta VMADDH
    jsr dma_vram_setup
    lda #<{obt_addr}
    sta A1T0L
    lda #>{obt_addr}
    sta A1T0H
    lda #${obt_bank:02X}
    sta A1B0
    lda #<{objtiles_len}
    sta DAS0L
    lda #>{objtiles_len}
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; CGRAM
    stz CGADD
    lda #$00
    sta DMAP0
    lda #$22
    sta BBAD0
    lda #<{cg_addr}
    sta A1T0L
    lda #>{cg_addr}
    sta A1T0H
    lda #${cg_bank:02X}
    sta A1B0
    lda #<512
    sta DAS0L
    lda #>512
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; OAM
    stz OAMADDL
    stz OAMADDL
    lda #$00
    sta DMAP0
    lda #$04
    sta BBAD0
    lda #<{oam_addr}
    sta A1T0L
    lda #>{oam_addr}
    sta A1T0H
    lda #${oam_bank:02X}
    sta A1B0
    lda #<544
    sta DAS0L
    lda #>544
    sta DAS0H
    lda #$01
    sta MDMAEN

    ; BG1 scroll
    lda #<{hofs}
    sta BG1HOFS
    lda #>{hofs}
    sta BG1HOFS
    lda #<{vofs}
    sta BG1VOFS
    lda #>{vofs}
    sta BG1VOFS

    lda #$11
    sta TM                  ; BG1 + OBJ
    lda #$0F
    sta INIDISP
loop:
    wai
    bra loop

dma_vram_setup:
    lda #$01
    sta DMAP0
    lda #$18
    sta BBAD0
    rts

nmi:
    rti
irq:
    rti

.org $FFE0
.word $0000,$0000,irq,irq,$0000,nmi,reset,irq
.org $FFF0
.word $0000,$0000,irq,$0000,$0000,nmi,reset,irq
"""
    Path("build/fullscene.pasm").write_text(asm)
    print("wrote build/fullscene.pasm")


if __name__ == "__main__":
    main()
