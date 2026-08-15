"""Static/unit guards for the two narrow renderer repairs.

This intentionally does not assemble, launch an emulator, or touch ROM outputs.
"""

from pathlib import Path

from validate_packed_obj_snapshot import derive_bg_column_capture


ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "src/video.pasm").read_text(encoding="utf-8")


def bg_code(columns: tuple[int, ...]) -> bytes:
    result = bytearray(0x400)
    for column in columns:
        for offset in range(column * 0x40, (column + 1) * 0x40, 2):
            result[offset : offset + 2] = b"\x00\x01"
    return bytes(result)


def controls(start: int = 0x0F) -> bytearray:
    raw = bytearray(0x208)
    raw[0x201] = 0
    raw[0x203] = 1
    for column in range(16):
        raw[9 + column * 0x20] = (start + column * 0x20) & 0xFF
    return raw


def majority_column_rotation(
    raw: bytes, applied: bytes, occupied: tuple[bool, ...]
) -> int | None:
    """Reference model for the fail-closed runtime rotation selector."""
    deltas = [
        (source - target) & 0x0F
        for source, target, live in zip(raw, applied, occupied)
        if live
    ]
    if len(deltas) < 2:
        return None
    candidate = 0
    votes = 0
    for delta in deltas:
        if votes == 0:
            candidate = delta
            votes = 1
        elif delta == candidate:
            votes += 1
        else:
            votes -= 1
    support = sum(delta == candidate for delta in deltas)
    return candidate if support * 2 > len(deltas) else None


