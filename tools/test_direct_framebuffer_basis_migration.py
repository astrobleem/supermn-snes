#!/usr/bin/env python3
"""Guard the checkpoint-only nine-bit BG basis migration."""

from __future__ import annotations

import capture_snes_direct_framebuffers as capture


class FakeSession:
    def __init__(self) -> None:
        self.wram = bytearray(0x20000)
        self.writes: list[tuple[str, int, str]] = []

    def read_memory(self, memory_type: str, address: int, length: int) -> bytes:
        if memory_type != "snesWorkRam":
            raise AssertionError(memory_type)
        return bytes(self.wram[address : address + length])

    def write_memory(self, memory_type: str, address: int, data: str) -> None:
        if memory_type != "snesWorkRam":
            raise AssertionError(memory_type)
        raw = bytes.fromhex(data)
        self.wram[address : address + len(raw)] = raw
        self.writes.append((memory_type, address, data))


def coherent_row() -> dict[str, object]:
    # slot 4 = 12, phase = 96, raw column 4 X = 64:
    # (12 * 32 + 96 - 64) & 0x1ff = 0x1a0.
    column_map = bytes((8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7))
    return {
        "renderer_busy": 0,
        "render_queue_primary": 0,
        "render_queue_secondary": 0,
        "snapshot_generation": 7,
        "direct_generation": 7,
        "rendered_generation": 7,
        "displayed_map_valid": 0xA5,
        "bg_column_kind": 1,
        "bg_column_map_applied": column_map.hex(),
        "displayed_column_map": column_map.hex(),
        "obj_cache_scrollx": 96,
        "obj_queue_scrollx": 96,
        "obj_queue2_scrollx": 96,
        "latest_scrollx": 96,
        "presented_scrollx": 96,
        "bg1_hscroll": 0x180,
        "scroll_packed": 64 << 8,
    }


def main() -> int:
    fake = FakeSession()
    report = capture.initialize_basis9_from_coherent_map(fake, coherent_row())
    assert report[0]["basis"] == 0x1A0
    assert bytes(fake.wram[0x71A4 : 0x71B2]) == bytes.fromhex(
        "a001a00160006000600060006000"
    )
    assert fake.writes == [
        (
            "snesWorkRam",
            0x71A4,
            "a001a00160006000600060006000",
        ),
    ]

    incoherent = coherent_row()
    incoherent["render_queue_primary"] = 1
    rejected = FakeSession()
    try:
        capture.initialize_basis9_from_coherent_map(rejected, incoherent)
    except RuntimeError as exc:
        assert "idle queues" in str(exc)
    else:
        raise AssertionError("migration accepted a non-idle renderer")
    assert rejected.writes == []

    print("direct framebuffer nine-bit basis migration: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
