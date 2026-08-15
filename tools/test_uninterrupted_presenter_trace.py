#!/usr/bin/env python3
"""Unit checks for the uninterrupted presenter-cadence gate."""

from analyze_uninterrupted_presenter_trace import analyze_trace


def event(label: str, frame: int, value: int = 0) -> dict[str, int | str]:
    return {"label": label, "frame": frame, "value": value}


def fixture() -> tuple[dict, list[dict]]:
    source = {
        "initial": {"ppu_frame": 100},
        "final": {"ppu_frame": 105},
        "advanced_video_frames": 5,
    }
    events = []
    for index, frame in enumerate(range(101, 106)):
        events.extend(
            (
                event("bg_scroll_present_step", frame),
                event("obj_present_nmi", frame),
                event("presented_scrollx_write", frame, (20 - index * 2) & 0xFF),
            )
        )
    return source, events


def main() -> int:
    source, events = fixture()
    assert analyze_trace(source, events, 5)["result"] == "green"

    missing = [row for row in events if not (
        row["label"] == "bg_scroll_present_step" and row["frame"] == 103
    )]
    missing_report = analyze_trace(source, missing, 5)
    assert missing_report["result"] == "red"
    assert missing_report["mismatch_ranges"]["bg_scroll_present_step"]["missing"] == [[103, 103]]

    duplicate = events + [event("obj_present_nmi", 104)]
    assert analyze_trace(source, duplicate, 5)["result"] == "red"

    oversized = [dict(row) for row in events]
    for row in oversized:
        if row["label"] == "presented_scrollx_write" and row["frame"] == 103:
            row["value"] = 10
    assert analyze_trace(source, oversized, 5)["result"] == "red"

    short_source = dict(source)
    short_source["advanced_video_frames"] = 4
    assert analyze_trace(short_source, events, 5)["result"] == "unknown"
    print("uninterrupted presenter trace gate: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
