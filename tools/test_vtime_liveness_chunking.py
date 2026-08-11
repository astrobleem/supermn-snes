#!/usr/bin/env python3
"""Guard the long VTIME liveness probe against a single RPC timeout."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "validate_vtime_liveness.py"


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "while remaining:",
        "requested = min(120, remaining)",
        "--single-frame-after",
        "--max-wall-seconds",
        "if slice_before >= args.single_frame_after:",
        "requested = 1",
        "timed_out = True",
        '"result": "inconclusive" if timed_out',
        "response = m.run_frames(requested)",
        "pause_response = m.pause()",
        "if advanced <= 0:",
        '"shortfall": requested - advanced',
        '"pause_response": pause_response',
        'def write_progress(',
        '"progress.json"',
        '"last_completed_frame"',
        '"host-side completed-RPC progress only',
        '"interpreter_only_native_gates_disabled_after_timer_activation"',
        'after["magic"] == VTIME_MAGIC',
    )
    missing = [text for text in required if text not in source]
    if missing:
        raise AssertionError(
            "VTIME liveness probe lost its sliced pause/accounting guard: "
            + ", ".join(repr(text) for text in missing)
        )
    if "m.run_frames(args.frames)" in source:
        raise AssertionError(
            "VTIME liveness probe restored one long run_frames RPC; "
            "it can time out before its post-run snapshot"
        )
    print("VTIME liveness transport-chunk regression: green")


if __name__ == "__main__":
    main()
