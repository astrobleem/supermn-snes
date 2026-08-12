#!/usr/bin/env python3
"""
Build the full-ROM 68K-interpreter harness: a 4MB HiROM .sfc embedding the
65816 interpreter (file $8000, CPU $00/$C0:8000-FFFF) + the entire 512KB 68K
program image (file $10000, CPU $C1:0000+ — so 68K addr A reads flat at $C10000+A).
Load this in Mesen (MESEN_ROM) to let the interpreter follow cross-ROM control flow.
"""
import hashlib
from pathlib import Path

from gen_boot_screen import ASSET_SIZE as BOOT_ASSET_SIZE
from gen_boot_screen import build_asset as build_boot_asset

INTERP = Path("src/interp.bin").read_bytes()        # 32KB ($8000-$FFFF)
IMG = Path("data/superman_m68k.bin").read_bytes()   # 512KB 68K program
GFX = Path("tools/mame-trace/gfx1.bin").read_bytes() # 2MB arcade tile ROM (16x16 planar 4bpp)
assert len(INTERP) == 0x8000, len(INTERP)


def interp_symbol(name: str) -> int:
    symbols = Path("src/interp.sym").read_text(encoding="utf-8-sig")
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            bank, address = fields[0].split(":", 1)
            assert bank == "00", (name, fields[0])
            return int(address, 16)
    raise AssertionError(f"missing interpreter layout symbol {name}")


# The bank-$00 dispatch extension is packed into a formerly zero seam between
# two long-lived hot paths. Poppy permits .org overlap and short-branch drift,
# so pin every boundary that protects the $01F2E4 arm and the following $25110
# body. These addresses are also hardcoded by cross-bank code.
for _symbol, _expected in {
    "bbe_miss": 0xD28A,
    "jb2_ext": 0xD28D,
    "ors_98chk": 0xD2C6,
    "bbe_ext2": 0xD360,
    "bbe_ext2_miss": 0xD36E,
    "_25110_t1": 0xD372,
}.items():
    assert interp_symbol(_symbol) == _expected, (
        f"bank-$00 dispatch seam {_symbol} moved from ${_expected:04X}"
    )
assert INTERP[0x528A:0x528D] == bytes.fromhex("4c60d3"), (
    "bbe_miss no longer jumps to the pinned $D360 extension"
)
assert INTERP[0x5360:0x5372] == bytes.fromhex(
    "c9e4f2d009a5548540685c00c09d4c50e400"
), "the packed $01F2E4 -> $9D:C000 dispatch arm changed or overlapped $25110"

entry_ce4 = interp_symbol("entry_ce4")
entry_ce4_after_counter = interp_symbol("entry_ce4_after_counter")
assert (
    entry_ce4_after_counter == entry_ce4 + 5
), "$CE4 leaf residue return moved from its size-neutral five-byte seam"
assert INTERP[
    entry_ce4 - 0x8000:entry_ce4_after_counter - 0x8000
] == bytes.fromhex("5c00ca94ea"), (
    "$CE4 leaf no longer redirects size-neutrally to $94:CA00"
)
rdw_ea_l = interp_symbol("rdw_ea_l")
readbyte_l = interp_symbol("readbyte_l")
assert rdw_ea_l == 0xE5B2 and readbyte_l == 0xE5B6
assert INTERP[rdw_ea_l - 0x8000:readbyte_l - 0x8000] == bytes.fromhex(
    "5c00eb9f"
), "rdw_ea_l no longer redirects size-neutrally to $9F:EB00"

# $0020E8 is itself packed through the old $F400 overlap zone.  Its hot-loop
# seam replaces exactly `lda $00; sta $80` with a four-byte long jump; any
# address or byte drift can silently land on the guard-failure trampoline.
assert interp_symbol("L20e8_2108") == 0xEEC9
assert interp_symbol("h20e8_fill_resume") == 0xEECD
assert INTERP[0x6EC9:0x6ECD] == bytes.fromhex("5c03a09d"), (
    "$20E8 live-shape seam no longer targets h20e8_fast@$9D:A003"
)
assert interp_symbol("entry_20e8_return") == 0xF589
assert interp_symbol("loop_hook") == 0xF58C
assert INTERP[0x7589:0x758C] == bytes.fromhex("4c6fd1"), (
    "$20E8 return no longer uses the size-neutral bank-aware sentinel path"
)

# op_lea_pc is a fixed four-byte bank-$00 bridge. The production pacing vector
# trampolines consume the final eight bytes of the old zero seam while keeping
# op_movl_imm_d16 pinned at $9430. Catch drift or Poppy .org overlap here.
assert INTERP[0x13EA:0x13EE] == bytes.fromhex("5c00f999"), (
    "op_lea_pc bridge at $00:93EA no longer targets $99:F900"
)
assert INTERP[0x13EE:0x1428] == bytes(0x3A), (
    "op_lea_pc bridge grew across the $93EE-$9427 pinned seam"
)
assert INTERP[0x1428:0x1430] == bytes.fromhex("5c408f7f5c008f7f"), (
    "production IRQ/NMI trampolines moved or no longer target $7F:8F40/$7F:8F00"
)
assert INTERP[0x75A3:0x75A6] == bytes.fromhex("ee6007"), (
    "the real $0818 INC $0760 boundary moved from $00:F5A3"
)
assert interp_symbol("lh_0818_after_gateway") == 0xF59B
assert INTERP[0x7597:0x759D] == bytes.fromhex("5cb0fb999009"), (
    "$0818 loop hook lost its size-neutral bank-$99 fallback gateway/BCC seam"
)
lh_sched = interp_symbol("lh_sched")
lh_sched_end = interp_symbol("lh_sched_end")
assert lh_sched == 0xF9B2 and lh_sched < lh_sched_end <= 0xFA00, (
    "native scheduler scan moved or crossed the fixed $FA00 opcode seam"
)
assert INTERP[lh_sched - 0x8000:lh_sched - 0x8000 + 7] == bytes.fromhex(
    "ad3607d0021860"
), "native scheduler scan lost its zero-select-gate interpreter fallback"
assert INTERP[lh_sched_end - 0x8000:0x7A00] == bytes(
    0xFA00 - lh_sched_end
), "native scheduler scan consumed the zero seam before op_move_g@$00:FA00"
assert interp_symbol("iloop") == 0x80A5
assert INTERP[0x00AC:0x00B1] == bytes.fromhex("22c0e597ea"), (
    "packed virtual-IRQ reload no longer calls campaign_irq_reload@$97:E5C0"
)
# readbyte deliberately reuses the store mapper to translate video-shadow
# addresses.  The bank-$9E publisher distinguishes that read by the exact JSR
# return word ($B615), so pin the caller and both ends of the packed bridge.
assert interp_symbol("rb_zero") == 0xB60D
assert interp_symbol("map_snes") == 0xF800
assert interp_symbol("ms_shadow_return") == 0xF846
assert INTERP[0x360D:0x3616] == bytes.fromhex("a554856aa5522000f8"), (
    "rb_zero video-shadow mapping call moved; update the read-only publisher guard"
)
# STZ has no 65816 long-address form.  Poppy silently truncated the old
# `stz $400000,x` virtual-IRQ PC push to `stz $0000,x`, letting emulated
# stack offsets overwrite IRAM (including FRAME_REQ at physical $0300).
# Guard the size-neutral two-word long store and its bank-$00 layout seam.
assert INTERP[0x340F:0x342B] == (
    bytes.fromhex("c220a542eb9f000040e8e8a540eb9f000040e8")
    + bytes.fromhex("ea" * 9)
), "take_irq no longer performs the pinned long-address PC stack push"
assert INTERP[0x5308:0x5318] == bytes.fromhex(
    "c9f900f0034c50d3a995008542dc4000"
), "bank-$95 $00F9 return-sentinel island moved or lost its bank-$9D chain"
assert INTERP[0x5350:0x5360] == bytes.fromhex(
    "c9f800f0034c3aeaa99d008542dc4000"
), "bank-$9D $00F8 return-sentinel island moved or was overwritten"
trap1_dispatch = interp_symbol("trap1_dispatch")
trap1_dispatch_end = interp_symbol("trap1_dispatch_end")
op_movem_abs = interp_symbol("op_movem_abs")
assert trap1_dispatch == 0xD3A1 and trap1_dispatch_end <= 0xD3BC, (
    "TRAP #1 dispatcher moved or escaped its dead-$25110 island"
)
assert INTERP[op_movem_abs - 0x8000 - 3:op_movem_abs - 0x8000] == bytes.fromhex(
    "4ca1d3"
), "op_trap no longer ends in the size-neutral trap1_dispatch jump"
assert INTERP[trap1_dispatch - 0x8000:trap1_dispatch_end - 0x8000].count(
    bytes.fromhex("5c00809e")
) == 1, "TRAP #1 dispatcher lost its sole $9E:8000 native target"
assert len(IMG) == 0x80000, len(IMG)
assert len(GFX) == 0x200000, len(GFX)


def build_snes_tile_blob(gfx: bytes) -> bytes:
    """Reorder every arcade 16x16 tile into four native SNES 4bpp tiles.

    The arcade and SNES formats store the same plane bits; the old 5A22
    ``decode_tile`` paid to rearrange their bytes every time a code first
    appeared on screen.  The graphics ROM is immutable, so perform that exact
    permutation once while packing the private-derived ROM.  Each 128-byte
    output record is TL, TR, BL, BR (32 bytes apiece), which remains indexed by
    ``code * 128`` at CPU $C9:0000.
    """

    assert len(gfx) % 0x80 == 0
    output = bytearray(len(gfx))
    for base in range(0, len(gfx), 0x80):
        for y in range(16):
            source_row = y * 4 if y < 8 else 0x40 + (y - 8) * 4
            vertical_quad = 0 if y < 8 else 2
            for half in range(2):
                source = base + source_row + half * 0x20
                destination = (
                    base
                    + (vertical_quad + half) * 0x20
                    + (y & 7) * 2
                )
                # Taito plane 0 is the high pixel bit; SNES plane 0 is the
                # low pixel bit.  This is the same reversal as dt_copy4.
                output[destination] = gfx[source + 3]
                output[destination + 1] = gfx[source + 2]
                output[destination + 0x10] = gfx[source + 1]
                output[destination + 0x11] = gfx[source]
    result = bytes(output)
    assert hashlib.sha256(result).hexdigest() == (
        "991a34a8fc6984048bf9bd29d9d5dc697f6c48885105fca0f6c778020c16a329"
    ), "SNES-native graphics permutation changed; re-run the 128/128 oracle"
    return result


def make_credit_tiles_transparent(snes_gfx: bytes) -> bytes:
    """Remove the arcade credit label's painted-black background.

    Logical OBJ codes $007D-$0080 spell the four wide ``CREDIT`` chunks used
    by the bottom HUD.  Their source art uses palette index 15 for the black
    arcade backdrop instead of transparent index 0.  That was harmless over
    the arcade's black overscan, but after the centered SNES crop moved the
    label over live artwork it became an opaque rectangle.

    Patch only pixels whose complete native 4bpp value is 15, and only in
    those four derived tile records.  White glyph pixels (index 1), every
    other palette index, and the authenticated private graphics input remain
    unchanged.
    """

    output = bytearray(snes_gfx)
    changed_by_code: dict[int, int] = {}
    for code in range(0x007D, 0x0081):
        changed = 0
        record = code * 0x80
        for quadrant in range(4):
            tile = record + quadrant * 0x20
            for row in range(8):
                planes = (
                    tile + row * 2,
                    tile + row * 2 + 1,
                    tile + 0x10 + row * 2,
                    tile + 0x11 + row * 2,
                )
                index15 = (
                    output[planes[0]]
                    & output[planes[1]]
                    & output[planes[2]]
                    & output[planes[3]]
                )
                changed += index15.bit_count()
                keep = 0xFF ^ index15
                for plane in planes:
                    output[plane] &= keep
        changed_by_code[code] = changed

    assert changed_by_code == {
        0x007D: 234,
        0x007E: 194,
        0x007F: 204,
        0x0080: 238,
    }, "credit-label pixel shape changed; re-audit the transparent-HUD patch"
    result = bytes(output)
    assert hashlib.sha256(result).hexdigest() == (
        "1a5b137302ccff5bebd9ea307a166cc7e7ba75d867991e84ea2ee899686689a5"
    ), "transparent credit-tile derivation changed unexpectedly"
    return result


def build_c262_dma_blob(image: bytes) -> bytes:
    """Derive the first thirteen fixed $C262 tilemap rows from the private ROM."""

    pointer_table = 0x5707C
    pointers = [
        int.from_bytes(image[pointer_table + index * 4:pointer_table + index * 4 + 4], "big")
        for index in range(4)
    ]
    assert pointers == [0x055CD4, 0x055DB4, 0x055E94, 0x055F74], (
        "$C262 source-pointer table changed; re-audit the fixed-row HLE"
    )
    planes = [bytearray(), bytearray()]
    for row in range(13):
        source = pointers[row // 4] + (row % 4) * 0x38
        assert source == 0x055CD4 + row * 0x38
        words = [
            int.from_bytes(image[source + offset:source + offset + 2], "big")
            for offset in range(0, 0x38, 2)
        ]
        outputs = [bytearray(0x38), bytearray(0x38)]
        for index, word in enumerate(words):
            destination = (index % 14) * 4 + (2 if index >= 14 else 0)
            values = (
                word & 0x1FFF,
                (((word >> 2) & 0xF800) + 0x9000) & 0xFFFF,
            )
            for plane, value in enumerate(values):
                outputs[plane][destination:destination + 2] = value.to_bytes(2, "big")
        for plane in range(2):
            planes[plane].extend(outputs[plane])
    blob = bytes(planes[0] + planes[1])
    assert len(blob) == 0x05B0
    assert hashlib.sha256(blob).hexdigest() == (
        "996c12c27a441547f99e05976d1602498470395cbb31fbf74c541620fd20a309"
    ), "$C262 DMA payload changed; inspect the private input before accepting it"
    return blob


def build_c0bc_blobs(image: bytes) -> tuple[bytes, bytes]:
    """Derive selector zero's fixed rows and exact prepared renderer image.

    The native initializer copies the first thirteen rows directly and leaves
    the real final $29B6 callback in charge of row fourteen.  When every cell
    outside that 14x28 footprint is empty, the resulting BG image is fully
    determined by these private-ROM tables.  The second blob is the exact
    producer-prepared representation consumed by the established $FFFE
    renderer path: 4 KiB SNES tilemap, sorted code words, then the 32-byte
    arcade-palette-bank map.
    """

    source_table = int.from_bytes(image[0xC23A:0xC23E], "big")
    tile_table = int.from_bytes(image[0xC24E:0xC252], "big")
    assert source_table == 0x055FE4 and tile_table == 0x05708C, (
        "$C0BC selector-zero tables changed; re-audit the production HLE"
    )
    expected_sources = (
        0x046874, 0x0468AC, 0x0468E4, 0x04691C,
        0x047214, 0x04724C, 0x047284, 0x0472BC,
        0x047754, 0x04778C, 0x0477C4, 0x0477FC,
        0x047834, 0x04786C,
    )
    compact_planes = [bytearray(), bytearray()]
    full_planes = [bytearray(0x0400), bytearray(0x0400)]
    observed_sources = []
    for row in range(14):
        group = row // 4
        source = int.from_bytes(
            image[source_table + group * 4:source_table + group * 4 + 4],
            "big",
        ) + (row % 4) * 0x38
        tile_base = int.from_bytes(
            image[tile_table + group * 2:tile_table + group * 2 + 2],
            "big",
        )
        observed_sources.append(source)
        assert tile_base == 0x9800, (
            "$C0BC selector-zero tile base changed; re-audit the production HLE"
        )
        outputs = [bytearray(0x38), bytearray(0x38)]
        for index in range(28):
            word = int.from_bytes(
                image[source + index * 2:source + index * 2 + 2], "big"
            )
            destination = (index % 14) * 4 + (2 if index >= 14 else 0)
            values = (
                word & 0x1FFF,
                0x9000 if ((word >> 2) & 0xF800) else tile_base,
            )
            for plane, value in enumerate(values):
                outputs[plane][destination:destination + 2] = value.to_bytes(2, "big")
        for plane in range(2):
            full_planes[plane][row * 0x40:row * 0x40 + 0x38] = outputs[plane]
            if row < 13:
                compact_planes[plane].extend(outputs[plane])
    assert tuple(observed_sources) == expected_sources, (
        "$C0BC selector-zero row sources changed; re-audit the production HLE"
    )
    dma_blob = bytes(compact_planes[0] + compact_planes[1])
    assert len(dma_blob) == 0x05B0
    assert hashlib.sha256(dma_blob).hexdigest() == (
        "aaffe61ca522b324fe0f856853c0d61ee05ab6d8f459359f739aabd80e2688d4"
    ), "$C0BC DMA payload changed; inspect the private input before accepting it"

    codes = bytes(full_planes[0])
    colors = bytes(full_planes[1])
    nonempty_codes = [
        int.from_bytes(codes[offset:offset + 2], "big") & 0x3FFF
        for offset in range(0, 0x0400, 2)
        if int.from_bytes(codes[offset:offset + 2], "big") & 0x3FFF
    ]
    unique_codes = sorted(set(nonempty_codes))
    assert len(nonempty_codes) == 392 and len(unique_codes) == 45, (
        "$C0BC prepared-image shape changed; re-audit the renderer shortcut"
    )
    slots = {code: index for index, code in enumerate(unique_codes)}
    palette_map = bytearray([0xFF] * 32)
    next_palette = 0
    tilemap = bytearray(0x1000)
    for cell, offset in enumerate(range(0, 0x0400, 2)):
        raw_code = int.from_bytes(codes[offset:offset + 2], "big")
        code = raw_code & 0x3FFF
        if not code:
            continue
        palette_bank = (colors[offset] & 0xF8) >> 3
        if palette_map[palette_bank] == 0xFF:
            assert next_palette < 8
            palette_map[palette_bank] = next_palette
            next_palette += 1
        attributes = slots[code] * 4 | palette_map[palette_bank] * 0x0400
        flips = raw_code & 0xC000
        if flips not in (0, 0xC000):
            flips ^= 0xC000
        attributes |= flips

        column, row = divmod(cell, 32)
        horizontal = column * 8 + (row & 1) * 4
        if horizontal & 0x40:
            horizontal = (horizontal & 0x3F) + 0x0800
        destination = (row & 0x1E) * 64 + horizontal
        for delta, value in (
            (0x0000, attributes),
            (0x0002, attributes + 1),
            (0x0040, attributes + 2),
            (0x0042, attributes + 3),
        ):
            tilemap[destination + delta:destination + delta + 2] = (
                value.to_bytes(2, "little")
            )

    sorted_code_blob = b"".join(
        code.to_bytes(2, "little") for code in unique_codes
    )
    assert len(sorted_code_blob) == 0x005A and next_palette == 2
    prepared_blob = bytes(tilemap) + sorted_code_blob + bytes(palette_map)
    assert len(prepared_blob) == 0x107A
    assert hashlib.sha256(prepared_blob).hexdigest() == (
        "24c76d377b164f4d26749c47127539eb64f95c5ebc3fe0b35feec57e91336fa7"
    ), "$C0BC prepared payload changed; inspect the private input before accepting it"
    return dma_blob, prepared_blob


C262_DMA_BLOB = build_c262_dma_blob(IMG)
C0BC_DMA_BLOB, C0BC_PREPARED_BLOB = build_c0bc_blobs(IMG)
SNES_GFX = make_credit_tiles_transparent(build_snes_tile_blob(GFX))

# 4MB HiROM: interp @ $C0:8000, 68K image @ $C1:0000 (file $10000), and the
# private arcade tile ROM pre-permuted into native SNES 4bpp records @ $C9:0000
# (file $90000). Runtime keeps the same flat $C90000 + code*128 lookup while
# avoiding an expensive per-tile software decode.
ROM = bytearray(0x400000)                            # 4MB HiROM
ROM[0x8000:0x10000] = INTERP                         # interpreter + vectors @ $00/$C0:8000
ROM[0x10000:0x90000] = IMG                           # 68K image @ $C1:0000 (flat $C10000+A)
ROM[0x90000:0x290000] = SNES_GFX                     # native SNES tiles @ $C9:0000
BOOT_ASSET, BOOT_ASSET_REPORT = build_boot_asset()
assert len(BOOT_ASSET) == BOOT_ASSET_SIZE == 0x8000
assert BOOT_ASSET_REPORT["sha256"] == hashlib.sha256(BOOT_ASSET).hexdigest()
assert BOOT_ASSET_REPORT["sections"] == {
    "tilemap_low": [0x0000, 0x4000],
    "mode7_tile_high": [0x4000, 0x2800],
    "obj_tiles": [0x6800, 0x1000],
    "oam": [0x7800, 0x0220],
    "palette": [0x7C00, 0x0200],
    "matrices": [0x7E00, 0x0200],
}, "Mode 7 generator offsets no longer match boot_screen_init's DMA descriptors"
boot_matrices = [
    tuple(
        int.from_bytes(
            BOOT_ASSET[0x7E00 + index * 8 + field * 2:
                       0x7E02 + index * 8 + field * 2],
            "little",
        )
        for field in range(4)
    )
    for index in range(64)
]
assert boot_matrices[0] == (0x0020, 0, 0, 0x0020)
assert boot_matrices[-1] == (0x00C0, 0, 0, 0x00C0)
assert all(
    a == d and b == 0 and c == 0
    for a, b, c, d in boot_matrices
), "boot matrix table gained rotation/shear or mismatched identity coefficients"
assert all(
    boot_matrices[index][0] < boot_matrices[index + 1][0]
    for index in range(63)
), "boot matrix table is no longer a one-shot monotonic huge-to-fitted zoom"
assert ROM[0x300000:0x308000] == bytes(0x8000), (
    "5A22 bank-$F0 boot-asset window overlaps another packed payload"
)
ROM[0x300000:0x308000] = BOOT_ASSET                  # original Mode 7 boot screen @ $F0:0000
VID = Path("src/video.bin").read_bytes()             # video subsystem (assembled @ $8000)
assert len(VID) <= 0x8000, len(VID)
VID_SYMBOLS = Path("src/video.sym").read_text(encoding="utf-8-sig")


def vid_off(symbol):
    for line in VID_SYMBOLS.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError("missing video layout symbol %s" % symbol)


# rc_copy mirrors only the ordinary $E9:8000-$AFFF renderer window.  The queue
# promoter is installed lazily in private $7E:ED00 WRAM while pacing has the SA-1
# asleep.  Bank $7F is never suitable: all 64 KiB are active emulated 68000 work
# RAM, not renderer scratch.  Layout assertions keep those execution domains
# explicit and prohibit both the old early-boot and delayed bank-$7F stores.
# The OAM hide loop used an exact-equality exit.  Once NMI/IRQ preemption
# disturbed X's low bits, it missed $0201 and wrote $F0 every four bytes through
# the supervisor and WRAM code mirror.  Keep the size-neutral bounded branch at
# $81B5 so that failure mode cannot silently return.
assert VID[0x01B5] == 0x90, (
    "vid_obj OAM hide loop is no longer bounded by BCC at $81B5"
)
# The WRAM renderer runs with DBR=$00.  A bare `lda $0734` therefore read
# unrelated 5A22 WRAM, not the SA-1 IRAM production gate, and selected the
# paced snapshot path only by chance.  Require the shared $41:012C cadence
# marker test at the pinned snapshot-acquire entry.
assert VID[0x1E00:0x1E11] == bytes.fromhex(
    "c230af2c014129ff00c9a500d0034c00a1"
), "snapshot_acquire no longer selects paced acquisition from $41:012C == $A5"
# snd_vframe must increment the two-byte FRAME_REQ while its forced A16 mode is
# still active, then restore the caller's P.  Restoring P first made the counter
# width caller-dependent and produced the observed $01F8->$0100 gameplay wrap.
assert VID[0x197D:0x1984] == bytes.fromhex("fa68ee0033286b"), (
    "snd_vframe no longer increments FRAME_REQ before restoring caller P"
)
# FRAME_ACK is a pre-render coalescing token, not a completion count.  Preserve
# the non-invasive telemetry written only after the real PPU flush returns.
assert VID[0x1D12:0x1D29] == bytes.fromhex(
    "202980c230afa2897e1a8fa2897eafa0897e4c809deaea"
), "true completed-render counter/generation telemetry moved or changed"
assert vid_off("ppu_dma_flush_ack_finish") == 0x9D80
assert VID[0x1D80:0x1D91] == bytes.fromhex(
    "8fa4897ee220ad1b1f10039c1b1fc22060"
), "completed-render tail no longer publishes generation and retires boot ownership"
# Production pacing is split across fixed WRAM-mirrored islands immediately
# before the TAD code at $9000. Guard both the flowing rc_copy tail and every
# handler seam because Poppy silently accepts overlapping .org sections.
bg_tile_run_dma_chunks = vid_off("bg_tile_run_dma_chunks")
bg_tile_run_dma_chunks_end = vid_off("bg_tile_run_dma_chunks_end")
service_pending_dma0 = vid_off("service_pending_dma0")
service_pending_dma0_end = vid_off("service_pending_dma0_end")
dma0_blank_pulse_extended = vid_off("dma0_blank_pulse_extended")
dma0_blank_pulse_extended_end = vid_off("dma0_blank_pulse_extended_end")
boot_mode7_tick = vid_off("boot_mode7_tick")
boot_mode7_tick_end = vid_off("boot_mode7_tick_end")
obj_cache_protect_displayed = vid_off("obj_cache_protect_displayed")
obj_cache_protect_displayed_end = vid_off("obj_cache_protect_displayed_end")
boot_mode7_scale_tick = vid_off("boot_mode7_scale_tick")
boot_mode7_scale_tick_end = vid_off("boot_mode7_scale_tick_end")
assert bg_tile_run_dma_chunks == 0x8A00
assert (
    0x8A00
    < bg_tile_run_dma_chunks_end
    == service_pending_dma0
    < service_pending_dma0_end
    == dma0_blank_pulse_extended
    < dma0_blank_pulse_extended_end
    <= 0x8B00
)
service_pending_dma0_bytes = VID[
    service_pending_dma0 - 0x8000:service_pending_dma0_end - 0x8000
]
assert bytes.fromhex("ad3f21ad3721ad3d21") in service_pending_dma0_bytes, (
    "pending DMA0 service no longer resets OPVCT low/high phase through "
    "STAT78 before latching and reading the vertical counter"
)
assert VID[
    dma0_blank_pulse_extended_end - 0x8000:boot_mode7_tick - 0x8000
] == bytes(boot_mode7_tick - dma0_blank_pulse_extended_end), (
    "VBlank DMA helpers grew into the fixed Mode 7 activity island"
)
assert boot_mode7_tick == 0x8B00 and boot_mode7_tick < boot_mode7_tick_end <= 0x8B40
assert VID[
    boot_mode7_tick_end - 0x8000:obj_cache_protect_displayed - 0x8000
] == bytes(obj_cache_protect_displayed - boot_mode7_tick_end), (
    "boot activity helper grew into the displayed-OBJ quarantine island"
)
assert (
    obj_cache_protect_displayed == 0x8B40
    and obj_cache_protect_displayed
    < obj_cache_protect_displayed_end
    <= boot_mode7_scale_tick
    == 0x8BC0
    < boot_mode7_scale_tick_end
    <= 0x8DD0
)
assert VID[
    obj_cache_protect_displayed_end - 0x8000:boot_mode7_scale_tick - 0x8000
] == bytes(boot_mode7_scale_tick - obj_cache_protect_displayed_end), (
    "displayed-OBJ quarantine helper grew into the boot-scale island"
)
assert VID[
    boot_mode7_scale_tick_end - 0x8000:0x0DD0
] == bytes(0x8DD0 - boot_mode7_scale_tick_end), (
    "boot-scale helper grew into the $8DD0 pacing island"
)
assert VID[0x099C:0x09AB] == bytes.fromhex(
    "bf0080e99f00807fe8e8e00030d0f1"
), "rc_copy no longer mirrors the full $8000-$AFFF production supervisor"
assert VID[0x0DD0:0x0DE4] == bytes.fromhex(
    "08e220eaeaeaaf2c0141c9a5f004284c56882860"
), "ordered-input wrapper moved or changed"
assert VID[0x0DE4:0x0E00] == bytes(0x1C), (
    "ordered-input wrapper grew into pacing_try_wake"
)
pacing_try_wake = vid_off("pacing_try_wake")
pacing_renderer_ownership_guard = vid_off("ptw_renderer_ownership_guard")
pacing_pending_direct_guard = vid_off("ptw_pending_direct_guard")
pacing_snapshot_queued = vid_off("ptw_snapshot_queued")
pacing_snapshot_publish = vid_off("ptw_snapshot_direct")
pacing_vtime_publish_tail = vid_off("pacing_vtime_publish_tail")
pacing_publish_vtime_joy = vid_off("pacing_publish_vtime_joy")
pacing_helpers_end = vid_off("pacing_helpers_end")
assert pacing_try_wake == 0x8E00
assert (
    pacing_try_wake
    < pacing_renderer_ownership_guard
    < pacing_pending_direct_guard
    < pacing_snapshot_queued
    < pacing_snapshot_publish
    < pacing_vtime_publish_tail
    < pacing_publish_vtime_joy
    < pacing_helpers_end
    <= 0x8F00
), "pacing direct-publication guard or helper seam moved out of order"
assert pacing_vtime_publish_tail == 0x8EA8, (
    "VTIME input publisher no longer begins at the historical sampler RTS seam"
)
assert VID[
    pacing_vtime_publish_tail - 0x8000:pacing_publish_vtime_joy - 0x8000
] == bytes.fromhex("4cab8e"), (
    "VTIME input sampler tail no longer jumps to its adjacent publisher"
)
renderer_guard_offset = pacing_renderer_ownership_guard - 0x8000
assert VID[renderer_guard_offset:renderer_guard_offset + 5] == bytes.fromhex(
    "af9c897ed0"
), "pacing wake no longer treats an active renderer as queue-owned"
renderer_guard_branch = VID[renderer_guard_offset + 5]
if renderer_guard_branch >= 0x80:
    renderer_guard_branch -= 0x100
assert pacing_renderer_ownership_guard + 6 + renderer_guard_branch == pacing_snapshot_queued, (
    "active-renderer branch no longer reaches the compressed queue path"
)
pending_guard_offset = pacing_pending_direct_guard - 0x8000
assert VID[pending_guard_offset:pending_guard_offset + 8] == bytes.fromhex(
    "af1e1f7ecd0233f0"
), "pacing wake no longer treats an unclaimed direct publication as busy"
pending_guard_branch = VID[pending_guard_offset + 8]
if pending_guard_branch >= 0x80:
    pending_guard_branch -= 0x100
assert pacing_pending_direct_guard + 9 + pending_guard_branch == pacing_snapshot_publish, (
    "pending-direct equality branch no longer reaches direct snapshot publication"
)
assert VID[pacing_helpers_end - 0x8000:0x0F00] == bytes(
    0x8F00 - pacing_helpers_end
), "pacing helper grew into the fixed NMI handler"
assert VID[0x0F00:0x0F3A] == bytes.fromhex(
    "08c23048da5a8be220a90048aba9808d"
    "0122af2a01411a8f2a014120008e2033"
    "8a208a8e20808fad0233ab"
    "eaeaeaeaeaeaeaea"
    "c2307afa682840"
), (
    "pacing NMI handler lost its leading-edge wake/DMA/cache-scroll wrapper "
    "or A-preserving restore order"
)
assert VID[0x0F3A:0x0F40] == bytes(0x06), (
    "pacing NMI handler grew into the fixed coprocessor-IRQ handler"
)
assert VID[0x0F68:0x0F80] == bytes(0x18) and VID[0x0F96:0x1000] == bytes(0x6A), (
    "pacing IRQ/cache-scroll handler grew into an adjacent reserved island"
)
assert VID[0x0F80:0x0F96] == bytes.fromhex(
    "20008bad0233f00dc220a5d04820b0a16885d0e22060"
), (
    "NMI cache-scroll wrapper no longer preserves boot ownership, waits for an "
    "acknowledged frame, preserves renderer DP scratch, or reapplies only the "
    "cached BG scroll registers"
)
# Keep each renderer island inside its declared execution domain.  Symbol bounds
# plus explicit zero seams catch Poppy's permissive .org overlap without freezing
# implementation bytes that these optimizations intentionally change.
palette_test = vid_off("pacing_palette_cache_test")
palette_test_end = vid_off("pacing_palette_cache_test_end")
bg_scroll = vid_off("bg_scroll")
bg_scroll_end = vid_off("bg_scroll_end")
bg_hscroll = vid_off("bg_hscroll")
bg_test = vid_off("pacing_bg_cache_test")
bg_test_end = vid_off("pacing_bg_cache_test_end")
obj_y_transform = vid_off("obj_y_transform")
obj_y_transform_end = vid_off("obj_y_transform_end")
bg_capacity_exact = vid_off("bg_capacity_exact")
bg_capacity_exact_end = vid_off("bg_capacity_exact_end")
snapshot_direct = vid_off("pacing_snapshot_direct")
snapshot_direct_end = vid_off("pacing_snapshot_direct_end")
obj_fast = vid_off("vid_obj_fast")
obj_oam_fast = vid_off("obj_oam_fast")
obj_oam_fast_end = vid_off("obj_oam_fast_end")
obj_hclr_stub = vid_off("obj_hclr")
obj_slot_legacy = vid_off("obj_slot")
obj_upload_dispatch = vid_off("obj_upload_dispatch")
obj_slot_fast_hash = vid_off("obj_slot_fast_hash")
obj_slot_fast_hash_end = vid_off("obj_slot_fast_hash_end")
obj_hash_clear = vid_off("obj_hclr_extended")
obj_queue_prepare_extended = vid_off("obj_queue_prepare_extended")
obj_hash_helpers_end = vid_off("obj_hash_helpers_end")
vf_tick = vid_off("vf_tick")
rc_copy = vid_off("rc_copy")
snapshot_acquire_paced = vid_off("snapshot_acquire_paced")
render_queue_finish = vid_off("render_queue_finish")
render_queue_install = vid_off("render_queue_install")
render_queue_helpers_end = vid_off("render_queue_helpers_end")
obj_upload_title_dispatch = vid_off("obj_upload_title_dispatch")
obj_upload_title_dispatch_end = vid_off("obj_upload_title_dispatch_end")
obj_palette_cache_init = vid_off("vof_pal_cache_init")
obj_palette_fill_cached = vid_off("obj_pal_fill_cached")
obj_fast_end = vid_off("vid_obj_fast_end")
obj_cache_next_packed = vid_off("ocp_next_packed")
obj_render_next_packed = vid_off("vop_next")
obj_queue_prepare_stub = vid_off("obj_queue_prepare")
obj_tile_queue = vid_off("obj_tile_queue")
obj_slot_fast_stub = vid_off("obj_slot_fast")
obj_cache_preflight = vid_off("obj_cache_preflight")
obj_cache_reclaim_fast = vid_off("obj_cache_reclaim_fast")
obj_cache_reclaim_fast_end = vid_off("obj_cache_reclaim_fast_end")
vid_obj_packed = vid_off("vid_obj_packed")
vid_obj_packed_end = vid_off("vid_obj_packed_end")
snapshot_dma_helpers = vid_off("psd_palette_dma")
snapshot_dma_helpers_end = vid_off("psd_manifest_dma_end")
bg_incremental = vid_off("vid_bg_incremental")
bg_incremental_end = vid_off("vid_bg_incremental_end")
capture_bg_vscroll = vid_off("capture_bg_vscroll")
capture_bg_vscroll_end = vid_off("capture_bg_vscroll_end")
capture_bg_upper_snapshot = vid_off("capture_bg_upper_snapshot")
capture_bg_upper_direct = vid_off("capture_bg_upper_direct")
capture_bg_upper_primary = vid_off("capture_bg_upper_primary")
capture_bg_upper_secondary = vid_off("capture_bg_upper_secondary")
capture_bg_upper_end = vid_off("capture_bg_upper_end")
bg_dispatch_dynamic = vid_off("bg_dispatch_dynamic")
bg_dispatch_dynamic_end = vid_off("bg_dispatch_dynamic_end")
bg_slot = vid_off("bg_slot")
bg_tile_dma = vid_off("bg_tile_dma")
bg_cache_reset_counts = vid_off("bg_cache_reset_counts")
bg_cache_reset_counts_end = vid_off("bg_cache_reset_counts_end")
producer_touch_reset = vid_off("producer_touch_reset")
producer_touch_reset_end = vid_off("producer_touch_reset_end")
bg_cache_extended = vid_off("bg_slot_extended")
bg_cache_reclaim = vid_off("bg_cache_reclaim")
bg_cache_reclaim_end = vid_off("bg_cache_reclaim_end")
bg_cache_extended_end = vid_off("bg_cache_extended_end")
bg_upload = vid_off("bg_upload")
queue_capture = vid_off("render_queue_capture")
queue_capture_end = vid_off("render_queue_capture_end")
queue_capture_secondary = vid_off("render_queue_capture_secondary")
queue_capture_secondary_end = vid_off("render_queue_capture_secondary_end")
title_bg_overlay = vid_off("title_bg_overlay")
title_bg_overlay_end = vid_off("title_bg_overlay_end")
title_bg_upload = vid_off("title_bg_upload")
title_font_codes = vid_off("title_font_codes")
title_text_row14 = vid_off("title_text_row14")
bg_write_cell = vid_off("bg_write_cell")
bg_write_cell_end = vid_off("bg_write_cell_end")
bg_column_map_update = vid_off("bg_column_map_update")
bg_column_map_update_end = vid_off("bg_column_map_update_end")
bg_offset_table_build = vid_off("bg_offset_table_build")
bg_offset_table_build_end = vid_off("bg_offset_table_build_end")
capture_bg_upper_full = vid_off("capture_bg_upper_full")
capture_bg_upper_full_end = vid_off("capture_bg_upper_full_end")
bg_hscroll_full = vid_off("bg_hscroll_full")
bg_hscroll_full_end = vid_off("bg_hscroll_full_end")
accept_bg_columns_snapshot = vid_off("accept_bg_columns_snapshot")
accept_bg_columns_snapshot_end = vid_off("accept_bg_columns_snapshot_end")
accept_bg_columns_direct = vid_off("accept_bg_columns_direct")
accept_bg_columns_direct_end = vid_off("accept_bg_columns_direct_end")
prepared_bg_map_remap = vid_off("prepared_bg_map_remap")
prepared_bg_map_remap_end = vid_off("prepared_bg_map_remap_end")
queue_promote = vid_off("render_queue_promote")
queue_promote_end = vid_off("render_queue_promote_end")
boot_screen_init = vid_off("boot_screen_init")
boot_screen_init_end = vid_off("boot_screen_init_end")
video_image_end = vid_off("video_image_end")
assert palette_test == 0xA1A0 and palette_test < palette_test_end <= bg_test == 0xA1E8
assert palette_test < bg_scroll == 0xA1B0 < bg_scroll_end == palette_test_end
assert VID[
    bg_scroll - 0x8000:bg_scroll_end - 0x8000
] == bytes.fromhex(
    "20998808e220afbf897e300eaf94897e8d0e21a9008d0e212860"
    "a9008d0e218d0e212860"
), "BG scroll dispatcher lost its title guard or two-write VOFS publication"
assert VID[bg_hscroll - 0x8000:bg_hscroll - 0x8000 + 5] == bytes.fromhex(
    "2200bbe960"
), "BG hscroll wrapper no longer reaches the fixed ROM helper"
bg_hscroll_full_bytes = VID[
    bg_hscroll_full - 0x8000:bg_hscroll_full_end - 0x8000
]
assert bg_hscroll_full_bytes == bytes.fromhex(
    "08c230e220af95897ec22029ff0085d0af96897ec9feffb00ca5d0291f0085d0a"
    "94000800caf96897e290100eb1869400038e5d029ff03e2208d0d21eb8d0d21286b"
), "BG hscroll helper changed without a fresh-boot-safe fixture"
assert VID[palette_test_end - 0x8000:bg_test - 0x8000] == bytes(
    bg_test - palette_test_end
), "palette manifest consumer overlapped the fixed BG consumer"
assert bg_test < bg_test_end <= obj_y_transform == 0xA200
assert VID[bg_test_end - 0x8000:obj_y_transform - 0x8000] == bytes(
    obj_y_transform - bg_test_end
), "BG manifest consumer overlapped the top-HUD Y-transform island"
assert obj_y_transform < obj_y_transform_end <= bg_capacity_exact == 0xA220
assert VID[
    obj_y_transform - 0x8000:obj_y_transform_end - 0x8000
] == bytes.fromhex(
    "a5ecc9e200f00fc9f000b00aa9da0038e5ec29ff0060"
    "a9ea0138e5ec29ff0060"
), "top-HUD Y transform lost its bounded $E2/$F0-$F2 wrap mapping"
assert VID[
    obj_y_transform_end - 0x8000:bg_capacity_exact - 0x8000
] == bytes(bg_capacity_exact - obj_y_transform_end), (
    "top-HUD Y transform crossed the exact-capacity helper"
)
assert bg_capacity_exact < bg_capacity_exact_end <= bg_cache_reset_counts == 0xA290
assert VID[
    bg_capacity_exact_end - 0x8000:bg_cache_reset_counts - 0x8000
] == bytes(bg_cache_reset_counts - bg_capacity_exact_end), (
    "BG exact-capacity helper overlapped the persistent-cache reset island"
)
assert bg_cache_reset_counts < bg_cache_reset_counts_end <= producer_touch_reset == 0xA2D0
assert VID[
    bg_cache_reset_counts_end - 0x8000:producer_touch_reset - 0x8000
] == bytes(producer_touch_reset - bg_cache_reset_counts_end), (
    "persistent BG cache reset crossed the producer-touch reset island"
)
assert producer_touch_reset < producer_touch_reset_end <= snapshot_direct == 0xA300
assert VID[
    producer_touch_reset_end - 0x8000:snapshot_direct - 0x8000
] == bytes(snapshot_direct - producer_touch_reset_end), (
    "producer-touch reset crossed the direct snapshot island"
)
assert snapshot_direct < snapshot_direct_end <= obj_fast == 0xA400
assert VID[snapshot_direct_end - 0x8000:obj_fast - 0x8000] == bytes(
    obj_fast - snapshot_direct_end
), "direct snapshot helper crossed the fast OBJ island"
assert obj_fast < obj_fast_end <= snapshot_dma_helpers == 0xA600
assert VID[obj_fast_end - 0x8000:snapshot_dma_helpers - 0x8000] == bytes(
    snapshot_dma_helpers - obj_fast_end
), "fast OBJ transform crossed the conditional snapshot-DMA helpers"
assert obj_hclr_stub == 0x8740 and obj_slot_legacy == 0x8756
assert VID[obj_hclr_stub - 0x8000:obj_hclr_stub - 0x8000 + 3] == bytes.fromhex(
    "4c00a0"
), "OBJ hash clear no longer redirects to the guarded widened-hash helper"
assert obj_upload_dispatch == 0x9C27
assert VID[0x9C2A - 0x8000:obj_slot_fast_hash - 0x8000] == bytes(
    obj_slot_fast_hash - 0x9C2A
), "OBJ upload dispatch crossed the widened-hash lookup island"
assert obj_slot_fast_hash == 0x9C40
assert obj_slot_fast_hash < obj_slot_fast_hash_end <= 0x9D00
assert VID[obj_slot_fast_hash_end - 0x8000:0x9D00 - 0x8000] == bytes(
    0x9D00 - obj_slot_fast_hash_end
), "widened OBJ hash lookup crossed vid_obj_cached"
assert obj_hash_clear == 0xA000
assert obj_hash_clear < obj_hash_helpers_end <= render_queue_finish == 0xA090
assert bytes.fromhex("8a18691000aaa90000e00008") in VID[
    obj_hash_clear - 0x8000:obj_hash_helpers_end - 0x8000
], "unrolled OBJ hash clear no longer restores A=0 between blocks"
assert VID[
    obj_hash_helpers_end - 0x8000:render_queue_finish - 0x8000
] == bytes(render_queue_finish - obj_hash_helpers_end), (
    "OBJ hash helpers crossed the queue-finish island"
)
assert render_queue_finish < render_queue_install < render_queue_helpers_end
assert (
    render_queue_helpers_end
    <= obj_upload_title_dispatch
    == 0xA0E0
    < obj_upload_title_dispatch_end
    <= snapshot_acquire_paced
    == 0xA100
)
assert VID[
    render_queue_helpers_end - 0x8000:obj_upload_title_dispatch - 0x8000
] == bytes(obj_upload_title_dispatch - render_queue_helpers_end), (
    "lazy queue installer crossed the title-upload dispatch island"
)
assert VID[
    obj_upload_title_dispatch_end - 0x8000:0xA100 - 0x8000
] == bytes(0xA100 - obj_upload_title_dispatch_end), (
    "title-upload dispatch crossed paced snapshot acquisition"
)
assert bytes.fromhex("9f00007f") not in VID, (
    "renderer must never write $7F:0000,X; bank $7F is emulated 68000 work RAM"
)
assert VID[vf_tick - 0x8000 + 12:vf_tick - 0x8000 + 16] == bytes.fromhex(
    "5c90a07f"
), "vf_tick no longer tail-jumps to the queue-aware WRAM finish helper"
assert bytes.fromhex("5c00ed7e") in VID[
    render_queue_finish - 0x8000:render_queue_install - 0x8000
], "queue-finish helper no longer jumps to private $7E:ED00 promoter code"
assert bytes.fromhex("9f00ed7e") not in VID[
    rc_copy - 0x8000:0x8E00 - 0x8000
], "rc_copy must not write the queue promoter during the 68K RAM test"
assert bytes.fromhex("9f00ed7e") in VID[
    render_queue_install - 0x8000:render_queue_helpers_end - 0x8000
], "lazy queue installer no longer places the promoter at private $7E:ED00"
assert bytes.fromhex("e05202") in VID[
    render_queue_install - 0x8000:render_queue_helpers_end - 0x8000
], "lazy queue installer lost its pinned 594-byte copy bound"
assert bytes.fromhex("9f00f17f") not in VID, (
    "queue code must never overwrite live emulated 68000 RAM at $7F:F100"
)
assert obj_queue_prepare_stub == 0xAC00 and obj_tile_queue == 0xAC0C
assert VID[
    obj_queue_prepare_stub - 0x8000:obj_queue_prepare_stub - 0x8000 + 3
] == bytes(
    (
        0x4C,
        obj_queue_prepare_extended & 0xFF,
        (obj_queue_prepare_extended >> 8) & 0xFF,
    )
), (
    "OBJ queue preparation no longer redirects to the guarded helper"
)
assert obj_slot_fast_stub == 0xAD38 and obj_cache_preflight == 0xADE5
assert VID[
    obj_slot_fast_stub - 0x8000:obj_slot_fast_stub - 0x8000 + 4
] == bytes.fromhex("4c409cea"), (
    "fast OBJ lookup stub moved or lost its size-neutral widened-hash redirect"
)
assert obj_cache_reclaim_fast == 0xAEE5
assert obj_cache_reclaim_fast < obj_cache_reclaim_fast_end <= vid_obj_packed == 0xAF68
assert VID[
    obj_cache_reclaim_fast_end - 0x8000:vid_obj_packed - 0x8000
] == bytes(vid_obj_packed - obj_cache_reclaim_fast_end), (
    "OBJ reclaimer crossed the packed-renderer seam"
)
assert VID[0xAF61 - 0x8000:0xAF67 - 0x8000] == bytes.fromhex(
    "a9800085de60"
), "OBJ reclaimer lost its $0080 high-water publication or RTS tail"
assert vid_obj_packed < vid_obj_packed_end <= 0xB000
assert obj_oam_fast == 0xA4D5 and obj_oam_fast < obj_oam_fast_end <= 0xA570
assert VID[0xA4E3 - 0x8000:0xA4F7 - 0x8000] == bytes.fromhex(
    "2000a2" + "ea" * 17
), "fast OAM helper lost its size-neutral top-HUD Y-transform call"
assert VID[obj_oam_fast_end - 0x8000:0xA570 - 0x8000] == bytes(
    0xA570 - obj_oam_fast_end
), "fast OAM helper crossed its pinned tail helper"
# Poppy accepted `$7E0000+constant` in these long operands but emitted bank
# $7E offset $0000.  Require the literal persistent-cache addresses so a
# superficially green assembly cannot silently reinitialize or alias WRAM.
assert VID[obj_fast - 0x8000 + 3:obj_fast - 0x8000 + 7] == bytes.fromhex(
    "afc0897e"
), "fast OBJ renderer no longer reads the $7E:89C0 cache marker"
assert VID[
    obj_palette_cache_init - 0x8000:obj_palette_cache_init - 0x8000 + 4
] == bytes.fromhex("9f002c7e"), (
    "fast OBJ cache initialization no longer writes $7E:2C00,X"
)
assert VID[
    obj_palette_fill_cached - 0x8000 + 10:
    obj_palette_fill_cached - 0x8000 + 14
] == bytes.fromhex("bf002c7e"), (
    "OBJ palette cache no longer reads $7E:2C00,X"
)
assert VID[
    obj_cache_next_packed - 0x8000:obj_cache_next_packed - 0x8000 + 6
] == bytes.fromhex("9818690600a8"), (
    "packed OBJ cache preflight lost its audited six-byte manifest stride"
)
assert VID[
    obj_render_next_packed - 0x8000:obj_render_next_packed - 0x8000 + 8
] == bytes.fromhex("a5e01869060085e0"), (
    "packed OBJ renderer lost its audited six-byte manifest stride"
)
assert snapshot_dma_helpers < snapshot_dma_helpers_end <= bg_incremental == 0xA680
assert VID[snapshot_dma_helpers_end - 0x8000:bg_incremental - 0x8000] == bytes(
    bg_incremental - snapshot_dma_helpers_end
), "snapshot-DMA helpers crossed the incremental BG island"
assert bg_incremental < bg_incremental_end <= 0xA800
assert (
    bg_incremental
    < capture_bg_vscroll
    == 0xA7BC
    < capture_bg_vscroll_end
    == capture_bg_upper_snapshot
    < capture_bg_upper_direct
    < capture_bg_upper_primary
    < capture_bg_upper_secondary
    < capture_bg_upper_end
    == bg_dispatch_dynamic
    < bg_dispatch_dynamic_end
    == bg_incremental_end
    <= 0xA800
)
capture_vscroll_bytes = VID[
    capture_bg_vscroll - 0x8000:capture_bg_vscroll_end - 0x8000
]
assert capture_vscroll_bytes == bytes.fromhex(
    "08e220af093441ebaf813441186907c2202860"
), "vertical-scroll capture lost center-column selection, exact -1/+8 offset, or side effects"
assert VID.count(
    bytes((0x20, capture_bg_vscroll & 0xFF, capture_bg_vscroll >> 8))
) == 4, "all direct/queued/legacy snapshots must pack vertical scroll coherently"
for helper in (
    capture_bg_upper_snapshot,
    capture_bg_upper_direct,
    capture_bg_upper_primary,
    capture_bg_upper_secondary,
):
    assert VID.count(bytes((0x20, helper & 0xFF, helper >> 8))) == 1, (
        "each direct/queued/legacy snapshot must select one coherent X1 column-map destination"
    )
assert VID.count(bytes((0x20, bg_scroll & 0xFF, bg_scroll >> 8))) == 3, (
    "full, unchanged, and NMI cache-keepalive paths must each reapply the "
    "same accepted BG scroll helper"
)
assert VID.count(bytes((0x4C, bg_scroll & 0xFF, bg_scroll >> 8))) == 1, (
    "full, incremental, and unchanged BG paths must all publish vertical scroll"
)
assert VID[bg_incremental_end - 0x8000:bg_cache_extended - 0x8000] == bytes(
    bg_cache_extended - bg_incremental_end
), "incremental BG renderer crossed the fixed cache-reclamation island"
assert bg_cache_extended == 0xA800
assert bg_cache_extended < bg_cache_reclaim < bg_cache_reclaim_end <= 0xAA00
assert VID[bg_cache_reclaim_end - 0x8000:0xAA00 - 0x8000] == bytes(
    0xAA00 - bg_cache_reclaim_end
), "bounded BG cache reclaimer crossed the fixed $AA00 offset-table island"
assert bg_cache_extended_end <= 0xB000
assert VID[bg_cache_extended_end - 0x8000:queue_capture - 0x8000] == bytes(
    queue_capture - bg_cache_extended_end
), "bounded BG cache reclaimer crossed the queue-capture island"
assert queue_capture == 0xB000 and queue_capture < queue_capture_end <= 0xED00
assert VID[queue_capture - 0x8000:queue_capture - 0x8000 + 9] == bytes.fromhex(
    "08c230a5d048a5d448"
), "primary queue capture no longer preserves interrupted $D0/$D4 scratch"
assert VID[
    queue_capture_end - 0x8000:queue_capture_secondary - 0x8000
] == bytes(queue_capture_secondary - queue_capture_end), (
    "primary queue capture crossed the fixed secondary capture island"
)
assert queue_capture_secondary == 0xB140
assert (
    queue_capture_secondary
    < queue_capture_secondary_end
    <= title_bg_overlay
    == 0xB300
    < title_bg_overlay_end
    <= queue_promote
)
assert VID[
    queue_capture_secondary - 0x8000:queue_capture_secondary - 0x8000 + 9
] == bytes.fromhex("08c230a5d048a5d448"), (
    "secondary queue capture no longer preserves interrupted $D0/$D4 scratch"
)
assert VID[
    queue_capture_secondary_end - 0x8000:title_bg_overlay - 0x8000
] == bytes(title_bg_overlay - queue_capture_secondary_end), (
    "ROM-only secondary capture crossed the title BG2 island"
)
assert VID[
    title_bg_overlay_end - 0x8000:bg_write_cell - 0x8000
] == bytes(bg_write_cell - title_bg_overlay_end), (
    "title BG2 island crossed the dynamic-column renderer island"
)
assert (
    bg_write_cell
    == 0xB700
    < bg_write_cell_end
    <= bg_column_map_update
    < bg_column_map_update_end
    == bg_offset_table_build
    < bg_offset_table_build_end
    <= capture_bg_upper_full
    < capture_bg_upper_full_end
    <= bg_hscroll_full
    < bg_hscroll_full_end
    <= accept_bg_columns_snapshot
    < accept_bg_columns_snapshot_end
    <= accept_bg_columns_direct
    < accept_bg_columns_direct_end
    <= prepared_bg_map_remap
    < prepared_bg_map_remap_end
    <= queue_promote
)
bg_map_update_code = VID[
    bg_column_map_update - 0x8000:bg_column_map_update_end - 0x8000
]
assert bg_map_update_code[:13] == bytes.fromhex(
    "c230a20000bfe0897edff0897e"
), "BG layout dispatch no longer compares the physical maps first"
assert (
    bg_map_update_code[13] == 0xD0
    and bg_map_update_code[15:20] == bytes.fromhex("e8e8e01000")
    and bg_map_update_code[20] == 0xD0
    and bg_map_update_code[22:26] == bytes.fromhex("af96897e")
), "BG layout dispatch regained a kind-only full-rebuild path"
assert VID[
    bg_offset_table_build_end - 0x8000:capture_bg_upper_full - 0x8000
] == bytes(capture_bg_upper_full - bg_offset_table_build_end), (
    "dynamic-column table builder crossed the full control-capture helper"
)
assert VID[
    capture_bg_upper_full_end - 0x8000:bg_hscroll_full - 0x8000
] == bytes(bg_hscroll_full - capture_bg_upper_full_end), (
    "full control-capture helper crossed the horizontal-scroll helper"
)
assert VID[
    bg_hscroll_full_end - 0x8000:accept_bg_columns_snapshot - 0x8000
] == bytes(accept_bg_columns_snapshot - bg_hscroll_full_end), (
    "horizontal-scroll helper crossed the snapshot column-acceptor"
)
assert VID[
    accept_bg_columns_snapshot_end - 0x8000:accept_bg_columns_direct - 0x8000
] == bytes(accept_bg_columns_direct - accept_bg_columns_snapshot_end), (
    "snapshot column-acceptor crossed the direct-cache acceptor"
)
assert VID[
    accept_bg_columns_direct_end - 0x8000:prepared_bg_map_remap - 0x8000
] == bytes(prepared_bg_map_remap - accept_bg_columns_direct_end), (
    "column acceptor crossed the prepared-map remap island"
)
assert VID[
    prepared_bg_map_remap_end - 0x8000:queue_promote - 0x8000
] == bytes(queue_promote - prepared_bg_map_remap_end), (
    "prepared-map remap crossed the private-WRAM queue-promoter island"
)
assert VID[
    prepared_bg_map_remap - 0x8000:prepared_bg_map_remap - 0x8000 + 36
] == bytes.fromhex(
    "088bc2308f8e747ea5d048a5d248a5d448a5d648a5d848a5da48da5ae220"
    "a97e48abc220"
), "prepared-map remap lost its saved WRAM DBR before 16-bit-only scratch opcodes"
assert VID[
    prepared_bg_map_remap_end - 0x8000 - 3:
    prepared_bg_map_remap_end - 0x8000
] == bytes.fromhex("ab286b"), (
    "prepared-map remap no longer restores DBR/P before returning"
)
assert (
    VID[
        title_bg_upload - 0x8000:title_font_codes - 0x8000
    ].count(bytes.fromhex("a9408d0543a9058d0643"))
    == 1
), "title font DMA must upload blank tile plus all 41 glyphs ($0540 bytes)"
assert VID[
    title_font_codes - 0x8000:title_text_row14 - 0x8000
] == bytes.fromhex(
    "4142434445464748494a4b4c4d4e4f505152535455565758595a"
    "30313233343536373839402e2c2d26"
), "title BG2 font-code table changed; re-audit its map tile indices"
assert bytes.fromhex("a9618d0b21") in VID[
    bg_upload - 0x8000:bg_upload - 0x8000 + 0x80
], "BG upload no longer preserves the live title BG2 character base"
assert queue_promote == 0xED00 and queue_promote < queue_promote_end <= 0xF000
assert queue_promote_end - queue_promote == 0x0252, (
    "pinned lazy-installer size no longer matches the queue promoter"
)
assert queue_promote_end <= boot_screen_init == 0xF000
assert VID[
    queue_promote_end - 0x8000:boot_screen_init - 0x8000
] == bytes(boot_screen_init - queue_promote_end), (
    "private-WRAM queue promoter grew into the Mode 7 boot-screen island"
)
assert boot_screen_init < boot_screen_init_end == video_image_end <= 0x10000
assert len(VID) == video_image_end - 0x8000, (
    "unexpected video bytes follow the Mode 7 boot-screen helper"
)
assert bg_slot == 0x854E and bg_tile_dma == 0x859E, (
    "BG allocator stub moved an established renderer/supervisor address"
)
assert VID[bg_slot - 0x8000:bg_slot - 0x8000 + 3] == bytes.fromhex("4c00a8"), (
    "BG allocator entry no longer jumps to the mirrored $A800 reclaimer"
)
ROM[0x298000:0x298000+len(VID)] = VID                # @ $E9:8000 (file $298000); jsl/jml VID_*

# --- SA-1 ESCAPE BANK ---
# Native transpiled escapes too big for bank $00's free gaps live here. File $290000 is the
# 32KB gap between the gfx tile ROM (ends $290000) and the video subsystem ($298000). The SA-1's
# default MMC maps file $200000-$2FFFFF -> $80-$9F:8000-FFFF (Sa1.cpp), so file $290000 = SA-1
# $92:8000 (segment 2, bank $80 + ($90000/$8000=18) = $92). The interp dispatches here with
# `jml $92:8000`; escapes return `jml inext` and call bank-$00 leaf helpers via `jsl <h>_l`.
# escbank.pasm is assembled @ .org $8000, so escbank_entry ($8000) -> file $290000 = $92:8000.
import os as _os
import os.path as _osp

# The staged virtual-MC68000-cycle diagnostic uses two otherwise unused linear
# SA-1 ROM banks. $F1:0000 holds the source-authenticated 64 KiB CPU-000 static
# opcode-cycle baseline; $F2:8000 holds the code and one pack-time enable byte.
# Neither payload is an arcade-ROM redistribution. The diagnostic is opt-in and
# deliberately incompatible with PC_RING, whose restored dbg_fetch body bypasses
# the timing gateway.
vtime_enabled = _os.environ.get("VTIME", "0") == "1"
vtime_interpreter_only = _os.environ.get("VTIME_INTERPRETER_ONLY", "0") == "1"
vtime_0818_interpreter_fallback = (
    _os.environ.get("VTIME_0818_INTERPRETER_FALLBACK", "0") == "1"
)
if vtime_interpreter_only and not vtime_enabled:
    raise AssertionError("VTIME_INTERPRETER_ONLY=1 requires VTIME=1")
if vtime_0818_interpreter_fallback and not vtime_interpreter_only:
    raise AssertionError(
        "VTIME_0818_INTERPRETER_FALLBACK=1 requires "
        "VTIME_INTERPRETER_ONLY=1"
    )
if vtime_enabled and _os.environ.get("PC_RING", "0") == "1":
    raise AssertionError("VTIME=1 and PC_RING=1 are mutually exclusive diagnostic modes")
VTIME_TABLE = Path("src/m68k_cpu000_static_cycles.bin")
VTIME_CODE = Path("src/vtime.bin")
VTIME_SYMS = Path("src/vtime.sym")
VTIME_ESC5_ROOT = Path("src/vtime_esc5_root.bin")
VTIME_ESC5_ROOT_SYMS = Path("src/vtime_esc5_root.sym")
if not all(path.is_file() for path in (
    VTIME_TABLE,
    VTIME_CODE,
    VTIME_SYMS,
    VTIME_ESC5_ROOT,
    VTIME_ESC5_ROOT_SYMS,
)):
    raise AssertionError("virtual-cycle payload missing; generate table and assemble src/vtime.pasm")
vtime_table = VTIME_TABLE.read_bytes()
assert len(vtime_table) == 0x10000
assert hashlib.sha256(vtime_table).hexdigest() == (
    "201cf148abf22ef763a55c6c086cc0eade0afb1f7185727d086f7b00a814914b"
), "MAME CPU-000 static-cycle baseline changed; re-run its source-authenticated generator"
vtime_code = VTIME_CODE.read_bytes()
assert len(vtime_code) <= 0x8000
vtime_symbols = VTIME_SYMS.read_text(encoding="utf-8-sig")
vtime_esc5_root = VTIME_ESC5_ROOT.read_bytes()
vtime_esc5_root_symbols = VTIME_ESC5_ROOT_SYMS.read_text(encoding="utf-8-sig")


def vtime_off(symbol):
    for line in vtime_symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError("missing virtual-timer layout symbol %s" % symbol)


def vtime_esc5_root_off(symbol):
    for line in vtime_esc5_root_symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError("missing VTIME $02429C root layout symbol %s" % symbol)


assert (
    vtime_off("vtime_enable_byte") == 0x8000
    and vtime_off("vtime_prepare_gateway") == 0x8001
    and vtime_off("vtime_consume") == 0x8400
    and vtime_off("vtime_reload") == 0x8500
    and vtime_off("vtime_load_next_deadline_end") <= 0x85A0
    and vtime_off("vtime_irq_enter") == 0x85A0
    and vtime_off("vtime_irq_enter_end") <= 0x8600
    and vtime_off("vtime_esc3_charge") == 0x8600
    and vtime_off("vtime_esc3_reset") == 0x8800
    and vtime_off("vtime_esc3_finish") == 0x8820
    and vtime_off("vtime_esc5_charge") == 0x8900
    and vtime_off("vtime_esc5_finish") == 0x8B00
    and vtime_off("vtime_esc5_charge_cost") == 0x8C00
    and vtime_off("vtime_esc5_charge_pc") == 0x8C40
    and vtime_off("vtime_esc5_charge_terminal") == 0x8C90
    and vtime_off("vtime_esc5_metadata_end") == 0x8CD6
    and vtime_off("vtime_esc3_charge_index") == 0x9000
    and vtime_off("vtime_esc3_charge_cost") == 0xAC00
    and vtime_off("vtime_esc3_charge_pc") == 0xAD00
    and vtime_off("vtime_esc3_charge_terminal") == 0xAF00
    and vtime_off("vtime_esc9_charge") == 0xB100
    and vtime_off("vtime_esc9_finish") == 0xB300
    and vtime_off("vtime_paced_release") == 0xB400
    and vtime_off("vtime_choke_gateway") == 0xB480
    and vtime_off("vtime_mvc_gateway") == 0xB4D1
    and vtime_off("vtime_mvc_gateway_end") <= 0xB500
    and vtime_off("vtime_dynamic_charge") == 0xB500
    and vtime_off("vtime_dynamic_helpers_end") <= 0xB740
    and vtime_off("vtime_input_p1_delayed") == 0xB740
    and vtime_off("vtime_input_p1_delayed_end") <= 0xBA00
    and vtime_off("vtime_esc9_charge_index") == 0xBA00
    and vtime_off("vtime_esc9_charge_cost") == 0xFC80
    and vtime_off("vtime_esc9_charge_pc") == 0xFCD3
    and vtime_off("vtime_esc9_charge_terminal") == 0xFD80
    and vtime_off("vtime_native_handoff_to_interpreter") == 0xFE40
    and vtime_off("vtime_native_handoff_to_interpreter_end")
    == vtime_off("vtime_image_end")
    and 0xFE40 < vtime_off("vtime_image_end") <= 0xFF00
), "virtual-timer callable layout moved; update the packed bank-$00 seams deliberately"
if vtime_enabled:
    assert (
        vtime_off("vtime_clock_ensure") == 0x8200
        and vtime_off("vtime_clock_finish_interval") < 0x8400
        and vtime_off("vtime_clock_current_phase") < 0x8400
        and vtime_off("vtime_clock_load_next_deadline") < 0x8400
        and vtime_off("vtime_input_p1_delayed_end")
        > vtime_off("vtime_input_p1_delayed")
    ), "VTIME CPU-phase helpers escaped their fixed bank-$F2 island"
assert vtime_code[0] == 0 and len(vtime_code) >= vtime_off("vtime_image_end") - 0x8000, (
    "virtual timer native-block metadata/handoff was not assembled through its audited end"
)
assert (
    vtime_esc5_root_off("vtime_entry_2429c") == 0x8000
    and vtime_esc5_root_off("vtime_esc5_charge_gateway") < 0x8980
    and vtime_esc5_root_off("vtime_esc5_return_dispatch") < 0x8A00
    and vtime_esc5_root_off("vtime_esc5_return_dispatch_end")
    == vtime_esc5_root_off("vtime_esc5_root_end")
    and len(vtime_esc5_root)
    == vtime_esc5_root_off("vtime_esc5_root_end") - 0x8000
    and len(vtime_esc5_root) <= 0x1000
), "VTIME `$02429C` root or exact-return dispatcher escaped its bank-$F3 island"
ROM[0x310000:0x320000] = vtime_table                # SA-1 $F1:0000-$FFFF
vtime_packed = bytearray(vtime_code)
vtime_esc5_payload_start = vtime_off("vtime_esc5_charge") - 0x8000
vtime_esc5_payload_end = vtime_off("vtime_esc5_metadata_end") - 0x8000
vtime_mvc_payload_start = vtime_off("vtime_mvc_gateway") - 0x8000
vtime_mvc_payload_end = vtime_off("vtime_mvc_gateway_end") - 0x8000
if not vtime_enabled:
    # This range was an all-zero diagnostic gap in the accepted production
    # image.  Keep ordinary ROM bytes/hash unchanged while still assembling
    # and auditing the opt-in root ledger on every build.
    vtime_packed[vtime_esc5_payload_start:vtime_esc5_payload_end] = bytes(
        vtime_esc5_payload_end - vtime_esc5_payload_start
    )
    # This island was zero in the accepted ordinary image. Keep the new
    # diagnostic-only MOVE-collapse gateway out of the production hash too.
    vtime_packed[vtime_mvc_payload_start:vtime_mvc_payload_end] = bytes(
        vtime_mvc_payload_end - vtime_mvc_payload_start
    )
ROM[0x328000:0x328000 + len(vtime_packed)] = vtime_packed  # SA-1 $F2:8000+

# The ordinary input mailbox is published only while `$410122` proves the SA-1
# video shadow quiescent. VTIME can begin another emulated gameplay interval
# before the scheduler returns to `$0818`; its P1 bridge therefore holds the
# latest NMI-completed sample for one virtual tick while preserving any real
# `$0818` mailbox publication. Patch only diagnostic ROMs: production keeps the
# historical sampler RTS and bank-$00 input bytes exactly, with no extra
# NMI/BW-RAM traffic.
vtime_input_video_start = pacing_vtime_publish_tail - 0x8000
vtime_input_video_end = pacing_helpers_end - 0x8000
vtime_input_video_file = 0x298000 + vtime_input_video_start
vtime_input_video_source = VID[vtime_input_video_start:vtime_input_video_end]
assert bytes(ROM[
    vtime_input_video_file:vtime_input_video_file + len(vtime_input_video_source)
]) == vtime_input_video_source, "packed VTIME input publisher differs from video.bin"
if not vtime_enabled:
    ROM[
        vtime_input_video_file:vtime_input_video_file + len(vtime_input_video_source)
    ] = b"\x60" + bytes(len(vtime_input_video_source) - 1)

joy_read = interp_symbol("joy_read")
joy_read_original = bytes.fromhex("08c230af00004185662860")
actual = bytes(ROM[joy_read:joy_read + len(joy_read_original)])
assert actual == joy_read_original, (
    "bank-$00 joy_read seam moved at file $%06X: expected %s, got %s"
    % (joy_read, joy_read_original.hex(), actual.hex())
)

input_p1 = interp_symbol("input_p1")
input_p1_original = bytes.fromhex("2056f8c230")
input_p1_vtime = bytes.fromhex("2240b7f2ea")
assert len(input_p1_original) == len(input_p1_vtime) == 5
actual = bytes(ROM[input_p1:input_p1 + len(input_p1_original)])
assert actual == input_p1_original, (
    "bank-$00 input_p1 seam moved at file $%06X: expected %s, got %s"
    % (input_p1, input_p1_original.hex(), actual.hex())
)
if vtime_enabled:
    ROM[input_p1:input_p1 + len(input_p1_vtime)] = input_p1_vtime

if vtime_enabled:
    # Bit 1 is an explicit interpreter-only correctness probe. It is never
    # packed into an ordinary image: the virtual clock first waits for the
    # established task-context gate, then turns off the existing global
    # gameplay-native and scheduler dispatch gates so unowned accelerated
    # spans fall back to the per-fetch dynamic clock.
    vtime_mode = 0x01
    if vtime_interpreter_only:
        vtime_mode |= 0x02
    if vtime_0818_interpreter_fallback:
        vtime_mode |= 0x04
    ROM[0x328000] = vtime_mode
    vtime_esc5_root_file = 0x338000                 # SA-1 $F3:8000+
    assert ROM[
        vtime_esc5_root_file:vtime_esc5_root_file + len(vtime_esc5_root)
    ] == bytes(len(vtime_esc5_root)), (
        "VTIME `$02429C` root would overwrite nonzero bank-$F3 data"
    )
    ROM[
        vtime_esc5_root_file:vtime_esc5_root_file + len(vtime_esc5_root)
    ] = vtime_esc5_root
print(
    "Virtual cycle timer: %s"
    % (
        "enabled interpreter-only diagnostic"
        if vtime_interpreter_only
        else ("enabled diagnostic" if vtime_enabled else "disabled")
    )
)

if _osp.exists("src/escbank.bin"):
    ESC = Path("src/escbank.bin").read_bytes()
    assert len(ESC) <= 0x8000, ("escape bank %d bytes overflows the $290000..$298000 gap" % len(ESC))
    esc_symbols = Path("src/escbank.sym").read_text()
    assert (
        "00:F042 jx_b0" in esc_symbols
        and "00:F0C4 jx_real" in esc_symbols
        and "00:F18F entry_d226" in esc_symbols
    ), (
        "bank-$92 jsr.l extension scan grew into the flowing entry_d226 body; "
        "relocate code instead of relying on Poppy's permissive .org overlap"
    )
    assert ESC[0x7042:0x7046] == bytes.fromhex("5c00fb9d"), (
        "bank-$92 jx_b0 no longer forwards to the fixed $9D:FB00 scan"
    )
    # The archived pre-extension bank begins its retained flowing body at
    # $F0CB.  Keep the remaining two-byte seam explicit: Poppy permits .org
    # overlap, so losing either byte means this extension has reached live
    # code even if assembly still succeeds.
    assert ESC[0x70C9:0x70CB] == bytes(2), (
        "bank-$92 jsr.l extension consumed the final zero seam before the "
        "retained flowing body"
    )
    def esc_off(symbol):
        for line in esc_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank layout symbol %s" % symbol)

    entry_swo = esc_off("entry_swo")
    entry_swo_vtime_go = esc_off("entry_swo_vtime_go")
    swo_movem = esc_off("swo_movem")
    swo_movem_done = esc_off("swo_movem_done")
    assert (
        entry_swo == 0xFA00
        and entry_swo_vtime_go == 0xFA0F
        and swo_movem == 0xFA1F
        and swo_movem_done == 0xFA32
    ), "native scheduler switch-out or its fixed $FA32 continuation moved"
    assert ESC[0x7A00:0x7A0F] == bytes.fromhex(
        "c230af0080f2290200f0045cc0f500"
    ), "native scheduler switch-out lost its interpreter-only pre-mutation fallback"
    assert ESC[0x7A23:0x7A32] == bytes(0x0F), (
        "native scheduler switch-out consumed the zero seam before $92:FA32"
    )

    lhs_sel = esc_off("lhs_sel")
    lhs_sel_end = esc_off("lhs_sel_end")
    assert lhs_sel == 0xFD00 and lhs_sel < lhs_sel_end <= 0xFE00, (
        "native scheduler selector moved or crossed the fixed $92:FE00 seam"
    )
    assert ESC[lhs_sel_end - 0x8000:0x7E00] == bytes(
        0xFE00 - lhs_sel_end
    ), "native scheduler selector consumed the zero seam before entry_d522@$92:FE00"

    entry_d3b0 = esc_off("entry_d3b0")
    entry_d226 = esc_off("entry_d226")
    assert entry_d3b0 == 0xEFFB and entry_d226 == 0xF18F, (
        "$D3B0 trampoline or following $D226 handler moved in bank $92"
    )
    assert ESC[entry_d3b0 - 0x8000:0x7000] == bytes.fromhex(
        "5c00b49400"
    ), (
        "$D3B0 charged-shot trampoline was overwritten before jah2_ext@$92:F000"
    )
    assert ESC[0x7000:0x7003] == bytes.fromhex("ad1a07"), (
        "jah2_ext lost its fixed $92:F000 entry after the $D3B0 relocation"
    )
    assert ESC[entry_d226 - 0x8000:entry_d226 - 0x8000 + 2] == bytes.fromhex(
        "c230"
    ), "$D226 handler lost its fixed REP #$30 prologue"
    jah2_ext_bsr = esc_off("jah2_ext_bsr")
    jxb_b2 = esc_off("jxb_b2")
    jxb_push_return = esc_off("jxb_push_return")
    jxb_real = esc_off("jxb_real")
    entry_d6b0 = esc_off("entry_d6b0")
    assert (
        jah2_ext_bsr == 0xF400
        and jah2_ext_bsr < jxb_b2 < jxb_push_return < jxb_real
        and jxb_real == 0xF5F8
        and jxb_real + 8 == entry_d6b0 == 0xF600
    ), "bank-$01/$02 BSR scan moved or overflowed the fixed $92:F400-$F5FF island"
    assert ESC[
        jxb_real + 8 - 0x8000:entry_d6b0 - 0x8000
    ] == bytes(entry_d6b0 - (jxb_real + 8)), (
        "bank-$01/$02 BSR scan consumed the zero seam before entry_d6b0@$92:F600"
    )
    for encoded, label in (
        (bytes.fromhex("5c00e09f"), "$013282 -> $9F:E000"),
        (bytes.fromhex("5c20db94"), "$0135E0 -> $94:DB20"),
        (bytes.fromhex("5c00fd9f"), "bank-$01 player-hot scan -> $9F:FD00"),
        (bytes.fromhex("5cb0fd9f"), "bank-$02 Stage-3 scan -> $9F:FDB0"),
    ):
        assert ESC[0x7400:0x7600].count(encoded) == 1, (
            "Stage-3 BSR scan lost its sole target " + label
        )

    entry_fb8 = esc_off("entry_fb8")
    entry_fb8_end = esc_off("entry_fb8_end")
    gm_memset = esc_off("gm_memset")
    assert entry_fb8 == 0x86E7 and entry_fb8 < entry_fb8_end <= gm_memset == 0x8869, (
        "$0FB8 fixed-offset rewrite moved or crossed the pinned gm_memset seam"
    )
    assert ESC[entry_fb8_end - 0x8000:gm_memset - 0x8000] == bytes(
        gm_memset - entry_fb8_end
    ), "$0FB8 rewrite has nonzero overlap before gm_memset@$92:8869"
    ce58_cd1a_jump = esc_off("entry_ce58_cd1a_jump")
    assert ESC[ce58_cd1a_jump - 0x8000:ce58_cd1a_jump - 0x8000 + 4] == bytes.fromhex(
        "5c00e09d"
    ), "$CE58->$CD1A guarded fusion no longer jumps to pinned $9D:E000"

    # $00D18A's cleanup originally flowed into the fixed $AEFA entry_2e06
    # .org.  Poppy accepts that overlap and the resulting native routine
    # entered $2E06 with a corrupted virtual register/return frame.  Pin the
    # explicit redirect and the relocated $F26B island so future growth fails
    # loudly before it can recreate an invisible overlap.
    d18a_cleanup = esc_off("Ld18a_d1fc")
    d18a_tail_full = esc_off("d18a_tail_full")
    d18a_tail_full_end = esc_off("d18a_tail_full_end")
    entry_2e06 = esc_off("entry_2e06")
    assert (
        d18a_cleanup == 0xAE00
        and d18a_tail_full == 0xF26B
        and d18a_tail_full < d18a_tail_full_end <= 0xF400
        and entry_2e06 == 0xAEFA
    ), "$D18A cleanup relocation moved or crossed its fixed bank-$92 seams"
    assert ESC[d18a_cleanup - 0x8000:d18a_cleanup - 0x8000 + 4] == (
        bytes([0x5C]) + d18a_tail_full.to_bytes(2, "little") + bytes([0x92])
    ), "$D18A cleanup no longer redirects away from the $AEFA overlap"
    assert ESC[d18a_tail_full_end - 0x8000:0x7400] == bytes(
        0xF400 - d18a_tail_full_end
    ), "$D18A cleanup grew into the fixed $92:F400 JAH2 entry"

    ibridge = esc_off("ibridge")
    ib_b0 = esc_off("ib_b0")
    ib_n4 = esc_off("ib_n4")
    ibridge_end = esc_off("ibridge_end")
    assert ibridge == 0xF828 and ibridge_end <= 0xF900, (
        "bank-$92 indirect bridge moved or crossed the fixed $F900 dispatcher"
    )
    assert (
        ibridge < ib_b0 < ib_n4 < ibridge_end
        and ESC[ibridge - 0x8000:ibridge_end - 0x8000].count(
            bytes.fromhex("5c80a69f")
        )
        == 1
        and ESC[ibridge - 0x8000:ibridge_end - 0x8000].count(
            bytes.fromhex("5c00d09f")
        )
        == 1
    ), "$02F2E0 indirect callback lost its sole $9F:A680 bridge route"
    entry_20e8 = interp_symbol("entry_20e8")
    assert ESC[ib_n4 - 0x8000:ib_n4 - 0x8000 + 9] == (
        bytes.fromhex("c9e820d0045c")
        + entry_20e8.to_bytes(2, "little")
        + bytes([0x00])
    ), "$20E8 indirect-call arm no longer crosses explicitly into bank $00"
    assert ESC[ibridge_end - 0x8000:0x7900] == bytes(0xF900 - ibridge_end), (
        "bank-$92 indirect bridge grew into the fixed $F900 dispatcher"
    )

    h8_block_loop = esc_off("h8_block_loop")
    assert h8_block_loop == 0xB39C
    assert ESC[h8_block_loop - 0x8000:h8_block_loop - 0x8000 + 6] == bytes.fromhex(
        "5c80e19e9005"
    ), "$8C2 zero-mask shortcut lost its size-neutral JML/BCC seam"
    br3a92_1 = esc_off("br3a92_1")
    assert ESC[0x5C2B:0x5C30] == (
        bytes([0xA9])
        + br3a92_1.to_bytes(2, "little")
        + bytes.fromhex("8540")
    ), (
        "$3A92->$2BDA callable bridge changed in tightly packed bank $92"
    )
    br3a92_8 = esc_off("br3a92_8")
    br3a92_9 = esc_off("br3a92_9")
    assert br3a92_8 == 0xDF55, "$3A92->$26A0 callsite moved"
    assert ESC[br3a92_8 - 0x8000:br3a92_8 - 0x8000 + 5] == (
        bytes([0xA9])
        + br3a92_9.to_bytes(2, "little")
        + bytes.fromhex("8540")
    ), (
        "$3A92->$26A0 callable bridge changed in tightly packed bank $92"
    )
    h26_range_ok = esc_off("h26_range_ok")
    h26_mask_resume = esc_off("h26_mask_generated_resume")
    assert h26_range_ok == 0x8F19 and h26_mask_resume == h26_range_ok + 5, (
        "$26A0 internal unrolled seam moved in tightly packed bank $92"
    )
    assert ESC[h26_range_ok - 0x8000:h26_mask_resume - 0x8000] == bytes.fromhex(
        "5c00989dea"
    ), (
        "$26A0 internal seam lost its size-neutral JML/NOP redirect"
    )
    entry_17b4 = esc_off("entry_17b4")
    entry_17b4_resume = esc_off("entry_17b4_generated_resume")
    assert entry_17b4 == 0xBA85 and entry_17b4_resume == 0xBA89, (
        "$17B4 redirect/resume moved in tightly packed bank $92"
    )
    assert ESC[entry_17b4 - 0x8000:entry_17b4_resume - 0x8000] == bytes.fromhex(
        "5c009b95"
    ), "entry_17b4 lost its size-neutral JML $95:9B00 wrapper"
    entry_2bda = esc_off("entry_2bda")
    entry_2bda_resume = esc_off("entry_2bda_generated_resume")
    assert entry_2bda == 0xB730 and entry_2bda_resume == 0xB734, (
        "$2BDA redirect/resume moved in tightly packed bank $92"
    )
    assert ESC[entry_2bda - 0x8000:entry_2bda_resume - 0x8000] == bytes.fromhex(
        "5c00aa9d"
    ), "entry_2bda lost its size-neutral JML $9D:AA00 wrapper"
    entry_2be2 = esc_off("entry_2be2")
    entry_2be2_resume = esc_off("entry_2be2_generated_resume")
    assert entry_2be2 == 0xB794 and entry_2be2_resume == 0xB798, (
        "$2BE2 redirect/resume moved in tightly packed bank $92"
    )
    assert ESC[entry_2be2 - 0x8000:entry_2be2_resume - 0x8000] == bytes.fromhex(
        "5c20969d"
    ), "entry_2be2 lost its size-neutral JML $9D:9620 wrapper"
    entry_3c36 = esc_off("entry_3c36")
    entry_3c36_resume = esc_off("entry_3c36_generated_resume")
    assert entry_3c36 == 0xD02A and entry_3c36_resume == 0xD02E, (
        "$3C36 redirect/resume moved in tightly packed bank $92"
    )
    assert ESC[entry_3c36 - 0x8000:entry_3c36_resume - 0x8000] == bytes.fromhex(
        "5c00a89d"
    ), "entry_3c36 lost its size-neutral JML $9D:A800 wrapper"
    ROM[0x290000:0x290000+len(ESC)] = ESC            # @ SA-1 $92:8000 (file $290000)

# --- SECOND SA-1 ESCAPE BANK ($94:8000, file $2A0000) ---
# The $92 bank's bodies region filled to $F000 (jah2 dispatch chains). file $2A0000 is free (after
# VID at $298000-$2A0000) and the SA-1 MMC maps it to $94:8000 (file $200000-$2FFFFF -> $80-$9F;
# ($A0000/$8000=20)+$80=$94). Confirmed by a live marker read. escbank2.pasm is .org $8000, so
# escbank2 $8000 -> file $2A0000 -> $94:8000. $92 dispatchers `jml entry_X` into it.
if _osp.exists("src/escbank2.bin"):
    ESC2 = Path("src/escbank2.bin").read_bytes()
    assert len(ESC2) <= 0x8000, ("escbank2 %d bytes overflows the $2A0000..$2A8000 bank" % len(ESC2))
    esc2_symbols = Path("src/escbank2.sym").read_text()
    def esc2_off(symbol):
        for line in esc2_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank2 layout symbol %s" % symbol)

    entry_8fat = esc2_off("entry_8fat")
    entry_8fat_resume = esc2_off("h8fa_generated_resume")
    entry_8fat_body = esc2_off("h8fa_generated_body")
    assert entry_8fat == 0xAD98 and entry_8fat_resume == 0xAD9E, (
        "$08FA redirect/resume moved in bank $94"
    )
    assert entry_8fat_body == 0xADA3, "$08FA generated body moved from $94:ADA3"
    assert ESC2[entry_8fat - 0x8000:entry_8fat_resume - 0x8000] == bytes.fromhex(
        "5c009d95eaea"
    ), "entry_8fat lost its size-neutral JML $95:9D00 wrapper"
    assert ESC2[entry_8fat_body - 0x8000:entry_8fat_body - 0x8000 + 2] == bytes.fromhex(
        "a538"
    ), "$08FA generated-body seam no longer begins with LDA $38"
    c172_flow_end = esc2_off("escbank2_flowing_end")
    d3f6_move_nz = esc2_off("d3f6_readbyte_move_nz")
    d3f6_move_nz_end = esc2_off("d3f6_readbyte_move_nz_end")
    entry_d3b0t = esc2_off("entry_d3b0t")
    entry_d3b0t_bridge_end = esc2_off("entry_d3b0t_bridge_end")
    brd3b0_1t = esc2_off("brd3b0_1t")
    entry_d3b0t_end = esc2_off("entry_d3b0t_end")
    entry_27952 = esc2_off("entry_27952")
    entry_27952_end = esc2_off("entry_27952_end")
    entry_279d2 = esc2_off("entry_279d2")
    entry_279d2_end = esc2_off("entry_279d2_end")
    entry_2f3ba = esc2_off("entry_2f3ba")
    entry_2f3ba_end = esc2_off("entry_2f3ba_end")
    entry_27b44 = esc2_off("entry_27b44")
    entry_27b44_end = esc2_off("entry_27b44_end")
    entry_2f56a = esc2_off("entry_2f56a")
    entry_2f56a_end = esc2_off("entry_2f56a_end")
    entry_27b7c = esc2_off("entry_27b7c")
    entry_27b7c_end = esc2_off("entry_27b7c_end")
    entry_2f5a2 = esc2_off("entry_2f5a2")
    entry_2f5a2_end = esc2_off("entry_2f5a2_end")
    entry_2e49c = esc2_off("entry_2e49c")
    entry_2e49c_end = esc2_off("entry_2e49c_end")
    entry_296c6 = esc2_off("entry_296c6")
    entry_296c6_end = esc2_off("entry_296c6_end")
    entry_2e40e = esc2_off("entry_2e40e")
    entry_2e40e_end = esc2_off("entry_2e40e_end")
    entry_135e0 = esc2_off("entry_135e0")
    h135e0_direct = esc2_off("h135e0_direct")
    entry_135e0_end = esc2_off("entry_135e0_end")
    xd_sparse_direct = esc2_off("xd_sparse_direct")
    xlat_choke = esc2_off("xlat_choke")
    xlat_choke_end = esc2_off("xlat_choke_end")
    hce4_leaf_residue = esc2_off("hce4_leaf_residue")
    hce4_entry = esc2_off("hce4_entry")
    hce4_counter = esc2_off("hce4_counter")
    hce4_shape_dispatch = esc2_off("hce4_shape_dispatch")
    hce4_hot_done = esc2_off("hce4_hot_done")
    hce4_ac_charge_exact = esc2_off("hce4_ac_charge_exact")
    hce4_ac_charge_dispatch = esc2_off("hce4_ac_charge_dispatch")
    hce4_ac_charge_fast_return = esc2_off(
        "hce4_ac_charge_fast_return"
    )
    hce4_leaf_residue_end = esc2_off("hce4_leaf_residue_end")
    c172_optional = esc2_off("hc172_optional_hot")
    c172_optional_end = esc2_off("hc172_optional_hot_end")
    assert (
        c172_flow_end <= d3f6_move_nz == 0xB3E0
        and d3f6_move_nz_end == 0xB3E4
        and d3f6_move_nz_end <= entry_d3b0t == 0xB400
    ), (
        "escbank2 flowing bodies crossed the fixed $B400 D3B0 relocation island"
    )
    assert ESC2[
        d3f6_move_nz - 0x8000:d3f6_move_nz_end - 0x8000
    ] == bytes.fromhex("5c709f95"), (
        "$D3F6 MOVE.B byte-N/Z helper changed"
    )
    assert (
        entry_d3b0t < entry_d3b0t_bridge_end <= brd3b0_1t == 0xB580
        and brd3b0_1t < entry_d3b0t_end <= 0xD800
    ), (
        "$D3B0 relocation crossed its continuation or the fixed $D800 C172 island"
    )
    assert (
        entry_27952 == 0xB600
        and entry_27952 < entry_27952_end <= 0xBC00
        and entry_279d2 == 0xBC00
        and entry_279d2 < entry_279d2_end <= 0xC200
        and entry_2f3ba == 0xC200
        and entry_2f3ba < entry_2f3ba_end <= 0xCA00
    ), "Stage-3 hot bodies moved or overflowed their fixed bank-$94 islands"
    assert (
        hce4_leaf_residue == 0xCA00
        and hce4_ac_charge_exact == 0xCA30
        and hce4_ac_charge_dispatch == 0xCB37
        and hce4_ac_charge_fast_return == 0xCB3B
        and hce4_leaf_residue < hce4_leaf_residue_end <= 0xCB40
    ), "$CE4 jsr(An)-to-semantic bridge moved or overflowed $94:CA00-$CB3F"
    assert (
        hce4_entry == 0xFA00
        and hce4_counter == 0xFB24
        and hce4_counter < hce4_shape_dispatch < hce4_hot_done < 0xFE00
    ), "$CE4 semantic body or fused route moved without pack review"
    ce4_stack_image = ESC2[
        hce4_counter - 0x8000:hce4_shape_dispatch - 0x8000
    ]
    assert ce4_stack_image.count(bytes.fromhex("9f000040")) == 19, (
        "$CE4 lost a mapped-BW-RAM LINK/MOVEM stack-image store"
    )
    ce4_fused_route = ESC2[
        hce4_shape_dispatch - 0x8000 - 11:
        hce4_shape_dispatch - 0x8000
    ]
    assert (
        ce4_fused_route[:9] == bytes.fromhex("a56af0072200d29f4c")
        and int.from_bytes(ce4_fused_route[9:], "little") == hce4_hot_done
    ), (
        "$CE4 fused 2x2 route lost its marker guard, direct emitter, or epilogue"
    )
    assert (
        entry_27b44 == 0xCB40
        and entry_27b44 < entry_27b44_end <= 0xCD00
        and entry_2f56a == 0xCD00
        and entry_2f56a < entry_2f56a_end <= 0xCEC0
        and entry_27b7c == 0xCEC0
        and entry_27b7c < entry_27b7c_end <= 0xD100
        and entry_2f5a2 == 0xD100
        and entry_2f5a2 < entry_2f5a2_end <= 0xD340
        and entry_2e49c == 0xD340
        and entry_2e49c < entry_2e49c_end <= 0xD480
        and entry_296c6 == 0xD480
        and entry_296c6 < entry_296c6_end <= 0xD600
        and entry_2e40e == 0xD540
        and entry_2e40e < entry_2e40e_end <= 0xD700
    ), "Stage-3 output leaves moved or overflowed their fixed bank-$94 islands"
    assert IMG[0x2E49C:0x2E4B8] == bytes.fromhex(
        "4280302c000a41fa022ce54820700800302c000ce548207008004e75"
    ), "$02E49C nine-instruction arcade lookup oracle changed"
    assert hashlib.sha256(IMG[0x2E6D0:0x2E71C]).hexdigest() == (
        "3caefa452d92bce123523a84548a941fa7e57b3d838e6ff3a4535269b39fa708"
    ), "$02E49C nineteen-entry immutable first table changed"
    e49c_table_bases = [
        int.from_bytes(IMG[offset:offset + 4], "big")
        for offset in range(0x2E6D0, 0x2E71C, 4)
    ]
    assert len(e49c_table_bases) == 19 and all(
        base % 4 == 0 and base + 0xFFFF < len(IMG)
        for base in e49c_table_bases
    ), (
        "$02E49C admitted table no longer keeps every shifted-word lookup "
        "aligned, non-crossing, and inside the authenticated 512 KiB image"
    )
    assert entry_2e49c_end == 0xD425, (
        "$02E49C hand-exact body changed size; re-audit guards and CCR/X/RTS"
    )
    assert hashlib.sha256(
        ESC2[entry_2e49c - 0x8000:entry_2e49c_end - 0x8000]
    ).hexdigest() == (
        "24a383a57947dc2a735c8b2ee9270dedb414c2ac6e1586789e7ec1a3e64ce9c7"
    ), "$02E49C hand-exact body bytes changed without differential review"
    h8_mark_palette_dirty = esc2_off("h8_mark_palette_dirty")
    h8_mark_palette_dirty_end = esc2_off("h8_mark_palette_dirty_end")
    assert c172_optional == 0xD800 and c172_optional_end <= 0xDB00, (
        "$C172 optional-callback helper crossed its fixed $94:D800-$DAFF island"
    )
    assert h8_mark_palette_dirty == 0xDB00 and h8_mark_palette_dirty_end <= 0xDB20, (
        "$8C2 renderer-palette dirty helper moved outside its fixed $94:DB00 island"
    )
    assert (
        entry_135e0 == 0xDB20
        and entry_135e0 < h135e0_direct < entry_135e0_end <= 0xE000
    ), (
        "$0135E0 coordinate leaf/direct ABI moved or crossed the fixed "
        "$94:E000 HLE island"
    )
    assert ESC2[
        h135e0_direct - 0x8000:h135e0_direct - 0x8000 + 2
    ] == bytes.fromhex("c230"), (
        "$0135E0 direct ABI lost its explicit REP #$30 prologue"
    )
    for seam_start, seam_end, label in (
        (c172_flow_end, d3f6_move_nz, "flowing bodies -> $D3F6 N/Z helper"),
        (d3f6_move_nz_end, entry_d3b0t, "$D3F6 N/Z helper -> $D3B0"),
        (entry_d3b0t_bridge_end, brd3b0_1t, "$D3B0 bridge -> continuation"),
        (entry_d3b0t_end, entry_27952, "$D3B0 continuation -> $027952"),
        (entry_27952_end, entry_279d2, "$027952 -> $0279D2"),
        (entry_279d2_end, entry_2f3ba, "$0279D2 -> $02F3BA"),
        (entry_2f3ba_end, hce4_leaf_residue, "$02F3BA -> $CE4 bridge"),
        (hce4_leaf_residue_end, entry_27b44, "$CE4 bridge -> $027B44"),
        (entry_27b44_end, entry_2f56a, "$027B44 -> $02F56A"),
        (entry_2f56a_end, entry_27b7c, "$02F56A -> $027B7C"),
        (entry_27b7c_end, entry_2f5a2, "$027B7C -> $02F5A2"),
        (entry_2f5a2_end, entry_2e49c, "$02F5A2 -> $02E49C"),
        (entry_2e49c_end, entry_296c6, "$02E49C -> $0296C6"),
        (entry_296c6_end, entry_2e40e, "$0296C6 -> $02E40E"),
        (entry_2e40e_end, c172_optional, "$02E40E -> $C172"),
        (c172_optional_end, h8_mark_palette_dirty, "$C172 -> palette helper"),
        (h8_mark_palette_dirty_end, entry_135e0, "palette helper -> $0135E0"),
    ):
        assert ESC2[
            seam_start - 0x8000:seam_end - 0x8000
        ] == bytes(seam_end - seam_start), (
            "escbank2 %s seam was overwritten" % label
        )
    assert ESC2[
        entry_d3b0t - 0x8000:entry_d3b0t - 0x8000 + 4
    ] == bytes.fromhex("c230a530"), (
        "$D3B0 relocation lost its REP #$30 / LDA $30 prologue"
    )
    assert ESC2[
        entry_d3b0t - 0x8000:entry_d3b0t_bridge_end - 0x8000
    ].count(bytes.fromhex("5c28f892")) == 1, (
        "$D3B0 relocation lost its sole cross-bank indirect bridge"
    )
    assert ESC2[
        brd3b0_1t - 0x8000:brd3b0_1t - 0x8000 + 3
    ] == bytes.fromhex("a90400"), (
        "$D3B0 continuation moved or lost its 16-bit prologue"
    )
    for entry, label in (
        (entry_27952, "$027952"),
        (entry_279d2, "$0279D2"),
        (entry_2f3ba, "$02F3BA"),
        (entry_27b44, "$027B44"),
        (entry_2f56a, "$02F56A"),
        (entry_27b7c, "$027B7C"),
        (entry_2f5a2, "$02F5A2"),
        (entry_2e49c, "$02E49C"),
        (entry_296c6, "$0296C6"),
        (entry_2e40e, "$02E40E"),
        (entry_135e0, "$0135E0"),
    ):
        assert ESC2[entry - 0x8000:entry - 0x8000 + 2] == bytes.fromhex(
            "c230"
        ), f"Stage-3 body {label} lost its REP #$30 prologue"
    assert ESC2[entry_135e0_end - 0x8000:0x6000] == bytes(
        0xE000 - entry_135e0_end
    ), "$0135E0 coordinate leaf grew into the fixed $94:E000 HLE island"
    assert ESC2[c172_optional - 0x8000:c172_optional_end - 0x8000].count(
        bytes.fromhex("5c00fc9d")
    ) == 1, "$C172 optional helper lost its sole direct $9D:FC00 callback link"
    assert (
        esc2_off("xlat_dispatch") == 0xF900
        and esc2_off("xd_table") == 0xF931
        and esc2_off("xd_dispatch_end") == 0xF97E
        and xlat_choke == 0xF980
        and xlat_choke < xlat_choke_end <= 0xFA00
    ), "xlat direct/generic dispatcher crossed its fixed $94:F900-$F97F island"
    assert ESC2[0x7900:0x7931] == bytes.fromhex(
        "c230a542f008c9030090228024eaa540eb29ff00c976009018c97b00900f"
        "c9c000"
        "f00ac9d7009009c9dd00b0045c00da9d"
    ), "gameplay-entry/combat/task sparse direct xlat arms changed bytes"
    assert ESC2[
        xd_sparse_direct - 0x8000:xd_sparse_direct - 0x8000 + 4
    ] == bytes.fromhex("5c00da9d"), (
        "xlat sparse-dispatch tail no longer has the VTIME-only patchable JML"
    )
    assert ESC2[
        xlat_choke - 0x8000:xlat_choke_end - 0x8000
    ].count(bytes.fromhex("5cf09995")) == 1, (
        "$002D8A fetch-choke route lost its sole pinned $95:99F0 gateway"
    )
    assert ESC2[xlat_choke_end - 0x8000:0x7A00] == bytes(
        0xFA00 - xlat_choke_end
    ), "xlat_choke has nonzero overlap before hce4_entry@$94:FA00"
    # Poppy permits flowing code to cross a later .org silently.  The fixed
    # $FE00/$FEC4/$FED4/$FF00/$FF80 helper islands must retain zero seams so one
    # helper cannot overwrite the next while still producing an assembly.  Use
    # assembled end labels because the DMA helper's chunk count is deliberately
    # tunable; a stale hard-coded end would reject safe growth or miss shrinkage.
    h158_dma_end = esc2_off("h158_dma_1020_end") - 0x8000
    h8_clear_end = esc2_off("h8_clear_ccr_x_end") - 0x8000
    h158_secondary_end = esc2_off("h158_dma_secondary_end") - 0x8000
    assert h158_dma_end <= 0x7EC4
    assert h8_clear_end <= 0x7ED4
    assert h158_secondary_end <= 0x7F00
    assert ESC2[:h158_dma_end].count(bytes.fromhex("2200e49e")) == 0, (
        "rejected $158E OBJ-Y staging hook reappeared in production"
    )
    for seam_start, seam_end, label in (
        (h158_dma_end, 0x7EC4, "h158_dma_1020 -> h8_clear_ccr_x"),
        (h8_clear_end, 0x7ED4, "h8_clear_ccr_x -> h158_dma_secondary"),
        (h158_secondary_end, 0x7F00, "h158_dma_secondary -> h158_set_ccr"),
        (0x7F35, 0x7F80, "h158_set_ccr -> h158_dma_residue"),
    ):
        assert ESC2[seam_start:seam_end] == bytes(seam_end - seam_start), (
            f"escbank2 {label} seam was overwritten; relocate code instead of "
            "allowing .org overlap"
        )
    ROM[0x2A0000:0x2A0000+len(ESC2)] = ESC2          # @ SA-1 $94:8000 (file $2A0000)

# --- SIXTH SA-1 escape bank ($95:8000, file $2A8000) ---
# This otherwise-free bank precedes the $96 xlat-data bank.  Do not use file
# $2D0000/$9A: the production TAD audio blob begins at file $2D002B.
if _osp.exists("src/escbank6.bin"):
    ESC6 = Path("src/escbank6.bin").read_bytes()
    assert len(ESC6) <= 0x8000, (
        "escbank6 %d bytes overflows the $2A8000..$2B0000 bank" % len(ESC6)
    )
    esc6_symbols = Path("src/escbank6.sym").read_text()
    assert "00:8000 escbank6_begin" in esc6_symbols, (
        "escbank6 no longer begins at the mapped $95:8000 origin"
    )
    def esc6_off(symbol):
        for line in esc6_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank6 layout symbol %s" % symbol)

    generated_end = esc6_off("escbank6_end")
    early_bodies_end = esc6_off("escbank6_early_bodies_end")
    entry_2d8at = esc6_off("entry_2d8at")
    entry_c8e0 = esc6_off("entry_c8e0t")
    entry_c8e0_resume = esc6_off("entry_c8e0_generated_resume")
    hle_17b4 = esc6_off("hle_17b4")
    hle_17b4_end = esc6_off("hle_17b4_end")
    hle_8fa = esc6_off("hle_8fa")
    hle_8fa_end = esc6_off("hle_8fa_end")
    d3f6_move_byte_nz = esc6_off("d3f6_move_byte_nz")
    d3f6_move_byte_nz_end = esc6_off("d3f6_move_byte_nz_end")
    h8fa_validation_spin = esc6_off("h8fa_validation_spin")
    h8fa_validation_spin_end = esc6_off("h8fa_validation_spin_end")
    h25110_tstw_e_dispatch = esc6_off("h25110_tstw_e_dispatch")
    h25110_tstw_e_dispatch_end = esc6_off(
        "h25110_tstw_e_dispatch_end"
    )
    esc6_udiv = esc6_off("esc_udiv")
    esc6_udiv_end = esc6_off("esc_udiv_end")
    hle_96a = esc6_off("hle_96a")
    hle_96a_end = esc6_off("hle_96a_end")
    hle_c262 = esc6_off("hle_c262")
    hle_c262_fast = esc6_off("hle_c262_fast_hook")
    hle_c262_end = esc6_off("hle_c262_end")
    hle_9ea = esc6_off("hle_9ea")
    hle_9ea_fast = esc6_off("hle_9ea_fast_hook")
    hle_9ea_end = esc6_off("hle_9ea_end")
    entry_111at = esc6_off("entry_111at")
    entry_111at_end = esc6_off("entry_111at_end")
    mid_bodies_end = esc6_off("escbank6_mid_bodies_end")
    hc262_generated_finish = esc6_off("hc262_generated_finish")
    hc262_generated_finish_end = esc6_off("hc262_generated_finish_end")
    entry_2a1b2 = esc6_off("entry_2a1b2")
    entry_2a190 = esc6_off("entry_2a190")
    entry_2a1d8t = esc6_off("entry_2a1d8t")
    entry_2a53a = esc6_off("entry_2a53a")
    entry_29128 = esc6_off("entry_29128")
    entry_29144 = esc6_off("entry_29144")
    entry_2a61e = esc6_off("entry_2a61e")
    post_late_bodies_end = esc6_off("escbank6_post_late_bodies_end")
    h176f6_tstw_zero_root = esc6_off("h176f6_tstw_zero_root")
    h176f6_move_one_root = esc6_off("h176f6_move_one_root")
    h176f6_backedge_ccr_end = esc6_off(
        "h176f6_backedge_ccr_end"
    )
    h25110_stage1 = esc6_off("h25110_stage1")
    h25_fast_done = esc6_off("h25_fast_done")
    h25_fast_x_done = esc6_off("h25_fast_x_done")
    h25_fast_done_jump = esc6_off("h25_fast_done_jump")
    h25110_xflag_stage1 = esc6_off("h25110_xflag_stage1")
    h25110_xflag_stage1_end = esc6_off("h25110_xflag_stage1_end")
    late_combat_bodies_end = esc6_off("late_combat_bodies_end")
    hce4_shape_try = esc6_off("hce4_shape_try")
    hce4_shape_miss = esc6_off("hce4_shape_miss")
    hce4_shape_end = esc6_off("hce4_shape_end")
    hcaf6_const_list = esc6_off("hcaf6_const_list")
    hcaf6_const_list_end = esc6_off("hcaf6_const_list_end")
    h25_predicates = esc6_off("h25_sgt")
    h25_predicates_end = esc6_off("h25_predicates_end")
    h25_clear_response_c = esc6_off("h25_clear_response_c")
    h25_clear_response_d = esc6_off("h25_clear_response_d")
    h25_clear_response_helpers_end = esc6_off(
        "h25_clear_response_helpers_end"
    )
    entry_11bdc = esc6_off("entry_11bdc")
    entry_11c9a = esc6_off("entry_11c9a")
    landing_combat_continuations_end = esc6_off(
        "landing_combat_continuations_end"
    )
    hcaf6_const_33208 = esc6_off("hcaf6_const_33208")
    hcaf6_const_33208_end = esc6_off("hcaf6_const_33208_end")
    hcaf6_const_332fe = esc6_off("hcaf6_const_332fe")
    hcaf6_const_332fe_end = esc6_off("hcaf6_const_332fe_end")
    assert generated_end <= 0x9B00 and hle_17b4 == 0x9B00, (
        "escbank6 generated bodies crossed the pinned $95:9B00 hle_17b4 slot"
    )
    assert early_bodies_end <= entry_2d8at == 0x99F0, (
        "escbank6 early bodies crossed or moved the pinned $95:99F0 "
        "$002D8A sparse-dispatch gateway"
    )
    assert ESC6[
        early_bodies_end - 0x8000:entry_2d8at - 0x8000
    ] == bytes(entry_2d8at - early_bodies_end), (
        "escbank6 early bodies left nonzero overlap before entry_2d8at"
    )
    assert entry_c8e0 == 0x8000 and entry_c8e0_resume == 0x8004, (
        "$C8E0 generated entry seam moved from $95:8000/$8004"
    )
    assert ESC6[0x0000:0x0004] == bytes.fromhex("c230a538"), (
        "entry_c8e0t no longer begins with the original REP/LDA prologue"
    )
    assert ESC6[0x0004:0x0006] == bytes.fromhex("8554"), (
        "entry_c8e0t generated body no longer continues at STA $54"
    )
    assert ESC6[generated_end - 0x8000:0x1B00] == bytes(
        0x1B00 - (generated_end - 0x8000)
    ), "escbank6 generated body has nonzero overlap before hle_17b4"
    assert ESC6[0x1B00:0x1B08] == bytes.fromhex("c23022c0879da53e"), (
        "hle_17b4 prologue moved or assembled with stale width state"
    )
    assert hle_17b4 < hle_17b4_end <= 0x9D00, (
        "hle_17b4 crossed its reserved $95:9B00-$9CFF island"
    )
    assert hle_8fa == 0x9D00, "hle_8fa moved from its pinned $95:9D00 entry"
    assert ESC6[hle_17b4_end - 0x8000:0x1D00] == bytes(
        0x1D00 - (hle_17b4_end - 0x8000)
    ), "hle_17b4 has nonzero overlap before hle_8fa"
    assert ESC6[0x1D00:0x1D04] == bytes.fromhex("c230a53e"), (
        "hle_8fa prologue moved or assembled with stale width state"
    )
    assert (
        hle_8fa < hle_8fa_end <= d3f6_move_byte_nz == 0x9F70
        and d3f6_move_byte_nz < d3f6_move_byte_nz_end <= 0x9FA0
    ), (
        "hle_8fa crossed the fixed $95:9FA0 validation seam"
    )
    assert h8fa_validation_spin == 0x9FA0 and h8fa_validation_spin_end == 0x9FA2, (
        "hle_8fa validation spin moved from its fixed two-byte seam"
    )
    assert (
        h25110_tstw_e_dispatch == 0x9FB0
        and h25110_tstw_e_dispatch
        < h25110_tstw_e_dispatch_end
        <= esc6_udiv
        < esc6_udiv_end
        <= 0xA000
    ), (
        "$025110 word-sign dispatcher or bank-$95 divider crossed "
        "hle_96a@$95:A000"
    )
    assert ESC6[hle_8fa_end - 0x8000:0x1F70] == bytes(
        0x1F70 - (hle_8fa_end - 0x8000)
    ), "hle_8fa has nonzero overlap before the $D3F6 flags helper"
    assert ESC6[
        d3f6_move_byte_nz_end - 0x8000:0x1FA0
    ] == bytes(0x1FA0 - (d3f6_move_byte_nz_end - 0x8000)), (
        "$D3F6 flags helper has nonzero overlap before the validation spin"
    )
    assert ESC6[0x1FA0:0x1FA2] == bytes.fromhex("80fe"), (
        "hle_8fa validation spin is not BRA -2"
    )
    assert hle_96a == 0xA000 and hle_96a < hle_96a_end <= 0xA300, (
        "hle_96a moved from $95:A000 or crossed its reserved $95:A000-$A2FF island"
    )
    assert ESC6[0x1FA2:0x1FB0] == bytes(0x000E), (
        "bank-$95 validation seam has nonzero overlap before the $025110 "
        "word-sign dispatcher"
    )
    assert ESC6[
        h25110_tstw_e_dispatch_end - 0x8000:esc6_udiv - 0x8000
    ] == bytes(esc6_udiv - h25110_tstw_e_dispatch_end), (
        "$025110 word-sign dispatcher has nonzero overlap before esc_udiv"
    )
    assert ESC6[
        esc6_udiv_end - 0x8000:0x2000
    ] == bytes(0xA000 - esc6_udiv_end), (
        "esc_udiv has nonzero overlap before hle_96a"
    )
    assert ESC6[0x2000:0x2004] == bytes.fromhex("c230a536"), (
        "hle_96a prologue moved or assembled with stale width state"
    )
    assert ESC6[hle_96a_end - 0x8000:0x2300] == bytes(
        0x2300 - (hle_96a_end - 0x8000)
    ), "hle_96a has nonzero overlap before the fixed $95:A300 hle_c262 slot"
    assert hle_c262 == 0xA300 and hle_c262 < hle_c262_fast < hle_c262_end <= 0xA600, (
        "hle_c262 moved from $95:A300 or crossed the fixed $95:A600 hle_9ea slot"
    )
    assert ESC6[0x2300:0x2304] == bytes.fromhex("c230a536"), (
        "hle_c262 prologue moved or assembled with stale width state"
    )
    assert ESC6[hle_c262_end - 0x8000:0x2600] == bytes(
        0x2600 - (hle_c262_end - 0x8000)
    ), "hle_c262 has nonzero overlap before hle_9ea@$95:A600"
    assert hle_9ea == 0xA600 and hle_9ea < hle_9ea_fast < hle_9ea_end <= 0xA700, (
        "hle_9ea moved from $95:A600 or crossed the rejected $95:A700 island"
    )
    assert ESC6[0x2600:0x2604] == bytes.fromhex("c230a536"), (
        "hle_9ea prologue moved or assembled with stale width state"
    )
    assert ESC6[hle_9ea_end - 0x8000:0x2700] == bytes(
        0x2700 - (hle_9ea_end - 0x8000)
    ), "hle_9ea has nonzero overlap before entry_111at@$95:A700"
    assert entry_111at == 0xA700 and entry_111at < entry_111at_end <= 0xAF00, (
        "$111A table body moved from $95:A700 or crossed the $95:AF00 seam"
    )
    assert (
        entry_111at_end <= entry_2a53a < mid_bodies_end <= 0xAF00
    ), (
        "$02A53A moved outside the audited post-$111A $95:ADCC-$AEFF gap"
    )
    assert ESC6[
        entry_111at_end - 0x8000:entry_2a53a - 0x8000
    ] == bytes(entry_2a53a - entry_111at_end), (
        "rejected $C8E0 island has nonzero data before entry_2a53a"
    )
    assert ESC6[mid_bodies_end - 0x8000:0x2F00] == bytes(
        0xAF00 - mid_bodies_end
    ), (
        "$02A53A has nonzero overlap before "
        "hc262_generated_finish@$95:AF00"
    )
    assert hc262_generated_finish == 0xAF00, (
        "the generated $C262 fallback finisher moved from $95:AF00"
    )
    assert hc262_generated_finish < hc262_generated_finish_end <= 0xB000, (
        "$C262 fallback finisher crossed the private DMA payload at $95:B000"
    )
    assert ESC6[hc262_generated_finish_end - 0x8000:0x3000] == bytes(
        0x3000 - (hc262_generated_finish_end - 0x8000)
    ), "$C262 fallback finisher has nonzero overlap before the private payload"
    assert ESC6[0x3000:0x35B0] == bytes(0x05B0), (
        "assembled bank-$95 code/data overlaps the private $B000-$B5AF DMA payload"
    )
    assert ESC6[0x35B0:0x3600] == bytes(0x0050), (
        "bank-$95 private-payload guard gap $B5B0-$B5FF is nonzero"
    )
    assert entry_2a1b2 == 0xB600, (
        "$02A1B2 guarded adapter moved from the audited $95:B600 seam"
    )
    assert (
        entry_2a1b2 < entry_2a190 < entry_2a1d8t
        < entry_29128 < entry_29144 < entry_2a61e
        < post_late_bodies_end
        <= h176f6_tstw_zero_root == 0xEFC0
        < h176f6_move_one_root
        < h176f6_backedge_ccr_end
        < h25110_stage1 == 0xF000 < h25110_xflag_stage1 == 0xF3E0
        < h25110_xflag_stage1_end == late_combat_bodies_end <= 0xF400
    ), "late-combat bodies overlap, reordered, or overflow bank $95"
    assert ESC6[
        post_late_bodies_end - 0x8000:
        h176f6_tstw_zero_root - 0x8000
    ] == bytes(
        h176f6_tstw_zero_root - post_late_bodies_end
    ), (
        "cycle-accounted copied C-Chip body overlaps the fixed "
        "$176F6 callback-CCR seam"
    )
    assert ESC6[
        h176f6_backedge_ccr_end - 0x8000:0x7000
    ] == bytes(
        0xF000 - h176f6_backedge_ccr_end
    ), "$176F6 callback-CCR helper overlaps h25110_stage1@$95:F000"
    esc3_import_symbols = Path("src/escbank3.sym").read_text(
        encoding="utf-8-sig"
    )
    esc3_stage1_done = None
    esc3_stage1_entry = None
    for line in esc3_import_symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "h25110_stage1_done":
            esc3_stage1_done = int(fields[0].split(":", 1)[1], 16)
        if len(fields) >= 2 and fields[1] == "L25110_25122":
            esc3_stage1_entry = int(fields[0].split(":", 1)[1], 16)
    assert esc3_stage1_done is not None and esc3_stage1_entry is not None, (
        "escbank3 lost a semantic $25110 stage-1 seam"
    )
    assert ESC6[
        h25_fast_done_jump - 0x8000:h25_fast_done_jump - 0x8000 + 4
    ] == bytes(
        (0x5C, esc3_stage1_done & 0xFF, esc3_stage1_done >> 8, 0x97)
    ), (
        "$25110 compact pass no longer jumps to the semantic bank-$97 "
        "stage-1 completion seam"
    )
    assert (
        h25_fast_done == 0xF39F
        < h25_fast_x_done == 0xF3AF
        < h25_fast_done_jump
        < h25110_xflag_stage1 == 0xF3E0
    ), "$25110 compact X publication moved or crossed its fixed tail seam"
    assert ESC6[0x739F:0x73AF] == bytes.fromhex(
        "64a2a5503a0aaab580c9543cd002e6a2"
    ), "$25110 compact pass lost its final-physical-slot X publication"
    assert ESC6[0x73E0:0x73FA] == (
        bytes.fromhex("c230a91e00851ca5341869743a8520a5366900008522")
        + bytes(
            (
                0x5C,
                esc3_stage1_entry & 0xFF,
                esc3_stage1_entry >> 8,
                0x97,
            )
        )
    ), "$25110 X-aware adapter moved or lost its current bank-$97 setup target"
    assert ESC6[late_combat_bodies_end - 0x8000:0x7400] == bytes(
        0x7400 - (late_combat_bodies_end - 0x8000)
    ), "late-combat bodies have nonzero overlap before hce4_shape_try@$95:F400"
    assert hce4_shape_try == 0xF400 and hce4_shape_try < hce4_shape_end <= 0xFA00, (
        "$CE4 shape island moved from $95:F400 or crossed the $95:FA00 CAF6 slot"
    )
    assert ESC6[hce4_shape_miss - 0x8000:hce4_shape_miss - 0x8000 + 4] == bytes.fromhex(
        "5c00e49d"
    ), "$CE4 shape miss no longer continues at the guarded $9D:E400 extension"
    assert ESC6[hce4_shape_end - 0x8000:0x7A00] == bytes(
        0x7A00 - (hce4_shape_end - 0x8000)
    ), "$CE4 shape island has nonzero overlap before hcaf6_const_list@$95:FA00"
    assert hcaf6_const_list == 0xFA00 and hcaf6_const_list < hcaf6_const_list_end <= 0xFBE0, (
        "$CAF6 constant-list island moved from $95:FA00 or overflowed bank $95"
    )
    assert h25_predicates == 0xFBE0 and h25_predicates < h25_predicates_end <= 0xFC10, (
        "$25110 signed predicates moved from their guarded $95:FBE0 tail island"
    )
    assert ESC6[hcaf6_const_list_end - 0x8000:0x7BE0] == bytes(
        0x7BE0 - (hcaf6_const_list_end - 0x8000)
    ), "$CAF6 constant-list island has nonzero overlap before $95:FBE0"
    assert (
        h25_predicates_end
        == h25_clear_response_c
        < h25_clear_response_d
        < h25_clear_response_helpers_end
        <= 0xFC20
        == entry_11bdc
        < entry_11c9a
        < landing_combat_continuations_end
        <= hcaf6_const_33208
        == 0xFE20
    ), "landing/combat continuations moved or overflowed their bank-$95 tail"
    assert ESC6[
        h25_clear_response_c - 0x8000:h25_clear_response_helpers_end - 0x8000
    ] == bytes.fromhex(
        "e220a9009f0c0040c22060"
        "e220a9009f0d0040c22060"
    ), "$25110 response-clear helpers lost their explicit long BW-RAM stores"
    assert ESC6[h25_clear_response_helpers_end - 0x8000:0x7C20] == bytes(
        0x7C20 - (h25_clear_response_helpers_end - 0x8000)
    ), "$25110 response-clear helpers overlap the $011B/$011C continuation island"
    assert ESC6[entry_11bdc - 0x8000:entry_11bdc - 0x8000 + 2] == bytes.fromhex(
        "c230"
    ), "$011BDC continuation lost its explicit REP #$30 prologue"
    assert ESC6[entry_11c9a - 0x8000:entry_11c9a - 0x8000 + 2] == bytes.fromhex(
        "c230"
    ), "$011C9A continuation lost its explicit REP #$30 prologue"
    assert ESC6[
        landing_combat_continuations_end - 0x8000:hcaf6_const_33208 - 0x8000
    ] == bytes(hcaf6_const_33208 - landing_combat_continuations_end), (
        "landing/combat continuations overlap the late CAF6 constant-list body"
    )
    assert hcaf6_const_33208 < hcaf6_const_33208_end <= 0xFF10, (
        "$033208 CAF6 constant-list body crossed the $0332FE island"
    )
    assert hcaf6_const_332fe == 0xFF10, (
        "$0332FE CAF6 constant-list body moved from fixed $95:FF10"
    )
    assert ESC6[
        hcaf6_const_33208_end - 0x8000:hcaf6_const_332fe - 0x8000
    ] == bytes(hcaf6_const_332fe - hcaf6_const_33208_end), (
        "nonzero bank-$95 bytes overlap the two late CAF6 constant bodies"
    )
    assert hcaf6_const_332fe < hcaf6_const_332fe_end <= 0x10000, (
        "$0332FE CAF6 constant-list body overflows bank $95"
    )
    assert len(ESC6) == hcaf6_const_332fe_end - 0x8000, (
        "unexpected bank-$95 bytes follow the late CAF6 constant-list bodies"
    )
    ROM[0x2A8000:0x2A8000+len(ESC6)] = ESC6          # @ SA-1 $95:8000 (file $2A8000)
    c262_blob_offset = 0x2AB000                       # @ SA-1 $95:B000
    assert ROM[c262_blob_offset:c262_blob_offset + len(C262_DMA_BLOB)] == bytes(
        len(C262_DMA_BLOB)
    ), "$C262 DMA payload would overwrite nonzero bank-$95 data"
    ROM[c262_blob_offset:c262_blob_offset + len(C262_DMA_BLOB)] = C262_DMA_BLOB

# --- AOT address-translation table (xlat_dispatch's data; SA-1 $96:8000 = file $2B0000) ---
# 2-level page table 68K PC -> native escape entry, generated by tools/gen_xlat_table.py. Bank $96
# is in the SA-1 MMC window ($80-$9F) and verified live-readable. xlat_dispatch (escbank2 $94:F900)
# indexes it via long addressing; a zero entry = miss = interpret.
if _osp.exists("src/xlat_table.bin"):
    XLAT = Path("src/xlat_table.bin").read_bytes()
    assert len(XLAT) <= 0x8000, ("xlat table %d bytes overflows the $2B0000..$2B8000 bank" % len(XLAT))
    # $01D5F0's retained native physics body does not publish the CCR/X
    # produced immediately before TRAP #5.  It is forensic material only:
    # production must miss both the fast-RTE selector and this generic xlat
    # table so op_rte resumes the canonical interpreter.  Its $01D5 page is
    # necessarily present for neighboring safe continuations, so decode the
    # generated two-level table and pin the individual entry to a zero miss.
    parked_1d5f0_page = (0x01D5F0 >> 8) & 0x3FF
    parked_1d5f0_page_slot = parked_1d5f0_page * 2
    parked_1d5f0_subtable = int.from_bytes(
        XLAT[parked_1d5f0_page_slot:parked_1d5f0_page_slot + 2],
        "little",
    )
    assert parked_1d5f0_subtable != 0, (
        "$01D5 xlat page unexpectedly vanished; cannot prove the individual "
        "$01D5F0 parking entry"
    )
    parked_1d5f0_slot = parked_1d5f0_subtable + (0xF0 * 3)
    assert XLAT[parked_1d5f0_slot:parked_1d5f0_slot + 3] == bytes(3), (
        "$01D5F0 unsafe physics coroutine re-entered the production xlat table"
    )
    ROM[0x2B0000:0x2B0000+len(XLAT)] = XLAT          # @ SA-1 $96:8000 (file $2B0000)

# --- THIRD SA-1 escape bank ($97:8000, file $2B8000) ---
# entry_25110 (collision, $025110): its 8KB body overflowed its bank-$00 inline gap ($D1ED..$E000)
# and was silently clobbered by the following .org routines. Relocated to this fresh 32KB bank (the
# SA-1 MMC maps file $200000-$2FFFFF -> $80-$9F uniformly, so file $2B8000 = $97:8000, executable
# like $92/$94). Bank $00's dead inline entry_25110 @ $D1ED is redirected here via `jml $978000`.
if _osp.exists("src/escbank4.bin"):
    ESC4 = Path("src/escbank4.bin").read_bytes()
    assert len(ESC4) <= 0x8000, ("escbank4 %d bytes overflows the $2C0000..$2C8000 bank" % len(ESC4))
    esc4_symbols = Path("src/escbank4.sym").read_text(encoding="utf-8-sig")
    def esc4_off(symbol):
        for line in esc4_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank4 layout symbol %s" % symbol)

    assert ESC4[0x0000:0x000E] == bytes.fromhex("5c008f98" + "ea" * 10), (
        "escbank4 entry_23342 guarded redirect moved or changed size"
    )
    assert (
        esc4_off("Lf23342_1") == 0x80AE
        and esc4_off("h23342_call_bridge") == 0x8F5E
        and esc4_off("br23342_1") == 0x80C6
        and esc4_off("br23342_2") == 0x80D3
    ), "$023342 generated branch/continuation moved; re-audit its mode-pinned call bridge"
    assert ESC4[0x00AE:0x00C6] == bytes.fromhex(
        "5c5e8f98" + "ea" * 20
    ), (
        "$023342 rare callee branch lost its size-neutral mode-pinned redirect; "
        "the old A8 encoding executed MVN $A9,$FB and erased SA-1 IRAM"
    )
    assert ESC4[0x00C6:0x00D3] == bytes.fromhex(
        "a9d3808540a9fb0085424c0084"
    ), (
        "$023342 continuation lost 16-bit immediates; the old encoding executed "
        "STA $40's operand as RTI and crashed crate throws"
    )
    assert ESC4[0x1200:0x120E] == bytes.fromhex("5c009098" + "ea" * 10), (
        "escbank4 entry_235e0 guarded redirect moved or changed size"
    )
    assert esc4_off("h2429c_empty_helpers") == 0x8E53, (
        "escbank4 fused $02429C empty-helper entry moved from $98:8E53"
    )
    assert esc4_off("entry_2335e_generated_end") == 0x8E53, (
        "escbank4 $02335E body overlaps the fixed $98:8E53 island"
    )
    h2429c_empty_end = esc4_off("h2429c_empty_helpers_end")
    assert h2429c_empty_end <= 0x8F00, (
        "escbank4 fused $02429C empty-helper body crossed the $8F00 island"
    )
    assert ESC4[
        h2429c_empty_end - 0x8000:0x0F00
    ] == bytes(0x8F00 - h2429c_empty_end), (
        "escbank4 fused $02429C empty-helper seam has nonzero overlap"
    )
    assert ESC4[0x0F5E:0x0F7A] == bytes.fromhex(
        "a9c6808554a9fb00855622aee500a90c388540a9020085425cb3d100"
    ), (
        "escbank4 $023342 rare callee bridge lost explicit 16-bit immediates"
    )
    assert ESC4[0x0F7A:0x0F80] == bytes(0x06), (
        "escbank4 $023342 call bridge crossed the fixed $8F80 island"
    )
    assert (
        esc4_off("h23e34_empty_end") == 0x8FD9
        and esc4_off("readbyte_tst") == 0x8FD9
        and esc4_off("readbyte_tst_native") == 0x8FEF
        and esc4_off("readbyte_tst_end") == 0x8FFE
    ), (
        "escbank4 compact byte-TST helper moved within the $8FD9-$8FFF seam"
    )
    assert ESC4[0x0FD9:0x0FFE] == bytes.fromhex(
        "a518d01268a966338540a9020085422080905c28d100"
        "22b6e50029ff0049800038e9800060"
    ), (
        "escbank4 compact byte-TST helper lost its final-iteration fallback "
        "or no longer sign-normalizes bit 7"
    )
    assert ESC4[0x0FFE:0x1000] == bytes(0x02), (
        "escbank4 compact byte-TST helper crossed the fixed $9000 island"
    )
    assert ESC4[0x0400:0x0E53].count(
        bytes.fromhex("20d98fea")
    ) == 4, (
        "escbank4 $02335E does not route exactly four TST.B loads through "
        "the size-neutral compact helper"
    )
    residue_2335e = esc4_off("restore_2335e_call_residue")
    residue_2335e_end = esc4_off("restore_2335e_call_residue_end")
    assert residue_2335e == 0x9080 and residue_2335e_end == 0x90B7, (
        "escbank4 $02335E call-residue helper left its audited "
        "$98:9080-$98:90B6 island"
    )
    assert ESC4[0x1061:0x1080] == bytes(0x1F), (
        "escbank4 h235e0_empty grew into the pre-residue $9061-$907F seam"
    )
    assert ESC4[0x1080:0x10B7] == bytes.fromhex(
        "a53c38e90e00aaa90200eb9f000040ebe8e8a93034eb9f000040eb"
        "a53c38e90400aaa90200eb9f000040ebe8e8a93635eb9f000040eb60"
    ), (
        "escbank4 $02335E call-residue helper no longer restores "
        "$023430 and $023536 below architectural A7"
    )
    assert ESC4[0x10B7:0x1100] == bytes(0x49), (
        "escbank4 $02335E call-residue helper crossed the $9100 island"
    )
    assert ESC4[0x115F:0x1200] == bytes(0xA1), (
        "escbank4 MOVEM residue helper grew into entry_235e0 at $9200"
    )
    assert ESC4[0x2EC6:0x2ECC] == bytes.fromhex("5c00e097eaea"), (
        "escbank4 $01E7C0 hot-loop redirect moved or stopped being the exact "
        "size-neutral JML $97:E000 + two-NOP replacement"
    )
    h1e7c0_loop_decrement = esc4_off("L1e7c0_1f192")
    h1e7c0_loop_done = esc4_off("Lf1e7c0_227")
    h1e7c0_generated_reentry = esc4_off("h1e7c0_generated_reentry")
    h1e7c0_script_seam = esc4_off("L1e7c0_1e94a")
    assert h1e7c0_script_seam == 0xB814, (
        "$01E7C0 generated script seam moved from audited $98:B814"
    )
    c892_end = esc4_off("entry_c892_end")
    residue_helper = esc4_off("restore_1e7c0_call_residue")
    residue_helper_end = esc4_off("restore_1e7c0_call_residue_end")
    byte_arith_helper = esc4_off("neg_d3_byte_1e7c0")
    byte_arith_helper_end = esc4_off("byte_arith_1e7c0_end")
    assert c892_end == 0xFF51, (
        "escbank4 entry_c892 tail moved from audited $98:FF51"
    )
    assert residue_helper == 0xFF60 and residue_helper_end <= 0xFF80, (
        "$01E7C0 shared call-residue helper left its audited "
        "$98:FF60-$98:FF7F tail island"
    )
    assert byte_arith_helper == 0xFF80 and byte_arith_helper_end <= 0xFFD0, (
        "$01E7C0 byte-arithmetic repair helpers left the audited "
        "$98:FF80-$98:FFCF tail island"
    )
    assert ESC4[
        c892_end - 0x8000:residue_helper - 0x8000
    ] == bytes(residue_helper - c892_end), (
        "$01E7C0 shared call-residue helper overlaps entry_c892"
    )
    assert h1e7c0_generated_reentry == 0xFA6A, (
        "$01E7C0 generated-record re-entry trampoline moved from $98:FA6A"
    )
    assert h1e7c0_loop_done - h1e7c0_loop_decrement == 0x0D, (
        "$01E7C0 generated DBRA seam changed shape; re-audit its re-entry JMP"
    )
    assert ESC4[
        h1e7c0_loop_done - 0x8000 - 3:h1e7c0_loop_done - 0x8000
    ] == bytes((
        0x4C,
        h1e7c0_generated_reentry & 0xFF,
        h1e7c0_generated_reentry >> 8,
    )), "$01E7C0 generated loop no longer JMPs to its bank-$98 re-entry trampoline"
    esc3_reentry = None
    for line in Path("src/escbank3.sym").read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "h1e7c0_hot_reentry":
            esc3_reentry = int(fields[0].split(":", 1)[1], 16)
            break
    assert esc3_reentry is not None, "escbank3 lost h1e7c0_hot_reentry"
    assert ESC4[0x7A6A:0x7A80] == (
        bytes((0x5C, esc3_reentry & 0xFF, esc3_reentry >> 8, 0x97))
        + bytes(0x12)
    ), (
        "escbank4 $01E7C0 re-entry trampoline changed or entry_1f1fet grew "
        "into the remaining $FA6E-$FA7F seam before entry_c7dc"
    )
    assert ESC4[0x7D56:0x7D70] == bytes(0x1A), (
        "escbank4 entry_c7dc grew into the $FD56-$FD6F seam before entry_c892; "
        "relocate code instead of allowing .org overlap"
    )
    assert (
        ESC4.count(bytes.fromhex("5c46fc99")) == 2
        and ESC4.count(bytes.fromhex("5c52fc99")) == 1
        and ESC4.count(bytes.fromhex("5c61fc99")) == 1
    ), (
        "escbank4 entry_c7dc lost a source-specific terminal-CCR route to "
        "the shared $99:FC46/$FC52/$FC61 helpers"
    )
    ROM[0x2C0000:0x2C0000+len(ESC4)] = ESC4          # @ SA-1 $98:8000 (file $2C0000)
if _osp.exists("src/escbank3.bin"):
    ESC3 = Path("src/escbank3.bin").read_bytes()
    assert len(ESC3) <= 0x8000, ("escbank3 %d bytes overflows the $2B8000..$2C0000 bank" % len(ESC3))
    esc3_symbols = Path("src/escbank3.sym").read_text(encoding="utf-8-sig")
    def esc3_off(symbol):
        for line in esc3_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank3 layout symbol %s" % symbol)

    entry_25110 = esc3_off("entry_25110")
    lf25110_1 = esc3_off("Lf25110_1")
    l25110_25122 = esc3_off("L25110_25122")
    h25110_stage1_done = esc3_off("h25110_stage1_done")
    h25110_stage2_generated_setup = esc3_off("h25110_stage2_generated_setup")
    h25110_stage5_select = esc3_off("h25110_stage5_select")
    lf25110_281 = esc3_off("Lf25110_281")
    l25110_259b0 = esc3_off("L25110_259b0")
    h25110_final_tst_done = esc3_off("h25110_final_tst_done")
    h25110_canonical_a5 = esc3_off("h25110_canonical_a5")
    h25110_vtime_finish_source = esc3_off("h25110_vtime_finish_source")
    esc3_ac_charge_2 = esc3_off("esc3_ac_charge_2")
    esc3_ac_charge_legacy_load = esc3_off("esc3_ac_charge_legacy_load")
    esc3_ac_charge_legacy_sbc = esc3_off("esc3_ac_charge_legacy_sbc")
    esc3_ac_charge_vtime_gateway = esc3_off("esc3_ac_charge_vtime_gateway")
    h25110_vtime_entry_gateway = esc3_off("h25110_vtime_entry_gateway")
    h25110_vtime_finish_gateway = esc3_off("h25110_vtime_finish_gateway")
    esc3_vtime_gateway_end = esc3_off("esc3_vtime_gateway_end")
    ors_pre_target = interp_symbol("ors_pre")
    entry_12e56 = esc3_off("entry_12e56")
    entry_1f1c0t = esc3_off("entry_1f1c0t")
    entry_1f1c0_generated = esc3_off("entry_1f1c0_generated")
    assert (
        entry_25110 == 0x8000
        < lf25110_1
        < l25110_25122
        < h25110_stage1_done
        < h25110_stage2_generated_setup
        < h25110_final_tst_done
        < entry_12e56 == 0xA000
    ), "$25110 adapters or semantic seams moved/reordered in bank $97"
    assert Path("src/escbank3.pasm").read_text(encoding="utf-8").count(
        "jsr esc3_ac_charge_"
    ) == 226, "$25110 lost one or more of its 226 generated charge blocks"
    assert ESC3[
        lf25110_1 - 0x8000:l25110_25122 - 0x8000
    ] == (
        bytes((0x20, esc3_ac_charge_2 & 0xFF, esc3_ac_charge_2 >> 8))
        + bytes.fromhex("ad3407f0045ce0f3955c00f095")
    ), "$25110 paced/generated versus unpaced/compact Stage-1 route changed"
    assert entry_1f1c0t == 0xFC60 and entry_1f1c0_generated == 0xFC64, (
        "$01F1C0 fast redirect or generated fallback moved in bank $97"
    )
    assert ESC3[0x7C60:0x7C64] == bytes.fromhex("5c00ab9d"), (
        "$01F1C0 table entry lost its size-neutral JML $9D:AB00 wrapper"
    )
    assert ESC3[
        h25110_stage1_done - 0x8000:h25110_stage1_done - 0x8000 + 8
    ] == (
        bytes((0x20, esc3_off("esc3_ac_charge_3") & 0xFF,
               esc3_off("esc3_ac_charge_3") >> 8))
        + bytes.fromhex("5c00809dea")
    ), (
        "$25110 stage-2 charge/guarded redirect changed"
    )
    assert h25110_stage2_generated_setup == h25110_stage1_done + 8, (
        "$25110 generated stage-2 fallback no longer follows its redirect"
    )
    assert ESC3[
        h25110_stage5_select - 0x8000:h25110_stage5_select - 0x8000 + 7
    ] == (
        bytes((0x20, esc3_ac_charge_2 & 0xFF, esc3_ac_charge_2 >> 8))
        + bytes.fromhex("5c00829d")
    ), (
        "$025110 stage-5 charge/inactive-list redirect changed"
    )
    assert lf25110_281 < l25110_259b0 < h25110_final_tst_done, (
        "$025110 word-sign or Stage-5 continuations reordered"
    )
    assert ESC3[
        lf25110_281 - 0x8000 - 6:lf25110_281 - 0x8000
    ] == bytes.fromhex("5cb09f95eaea"), (
        "$025110 TST.W $E(A2) lost its size-neutral word-sign dispatcher"
    )
    # The generated CAF6 body must end before its guarded production helper,
    # which is pinned at $DD00 and may use the remaining space before
    # h1e7c0@$E000.
    # Poppy accepts backward/overlapping .org sections, so make both gaps an
    # explicit ROM-pack invariant instead of trusting assembly success.
    caf6_generated_end = esc3_off("caf6_generated_end")
    assert 0xDC00 < caf6_generated_end <= 0xDD00, (
        "escbank3 CAF6 generated body crossed hcaf6_fast@$97:DD00"
    )
    assert ESC3[caf6_generated_end - 0x8000:0x5D00] == bytes(
        0xDD00 - caf6_generated_end
    ), (
        "escbank3 CAF6 generated body has nonzero bytes in the seam before "
        "hcaf6_fast; relocate code instead of allowing .org overlap"
    )
    hcaf6_end = esc3_off("hcaf6_end")
    assert 0xDD00 < hcaf6_end <= 0xE000, (
        "escbank3 hcaf6_fast crossed h1e7c0_hot@$97:E000"
    )
    assert ESC3[hcaf6_end - 0x8000:0x6000] == bytes(0xE000 - hcaf6_end), (
        "escbank3 hcaf6_fast has nonzero overlap before h1e7c0_hot@$97:E000"
    )
    h1e7c0_hot_end = esc3_off("h1e7c0_hot_end")
    h1e7c0_hot_timer_delta_select = esc3_off(
        "h1e7c0_hot_timer_delta_select"
    )
    h1e7c0_hot_timer_delta_ready = esc3_off(
        "h1e7c0_hot_timer_delta_ready"
    )
    assert 0xE000 < h1e7c0_hot_end <= 0xE500, (
        "escbank3 h1e7c0_hot crossed the fixed $01E7C0 X-helper slots"
    )
    assert (
        0xE000
        < h1e7c0_hot_timer_delta_select
        < h1e7c0_hot_timer_delta_ready
        < h1e7c0_hot_end
    ), "$01E7C0 mode-dependent object-timer delta moved outside its hot body"
    assert ESC3[
        h1e7c0_hot_timer_delta_select - 0x8000:
        h1e7c0_hot_timer_delta_ready - 0x8000
    ] == bytes.fromhex("af322940ebf007a90200858e641e"), (
        "$01E7C0 hot path no longer selects timer delta 2 while $2932 is "
        "active or no longer clears D7's MOVEQ high word"
    )
    assert ESC3[
        h1e7c0_hot_end - 0x8000:0x6500
    ] == bytes(0xE500 - h1e7c0_hot_end), (
        "escbank3 h1e7c0_hot has nonzero overlap before the X helpers"
    )
    x_helper_slots = (
        ("h1e7c0_x_sub_d2_9e", "h1e7c0_x_sub_d2_9e_end", 0xE500, 0xE520),
        ("h1e7c0_x_sub_d4_9e", "h1e7c0_x_sub_d4_9e_end", 0xE520, 0xE540),
        (
            "h1e7c0_x_sub_d2_0078",
            "h1e7c0_x_sub_d2_0078_end",
            0xE540,
            0xE560,
        ),
        (
            "h1e7c0_x_sub_d2_0010",
            "h1e7c0_x_sub_d2_0010_end",
            0xE560,
            0xE580,
        ),
        (
            "h1e7c0_x_sub_d7_0001",
            "h1e7c0_x_sub_d7_0001_end",
            0xE580,
            0xE5A0,
        ),
        (
            "h1e7c0_x_add_be_351c",
            "h1e7c0_x_add_be_351c_end",
            0xE5A0,
            0xE5C0,
        ),
    )
    for helper, helper_end, start, end in x_helper_slots:
        assert esc3_off(helper) == start, (
            "escbank3 %s moved from its pinned $97:%04X slot"
            % (helper, start)
        )
        resolved_end = esc3_off(helper_end)
        assert start < resolved_end <= end, (
            "escbank3 %s crossed its $97:%04X-$%04X slot"
            % (helper, start, end)
        )
        assert ESC3[
            resolved_end - 0x8000:end - 0x8000
        ] == bytes(end - resolved_end), (
            "escbank3 %s left nonzero overlap after its end symbol" % helper
        )
    campaign_irq_reload = esc3_off("campaign_irq_reload")
    campaign_irq_reload_end = esc3_off("campaign_irq_reload_end")
    h25110_native_guard = esc3_off("h25110_native_guard")
    h25110_native_guard_end = esc3_off("h25110_native_guard_end")
    h25110_yield_2582a = esc3_off("h25110_yield_2582a")
    h25110_yield_end = esc3_off("h25110_yield_end")
    entry_25110_resume_2582a = esc3_off("entry_25110_resume_2582a")
    entry_25110_resume_end = esc3_off("entry_25110_resume_end")
    esc3_ac_charge_1 = esc3_off("esc3_ac_charge_1")
    esc3_ac_charge_end = esc3_off("esc3_ac_charge_end")
    assert (
        campaign_irq_reload == 0xE5C0
        < campaign_irq_reload_end
        == h25110_native_guard
        < h25110_native_guard_end
        == h25110_yield_2582a
        < h25110_yield_end
        == entry_25110_resume_2582a
        < entry_25110_resume_end
        == esc3_ac_charge_1
        < esc3_ac_charge_end
        <= 0xE800
    ), (
        "campaign IRQ/yield/resume/charge helpers moved, reordered, or crossed "
        "entry_cb9e@$97:E800"
    )
    assert (
        esc3_ac_charge_end <= 0xE680
        and esc3_ac_charge_vtime_gateway == 0xE680
        < h25110_vtime_entry_gateway
        < h25110_vtime_finish_gateway
        < esc3_vtime_gateway_end
        <= 0xE700
    ), "VTIME-only bank-$97 gateway moved or crossed its reserved seam"
    assert ESC3[esc3_ac_charge_end - 0x8000:0x6680] == bytes(
        0xE680 - esc3_ac_charge_end
    ), "campaign IRQ helpers overlap the VTIME-only gateway seam"
    assert ESC3[esc3_vtime_gateway_end - 0x8000:0x6800] == bytes(
        0xE800 - esc3_vtime_gateway_end
    ), "VTIME-only gateway overlaps entry_cb9e@$97:E800"
    assert ESC3[
        h25110_canonical_a5 - 0x8000:h25110_canonical_a5 - 0x8000 + 3
    ] == bytes((0x20, esc3_ac_charge_2 & 0xFF, esc3_ac_charge_2 >> 8)), (
        "$025110 default entry charge is no longer a patchable same-bank JSR"
    )
    assert ESC3[
        esc3_ac_charge_legacy_load - 0x8000:esc3_ac_charge_legacy_load - 0x8000 + 3
    ] == bytes.fromhex("a5ac38"), (
        "$025110 default legacy charge load/seC seam changed"
    )
    assert ESC3[
        h25110_vtime_finish_source - 0x8000:h25110_vtime_finish_source - 0x8000 + 4
    ] == bytes.fromhex("5c") + ors_pre_target.to_bytes(2, "little") + bytes([0x00]), (
        "$025110 default RTS tail is no longer a patchable ors_pre JML"
    )
    # Every bank-$97 hot-helper exit into the generated bank-$98 body must be
    # assembled from the current escbank4 symbols.  Byte-width fixes can move
    # these targets; stale numeric JMLs previously survived assembly and sent
    # organic collision/render execution into the middle of instructions.
    esc4_symbols_for_cross = Path("src/escbank4.sym").read_text(
        encoding="utf-8-sig"
    )
    def esc4_cross_off(symbol):
        for line in esc4_symbols_for_cross.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError(
            "missing escbank4 cross-bank layout symbol %s" % symbol
        )

    for cross_symbol in (
        "L1e7c0_1e7cc",
        "L1e7c0_1e94a",
        "L1e7c0_1ee3a",
        "br1e7c0_10",
        "Lf1e7c0_227",
        "entry_d96t",
    ):
        target = esc4_cross_off(cross_symbol)
        encoded_jml = bytes((0x5C, target & 0xFF, target >> 8, 0x98))
        assert ESC3.count(encoded_jml) == 1, (
            "escbank3 $01E7C0 helper does not contain exactly one current "
            "JML to escbank4 %s@$98:%04X" % (cross_symbol, target)
        )
    # The guarded callable CB9E helper is pinned at $7A00 ($97:FA00).
    # Resolve the generated physics body's explicit end symbol so a faithful
    # lowering may change size without weakening Poppy's overlap guard.
    entry_1d5f0_end = esc3_off("entry_1d5f0_end")
    assert 0xEC00 < entry_1d5f0_end <= 0xFA00, (
        "escbank3 entry_1d5f0 crossed hcb9e_fast@$97:FA00"
    )
    assert ESC3[
        entry_1d5f0_end - 0x8000:0x7A00
    ] == bytes(0xFA00 - entry_1d5f0_end), (
        "escbank3 entry_1d5f0 has nonzero overlap before hcb9e_fast; "
        "relocate code instead of allowing .org overlap"
    )
    assert ESC3[0x7C48:0x7C60] == bytes(0x18), (
        "escbank3 hcb9e_fast helpers grew into the $FC48-$FC5F seam before "
        "entry_1f1c0t; relocate code instead of allowing .org overlap"
    )
    esc3_packed = bytearray(ESC3)
    vtime_irq_reload = bytes.fromhex("5c0085f2eaeaeaea")
    legacy_irq_reload = bytes.fromhex("c230a9007085ac6b")
    irq_reload_offset = campaign_irq_reload - 0x8000
    assert ESC3[irq_reload_offset:irq_reload_offset + len(vtime_irq_reload)] == (
        vtime_irq_reload
    ), "campaign IRQ reload no longer has the patchable VTIME gateway footprint"
    if vtime_enabled:
        # Keep VTIME completely out of the production native path.  The three
        # substitutions are source-byte asserted above and target fixed local
        # gateways; only the diagnostic ROM executes their cross-bank JSLs.
        esc3_packed[
            h25110_canonical_a5 - 0x8000:h25110_canonical_a5 - 0x8000 + 3
        ] = bytes((0x20, h25110_vtime_entry_gateway & 0xFF, h25110_vtime_entry_gateway >> 8))
        esc3_packed[
            esc3_ac_charge_legacy_load - 0x8000:esc3_ac_charge_legacy_load - 0x8000 + 3
        ] = bytes((0x20, esc3_ac_charge_vtime_gateway & 0xFF, esc3_ac_charge_vtime_gateway >> 8))
        esc3_packed[
            h25110_vtime_finish_source - 0x8000:h25110_vtime_finish_source - 0x8000 + 4
        ] = bytes(
            (0x5C, h25110_vtime_finish_gateway & 0xFF,
             h25110_vtime_finish_gateway >> 8, 0x97)
        )
    else:
        # The production interrupt path must use the old local $7000 reload,
        # not make an otherwise-disabled F2 JML/RTL round trip every IRQ.
        # This exact eight-byte sequence is the accepted f369 implementation.
        esc3_packed[
            irq_reload_offset:irq_reload_offset + len(legacy_irq_reload)
        ] = legacy_irq_reload
    ROM[0x2B8000:0x2B8000+len(esc3_packed)] = esc3_packed  # @ SA-1 $97:8000 (file $2B8000)

# --- FIFTH SA-1 escape bank ($99:8000, file $2C8000) ---
# The $023-25xxx trap#5-cluster SHELL segments (coroutine yield-loop bodies + their callees;
# CP1 item 2.3). Resume PCs dispatch via bank-$02 xlat pages; $00FA call-bridge sentinel.
if _osp.exists("src/escbank5.bin"):
    ESC5 = Path("src/escbank5.bin").read_bytes()
    assert len(ESC5) <= 0x8000, ("escbank5 %d bytes overflows the $2C8000..$2D0000 bank" % len(ESC5))
    assert ESC5[0x0B59:0x0B67] == bytes.fromhex("5c808f98" + "ea" * 10), (
        "escbank5 entry_23e34 guarded redirect moved or changed size"
    )
    assert "00:A4E1 entry_4a9e" in Path("src/escbank5.sym").read_text(), (
        "escbank4 entry_c7dc hard link is stale: escbank5 entry_4a9e moved from $99:A4E1"
    )
    esc5_symbols = Path("src/escbank5.sym").read_text()
    assert "00:C200 entry_96a" in esc5_symbols, (
        "palette-transition escape moved from the audited $99:C200 gap"
    )
    assert "00:C500 entry_9ea" in esc5_symbols, (
        "round-transition escape moved from the audited $99:C500 gap"
    )
    assert ESC5[0x4200:0x4204] == bytes.fromhex("5c00a095"), (
        "entry_96a lost its size-neutral JML $95:A000 wrapper"
    )
    assert "00:C204 h96a_generated_resume" in esc5_symbols, (
        "entry_96a generated fallback seam moved from $99:C204"
    )
    assert ESC5[0x4204:0x4206] == bytes.fromhex("8554"), (
        "entry_96a generated fallback no longer resumes at STA $54"
    )
    assert ESC5[0x415A:0x4200] == bytes(0x00A6), (
        "entry_77a grew into the fixed $99:C200 palette-stepper slot"
    )
    assert ESC5[0x4481:0x4500] == bytes(0x007F), (
        "entry_96a grew into the fixed $99:C500 round-transition slot"
    )
    assert ESC5[0x4500:0x4504] == bytes.fromhex("5c00a695"), (
        "entry_9ea lost its size-neutral JML $95:A600 wrapper"
    )
    assert "00:C504 h9ea_generated_resume" in esc5_symbols, (
        "entry_9ea generated fallback seam moved from $99:C504"
    )
    assert ESC5[0x4504:0x4506] == bytes.fromhex("8554"), (
        "entry_9ea generated fallback no longer resumes at STA $54"
    )
    assert ESC5[0x4662:0x4900] == bytes(0x029E), (
        "entry_9ea grew into the $99:C662-$C8FF seam before the round-start roots"
    )
    def esc5_off(symbol):
        for line in esc5_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank5 layout symbol %s" % symbol)

    esc5_root_2429c = esc5_off("entry_2429c")
    assert ESC5[
        esc5_root_2429c - 0x8000:esc5_root_2429c - 0x8000 + 4
    ] == bytes.fromhex("c230a534"), (
        "$02429C production entry lost its VTIME-only patchable REP/LDA seam"
    )
    assert esc5_off("entry_24cb6") == esc5_off("L24bc2_24cb6"), (
        "$024CB6 exported continuation no longer aliases the original native loop seam"
    )
    long_or_region = ESC5[
        esc5_off("entry_24cb6") - 0x8000:
        esc5_off("Ltj24bc2_24bc0") - 0x8000
    ]
    assert bytes.fromhex(
        "a50405008504"  # ORA $00 / D1.lo
        "a50405088504"  # ORA $08 / D2.lo
        "a506050a8506"  # ORA $0A / D2.hi
        "a504859aa506859c"
    ) in long_or_region, (
        "$024CB6 lost the high-word half of OR.L D2,D1; task spawn arguments "
        "would silently lose their 16.16 integer component"
    )
    d28_stub = esc5_off("Ltj24bc2_24d28") - 0x8000
    assert ESC5[d28_stub:d28_stub + 16].count(bytes.fromhex("5c00da9d")) == 1, (
        "$024D28 parent tail no longer routes through sparse dispatcher $9D:DA00"
    )

    assert esc5_off("br2429c_1") == 0x85F8, (
        "$02429C br2429c_1 moved; update the bank-$98 fused-helper constant"
    )
    assert esc5_off("br2429c_3") == 0x8613, (
        "$02429C br2429c_3 moved; update the bank-$98 fused-helper constant"
    )
    assert esc5_off("entry_242be") == esc5_off("br2429c_4"), (
        "$0242BE xlat return no longer aliases the native post-$25110 continuation"
    )
    if _osp.exists("src/xlat_table.bin"):
        ret_242be_page = (0x0242BE >> 8) & 0x3FF
        ret_242be_page_slot = ret_242be_page * 2
        ret_242be_subtable = int.from_bytes(
            XLAT[ret_242be_page_slot:ret_242be_page_slot + 2],
            "little",
        )
        assert ret_242be_subtable != 0, (
            "$0242BE xlat page vanished; native $025110 cannot return to its caller"
        )
        ret_242be_slot = ret_242be_subtable + ((0x0242BE & 0xFF) * 3)
        ret_242be_target = (0x990000 | esc5_off("entry_242be")).to_bytes(
            3, "little"
        )
        assert XLAT[ret_242be_slot:ret_242be_slot + 3] == ret_242be_target, (
            "$0242BE xlat slot no longer targets the bank-$99 post-$25110 continuation"
        )
    assert esc5_off("br23e34_1") == 0x8C04, (
        "$23E34 inner return moved; update the bank-$98 fused-helper constant"
    )
    fused_redirect = esc5_off("Lf2429c_1") - 0x8000
    assert ESC5[fused_redirect:fused_redirect + 14] == bytes.fromhex(
        "5c538e98" + "ea" * 10
    ), "$02429C fused empty-helper redirect moved or changed size"
    collision_cmp_start = esc5_off("Lf2429c_20") - 0x8000
    collision_cmp_end = esc5_off("Lf2429c_21") - 0x8000
    assert bytes.fromhex(
        # MOVE.B $18(A4),D1 preserves D1.bits8-31.  The following CMPI.B
        # must therefore execute with M=8; REP deliberately preserves its Z
        # result for BEQ.  A 16-bit SBC here caused the organic tick-12070
        # collision-row retirement failure when D1.w was $0105.
        "e2208504c220"      # SEP; STA $04; REP
        "a504e220c905c220"  # LDA $04; SEP; CMP #$05; REP
    ) in ESC5[collision_cmp_start:collision_cmp_end], (
        "$02429C collision cleanup lost byte-width CMPI.B #5,D1 semantics"
    )
    collision_fallthrough = esc5_off("L2429c_243b8") - 0x8000
    assert bytes.fromhex("8504859a") in ESC5[
        collision_fallthrough:collision_fallthrough + 20
    ], (
        "$02429C width repair lost its size-neutral D1 sign-extension store; "
        "following bank-$99 symbols may have moved"
    )

    round_roots = ["entry_c262", "entry_8d72", "entry_c3f6", "entry_7c22", "entry_ce48"]
    round_offsets = [esc5_off(symbol) for symbol in round_roots]
    assert round_offsets[0] == 0xC900 and round_offsets == sorted(round_offsets), (
        "round-start roots no longer form the ordered packed group beginning at $99:C900"
    )
    c262_resume = esc5_off("entry_c262_generated_resume")
    c262_generated_exit = esc5_off("Lfc262_2")
    c262_end = esc5_off("round_c262_end")
    assert c262_resume == 0xC906 and c262_generated_exit == 0xCBF6 and c262_end == 0xCC04, (
        "$C262 wrapper/resume/exit seams moved inside the packed round-root group"
    )
    assert ESC5[0x4900:0x4906] == bytes.fromhex("5c00a395eaea"), (
        "entry_c262 lost its fixed JML $95:A300 wrapper"
    )
    assert ESC5[0x4906:0x4908] == bytes.fromhex("a534"), (
        "$C262 generated fallback no longer resumes at LDA $34"
    )
    assert ESC5[0x4BF6:0x4C04] == bytes.fromhex("5c00af95" + "ea" * 10), (
        "$C262 generated exit no longer reaches the fixed $95:AF00 residue finisher"
    )
    for symbol, offset in zip(round_roots[1:], round_offsets[1:]):
        file_offset = offset - 0x8000
        assert ESC5[file_offset:file_offset + 2] == bytes.fromhex("c230"), (
            "%s lost its REP #$30 prologue or was overwritten by a Poppy .org overlap" % symbol
        )
    round_end = esc5_off("round_pool_alloc_end")
    assert round_offsets[-1] < round_end <= 0xEB00, (
        "round-start native group crossed the pinned entry_d232@$99:EB00 boundary"
    )
    rom_helper = esc5_off("rdw_rom_8d72_l")
    rom_helper_end = esc5_off("rdw_rom_8d72_end")
    assert rom_helper == round_end == 0xE6EF and rom_helper_end == 0xE6FF, (
        "$8D72 direct-ROM helper moved from its audited $99:E6EF-$E6FE slot"
    )
    assert ESC5[0x66EF:0x66FF] == bytes.fromhex(
        "a5548566a5521869c1008568a766eb6b"
    ), "$8D72 direct-ROM helper bytes changed or were overwritten"
    hle_2742 = esc5_off("hle_2742")
    hle_2742_end = esc5_off("hle_2742_end")
    assert hle_2742 == rom_helper_end == 0xE6FF and hle_2742_end <= 0xEB00, (
        "$2742 HLE moved from $99:E6FF or crossed entry_d232@$99:EB00"
    )
    entry_2742 = esc5_off("entry_2742t")
    entry_2742_resume = esc5_off("entry_2742_generated_resume")
    round_2742_end = esc5_off("round_2742t_end")
    assert ESC5[entry_2742 - 0x8000:entry_2742 - 0x8000 + 4] == bytes.fromhex(
        "5cffe699"
    ), "entry_2742t lost its size-neutral JML $99:E6FF wrapper"
    assert entry_2742_resume == 0xDE12 and round_2742_end == 0xE2C5, (
        "$2742 generated fallback or following round-start layout moved"
    )
    generic_read = bytes.fromhex(
        "a52c186900008554a52e690000855222b2e500eaeaea"
    )
    for symbol in ("L2742_277c", "L2742_27a4"):
        offset = esc5_off(symbol) - 0x8000
        assert ESC5[offset:offset + len(generic_read)] == generic_read, (
            "%s lost its generic rdw_ea_l source read or size-neutral padding" % symbol
        )
    assert ESC5[round_2742_end - 0x8000 - 4:round_2742_end - 0x8000] == bytes.fromhex(
        "5c00e999"
    ), "$2742 generated fallback no longer exits through $99:E900 CCR shim"
    assert ESC5[hle_2742 - 0x8000:hle_2742 - 0x8000 + 6] == bytes.fromhex(
        "c2302280de9e"
    ), "$2742 guarded HLE lost its size-neutral native BG-dirty publication"
    hle_fallback_end = esc5_off("h2742_generated_fallback_end")
    hle_generic_return = esc5_off("h2742_generated_return")
    assert hle_fallback_end == 0xE8E3 and hle_generic_return == 0xE900, (
        "$2742 generic-fallback tail or CCR shim moved"
    )
    assert ESC5[hle_fallback_end - 0x8000:hle_generic_return - 0x8000] == bytes(
        hle_generic_return - hle_fallback_end
    ), "$2742 fallback grew into the zero seam before its pinned CCR shim"
    assert hle_2742_end == 0xE95B, "$2742 guarded HLE/fallback end moved"
    assert ESC5[hle_generic_return - 0x8000:hle_generic_return - 0x8000 + 4] == bytes.fromhex(
        "c230a63c"
    ), "$2742 generic-fallback CCR shim prologue changed"
    assert ESC5[hle_2742_end - 0x8000 - 4:hle_2742_end - 0x8000] == bytes.fromhex(
        "5c6fd100"
    ), "$2742 generic-fallback CCR shim no longer returns through ors_pre"
    validation_spin = esc5_off("h2742_validation_spin")
    validation_spin_end = esc5_off("h2742_validation_spin_end")
    seam_start = hle_2742_end - 0x8000
    spin_start = validation_spin - 0x8000
    spin_end = validation_spin_end - 0x8000
    assert validation_spin == 0xEAF0 and validation_spin_end == 0xEAF2, (
        "$2742 synthetic completion spin moved from $99:EAF0-$EAF1"
    )
    assert ESC5[seam_start:spin_start] == bytes(spin_start - seam_start), (
        "$2742 HLE has nonzero overlap before its synthetic completion spin"
    )
    assert ESC5[spin_start:spin_end] == bytes.fromhex("80fe"), (
        "$99:EAF0 synthetic completion spin no longer preserves post-return state"
    )
    assert ESC5[spin_end:0x6B00] == bytes(0x6B00 - spin_end), (
        "$2742 completion spin has nonzero overlap before entry_d232@$99:EB00"
    )
    # cmpw5_fix currently ends at $F7C0; hle_158e is fixed at $F800. Poppy
    # silently permits a flowing section to overlap a later .org, so retain an
    # explicit zero seam between them before packing bank $99.
    assert ESC5[0x77C0:0x7800] == bytes(0x40), (
        "escbank5 cmpw5_fix grew into the $F7C0-$F7FF seam before hle_158e; "
        "relocate code instead of allowing .org overlap"
    )
    assert ESC5[0x7800:0x7804] == bytes.fromhex("5c00889d"), (
        "fixed $99:F800 hle_158e hook lost its JML $9D:8800 relocation"
    )
    assert ESC5[0x78F7:0x7900] == bytes(0x09), (
        "escbank5 hle_158e grew into the $F8F7-$F8FF seam before lea_pc5; "
        "relocate code instead of allowing .org overlap"
    )
    assert ESC5[0x7AD6:0x7B00] == bytes(0x2A), (
        "escbank5 scheduler MOVEM helper grew into the $FAD6-$FAFF seam before "
        "lh_0818_paced; relocate code instead of allowing .org overlap"
    )
    assert ESC5[0x7B00:0x7B04] == bytes.fromhex("ad3407d0"), (
        "production $0818 pacing handler moved from $99:FB00"
    )
    assert ESC5[0x7B7E:0x7B84] == bytes.fromhex("c90b9002a90a"), (
        "production pacing no longer saturates catch-up debt at ten frames"
    )
    paced_end = esc5_off("lh_0818_paced_end")
    paced_gateway = esc5_off("lh_0818_vtime_gateway")
    paced_gateway_end = esc5_off("lh_0818_vtime_gateway_end")
    paced_release = esc5_off("lhp_vtime_release_seam")
    charge_12b6c = esc5_off("h11752_charge_12b6c")
    charge_12b6c_end = esc5_off("h11752_charge_12b6c_end")
    task24bc2_ccr = esc5_off("h24bc2_tst_zero_yield")
    task24bc2_ccr_end = esc5_off("h24bc2_tst_zero_yield_end")
    h13be_inext = esc5_off("h13be_exit_flags_inext")
    h13be_inext_end = esc5_off("h13be_exit_flags_inext_end")
    h13be_write = esc5_off("h13be_writeword_flags")
    h13be_write_end = esc5_off("h13be_writeword_flags_end")
    h13be_ors = esc5_off("h13be_exit_flags_ors")
    h13be_ors_end = esc5_off("h13be_exit_flags_ors_end")
    c846_clear = esc5_off("hc846_clear_nzvc")
    c846_clear_end = esc5_off("hc846_clear_nzvc_end")
    c846_z = esc5_off("hc846_z_preserve_x")
    c846_z_end = esc5_off("hc846_z_preserve_x_end")
    c846_tst = esc5_off("hc846_tst_d7")
    c846_tst_end = esc5_off("hc846_tst_d7_end")
    h13be_table_store = esc5_off("h13be_store_flags_table")
    h13be_table_store_end = esc5_off("h13be_store_flags_table_end")
    task24bc2_cmp = esc5_off("h24bc2_cmp_d1_d0_yield")
    task24bc2_cmp_end = esc5_off("h24bc2_cmp_d1_d0_yield_end")
    task24bc2_tst_word = esc5_off("h24bc2_tst_word_zero_yield")
    task24bc2_tst_word_end = esc5_off(
        "h24bc2_tst_word_zero_yield_end"
    )
    task24bc2_tst_byte = esc5_off(
        "h24bc2_tst_byte_nonzero_yield"
    )
    task24bc2_tst_byte_end = esc5_off(
        "h24bc2_tst_byte_nonzero_yield_end"
    )
    task24bc2_move_byte = esc5_off(
        "h24bc2_move_byte_one_yield"
    )
    task24bc2_move_byte_end = esc5_off(
        "h24bc2_move_byte_one_yield_end"
    )
    task2429c_tst_byte = esc5_off("h2429c_tst_byte19_branch")
    task2429c_tst_byte_end = esc5_off("h2429c_tst_byte19_branch_end")
    task259ca_tst_byte = esc5_off("h259ca_tst_byte_branch")
    task259ca_tst_byte_end = esc5_off("h259ca_tst_byte_branch_end")
    assert (
        paced_end <= paced_gateway == 0xFBB0
        and paced_gateway < paced_gateway_end <= 0xFBE0
        and charge_12b6c == 0xFBE0
        and charge_12b6c_end == task24bc2_ccr
        and task24bc2_ccr_end == h13be_inext == 0xFC0C
        and h13be_inext_end == h13be_write == 0xFC10
        and h13be_write_end <= h13be_ors == 0xFC2C
        and h13be_ors_end <= c846_clear == 0xFC46
        and c846_clear_end == c846_z
        and c846_z_end == c846_tst
        and c846_tst_end == h13be_table_store == 0xFC7B
        and h13be_table_store_end <= 0xFCA0
        and task24bc2_cmp == 0xFCA0
        and task24bc2_cmp_end <= task24bc2_tst_word == 0xFCD0
        and task24bc2_tst_word_end == task24bc2_tst_byte
        and task24bc2_tst_byte_end == task24bc2_move_byte
        and task24bc2_move_byte_end <= 0xFD00
        and task2429c_tst_byte == 0xFD00
        and task2429c_tst_byte_end == task259ca_tst_byte
        and task259ca_tst_byte_end <= 0xFD40
    ), (
        "$11752/$24BC2/$13BE/$C78E/$C7DC/$C846 terminal island layout "
        "moved, or $0818 pacing grew into its $99:FBE0 island"
    )
    assert ESC5[
        task24bc2_ccr - 0x8000:task24bc2_ccr_end - 0x8000
    ] == bytes.fromhex("64706472646ea9010085604c9b85"), (
        "$024BC2 TST-zero terminal-CCR island moved or changed"
    )
    assert ESC5[
        h13be_inext - 0x8000:h13be_inext_end - 0x8000
    ] == bytes.fromhex("5c28d100"), (
        "$0013BE direct-entry terminal bridge moved or changed"
    )
    assert ESC5[
        h13be_write - 0x8000:h13be_write_end - 0x8000
    ] == bytes.fromhex(
        "22bae500646e647264706460a504f0051002e6706be6606b"
    ), "$0013BE direct write/CCR island moved or changed"
    assert ESC5[
        h13be_ors - 0x8000:h13be_ors_end - 0x8000
    ] == bytes.fromhex("5c6fd100"), (
        "$0013BE table-entry terminal bridge moved or changed"
    )
    assert ESC5[
        c846_clear - 0x8000:c846_clear_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e64605c28d100"
    ), "$00C846 clear-NZVC exit island moved or changed"
    assert ESC5[
        c846_z - 0x8000:c846_z_end - 0x8000
    ] == bytes.fromhex(
        "64706472646ea9010085605c28d100"
    ), "$00C846 Z-preserving exit island moved or changed"
    assert ESC5[
        c846_tst - 0x8000:c846_tst_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e6460a51cf0081002e6705c28d100e6605c28d100"
    ), "$00C846 TST.W-D7 exit island moved or changed"
    assert ESC5[
        h13be_table_store - 0x8000:h13be_table_store_end - 0x8000
    ] == bytes.fromhex(
        "9f00004048646e647264706460a504f0061002e670686be660686b"
    ), "$0013BE table write/CCR island moved or changed"
    assert ESC5[paced_end - 0x8000:paced_gateway - 0x8000] == bytes(
        paced_gateway - paced_end
    ), "$0818 pacing has nonzero overlap before its fallback gateway"
    assert ESC5[
        paced_gateway - 0x8000:paced_gateway_end - 0x8000
    ] == bytes.fromhex(
        "af0080f2290200f0045cc0f5002200fb995c9bf500"
    ), "$0818 fallback gateway moved or lost its pre-mutation mode split"
    assert ESC5[paced_gateway_end - 0x8000:charge_12b6c - 0x8000] == bytes(
        charge_12b6c - paced_gateway_end
    ), "$0818 fallback gateway overlaps the $11752 AC-charge tail"
    assert ESC5[
        h13be_write_end - 0x8000:h13be_ors - 0x8000
    ] == bytes(h13be_ors - h13be_write_end), (
        "$0013BE direct write helper overlaps its fixed table bridge"
    )
    assert ESC5[
        h13be_ors_end - 0x8000:c846_clear - 0x8000
    ] == bytes(c846_clear - h13be_ors_end), (
        "$0013BE table bridge overlaps the fixed $00C846 helpers"
    )
    assert (
        ESC5.count(bytes.fromhex("5c46fc99")) == 4
        and ESC5.count(bytes.fromhex("5c52fc99")) == 2
        and ESC5.count(bytes.fromhex("5c61fc99")) == 2
    ), (
        "escbank5 entry_c78e/entry_c846 lost a source-specific "
        "terminal-CCR route"
    )
    assert ESC5[
        h13be_table_store_end - 0x8000:task24bc2_cmp - 0x8000
    ] == bytes(task24bc2_cmp - h13be_table_store_end), (
        "$024BC2 CMP terminal bridge overlaps the $0013BE table write helper"
    )
    assert ESC5[
        task24bc2_cmp_end - 0x8000:task24bc2_tst_word - 0x8000
    ] == bytes(task24bc2_tst_word - task24bc2_cmp_end), (
        "$024BC2 source-specific terminal bridges overlap at $99:FCD0"
    )
    assert ESC5[
        task24bc2_cmp - 0x8000:task24bc2_cmp_end - 0x8000
    ] == bytes.fromhex(
        "08e22068c23029ff0085502902008560a5502980008570"
        "a5502940008572a550290100490100856e4cc585"
    ), "$024BC2 CMP/BGT terminal-CCR bridge moved or changed"
    assert ESC5[
        task24bc2_tst_word - 0x8000:task24bc2_tst_word_end - 0x8000
    ] == bytes.fromhex(
        "64706472646ea9010085604cc585"
    ), "$024BC2 TST.W-zero terminal-CCR bridge moved or changed"
    assert ESC5[
        task24bc2_tst_byte - 0x8000:task24bc2_tst_byte_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e6460298000f002e6704cc585"
    ), "$024BC2 TST.B-nonzero terminal-CCR bridge moved or changed"
    assert ESC5[
        task24bc2_move_byte - 0x8000:task24bc2_move_byte_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e64604cc585"
    ), "$024BC2 MOVE.B-one terminal-CCR bridge moved or changed"
    assert ESC5[
        task2429c_tst_byte - 0x8000:task2429c_tst_byte_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e646029ff00f00a298000f002e6704c9286e6604c2f8b"
    ), "$02429C inactive-record TST.B terminal-CCR bridge moved or changed"
    assert ESC5[
        task259ca_tst_byte - 0x8000:task259ca_tst_byte_end - 0x8000
    ] == bytes.fromhex(
        "64706472646e646029ff00f00a298000f002e6704ce896e6604c5e98"
    ), "$0259CA inactive-record TST.B terminal-CCR bridge moved or changed"
    assert len(ESC5) == task259ca_tst_byte_end - 0x8000, (
        "escbank5 data unexpectedly follows the terminal-CCR bridges"
    )
    assert paced_release == 0xFBA1 and ESC5[
        paced_release - 0x8000:paced_release - 0x8000 + 5
    ] == bytes.fromhex("a9010085ac"), (
        "$0818 release no longer has the VTIME-only patchable legacy `$AC` seam"
    )
    esc5_packed = bytearray(ESC5)
    if vtime_enabled:
        # Route only the opt-in diagnostic through the complete bank-$F3 copy.
        # Its child calls carry real return PCs and the patched sparse xlat
        # front end maps those eleven exact returns back to F3 continuations.
        esc5_packed[
            esc5_root_2429c - 0x8000:esc5_root_2429c - 0x8000 + 4
        ] = bytes.fromhex("5c0080f3")
        # `$0818` has already completed its real S-CPU/NMI wait here.  Only
        # the opt-in diagnostic routes that hardware deadline into VTIME; the
        # normal image retains the exact legacy instruction-count write.
        esc5_packed[
            paced_release - 0x8000:paced_release - 0x8000 + 5
        ] = bytes((
            0x22,
            vtime_off("vtime_paced_release") & 0xFF,
            vtime_off("vtime_paced_release") >> 8,
            0xF2,
            0xEA,
        ))
        # The old `$0818` interpreter-fallback experiment keyed directly on
        # interpreter-only bit 1 and therefore bypassed the complete S-CPU/NMI
        # input/render rendezvous in every interpreter-only VTIME image. Keep
        # the source/ordinary ROM bytes exact, but make that rejected experiment
        # require its own opt-in bit 2 in packed VTIME images. Default
        # interpreter-only mode retains the hardware wait and VTIME release.
        gateway_mode_immediate = paced_gateway - 0x8000 + 5
        assert esc5_packed[gateway_mode_immediate] == 0x02
        esc5_packed[gateway_mode_immediate] = 0x04
    ROM[0x2C8000:0x2C8000+len(esc5_packed)] = esc5_packed  # @ SA-1 $99:8000

# --- TAD audio-data blob (sound port P3: 21 songs + real samples, multi-bank) ---
# Self-contained: [loader.bin(116)][audio-driver.bin(3218)][DataTable][common+21 songs]. Placed at
# file $2D002B = 5A22 HiROM $ED:002B — segment offset 43, mirroring stock ca65's
# [43-byte LoadAudioData proc][blob] layout so the DataTable's segment-relative u24 entries resolve
# UNSKEWED (far addr = $ED:0000 + entry; map mode $31 keeps $C0-$FF file-linear across banks
# $ED/$EE/...). The ported LoadAudioData/Tad_Init upload it to the SPC700. Regen with
# soundwork/tad/build_blob.sh (also generates build/tad_blob_syms.pasm for tad_glue.pasm).
if _osp.exists("soundwork/tad/build/audio-data.bin"):
    TADBLOB = Path("soundwork/tad/build/audio-data.bin").read_bytes()
    assert 0x2D002B + len(TADBLOB) <= 0x400000, ("TAD blob %d bytes overflows the ROM" % len(TADBLOB))
    ROM[0x2D002B:0x2D002B+len(TADBLOB)] = TADBLOB     # @ 5A22 $ED:002B (file $2D002B)

# --- SEVENTH SA-1 escape bank ($9D:8000, file $2E8000) ---
# The TAD blob currently ends at file $2E6D76.  Refuse to pack this bank if a
# regenerated audio project ever reaches its first byte; silent overlap would
# corrupt both sound data and native code.
if _osp.exists("src/escbank7.bin"):
    ESC7 = Path("src/escbank7.bin").read_bytes()
    assert len(ESC7) <= 0x8000, (
        "escbank7 %d bytes overflows the $2E8000..$2F0000 bank" % len(ESC7)
    )
    if _osp.exists("soundwork/tad/build/audio-data.bin"):
        assert 0x2D002B + len(TADBLOB) <= 0x2E8000, (
            "TAD blob overlaps escbank7 at file $2E8000"
        )
    esc7_symbols = Path("src/escbank7.sym").read_text(encoding="utf-8-sig")
    def esc7_off(symbol):
        for line in esc7_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank7 layout symbol %s" % symbol)

    assert "00:8000 escbank7_begin" in esc7_symbols, (
        "escbank7 no longer begins at mapped SA-1 $9D:8000"
    )
    assert "00:8000 h25110_stage2_try" in esc7_symbols, (
        "$25110 stage-2 helper moved from its fixed redirect target"
    )
    assert "00:8200 h25110_stage5_inactive_try" in esc7_symbols, (
        "$25110 stage-5 helper moved from its fixed redirect target"
    )
    assert "00:8400 hfast_rte_entry" in esc7_symbols, (
        "scheduler fast-RTE helper moved from its fixed $9D:8400 redirect target"
    )
    hfr_bank1 = esc7_off("hfr_bank1")
    hfr_bank2 = esc7_off("hfr_bank2")
    hfr_bank1_blob = ESC7[hfr_bank1 - 0x8000:hfr_bank2 - 0x8000]
    assert hfr_bank1_blob.count(bytes.fromhex("c9f1d5")) == 1, (
        "$01D5F0 parking guard no longer uses the impossible aligned-PC "
        "selector CMP #$D5F1"
    )
    assert bytes.fromhex("c9f0d5") not in hfr_bank1_blob, (
        "$01D5F0 unsafe physics coroutine became reachable through fast RTE"
    )
    assert "00:87C0 hobj_capture_reset" in esc7_symbols, (
        "paced OBJ token reset moved from fixed $9D:87C0"
    )
    assert "00:8800 h158_esc7" in esc7_symbols, (
        "relocated hle_158e body moved from fixed $9D:8800"
    )
    assert "00:8A00 entry_2ad4ct" in esc7_symbols, (
        "$02AD4C table wrapper moved from fixed $9D:8A00"
    )
    assert "00:9000 entry_2a86et" in esc7_symbols, (
        "$02A86E table body moved from fixed $9D:9000"
    )
    assert ESC7[0x400:0x404] == bytes.fromhex("c230ad1a"), (
        "scheduler fast-RTE helper prologue changed unexpectedly"
    )
    assert ESC7[0:5] == bytes.fromhex("c230ad3407"), (
        "$25110 stage-2 helper lost its explicit paced-path gate"
    )
    assert ESC7[0x200:0x205] == bytes.fromhex("c230ad3407"), (
        "$25110 stage-5 helper lost its explicit paced-path gate"
    )
    hfr_bank2_blob = ESC7[
        hfr_bank2 - 0x8000:esc7_off("hfr_b2_miss") - 0x8000
    ]
    for resume_cmp in ("c92a58", "c92e58", "c9b059"):
        assert hfr_bank2_blob.count(bytes.fromhex(resume_cmp)) == 1, (
            "$25110 mid-routine resume selector missing from scheduler fast RTE"
        )
    hfast_rte_end = esc7_off("hfast_rte_end")
    assert 0x8400 < hfast_rte_end <= 0x87C0, (
        "scheduler fast-RTE body crossed the paced OBJ reset seam"
    )
    assert ESC7[hfast_rte_end - 0x8000:0x7C0] == bytes(
        0x7C0 - (hfast_rte_end - 0x8000)
    ), (
        "scheduler fast-RTE body grew into the paced OBJ reset seam"
    )
    assert ESC7[0x7C0:0x7C4] == bytes.fromhex("c230ad34"), (
        "paced OBJ reset helper prologue changed unexpectedly"
    )
    assert ESC7[0x7CF:0x800] == bytes(0x0031), (
        "paced OBJ reset helper grew into hle_158e@$9D:8800"
    )
    assert ESC7[0x800:0x806] == bytes.fromhex("c23022c0879d"), (
        "relocated hle_158e prologue lost its explicit mapped reset call"
    )
    h158_end = None
    entry_2ad4ct_end = None
    entry_2a86et_end = None
    h2be2_fast = None
    h2be2_fast_end = None
    hce4_ext_prepare_2x2 = None
    hce4_ext_prepare_2x2_end = None
    h26_unrolled_ordered = None
    h26_unrolled_ordered_end = None
    h3c36_fast = None
    h3c36_fast_end = None
    h2bda_fast = None
    h2bda_fast_end = None
    h1f1c0_fast = None
    h1f1c0_fast_end = None
    h20e8_fast = None
    h20e8_fast_end = None
    h20e8_dma_data = None
    h20e8_dma_data_end = None
    producer_bg_append_range = None
    producer_bg_append_range_end = None
    hcaf6_32fca = None
    hcaf6_32fca_end = None
    entry_2498c = None
    entry_2498c_end = None
    entry_249c2 = None
    entry_249c2_end = None
    entry_1f2e4 = None
    entry_1f2e4_end = None
    for line in esc7_symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "h158_esc7_end":
            h158_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_2ad4ct_end":
            entry_2ad4ct_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_2a86et_end":
            entry_2a86et_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h2be2_fast":
            h2be2_fast = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h2be2_fast_end":
            h2be2_fast_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "hce4_ext_prepare_2x2":
            hce4_ext_prepare_2x2 = int(
                fields[0].split(":", 1)[1], 16
            )
        elif len(fields) >= 2 and fields[1] == "hce4_ext_prepare_2x2_end":
            hce4_ext_prepare_2x2_end = int(
                fields[0].split(":", 1)[1], 16
            )
        elif len(fields) >= 2 and fields[1] == "h26_unrolled_ordered":
            h26_unrolled_ordered = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h26_unrolled_ordered_end":
            h26_unrolled_ordered_end = int(
                fields[0].split(":", 1)[1], 16
            )
        elif len(fields) >= 2 and fields[1] == "h3c36_fast":
            h3c36_fast = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h3c36_fast_end":
            h3c36_fast_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h2bda_fast":
            h2bda_fast = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h2bda_fast_end":
            h2bda_fast_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h1f1c0_fast":
            h1f1c0_fast = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h1f1c0_fast_end":
            h1f1c0_fast_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h20e8_fast":
            h20e8_fast = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h20e8_fast_end":
            h20e8_fast_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h20e8_dma_data":
            h20e8_dma_data = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "h20e8_dma_data_end":
            h20e8_dma_data_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "producer_bg_append_range":
            producer_bg_append_range = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "producer_bg_append_range_end":
            producer_bg_append_range_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "hcaf6_32fca":
            hcaf6_32fca = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "hcaf6_32fca_end":
            hcaf6_32fca_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_2498c":
            entry_2498c = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_2498c_end":
            entry_2498c_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_249c2":
            entry_249c2 = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_249c2_end":
            entry_249c2_end = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_1f2e4":
            entry_1f2e4 = int(fields[0].split(":", 1)[1], 16)
        elif len(fields) >= 2 and fields[1] == "entry_1f2e4_end":
            entry_1f2e4_end = int(fields[0].split(":", 1)[1], 16)
    assert h158_end is not None and h158_end <= 0x8A00, (
        "relocated hle_158e body crossed the $9D:8A00 combat island"
    )
    assert ESC7[h158_end - 0x8000:0x0A00] == bytes(
        0x0A00 - (h158_end - 0x8000)
    ), "nonzero escbank7 bytes overlap the $02AD4C combat island"
    entry_122a4 = esc7_off("entry_122a4")
    entry_122a4_end = esc7_off("entry_122a4_end")
    assert entry_2ad4ct_end is not None and entry_2ad4ct_end <= 0x8D00, (
        "$02AD4C table body crossed the $0122A4 coroutine island"
    )
    assert ESC7[entry_2ad4ct_end - 0x8000:0x0D00] == bytes(
        0x0D00 - (entry_2ad4ct_end - 0x8000)
    ), "nonzero escbank7 bytes overlap entry_122a4@$9D:8D00"
    assert entry_122a4 == 0x8D00 and entry_122a4 < entry_122a4_end <= 0x9000, (
        "$0122A4 coroutine spine moved or crossed entry_2a86et@$9D:9000"
    )
    assert ESC7[entry_122a4 - 0x8000:entry_122a4 - 0x8000 + 4] == bytes.fromhex(
        "c230a53a"
    ), "$0122A4 coroutine spine lost its REP/A6-bank guard"
    assert ESC7[entry_122a4_end - 0x8000:0x1000] == bytes(
        0x1000 - (entry_122a4_end - 0x8000)
    ), "nonzero escbank7 bytes overlap the $02A86E combat island"
    assert ESC7[0x1000:0x1002] == bytes.fromhex("c230"), (
        "$02A86E table body lost its explicit REP #$30 prologue"
    )
    assert entry_2a86et_end is not None and entry_2a86et_end <= 0x9620, (
        "$02A86E table body crossed h2be2_fast@$9D:9620"
    )
    assert ESC7[entry_2a86et_end - 0x8000:0x1620] == bytes(
        0x1620 - (entry_2a86et_end - 0x8000)
    ), "nonzero bank-$9D bytes overlap h2be2_fast@$9D:9620"
    assert h2be2_fast == 0x9620 and h2be2_fast_end is not None, (
        "$2BE2 canonical-work-RAM helper moved from its fixed $9D:9620 island"
    )
    assert h2be2_fast_end <= 0x9800, (
        "$2BE2 canonical-work-RAM helper crossed the $26A0 ordered island"
    )
    assert hce4_ext_prepare_2x2 == 0x9700 and hce4_ext_prepare_2x2_end is not None, (
        "CE4 2x2 preparation helper moved from its fixed $9D:9700 island"
    )
    assert h2be2_fast_end <= hce4_ext_prepare_2x2, (
        "$2BE2 helper crossed the CE4 2x2 preparation island"
    )
    assert ESC7[
        h2be2_fast_end - 0x8000:
        hce4_ext_prepare_2x2 - 0x8000
    ] == bytes(hce4_ext_prepare_2x2 - h2be2_fast_end), (
        "nonzero bank-$9D bytes overlap the CE4 2x2 preparation island"
    )
    assert hce4_ext_prepare_2x2_end <= 0x9800, (
        "CE4 2x2 preparation helper crossed the $26A0 ordered island"
    )
    assert ESC7[hce4_ext_prepare_2x2_end - 0x8000:0x1800] == bytes(
        0x1800 - (hce4_ext_prepare_2x2_end - 0x8000)
    ), "nonzero bank-$9D bytes overlap the $26A0 ordered island"
    assert (
        h26_unrolled_ordered == 0x9800
        and h26_unrolled_ordered_end is not None
        and h26_unrolled_ordered_end <= 0xA000
    ), "$26A0 ordered helper moved or crossed h20e8@$9D:A000"
    assert ESC7[
        h26_unrolled_ordered_end - 0x8000:0x2000
    ] == bytes(
        0x2000 - (h26_unrolled_ordered_end - 0x8000)
    ), "nonzero bank-$9D bytes overlap h20e8_fast@$9D:A003"
    assert h20e8_fast == 0xA003 and h20e8_fast_end is not None, (
        "$20E8 helper moved from its fixed $9D:A000 island"
    )
    assert h20e8_fast_end <= 0xA200, (
        "$20E8 helper crossed the fixed $CAF6/$032FCA island"
    )
    assert ESC7[h20e8_fast_end - 0x8000:0x2200] == bytes(
        0x2200 - (h20e8_fast_end - 0x8000)
    ), "$20E8 helper has nonzero overlap before hcaf6_32fca@$9D:A200"
    assert hcaf6_32fca == 0xA200 and hcaf6_32fca_end is not None, (
        "$CAF6/$032FCA helper moved from its fixed $9D:A200 island"
    )
    assert hcaf6_32fca_end <= 0xA400, (
        "$CAF6/$032FCA helper crossed the fixed $20E8 DMA-data island"
    )
    assert h20e8_dma_data == 0xA400 and h20e8_dma_data_end == 0xA540, (
        "$20E8 DMA payload moved from its fixed $9D:A400-$A53F island"
    )
    assert ESC7[hcaf6_32fca_end - 0x8000:0x2400] == bytes(
        0x2400 - (hcaf6_32fca_end - 0x8000)
    ), "$CAF6/$032FCA helper has nonzero overlap before $20E8 DMA data"
    h20e8_blob = Path("src/h20e8_dma_data.bin").read_bytes()
    h20e8_expected = bytearray(b"\x28\x00" * 64)
    h20e8_full_code = bytearray()
    for index in range(14):
        for base in (0x366F6, 0x36712):
            offset = base + index * 2
            tile = int.from_bytes(IMG[offset:offset + 2], "big")
            h20e8_full_code.extend(
                ((tile + 0x2000) & 0xFFFF).to_bytes(2, "big")
            )
    h20e8_full_code.extend(bytes(8))
    h20e8_half_code = bytearray(h20e8_full_code)
    for offset in range(2, 14 * 4, 4):
        h20e8_half_code[offset : offset + 2] = b"\x00\x00"
    h20e8_expected.extend(h20e8_full_code)
    h20e8_expected.extend(h20e8_half_code)
    h20e8_expected.extend(bytes(64))
    assert h20e8_blob == bytes(h20e8_expected), (
        "$20E8 generated DMA payload differs from the packed arcade image"
    )
    assert hashlib.sha256(h20e8_blob).hexdigest() == (
        "069f916c815015ed7e0d2b319270e99dcdca086af782e2f374fc681449412f0d"
    ), "$20E8 DMA payload hash differs from the audited descriptor"
    assert ESC7[0x2400:0x2540] == h20e8_blob, (
        "$20E8 DMA payload bytes differ from their generated source"
    )
    assert producer_bg_append_range == 0xA540 and producer_bg_append_range_end is not None, (
        "exact BG producer-list appender moved from the post-$20E8 payload island"
    )
    assert producer_bg_append_range < producer_bg_append_range_end <= 0xA800
    producer_bg_appender = ESC7[
        producer_bg_append_range - 0x8000:
        producer_bg_append_range_end - 0x8000
    ]
    assert producer_bg_appender.startswith(
        bytes.fromhex("c230858c8be220a94148abc220")
    ), "BG producer-list appender no longer establishes DBR=$41 explicitly"
    assert producer_bg_appender.count(bytes.fromhex("990012")) == 1, (
        "BG producer-list appender lost its DBR-qualified $1200,Y store"
    )
    assert producer_bg_appender.count(bytes.fromhex("ab60")) == 1, (
        "BG producer-list appender no longer restores DBR on its common exit"
    )
    assert ESC7[
        producer_bg_append_range_end - 0x8000:0x2800
    ] == bytes(0x2800 - (producer_bg_append_range_end - 0x8000)), (
        "BG producer-list appender has nonzero overlap before h3c36_fast@$9D:A800"
    )
    assert ESC7.count(bytes.fromhex("2040a5")) == 2, (
        "$20E8/$29B6 no longer have exactly two bank-local BG-list appender calls"
    )
    assert h3c36_fast == 0xA800 and h3c36_fast_end is not None, (
        "$3C36 settled-gameplay helper moved from its fixed $9D:A800 island"
    )
    assert h3c36_fast_end <= 0xAA00, (
        "$3C36 settled-gameplay helper crossed the fixed $2BDA island"
    )
    assert ESC7[h3c36_fast_end - 0x8000:0x2A00] == bytes(
        0x2A00 - (h3c36_fast_end - 0x8000)
    ), "nonzero escbank7 bytes overlap h2bda_fast@$9D:AA00"
    assert h2bda_fast == 0xAA00 and h2bda_fast_end is not None, (
        "$2BDA canonical-work-RAM helper moved from its fixed $9D:AA00 island"
    )
    assert h2bda_fast_end <= 0xAB00, (
        "$2BDA canonical-work-RAM helper crossed the $01F1C0 island"
    )
    assert ESC7[h2bda_fast_end - 0x8000:0x2B00] == bytes(
        0x2B00 - (h2bda_fast_end - 0x8000)
    ), "nonzero escbank7 bytes overlap h1f1c0_fast@$9D:AB00"
    assert h1f1c0_fast == 0xAB00 and h1f1c0_fast_end is not None, (
        "$01F1C0 table helper moved from its fixed $9D:AB00 island"
    )
    assert h1f1c0_fast_end <= 0xB000, (
        "$01F1C0 table helper crossed the object-allocation island"
    )
    assert ESC7[h1f1c0_fast_end - 0x8000:0x3000] == bytes(
        0x3000 - (h1f1c0_fast_end - 0x8000)
    ), "nonzero escbank7 bytes overlap entry_2498c@$9D:B000"
    assert entry_2498c == 0xB000 and entry_2498c_end is not None, (
        "$02498C pool scanner moved from its fixed $9D:B000 island"
    )
    assert entry_249c2 == 0xB800 and entry_249c2_end is not None, (
        "$0249C2 pool scanner moved from its fixed $9D:B800 island"
    )
    assert entry_1f2e4 == 0xC000 and entry_1f2e4_end is not None, (
        "$01F2E4 allocator moved from its fixed $9D:C000 island"
    )
    assert entry_1f2e4_end <= 0xCC00, (
        "$01F2E4 allocator crossed the fixed $D8AC/$DAxx task island"
    )
    assert ESC7[entry_1f2e4 - 0x8000:entry_1f2e4_end - 0x8000].count(
        bytes.fromhex("5c00a09e")
    ) == 1, "$01F2E4 lost its sole direct $9E:A000 $01F4B0 leaf link"
    assert ESC7[entry_1f2e4_end - 0x8000:0x4C00] == bytes(
        0x4C00 - (entry_1f2e4_end - 0x8000)
    ), "nonzero escbank7 bytes overlap the $D8AC/$DAxx task island"

    da_entries = [
        "entry_da72", "entry_d8ac", "entry_d8b4", "entry_d9cct",
        "entry_dc44t", "entry_da44t", "entry_da9et", "entry_daf4t",
        "entry_dc2et", "entry_dc2et_end",
    ]
    da_offsets = [esc7_off(symbol) for symbol in da_entries]
    assert da_offsets[0] == 0xCC00 and da_offsets == sorted(da_offsets), (
        "$D8AC/$DAxx task entries moved out of order or off their $9D:CC00 island"
    )
    assert da_offsets[-1] <= 0xDA00, (
        "$D8AC/$DAxx task bodies crossed the fixed direct-dispatch island"
    )
    assert ESC7[da_offsets[-1] - 0x8000:0x5A00] == bytes(
        0x5A00 - (da_offsets[-1] - 0x8000)
    ), "nonzero task-body bytes overlap xlat_da_dispatch@$9D:DA00"

    xdd = esc7_off("xlat_da_dispatch")
    xdd_end = esc7_off("xlat_da_dispatch_end")
    entry_2e4b8 = esc7_off("entry_2e4b8")
    entry_2e4b8_end = esc7_off("entry_2e4b8_end")
    entry_2e524 = esc7_off("entry_2e524")
    entry_2e524_end = esc7_off("entry_2e524_end")
    stage3_2e42c_bsr_trampoline = esc7_off(
        "stage3_2e42c_bsr_trampoline"
    )
    stage3_2e42c_callback_trampoline = esc7_off(
        "stage3_2e42c_callback_trampoline"
    )
    stage3_bd1c_callback_trampoline_1 = esc7_off(
        "stage3_bd1c_callback_trampoline_1"
    )
    stage3_bd1c_callback_trampoline_2 = esc7_off(
        "stage3_bd1c_callback_trampoline_2"
    )
    stage3_bd1c_callback_trampoline_3 = esc7_off(
        "stage3_bd1c_callback_trampoline_3"
    )
    stage3_bd1c_callback_trampoline_4 = esc7_off(
        "stage3_bd1c_callback_trampoline_4"
    )
    stage3_278e8_callback_trampoline_1 = esc7_off(
        "stage3_278e8_callback_trampoline_1"
    )
    stage3_278e8_callback_trampoline_2 = esc7_off(
        "stage3_278e8_callback_trampoline_2"
    )
    stage3_278e8_callback_trampoline_3 = esc7_off(
        "stage3_278e8_callback_trampoline_3"
    )
    stage3_2e42c_trampolines_end = esc7_off(
        "stage3_2e42c_trampolines_end"
    )
    stage3_13282_callback_trampoline_1 = esc7_off(
        "stage3_13282_callback_trampoline_1"
    )
    stage3_13282_callback_trampoline_2 = esc7_off(
        "stage3_13282_callback_trampoline_2"
    )
    stage3_13282_trampolines_end = esc7_off(
        "stage3_13282_trampolines_end"
    )
    stage3_2e42c_fast_callback_trampoline = esc7_off(
        "stage3_2e42c_fast_callback_trampoline"
    )
    stage3_2e42c_fast_trampolines_end = esc7_off(
        "stage3_2e42c_fast_trampolines_end"
    )
    hcd1a_fb8 = esc7_off("hcd1a_fb8")
    hcd1a_fb8_end = esc7_off("hcd1a_fb8_end")
    hce4_shape_try_ext = esc7_off("hce4_shape_try_ext")
    hce4_shape_try_ext_end = esc7_off("hce4_shape_try_ext_end")
    stage3_133ea_trampoline_1 = esc7_off(
        "stage3_133ea_trampoline_1"
    )
    stage3_133ea_trampoline_2 = esc7_off(
        "stage3_133ea_trampoline_2"
    )
    stage3_133ea_trampoline_3 = esc7_off(
        "stage3_133ea_trampoline_3"
    )
    stage3_13468_trampoline_1 = esc7_off(
        "stage3_13468_trampoline_1"
    )
    stage3_13538_trampoline_1 = esc7_off(
        "stage3_13538_trampoline_1"
    )
    stage3_13538_trampoline_2 = esc7_off(
        "stage3_13538_trampoline_2"
    )
    stage3_1337e_trampoline_1 = esc7_off(
        "stage3_1337e_trampoline_1"
    )
    stage3_player_hot_trampolines_end = esc7_off(
        "stage3_player_hot_trampolines_end"
    )
    h25110_stage2_overlap = esc7_off("h25110_stage2_overlap")
    h25110_stage2_overlap_end = esc7_off("h25110_stage2_overlap_end")
    entry_24aa8t = esc7_off("entry_24aa8t")
    entry_24aa8t_end = esc7_off("entry_24aa8t_end")
    entry_28f92t = esc7_off("entry_28f92t")
    entry_28f92t_end = esc7_off("entry_28f92t_end")
    entry_91et = esc7_off("entry_91et")
    entry_91et_end = esc7_off("entry_91et_end")
    entry_c0bc = esc7_off("entry_c0bc")
    entry_c0bc_generated = esc7_off("entry_c0bc_generated")
    c0bc_hle_29b6_return = esc7_off("c0bc_hle_29b6_return")
    entry_c0bc_end = esc7_off("entry_c0bc_end")
    jah2_b0_ext = esc7_off("jah2_b0_ext")
    jah2_b0_ext_end = esc7_off("jah2_b0_ext_end")
    entry_29b6_fast = esc7_off("entry_29b6_fast")
    entry_29b6_fast_end = esc7_off("entry_29b6_fast_end")
    hcaf6_generic_admit = esc7_off("hcaf6_generic_admit")
    hcaf6_generic_admit_end = esc7_off("hcaf6_generic_admit_end")
    hcaf6_late_selector = esc7_off("hcaf6_late_selector")
    hcaf6_late_selector_end = esc7_off("hcaf6_late_selector_end")
    esc7_end = esc7_off("escbank7_end")
    assert xdd == 0xDA00 and xdd < xdd_end <= 0xDC00, (
        "sparse direct dispatcher moved or overflowed its $9D:DA00-$DBFF island"
    )
    assert (
        entry_2e4b8 == 0xDC00
        and entry_2e4b8 < entry_2e4b8_end <= 0xE000
        and entry_2e524 == 0xE190
        and entry_2e524 < entry_2e524_end
        <= stage3_2e42c_bsr_trampoline
        == 0xE3C0
        and stage3_2e42c_callback_trampoline == 0xE3C4
        and stage3_bd1c_callback_trampoline_1 == 0xE3C8
        and stage3_bd1c_callback_trampoline_2 == 0xE3CC
        and stage3_bd1c_callback_trampoline_3 == 0xE3D0
        and stage3_bd1c_callback_trampoline_4 == 0xE3D4
        and stage3_278e8_callback_trampoline_1 == 0xE3D8
        and stage3_278e8_callback_trampoline_2 == 0xE3DC
        and stage3_278e8_callback_trampoline_3 == 0xE3E0
        and stage3_2e42c_trampolines_end == 0xE3E4
        and stage3_13282_callback_trampoline_1 == 0xE3E4
        and stage3_13282_callback_trampoline_2 == 0xE3E8
        and stage3_13282_trampolines_end == 0xE3EC
        and stage3_2e42c_fast_callback_trampoline == 0xE3F0
        and stage3_2e42c_fast_trampolines_end == 0xE3F4
    ), "Stage-3 draw wrappers moved or overflowed their fixed bank-$9D islands"
    assert ESC7[xdd_end - 0x8000:entry_2e4b8 - 0x8000] == bytes(
        entry_2e4b8 - xdd_end
    ), "sparse dispatcher consumed the zero seam before $02E4B8"
    assert ESC7[
        entry_2e4b8_end - 0x8000:hcd1a_fb8 - 0x8000
    ] == bytes(hcd1a_fb8 - entry_2e4b8_end), (
        "$02E4B8 draw wrapper consumed the zero seam before $CD1A/$0FB8"
    )
    assert ESC7[xdd - 0x8000:xdd - 0x8000 + 4] == bytes.fromhex("c230a542"), (
        "sparse direct dispatcher lost its REP/LDA bank prologue"
    )
    xdd_bytes = ESC7[xdd - 0x8000:xdd_end - 0x8000]
    assert xdd_bytes.count(bytes.fromhex("5c00989e")) == 1, (
        "sparse dispatcher lost its sole $9E:9800 entry_24d28 target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c009c9e")) == 1, (
        "sparse dispatcher lost its sole $9E:9C00 entry_24d64 target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c60b695")) == 1, (
        "sparse dispatcher lost its sole $95:B660 entry_2a190 target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c20fc95")) == 1, (
        "sparse dispatcher lost its sole $95:FC20 entry_11bdc target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c39fd95")) == 1, (
        "sparse dispatcher lost its sole $95:FD39 entry_11c9a target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c00d89e")) == 1, (
        "sparse dispatcher lost its sole $9E:D800 entry_d7be target"
    )
    assert xdd_bytes.count(bytes.fromhex("5c00a79e")) == 1, (
        "sparse dispatcher lost its sole $9E:A700 one-shot task fan-out"
    )
    assert xdd_bytes.count(bytes.fromhex("5cf09995")) == 0, (
        "shared dispatcher re-admitted the unproven $002D8A direct route"
    )
    # The Stage-3 direct routes are deliberately not admitted through this
    # shared dispatcher.  The fresh current-ROM controller replay reaches
    # $02xxxx and $01xxxx addresses during Stage 1 as well; canonical pointer
    # guards alone cannot establish Stage-3 provenance.  Routing those shared
    # PCs into the Stage-3 bodies created a deterministic long-update burst
    # before tick 2956, then delayed Button 1 response.  Keep the conservative
    # dispatcher until a live-stage discriminator is compared three-way.
    for encoded, label in (
        (bytes.fromhex("5c00b694"), "$027952 -> $94:B600"),
        (bytes.fromhex("5c00bc94"), "$0279D2 -> $94:BC00"),
        (bytes.fromhex("5c00c294"), "$02F3BA -> $94:C200"),
        (bytes.fromhex("5c00d09f"), "$0278E8 -> $9F:D000"),
        (bytes.fromhex("5c00c09f"), "$027AEA -> $9F:C000"),
        (bytes.fromhex("5c40cb94"), "$027B44 -> $94:CB40"),
        (bytes.fromhex("5cc0ce94"), "$027B7C -> $94:CEC0"),
        (bytes.fromhex("5c00cd94"), "$02F56A -> $94:CD00"),
        (bytes.fromhex("5c00d194"), "$02F5A2 -> $94:D100"),
        (bytes.fromhex("5c40d394"), "$02E49C -> $94:D340"),
        (bytes.fromhex("5c80d494"), "$0296C6 -> $94:D480"),
        (bytes.fromhex("5c40d594"), "$02E40E -> $94:D540"),
        (bytes.fromhex("5c40a19f"), "$02E42C -> $9F:A140"),
        (bytes.fromhex("5c00a59f"), "$027912 -> $9F:A500"),
        (bytes.fromhex("5c80a69f"), "$02F2E0 -> $9F:A680"),
        (bytes.fromhex("5c00e09f"), "$013282 -> $9F:E000"),
        (bytes.fromhex("5c00d89f"), "$013314 -> $9F:D800"),
        (bytes.fromhex("5c00ba9f"), "$01337E -> $9F:BA00"),
        (bytes.fromhex("5c00e49f"), "$02E676 -> $9F:E400"),
        (bytes.fromhex("5c00fe9f"), "$02F542 -> $9F:FE00"),
        (bytes.fromhex("5c00ec9f"), "$0133EA -> $9F:EC00"),
        (bytes.fromhex("5c00f19f"), "$013468 -> $9F:F100"),
        (bytes.fromhex("5c00f79f"), "$013538 -> $9F:F700"),
        (bytes.fromhex("5c20db94"), "$0135E0 -> $94:DB20"),
    ):
        assert xdd_bytes.count(encoded) == 0, (
            "shared dispatcher re-admitted unproven Stage-3 target " + label
        )
    # Same-bank targets must be absolute JMPs: a local JML would encode bank
    # $00 from Poppy's logical .org and escape the physical bank-$9D mapping.
    for stub, target in (
        ("xdd_122a4", "entry_122a4"),
        ("xdd_91e", "entry_91et"),
        ("xdd_c0bc", "entry_c0bc"),
        ("xdd_da72", "entry_da72"),
        ("xdd_d8b4", "entry_d8b4"),
        ("xdd_d9cc", "entry_d9cct"),
        ("xdd_dc44", "entry_dc44t"),
        ("xdd_da44", "entry_da44t"),
        ("xdd_da9e", "entry_da9et"),
        ("xdd_daf4", "entry_daf4t"),
        ("xdd_dc2e", "entry_dc2et"),
    ):
        stub_off = esc7_off(stub)
        target_off = esc7_off(target)
        encoded = bytes((0x4C, target_off & 0xFF, target_off >> 8))
        assert ESC7[
            stub_off - 0x8000:stub_off - 0x8000 + 3
        ] == encoded, f"{stub} is no longer a bank-preserving JMP to {target}"
    assert hcd1a_fb8 == 0xE000 and entry_2e4b8_end <= hcd1a_fb8, (
        "$CD1A/$0FB8 guarded fusion moved from its pinned $9D:E000 island"
    )
    assert 0xE000 < hcd1a_fb8_end <= entry_2e524 == 0xE190, (
        "$CD1A/$0FB8 guarded fusion overflowed into the $02E524 wrapper"
    )
    assert ESC7[
        hcd1a_fb8_end - 0x8000:entry_2e524 - 0x8000
    ] == bytes(entry_2e524 - hcd1a_fb8_end), (
        "$CD1A/$0FB8 fusion consumed the zero seam before $02E524"
    )
    assert ESC7[
        entry_2e524_end - 0x8000:
        stage3_2e42c_bsr_trampoline - 0x8000
    ] == bytes(stage3_2e42c_bsr_trampoline - entry_2e524_end), (
        "$02E524 draw wrapper consumed the selector-trampoline seam"
    )
    for wrapper_start, wrapper_end, continuation, label in (
        (
            entry_2e4b8,
            entry_2e4b8_end,
            esc7_off("br2e4b8_1"),
            "$02E4B8->$02E49C",
        ),
        (
            entry_2e524,
            entry_2e524_end,
            esc7_off("br2e524_1"),
            "$02E524->$02E49C",
        ),
    ):
        wrapper = ESC7[
            wrapper_start - 0x8000:wrapper_end - 0x8000
        ]
        exact_edge = bytes(
            (
                0xA9,
                continuation & 0xFF,
                continuation >> 8,
                0x85,
                0x54,
                0xA9,
                0xF8,
                0x00,
                0x85,
                0x56,
                0x22,
                0xAE,
                0xE5,
                0x00,
                0x5C,
                0x40,
                0xD3,
                0x94,
            )
        )
        assert wrapper.count(exact_edge) == 1, (
            f"{label} lost its exact sentinel push and direct guarded "
            "bank-$94 call edge"
        )
    assert ESC7[
        stage3_2e42c_bsr_trampoline - 0x8000:
        stage3_2e42c_trampolines_end - 0x8000
    ] == bytes.fromhex(
        "5c00a89f5c03a89f"
        "5c06a89f5c09a89f5c0ca89f5c0fa89f"
        "5c12a89f5c15a89f5c18a89f"
    ), (
        "Stage-3 selector/scroll return trampolines moved or changed bank targets"
    )
    assert ESC7[
        stage3_13282_callback_trampoline_1 - 0x8000:
        stage3_13282_trampolines_end - 0x8000
    ] == bytes.fromhex("5c80a89f5c83a89f"), (
        "$013282 return trampolines moved or changed bank targets"
    )
    assert ESC7[
        stage3_13282_trampolines_end - 0x8000:
        stage3_2e42c_fast_callback_trampoline - 0x8000
    ] == bytes(
        stage3_2e42c_fast_callback_trampoline
        - stage3_13282_trampolines_end
    ), "nonzero bytes consumed the selector fast-trampoline alignment seam"
    assert ESC7[
        stage3_2e42c_fast_callback_trampoline - 0x8000:
        stage3_2e42c_fast_trampolines_end - 0x8000
    ] == bytes.fromhex("5c00a99f"), (
        "$02E42C fast callback trampoline moved or changed bank target"
    )
    assert ESC7[
        stage3_2e42c_fast_trampolines_end - 0x8000:0x6400
    ] == bytes(0xE400 - stage3_2e42c_fast_trampolines_end), (
        "selector trampolines consumed the zero seam before the $CE4 extension"
    )
    assert hce4_shape_try_ext == 0xE400, (
        "$CE4 extension moved from its fixed $9D:E400 entry"
    )
    assert ESC7[0x6400:0x6404] == bytes.fromhex("c230a582"), (
        "$CE4 extension lost its explicit REP/LDA mapped-source prologue"
    )
    hce4_ext_miss = esc7_off("hce4_ext_miss")
    hce4_ext_after_panel = esc7_off("hce4_ext_after_panel")
    assert hce4_ext_after_panel == 0xE446, (
        "$CE4 extension's size-neutral Stage-3 panel resume moved"
    )
    assert ESC7[
        hce4_ext_miss - 0x8000:hce4_ext_after_panel - 0x8000
    ] == bytes.fromhex("5c00d49fea"), (
        "$CE4 extension lost its exact bank-$9F panel redirect/NOP seam"
    )
    assert 0xE400 < hce4_shape_try_ext_end <= 0xE7E0, (
        "$CE4 extension overflowed its reserved $9D:E400-$E7FF island"
    )
    assert ESC7[
        hce4_shape_try_ext_end - 0x8000:
        stage3_133ea_trampoline_1 - 0x8000
    ] == bytes(stage3_133ea_trampoline_1 - hce4_shape_try_ext_end), (
        "$CE4 extension consumed the player-hot trampoline seam"
    )
    assert (
        stage3_133ea_trampoline_1 == 0xE7E0
        and stage3_133ea_trampoline_2 == 0xE7E4
        and stage3_133ea_trampoline_3 == 0xE7E8
        and stage3_13468_trampoline_1 == 0xE7EC
        and stage3_13538_trampoline_1 == 0xE7F0
        and stage3_13538_trampoline_2 == 0xE7F4
        and stage3_1337e_trampoline_1 == 0xE7F8
        and stage3_player_hot_trampolines_end == 0xE7FC
    ), "Stage-3 player-hot return trampolines moved"
    assert ESC7[
        stage3_133ea_trampoline_1 - 0x8000:
        stage3_1337e_trampoline_1 - 0x8000
    ] == bytes.fromhex(
        "5c40eb9f5c43eb9f5c46eb9f"
        "5c49eb9f5c4ceb9f5c4feb9f"
    ), "Stage-3 player-hot return trampolines changed targets"
    trampoline_1337e = ESC7[
        stage3_1337e_trampoline_1 - 0x8000:
        stage3_player_hot_trampolines_end - 0x8000
    ]
    assert (
        trampoline_1337e == bytes.fromhex("5c18bd9f")
    ), (
        "$01337E return trampoline changed its exact bank-$9F target"
    )
    assert ESC7[
        stage3_player_hot_trampolines_end - 0x8000:0x6800
    ] == bytes(0xE800 - stage3_player_hot_trampolines_end), (
        "player-hot return trampolines consumed the $025110 seam"
    )
    assert h25110_stage2_overlap == 0xE800, (
        "$25110 stage-2 overlap continuation moved from fixed $9D:E800"
    )
    assert h25110_stage2_overlap < h25110_stage2_overlap_end <= 0xF000, (
        "$25110 stage-2 overlap continuation overflowed $9D:E800-$EFFF"
    )
    assert ESC7[h25110_stage2_overlap_end - 0x8000:0x7000] == bytes(
        0x7000 - (h25110_stage2_overlap_end - 0x8000)
    ), "nonzero bank-$9D bytes overlap the gameplay-entry initializer island"
    entry_init_offsets = [
        entry_24aa8t, entry_24aa8t_end,
        entry_28f92t, entry_28f92t_end,
        entry_91et, entry_91et_end,
        entry_c0bc, entry_c0bc_end,
    ]
    assert entry_24aa8t == 0xF000 and entry_init_offsets == sorted(entry_init_offsets), (
        "gameplay-entry initializer bodies moved or reordered in bank $9D"
    )
    assert entry_28f92t == 0xF298, (
        "$028F92 initializer moved from the bank-$92 absolute-JSR target"
    )
    assert entry_c0bc_end <= 0xFB00, (
        "gameplay-entry initializer bodies crossed the fixed JAH2 bank-0 island"
    )
    assert entry_c0bc_generated == entry_c0bc + 6, (
        "$C0BC generated fallback no longer follows its six-byte public wrapper"
    )
    assert ESC7[entry_c0bc - 0x8000:entry_c0bc_generated - 0x8000] == bytes.fromhex(
        "5c00ec9eeaea"
    ), "$C0BC public entry lost its fixed JML $9E:EC00 wrapper"
    assert c0bc_hle_29b6_return + 4 == entry_c0bc_end, (
        "$C0BC bank-$9D callback trampoline moved away from the initializer tail"
    )
    assert ESC7[
        c0bc_hle_29b6_return - 0x8000:entry_c0bc_end - 0x8000
    ] == bytes.fromhex("5c00ee9e"), (
        "$C0BC callback trampoline no longer reaches fixed $9E:EE00"
    )
    assert ESC7[entry_c0bc_end - 0x8000:0x7B00] == bytes(
        0x7B00 - (entry_c0bc_end - 0x8000)
    ), "nonzero initializer bytes overlap jah2_b0_ext@$9D:FB00"
    assert jah2_b0_ext == 0xFB00 and jah2_b0_ext_end <= 0xFC00, (
        "relocated JAH2 bank-0 scan moved or overflowed its fixed island"
    )
    assert ESC7[jah2_b0_ext_end - 0x8000:0x7C00] == bytes(
        0x7C00 - (jah2_b0_ext_end - 0x8000)
    ), "nonzero JAH2 bytes overlap entry_29b6_fast@$9D:FC00"
    assert entry_29b6_fast == 0xFC00 and entry_29b6_fast_end <= 0xFE40, (
        "$29B6 fast wrapper moved or crossed the $CAF6 admission island"
    )
    assert ESC7[entry_c0bc - 0x8000:entry_c0bc_end - 0x8000].count(
        bytes.fromhex("5c00fc9d")
    ) == 1, "$C0BC no longer direct-links its organic $29B6 callback to $9D:FC00"
    assert hcaf6_generic_admit == 0xFE40, (
        "$CAF6 general-loop admission moved from fixed $9D:FE40"
    )
    assert entry_29b6_fast_end <= hcaf6_generic_admit, (
        "$29B6 fast wrapper overlaps the $CAF6 general-loop admission"
    )
    assert ESC7[
        entry_29b6_fast_end - 0x8000:hcaf6_generic_admit - 0x8000
    ] == bytes(hcaf6_generic_admit - entry_29b6_fast_end), (
        "nonzero bank-$9D bytes overlap the $29B6/$CAF6 seam"
    )
    assert hcaf6_generic_admit < hcaf6_generic_admit_end <= 0xFED0, (
        "$CAF6 general-loop admission crossed the late-selector adapter"
    )
    assert hcaf6_late_selector == 0xFED0, (
        "$CAF6 late-selector adapter moved from fixed $9D:FED0"
    )
    assert ESC7[
        hcaf6_generic_admit_end - 0x8000:hcaf6_late_selector - 0x8000
    ] == bytes(hcaf6_late_selector - hcaf6_generic_admit_end), (
        "nonzero bank-$9D bytes overlap the CAF6 admission/selector seam"
    )
    assert hcaf6_late_selector < hcaf6_late_selector_end <= 0x10000, (
        "$CAF6 late-selector adapter overflows bank $9D"
    )
    assert esc7_end == hcaf6_late_selector_end and len(ESC7) == esc7_end - 0x8000, (
        "unexpected bank-$9D bytes follow the CAF6 late-selector adapter"
    )
    ROM[0x2E8000:0x2E8000+len(ESC7)] = ESC7          # @ SA-1 $9D:8000 (file $2E8000)

# --- EIGHTH SA-1 escape bank ($9E:8000, file $2F0000) ---
# The bank after escbank7 is private-ROM free and remains below the 4 MiB cart
# limit.  Its fixed islands accelerate the bounded object-spawn/TRAP #1 path;
# pin every cross-bank entry because bank $00/$99/$9D use literal JML targets.
if _osp.exists("src/escbank8.bin"):
    ESC8 = Path("src/escbank8.bin").read_bytes()
    assert len(ESC8) <= 0x8000, (
        "escbank8 %d bytes overflows the $2F0000..$2F8000 bank" % len(ESC8)
    )
    esc8_symbols = Path("src/escbank8.sym").read_text(encoding="utf-8-sig")

    def esc8_off(symbol):
        for line in esc8_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank8 layout symbol %s" % symbol)

    entry_466_8 = esc8_off("entry_466")
    entry_466_8_end = esc8_off("entry_466_end")
    entry_1d51a_8 = esc8_off("entry_1d51a")
    entry_1d_init_end = esc8_off("entry_1d_init_end")
    entry_24d28_8 = esc8_off("entry_24d28")
    entry_24d28_8_end = esc8_off("entry_24d28_end")
    entry_24d64_8 = esc8_off("entry_24d64")
    entry_24d64_8_end = esc8_off("entry_24d64_end")
    entry_1f4b0t_8 = esc8_off("entry_1f4b0t")
    entry_1f4b0t_8_end = esc8_off("entry_1f4b0t_end")
    xlat_76_dispatch_8 = esc8_off("xlat_76_dispatch")
    xlat_76_dispatch_8_end = esc8_off("xlat_76_dispatch_end")
    entry_76b6_8 = esc8_off("entry_76b6")
    entry_7734_8_end = esc8_off("entry_7734_end")
    entry_1e71e_8 = esc8_off("entry_1e71e")
    entry_1e71e_8_end = esc8_off("entry_1e71e_end")
    entry_24b5a_8 = esc8_off("entry_24b5a")
    entry_2427c_8_end = esc8_off("entry_2427c_end")
    entry_8b46t_8 = esc8_off("entry_8b46t")
    entry_8b9c_8_end = esc8_off("entry_8b9c_end")
    entry_1c9ae_empty_8 = esc8_off("entry_1c9ae_empty")
    entry_1c9ae_empty_8_end = esc8_off("entry_1c9ae_empty_end")
    entry_d7be_8 = esc8_off("entry_d7be")
    entry_d7be_8_end = esc8_off("entry_d7be_end")
    esc8_end = esc8_off("escbank8_end")
    render_manifest_build_8 = esc8_off("render_manifest_build")
    render_manifest_build_8_end = esc8_off("render_manifest_build_end")
    rmb_obj_begin_8 = esc8_off("rmb_obj_begin")
    rmb_bg_select_8 = esc8_off("rmb_bg_select")
    rmb_bg_dirty_default_8 = esc8_off("rmb_bg_dirty_default")
    rmb_bg_full_scan_8 = esc8_off("rmb_bg_full_scan")
    rmb_bg_first_8 = esc8_off("rmb_bg_first")
    rmb_bg_first_copy_8 = esc8_off("rmb_bg_first_copy")
    rmb_bg_clean_8 = esc8_off("rmb_bg_clean")
    rmb_bg_clean_jump_8 = esc8_off("rmb_bg_clean_jump")
    rmb_bg_reconcile_8 = esc8_off("rmb_bg_reconcile")
    rmb_bg_reconcile_end_8 = esc8_off("rmb_bg_reconcile_done")
    rmb_bg_promote_8 = esc8_off("rmb_bg_promote")
    rmb_bg_revert_8 = esc8_off("rmb_bg_revert")
    rmb_obj_done_8 = esc8_off("rmb_obj_done")
    rmb_obj_pack_8 = esc8_off("rmb_obj_pack")
    rmb_obj_pack_bottom_status_8 = esc8_off("rmb_obj_pack_bottom_status")
    rmb_obj_pack_bottom_y_8 = esc8_off("rmb_obj_pack_bottom_y")
    rmb_obj_pack_x_8 = esc8_off("rmb_obj_pack_x")
    rmb_obj_pack_8_end = esc8_off("rmb_obj_pack_end")
    rmb_title_detect_8 = esc8_off("rmb_title_detect")
    rmb_title_detect_8_end = esc8_off("rmb_title_detect_end")
    rmb_obj_fast_scan_8 = esc8_off("rmb_obj_fast_scan")
    rmb_obj_fast_loop_8 = esc8_off("rmb_obj_fast_loop")
    rmb_obj_fast_done_8 = esc8_off("rmb_obj_fast_done")
    rmb_obj_fast_scan_8_end = esc8_off("rmb_obj_fast_scan_end")
    render_bg_dirty_sparse_8 = esc8_off("render_bg_dirty_sparse")
    rbds_done_8 = esc8_off("rbds_done")
    rbds_clean_8 = esc8_off("rbds_clean")
    rbds_default_8 = esc8_off("rbds_default")
    render_bg_dirty_sparse_8_end = esc8_off("render_bg_dirty_sparse_end")
    shadow_dirty_publish_8 = esc8_off("shadow_dirty_publish")
    shadow_dirty_publish_8_end = esc8_off("shadow_dirty_publish_end")
    rmb_bg_invalidate_tokens_8 = esc8_off("rmb_bg_invalidate_tokens")
    rmb_bg_changed_publish_8 = esc8_off("rmb_bg_changed_publish")
    rmb_bg_changed_publish_done_8 = esc8_off("rmb_bg_changed_publish_done")
    mark_bg_dirty_8 = esc8_off("mark_bg_dirty")
    mark_bg_dirty_8_end = esc8_off("mark_bg_dirty_end")
    rmb_bg_first_finish_8 = esc8_off("rmb_bg_first_finish")
    rmb_bg_first_prepare_c0bc_8 = esc8_off(
        "rmb_bg_first_prepare_c0bc"
    )
    rmb_bg_first_finish_8_end = esc8_off("rmb_bg_first_finish_end")
    rmb_bg_validate_tokens_8 = esc8_off("rmb_bg_validate_tokens")
    rmb_bg_validate_invalid_8 = esc8_off("rmb_bg_validate_invalid")
    rmb_bg_validate_tokens_8_end = esc8_off(
        "rmb_bg_validate_tokens_end"
    )
    rmb_prepare_bg_8 = esc8_off("rmb_prepare_bg")
    rmb_prepare_bg_8_end = esc8_off("rmb_prepare_bg_end")
    rpb_sort_outer_8 = esc8_off("rpb_sort_outer")
    rpb_prepare_dispatch_8 = esc8_off("rpb_prepare_dispatch")
    rpb_c0bc_prepared_8 = esc8_off("rpb_c0bc_prepared")
    rpb_prepare_dispatch_8_end = esc8_off("rpb_prepare_dispatch_end")
    h8_zero_mask_gate_8 = esc8_off("h8_zero_mask_gate")
    h8_zero_mask_gate_8_end = esc8_off("h8_zero_mask_gate_end")
    rmb_obj_x_visible_8 = esc8_off("rmb_obj_x_visible")
    rmb_obj_x_visible_8_end = esc8_off("rmb_obj_x_visible_end")
    rmb_obj_prefilter_8 = esc8_off("rmb_obj_prefilter")
    rmb_obj_prefilter_8_end = esc8_off("rmb_obj_prefilter_end")
    render_bg_dirty_sparse_8 = esc8_off("render_bg_dirty_sparse")
    render_bg_dirty_sparse_8_end = esc8_off("render_bg_dirty_sparse_end")
    rox_top_x_8 = esc8_off("rox_top_x")
    rox_top_x_8_end = esc8_off("rox_top_x_end")
    h158_ylist_stage_8 = esc8_off("h158_ylist_stage")
    h158_ylist_first_8 = esc8_off("hyl_first")
    h158_ylist_stage_8_end = esc8_off("h158_ylist_stage_end")
    render_bg_offset_table_8 = esc8_off("render_bg_offset_table")
    render_bg_offset_table_8_end = esc8_off("render_bg_offset_table_end")
    hle_c0bc_8 = esc8_off("hle_c0bc")
    hc0bc_hle_fast_8 = esc8_off("hc0bc_hle_fast")
    hc0bc_hle_reject_8 = esc8_off("hc0bc_hle_reject")
    hc0bc_hle_main_end_8 = esc8_off("hc0bc_hle_main_end")
    hc0bc_hle_after_29b6_8 = esc8_off("hc0bc_hle_after_29b6")
    hc0bc_hle_done_8 = esc8_off("hc0bc_hle_done")
    hc0bc_hle_after_end_8 = esc8_off("hc0bc_hle_after_end")
    hc0bc_token_snapshot_8 = esc8_off("hc0bc_token_snapshot")
    hc0bc_token_snapshot_8_end = esc8_off("hc0bc_token_snapshot_end")
    hc0bc_hle_dma56_8 = esc8_off("hc0bc_hle_dma56")
    rpb_c0bc_rom_dma_8 = esc8_off("rpb_c0bc_rom_dma")
    rpb_c0bc_rom_dma_8_end = esc8_off("rpb_c0bc_rom_dma_end")
    hc0bc_hle_end_8 = esc8_off("hc0bc_hle_end")
    esc8_physical_end = esc8_off("escbank8_physical_end")
    assert entry_466_8 == 0x8000 and entry_466_8_end <= 0x9000, (
        "$000466 TRAP #1 body moved or crossed the $9E:9000 initializer island"
    )
    assert entry_1d51a_8 == 0x9000 and entry_1d_init_end <= 0x9800, (
        "$01D51A initializer cluster moved or crossed entry_24d28@$9E:9800"
    )
    assert entry_24d28_8 == 0x9800 and entry_24d28_8_end <= 0x9C00, (
        "$024D28 body moved or crossed entry_24d64@$9E:9C00"
    )
    assert entry_24d64_8 == 0x9C00 and entry_24d64_8_end <= 0xA000, (
        "$024D64 body moved or crossed entry_1f4b0t@$9E:A000"
    )
    assert entry_1f4b0t_8 == 0xA000 and entry_1f4b0t_8_end <= 0xA700, (
        "$01F4B0 table body moved or crossed the sparse dispatcher"
    )
    assert xlat_76_dispatch_8 == 0xA700 and xlat_76_dispatch_8_end <= 0xA800, (
        "$0076xx sparse dispatcher moved or crossed the task bodies"
    )
    assert entry_76b6_8 == 0xA800 and entry_7734_8_end <= 0xC000, (
        "$0076B6 fan-out cluster moved or crossed entry_1e71e@$9E:C000"
    )
    assert entry_1e71e_8 == 0xC000 and entry_1e71e_8_end <= 0xC800, (
        "$01E71E body moved or crossed the bank-$02 roots"
    )
    assert entry_24b5a_8 == 0xC800 and entry_2427c_8_end <= 0xD000, (
        "$024B5A/$02427C roots moved or crossed the $8B46 cluster"
    )
    assert entry_8b46t_8 == 0xD000 and entry_8b9c_8_end <= 0xD400, (
        "$008B46 palette task moved or crossed the $01C9AE island"
    )
    assert entry_1c9ae_empty_8 == 0xD400 and entry_1c9ae_empty_8_end <= 0xD800, (
        "$01C9AE inactive-record path moved or crossed entry_d7be@$9E:D800"
    )
    assert entry_d7be_8 == 0xD800 and entry_d7be_8_end <= 0x10000, (
        "$00D7BE transition prefix moved or overflowed bank $9E"
    )
    assert esc8_end == entry_d7be_8_end, (
        "unexpected bytes between the $00D7BE path and its generated-body end"
    )
    for seam_start, seam_end, label in (
        (entry_466_8_end, 0x9000, "$000466 -> $01D51A"),
        (entry_1d_init_end, 0x9800, "$01D51A cluster -> $024D28"),
        (entry_24d28_8_end, 0x9C00, "$024D28 -> $024D64"),
        (entry_24d64_8_end, 0xA000, "$024D64 -> $01F4B0"),
        (entry_1f4b0t_8_end, 0xA700, "$01F4B0 -> xlat_76_dispatch"),
        (xlat_76_dispatch_8_end, 0xA800, "xlat_76_dispatch -> $0076B6"),
        (entry_7734_8_end, 0xC000, "$0076B6 cluster -> $01E71E"),
        (entry_1e71e_8_end, 0xC800, "$01E71E -> bank-$02 roots"),
        (entry_2427c_8_end, 0xD000, "bank-$02 roots -> $008B46"),
        (entry_8b9c_8_end, 0xD400, "$008B46 cluster -> $01C9AE"),
        (entry_1c9ae_empty_8_end, 0xD800, "$01C9AE -> $00D7BE"),
    ):
        assert ESC8[seam_start - 0x8000:seam_end - 0x8000] == bytes(
            seam_end - seam_start
        ), "escbank8 %s seam was overwritten" % label
    assert ESC8[entry_466_8 - 0x8000:entry_466_8 - 0x8000 + 4] == bytes.fromhex(
        "c230a534"
    ), "$000466 entry lost its guarded canonical-A5 prologue"
    assert ESC8[entry_466_8 - 0x8000:entry_466_8_end - 0x8000].count(
        bytes.fromhex("5cb8b300")
    ) == 1, "$000466 body no longer tail-calls the exact bank-$00 op_rte"
    assert ESC8[entry_1c9ae_empty_8 - 0x8000:entry_1c9ae_empty_8 - 0x8000 + 4] == bytes.fromhex(
        "c230a522"
    ), "$01C9AE entry lost its guarded A0-bank prologue"
    assert ESC8[entry_d7be_8 - 0x8000:entry_d7be_8 - 0x8000 + 4] == bytes.fromhex(
        "c230a534"
    ), "$00D7BE entry lost its guarded canonical-A5 prologue"
    assert render_manifest_build_8 == 0xDC00 and esc8_end <= render_manifest_build_8, (
        "renderer manifest helper moved from its fixed $9E:DC00 island"
    )
    assert ESC8[esc8_end - 0x8000:render_manifest_build_8 - 0x8000] == bytes(
        render_manifest_build_8 - esc8_end
    ), "nonzero bank-$9E bytes overlap the renderer manifest island"
    assert render_manifest_build_8 < render_manifest_build_8_end <= 0xDE20, (
        "renderer manifest helper overflowed its $9E:DC00-$DE1F island"
    )
    assert rmb_obj_begin_8 == 0xDCDE, (
        "renderer packed-OBJ redirect moved from its fixed $9E:DCDE seam"
    )
    clean_jump = ESC8[
        rmb_bg_clean_jump_8 - 0x8000:rmb_bg_clean_jump_8 - 0x8000 + 2
    ]
    assert clean_jump[0] == 0x80, (
        "clean-BG manifest path lost its explicit BRA across the fixed .org gap"
    )
    clean_jump_target = rmb_bg_clean_jump_8 + 2 + int.from_bytes(
        clean_jump[1:2], "little", signed=True
    )
    assert clean_jump_target == rmb_obj_begin_8, (
        "clean-BG manifest branch no longer lands on the packed-OBJ redirect"
    )
    assert (
        render_bg_dirty_sparse_8
        < rbds_done_8
        < rbds_clean_8
        < rbds_default_8
        < render_bg_dirty_sparse_8_end
    ), "sparse-BG route island labels are no longer ordered"
    for route_name, route_offset, route_target in (
        ("done", rbds_done_8, rmb_obj_begin_8),
        ("clean", rbds_clean_8, rmb_bg_clean_8),
        ("default", rbds_default_8, rmb_bg_dirty_default_8),
    ):
        packed_target = 0x9E0000 | route_target
        expected_jml = bytes(
            (
                0x5C,
                packed_target & 0xFF,
                (packed_target >> 8) & 0xFF,
                (packed_target >> 16) & 0xFF,
            )
        )
        observed_jml = ESC8[
            route_offset - 0x8000:route_offset - 0x8000 + 4
        ]
        assert observed_jml == expected_jml, (
            f"sparse-BG {route_name} route {observed_jml.hex()} no longer "
            f"targets packed ${packed_target:06X}"
        )
    assert ESC8[
        rmb_obj_begin_8 - 0x8000:rmb_obj_begin_8 - 0x8000 + 6
    ] == bytes.fromhex("5c00e69eeaea"), (
        "renderer packed-OBJ scan lost its size-neutral $9E:E600 redirect"
    )
    assert rmb_obj_begin_8 < rmb_bg_reconcile_8 < rmb_bg_promote_8 < rmb_bg_revert_8
    assert rmb_bg_revert_8 < rmb_obj_done_8 == 0xDDF6 < render_manifest_build_8_end
    assert rmb_bg_reconcile_8 < rmb_bg_reconcile_end_8 < rmb_bg_promote_8
    reconcile_bytes = ESC8[
        rmb_bg_reconcile_8 - 0x8000:rmb_obj_done_8 - 0x8000
    ]
    assert reconcile_bytes.count(bytes.fromhex("544141")) == 2, (
        "candidate reconciliation no longer has exact promote/revert MVN fallbacks"
    )
    assert bytes.fromhex("be001a") in reconcile_bytes, (
        "candidate reconciliation lost its retained BG-offset-list reads"
    )
    assert ESC8[
        render_manifest_build_8 - 0x8000:render_manifest_build_8_end - 0x8000
    ].count(bytes.fromhex("5c00e29e")) == 0, (
        "rejected OBJ prefilter redirect reappeared in the live manifest"
    )
    assert rmb_bg_select_8 == 0xDC2C
    assert ESC8[
        rmb_bg_select_8 - 0x8000:rmb_bg_dirty_default_8 - 0x8000
    ] == bytes.fromhex("5c80e29eeaea"), (
        "BG selector lost its size-neutral exact producer-list redirect"
    )
    assert rmb_bg_dirty_default_8 == 0xDC32 < rmb_bg_full_scan_8
    assert rmb_bg_first_8 == 0xDC8C < rmb_bg_first_copy_8 == 0xDC92
    assert ESC8[
        rmb_bg_first_8 - 0x8000:rmb_bg_first_copy_8 - 0x8000
    ] == bytes.fromhex("eaeaeaa20000"), (
        "first-BG manifest path lost its size-neutral C0BC handoff"
    )
    assert shadow_dirty_publish_8 == 0xDE20
    assert ESC8[
        render_manifest_build_8_end - 0x8000:shadow_dirty_publish_8 - 0x8000
    ] == bytes(shadow_dirty_publish_8 - render_manifest_build_8_end), (
        "renderer manifest bytes overlap the fixed map_snes dirty publisher"
    )
    assert ESC8[
        shadow_dirty_publish_8 - 0x8000:shadow_dirty_publish_8 - 0x8000 + 8
    ] == bytes.fromhex("c230a301c915b6f0"), (
        "map_snes publisher lost the pinned rb_zero read-only caller guard"
    )
    assert shadow_dirty_publish_8 < shadow_dirty_publish_8_end == 0xDE6D
    assert (
        rmb_bg_invalidate_tokens_8
        == shadow_dirty_publish_8_end
        < rmb_bg_changed_publish_8
        < rmb_bg_changed_publish_done_8
        < 0xDE80
    )
    assert mark_bg_dirty_8 == 0xDE80
    assert ESC8[
        shadow_dirty_publish_8_end - 0x8000:mark_bg_dirty_8 - 0x8000
    ] == bytes.fromhex("9c4a019c5a0160488f3a0141f00320c0de6860"), (
        "content-based BG invalidation helper moved or overlapped the native marker"
    )
    assert (
        mark_bg_dirty_8
        < mark_bg_dirty_8_end
        <= rmb_bg_first_finish_8
        < rmb_bg_first_prepare_c0bc_8
        < rmb_bg_first_finish_8_end
        <= rmb_bg_validate_tokens_8
        < rmb_bg_validate_invalid_8
        < rmb_bg_validate_tokens_8_end
        <= rmb_prepare_bg_8
    )
    assert rmb_prepare_bg_8 == 0xDF00
    assert ESC8[
        mark_bg_dirty_8_end - 0x8000:rmb_bg_first_finish_8 - 0x8000
    ] == bytes(rmb_bg_first_finish_8 - mark_bg_dirty_8_end), (
        "native BG dirty marker overlapped the first-image dispatcher"
    )
    assert rmb_bg_first_finish_8 == 0xDEA0
    assert ESC8[
        rmb_bg_first_finish_8 - 0x8000:
        rmb_bg_first_finish_8_end - 0x8000
    ] == bytes.fromhex(
        "ad4a01c9bcc0f00d206ddea9ffff8f3a01414cdedc2000df4cdedc"
    ), (
        "first-image C0BC dispatcher moved or changed semantics"
    )
    assert ESC8[
        rmb_bg_first_finish_8_end - 0x8000:rmb_bg_validate_tokens_8 - 0x8000
    ] == bytes(rmb_bg_validate_tokens_8 - rmb_bg_first_finish_8_end), (
        "first-image C0BC dispatcher overlapped the token validator"
    )
    assert rmb_bg_validate_tokens_8 == 0xDEC0
    assert ESC8[
        rmb_bg_validate_tokens_8 - 0x8000:
        rmb_bg_validate_tokens_8_end - 0x8000
    ] == bytes.fromhex(
        "ad4a01c9bcc0d01da20000bf004841dd00a0d011bf004c41dd00a4d008"
        "e8e8e00004d0e7604c6dde"
    ), (
        "C0BC token validator moved or changed exact-plane semantics"
    )
    assert ESC8[
        rmb_bg_validate_tokens_8_end - 0x8000:rmb_prepare_bg_8 - 0x8000
    ] == bytes(rmb_prepare_bg_8 - rmb_bg_validate_tokens_8_end), (
        "C0BC token validator overlapped the prepared-map island"
    )
    assert rmb_prepare_bg_8 < rmb_prepare_bg_8_end <= rpb_prepare_dispatch_8, (
        "prepared-map helper overflowed its bank-$9E tail"
    )
    assert ESC8[
        rpb_sort_outer_8 - 0x8000:rpb_sort_outer_8 - 0x8000 + 4
    ] == bytes.fromhex("cc4601b0"), (
        "prepared-map insertion sort lost its Y>=length empty-list exit"
    )
    assert rpb_prepare_dispatch_8 == 0xE100
    assert rpb_prepare_dispatch_8 < rpb_c0bc_prepared_8
    assert rpb_c0bc_prepared_8 < rpb_prepare_dispatch_8_end <= 0xE180, (
        "$C0BC prepared dispatcher overflowed the palette-mask seam"
    )
    assert h8_zero_mask_gate_8 == 0xE180
    assert ESC8[
        rmb_prepare_bg_8_end - 0x8000:rpb_prepare_dispatch_8 - 0x8000
    ] == bytes(rpb_prepare_dispatch_8 - rmb_prepare_bg_8_end), (
        "dynamic prepared-map helper overlapped its fixed dispatcher"
    )
    assert ESC8[
        rpb_prepare_dispatch_8_end - 0x8000:h8_zero_mask_gate_8 - 0x8000
    ] == bytes(h8_zero_mask_gate_8 - rpb_prepare_dispatch_8_end), (
        "$C0BC prepared dispatcher overlapped the palette-mask shortcut"
    )
    assert (
        h8_zero_mask_gate_8
        < h8_zero_mask_gate_8_end
        <= rmb_obj_x_visible_8
        == 0xE1A0
        < rmb_obj_x_visible_8_end
        <= rmb_obj_prefilter_8
    )
    assert ESC8[
        h8_zero_mask_gate_8_end - 0x8000:rmb_obj_x_visible_8 - 0x8000
    ] == bytes(rmb_obj_x_visible_8 - h8_zero_mask_gate_8_end), (
        "zero-mask gate overlapped the credit-label X helper"
    )
    assert ESC8[
        rmb_obj_x_visible_8_end - 0x8000:rmb_obj_prefilter_8 - 0x8000
    ] == bytes(rmb_obj_prefilter_8 - rmb_obj_x_visible_8_end), (
        "credit-label X helper overlapped the rejected OBJ prefilter island"
    )
    assert rmb_obj_prefilter_8 == 0xE200
    assert rmb_obj_prefilter_8 < rmb_obj_prefilter_8_end <= render_bg_dirty_sparse_8
    assert render_bg_dirty_sparse_8 == 0xE280
    assert (
        render_bg_dirty_sparse_8
        < render_bg_dirty_sparse_8_end
        <= rox_top_x_8
        == 0xE320
        < rox_top_x_8_end
        <= h158_ylist_stage_8
    )
    assert ESC8[
        rmb_obj_prefilter_8_end - 0x8000:render_bg_dirty_sparse_8 - 0x8000
    ] == bytes(render_bg_dirty_sparse_8 - rmb_obj_prefilter_8_end), (
        "OBJ prefilter overlapped the exact BG producer-list helper"
    )
    assert ESC8[
        render_bg_dirty_sparse_8_end - 0x8000:rox_top_x_8 - 0x8000
    ] == bytes(rox_top_x_8 - render_bg_dirty_sparse_8_end), (
        "exact BG producer-list helper overlapped the top-HUD X helper"
    )
    assert ESC8[
        rox_top_x_8_end - 0x8000:h158_ylist_stage_8 - 0x8000
    ] == bytes(h158_ylist_stage_8 - rox_top_x_8_end), (
        "top-HUD X helper overlapped the staged OBJ initializer"
    )
    assert h158_ylist_stage_8 == 0xE400
    assert h158_ylist_stage_8 < h158_ylist_stage_8_end <= rmb_obj_pack_8
    assert rmb_obj_pack_8 == 0xE540
    assert (
        rmb_obj_pack_8
        < rmb_obj_pack_bottom_status_8
        < rmb_obj_pack_bottom_y_8
        < rmb_obj_pack_x_8
        < rmb_obj_pack_8_end
        == 0xE5BF
        <= rmb_title_detect_8
        == 0xE5C0
        < rmb_title_detect_8_end
        <= rmb_obj_fast_scan_8
    )
    packed_obj_helper = ESC8[
        rmb_obj_pack_8 - 0x8000:rmb_obj_pack_8_end - 0x8000
    ]
    assert ESC8[
        rmb_obj_pack_bottom_status_8 - 0x8000:rmb_obj_pack_x_8 - 0x8000
    ] == bytes.fromhex(
        "e00400f00ae048009017e07200b012bd0030c9000af04ce06a009005c9001af042"
    ), (
        "packed OBJ helper lost its exact bottom-status/ROUND source and Y filters"
    )
    for encoding, label in (
        (bytes.fromhex("e06a00"), "ROUND first source slot"),
        (bytes.fromhex("c9001a"), "ROUND Y=$1A row"),
    ):
        assert encoding in packed_obj_helper, (
            f"packed OBJ helper lost its {label} filter"
        )
    assert rmb_obj_fast_scan_8 == 0xE600
    assert rmb_obj_fast_scan_8 < rmb_obj_fast_loop_8 < rmb_obj_fast_done_8
    assert rmb_obj_fast_done_8 < rmb_obj_fast_scan_8_end <= render_bg_offset_table_8
    assert ESC8[
        rmb_obj_fast_scan_8 - 0x8000:rmb_obj_fast_scan_8 - 0x8000 + 6
    ] == bytes.fromhex("a200009be220"), (
        "six-byte OBJ scan lost its 16-bit X/Y zero + A8 prologue"
    )
    assert ESC8[
        rmb_obj_fast_scan_8 - 0x8000:rmb_obj_fast_scan_8_end - 0x8000
    ].count(bytes.fromhex("2040e5")) == 8, (
        "six-byte OBJ scan no longer has eight audited packed-record calls"
    )
    assert ESC8[
        rmb_obj_fast_scan_8 - 0x8000:rmb_obj_fast_scan_8_end - 0x8000
    ].count(bytes.fromhex("c9f3")) == 8, (
        "six-byte OBJ scan no longer retains visible top-HUD rows $F0-$F2"
    )
    assert ESC8[
        rmb_obj_fast_scan_8 - 0x8000:rmb_obj_fast_scan_8_end - 0x8000
    ].count(bytes.fromhex("c970")) == 8, (
        "six-byte OBJ scan no longer admits all eight bottom-row credit slots"
    )
    assert ESC8[
        rmb_obj_fast_done_8 - 0x8000:rmb_obj_fast_scan_8_end - 0x8000
    ].endswith(bytes.fromhex("5cf6dd9e")), (
        "six-byte OBJ scan no longer rejoins the fixed manifest epilogue"
    )
    assert ESC8[
        h158_ylist_first_8 - 0x8000:h158_ylist_first_8 - 0x8000 + 11
    ] == bytes.fromhex("a900008f5801418f5a0141"), (
        "OBJ Y-list first-chunk reset lost its 16-bit LDA/long-store encoding"
    )
    assert render_bg_offset_table_8 == 0xE800
    assert render_bg_offset_table_8_end == 0xEC00
    for seam_start, seam_end, label in (
        (h8_zero_mask_gate_8_end, rmb_obj_x_visible_8, "palette-mask -> credit X"),
        (rmb_obj_x_visible_8_end, rmb_obj_prefilter_8, "credit X -> OBJ prefilter"),
        (rmb_obj_prefilter_8_end, render_bg_dirty_sparse_8, "OBJ prefilter -> exact BG list"),
        (render_bg_dirty_sparse_8_end, rox_top_x_8, "exact BG list -> top-HUD X"),
        (rox_top_x_8_end, h158_ylist_stage_8, "top-HUD X -> Y-list stage"),
        (h158_ylist_stage_8_end, rmb_obj_pack_8, "Y-list stage -> packed OBJ helper"),
        (rmb_obj_pack_8_end, rmb_title_detect_8, "packed OBJ helper -> title detector"),
        (rmb_title_detect_8_end, rmb_obj_fast_scan_8, "title detector -> six-byte scan"),
        (rmb_obj_fast_scan_8_end, render_bg_offset_table_8, "six-byte scan -> BG-offset table"),
    ):
        assert ESC8[
            seam_start - 0x8000:seam_end - 0x8000
        ] == bytes(seam_end - seam_start), (
            "escbank8 %s seam was overwritten" % label
        )
    expected_bg_offsets = bytearray()
    for column in range(16):
        for row in range(32):
            horizontal = column * 8 + (row & 1) * 4
            if horizontal & 0x40:
                horizontal = (horizontal & 0x3F) + 0x0800
            offset = (row & 0x1E) * 64 + horizontal
            expected_bg_offsets.extend(offset.to_bytes(2, "little"))
    assert ESC8[
        render_bg_offset_table_8 - 0x8000:render_bg_offset_table_8_end - 0x8000
    ] == bytes(expected_bg_offsets), (
        "bank-$9E immutable BG-offset table does not match video geometry"
    )
    assert hle_c0bc_8 == render_bg_offset_table_8_end == 0xEC00, (
        "$C0BC selector-zero HLE moved from the fixed $9E:EC00 seam"
    )
    assert hle_c0bc_8 < hc0bc_hle_fast_8 < hc0bc_hle_main_end_8 <= 0xEE00, (
        "$C0BC HLE main path crossed its fixed $9E:EE00 callback continuation"
    )
    assert hle_c0bc_8 < hc0bc_hle_reject_8 < hc0bc_hle_main_end_8
    assert hc0bc_hle_after_29b6_8 == 0xEE00
    assert (
        hc0bc_hle_after_29b6_8
        < hc0bc_hle_done_8
        < hc0bc_hle_after_end_8
        <= hc0bc_token_snapshot_8
        < hc0bc_token_snapshot_8_end
        <= 0xEF00
    ), (
        "$C0BC post-callback path crossed its fixed $9E:EF00 DMA helper"
    )
    assert hc0bc_token_snapshot_8 == 0xEEA0
    assert ESC8[
        hc0bc_token_snapshot_8 - 0x8000:
        hc0bc_token_snapshot_8_end - 0x8000
    ] == bytes.fromhex(
        "8bda5aa9ff03a20048a000a0544141a9ff03a2004ca000a45441417afaab60"
    ), (
        "$C0BC token snapshot moved or changed exact-plane semantics"
    )
    assert ESC8[
        hc0bc_hle_after_end_8 - 0x8000:hc0bc_token_snapshot_8 - 0x8000
    ] == bytes(hc0bc_token_snapshot_8 - hc0bc_hle_after_end_8), (
        "$C0BC post-callback path overlapped its token snapshot helper"
    )
    assert ESC8[
        hc0bc_token_snapshot_8_end - 0x8000:0xEF00 - 0x8000
    ] == bytes(0xEF00 - hc0bc_token_snapshot_8_end), (
        "$C0BC token snapshot helper overlapped fixed $9E:EF00"
    )
    assert hc0bc_hle_dma56_8 == 0xEF00
    assert hc0bc_hle_dma56_8 < rpb_c0bc_rom_dma_8 == 0xEF40
    assert rpb_c0bc_rom_dma_8 < rpb_c0bc_rom_dma_8_end
    assert rpb_c0bc_rom_dma_8_end == hc0bc_hle_end_8 == esc8_physical_end <= 0xF000, (
        "$C0BC DMA helper overflowed the bank-$9E zero-source boundary"
    )
    assert len(ESC8) == esc8_physical_end - 0x8000, (
        "unexpected bytes follow the renderer manifest helper"
    )
    ROM[0x2F0000:0x2F0000+len(ESC8)] = ESC8          # @ SA-1 $9E:8000

    assert ROM[0x2F7000:0x2F8000] == bytes(0x1000), (
        "bank-$9E $F000-$FFFF zero page was overwritten; renderer DMA source is unsafe"
    )
    c0bc_blob_offset = 0x2F8000                       # @ SA-1 $9F:8000
    assert ROM[c0bc_blob_offset:c0bc_blob_offset + len(C0BC_DMA_BLOB)] == bytes(
        len(C0BC_DMA_BLOB)
    ), "$C0BC DMA payload would overwrite nonzero bank-$9F data"
    ROM[c0bc_blob_offset:c0bc_blob_offset + len(C0BC_DMA_BLOB)] = C0BC_DMA_BLOB
    c0bc_prepared_offset = 0x2F9000                   # @ SA-1 $9F:9000
    assert ROM[
        c0bc_prepared_offset:c0bc_prepared_offset + len(C0BC_PREPARED_BLOB)
    ] == bytes(len(C0BC_PREPARED_BLOB)), (
        "$C0BC prepared payload would overwrite nonzero bank-$9F data"
    )
    ROM[
        c0bc_prepared_offset:c0bc_prepared_offset + len(C0BC_PREPARED_BLOB)
    ] = C0BC_PREPARED_BLOB

# --- NINTH SA-1 escape region ($9F:A100+, file $2FA100) ---
# The front of bank $9F is occupied by the two renderer payloads above.
# Poppy anchors this standalone binary at its first logical origin ($A100).
# Pack that complete audited payload at the matching file offset and prove
# both sides of the seam.
if _osp.exists("src/escbank9.bin"):
    ESC9 = Path("src/escbank9.bin").read_bytes()
    assert len(ESC9) <= 0x8000, "escbank9 overflows logical bank $9F"
    esc9_symbols = Path("src/escbank9.sym").read_text(encoding="utf-8-sig")

    def esc9_off(symbol):
        for line in esc9_symbols.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == symbol:
                return int(fields[0].split(":", 1)[1], 16)
        raise AssertionError("missing escbank9 layout symbol %s" % symbol)

    esc9_ac_charge = esc9_off("esc9_ac_charge")
    esc9_ac_charge_end = esc9_off("esc9_ac_charge_end")
    entry_2e42c_9 = esc9_off("entry_2e42c")
    entry_2e42c_9_end = esc9_off("entry_2e42c_end")
    entry_27912t_9 = esc9_off("entry_27912t")
    entry_27912t_9_end = esc9_off("entry_27912t_end")
    entry_2f2e0t_9 = esc9_off("entry_2f2e0t")
    entry_2f2e0t_9_end = esc9_off("entry_2f2e0t_end")
    entry_2e42c_bsr_resume = esc9_off("entry_2e42c_bsr_resume")
    entry_2e42c_callback_resume = esc9_off(
        "entry_2e42c_callback_resume"
    )
    entry_2e42c_resumes_end = esc9_off("entry_2e42c_resumes_end")
    entry_bd1c_callback_resume_1 = esc9_off(
        "entry_bd1c_callback_resume_1"
    )
    entry_bd1c_callback_resume_2 = esc9_off(
        "entry_bd1c_callback_resume_2"
    )
    entry_bd1c_callback_resume_3 = esc9_off(
        "entry_bd1c_callback_resume_3"
    )
    entry_bd1c_callback_resume_4 = esc9_off(
        "entry_bd1c_callback_resume_4"
    )
    entry_bd1c_resumes_end = esc9_off("entry_bd1c_resumes_end")
    entry_278e8_callback_resume_1 = esc9_off(
        "entry_278e8_callback_resume_1"
    )
    entry_278e8_callback_resume_2 = esc9_off(
        "entry_278e8_callback_resume_2"
    )
    entry_278e8_callback_resume_3 = esc9_off(
        "entry_278e8_callback_resume_3"
    )
    entry_278e8_resumes_end = esc9_off("entry_278e8_resumes_end")
    entry_13282_callback_resume_1 = esc9_off(
        "entry_13282_callback_resume_1"
    )
    entry_13282_callback_resume_2 = esc9_off(
        "entry_13282_callback_resume_2"
    )
    entry_13282_resumes_end = esc9_off("entry_13282_resumes_end")
    entry_2e42c_fast_callback_resume = esc9_off(
        "entry_2e42c_fast_callback_resume"
    )
    h2e42c_fast_entry = esc9_off("h2e42c_fast_entry")
    entry_2e42c_fast_end = esc9_off("entry_2e42c_fast_end")
    hbd1c_callback_charge = esc9_off("hbd1c_callback_charge")
    hbd1c_callback_charge_end = esc9_off(
        "hbd1c_callback_charge_end"
    )
    entry_bd1c_9 = esc9_off("entry_bd1c")
    entry_bd1c_9_end = esc9_off("entry_bd1c_end")
    entry_1337et = esc9_off("entry_1337et")
    br1337e_1_9 = esc9_off("br1337e_1")
    entry_1337et_end = esc9_off("entry_1337et_end")
    stage3_79_sparse_dispatch = esc9_off(
        "stage3_79_sparse_dispatch"
    )
    stage3_79_sparse_dispatch_end = esc9_off(
        "stage3_79_sparse_dispatch_end"
    )
    entry_79fe_9 = esc9_off("entry_79fe")
    entry_7ac6_9 = esc9_off("entry_7ac6")
    entry_stage3_79_loop_end = esc9_off(
        "entry_stage3_79_loop_end"
    )
    entry_27aea_9 = esc9_off("entry_27aea")
    entry_27aea_9_end = esc9_off("entry_27aea_end")
    entry_278e8_9 = esc9_off("entry_278e8")
    entry_278e8_9_end = esc9_off("entry_278e8_end")
    hce4_fast_render_2x2 = esc9_off("hce4_fast_render_2x2")
    hce4_fast_render_2x2_end = esc9_off(
        "hce4_fast_render_2x2_end"
    )
    hce4_charge_2x2_dynamic = esc9_off(
        "hce4_charge_2x2_dynamic"
    )
    hce4_charge_2x2_dynamic_end = esc9_off(
        "hce4_charge_2x2_dynamic_end"
    )
    hce4_stage3_panel_try = esc9_off("hce4_stage3_panel_try")
    hce4_stage3_panel_end = esc9_off("hce4_stage3_panel_end")
    entry_13314t_9 = esc9_off("entry_13314t")
    entry_13314t_9_end = esc9_off("entry_13314t_end")
    entry_13282t_9 = esc9_off("entry_13282t")
    entry_13282t_9_end = esc9_off("entry_13282t_end")
    entry_2e676t_9 = esc9_off("entry_2e676t")
    entry_2e676t_9_end = esc9_off("entry_2e676t_end")
    hce4_ac_charge_fast_2x2 = esc9_off("hce4_ac_charge_fast_2x2")
    hce4_ac_charge_fast_2x2_end = esc9_off(
        "hce4_ac_charge_fast_2x2_end"
    )
    hstage3_box_leaf = esc9_off("hstage3_box_leaf")
    hstage3_box_leaf_end = esc9_off("hstage3_box_leaf_end")
    hstage3_collision_leaf = esc9_off("hstage3_collision_leaf")
    hstage3_collision_leaf_end = esc9_off(
        "hstage3_collision_leaf_end"
    )
    hrdw_ea_l = esc9_off("hrdw_ea_l")
    hrdw_ea_l_end = esc9_off("hrdw_ea_l_end")
    entry_133ea_resume_1 = esc9_off("entry_133ea_resume_1")
    entry_133ea_resume_2 = esc9_off("entry_133ea_resume_2")
    entry_133ea_resume_3 = esc9_off("entry_133ea_resume_3")
    entry_13468_resume_1 = esc9_off("entry_13468_resume_1")
    entry_13538_resume_1 = esc9_off("entry_13538_resume_1")
    entry_13538_resume_2 = esc9_off("entry_13538_resume_2")
    stage3_player_hot_resumes_end = esc9_off(
        "stage3_player_hot_resumes_end"
    )
    br133ea_1_9 = esc9_off("br133ea_1")
    br133ea_2_9 = esc9_off("br133ea_2")
    br133ea_3_9 = esc9_off("br133ea_3")
    br13468_1_9 = esc9_off("br13468_1")
    br13538_1_9 = esc9_off("br13538_1")
    br13538_2_9 = esc9_off("br13538_2")
    entry_133eat = esc9_off("entry_133eat")
    entry_133eat_end = esc9_off("entry_133eat_end")
    entry_13468t = esc9_off("entry_13468t")
    entry_13468t_end = esc9_off("entry_13468t_end")
    entry_13538t = esc9_off("entry_13538t")
    entry_13538t_end = esc9_off("entry_13538t_end")
    stage3_player_bsr_ext = esc9_off("stage3_player_bsr_ext")
    stage3_player_bsr_ext_end = esc9_off("stage3_player_bsr_ext_end")
    stage3_bank2_bsr_ext = esc9_off("stage3_bank2_bsr_ext")
    stage3_bank2_bsr_ext_end = esc9_off("stage3_bank2_bsr_ext_end")
    entry_2f542t = esc9_off("entry_2f542t")
    entry_2f542t_end = esc9_off("entry_2f542t_end")
    esc9_vtime_charge_gateway = esc9_off("esc9_vtime_charge_gateway")
    esc9_vtime_ojmp_gateway = esc9_off("esc9_vtime_ojmp_gateway")
    esc9_vtime_ibridge_gateway = esc9_off("esc9_vtime_ibridge_gateway")
    esc9_vtime_ors_gateway = esc9_off("esc9_vtime_ors_gateway")
    esc9_vtime_handoff_due = esc9_off("esc9_vtime_handoff_due")
    esc9_vtime_gateway_end = esc9_off("esc9_vtime_gateway_end")
    esc9_end = esc9_off("escbank9_end")
    assert (
        esc9_ac_charge == 0xA100
        and esc9_ac_charge < esc9_ac_charge_end <= entry_2e42c_9
        == 0xA140
        and entry_2e42c_9 < entry_2e42c_9_end <= entry_27912t_9
        == 0xA500
        and entry_27912t_9 < entry_27912t_9_end <= entry_2f2e0t_9
        == 0xA680
        and entry_2f2e0t_9 < entry_2f2e0t_9_end <= 0xA800
        and entry_2e42c_bsr_resume == 0xA800
        and entry_2e42c_callback_resume == 0xA803
        and entry_2e42c_resumes_end
        == entry_bd1c_callback_resume_1
        == 0xA806
        and entry_bd1c_callback_resume_2 == 0xA809
        and entry_bd1c_callback_resume_3 == 0xA80C
        and entry_bd1c_callback_resume_4 == 0xA80F
        and entry_bd1c_resumes_end
        == entry_278e8_callback_resume_1
        == 0xA812
        and entry_278e8_callback_resume_2 == 0xA815
        and entry_278e8_callback_resume_3 == 0xA818
        and entry_278e8_resumes_end == 0xA81B
        and hbd1c_callback_charge == 0xA820
        and hbd1c_callback_charge
        < hbd1c_callback_charge_end
        <= entry_13282_callback_resume_1
        == 0xA880
        and entry_13282_callback_resume_2 == 0xA883
        and entry_13282_resumes_end == 0xA886
        and entry_2e42c_fast_callback_resume == 0xA900
        and entry_2e42c_fast_callback_resume
        < h2e42c_fast_entry
        < entry_2e42c_fast_end
        <= 0xB000
        and entry_bd1c_9 == 0xB000
        and entry_bd1c_9 < entry_bd1c_9_end <= entry_1337et
        == 0xBA00
        and entry_1337et < br1337e_1_9 == 0xBD18
        and entry_1337et_end == 0xBD6D
        and entry_1337et_end <= stage3_79_sparse_dispatch
        == 0xBD80
        and stage3_79_sparse_dispatch
        < stage3_79_sparse_dispatch_end
        <= entry_79fe_9
        == 0xBE00
        and entry_7ac6_9 == 0xBE10
        and entry_7ac6_9 < entry_stage3_79_loop_end
        <= entry_27aea_9
        == 0xC000
        and entry_27aea_9 < entry_27aea_9_end <= entry_278e8_9
        == 0xD000
        and entry_278e8_9 < entry_278e8_9_end <= hce4_fast_render_2x2
        == 0xD200
        and hce4_fast_render_2x2
        < hce4_fast_render_2x2_end
        <= hce4_charge_2x2_dynamic
        == 0xD300
        and hce4_charge_2x2_dynamic
        < hce4_charge_2x2_dynamic_end
        <= hce4_stage3_panel_try
        == 0xD400
        and hce4_stage3_panel_try
        < hce4_stage3_panel_end
        <= entry_13314t_9
        == 0xD800
        and entry_13314t_9 < entry_13314t_9_end == 0xD99E
        and entry_13314t_9_end <= entry_13282t_9
        == 0xE000
        and entry_13282t_9 < entry_13282t_9_end == 0xE3F2
        and entry_13282t_9_end <= entry_2e676t_9
        == 0xE400
        and entry_2e676t_9 < entry_2e676t_9_end <= 0xE800
        and entry_2e676t_9_end <= hce4_ac_charge_fast_2x2
        == 0xE700
        and hce4_ac_charge_fast_2x2
        < hce4_ac_charge_fast_2x2_end
        <= 0xE800
        and hce4_ac_charge_fast_2x2_end <= hstage3_box_leaf
        == 0xE800
        and hstage3_box_leaf < hstage3_box_leaf_end <= 0xF000
        and hstage3_box_leaf_end <= hstage3_collision_leaf
        == 0xE900
        and hstage3_collision_leaf < hstage3_collision_leaf_end <= 0xF000
        and hstage3_collision_leaf_end <= hrdw_ea_l
        == 0xEB00
        and hrdw_ea_l < hrdw_ea_l_end <= 0xEC00
        and hrdw_ea_l_end <= entry_133ea_resume_1
        == 0xEB40
        and entry_133ea_resume_2 == 0xEB43
        and entry_133ea_resume_3 == 0xEB46
        and entry_13468_resume_1 == 0xEB49
        and entry_13538_resume_1 == 0xEB4C
        and entry_13538_resume_2 == 0xEB4F
        and stage3_player_hot_resumes_end == 0xEB52
        and stage3_player_hot_resumes_end <= entry_133eat
        == 0xEC00
        and entry_133eat < entry_133eat_end <= entry_13468t
        == 0xF100
        and entry_13468t < entry_13468t_end <= entry_13538t
        == 0xF700
        and entry_13538t < entry_13538t_end <= stage3_player_bsr_ext
        == 0xFD00
        and stage3_player_bsr_ext
        < stage3_player_bsr_ext_end
        <= stage3_bank2_bsr_ext
        == 0xFDB0
        and stage3_bank2_bsr_ext
        < stage3_bank2_bsr_ext_end
        <= entry_2f542t
        == 0xFE00
        and entry_2f542t < entry_2f542t_end
        == esc9_vtime_charge_gateway
        == 0xFFA1
        and esc9_vtime_charge_gateway
        < esc9_vtime_ojmp_gateway
        < esc9_vtime_ibridge_gateway
        < esc9_vtime_ors_gateway
        < esc9_vtime_handoff_due
        < esc9_vtime_gateway_end
        == esc9_end
        <= 0x10000
    ), "bank-$9F Stage-3 selector/scroll task moved or overflowed a fixed island"
    assert len(ESC9) == esc9_end - esc9_ac_charge, (
        "unexpected bank-$9F bytes follow the Stage-3 player-hot bodies"
    )
    assert ESC9[
        esc9_ac_charge_end - esc9_ac_charge:
        entry_2e42c_9 - esc9_ac_charge
    ] == bytes(entry_2e42c_9 - esc9_ac_charge_end), (
        "bank-$9F AC helper consumed the selector seam"
    )
    assert ESC9[
        entry_2e42c_9_end - esc9_ac_charge:
        entry_27912t_9 - esc9_ac_charge
    ] == bytes(entry_27912t_9 - entry_2e42c_9_end), (
        "$02E42C selector consumed the $027912 dispatcher seam"
    )
    assert ESC9[
        entry_27912t_9_end - esc9_ac_charge:
        entry_2f2e0t_9 - esc9_ac_charge
    ] == bytes(entry_2f2e0t_9 - entry_27912t_9_end), (
        "$027912 dispatcher consumed the $02F2E0 dispatcher seam"
    )
    assert ESC9[
        entry_2f2e0t_9_end - esc9_ac_charge:
        entry_2e42c_bsr_resume - esc9_ac_charge
    ] == bytes(entry_2e42c_bsr_resume - entry_2f2e0t_9_end), (
        "$02F2E0 dispatcher consumed the fixed resume-adapter seam"
    )
    assert ESC9[
        entry_278e8_resumes_end - esc9_ac_charge:
        hbd1c_callback_charge - esc9_ac_charge
    ] == bytes(hbd1c_callback_charge - entry_278e8_resumes_end), (
        "bank-$9F resume adapters consumed the callback-charge seam"
    )
    assert ESC9[
        hbd1c_callback_charge_end - esc9_ac_charge:
        entry_13282_callback_resume_1 - esc9_ac_charge
    ] == bytes(
        entry_13282_callback_resume_1 - hbd1c_callback_charge_end
    ), "bank-$9F callback-charge helper consumed the $013282 resume seam"
    assert ESC9[
        entry_13282_resumes_end - esc9_ac_charge:
        entry_2e42c_fast_callback_resume - esc9_ac_charge
    ] == bytes(
        entry_2e42c_fast_callback_resume - entry_13282_resumes_end
    ), "bank-$9F $013282 resumes consumed the fast-selector seam"
    assert ESC9[
        entry_2e42c_fast_end - esc9_ac_charge:
        entry_bd1c_9 - esc9_ac_charge
    ] == bytes(entry_bd1c_9 - entry_2e42c_fast_end), (
        "$02E42C fast selector consumed the scroll-task seam"
    )
    assert ESC9[
        entry_bd1c_9_end - esc9_ac_charge:
        entry_1337et - esc9_ac_charge
    ] == bytes(entry_1337et - entry_bd1c_9_end), (
        "bank-$9F scroll task consumed the $01337E seam"
    )
    body_1337e_bytes = ESC9[
        entry_1337et - esc9_ac_charge:
        entry_1337et_end - esc9_ac_charge
    ]
    assert body_1337e_bytes.startswith(
        bytes.fromhex(
            "c230a536c9f000d02ca534d028a53ac9f000d021"
            "a538c96c00901ac90040b015"
            "a53ec9f000d00ea53cc950009007c9fd3fb002800e"
        )
    ), (
        "$01337E lost its exact A5/A6-$006C/A7-$0050 canonical guard"
    )
    assert body_1337e_bytes.count(bytes.fromhex("2000a1")) == 9, (
        "$01337E lost an AC-charge basic block"
    )
    assert body_1337e_bytes.count(bytes.fromhex("5c28f892")) == 1, (
        "$01337E lost its sole bank-$92 indirect-call bridge"
    )
    assert body_1337e_bytes.count(
        bytes.fromhex("a9f8e78540a9f8008542")
    ) == 1, (
        "$01337E lost its pinned bank-$9D return trampoline tag"
    )
    assert body_1337e_bytes.count(bytes.fromhex("1a3a")) == 2, (
        "$01337E lost one of its two exact TST.W N/Z materializers"
    )
    assert body_1337e_bytes.endswith(bytes.fromhex("5c6fd100")), (
        "$01337E lost its exact terminal mapped-RTS jump"
    )
    assert ESC9[
        entry_1337et_end - esc9_ac_charge:
        stage3_79_sparse_dispatch - esc9_ac_charge
    ] == bytes(stage3_79_sparse_dispatch - entry_1337et_end), (
        "$01337E consumed the $0079FE sparse-dispatch seam"
    )
    stage3_79_dispatch_bytes = ESC9[
        stage3_79_sparse_dispatch - esc9_ac_charge:
        stage3_79_sparse_dispatch_end - esc9_ac_charge
    ]
    for encoded, label in (
        (bytes.fromhex("4c00be"), "$0079FE local entry"),
        (bytes.fromhex("4c10be"), "$007AC6 local entry"),
        (bytes.fromhex("5c00a79e"), "$76/$77 fan-out"),
        (bytes.fromhex("5c31f994"), "generic xlat miss"),
    ):
        assert stage3_79_dispatch_bytes.count(encoded) == 1, (
            "Stage-3 low-page sparse dispatcher lost its sole " + label
        )
    assert ESC9[
        stage3_79_sparse_dispatch_end - esc9_ac_charge:
        entry_79fe_9 - esc9_ac_charge
    ] == bytes(entry_79fe_9 - stage3_79_sparse_dispatch_end), (
        "Stage-3 low-page dispatcher consumed the $0079FE entry seam"
    )
    stage3_79_loop_bytes = ESC9[
        entry_79fe_9 - esc9_ac_charge:
        entry_stage3_79_loop_end - esc9_ac_charge
    ]
    assert stage3_79_loop_bytes.count(bytes.fromhex("2000a1")) == 1, (
        "$0079FE hot path lost its cumulative AC charge"
    )
    assert stage3_79_loop_bytes.count(bytes.fromhex("5c28d100")) == 2, (
        "$0079FE hot/cold paths lost an interpreter delegation"
    )
    assert ESC9[
        entry_stage3_79_loop_end - esc9_ac_charge:
        entry_27aea_9 - esc9_ac_charge
    ] == bytes(entry_27aea_9 - entry_stage3_79_loop_end), (
        "$0079FE loop consumed the $027AEA leaf seam"
    )
    leaf_27aea_bytes = ESC9[
        entry_27aea_9 - esc9_ac_charge:
        entry_27aea_9_end - esc9_ac_charge
    ]
    assert leaf_27aea_bytes.count(bytes.fromhex("2000a1")) == 8, (
        "$027AEA lost an AC-charge basic block"
    )
    assert ESC9[
        entry_27aea_9_end - esc9_ac_charge:
        entry_278e8_9 - esc9_ac_charge
    ] == bytes(entry_278e8_9 - entry_27aea_9_end), (
        "bank-$9F $027AEA leaf consumed the $0278E8 parent seam"
    )
    parent_278e8_bytes = ESC9[
        entry_278e8_9 - esc9_ac_charge:
        entry_278e8_9_end - esc9_ac_charge
    ]
    assert parent_278e8_bytes.count(bytes.fromhex("2000a1")) == 6
    assert parent_278e8_bytes.count(bytes.fromhex("5c00a59f")) == 2
    for encoded in (
        bytes.fromhex("a9d8e38554a9f8008556"),
        bytes.fromhex("a9dce38554a9f8008556"),
        bytes.fromhex("a9e0e38554a9f8008556"),
    ):
        assert parent_278e8_bytes.count(encoded) == 1, (
            "$0278E8 lost a pinned bank-$9D callback continuation"
        )
    assert ESC9[
        entry_278e8_9_end - esc9_ac_charge:
        hce4_fast_render_2x2 - esc9_ac_charge
    ] == bytes(hce4_fast_render_2x2 - entry_278e8_9_end), (
        "bank-$9F $0278E8 parent consumed the CE4 fused-render seam"
    )
    ce4_fast_render_bytes = ESC9[
        hce4_fast_render_2x2 - esc9_ac_charge:
        hce4_fast_render_2x2_end - esc9_ac_charge
    ]
    assert sum(
        ce4_fast_render_bytes.count(bytes((0x97, pointer)))
        for pointer in (0x54, 0x58, 0x5C)
    ) == 12, (
        "CE4 fused 2x2 renderer lost one of its twelve output-word writes"
    )
    assert ce4_fast_render_bytes.count(
        bytes.fromhex("a9ffff8592a901008570856e85a2646064726b")
    ) == 1, "CE4 fused 2x2 renderer lost its exact exhausted-D7 CCR/X tail"
    assert ESC9[
        hce4_fast_render_2x2_end - esc9_ac_charge:
        hce4_charge_2x2_dynamic - esc9_ac_charge
    ] == bytes(
        hce4_charge_2x2_dynamic - hce4_fast_render_2x2_end
    ), "CE4 fused renderer consumed its dynamic-charge seam"
    ce4_dynamic_charge_bytes = ESC9[
        hce4_charge_2x2_dynamic - esc9_ac_charge:
        hce4_charge_2x2_dynamic_end - esc9_ac_charge
    ]
    assert ce4_dynamic_charge_bytes.count(bytes.fromhex("2000a1")) == 1, (
        "CE4 dynamic 2x2 charge lost its sole scheduler charge"
    )
    assert ce4_dynamic_charge_bytes.endswith(
        bytes.fromhex("1865ae85ae60")
    ), (
        "CE4 dynamic 2x2 charge lost its add-and-return tail"
    )
    assert ESC9[
        hce4_charge_2x2_dynamic_end - esc9_ac_charge:
        hce4_stage3_panel_try - esc9_ac_charge
    ] == bytes(
        hce4_stage3_panel_try - hce4_charge_2x2_dynamic_end
    ), "CE4 dynamic charge consumed the Stage-3 panel seam"
    panel_bytes = ESC9[
        hce4_stage3_panel_try - esc9_ac_charge:
        hce4_stage3_panel_end - esc9_ac_charge
    ]
    assert panel_bytes.startswith(
        bytes.fromhex("c230a582c9c500")
    ), "CE4 Stage-3 panel lost its mapped-source-bank guard"
    assert panel_bytes.count(bytes.fromhex("205ed5")) == 19, (
        "CE4 Stage-3 panel lost one of its variant/common emit call sites"
    )
    for tile in (
        0x21BF, 0x21C0, 0x21C1, 0x21C2, 0x21C3,
        0x21C4, 0x21C5, 0x21C6, 0x21C7, 0x21C8, 0x21C9,
        0x21CA, 0x21CB, 0x21CC,
        0x21CD, 0x21CE, 0x21CF, 0x21D0,
    ):
        encoded = bytes((0xA9, tile & 0xFF, tile >> 8))
        assert panel_bytes.count(encoded) >= 1, (
            f"CE4 Stage-3 panel lost authenticated tile ${tile:04X}"
        )
    assert panel_bytes.endswith(
        bytes.fromhex("a584c901005c46e49d")
    ), "CE4 Stage-3 panel lost its size-neutral bank-$9D fallback"
    assert ESC9[
        hce4_stage3_panel_end - esc9_ac_charge:
        entry_13314t_9 - esc9_ac_charge
    ] == bytes(entry_13314t_9 - hce4_stage3_panel_end), (
        "CE4 Stage-3 panel consumed the $013314 seam"
    )
    body_13314_bytes = ESC9[
        entry_13314t_9 - esc9_ac_charge:
        entry_13314t_9_end - esc9_ac_charge
    ]
    assert body_13314_bytes.startswith(
        bytes.fromhex(
            "c230a53ac9f000d01ca538c940009015c90040b010"
            "a53ec9f000d009a53cc9fd3fb002800e"
            "a914338540a9010085425c28d100"
        )
    ), "$013314 lost its exact A6/A7 canonical guard"
    assert body_13314_bytes.count(bytes.fromhex("2000a1")) == 9, (
        "$013314 lost an AC-charge basic block"
    )
    assert body_13314_bytes.endswith(bytes.fromhex("5c6fd100")), (
        "$013314 lost its exact terminal mapped-RTS jump"
    )
    assert ESC9[
        entry_13314t_9_end - esc9_ac_charge:
        entry_13282t_9 - esc9_ac_charge
    ] == bytes(entry_13282t_9 - entry_13314t_9_end), (
        "bank-$9F $013314 clamp consumed the $013282 seam"
    )
    body_13282_bytes = ESC9[
        entry_13282t_9 - esc9_ac_charge:
        entry_13282t_9_end - esc9_ac_charge
    ]
    assert body_13282_bytes.count(bytes.fromhex("2000a1")) == 9, (
        "$013282 lost an AC-charge basic block"
    )
    for encoded in (
        bytes.fromhex("a9e4e38554a9f8008556"),
        bytes.fromhex("a9e8e38554a9f8008556"),
    ):
        assert body_13282_bytes.count(encoded) == 1, (
            "$013282 lost a pinned bank-$9D callback continuation"
        )
    assert ESC9[
        entry_13282t_9_end - esc9_ac_charge:
        entry_2e676t_9 - esc9_ac_charge
    ] == bytes(entry_2e676t_9 - entry_13282t_9_end), (
        "bank-$9F $013282 consumed the $02E676 seam"
    )
    body_2e676_bytes = ESC9[
        entry_2e676t_9 - esc9_ac_charge:
        entry_2e676t_9_end - esc9_ac_charge
    ]
    assert body_2e676_bytes.count(bytes.fromhex("2000a1")) == 8, (
        "$02E676 lost an AC-charge basic block"
    )
    assert ESC9[
        entry_2e676t_9_end - esc9_ac_charge:
        hce4_ac_charge_fast_2x2 - esc9_ac_charge
    ] == bytes(hce4_ac_charge_fast_2x2 - entry_2e676t_9_end), (
        "bank-$9F $02E676 body consumed the CE4 charge-helper seam"
    )
    ce4_fast_charge_bytes = ESC9[
        hce4_ac_charge_fast_2x2 - esc9_ac_charge:
        hce4_ac_charge_fast_2x2_end - esc9_ac_charge
    ]
    assert ce4_fast_charge_bytes.count(bytes.fromhex("2000d3")) == 1, (
        "CE4 2x2 shortcut lost its dynamic clipping-aware AC charge"
    )
    assert ce4_fast_charge_bytes.count(
        bytes.fromhex("a94d012000a1")
    ) == 1, (
        "CE4 Stage-3 panel shortcut lost its exact 333-instruction AC charge"
    )
    for encoded, label in (
        (bytes.fromhex("c9ee2a"), "$042AEA source"),
        (bytes.fromhex("c91c2b"), "$042B18 source"),
    ):
        assert ce4_fast_charge_bytes.count(encoded) == 1, (
            "CE4 Stage-3 panel charge guard lost its sole " + label
        )
    for retained_word in (0x74, 0x76, 0x78, 0x7A):
        assert ce4_fast_charge_bytes.count(
            bytes((0x85, retained_word))
        ) == 1, (
            "CE4 2x2 shortcut lost a retained source word"
        )
    assert ce4_fast_charge_bytes.count(bytes.fromhex("a90100856a")) == 1, (
        "CE4 2x2 shortcut lost its fused-render route marker"
    )
    assert ce4_fast_charge_bytes.count(bytes.fromhex("646a")) == 2, (
        "CE4 charge shortcuts lost a panel/fallback route-marker clear"
    )
    assert ce4_fast_charge_bytes.count(bytes.fromhex("5c3bcb94")) == 2, (
        "CE4 2x2/panel shortcuts lost a fixed bank-$94 RTS return"
    )
    assert ce4_fast_charge_bytes.count(bytes.fromhex("5c30ca94")) == 1, (
        "CE4 2x2 shortcut lost its exact-counter fallback"
    )
    assert ESC9[
        hce4_ac_charge_fast_2x2_end - esc9_ac_charge:
        hstage3_box_leaf - esc9_ac_charge
    ] == bytes(hstage3_box_leaf - hce4_ac_charge_fast_2x2_end), (
        "CE4 charge shortcut consumed the Stage-3 box-emitter seam"
    )
    box_leaf_bytes = ESC9[
        hstage3_box_leaf - esc9_ac_charge:
        hstage3_box_leaf_end - esc9_ac_charge
    ]
    assert box_leaf_bytes.count(bytes.fromhex("a910002000a1")) == 1, (
        "Stage-3 box emitter lost its exact 16-instruction AC charge"
    )
    assert ESC9[
        hstage3_box_leaf_end - esc9_ac_charge:
        hstage3_collision_leaf - esc9_ac_charge
    ] == bytes(hstage3_collision_leaf - hstage3_box_leaf_end), (
        "Stage-3 box emitter consumed the collision-emitter seam"
    )
    collision_leaf_bytes = ESC9[
        hstage3_collision_leaf - esc9_ac_charge:
        hstage3_collision_leaf_end - esc9_ac_charge
    ]
    assert (
        collision_leaf_bytes.count(bytes.fromhex("a90400")) >= 2
        and collision_leaf_bytes.count(bytes.fromhex("a90300")) == 1
        and collision_leaf_bytes.count(bytes.fromhex("2000a1")) == 3
    ), (
        "Stage-3 collision emitter lost its parent/callee AC charges"
    )
    assert collision_leaf_bytes.count(bytes.fromhex("a910002000a1")) == 1, (
        "Stage-3 collision emitter lost its exact 16-instruction tail charge"
    )
    assert ESC9[
        hstage3_collision_leaf_end - esc9_ac_charge:
        hrdw_ea_l - esc9_ac_charge
    ] == bytes(hrdw_ea_l - hstage3_collision_leaf_end), (
        "Stage-3 collision emitter consumed the rdw_ea_l seam"
    )
    assert ESC9[
        hrdw_ea_l_end - esc9_ac_charge:
        entry_133ea_resume_1 - esc9_ac_charge
    ] == bytes(entry_133ea_resume_1 - hrdw_ea_l_end), (
        "rdw_ea_l consumed the player-hot resume seam"
    )
    player_hot_resume_bytes = b"".join(
        bytes((0x4C, target & 0xFF, target >> 8))
        for target in (
            br133ea_1_9,
            br133ea_2_9,
            br133ea_3_9,
            br13468_1_9,
            br13538_1_9,
            br13538_2_9,
        )
    )
    assert ESC9[
        entry_133ea_resume_1 - esc9_ac_charge:
        stage3_player_hot_resumes_end - esc9_ac_charge
    ] == player_hot_resume_bytes, (
        "Stage-3 player-hot resume adapters no longer JMP to their "
        "assembled continuation labels"
    )
    assert ESC9[
        stage3_player_hot_resumes_end - esc9_ac_charge:
        entry_133eat - esc9_ac_charge
    ] == bytes(entry_133eat - stage3_player_hot_resumes_end), (
        "player-hot resume adapters consumed the $0133EA seam"
    )
    assert ESC9[
        entry_133eat_end - esc9_ac_charge:
        entry_13468t - esc9_ac_charge
    ] == bytes(entry_13468t - entry_133eat_end), (
        "$0133EA consumed the $013468 seam"
    )
    assert ESC9[
        entry_13468t_end - esc9_ac_charge:
        entry_13538t - esc9_ac_charge
    ] == bytes(entry_13538t - entry_13468t_end), (
        "$013468 consumed the $013538 seam"
    )
    assert ESC9[
        entry_13538t_end - esc9_ac_charge:
        stage3_player_bsr_ext - esc9_ac_charge
    ] == bytes(stage3_player_bsr_ext - entry_13538t_end), (
        "$013538 consumed the player-hot BSR-extension seam"
    )
    player_13538_bytes = ESC9[
        entry_13538t - esc9_ac_charge:
        entry_13538t_end - esc9_ac_charge
    ]
    h135e0_direct_jsl = bytes(
        (0x22, h135e0_direct & 0xFF, h135e0_direct >> 8, 0x94)
    )
    assert player_13538_bytes.count(h135e0_direct_jsl) == 2, (
        "$013538 lost one of its two guarded direct $0135E0 call sites"
    )
    player_bsr_bytes = ESC9[
        stage3_player_bsr_ext - esc9_ac_charge:
        stage3_player_bsr_ext_end - esc9_ac_charge
    ]
    for encoded, label in (
        (bytes.fromhex("5cf8f592"), "miss -> $92:F5F8"),
        (bytes.fromhex("5c00d89f"), "$013314 -> $9F:D800"),
        (bytes.fromhex("5c00ba9f"), "$01337E -> $9F:BA00"),
        (bytes.fromhex("5c00ec9f"), "$0133EA -> $9F:EC00"),
        (bytes.fromhex("5c00f19f"), "$013468 -> $9F:F100"),
        (bytes.fromhex("5c00f79f"), "$013538 -> $9F:F700"),
    ):
        assert player_bsr_bytes.count(encoded) == 1, (
            "player-hot BSR extension lost its sole " + label
        )
    assert ESC9[
        stage3_player_bsr_ext_end - esc9_ac_charge:
        stage3_bank2_bsr_ext - esc9_ac_charge
    ] == bytes(stage3_bank2_bsr_ext - stage3_player_bsr_ext_end), (
        "player-hot BSR extension consumed the bank-$02 BSR seam"
    )
    bank2_bsr_bytes = ESC9[
        stage3_bank2_bsr_ext - esc9_ac_charge:
        stage3_bank2_bsr_ext_end - esc9_ac_charge
    ]
    for encoded, label in (
        (bytes.fromhex("5cf8f592"), "miss -> $92:F5F8"),
        (bytes.fromhex("5c40a19f"), "$02E42C -> $9F:A140"),
        (bytes.fromhex("5c40d594"), "$02E40E -> $94:D540"),
        (bytes.fromhex("5c40d394"), "$02E49C -> $94:D340"),
        (bytes.fromhex("5c00a59f"), "$027912 -> $9F:A500"),
        (bytes.fromhex("5c00fe9f"), "$02F542 -> $9F:FE00"),
    ):
        assert bank2_bsr_bytes.count(encoded) == 1, (
            "bank-$02 BSR extension lost its sole " + label
        )
    assert ESC9[
        stage3_bank2_bsr_ext_end - esc9_ac_charge:
        entry_2f542t - esc9_ac_charge
    ] == bytes(entry_2f542t - stage3_bank2_bsr_ext_end), (
        "bank-$02 BSR extension consumed the $02F542 seam"
    )
    body_2f542_bytes = ESC9[
        entry_2f542t - esc9_ac_charge:
        entry_2f542t_end - esc9_ac_charge
    ]
    assert body_2f542_bytes.count(bytes.fromhex("2000a1")) == 6, (
        "$02F542 lost an AC-charge basic block"
    )
    selector_bytes = ESC9[
        entry_2e42c_9 - esc9_ac_charge:
        entry_2e42c_9_end - esc9_ac_charge
    ]
    assert selector_bytes.count(bytes.fromhex("a9c0e38554a9f8008556")) == 1, (
        "$02E42C lost its sole bank-$9D BSR return trampoline tag"
    )
    assert selector_bytes.count(bytes.fromhex("a9c4e38540a9f8008542")) == 1, (
        "$02E42C lost its sole bank-$9D callback return trampoline tag"
    )
    selector_fast_bytes = ESC9[
        entry_2e42c_fast_callback_resume - esc9_ac_charge:
        entry_2e42c_fast_end - esc9_ac_charge
    ]
    assert selector_fast_bytes.count(
        bytes.fromhex("a9f0e385408554")
    ) == 1, (
        "$02E42C fast loop lost its callback return low-word publication"
    )
    assert selector_fast_bytes.count(
        bytes.fromhex("a9f80085428556")
    ) == 1, (
        "$02E42C fast loop lost its callback return bank publication"
    )
    assert selector_fast_bytes.count(bytes.fromhex("22aee500")) == 1, (
        "$02E42C fast loop lost its sole callback return push"
    )
    assert selector_fast_bytes.count(bytes.fromhex("5c28f892")) == 0, (
        "$02E42C fast loop unexpectedly retained the generic indirect bridge"
    )
    assert selector_fast_bytes.count(bytes.fromhex("4c80a6")) == 1, (
        "$02E42C fast loop lost its direct $02F2E0 callback edge"
    )
    assert selector_fast_bytes.count(bytes.fromhex("4c00d0")) == 1, (
        "$02E42C fast loop lost its direct $0278E8 callback edge"
    )
    assert selector_fast_bytes.count(bytes.fromhex("9f000040")) == 3, (
        "$02E42C fast loop lost its base big-endian frame/residue stores"
    )
    assert selector_fast_bytes.count(bytes.fromhex("bf000040")) == 3, (
        "$02E42C fast loop lost its base big-endian frame/return reads"
    )
    dispatcher_27912_bytes = ESC9[
        entry_27912t_9 - esc9_ac_charge:
        entry_27912t_9_end - esc9_ac_charge
    ]
    dispatcher_2f2e0_bytes = ESC9[
        entry_2f2e0t_9 - esc9_ac_charge:
        entry_2f2e0t_9_end - esc9_ac_charge
    ]
    assert dispatcher_27912_bytes.count(bytes.fromhex("5c00b694")) == 1
    assert dispatcher_27912_bytes.count(bytes.fromhex("5c00bc94")) == 1
    assert dispatcher_2f2e0_bytes.count(bytes.fromhex("5c00c294")) == 1
    assert dispatcher_27912_bytes.count(bytes.fromhex("2000a1")) == 1
    assert dispatcher_2f2e0_bytes.count(bytes.fromhex("2000a1")) == 1
    bsr_cont = esc9_off("br2e42c_1")
    callback_cont = esc9_off("br2e42c_2")
    assert ESC9[
        entry_2e42c_bsr_resume - esc9_ac_charge:
        entry_2e42c_resumes_end - esc9_ac_charge
    ] == bytes(
        (
            0x4C,
            bsr_cont & 0xFF,
            bsr_cont >> 8,
            0x4C,
            callback_cont & 0xFF,
            callback_cont >> 8,
        )
    ), "bank-$9F selector resume adapters no longer JMP locally"
    bd1c_conts = [esc9_off(f"brbd1c_{index}") for index in range(1, 5)]
    assert ESC9[
        entry_bd1c_callback_resume_1 - esc9_ac_charge:
        entry_bd1c_resumes_end - esc9_ac_charge
    ] == bytes(
        byte
        for cont in bd1c_conts
        for byte in (0x4C, cont & 0xFF, cont >> 8)
    ), "bank-$9F scroll-task resume adapters no longer JMP locally"
    body_13282_conts = [
        esc9_off(f"br13282_{index}") for index in range(1, 3)
    ]
    assert ESC9[
        entry_13282_callback_resume_1 - esc9_ac_charge:
        entry_13282_resumes_end - esc9_ac_charge
    ] == bytes(
        byte
        for cont in body_13282_conts
        for byte in (0x4C, cont & 0xFF, cont >> 8)
    ), "bank-$9F $013282 resume adapters no longer JMP locally"
    scroll_bytes = ESC9[
        entry_bd1c_9 - esc9_ac_charge:
        entry_bd1c_9_end - esc9_ac_charge
    ]
    assert ESC9[
        hbd1c_callback_charge - esc9_ac_charge:
        hbd1c_callback_charge_end - esc9_ac_charge
    ] == bytes.fromhex(
        "a522d017a520c95a29f00ac94227d00b"
        "a94d018003a90e002000a160"
    ), "$00BD1C callback-charge helper moved or changed its exact source classes"
    assert scroll_bytes.count(bytes.fromhex("2020a8")) == 4, (
        "$00BD1C lost one of its four callback-charge calls"
    )
    for trampoline in (0xE3C8, 0xE3CC, 0xE3D0, 0xE3D4):
        tag = bytes(
            (0xA9, trampoline & 0xFF, trampoline >> 8,
             0x85, 0x40, 0xA9, 0xF8, 0x00, 0x85, 0x42)
        )
        assert scroll_bytes.count(tag) == 1, (
            "$00BD1C lost its sole pinned callback trampoline "
            f"${trampoline:04X}"
        )

    # The diagnostic player ledger is intentionally narrower than a common
    # clock, but it must still be internally complete: all 83 table entries
    # are real generated block charges in the six admitted player bodies, and
    # every terminal JSR/RTS handoff flushes its pending block before leaving
    # that ledger.  Do this with pack-time byte substitutions only for
    # VTIME=1; normal ROMs preserve every original helper target exactly.
    VTIME_ESC9_RETURN_BASE = 0xBA00
    vtime_esc9_index = Path("src/vtime_esc9_charge_index.bin").read_bytes()
    vtime_esc9_cost = Path("src/vtime_esc9_charge_cost.bin").read_bytes()
    vtime_esc9_pc = Path("src/vtime_esc9_charge_pc.bin").read_bytes()
    vtime_esc9_terminal = Path("src/vtime_esc9_charge_terminal.bin").read_bytes()
    assert (
        len(vtime_esc9_index) == 17011
        and len(vtime_esc9_cost) == 83
        and len(vtime_esc9_pc) == 166
        and len(vtime_esc9_terminal) == 166
    ), "bank-$9F VTIME metadata changed; regenerate and audit its fixed layout"
    assert (
        vtime_code[0x3A00:0x3A00 + len(vtime_esc9_index)] == vtime_esc9_index
        and vtime_code[0x7C80:0x7C80 + len(vtime_esc9_cost)] == vtime_esc9_cost
        and vtime_code[0x7CD3:0x7CD3 + len(vtime_esc9_pc)] == vtime_esc9_pc
        and vtime_code[0x7D80:0x7D80 + len(vtime_esc9_terminal)] == vtime_esc9_terminal
    ), "bank-$9F VTIME metadata was not packed at its audited F2 offsets"
    player_vtime_ranges = (
        (entry_13282t_9, entry_13282t_9_end),
        (entry_13314t_9, entry_13314t_9_end),
        (entry_1337et, entry_1337et_end),
        (entry_133eat, entry_133eat_end),
        (entry_13468t, entry_13468t_end),
        (entry_13538t, entry_13538t_end),
    )
    player_vtime_returns = [
        VTIME_ESC9_RETURN_BASE + offset
        for offset, ordinal in enumerate(vtime_esc9_index)
        if ordinal
    ]
    assert (
        len(player_vtime_returns) == 83
        and sorted(vtime_esc9_index[offset] for offset, ordinal in enumerate(vtime_esc9_index) if ordinal)
        == list(range(1, 84))
    ), "bank-$9F VTIME sparse index lost a block or ordinal"
    player_vtime_call_offsets = []
    legacy_esc9_charge_call = bytes(
        (0x20, esc9_ac_charge & 0xFF, esc9_ac_charge >> 8)
    )
    for return_pc in player_vtime_returns:
        call_pc = return_pc - 3
        assert any(
            start <= call_pc and return_pc <= end
            for start, end in player_vtime_ranges
        ), (
            "bank-$9F VTIME table return $%04X is outside an admitted "
            "Stage-3 player body" % return_pc
        )
        call_offset = call_pc - esc9_ac_charge
        assert ESC9[call_offset:call_offset + 3] == legacy_esc9_charge_call, (
            "bank-$9F VTIME table return $%04X no longer follows an "
            "esc9_ac_charge JSR" % return_pc
        )
        charge_context = ESC9[call_offset - 6:call_offset]
        assert (
            len(charge_context) == 6
            and charge_context[:4] == bytes.fromhex("08c230a9")
            and charge_context[4]
            and charge_context[5] == 0
        ), (
            "bank-$9F VTIME table return $%04X no longer has the required "
            "PHP/REP/LDA immediate charge frame" % return_pc
        )
        player_vtime_call_offsets.append(call_offset)

    def esc9_jml(target):
        return bytes((0x5C, target & 0xFF, target >> 8, 0x9F))

    def player_jml_offsets(encoded):
        offsets = []
        for start, end in player_vtime_ranges:
            first = start - esc9_ac_charge
            last = end - esc9_ac_charge
            offsets.extend(
                offset
                for offset in range(first, last - len(encoded) + 1)
                if ESC9[offset:offset + len(encoded)] == encoded
            )
        return offsets

    player_ojmp_offsets = player_jml_offsets(bytes.fromhex("5cb3d100"))
    player_ibridge_offsets = player_jml_offsets(bytes.fromhex("5c28f892"))
    player_ors_offsets = player_jml_offsets(bytes.fromhex("5c6fd100"))
    assert len(player_ojmp_offsets) == 8, (
        "admitted player bodies lost or gained a logical-JSR OJMP handoff"
    )
    assert len(player_ibridge_offsets) == 1, (
        "admitted player bodies lost their indirect-JSR bridge handoff"
    )
    assert len(player_ors_offsets) == 6, (
        "admitted player bodies lost or gained a final RTS/ORS handoff"
    )

    esc9_packed = bytearray(ESC9)
    if vtime_enabled:
        for call_offset in player_vtime_call_offsets:
            esc9_packed[call_offset + 1:call_offset + 3] = bytes(
                (esc9_vtime_charge_gateway & 0xFF,
                 esc9_vtime_charge_gateway >> 8)
            )
        for offset in player_ojmp_offsets:
            esc9_packed[offset:offset + 4] = esc9_jml(
                esc9_vtime_ojmp_gateway
            )
        for offset in player_ibridge_offsets:
            esc9_packed[offset:offset + 4] = esc9_jml(
                esc9_vtime_ibridge_gateway
            )
        for offset in player_ors_offsets:
            esc9_packed[offset:offset + 4] = esc9_jml(
                esc9_vtime_ors_gateway
            )
        assert (
            esc9_packed.count(
                bytes((0x20, esc9_vtime_charge_gateway & 0xFF,
                       esc9_vtime_charge_gateway >> 8))
            ) == 83
        ), "VTIME player block-charge substitutions are incomplete"
    print(
        "VTIME Stage-3 player ledger: %s"
        % ("enabled diagnostic (83 blocks, 15 handoffs)" if vtime_enabled else "disabled")
    )

    esc9_file_start = 0x2F8000 + (esc9_ac_charge - 0x8000)
    esc9_payload = esc9_packed
    prepared_end = c0bc_prepared_offset + len(C0BC_PREPARED_BLOB)
    assert prepared_end <= esc9_file_start, (
        "bank-$9F selector overlaps the derived renderer payload"
    )
    assert ROM[prepared_end:esc9_file_start] == bytes(
        esc9_file_start - prepared_end
    ), "nonzero data occupies the renderer-payload/selector seam"
    assert ROM[
        esc9_file_start:esc9_file_start + len(esc9_payload)
    ] == bytes(len(esc9_payload)), (
        "bank-$9F selector would overwrite existing ROM data"
    )
    ROM[
        esc9_file_start:esc9_file_start + len(esc9_payload)
    ] = esc9_payload

# --- SA-1 LoROM mirror of the interpreter ---
# Under the SA-1 cart map, the 5A22 (and the SA-1) see $00-$1F:8000-FFFF as LoROM-style
# (32KB/bank): $00:8000-FFFF -> FILE $0-$7FFF, so $00:FFFC (reset) -> FILE $7FFC and the
# interp's DBR=$00 abs reads of its own ROM data (e.g. RESP1, the C-Chip response) -> FILE
# $0-$7FFF. Plain HiROM mirrored ROM file $8000-FFFF into $00:8000 there; the SA-1 map does
# not. Restore that by mirroring the 32KB interp into FILE $0-$7FFF, so $00:8000 presents a
# full copy of the interpreter + data tables + vectors exactly as the interp was designed
# for (DBR=$00). The 5A22 boots into it at $00:8000 with NO interp.pasm changes; the interp
# also stays reachable at $C0:8000 (HiROM-linear) for when it moves to the SA-1 (Phase A2).
ROM[0x0000:0x8000] = INTERP                          # interp mirror @ $00-$1F:8000 (LoROM)

# The LoROM mirror did not exist when the VTIME input seam above patched the
# linear bank-$00 copy. Apply the same exact-byte guards and diagnostic patch
# now that the mirror has been materialized.
joy_read_mirror = joy_read - 0x8000
actual = bytes(ROM[
    joy_read_mirror:joy_read_mirror + len(joy_read_original)
])
assert actual == joy_read_original, (
    "bank-$00 joy_read mirror moved at file $%06X: expected %s, got %s"
    % (joy_read_mirror, joy_read_original.hex(), actual.hex())
)
input_p1_mirror = input_p1 - 0x8000
actual = bytes(ROM[
    input_p1_mirror:input_p1_mirror + len(input_p1_original)
])
assert actual == input_p1_original, (
    "bank-$00 input_p1 mirror moved at file $%06X: expected %s, got %s"
    % (input_p1_mirror, input_p1_original.hex(), actual.hex())
)
if vtime_enabled:
    ROM[input_p1_mirror:input_p1_mirror + len(input_p1_vtime)] = input_p1_vtime

# A VTIME IRQ owns two costs that the ordinary fetch choke cannot represent:
# any instruction staged while a pending level-6 request was mask-blocked,
# followed by the CPU-000's 66-cycle exception-entry edge.  Patch only the
# opt-in diagnostic into the nine-byte NOP island in `take_irq`; production
# retains those exact source bytes and therefore its existing ROM behavior.
take_irq_vtime_entry_seam = interp_symbol("take_irq_vtime_entry_seam")
take_irq_vtime_entry_seam_end = interp_symbol("take_irq_vtime_entry_seam_end")
vtime_irq_entry_call = bytes((
    0x22,
    vtime_off("vtime_irq_enter") & 0xFF,
    vtime_off("vtime_irq_enter") >> 8,
    0xF2,
))
assert (
    take_irq_vtime_entry_seam_end - take_irq_vtime_entry_seam == 9
), "take_irq VTIME entry seam is no longer the pinned nine-byte NOP island"
for take_irq_vtime_offset in (
    take_irq_vtime_entry_seam - 0x8000,
    take_irq_vtime_entry_seam,
):
    assert ROM[
        take_irq_vtime_offset:take_irq_vtime_offset + 9
    ] == bytes.fromhex("ea" * 9), (
        "take_irq VTIME entry seam changed at file $%06X"
        % take_irq_vtime_offset
    )
    if vtime_enabled:
        ROM[
            take_irq_vtime_offset:
            take_irq_vtime_offset + len(vtime_irq_entry_call)
        ] = vtime_irq_entry_call

# The diagnostic root deliberately interprets each child with the global
# native gate temporarily clear.  Patch both bank-$00 ROM views so op_rts can
# recognize the eleven genuine bank-$02 parent returns before consulting that
# gate, then restore the gate and resume the bank-$F3 continuation.  The F3
# front end reproduces the original $00FF and ordinary xlat/miss behavior for
# every other return.  Normal images retain these exact source bytes.
op_rts_sentinel = interp_symbol("op_rts_sentinel")
op_rts_source = bytes.fromhex("a542c9ff")
return_dispatch = vtime_esc5_root_off("vtime_esc5_return_dispatch")
op_rts_vtime = bytes((
    0x5C,
    return_dispatch & 0xFF,
    return_dispatch >> 8,
    0xF3,
))
for op_rts_file in (
    op_rts_sentinel - 0x8000,
    op_rts_sentinel,
):
    assert ROM[op_rts_file:op_rts_file + 4] == op_rts_source, (
        "op_rts_sentinel lost its VTIME-only patchable LDA/CMP seam"
    )
    if vtime_enabled:
        ROM[op_rts_file:op_rts_file + 4] = op_rts_vtime

# A2 boot-flow swap: the 5A22 reset vector ($00:FFFC -> file $7FFC) points at cpu5a22_boot
# ($FC00), NOT the interp reset. The 5A22 bootstraps the SA-1 (CRV=$8000 = interp reset)
# then halts; the SA-1 runs the interpreter. (The mirror set $7FFC = interp reset $8000;
# override it here.)
ROM[0x7FFC] = 0x00; ROM[0x7FFD] = 0xFC               # 5A22 reset vector = $FC00 (cpu5a22_boot)

# HiROM cartridge header at file $FFC0 (= CPU $00:FFC0)
H = 0xFFC0
title = b"SUPERMAN INTERP H>SNES"[:21].ljust(21, b" ")
ROM[H:H+21] = title
# Extended header at $FFB0 (recognized because DeveloperId $FFDA below = $33):
# ExpansionRamSize $FFBD = $06 -> SA-1 BW-RAM = 1024<<6 = 64KB (the shared RAM at
# SNES $40:0000, reachable by both the 5A22 and the SA-1). Without this byte the
# coprocessor RAM is 0 and $40:0000 is unmapped (BaseCartridge.cpp:244).
ROM[0xFFBD] = 0x07      # SA-1 BW-RAM size: 128 KB ($40:0000 work RAM + $41:0000 shadow)
ROM[H+0x15] = 0x31      # map mode: HiROM + FastROM (SA-1 keeps the $C0-$FF linear ROM map)
ROM[H+0x16] = 0x33      # cart type: SA-1 ((RomType&0xF0)>>4==3 -> CoprocessorType::SA1)
ROM[H+0x17] = 0x0C      # ROM size: 4MB (2^12 KB)
ROM[H+0x18] = 0x07      # SRAM size = 128 KB: for SA-1 this IS the BW-RAM (the save RAM,
                        # sized by SramSize $FFD8 -> _saveRamSize; BaseCartridge.cpp:259).
                        # mapSram=false for SA-1 so no conflict; Sa1::Init maps it to
                        # $40-$5F (SA-1) / $40-$4F (5A22). $40:0000=work RAM, $41:0000=shadow.
ROM[H+0x19] = 0x01      # country
ROM[H+0x1A] = 0x33      # licensee
ROM[H+0x1B] = 0x00      # version
# --- bank-$00 org-overlap guards (the loop_hook overgrowth class, 2026-07-10) ---
# Poppy silently lets a later .org assemble OVER earlier flowed code (last org wins
# per byte). That buried the $F600 TESTFLAG, truncated lh_3fea's sec/rts (boot
# RAM-test failure) and buried lh_adbe/gm_memclr under gm_verify (the $080100
# gameplay derail). Guard the two seams: the loop-hook flow chain (.org $F442)
# must leave slack before the $F602 section, and gm_memclr's rehomed body must
# leave slack before the $F6EA section. Slack bytes assemble as zero fill; code
# growing into them fails HERE instead of silently misexecuting.
# (the flow chain legitimately ends at $F5FB after the 2026-07-10 lh_0818 streak
# gate — only 6 slack bytes remain; the NEXT lh growth must relocate to escbank5
# like lh_3fea/lh_adbe/gm_verify did)
for a, b, what in [(0xF5FC, 0xF602, "loop-hook flow chain vs .org $F602"),
                   (0xF6E4, 0xF6EA, "gm_memclr region vs .org $F6EA")]:
    for fo in (a - 0x8000, a):        # file offsets: SA-1 view (addr-$8000), 5A22 view (addr)
        chunk = bytes(ROM[fo:fo + (b - a)])
        assert chunk == bytes(b - a), (
            "bank-$00 org-overlap guard tripped (%s): bytes $%04X-$%04X not zero "
            "(file +0x%X): %s — code grew into the slack; RELOCATE it (see the "
            "loop_hook root-cause notes in interp.pasm/escbank5.pasm)"
            % (what, a, b - 1, fo, chunk.hex()))

# --- TESTFLAG guard (see interp.pasm TESTFLAG declaration) ---
# The production cold-boot path requires $00:F7E0 == 0 in BOTH ROM views (SA-1
# LoROM mirror file $77E0 / 5A22 HiROM file $F7E0). This byte has been silently
# covered by code growth TWICE ($F400, then $F600), each time making cold boot
# unreachable; fail the build loudly instead of shipping a third regression.
assert ROM[0x77E0] == 0 and ROM[0xF7E0] == 0, (
    "TESTFLAG ($00:F7E0) nonzero in a ROM view (sa1 file $77E0=%02X, 5a22 file "
    "$F7E0=%02X): code growth covered it AGAIN — relocate the flag (interp.pasm)"
    % (ROM[0x77E0], ROM[0xF7E0]))

# Per-fetch PC logging is a diagnostic build feature, not production game
# behavior. Ordinary production skips its JSR while PC_RING restores the
# original debug body. The VTIME diagnostic reuses the already-called choke
# trampoline instead: before `$072E` opens it has the same local gated return
# as production; after that established game gate it can call the cycle helper.
# The modes are asserted mutually exclusive above.
pc_ring_enabled = _os.environ.get("PC_RING", "0") == "1"
pc_ring_call = bytes.fromhex("2081e2")       # jsr dbg_fetch ($E281)
vtime_consume_call = bytes.fromhex("220084f2ea")  # source: jsl $F2:8400 / nop
legacy_consume = bytes.fromhex("a5ac3a85ac")      # lda/dec/sta $AC


def production_skip(length):
    """Size-neutral BRA over diagnostic bytes, with unreachable NOP fill."""

    assert 3 <= length <= 0x81
    return bytes((0x80, length - 2)) + bytes.fromhex("ea" * (length - 2))


pc_ring_disabled = production_skip(len(pc_ring_call))

# `interp.pasm` carries the VTIME consumer at the top of iloop only to reserve
# its exact five-byte seam. Every packed image, including VTIME diagnostics,
# restores the proven local `LDA/DEC/STA $AC` there. The VTIME choke gateway
# suppresses that legacy countdown only after it has initialized a virtual
# state; no pre-self-test per-fetch helper is allowed.
dbg_fetch = interp_symbol("dbg_fetch")
op_movem_d16 = interp_symbol("op_movem_d16")
choke_tramp = interp_symbol("choke_tramp")
ct_ret = interp_symbol("ct_ret")
lh_sched_pre = interp_symbol("lh_sched_pre")
choke_original_size = lh_sched_pre - choke_tramp
# The pre-arm test is the absolute loop-hook gate `$072E`.  The earlier
# two-byte `LDA $2E` accidentally read emulated A3.H from the direct-page
# register file; task 13 changes that register after its first fetch and then
# bypasses VTIME prepare for the rest of the pool scan.  The gateway has ample
# audited slack, so use the exact three-byte absolute load and keep the branch
# displacement/remaining control flow unchanged.
choke_gateway = bytes.fromhex(
    "c230ad2e07f00f2280b4f2d005685ca580005c81e20060"
)
assert (
    dbg_fetch == 0xE281
    and choke_tramp == 0xF980
    and ct_ret == 0xF9A7
    and choke_original_size == 42
    and len(choke_gateway) <= choke_original_size
    and dbg_fetch + choke_original_size <= op_movem_d16
), "VTIME choke gateway no longer fits its audited diagnostic seams"
for vtime_consume_offset in (0x00A5, 0x80A5):
    actual = bytes(ROM[vtime_consume_offset:vtime_consume_offset + 5])
    assert actual == vtime_consume_call, (
        "VTIME consume seam moved at file $%06X: expected %s, got %s"
        % (vtime_consume_offset, vtime_consume_call.hex(), actual.hex())
    )
    ROM[vtime_consume_offset:vtime_consume_offset + 5] = legacy_consume

for pc_ring_offset in (0x00EB, 0x80EB):
    actual = bytes(ROM[pc_ring_offset:pc_ring_offset + 3])
    assert actual == pc_ring_call, (
        "ifetch dbg_fetch call moved at file $%06X: expected %s, got %s; "
        "update the size-neutral PC_RING pack patch"
        % (pc_ring_offset, pc_ring_call.hex(), actual.hex())
    )
    if vtime_enabled:
        original = bytes(ROM[pc_ring_offset:pc_ring_offset + 6])
        assert original == bytes.fromhex("2081e2ad2e07"), (
            "VTIME fetch seam moved: expected JSR dbg_fetch / LDA $072E at file $%06X, "
            "got %s" % (pc_ring_offset, original.hex())
        )
        ROM[pc_ring_offset:pc_ring_offset + 3] = pc_ring_disabled
    elif not pc_ring_enabled:
        ROM[pc_ring_offset:pc_ring_offset + 3] = pc_ring_disabled

dbg_fetch_relative = dbg_fetch - 0x8000
dbg_fetch_gateway = bytes.fromhex("5c0180f2ea")
dbg_fetch_original = bytes.fromhex("daa448a540")  # PHX / LDY $48 / LDA $40
for dbg_fetch_offset in (dbg_fetch_relative, dbg_fetch_relative + 0x8000):
    actual = bytes(ROM[dbg_fetch_offset:dbg_fetch_offset + 5])
    assert actual == dbg_fetch_gateway, (
        "dbg_fetch virtual-cycle gateway moved or changed at file $%06X: %s"
        % (dbg_fetch_offset, actual.hex())
    )
    if vtime_enabled:
        # dbg_fetch is skipped in a VTIME image; borrow its unused diagnostic
        # body as the byte-exact legacy choke tail. The VTIME choke returns here
        # after accounting so the original xlat/RTS contract stays intact.
        choke_source_offset = choke_tramp - 0x8000
        choke_original = bytes(
            ROM[choke_source_offset:choke_source_offset + choke_original_size]
        )
        assert choke_original == bytes.fromhex(
            "c230ad3a07f020a542f0034c20d3a540c9e40cf00dc9be13f008"
            "c9fa08f0034ce8d2685c00f99460eaea"
        ), "legacy choke body changed; re-audit the VTIME relocation"
        ROM[dbg_fetch_offset:dbg_fetch_offset + choke_original_size] = choke_original
    elif not vtime_enabled or pc_ring_enabled:
        ROM[dbg_fetch_offset:dbg_fetch_offset + 5] = dbg_fetch_original
print(
    "PC ring: %s"
    % (
        "enabled (diagnostic)"
        if pc_ring_enabled
        else ("choke-gated VTIME gateway" if vtime_enabled else "disabled (production)")
    )
)

if vtime_enabled:
    choke_packed = choke_gateway + bytes(choke_original_size - len(choke_gateway))
    for choke_offset in (choke_tramp - 0x8000, choke_tramp - 0x8000 + 0x8000):
        original = bytes(ROM[choke_offset:choke_offset + choke_original_size])
        assert original == choke_original, (
            "legacy choke copy differs across ROM views at file $%06X" % choke_offset
        )
        ROM[choke_offset:choke_offset + choke_original_size] = choke_packed

# `mvc_check` is an unconditional bank-$00 optimization: repeated identical
# MOVE.L (An)+,(An)+ opcodes are bulk-copied after only the first fetch. That is
# valid for production semantics but bypasses the VTIME per-fetch clock. Route
# only VTIME images through the fixed $F2 gateway; ordinary images retain the
# byte-identical REP/LDA prefix. Bit 1 declines to op_move_g, while bit 0 resumes
# the collapse after re-materializing this prefix in the gateway.
mvc_check = interp_symbol("mvc_check")
op_move_g = interp_symbol("op_move_g")
mvc_prefix = bytes.fromhex("c230a544")       # REP #$30 / LDA $44
mvc_vtime_gateway = bytes.fromhex("5cd1b4f2") # JML $F2:B4D1
assert mvc_check == 0x95EE and op_move_g == 0xFA00, (
    "VTIME mvc gateway fixed bank-$00 continuations moved"
)
for mvc_offset in (mvc_check - 0x8000, mvc_check):
    actual = bytes(ROM[mvc_offset:mvc_offset + len(mvc_prefix)])
    assert actual == mvc_prefix, (
        "mvc_check prefix changed at file $%06X: expected %s, got %s"
        % (mvc_offset, mvc_prefix.hex(), actual.hex())
    )
    if vtime_enabled:
        ROM[mvc_offset:mvc_offset + len(mvc_prefix)] = mvc_vtime_gateway

# The scheduler fire counters are validation telemetry, not emulated game
# state.  Keep them in PC_RING diagnostic ROMs for the existing scheduler
# harnesses, but remove their shared-BW-RAM traffic from production with a
# size-neutral pack patch.  Symbol-derived bounds and exact-byte assertions
# make this fail loud if either tightly pinned body moves.
if _osp.exists("src/escbank.bin"):
    scheduler_counters = [
        (
            "switch-in",
            esc_off("swin_diag_counter_begin"),
            esc_off("swin_diag_counter_end"),
            bytes.fromhex("afe27f401a8fe27f40"),
        ),
        (
            "select",
            esc_off("sels_diag_counter_begin"),
            esc_off("sels_diag_counter_end"),
            bytes.fromhex("afea7f401a8fea7f40"),
        ),
    ]
    for counter_name, counter_begin, counter_end, counter_bytes in scheduler_counters:
        assert counter_end - counter_begin == len(counter_bytes) == 9, (
            "scheduler %s counter is no longer the audited nine-byte sequence" % counter_name
        )
        counter_file_offset = 0x290000 + counter_begin - 0x8000
        actual = bytes(ROM[counter_file_offset:counter_file_offset + len(counter_bytes)])
        assert actual == counter_bytes, (
            "scheduler %s counter bytes moved or changed: expected %s, got %s"
            % (counter_name, counter_bytes.hex(), actual.hex())
        )
        if not pc_ring_enabled:
            ROM[counter_file_offset:counter_file_offset + len(counter_bytes)] = production_skip(
                len(counter_bytes)
            )
print(
    "Scheduler counters: %s"
    % ("enabled (diagnostic)" if pc_ring_enabled else "disabled (production)")
)

# Native-escape hit counters and dispatch counters are validation telemetry,
# never emulated 68000 state.  Keep one source/diagnostic ROM with every counter
# intact, but skip the complete read-modify-write sequences in production.  The
# exact-byte checks distinguish these audited counters from the real $0760 game-
# tick counter at $00:F5A3, which must remain enabled for end-to-end evidence.
def symbol_address(symbol_path, symbol):
    for line in Path(symbol_path).read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError("missing %s in %s" % (symbol, symbol_path))


def patch_validation_counter(name, file_offsets, expected):
    replacement = production_skip(len(expected))
    for file_offset in file_offsets:
        actual = bytes(ROM[file_offset:file_offset + len(expected)])
        assert actual == expected, (
            "%s validation counter moved or changed at file $%06X: expected %s, got %s"
            % (name, file_offset, expected.hex(), actual.hex())
        )
        if not pc_ring_enabled:
            ROM[file_offset:file_offset + len(expected)] = replacement


interp_counter_specs = [
    ("entry412", "entry412", bytes.fromhex("ee1c07")),
    ("cb9e", "entry_cb9e", bytes.fromhex("ee1e07")),
    ("15b4", "entry_15b4_gap", bytes.fromhex("ee2007")),
    ("3e6a", "entry_3e6a_gap", bytes.fromhex("ee2207")),
    ("111a", "entry_111a", bytes.fromhex("ee2607")),
    ("20e8", "entry_20e8", bytes.fromhex("ee2c07")),
]
for counter_name, counter_symbol, counter_bytes in interp_counter_specs:
    counter_address = symbol_address("src/interp.sym", counter_symbol) + 2
    counter_relative = counter_address - 0x8000
    patch_validation_counter(
        counter_name,
        (counter_relative, counter_relative + 0x8000),
        counter_bytes,
    )

fixed_counter_specs = [
    (
        "13be-table",
        0x2A0000,
        "src/escbank2.sym",
        "entry_13bet",
        2,
        bytes.fromhex("ad30071a8d3007"),
    ),
    (
        "ce4-semantic",
        0x2A0000,
        "src/escbank2.sym",
        "hce4_counter",
        0,
        bytes.fromhex("ad24071a8d2407"),
    ),
    (
        "25110",
        0x2B8000,
        "src/escbank3.sym",
        "entry_25110",
        2,
        bytes.fromhex("ad2a071a8d2a07"),
    ),
    (
        "111a-table",
        0x2A8000,
        "src/escbank6.sym",
        "entry_111at",
        2,
        bytes.fromhex("ee2607"),
    ),
]
for (
    counter_name,
    bank_file_base,
    symbol_path,
    counter_symbol,
    symbol_delta,
    counter_bytes,
) in fixed_counter_specs:
    counter_address = symbol_address(symbol_path, counter_symbol) + symbol_delta
    patch_validation_counter(
        counter_name,
        (bank_file_base + counter_address - 0x8000,),
        counter_bytes,
    )


def patch_counter_pattern(name, bank_file_base, start, end, pattern, expected_count):
    region_start = bank_file_base + start - 0x8000
    region = bytes(ROM[region_start:region_start + end - start])
    positions = []
    cursor = 0
    while True:
        cursor = region.find(pattern, cursor)
        if cursor < 0:
            break
        positions.append(region_start + cursor)
        cursor += len(pattern)
    assert len(positions) == expected_count, (
        "%s validation-counter scan found %d, expected %d"
        % (name, len(positions), expected_count)
    )
    for index, file_offset in enumerate(positions):
        patch_validation_counter("%s-%d" % (name, index), (file_offset,), pattern)


patch_counter_pattern(
    "jah2-dispatch", 0x290000, 0xF000, 0xF600, bytes.fromhex("ee6407"), 23
)
patch_counter_pattern(
    "jah2-b0-dispatch", 0x2E8000, 0xFB00, 0xFC00, bytes.fromhex("ee6407"), 8
)
patch_counter_pattern(
    "coroutine-dispatch", 0x290000, 0xF800, 0xF803, bytes.fromhex("ee6607"), 1
)
patch_counter_pattern(
    "fast-rte-dispatch", 0x2E8000, 0x8400, 0x8650, bytes.fromhex("ee6607"), 4
)
print(
    "Validation counters: %s"
    % ("enabled (diagnostic)" if pc_ring_enabled else "disabled (production)")
)
print(
    "Mode 7 boot asset: %s (%d visible OBJ sprites)"
    % (
        BOOT_ASSET_REPORT["sha256"],
        BOOT_ASSET_REPORT["visible_obj_sprites"],
    )
)

# checksum (zero the fields, sum, write complement+checksum)
for i in range(H+0x1C, H+0x20):
    ROM[i] = 0x00
total = sum(ROM) & 0xFFFF
comp = (~total) & 0xFFFF
ROM[H+0x1C] = comp & 0xFF
ROM[H+0x1D] = (comp >> 8) & 0xFF
ROM[H+0x1E] = total & 0xFF
ROM[H+0x1F] = (total >> 8) & 0xFF

out = Path("build/interp.sfc")
out.parent.mkdir(exist_ok=True)
out.write_bytes(ROM)
print(f"wrote {out} ({len(ROM)} bytes, HiROM)")
print(f"reset vector @file $FFFC: ${ROM[0xFFFC]|(ROM[0xFFFD]<<8):04X}")
print(f"68K image @ $C1:0000 (file $10000); 68K reset bytes @ image $3EF0: "
      f"{IMG[0x3EF0:0x3EF6].hex()}")
