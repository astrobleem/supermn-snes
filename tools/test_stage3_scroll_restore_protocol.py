#!/usr/bin/env python3
"""Keep the Stage-3 checkpoint renderer test honest about state restore."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "validate_stage3_scroll_input_probe.py"


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    required = (
        "restore_vblank_frames = advance_exact(m, 0, 1)",
        'f"{label}/after-restore-vblank"',
        '"after_restore_vblank_blue_gap_columns"',
        '"native_off_restore_does_not_advance_game_tick"',
        '"native_on_restore_does_not_advance_game_tick"',
        '"native_off_restore_vblank_blue_gap_cleared"',
        '"native_on_restore_vblank_blue_gap_cleared"',
    )
    missing = [needle for needle in required if needle not in text]
    assert not missing, (
        "Stage-3 checkpoint recovery must prove a neutral post-load vblank "
        f"before input-driven recovery: {missing}"
    )
    print("Stage-3 restore-vblank regression protocol: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