def expected_column_offsets(source_column: int, physical_slot: int) -> list[int]:
    """Reference BG_OFFSET_TABLE words for one 32-cell source column."""
    result = []
    for row in range(32):
        horizontal = physical_slot * 8 + (row & 1) * 4
        vertical = (row >> 1) * 0x80
        quadrant = (horizontal // 0x40) * 0x800
        result.append(quadrant + vertical + (horizontal & 0x3F))
    assert len(result) == 32 and source_column in range(16)
    return result


def main() -> int:
    # Acquisition/producer must not retire boot ownership; completed PPU flush
    # is the sole clear site and is downstream of ppu_dma_flush.
    joy = VIDEO.index("joy5a22_ordered:")
    assert "stz $1F1B" not in VIDEO[joy : VIDEO.index(".org $8E00", joy)]
    flush = VIDEO.index("ppu_dma_flush_acked:")
    flush_end = VIDEO.index("vid_obj_telemetry:", flush)
    body = VIDEO[flush:flush_end]
    assert "jmp ppu_dma_flush_ack_finish" in body
    assert "stz $1F1B" not in body
    helper = VIDEO.index("ppu_dma_flush_ack_finish:")
    helper_end = VIDEO.index("; =============================================================================", helper)
    owner = VIDEO[helper:helper_end]
    assert "sta $7E89A4" in owner
    assert "sep #$20\n.a8\n    lda $1F1B" in owner
    assert "stz $1F1B" in owner
    assert "rep #$20\n.a16" in owner
    early = VIDEO[VIDEO.index("nmi_present_before_dma:") : VIDEO.index(
        "nmi_present_before_dma_end:"
    )]
    assert "lda $1F1B\n    bmi npbd_boot_obj" in early
    boot_obj = early[early.index("npbd_boot_obj:") :]
    assert "jsl.l $E9CA80" in boot_obj
    assert "jsl.l $E9CD00" not in boot_obj
    assert "$3300" not in early and "$3302" not in early
    keepalive = VIDEO[VIDEO.index("nmi_video_keepalive:") : VIDEO.index(
        "nmi_video_keepalive_end:"
    )]
    assert keepalive.index("jsr boot_mode7_tick") < keepalive.index("lda $1F1B")
    assert "lda $1F1B\n    bmi nvk_done" in keepalive
    presenter_entry = VIDEO[
        VIDEO.index("bg_scroll_present_step:"):
        VIDEO.index("bg_scroll_present_step_end:")
    ]
    assert "jml.l $E9CD60" in presenter_entry
    presenter = VIDEO[
        VIDEO.index("bg_scroll_present_step_full:"):
        VIDEO.index("bg_scroll_present_step_full_end:")
    ]
    assert "lda $7E7194" in presenter
    assert "lda $7E72B2" in presenter
    assert "lda $7E7192" not in presenter
    assert "lda $7E71AA" in presenter
    assert presenter.count("sta $7E71AA") == 2
    queue_full = VIDEO[VIDEO.index("ptw_queue_full:") : VIDEO.index(
        "ptw_snapshot_direct:"
    )]
    assert "jsl.l $E9EA40" in queue_full
    latest_clean = VIDEO[VIDEO.index("render_queue_replace_latest_clean:") : VIDEO.index(
        "render_queue_replace_latest_clean_end:"
    )]
    for required in (
        "lda $7E89D2\n    cmp #$0001",
        "lda $7E89D6\n    cmp #$0001",
        "lda $41013A",
        "lda $7ED184",
        "lda $7EB004",
        "ora #$0001\n    sta $41013C",
        "jsl.l $E9B140",
        "jsl.l $E9B000",
        "sta $7E89D4",
    ):
        assert required in latest_clean
    promoter = VIDEO[VIDEO.index("render_queue_promote:") : VIDEO.index(
        "render_queue_promote_end:"
    )]
    assert "eor $7EB006\n    and #$0001" in promoter
    assert "sta $7E89D2\n    sta $7E89D6" in promoter
    assert "both BG-clean packets collapsed into the selected latest" in promoter

    # Mode-2 offsets are built into a private candidate and only published when
    # their complete applied image differs.  The marker becomes valid after the
    # synchronous DMA return, never merely after the WRAM copy.
    opt = VIDEO[VIDEO.index("bg_opt_update:") : VIDEO.index("bg_opt_update_end:")]
    assert "sta $7380,x" in opt and "sta $73C0,x" in opt
    assert "sta $7300,x" not in opt and "sta $7340,x" not in opt
    assert "jsr bg_opt_table_changed\n    bcc bou_select_mode2" in opt
    assert opt.index("jsr dma0_blank_pulse") < opt.index("sta $7E74AA")
    opt_cache = VIDEO[VIDEO.index("bg_opt_table_changed:") : VIDEO.index(
        "bg_opt_table_changed_end:"
    )]
    for required in (
        "lda $7E74AA\n    cmp #$A55A",
        "lda $7E7380,x\n    cmp $7E7300,x",
        "mvn $7E,$7E",
        "clc\n    rts",
        "sec\n    rts",
    ):
        assert required in opt_cache

    # The early foreground planner owns a complete slot/code list while BG is
    # constructed.  The final OAM path consumes that immutable plan and waits
    # only for the bounded NMI consumer; it cannot restart the queue at the end.
    queued = VIDEO[VIDEO.index("obj_upload_queued:") : VIDEO.index("ouq_done:")]
    assert "jml.l obj_upload_queued_extended|$E90000" in queued
    assert "jsr obj_tile_dma_direct" not in queued
    prefetch = VIDEO[VIDEO.index("obj_prefetch_begin:") : VIDEO.index(
        "obj_prefetch_begin_end:"
    )]
    finish = VIDEO[VIDEO.index("obj_upload_queued_extended:") : VIDEO.index(
        "obj_upload_queued_extended_end:"
    )]
    assert "jsr obj_fast_prepare" in prefetch
    assert prefetch.rindex("sta $7E74AC") < prefetch.index("sta $7E74A2")
    assert "lda $1F20\n    bne ouqe_wait" in finish
    assert "sta $7E74AC" in finish
    frame = VIDEO[VIDEO.index("vid_frame:") : VIDEO.index("decode_tile:")]
    assert frame.index("jsl.l obj_prefetch_begin|$E90000") < frame.index("jsr vid_bg")
    lead = VIDEO[VIDEO.index("nmi_present_then_wake:") : VIDEO.index(
        "nmi_present_then_wake_end:"
    )]
    assert "lda $7E74A2\n    cmp #$A55A" in lead
    assert "jml.l $E9D160" in lead
    post = VIDEO[VIDEO.index("nmi_present_then_sample:") : VIDEO.index(
        "nmi_present_then_sample_end:"
    )]
    assert post.index(
        "jsl.l nmi_obj_tile_batch_dispatch|$E90000"
    ) < post.index("jsl.l $E9CD20")
    assert "lda $1F11" not in post
    assert "sta $7E719B" not in post
    batch = VIDEO[VIDEO.index("nmi_obj_tile_batch:") : VIDEO.index(
        "nmi_obj_tile_batch_end:"
    )]
    for required in (
        "cmp #$FC",
        "and #$01\n    beq notb_time_safe",
        "sta DMAP5",
        "sta BBAD5",
        "sta A1T5L",
        "sta A1B5",
        "sta DAS5L",
        "lda #$20\n    sta MDMAEN",
        "sta $7E74A0\n    jmp notb_next",
        "sta $7E74A2          ; publish completion after the final DMA has returned",
    ):
        assert required in batch
    assert "sta $7E719B" not in batch
    assert "jsl.l $E9CD20" not in batch
    batch_lead = VIDEO[VIDEO.index("nmi_batch_present_then_wake:") : VIDEO.index(
        "nmi_batch_present_then_wake_end:"
    )]
    assert batch_lead.index(
        "jsl.l nmi_batch_present_arbitrate|$E90000"
    ) < batch_lead.index(
        "jsl.l nmi_obj_tile_batch_dispatch|$E90000"
    ) < batch_lead.index("jml.l $7F8E00")
    assert batch.count("sta MDMAEN") == 2
    assert batch.rindex("sta MDMAEN") < batch.index("sta $7E74A2")
    capture = VIDEO[VIDEO.index("capture_bg_upper_full:") : VIDEO.index(
        "capture_bg_upper_full_end:"
    )]
    assert capture.index("lda $D6\n    pha") < capture.index(
        "sta $D6\n    pla"
    )
    assert "stz $D8              ; occupied flag" not in capture
    for required in (
        "lda $7E71A8\n    sta $7E71AC",
        "lda $7E71A8\n    sta $7E71AE",
        "lda $7E71A8\n    sta $7E71B0",
    ):
        assert required in capture
    phase = capture[capture.index("cbuf_phase_loop:") : capture.index(
        "cbuf_irregular8:"
    )]
    assert "sta $D6              ; BG-code byte offset" in phase
    assert "txa\n    asl a\n    sta $D6" not in phase
    assert [column * 0x40 for column in range(16)] == list(
        range(0, 0x400, 0x40)
    )
    assert 0x400 == 0x3C0 + 0x40

    canonical = VIDEO[
        VIDEO.index("bg_column_map_update_fast:"):
        VIDEO.index("bg_column_map_update_fast_end:")
    ]
    rotation = VIDEO[
        VIDEO.index("bg_column_rotation_select:"):
        VIDEO.index("bg_column_rotation_select_end:")
    ]
    assert "jsr bg_column_rotation_select\n    bcs bcmf_rotation_ready" in canonical
    assert "sbc $D6" in canonical
    assert "sbc $7E89E4" not in canonical
    assert "jsr bg_column_occupied\n    bcc bcmf_normalize_next8" in canonical
    assert canonical.count("jsr bcmf_publish_map") == 2
    assert (
        "bcmf_incremental:\n    jsr bcmf_move_slot\n"
        "    lda $F4\n    jsr bcmf_clear_slot\n    jsr bcmf_update_column"
    ) in canonical
    assert "lda $F6\n    jsr bcmf_clear_slot" not in canonical
    for required in (
        "jsr bg_column_occupied",
        "cmp #$0002",
        "bit $DA",
        "sbc $7E89F0,x",
        "beq bcrs_fail        ; ties are geometry-ambiguous and must rebuild fully",
    ):
        assert required in rotation
    publish_map = canonical[
        canonical.index("bcmf_publish_map:"):
        canonical.index("bcmf_clear_slot:")
    ]
    assert "lda $7E74B0,x\n    sta $7E89F0,x" in publish_map
    update_column = canonical[canonical.index("bcmf_update_column:"):]
    assert (
        "and #$001E\n    asl a\n    asl a\n    asl a\n    asl a\n    asl a\n    asl a\n"
        "    sta $D2              ; (cell & ~1) * 64"
    ) in update_column
    assert expected_column_offsets(5, 12) == [
        0x0820,
        0x0824,
        0x08A0,
        0x08A4,
        0x0920,
        0x0924,
        0x09A0,
        0x09A4,
        0x0A20,
        0x0A24,
        0x0AA0,
        0x0AA4,
        0x0B20,
        0x0B24,
        0x0BA0,
        0x0BA4,
        0x0C20,
        0x0C24,
        0x0CA0,
        0x0CA4,
        0x0D20,
        0x0D24,
        0x0DA0,
        0x0DA4,
        0x0E20,
        0x0E24,
        0x0EA0,
        0x0EA4,
        0x0F20,
        0x0F24,
        0x0FA0,
        0x0FA4,
    ]

    occupied = (True,) * 14 + (False,) * 2
    applied_248 = bytes.fromhex("0e0f00030405060708090a0b0c0d0505")
    raw_248 = bytes.fromhex("08090a0b0e0f00010203040506070000")
    rotation_248 = majority_column_rotation(raw_248, applied_248, occupied)
    assert rotation_248 == 10
    normalized_248 = bytes((value - rotation_248) & 0x0F for value in raw_248)
    assert normalized_248.hex() == "0e0f00010405060708090a0b0c0d0606"
    assert sum(
        normalized_248[index] != applied_248[index] for index in range(14)
    ) == 1

    # Exact retained fad4dafb gap crossing.  Source 4 changes slot and therefore
    # yields rotation 8, but 13 of the other populated sources prove rotation
    # 10.  The old anchor falsely moved 13 live columns; the majority moves one.
    applied_270 = normalized_248
    raw_270 = bytes.fromhex("08090a0b0c0f00010203040506070000")
    rotation_270 = majority_column_rotation(raw_270, applied_270, occupied)
    assert rotation_270 == 10
    normalized_270 = bytes((value - rotation_270) & 0x0F for value in raw_270)
    anchor_rotation = (raw_270[4] - 4) & 0x0F
    anchor_270 = bytes((value - anchor_rotation) & 0x0F for value in raw_270)
    assert sum(
        normalized_270[index] != applied_270[index] for index in range(14)
    ) == 1
    assert sum(anchor_270[index] != applied_270[index] for index in range(14)) == 13
    assert majority_column_rotation(b"\x00\x01", b"\x00\x00", (True, True)) is None
    assert majority_column_rotation(b"\x00", b"\x00", (True,)) is None

    raw = controls()
    raw[9 + 14 * 0x20] = 0
    raw[9 + 15 * 0x20] = 0
    assert derive_bg_column_capture(bytes(raw), bg_code(tuple(range(14))))[0] == 0

    raw[9 + 7 * 0x20] ^= 1
    assert derive_bg_column_capture(bytes(raw), bg_code(tuple(range(14))))[0] == 0xFFFE

    zero = controls(0)
    assert derive_bg_column_capture(bytes(zero), bg_code((0, 1)))[0] == 0
    attribute_only = bytearray(0x400)
    attribute_only[0:2] = b"\x80\x00"  # $8000: flip attribute, code zero
    attribute_only[2:4] = b"\x40\x00"  # $4000: flip attribute, code zero
    assert derive_bg_column_capture(bytes(zero), bytes(attribute_only))[0] == 0
    populated = bytearray(attribute_only)
    populated[4:6] = b"\x00\x80"  # $0080: populated code
    assert derive_bg_column_capture(bytes(zero), bytes(populated))[0] == 0
    identity = controls(0)
    identity[0x205] = 0
    identity[0x207] = 0xFF
    assert derive_bg_column_capture(bytes(identity), bg_code(()))[1] == bytes(
        range(16)
    )
    print("renderer boot/empty-column static guards: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
