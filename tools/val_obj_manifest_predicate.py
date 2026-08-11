#!/usr/bin/env python3
"""Focused regression for the production packed-OBJ visibility predicate."""

from __future__ import annotations

import validate_paced_obj_sources as paced
import validate_packed_obj_snapshot as snapshot
import validate_fast_obj_renderer as fast


def put_word(plane: bytearray, offset: int, value: int) -> None:
    plane[offset : offset + 2] = value.to_bytes(2, "big")


def fixture_manifest(*, title_overlay: bool) -> tuple[bytes, bytes]:
    y = bytearray(0x0400)
    code = bytearray(0x0400)
    x = bytearray(0x0400)

    fixtures = (
        # offset, Y, code, X
        (0x0000, 0xF2, 0x0010, 0x0020),  # visible top-left, translated +48
        (0x0002, 0xF2, 0x0020, 0x0050),  # transparent HUD spacer, rejected
        (0x0004, 0x0A, 0x0002, 0x00E0),  # CREDIT black spacer, rejected
        (0x0006, 0xF3, 0x0013, 0x0080),  # above top edge, rejected
        (0x0008, 0x0A, 0x007D, 0x0120),  # CREDIT glyph, translated -48
        (0x000A, 0x0A, 0x0030, 0x0080),  # ordinary centered record
        (0x000C, 0xE2, 0x0012, 0x0120),  # visible top-right, translated -24
        (0x0048, 0x0A, 0x0002, 0x00D0),  # digit black spacer, rejected
        (0x004A, 0x0A, 0x0031, 0x0080),  # stale bottom status slot, rejected
        (0x006A, 0x1A, 0x0097, 0x0138),  # ROUND edge fragment, rejected
        (0x0072, 0x1A, 0x0040, 0x0138),  # adjacent ordinary slot, visible
        (0x0100, 0x1A, 0x0041, 0x0080),  # title text row, metadata-gated
        (0x0102, 0x1B, 0x0042, 0x0080),  # adjacent non-title row
    )
    for offset, sy, code_word, x_word in fixtures:
        put_word(y, offset, sy)
        put_word(code, offset, code_word)
        put_word(x, offset, x_word)

    visible = paced.expected_obj_manifest(
        bytes(y),
        bytes(code),
        bytes(x),
        title_overlay=title_overlay,
    )
    packed = paced.expected_packed_manifest(
        bytes(y),
        bytes(code),
        bytes(x),
        title_overlay=title_overlay,
    )
    return visible, packed


def main() -> int:
    helper_cases = (
        (0xF2, 0x0020, 0x0010, 0x0000, 0x0050),
        (0xE2, 0x0120, 0x0012, 0x0004, 0x0108),
        (0x0A, 0x0120, 0x007D, 0x0008, 0x00F0),
        (0x0A, 0x00E0, 0x0002, 0x0004, None),
        (0x0A, 0x00D0, 0x0002, 0x0048, None),
        (0x0A, 0x0080, 0x0031, 0x004A, None),
        (0x1A, 0x0138, 0x0097, 0x006A, None),
        (0x1A, 0x0138, 0x0040, 0x0072, 0x0138),
        (0xF2, 0x0050, 0x0020, 0x0002, None),
        (0x40, 0x0031, 0x0040, 0x0100, 0x0031),
        (0x40, 0x0140, 0x0040, 0x0100, None),
        (0x40, 0x0080, 0x0002, 0x0004, 0x0080),
    )
    for sy, x_word, code_word, source_offset, expected in helper_cases:
        paced_value = paced.packed_x_word(
            sy,
            x_word,
            code_word,
            source_offset=source_offset,
        )
        snapshot_value = snapshot.packed_x_word(
            sy,
            x_word,
            code_word,
            source_offset=source_offset,
        )
        fast_value = fast.packed_x_word(
            sy,
            x_word,
            code_word,
            source_offset=source_offset,
        )
        assert paced_value == expected
        assert snapshot_value == expected
        assert fast_value == expected

    y_plane = bytearray(0x0400)
    y_plane[1] = 0xF2
    y_plane[3] = 0xF3
    assert paced.expected_y_manifest(bytes(y_plane)) == b"\x00\x00"

    visible_title, packed_title = fixture_manifest(title_overlay=True)
    assert visible_title == bytes.fromhex("000008000a000c000201")
    assert len(packed_title) == 30

    visible_plain, packed_plain = fixture_manifest(title_overlay=False)
    assert visible_plain == bytes.fromhex(
        "000008000a000c00720000010201"
    )
    assert len(packed_plain) == 42

    print(
        "packed OBJ predicate regression: "
        "12 helper + 2 manifest + Y-edge cases green"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
