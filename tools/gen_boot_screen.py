#!/usr/bin/env python3
"""Generate the original, ROM-safe Mode 7 boot-indicator assets.

The asset contains no arcade ROM material.  It uses a downsampled, indexed
derivative of the user-supplied SA-1 logo, an 8x8 status font/OAM image, and a
small non-moving activity light.  The ROM packer imports :func:`build_asset`
directly; the command-line form is useful for byte auditing.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import zlib
from pathlib import Path


ASSET_SIZE = 0x8000
MAP_OFFSET = 0x0000
MAP_SIZE = 0x4000
MODE7_TILES_OFFSET = 0x4000
MODE7_TILES_SIZE = 0x2800
OBJ_TILES_OFFSET = 0x6800
OBJ_TILES_SIZE = 0x1000
OAM_OFFSET = 0x7800
OAM_SIZE = 0x0220
PALETTE_OFFSET = 0x7C00
PALETTE_SIZE = 0x0200
MATRIX_OFFSET = 0x7E00
MATRIX_SIZE = 0x0200

LOGO_WIDTH = 120
LOGO_HEIGHT = 80
LOGO_MAP_X = 8
LOGO_MAP_Y = 9
LOGO_COLORS = 92
LOGO_PALETTE_BYTES = LOGO_COLORS * 3
LOGO_RAW_SHA256 = "c85b266b610ff7dd08ad860369d17170c891ead78f37aff4322836a5ad7c2d09"
LOGO_SOURCE_SHA256 = "091e5831c949a8c686e35ff8ba1e77fccd4bbbf0b6ed173c821bd9494516b3c6"

# 120x80, 92-color indexed derivative of /home/chad/data/sa1-logo.png.
# Embedding the small derived pixels keeps builds reproducible without
# redistributing the 1536x1024 source artwork.
LOGO_DATA_B85 = (
    "c-rk*Uu@gP89z&rsMxY3N~TDPB1K7*Et6#|*|9A}k~7D&!$^uHD|YOpc_`M0CRkAn=$hnVZyQ>)7&;VKJFF;B3<%Nz!_Z*`)&bkPVMDX0VZdHG>|wxOTVUH$_qy-yNd0kS*$!fC1N^}>kKcFq{l0%Z-klIag0^_>%1g6Xz9BvT`^eP?Y~#J)<sZbaJrtgM6rH~%KKE;%xXj=B#ToMsvwT0;d~jx*^JVI1_3erFPiAIjZr{HB=6B!v@TVXB;nAbr-Mx4;bouh-S6_SW{=NHNW$ojifBf$+zx>N*pWS)s-uK^m=ZnujXA^obCjIN5|7dh>EiElQ{NRIJ`FcDaudZ$GJ^%6<Hs=Xt{{FYWe)C)3nLbxxXPfUn_*p8Idh6XEwO)ALT(bWBr$07tym;sC>+@x6vh&d=zx|Xow}17UPp3*R1XthS?KjoEAN#L<7^r^xcc1)ncIypP{oc#3KG=Nm?fI`h44(g*uzHWJ-2LHuZ_8t2jet+}c)mV4c{dVyB@}uk9Dd(-_KUM&bV{dmN~d&6|NAuN@tzoY#tww_p7HsIl8^oYktg3kH~i=uGGdUJz*+ABu;UZKlMH6??D%lOWawnG7>*2OvlG#i#f?o3$DKS7my7d)2qf?c$>k+w1xS`<MNSSIgXJ=JB;3?+)TEm3QN{sbGd*5*h@~19<fe~;J24zrNe@tFhH$g#yu-++XZH`$wLB3R=*e;8E}nyve+F~ST%RfD`um$nS#$++N5h5uvV~%oSRiE1Qxyw^go972K<*F0`F=HGkDtR+1=hkA3+(8+VhLK0kb^eA=(d&$(07@-OLIJsMZM1+l|?S_DBPj%kw8_HSmab!87t#Sc15i}<8C$Na=GF4HZsn^La@*y7V?<K6#}Nu&Jn_sj!w%aVNiIsPs{Sy*mRuMT>b*}7Ap#l@b?VKZ$ByvVarpDOv3F37skt{#X^OM)cu+?iYvNdE@EBBi!=C}!_c5e)dzBzPge`M?%QH=4s~lipRS=}#5omo3HwXxiojyGHPg*GahG-Qd4!}&K8Go-;d#b+wO5F@#R66qEgqKNE^2|)Gt$+xldgO^M<%NzP5B(ylz03}x+Of@3v;FDrWe$uipQ*HphU(+rf;N3-3>zRItDoP4W$ioDMQ)vW8Z~~2jdoF(P%W~`s+%RybBB%j+e76DK9cjQYf5imWBgo<y_C*R5VsN0<HthB2LLF*{l*rT*Xo5fmA{R9x9nkj<g_;(#i!wD`TwVdp=#6?xi<+DDKct!dGxea~LDDipa}J@SI!j{Ggf&EkunyW}H*KVph|nNNYu0!Wd*JNJ83!g~t5!;J1i|gH#xuG;mo(j~Zv3T`ory=bpjyF=>`r$8qx7P~6I(V>0cTneL`H6?Ni#)b&OpO;yk7#NAxF5_1j6PLEBiw0UU|SEOA_?6KB4Y&7adnT1qRhiOP*7AhBIC(l9pzF@BLc$lF_)%_GXaW0O=Erwz-3{BF@<w<@C;bN+#I48C>@P;GP7<jg?6iIfwpWXtg=2$3roONBY?;}3H<VoSFh`77hoeuNqh5cc6U*u!OIn|9a;puT%E0r|4R$UE3sC1pYrswe#Xs%pX!8EY{U{@%2%)#wO`jB}N;!MI^VA%nSS@sDQ%&hYsL7+#)`M<kvA6r~pTwRR8KSHt9@o{_&rL{Hu?{R(%h>ms}tJ8<zt}&LySnKP74L{?LM0|lrB(O1sDX?+z;^gE-O5OWpmw9<=Vq$6v8o2AmhR+v?`2B%^pTXphj>es~!nSRP1yQ|HZ&-}o%v^1h1RDl6npZ5p*ld8h2y->lWFk}0C{;EaOF{$lHZO_dr2qq4&dtgd(SR|G1$xA$ZP~V!8jTx-KDO-@=UVMBIBu6ROZFw+2HzWM$==MA8Gwjvh+>H$1_<*dMqB`6e2gHp%0@lnk2IR1cdKmyY`s!jGt@A~jUI*z{)WryLbDE?t+rtZWwqP@+t&r7xun){%$O2iGb~6#q%If+$gz{_Lao8rAY>XPwb`_=)n(Odm-wUO*5ujh8gX3n$UN@_3!phyl^1Xj8g;E&<1L)FI`5HX-V3cpo%c2%wt#2J+3M^T-0hkiYHM@$k#YHjc6|%yx!i%+$<VaIS39jRpT)L^dDweub!<#c3)Kv4jAfTQ^*Ue0%zCG~UdL8L$9k>f!ObJ#ws}qKcx~c%sNTtvQd_`H54LKq(++uvy6}P$@^-K>VcW~|ngT(x?5YN>FtFO1rtwv5s?8iSKL<&mT3fA_jWe_bu5RIwSr**vEzGpqEt|2ns2r3MIlzUtT45rG!L2YE(`s!|7SlRxeh!`p6`t&zVHjQ8-r3%MYV+jv-MzhCxc10>clXBL-i^H*_(q=L2@9dUjcz{s>>lY)J3=Qc#(kkTekOWg0J&Wsje8AfXNUZE8arK19{~fQn>R`SZigM(CJ!!ir#tj%#ThW4@;Q<Y+b@${hLw!YB1zY2gPhW^CSvjCOs9K8PUnybmjpv3)0EIM0x2+{fu(riU?NkJ%p;s5DTXMS0w*9{6lA2Ruv<_Cg}@lPff5=%SyIS3mYj(r%}63mRgsdAlWZkvptvA%k^t}m4Ale?B@~5ho@0@bxN4F^Nj|Becs83w1`LTSadKpk)Z#Ld<AA3)>n{zlD!8ngN$6-udJZIDoCNkkM}Wf;UFB(<eM50)99&)0Q8pfrBUv>}q#7KOMS%n=tBRl>qNh1~a3za4QARr6^$LQD;%WtV0H47yEva#w24+ebeKamPj@5NVL7J}V1cAe=V@;t31D8W!f+RSng<29NV7m!M>Lv&gpUs#Y;9&tvl7csNrnAD1`G?~Mg7j1nlq-geB%VCUtR(AnFUxa0G6f#8uhD}?-b4vVV#3g1;hBI40TgFI!g;V+Gl*mvIipdG8HG!ij@{!=R@z?%(jZfk`g(Uqbg#a3Xmm90$*m`?;e7uI{}|jpK>zB+wV4y7cHp32HpczFfJ?pBQy~0{h;M!Iz(`2lqq<_T*mp9EpY}f%T+X0?h#uz@iUsNPcd}DDrBgbk{{#9DhWJRB"
)

STATUS_LINES = (
    ("SUPERMAN ROM LOADED", 32),
    ("SA-1 68000 CORE ACTIVE", 48),
    ("ARCADE BOOT IN PROGRESS", 192),
)


# Five pixels wide, seven high.  Only project-authored boot text uses this
# compact font; game graphics still come from the user's private arcade input.
GLYPHS: dict[str, tuple[int, ...]] = {
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0F, 0x10, 0x10, 0x10, 0x10, 0x10, 0x0F),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "G": (0x0F, 0x10, 0x10, 0x13, 0x11, 0x11, 0x0F),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snes_color(red: int, green: int, blue: int) -> bytes:
    value = ((blue >> 3) << 10) | ((green >> 3) << 5) | (red >> 3)
    return value.to_bytes(2, "little")


def logo_data() -> tuple[bytes, bytes]:
    raw = zlib.decompress(base64.b85decode(LOGO_DATA_B85))
    assert sha256(raw) == LOGO_RAW_SHA256
    assert len(raw) == LOGO_PALETTE_BYTES + LOGO_WIDTH * LOGO_HEIGHT
    palette = raw[:LOGO_PALETTE_BYTES]
    pixels = raw[LOGO_PALETTE_BYTES:]
    assert max(pixels) < 128  # OBJ status colors live at CGRAM 128+
    return palette, pixels


def mode7_sections() -> tuple[bytes, bytes, bytes]:
    tilemap = bytearray(MAP_SIZE)
    tile_data = bytearray(MODE7_TILES_SIZE)
    palette, pixels = logo_data()
    tile_index = 1  # tile zero is the transparent/backdrop field
    for tile_y in range(LOGO_HEIGHT // 8):
        for tile_x in range(LOGO_WIDTH // 8):
            tile = bytes(
                pixels[
                    (tile_y * 8 + row) * LOGO_WIDTH
                    + tile_x * 8
                    + col
                ]
                for row in range(8)
                for col in range(8)
            )
            start = tile_index * 64
            tile_data[start : start + 64] = tile
            map_x = LOGO_MAP_X + tile_x
            map_y = LOGO_MAP_Y + tile_y
            tilemap[map_y * 128 + map_x] = tile_index
            tile_index += 1
    assert tile_index == 151
    return bytes(tilemap), bytes(tile_data), palette


def font_tile(char: str) -> bytes:
    pixels = [[0 for _ in range(8)] for _ in range(8)]
    rows = GLYPHS[char]
    # One-pixel navy shadow, then the white 5x7 face.
    for row, bits in enumerate(rows):
        for col in range(5):
            if bits & (1 << (4 - col)):
                if col + 2 < 8 and row + 1 < 8:
                    pixels[row + 1][col + 2] = 2
                pixels[row][col + 1] = 1

    planar = bytearray(32)
    for row in range(8):
        p0 = p1 = p2 = p3 = 0
        for col, value in enumerate(pixels[row]):
            bit = 1 << (7 - col)
            if value & 1:
                p0 |= bit
            if value & 2:
                p1 |= bit
            if value & 4:
                p2 |= bit
            if value & 8:
                p3 |= bit
        planar[row * 2] = p0
        planar[row * 2 + 1] = p1
        planar[16 + row * 2] = p2
        planar[16 + row * 2 + 1] = p3
    return bytes(planar)


def heartbeat_tile() -> bytes:
    """A tiny amber diamond; NMI pulses only its palette color."""
    pixels = (
        (0, 0, 0, 3, 3, 0, 0, 0),
        (0, 0, 3, 3, 3, 3, 0, 0),
        (0, 3, 3, 3, 3, 3, 3, 0),
        (3, 3, 3, 3, 3, 3, 3, 3),
        (3, 3, 3, 3, 3, 3, 3, 3),
        (0, 3, 3, 3, 3, 3, 3, 0),
        (0, 0, 3, 3, 3, 3, 0, 0),
        (0, 0, 0, 3, 3, 0, 0, 0),
    )
    planar = bytearray(32)
    for row in range(8):
        for col, value in enumerate(pixels[row]):
            bit = 1 << (7 - col)
            if value & 1:
                planar[row * 2] |= bit
            if value & 2:
                planar[row * 2 + 1] |= bit
    return bytes(planar)


def obj_sections() -> tuple[bytes, bytes, dict[str, int], int, int]:
    characters = sorted({char for text, _y in STATUS_LINES for char in text if char != " "})
    missing = sorted(set(characters) - GLYPHS.keys())
    if missing:
        raise AssertionError(f"missing boot font glyphs: {missing}")
    tile_for_char = {char: index for index, char in enumerate(characters)}

    tiles = bytearray(OBJ_TILES_SIZE)
    for char, index in tile_for_char.items():
        tile = font_tile(char)
        tiles[index * 32 : index * 32 + 32] = tile
    heartbeat_tile_index = len(tile_for_char)
    tiles[
        heartbeat_tile_index * 32 : heartbeat_tile_index * 32 + 32
    ] = heartbeat_tile()

    low_oam = bytearray(512)
    for sprite in range(128):
        low_oam[sprite * 4 + 1] = 0xF0
        low_oam[sprite * 4 + 3] = 0x30
    sprite = 0
    for text, y in STATUS_LINES:
        x0 = (256 - len(text) * 8) // 2
        for index, char in enumerate(text):
            if char == " ":
                continue
            if sprite >= 128:
                raise AssertionError("boot status text exceeds SNES OAM")
            offset = sprite * 4
            low_oam[offset] = x0 + index * 8
            low_oam[offset + 1] = y
            low_oam[offset + 2] = tile_for_char[char]
            low_oam[offset + 3] = 0x30  # OBJ palette 0, priority 3, no flips
            sprite += 1
    activity_sprite = sprite
    offset = activity_sprite * 4
    low_oam[offset] = 228
    low_oam[offset + 1] = 192
    low_oam[offset + 2] = heartbeat_tile_index
    low_oam[offset + 3] = 0x30
    sprite += 1
    high_oam = bytes(32)  # all X<256 and all sprites use the 8x8 small size
    return (
        bytes(tiles),
        bytes(low_oam) + high_oam,
        tile_for_char,
        sprite,
        activity_sprite,
    )


def palette_section(logo_palette: bytes) -> bytes:
    colors = bytearray(PALETTE_SIZE)
    for index in range(LOGO_COLORS):
        start = index * 3
        colors[index * 2 : index * 2 + 2] = snes_color(
            logo_palette[start],
            logo_palette[start + 1],
            logo_palette[start + 2],
        )
    obj_colors = {
        128: (0, 0, 0),
        129: (248, 248, 255),
        130: (5, 16, 48),
        131: (250, 190, 42),
    }
    for index, rgb in obj_colors.items():
        colors[index * 2 : index * 2 + 2] = snes_color(*rgb)
    return bytes(colors)


def matrix_section() -> bytes:
    # Retain the historical table-shaped asset seam, but every entry is the
    # same static 0.75-scale identity matrix.  The logo never rotates.
    matrix = b"".join(
        value.to_bytes(2, "little") for value in (0x00C0, 0, 0, 0x00C0)
    )
    table = matrix * 64
    assert len(table) == MATRIX_SIZE
    return bytes(table)


def build_asset() -> tuple[bytes, dict[str, object]]:
    tilemap, mode7_tiles, logo_palette = mode7_sections()
    (
        obj_tiles,
        oam,
        tile_for_char,
        visible_sprites,
        activity_sprite,
    ) = obj_sections()
    palette = palette_section(logo_palette)
    matrices = matrix_section()

    asset = bytearray(ASSET_SIZE)
    asset[MAP_OFFSET : MAP_OFFSET + MAP_SIZE] = tilemap
    asset[
        MODE7_TILES_OFFSET : MODE7_TILES_OFFSET + MODE7_TILES_SIZE
    ] = mode7_tiles
    asset[OBJ_TILES_OFFSET : OBJ_TILES_OFFSET + OBJ_TILES_SIZE] = obj_tiles
    asset[OAM_OFFSET : OAM_OFFSET + OAM_SIZE] = oam
    asset[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette
    asset[MATRIX_OFFSET : MATRIX_OFFSET + MATRIX_SIZE] = matrices

    report: dict[str, object] = {
        "asset_size": len(asset),
        "sha256": sha256(asset),
        "mode7_tiles": 151,
        "visible_obj_sprites": visible_sprites,
        "activity_sprite": activity_sprite,
        "activity": "static OBJ diamond with a palette-only NMI pulse",
        "logo": {
            "width": LOGO_WIDTH,
            "height": LOGO_HEIGHT,
            "colors": LOGO_COLORS,
            "raw_sha256": LOGO_RAW_SHA256,
            "source_sha256": LOGO_SOURCE_SHA256,
        },
        "font_tiles": len(tile_for_char),
        "font_map": tile_for_char,
        "status_lines": [text for text, _y in STATUS_LINES],
        "sections": {
            "tilemap_low": [MAP_OFFSET, MAP_SIZE],
            "mode7_tile_high": [MODE7_TILES_OFFSET, MODE7_TILES_SIZE],
            "obj_tiles": [OBJ_TILES_OFFSET, OBJ_TILES_SIZE],
            "oam": [OAM_OFFSET, OAM_SIZE],
            "palette": [PALETTE_OFFSET, PALETTE_SIZE],
            "matrices": [MATRIX_OFFSET, MATRIX_SIZE],
        },
    }
    return bytes(asset), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    asset, report = build_asset()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(asset)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
