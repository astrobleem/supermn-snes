#!/usr/bin/env python3
"""Focused regression for X1 column-layout capture semantics."""

from __future__ import annotations

import hashlib

from validate_packed_obj_snapshot import (
    bg_layout_requires_rebuild,
    derive_bg_column_capture,
    prepared_requires_remap,
    remap_prepared_tilemap,
)


def make_raw(
    *,
    upper_mask: int,
    start: int = 0,
    sequential: bool = True,
    start_control: int = 0,
    count_control: int = 1,
) -> bytearray:
    raw = bytearray(0x0208)
    raw[0x0201] = start_control
    raw[0x0203] = count_control
    raw[0x0205] = upper_mask & 0xFF
    raw[0x0207] = upper_mask >> 8
    for column in range(16):
        value = (start + column * 0x20) & 0xFF
        if not sequential and column == 7:
            value ^= 0x20
        raw[0x0009 + column * 0x20] = value
    return raw


def make_bg_code(occupied: tuple[int, ...], value: int = 1) -> bytes:
    code = bytearray(0x0400)
    for column in occupied:
        for offset in range(column * 0x40, (column + 1) * 0x40, 2):
            code[offset : offset + 2] = value.to_bytes(2, "big")
    return bytes(code)


def main() -> int:
    regular = make_raw(upper_mask=0x00FF, start=0x20)
    kind, column_map = derive_bg_column_capture(bytes(regular))
    assert kind == 0x00FF
    assert column_map == bytes(
        ((1 + column) & 7) | (8 if column < 8 else 0)
        for column in range(16)
    )

    stage3 = make_raw(upper_mask=0xC003, sequential=False)
    kind, _ = derive_bg_column_capture(bytes(stage3))
    assert kind == 0xC003

    prompt = make_raw(
        upper_mask=0x0000,
        start_control=0x10,
        count_control=0x21,
    )
    kind, _ = derive_bg_column_capture(bytes(prompt))
    assert kind == 0x0000

    odd_irregular = make_raw(
        upper_mask=0x0001,
        start_control=1,
        count_control=0,
    )
    kind, _ = derive_bg_column_capture(bytes(odd_irregular))
    assert kind == 0xFFFF

    aligned_permutation = make_raw(upper_mask=0x0FF0, sequential=False)
    kind, _ = derive_bg_column_capture(bytes(aligned_permutation))
    assert kind == 0x0FF0

    phase_irregular = make_raw(upper_mask=0x0FF0, sequential=False)
    phase_irregular[0x0009 + 7 * 0x20] ^= 0x01
    kind, _ = derive_bg_column_capture(bytes(phase_irregular))
    assert kind == 0xFFFE

    # Empty columns have no phase: populated 0..13 at phase 15 remains exact
    # even when the producer reports X=0 for empty columns 14/15.
    sparse = make_raw(upper_mask=0x0000, start=0x0F)
    for column in (14, 15):
        sparse[0x0009 + column * 0x20] = 0
    kind, _ = derive_bg_column_capture(
        bytes(sparse), make_bg_code(tuple(range(14)))
    )
    assert kind == 0x0000

    # A populated phase mismatch still rejects the exact permutation.
    sparse[0x0009 + 7 * 0x20] ^= 1
    kind, _ = derive_bg_column_capture(
        bytes(sparse), make_bg_code(tuple(range(14)))
    )
    assert kind == 0xFFFE

    # Phase zero is valid when it belongs to a populated source column; empty
    # remainder columns must not turn it into an irregular layout.
    phase_zero = make_raw(upper_mask=0xFF00, start=0)
    kind, _ = derive_bg_column_capture(
        bytes(phase_zero), make_bg_code((0, 1, 2))
    )
    assert kind == 0xFF00

    # All-empty retains the historical regular/identity result.
    kind, identity_map = derive_bg_column_capture(
        bytes(phase_zero), make_bg_code(())
    )
    assert kind == 0xFF00
    assert identity_map == bytes(range(16))

    # Byte-exact retained one-credit prompt controls.  This is deliberately
    # non-sequential yet phase-aligned: occupied source columns 0/1/2/4 must
    # land contiguously at physical slots 4/5/6/7.
    credited_prompt = bytearray(0x0208)
    for column in range(12):
        credited_prompt[column * 0x20 + 0x01] = 0xF9
    for column in range(8, 12):
        credited_prompt[column * 0x20 + 0x08] = 0x01
    for column, xlow in enumerate(
        (
            0x80,
            0xA0,
            0xC0,
            0x60,
            0xE0,
            0xA0,
            0xC0,
            0xE0,
            0x00,
            0x20,
            0x40,
            0x60,
            0x00,
            0x00,
            0x00,
            0x00,
        )
    ):
        credited_prompt[column * 0x20 + 0x09] = xlow
    credited_prompt[0x0201] = 0x10
    credited_prompt[0x0203] = 0x21
    credited_prompt[0x0207] = 0x0F
    assert hashlib.sha256(credited_prompt).hexdigest() == (
        "0a421fcb2c193b2a3573ab4550eeee0bd56e5ca7045cbdd469284bce46f4fb8a"
    )
    prompt_kind, prompt_map = derive_bg_column_capture(bytes(credited_prompt))
    assert prompt_kind == 0x0F00
    assert prompt_map == bytes.fromhex(
        "040506030705060708090a0b00000000"
    )
    assert tuple(prompt_map[index] for index in (0, 1, 2, 4)) == (
        4,
        5,
        6,
        7,
    )
    assert prepared_requires_remap(0xFFFE, prompt_kind, prompt_map)
    assert len(set(prompt_map)) != len(prompt_map)

    prepared = bytearray(0x1000)
    for row in range(32):
        for source in range(16):
            offset = (
                row * 0x40
                + (source & 7) * 8
                + (0x0800 if source & 8 else 0)
            )
            prepared[offset : offset + 8] = bytes([source + 1]) * 8
    remapped = remap_prepared_tilemap(bytes(prepared), prompt_map)
    for row in range(32):
        for destination in range(16):
            owners = [
                source
                for source, slot in enumerate(prompt_map)
                if slot == destination
            ]
            expected = 0 if not owners else owners[-1] + 1
            offset = (
                row * 0x40
                + (destination & 7) * 8
                + (0x0800 if destination & 8 else 0)
            )
            assert remapped[offset : offset + 8] == bytes([expected]) * 8

    sparse_prompt = bytearray(0x1000)
    for row in range(32):
        for source in (0, 1, 2, 4):
            offset = (
                row * 0x40
                + (source & 7) * 8
                + (0x0800 if source & 8 else 0)
            )
            sparse_prompt[offset : offset + 8] = bytes([source + 1]) * 8
    sparse_remapped = remap_prepared_tilemap(
        bytes(sparse_prompt), prompt_map
    )
    for source, destination in ((0, 4), (1, 5), (2, 6), (4, 7)):
        for row in range(32):
            offset = (
                row * 0x40
                + (destination & 7) * 8
                + (0x0800 if destination & 8 else 0)
            )
            assert sparse_remapped[offset : offset + 8] == (
                bytes([source + 1]) * 8
            )

    identity_prepared = make_raw(upper_mask=0xFF00)
    identity_kind, identity_map = derive_bg_column_capture(
        bytes(identity_prepared)
    )
    assert identity_kind == 0xFF00
    assert identity_map == bytes(range(16))
    assert not prepared_requires_remap(
        0xFFFE, identity_kind, identity_map
    )
    assert remap_prepared_tilemap(bytes(prepared), identity_map) == prepared
    assert not prepared_requires_remap(0xFFFF, prompt_kind, prompt_map)
    assert not prepared_requires_remap(0xFFFE, 0xFFFE, prompt_map)

    # Retained Stage-3 trace: the upper-position mask advanced while all
    # sixteen physical slots remained identical.  This is scroll-only state,
    # not geometry, and must not trigger another 392-cell reconstruction.
    stage3_map = bytes.fromhex("08090a0b0e0f00010203040506070e0e")
    assert not bg_layout_requires_rebuild(
        0xC03F,
        stage3_map,
        0xC07E,
        stage3_map,
    )
    changed_stage3_map = bytearray(stage3_map)
    changed_stage3_map[6] = 1
    assert bg_layout_requires_rebuild(
        0xC07E,
        stage3_map,
        0xC07E,
        bytes(changed_stage3_map),
    )

    print(
        "BG column capture regression: 6 synthetic layout families, "
        "exact credited-prompt fixture, transparent overlap order, and "
        "Stage-3 kind-only scroll transition green"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
