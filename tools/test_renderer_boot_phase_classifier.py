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
    capture = VIDEO[VIDEO.index("capture_bg_upper_full:") : VIDEO.index(
        "capture_bg_upper_full_end:"
    )]
    assert capture.index("lda $D6\n    pha") < capture.index(
        "sta $D6\n    pla"
    )
    assert "stz $D8              ; occupied flag" not in capture
    phase = capture[capture.index("cbuf_phase_loop:") : capture.index(
        "cbuf_irregular8:"
    )]
    assert "sta $D6              ; BG-code byte offset" in phase
    assert "txa\n    asl a\n    sta $D6" not in phase
    assert [column * 0x40 for column in range(16)] == list(
        range(0, 0x400, 0x40)
    )
    assert 0x400 == 0x3C0 + 0x40

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
