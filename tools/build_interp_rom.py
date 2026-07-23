#!/usr/bin/env python3
"""
Build the full-ROM 68K-interpreter harness: a 1MB HiROM .sfc embedding the
65816 interpreter (file $8000, CPU $00/$C0:8000-FFFF) + the entire 512KB 68K
program image (file $10000, CPU $C1:0000+ — so 68K addr A reads flat at $C10000+A).
Load this in Mesen (MESEN_ROM) to let the interpreter follow cross-ROM control flow.
"""
import hashlib
from pathlib import Path

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
SNES_GFX = build_snes_tile_blob(GFX)

# 4MB HiROM: interp @ $C0:8000, 68K image @ $C1:0000 (file $10000), and the
# private arcade tile ROM pre-permuted into native SNES 4bpp records @ $C9:0000
# (file $90000). Runtime keeps the same flat $C90000 + code*128 lookup while
# avoiding an expensive per-tile software decode.
ROM = bytearray(0x400000)                            # 4MB HiROM
ROM[0x8000:0x10000] = INTERP                         # interpreter + vectors @ $00/$C0:8000
ROM[0x10000:0x90000] = IMG                           # 68K image @ $C1:0000 (flat $C10000+A)
ROM[0x90000:0x290000] = SNES_GFX                     # native SNES tiles @ $C9:0000
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
    "202980c230afa2897e1a8fa2897eafa0897e8fa4897e60"
), "true completed-render counter/generation telemetry moved or changed"
# Production pacing is split across fixed WRAM-mirrored islands immediately
# before the TAD code at $9000. Guard both the flowing rc_copy tail and every
# handler seam because Poppy silently accepts overlapping .org sections.
assert VID[0x0A00:0x0DD0] == bytes(0x3D0), (
    "video rc_copy flow grew into the $8A00-$8DCF pacing seam"
)
assert VID[0x099C:0x09AB] == bytes.fromhex(
    "bf0080e99f00807fe8e8e00030d0f1"
), "rc_copy no longer mirrors the full $8000-$AFFF production supervisor"
assert VID[0x0DD0:0x0DE1] == bytes.fromhex(
    "08e220af2c0141c9a5f004284c56882860"
), "ordered-input wrapper moved or changed"
assert VID[0x0DE1:0x0E00] == bytes(0x1F), (
    "ordered-input wrapper grew into pacing_try_wake"
)
pacing_try_wake = vid_off("pacing_try_wake")
pacing_renderer_ownership_guard = vid_off("ptw_renderer_ownership_guard")
pacing_pending_direct_guard = vid_off("ptw_pending_direct_guard")
pacing_snapshot_queued = vid_off("ptw_snapshot_queued")
pacing_snapshot_publish = vid_off("ptw_snapshot_direct")
pacing_helpers_end = vid_off("pacing_helpers_end")
assert pacing_try_wake == 0x8E00
assert (
    pacing_try_wake
    < pacing_renderer_ownership_guard
    < pacing_pending_direct_guard
    < pacing_snapshot_queued
    < pacing_snapshot_publish
    < pacing_helpers_end
    <= 0x8F00
), "pacing direct-publication guard or helper seam moved out of order"
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
assert VID[0x0F00:0x0F34] == bytes.fromhex(
    "08c23048da5a8be220a90048aba9808d"
    "0122af2a01411a8f2a014120008e208a"
    "8ead0233abe220a30829fb8308c2307a"
    "fa682840"
), (
    "pacing NMI handler lost its A-preserving stacked-P patch/restore order"
)
assert VID[0x0F34:0x0F40] == bytes(0x0C), (
    "pacing NMI handler grew into the fixed coprocessor-IRQ handler"
)
assert VID[0x0F68:0x1000] == bytes(0x98), (
    "pacing IRQ handler grew into the TAD $9000 island"
)
# Keep each renderer island inside its declared execution domain.  Symbol bounds
# plus explicit zero seams catch Poppy's permissive .org overlap without freezing
# implementation bytes that these optimizations intentionally change.
palette_test = vid_off("pacing_palette_cache_test")
palette_test_end = vid_off("pacing_palette_cache_test_end")
bg_test = vid_off("pacing_bg_cache_test")
bg_test_end = vid_off("pacing_bg_cache_test_end")
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
queue_capture = vid_off("render_queue_capture")
queue_capture_end = vid_off("render_queue_capture_end")
queue_capture_secondary = vid_off("render_queue_capture_secondary")
queue_capture_secondary_end = vid_off("render_queue_capture_secondary_end")
queue_promote = vid_off("render_queue_promote")
queue_promote_end = vid_off("render_queue_promote_end")
video_image_end = vid_off("video_image_end")
assert palette_test == 0xA1A0 and palette_test < palette_test_end <= bg_test == 0xA1E8
assert VID[palette_test_end - 0x8000:bg_test - 0x8000] == bytes(
    bg_test - palette_test_end
), "palette manifest consumer overlapped the fixed BG consumer"
assert bg_test < bg_test_end <= bg_capacity_exact == 0xA220
assert VID[bg_test_end - 0x8000:bg_capacity_exact - 0x8000] == bytes(
    bg_capacity_exact - bg_test_end
), "BG manifest consumer overlapped the exact-capacity helper"
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
assert render_queue_helpers_end <= snapshot_acquire_paced == 0xA100
assert VID[
    render_queue_helpers_end - 0x8000:0xA100 - 0x8000
] == bytes(0xA100 - render_queue_helpers_end), (
    "lazy queue installer crossed paced snapshot acquisition"
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
assert bytes.fromhex("e02a02") in VID[
    render_queue_install - 0x8000:render_queue_helpers_end - 0x8000
], "lazy queue installer lost its pinned 554-byte copy bound"
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
assert obj_cache_reclaim_fast == 0xAEE2
assert obj_cache_reclaim_fast < obj_cache_reclaim_fast_end <= vid_obj_packed == 0xAF64
assert VID[
    obj_cache_reclaim_fast_end - 0x8000:vid_obj_packed - 0x8000
] == bytes(vid_obj_packed - obj_cache_reclaim_fast_end), (
    "OBJ reclaimer crossed the packed-renderer seam"
)
assert VID[0xAF5E - 0x8000:0xAF64 - 0x8000] == bytes.fromhex(
    "a9800085de60"
), "OBJ reclaimer lost its $0080 high-water publication or RTS tail"
assert vid_obj_packed < vid_obj_packed_end <= 0xB000
assert obj_oam_fast == 0xA4D5 and obj_oam_fast < obj_oam_fast_end <= 0xA570
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
assert queue_capture_secondary < queue_capture_secondary_end <= queue_promote
assert VID[
    queue_capture_secondary - 0x8000:queue_capture_secondary - 0x8000 + 9
] == bytes.fromhex("08c230a5d048a5d448"), (
    "secondary queue capture no longer preserves interrupted $D0/$D4 scratch"
)
assert VID[
    queue_capture_secondary_end - 0x8000:queue_promote - 0x8000
] == bytes(queue_promote - queue_capture_secondary_end), (
    "ROM-only secondary capture crossed the private-WRAM queue-promoter island"
)
assert queue_promote == 0xED00 and queue_promote < queue_promote_end <= 0xF000
assert queue_promote_end - queue_promote == 0x022A, (
    "pinned lazy-installer size no longer matches the queue promoter"
)
assert video_image_end == queue_promote_end
assert len(VID) == video_image_end - 0x8000, (
    "unexpected video bytes follow the private-WRAM queue promoter"
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

    ibridge = esc_off("ibridge")
    ib_n4 = esc_off("ib_n4")
    ibridge_end = esc_off("ibridge_end")
    assert ibridge == 0xF828 and ibridge_end <= 0xF900, (
        "bank-$92 indirect bridge moved or crossed the fixed $F900 dispatcher"
    )
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
    c172_optional = esc2_off("hc172_optional_hot")
    c172_optional_end = esc2_off("hc172_optional_hot_end")
    assert c172_flow_end <= 0xD800, (
        "escbank2 flowing bodies crossed the fixed $D800 C172 helper island"
    )
    assert c172_optional == 0xD800 and c172_optional_end <= 0xE000, (
        "$C172 optional-callback helper crossed its fixed $94:D800-$DFFF island"
    )
    assert ESC2[c172_flow_end - 0x8000:0x5800] == bytes(
        0xD800 - c172_flow_end
    ), "escbank2 flowing-body -> $D800 seam was overwritten"
    h8_mark_palette_dirty = esc2_off("h8_mark_palette_dirty")
    h8_mark_palette_dirty_end = esc2_off("h8_mark_palette_dirty_end")
    assert h8_mark_palette_dirty == 0xDB00 and h8_mark_palette_dirty_end <= 0xDB20, (
        "$8C2 renderer-palette dirty helper moved outside its fixed $94:DB00 island"
    )
    assert ESC2[c172_optional_end - 0x8000:0x5B00] == bytes(
        0xDB00 - c172_optional_end
    ), "$C172 helper grew into the fixed $94:DB00 palette-dirty island"
    assert ESC2[h8_mark_palette_dirty_end - 0x8000:0x6000] == bytes(
        0xE000 - h8_mark_palette_dirty_end
    ), "$8C2 palette helper grew into the fixed $94:E000 HLE island"
    assert ESC2[c172_optional - 0x8000:c172_optional_end - 0x8000].count(
        bytes.fromhex("5c00fc9d")
    ) == 1, "$C172 optional helper lost its sole direct $9D:FC00 callback link"
    assert (
        esc2_off("xlat_dispatch") == 0xF900
        and esc2_off("xd_table") == 0xF931
        and esc2_off("xd_dispatch_end") == 0xF97E
        and esc2_off("xlat_choke") == 0xF980
    ), "xlat direct/generic dispatcher crossed its fixed $94:F900-$F97F island"
    assert ESC2[0x7900:0x7931] == bytes.fromhex(
        "c230a542c90200f024c90000d023a540eb29ff00c976009018c97800900f"
        "c9c000"
        "f00ac9d7009009c9dd00b0045c00da9d"
    ), "gameplay-entry/combat/task sparse direct xlat arms changed bytes"
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
    entry_c8e0 = esc6_off("entry_c8e0t")
    entry_c8e0_resume = esc6_off("entry_c8e0_generated_resume")
    hle_17b4 = esc6_off("hle_17b4")
    hle_17b4_end = esc6_off("hle_17b4_end")
    hle_8fa = esc6_off("hle_8fa")
    hle_8fa_end = esc6_off("hle_8fa_end")
    h8fa_validation_spin = esc6_off("h8fa_validation_spin")
    h8fa_validation_spin_end = esc6_off("h8fa_validation_spin_end")
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
    hc262_generated_finish = esc6_off("hc262_generated_finish")
    hc262_generated_finish_end = esc6_off("hc262_generated_finish_end")
    entry_2a1b2 = esc6_off("entry_2a1b2")
    entry_2a190 = esc6_off("entry_2a190")
    entry_2a1d8t = esc6_off("entry_2a1d8t")
    entry_2a53a = esc6_off("entry_2a53a")
    entry_29128 = esc6_off("entry_29128")
    entry_29144 = esc6_off("entry_29144")
    entry_2a61e = esc6_off("entry_2a61e")
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
    assert generated_end <= 0x9B00 and hle_17b4 == 0x9B00, (
        "escbank6 generated bodies crossed the pinned $95:9B00 hle_17b4 slot"
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
    assert hle_8fa < hle_8fa_end <= 0x9FA0, (
        "hle_8fa crossed the fixed $95:9FA0 validation seam"
    )
    assert h8fa_validation_spin == 0x9FA0 and h8fa_validation_spin_end == 0x9FA2, (
        "hle_8fa validation spin moved from its fixed two-byte seam"
    )
    assert ESC6[hle_8fa_end - 0x8000:0x1FA0] == bytes(
        0x1FA0 - (hle_8fa_end - 0x8000)
    ), "hle_8fa has nonzero overlap before its validation spin"
    assert ESC6[0x1FA0:0x1FA2] == bytes.fromhex("80fe"), (
        "hle_8fa validation spin is not BRA -2"
    )
    assert hle_96a == 0xA000 and hle_96a < hle_96a_end <= 0xA300, (
        "hle_96a moved from $95:A000 or crossed its reserved $95:A000-$A2FF island"
    )
    assert ESC6[0x1FA2:0x2000] == bytes(0x005E), (
        "bank-$95 validation seam has nonzero overlap before hle_96a"
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
    assert ESC6[entry_111at_end - 0x8000:0x2F00] == bytes(
        0x2F00 - (entry_111at_end - 0x8000)
    ), (
        "rejected $C8E0 island has nonzero data after the $111A table body and "
        "before hc262_generated_finish@$95:AF00"
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
        entry_2a1b2 < entry_2a190 < entry_2a1d8t < entry_2a53a
        < entry_29128 < entry_29144 < entry_2a61e
        < h25110_stage1 == 0xF000 < h25110_xflag_stage1 == 0xF3E0
        < h25110_xflag_stage1_end == late_combat_bodies_end <= 0xF400
    ), "late-combat bodies overlap, reordered, or overflow bank $95"
    esc3_import_symbols = Path("src/escbank3.sym").read_text(
        encoding="utf-8-sig"
    )
    esc3_stage1_done = None
    for line in esc3_import_symbols.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "h25110_stage1_done":
            esc3_stage1_done = int(fields[0].split(":", 1)[1], 16)
            break
    assert esc3_stage1_done is not None, (
        "escbank3 lost the semantic $25110 stage-1 completion seam"
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
    assert ESC6[0x73E0:0x73FA] == bytes.fromhex(
        "c230a91e00851ca5341869743a8520a53669000085225c4f8097"
    ), "$25110 X-aware adapter moved or changed bytes at $95:F3E0"
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
    assert len(ESC6) == h25_predicates_end - 0x8000, (
        "unexpected bank-$95 bytes follow the $25110 predicate tail island"
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
    assert ESC4[0x1200:0x120E] == bytes.fromhex("5c009098" + "ea" * 10), (
        "escbank4 entry_235e0 guarded redirect moved or changed size"
    )
    assert esc4_off("h2429c_empty_helpers") == 0x8E53, (
        "escbank4 fused $02429C empty-helper entry moved from $98:8E53"
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
    assert ESC4[0x0F5E:0x0F80] == bytes(0x22), (
        "escbank4 h23342_empty grew into the $8F5E-$8F7F seam"
    )
    assert ESC4[0x0FD9:0x1000] == bytes(0x27), (
        "escbank4 h23e34_empty grew into the $8FD9-$8FFF seam"
    )
    assert ESC4[0x1061:0x1100] == bytes(0x9F), (
        "escbank4 h235e0_empty grew into the $9061-$90FF seam"
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
    assert h1e7c0_script_seam == 0xB7FD, (
        "$01E7C0 generated script seam moved from $98:B7FD"
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
    h25110_final_tst_done = esc3_off("h25110_final_tst_done")
    entry_12e56 = esc3_off("entry_12e56")
    entry_1f1c0t = esc3_off("entry_1f1c0t")
    entry_1f1c0_generated = esc3_off("entry_1f1c0_generated")
    assert (
        entry_25110 == 0x8000
        < lf25110_1 == 0x803E
        < l25110_25122 == 0x804F
        < h25110_stage1_done
        < h25110_stage2_generated_setup
        < h25110_final_tst_done
        < entry_12e56 == 0xA000
    ), "$25110 adapters or semantic seams moved/reordered in bank $97"
    assert ESC3[0x003E:0x004F] == bytes.fromhex(
        "a5a280045ce0f3955c00f095eaeaeaeaea"
    ), "$25110 X/compact routing seam moved or changed bytes"
    assert entry_1f1c0t == 0xFC60 and entry_1f1c0_generated == 0xFC64, (
        "$01F1C0 fast redirect or generated fallback moved in bank $97"
    )
    assert ESC3[0x7C60:0x7C64] == bytes.fromhex("5c00ab9d"), (
        "$01F1C0 table entry lost its size-neutral JML $9D:AB00 wrapper"
    )
    assert ESC3[
        h25110_stage1_done - 0x8000:h25110_stage1_done - 0x8000 + 5
    ] == bytes.fromhex("5c00809dea"), (
        "$25110 stage-2 guarded redirect moved or is no longer size-neutral"
    )
    assert h25110_stage2_generated_setup == h25110_stage1_done + 5, (
        "$25110 generated stage-2 fallback no longer follows its redirect"
    )
    assert ESC3[
        h25110_stage5_select - 0x8000:h25110_stage5_select - 0x8000 + 4
    ] == bytes.fromhex("5c00829d"), (
        "$025110 stage-5 inactive-list redirect moved or changed size"
    )
    # The generated CAF6 body ends at $DC6D; its guarded production helper is
    # pinned at $DD00 and may use the remaining space before h1e7c0@$E000.
    # Poppy accepts backward/overlapping .org sections, so make both gaps an
    # explicit ROM-pack invariant instead of trusting assembly success.
    assert ESC3[0x5C6D:0x5D00] == bytes(0x93), (
        "escbank3 CAF6 generated body grew into the $DC6D-$DCFF seam before "
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
    assert 0xE000 < h1e7c0_hot_end <= 0xE800, (
        "escbank3 h1e7c0_hot crossed the fixed entry_cb9e@$97:E800 slot"
    )
    assert ESC3[
        h1e7c0_hot_end - 0x8000:0x6800
    ] == bytes(0xE800 - h1e7c0_hot_end), (
        "escbank3 h1e7c0_hot has nonzero overlap before entry_cb9e@$97:E800"
    )
    # entry_1d5f0 ends at file-relative $7911 and the guarded callable CB9E
    # helper is pinned at $7A00 ($97:FA00).  Poppy permits flowing code to
    # overwrite a later .org silently, so keep this seam explicit.
    assert ESC3[0x7911:0x7A00] == bytes(0xEF), (
        "escbank3 entry_1d5f0 grew into the $F911-$F9FF seam before hcb9e_fast; "
        "relocate code instead of allowing .org overlap"
    )
    assert ESC3[0x7C48:0x7C60] == bytes(0x18), (
        "escbank3 hcb9e_fast helpers grew into the $FC48-$FC5F seam before "
        "entry_1f1c0t; relocate code instead of allowing .org overlap"
    )
    ROM[0x2B8000:0x2B8000+len(ESC3)] = ESC3          # @ SA-1 $97:8000 (file $2B8000)

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

    assert esc5_off("entry_24cb6") == esc5_off("L24bc2_24cb6"), (
        "$024CB6 exported continuation no longer aliases the original native loop seam"
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
    assert esc5_off("br23e34_1") == 0x8C04, (
        "$23E34 inner return moved; update the bank-$98 fused-helper constant"
    )
    fused_redirect = esc5_off("Lf2429c_1") - 0x8000
    assert ESC5[fused_redirect:fused_redirect + 14] == bytes.fromhex(
        "5c538e98" + "ea" * 10
    ), "$02429C fused empty-helper redirect moved or changed size"

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
    charge_12b6c = esc5_off("h11752_charge_12b6c")
    charge_12b6c_end = esc5_off("h11752_charge_12b6c_end")
    assert paced_end <= 0xFBE0 and charge_12b6c == 0xFBE0 and charge_12b6c_end <= 0xFC10, (
        "$11752 AC-charge tail moved, or $0818 pacing grew into its $99:FBE0 island"
    )
    assert ESC5[paced_end - 0x8000:charge_12b6c - 0x8000] == bytes(
        charge_12b6c - paced_end
    ), "$0818 pacing has nonzero overlap before the $11752 AC-charge tail"
    assert len(ESC5) == charge_12b6c_end - 0x8000, (
        "escbank5 data unexpectedly follows the guarded $11752 AC-charge tail"
    )
    ROM[0x2C8000:0x2C8000+len(ESC5)] = ESC5          # @ SA-1 $99:8000 (file $2C8000)

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
    assert ESC7[0:4] == bytes.fromhex("c230a254"), (
        "$25110 stage-2 helper prologue changed unexpectedly"
    )
    assert ESC7[0x650:0x7C0] == bytes(0x0170), (
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
    assert entry_2ad4ct_end is not None and entry_2ad4ct_end <= 0x9000, (
        "$02AD4C table body crossed its $9D:8A00-$8FFF island"
    )
    assert ESC7[entry_2ad4ct_end - 0x8000:0x1000] == bytes(
        0x1000 - (entry_2ad4ct_end - 0x8000)
    ), "nonzero escbank7 bytes overlap the $02A86E combat island"
    assert ESC7[0x1000:0x1002] == bytes.fromhex("c230"), (
        "$02A86E table body lost its explicit REP #$30 prologue"
    )
    assert entry_2a86et_end is not None and entry_2a86et_end <= 0xA800, (
        "$02A86E table body crossed the fixed $3C36 island at $9D:A800"
    )
    assert h20e8_fast == 0xA003 and h20e8_fast_end is not None, (
        "$20E8 helper moved from its fixed $9D:A000 island"
    )
    assert ESC7[entry_2a86et_end - 0x8000:0x2000] == bytes(
        0x2000 - (entry_2a86et_end - 0x8000)
    ), "$02A86E body has nonzero overlap before h20e8_fast@$9D:A000"
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
    assert entry_2498c_end <= 0xB800, (
        "$02498C pool scanner crossed the fixed $0249C2 island"
    )
    assert ESC7[entry_2498c_end - 0x8000:0x3800] == bytes(
        0x3800 - (entry_2498c_end - 0x8000)
    ), "nonzero escbank7 bytes overlap entry_249c2@$9D:B800"
    assert entry_249c2 == 0xB800 and entry_249c2_end is not None, (
        "$0249C2 pool scanner moved from its fixed $9D:B800 island"
    )
    assert entry_249c2_end <= 0xC000, (
        "$0249C2 pool scanner crossed the fixed $01F2E4 island"
    )
    assert ESC7[entry_249c2_end - 0x8000:0x4000] == bytes(
        0x4000 - (entry_249c2_end - 0x8000)
    ), "nonzero escbank7 bytes overlap entry_1f2e4@$9D:C000"
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
    hcd1a_fb8 = esc7_off("hcd1a_fb8")
    hcd1a_fb8_end = esc7_off("hcd1a_fb8_end")
    hce4_shape_try_ext = esc7_off("hce4_shape_try_ext")
    hce4_shape_try_ext_end = esc7_off("hce4_shape_try_ext_end")
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
    esc7_end = esc7_off("escbank7_end")
    assert xdd == 0xDA00 and xdd < xdd_end <= 0xDB00, (
        "sparse $D7-$DC direct dispatcher moved or overflowed its $9D:DA00 island"
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
    assert xdd_bytes.count(bytes.fromhex("5c00d89e")) == 1, (
        "sparse dispatcher lost its sole $9E:D800 entry_d7be target"
    )
    # Same-bank targets must be absolute JMPs: a local JML would encode bank
    # $00 from Poppy's logical .org and escape the physical bank-$9D mapping.
    for stub, target in (
        ("xdd_2a86e", "entry_2a86et"),
        ("xdd_2ad4c", "entry_2ad4ct"),
        ("xdd_24aa8", "entry_24aa8t"),
        ("xdd_28f92", "entry_28f92t"),
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
        assert ESC7[stub_off - 0x8000:stub_off - 0x8000 + 3] == bytes(
            (0x4C, target_off & 0xFF, target_off >> 8)
        ), f"{stub} is no longer a bank-preserving JMP to {target}"
    assert hcd1a_fb8 == 0xE000 and xdd_end <= 0xE000, (
        "$CD1A/$0FB8 guarded fusion moved from its pinned $9D:E000 island"
    )
    assert ESC7[xdd_end - 0x8000:0x6000] == bytes(
        0x6000 - (xdd_end - 0x8000)
    ), "nonzero escbank7 bytes overlap the $CD1A/$0FB8 fusion island"
    assert 0xE000 < hcd1a_fb8_end <= 0xE400, (
        "$CD1A/$0FB8 guarded fusion overflowed its reserved island"
    )
    assert ESC7[hcd1a_fb8_end - 0x8000:0x6400] == bytes(
        0x6400 - (hcd1a_fb8_end - 0x8000)
    ), "nonzero bank-$9D bytes overlap the fixed $CE4 extension island"
    assert hce4_shape_try_ext == 0xE400, (
        "$CE4 extension moved from its fixed $9D:E400 entry"
    )
    assert ESC7[0x6400:0x6404] == bytes.fromhex("c230a582"), (
        "$CE4 extension lost its explicit REP/LDA mapped-source prologue"
    )
    assert 0xE400 < hce4_shape_try_ext_end <= 0xE800, (
        "$CE4 extension overflowed its reserved $9D:E400-$E7FF island"
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
    assert entry_29b6_fast == 0xFC00 and entry_29b6_fast_end <= 0x10000, (
        "$29B6 fast wrapper moved or overflowed bank $9D"
    )
    assert ESC7[entry_c0bc - 0x8000:entry_c0bc_end - 0x8000].count(
        bytes.fromhex("5c00fc9d")
    ) == 1, "$C0BC no longer direct-links its organic $29B6 callback to $9D:FC00"
    assert esc7_end == entry_29b6_fast_end and len(ESC7) == esc7_end - 0x8000, (
        "unexpected bank-$9D bytes follow the $29B6 fast wrapper"
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
    rmb_bg_clean_jump_8 = esc8_off("rmb_bg_clean_jump")
    rmb_bg_reconcile_8 = esc8_off("rmb_bg_reconcile")
    rmb_bg_reconcile_end_8 = esc8_off("rmb_bg_reconcile_done")
    rmb_bg_promote_8 = esc8_off("rmb_bg_promote")
    rmb_bg_revert_8 = esc8_off("rmb_bg_revert")
    rmb_obj_done_8 = esc8_off("rmb_obj_done")
    rmb_obj_pack_8 = esc8_off("rmb_obj_pack")
    rmb_obj_pack_8_end = esc8_off("rmb_obj_pack_end")
    rmb_obj_fast_scan_8 = esc8_off("rmb_obj_fast_scan")
    rmb_obj_fast_loop_8 = esc8_off("rmb_obj_fast_loop")
    rmb_obj_fast_done_8 = esc8_off("rmb_obj_fast_done")
    rmb_obj_fast_scan_8_end = esc8_off("rmb_obj_fast_scan_end")
    shadow_dirty_publish_8 = esc8_off("shadow_dirty_publish")
    shadow_dirty_publish_8_end = esc8_off("shadow_dirty_publish_end")
    mark_bg_dirty_8 = esc8_off("mark_bg_dirty")
    mark_bg_dirty_8_end = esc8_off("mark_bg_dirty_end")
    rmb_prepare_bg_8 = esc8_off("rmb_prepare_bg")
    rmb_prepare_bg_8_end = esc8_off("rmb_prepare_bg_end")
    rpb_prepare_dispatch_8 = esc8_off("rpb_prepare_dispatch")
    rpb_c0bc_prepared_8 = esc8_off("rpb_c0bc_prepared")
    rpb_prepare_dispatch_8_end = esc8_off("rpb_prepare_dispatch_end")
    h8_zero_mask_gate_8 = esc8_off("h8_zero_mask_gate")
    h8_zero_mask_gate_8_end = esc8_off("h8_zero_mask_gate_end")
    rmb_obj_prefilter_8 = esc8_off("rmb_obj_prefilter")
    rmb_obj_prefilter_8_end = esc8_off("rmb_obj_prefilter_end")
    render_bg_dirty_sparse_8 = esc8_off("render_bg_dirty_sparse")
    render_bg_dirty_sparse_8_end = esc8_off("render_bg_dirty_sparse_end")
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
    assert shadow_dirty_publish_8 < shadow_dirty_publish_8_end <= 0xDE80
    assert mark_bg_dirty_8 == 0xDE80
    assert ESC8[
        shadow_dirty_publish_8_end - 0x8000:mark_bg_dirty_8 - 0x8000
    ] == bytes(mark_bg_dirty_8 - shadow_dirty_publish_8_end), (
        "map_snes dirty publisher overlapped the fixed native-write marker"
    )
    assert mark_bg_dirty_8 < mark_bg_dirty_8_end <= rmb_prepare_bg_8
    assert rmb_prepare_bg_8 == 0xDF00
    assert ESC8[
        mark_bg_dirty_8_end - 0x8000:rmb_prepare_bg_8 - 0x8000
    ] == bytes(rmb_prepare_bg_8 - mark_bg_dirty_8_end), (
        "native BG dirty marker overlapped the prepared-map island"
    )
    assert rmb_prepare_bg_8 < rmb_prepare_bg_8_end <= rpb_prepare_dispatch_8, (
        "prepared-map helper overflowed its bank-$9E tail"
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
    assert h8_zero_mask_gate_8 < h8_zero_mask_gate_8_end <= rmb_obj_prefilter_8
    assert rmb_obj_prefilter_8 == 0xE200
    assert rmb_obj_prefilter_8 < rmb_obj_prefilter_8_end <= render_bg_dirty_sparse_8
    assert render_bg_dirty_sparse_8 == 0xE280
    assert render_bg_dirty_sparse_8 < render_bg_dirty_sparse_8_end <= h158_ylist_stage_8
    assert ESC8[
        rmb_obj_prefilter_8_end - 0x8000:render_bg_dirty_sparse_8 - 0x8000
    ] == bytes(render_bg_dirty_sparse_8 - rmb_obj_prefilter_8_end), (
        "OBJ prefilter overlapped the exact BG producer-list helper"
    )
    assert ESC8[
        render_bg_dirty_sparse_8_end - 0x8000:h158_ylist_stage_8 - 0x8000
    ] == bytes(h158_ylist_stage_8 - render_bg_dirty_sparse_8_end), (
        "exact BG producer-list helper overlapped the staged OBJ initializer"
    )
    assert h158_ylist_stage_8 == 0xE400
    assert h158_ylist_stage_8 < h158_ylist_stage_8_end <= rmb_obj_pack_8
    assert rmb_obj_pack_8 == 0xE540
    assert rmb_obj_pack_8 < rmb_obj_pack_8_end <= rmb_obj_fast_scan_8
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
        (h8_zero_mask_gate_8_end, rmb_obj_prefilter_8, "palette-mask -> OBJ prefilter"),
        (rmb_obj_prefilter_8_end, render_bg_dirty_sparse_8, "OBJ prefilter -> exact BG list"),
        (render_bg_dirty_sparse_8_end, h158_ylist_stage_8, "exact BG list -> Y-list stage"),
        (h158_ylist_stage_8_end, rmb_obj_pack_8, "Y-list stage -> packed OBJ helper"),
        (rmb_obj_pack_8_end, rmb_obj_fast_scan_8, "packed OBJ helper -> six-byte scan"),
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
    assert hc0bc_hle_after_29b6_8 < hc0bc_hle_done_8 < hc0bc_hle_after_end_8 <= 0xEF00, (
        "$C0BC post-callback path crossed its fixed $9E:EF00 DMA helper"
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
# behavior.  Keeping the JSR in interp.bin preserves one exact source-level
# enable path, while the ROM pack replaces it size-neutrally in both bank-$00
# mirrors by default.  tools/profile_tick_ring.py requires PC_RING=1 and fails
# loud on a production ROM so cycle attribution can never silently read an
# inert ring.
pc_ring_enabled = _os.environ.get("PC_RING", "0") == "1"
pc_ring_call = bytes.fromhex("2081e2")       # jsr dbg_fetch ($E281)


def production_skip(length):
    """Size-neutral BRA over diagnostic bytes, with unreachable NOP fill."""

    assert 3 <= length <= 0x81
    return bytes((0x80, length - 2)) + bytes.fromhex("ea" * (length - 2))


pc_ring_disabled = production_skip(len(pc_ring_call))
for pc_ring_offset in (0x00EB, 0x80EB):
    actual = bytes(ROM[pc_ring_offset:pc_ring_offset + 3])
    assert actual == pc_ring_call, (
        "ifetch dbg_fetch call moved at file $%06X: expected %s, got %s; "
        "update the size-neutral PC_RING pack patch"
        % (pc_ring_offset, pc_ring_call.hex(), actual.hex())
    )
    if not pc_ring_enabled:
        ROM[pc_ring_offset:pc_ring_offset + 3] = pc_ring_disabled
print("PC ring: %s" % ("enabled (diagnostic)" if pc_ring_enabled else "disabled (production)"))

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
    ("ce4", "entry_ce4", bytes.fromhex("ee2407")),
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
        "hce4_guards_done",
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
    "jah2-dispatch", 0x290000, 0xF000, 0xF600, bytes.fromhex("ee6407"), 22
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
