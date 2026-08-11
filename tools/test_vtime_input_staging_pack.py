#!/usr/bin/env python3
"""Guard VTIME-only, one-tick-ordered controller staging and ROM packing."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "build/interp.sfc"
VTIME_ENABLE_FILE = 0x328000
VIDEO_FILE = 0x298000
JOY_ORIGINAL = bytes.fromhex("08c230af00004185662860")
INPUT_P1_ORIGINAL = bytes.fromhex("2056f8c230")
INPUT_P1_VTIME = bytes.fromhex("2240b7f2ea")


def symbol(path: Path, name: str) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError(f"missing symbol {name} in {path}")


def body(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


def main() -> None:
    video_source = (ROOT / "src/video.pasm").read_text(encoding="utf-8")
    vtime_source = (ROOT / "src/vtime.pasm").read_text(encoding="utf-8")
    enabled_source = (ROOT / "src/vtime_enabled.pasm").read_text(encoding="utf-8")
    packer = (ROOT / "tools/build_interp_rom.py").read_text(encoding="utf-8")

    publisher = body(
        video_source, "pacing_publish_vtime_joy:\n", "pacing_helpers_end:\n"
    )
    for required in (
        "sta $41015C          ; odd",
        "lda $1F12",
        "sta $41015E",
        "sta $41015C          ; even",
        "sep #$20",
    ):
        assert required in publisher
    assert "VTIME_INPUT_DELAYED_COMMIT_FIX=1" in enabled_source

    bridge = body(
        vtime_source,
        "vtime_input_p1_delayed:\n",
        "vtime_input_p1_delayed_end:\n",
    )
    assert bridge.index("jsr vtime_input_ensure") < bridge.index(
        "cmp.l VT_INPUT_LAST_RELEASE"
    )
    assert bridge.index("cmp.l VT_INPUT_LAST_RELEASE") < bridge.index(
        "lda.l VT_INPUT_PENDING"
    )
    assert bridge.index("sta.l $410000") < bridge.index("sta $66")
    assert bridge.index("sta $66") < bridge.index("jsr vtime_input_read_staged")
    assert bridge.index("jsr vtime_input_read_staged") < bridge.index(
        "sta.l VT_INPUT_PENDING"
    )
    assert bridge.index("lda.l $41015C") < bridge.index("lda.l $41015E")
    assert bridge.count("$41015C") == 2
    assert bridge.index("cmp.l $41015C") < bridge.index("lda.l $410002")
    assert "ora.l VT_INPUT_SCRATCH" in bridge and "lda $66" in bridge
    assert 'input_p1_vtime = bytes.fromhex("2240b7f2ea")' in packer
    assert "if not vtime_enabled:" in packer

    rom = ROM.read_bytes()
    assert len(rom) == 0x400000
    enabled = bool(rom[VTIME_ENABLE_FILE] & 0x01)
    video_sym = ROOT / "src/video.sym"
    interp_sym = ROOT / "src/interp.sym"
    vtime_sym = ROOT / "src/vtime.sym"
    tail = symbol(video_sym, "pacing_vtime_publish_tail")
    helper_end = symbol(video_sym, "pacing_helpers_end")
    assert tail == 0x8EA8 and helper_end <= 0x8F00
    source_video = (ROOT / "src/video.bin").read_bytes()
    source_span = source_video[tail - 0x8000:helper_end - 0x8000]
    packed_span = rom[
        VIDEO_FILE + tail - 0x8000:VIDEO_FILE + helper_end - 0x8000
    ]
    assert packed_span == (
        source_span if enabled else b"\x60" + bytes(len(source_span) - 1)
    )

    joy = symbol(interp_sym, "joy_read")
    for offset in (joy - 0x8000, joy):
        assert rom[offset:offset + len(JOY_ORIGINAL)] == JOY_ORIGINAL

    input_p1 = symbol(interp_sym, "input_p1")
    expected_input_p1 = INPUT_P1_VTIME if enabled else INPUT_P1_ORIGINAL
    for offset in (input_p1 - 0x8000, input_p1):
        assert rom[offset:offset + len(expected_input_p1)] == expected_input_p1

    staged = symbol(vtime_sym, "vtime_input_p1_delayed")
    staged_end = symbol(vtime_sym, "vtime_input_p1_delayed_end")
    dynamic_end = symbol(vtime_sym, "vtime_dynamic_helpers_end")
    assert dynamic_end <= 0xB740
    assert staged == 0xB740 and staged_end <= 0xBA00
    if enabled:
        assert staged_end > staged
        vtime_bin = (ROOT / "src/vtime.bin").read_bytes()
        helper = vtime_bin[staged - 0x8000:staged_end - 0x8000]
        assert bytes.fromhex("af5c0141") in helper
        assert bytes.fromhex("af5e0141") in helper
        assert bytes.fromhex("af020041") in helper
        for state_address in (0x404020, 0x404022, 0x404024, 0x404026):
            assert state_address.to_bytes(3, "little") in helper
    else:
        assert staged_end == staged

    print("VTIME input staging/pack regression: green")


if __name__ == "__main__":
    main()
