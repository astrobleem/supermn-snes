#!/usr/bin/env python3
"""Trace causal hook events between authenticated exact gameplay boundaries.

The source state must be a post-entry safe checkpoint with recursively
authenticated fresh-boot lineage.  Each interval ends on the synchronous
$003A92 pre-body boundary used by the controller campaign.  Ordinary hook
notifications are observations only; they never select or pause the stop.
The retained event count is checked against Nexen's hook-emission counter so
the 4096-event notification queue cannot silently truncate evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_TIMELINE = EVIDENCE / "full-playback-timeline-v1" / "timeline.jsonl"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-safe-checkpoint-publish/Nexen"
)

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_snes_movie_ticks as capture_tool  # noqa: E402
import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_named_address(value: str) -> tuple[str, int]:
    try:
        label, address_text = value.split("=", 1)
        address = int(address_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "expected LABEL=0xADDRESS"
        ) from error
    if not label or not 0 <= address <= 0xFFFFFF:
        raise argparse.ArgumentTypeError("expected LABEL=0xADDRESS")
    return label, address


def parse_named_range(value: str) -> tuple[str, int, int]:
    try:
        label, range_text = value.split("=", 1)
        if "-" in range_text:
            start_text, end_text = range_text.split("-", 1)
        else:
            start_text = end_text = range_text
        start = int(start_text, 0)
        end = int(end_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "expected LABEL=0xSTART[-0xEND]"
        ) from error
    if not label or not 0 <= start <= end <= 0xFFFFFF:
        raise argparse.ArgumentTypeError(
            "expected LABEL=0xSTART[-0xEND]"
        )
    return label, start, end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--state-mame-tick", type=int, required=True)
    parser.add_argument(
        "--state-lineage-events",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--allow-forensic-nonresumable-state",
        action="store_true",
        help=(
            "permit a retained nested SA-1 exact-entry state for route "
            "forensics only; this never upgrades that state to fresh-boot "
            "or resumable evidence"
        ),
    )
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--end-mame-tick", type=int, required=True)
    parser.add_argument(
        "--gameplay-native",
        choices=("preserve", "off"),
        default="preserve",
    )
    parser.add_argument(
        "--exec-hook",
        type=parse_named_address,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--write-hook",
        type=parse_named_range,
        action="append",
        default=[],
    )
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9270)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.end_mame_tick <= args.state_mame_tick:
        parser.error("--end-mame-tick must follow --state-mame-tick")
    if not args.exec_hook and not args.write_hook:
        parser.error("at least one --exec-hook or --write-hook is required")
    labels = [row[0] for row in [*args.exec_hook, *args.write_hook]]
    if len(labels) != len(set(labels)):
        parser.error("hook labels must be unique")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("lineage events", args.state_lineage_events),
        ("timeline", args.timeline),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def hook_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row["params"])
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
        and isinstance(row.get("params"), dict)
    ]


def drain_paused_hook_rows(
    m: campaign.AuditedMcpSession,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drain until the paused hook counter and notification stream stabilize."""

    retained: list[dict[str, Any]] = []
    previous_matches = -1
    empty_passes = 0
    final_diag: dict[str, Any] = {}
    for _attempt in range(12):
        retained.extend(hook_rows(m.drain_notifications(timeout=0.10)))
        final_diag = dict(m.hook_diag())
        retained.extend(hook_rows(m.drain_notifications(timeout=0.05)))
        matches = int(final_diag.get("matchedEventsEmitted", -1))
        if matches == previous_matches:
            empty_passes += 1
        else:
            empty_passes = 0
        previous_matches = matches
        if empty_passes >= 1:
            return retained, final_diag
    raise RuntimeError("hook notification stream did not stabilize while paused")


def read_timeline(
    path: Path,
    start_tick: int,
    end_tick: int,
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            tick = int(row.get("tick", -1))
            if (
                start_tick <= tick <= end_tick
                and row.get("event") == "tick"
            ):
                rows[tick] = row
    missing = [
        tick
        for tick in range(start_tick, end_tick + 1)
        if tick not in rows
    ]
    if missing:
        raise RuntimeError(
            f"timeline lacks exact tick-start rows: {missing[:16]}"
        )
    return rows


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.state_lineage_events = args.state_lineage_events.resolve()
    args.timeline = args.timeline.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()

    state_auth = capture_tool.authenticate_start_state(
        state=args.state,
        state_mame_tick=args.state_mame_tick,
        rom=args.rom,
        timeline=args.timeline,
        nexen=args.nexen,
        lineage_events=args.state_lineage_events,
        allow_forensic_nonresumable_state=args.allow_forensic_nonresumable_state,
    )
    timeline = read_timeline(
        args.timeline,
        args.state_mame_tick,
        args.end_mame_tick,
    )
    timeline_buttons = int(
        timeline[args.state_mame_tick]["snes_buttons"]
    )
    retained_buttons = (
        timeline_buttons
        if args.allow_forensic_nonresumable_state
        else int(state_auth["lineage"]["resume_context"]["current_buttons"])
    )
    if retained_buttons != timeline_buttons:
        raise RuntimeError(
            "checkpoint/timeline controller mismatch: "
            f"{retained_buttons} != {timeline_buttons}"
        )

    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    boundaries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    runtime_controls: list[dict[str, Any]] = []

    with campaign.AuditedMcpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        load_response = dict(m.load_state(args.state))
        campaign.require_paused(m, "checkpoint load")
        loaded_validation = capture_tool.validate_loaded_start_state(
            m,
            state_auth,
        )

        xlat_native_enabled = True
        if args.gameplay_native == "off":
            for address in capture_tool.GAMEPLAY_NATIVE_GATES:
                before = int(m.read_u16(address, "Sa1Memory"))
                m.write_u16(address, 0, "Sa1Memory")
                runtime_controls.append(
                    {
                        "kind": "native_gate_classification",
                        "address": f"{address:04X}",
                        "before": before,
                        "after": 0,
                    }
                )
            xlat_native_enabled = False

        input_responses: list[dict[str, Any]] = [
            {
                "mame_tick": args.state_mame_tick,
                "buttons": retained_buttons,
                "response": campaign.set_held_input(m, retained_buttons),
            }
        ]
        boundaries.append(
            capture_tool.capture(
                m,
                args.output,
                args.state_mame_tick,
            )
        )

        handle_labels: dict[int, str] = {}
        for label, address in args.exec_hook:
            handle = m.add_exec_hook(address, cpu_type="Sa1")
            handle_labels[handle] = label
        for label, start, end in args.write_hook:
            handle = m.add_write_hook(
                start,
                end_address=end,
                cpu_type="Sa1",
            )
            handle_labels[handle] = label
        _discarded, install_diag = drain_paused_hook_rows(m)

        try:
            for start_tick in range(
                args.state_mame_tick,
                args.end_mame_tick,
            ):
                end_tick = start_tick + 1
                discarded, before_diag = drain_paused_hook_rows(m)
                if discarded:
                    raise RuntimeError(
                        "unexpected pending hook events before interval "
                        f"{start_tick}: {discarded}"
                    )
                before_cpu = dict(m.get_cpu_state("Sa1"))
                spans = capture_tool.run_game_update_boundaries(
                    m,
                    1,
                    xlat_native_enabled=xlat_native_enabled,
                )
                campaign.require_paused(m, f"exact boundary {end_tick}")
                after_cpu = dict(m.get_cpu_state("Sa1"))
                rows, after_diag = drain_paused_hook_rows(m)
                emitted = (
                    int(after_diag["matchedEventsEmitted"])
                    - int(before_diag["matchedEventsEmitted"])
                )
                if emitted != len(rows):
                    raise RuntimeError(
                        "hook evidence truncated or miscounted in interval "
                        f"{start_tick}->{end_tick}: emitted={emitted}, "
                        f"retained={len(rows)}"
                    )

                terminal_cycle = int(after_cpu.get("cycleCount", -1))
                interval_events: list[dict[str, Any]] = []
                for row in rows:
                    handle = int(row.get("handle", -1))
                    if handle not in handle_labels:
                        raise RuntimeError(
                            f"unknown hook handle in interval: {row}"
                        )
                    event = {
                        **row,
                        "label": handle_labels[handle],
                        "interval_start_mame_tick": start_tick,
                        "interval_end_mame_tick": end_tick,
                        "terminal_cycle": terminal_cycle,
                        "in_half_open_interval": (
                            int(row.get("cycleCount", terminal_cycle))
                            < terminal_cycle
                        ),
                    }
                    interval_events.append(event)
                    all_events.append(event)

                boundary = capture_tool.capture(
                    m,
                    args.output,
                    end_tick,
                )
                boundaries.append(boundary)
                next_buttons = int(timeline[end_tick]["snes_buttons"])
                input_response = campaign.set_held_input(m, next_buttons)
                input_responses.append(
                    {
                        "mame_tick": end_tick,
                        "buttons": next_buttons,
                        "response": input_response,
                    }
                )
                intervals.append(
                    {
                        "start_mame_tick": start_tick,
                        "end_mame_tick": end_tick,
                        "controller_buttons": int(
                            timeline[start_tick]["snes_buttons"]
                        ),
                        "before_sa1_cycle": int(
                            before_cpu.get("cycleCount", 0)
                        ),
                        "after_sa1_cycle": terminal_cycle,
                        "sa1_cycles": (
                            terminal_cycle
                            - int(before_cpu.get("cycleCount", 0))
                        ),
                        "spans": spans,
                        "hook_diag_before": before_diag,
                        "hook_diag_after": after_diag,
                        "emitted_events": emitted,
                        "retained_events": len(interval_events),
                        "half_open_events": sum(
                            bool(row["in_half_open_interval"])
                            for row in interval_events
                        ),
                    }
                )
        finally:
            for handle in handle_labels:
                m.remove_hook(handle)
            m.drain_notifications(timeout=0.10)

    event_path = args.output / "events.jsonl"
    event_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in all_events
        ),
        encoding="utf-8",
    )
    summary = {
        "result": "green",
        "classification": "causal_exact_boundary_hook_trace",
        "scope": (
            (
                "forensic nested-SA1-entry controller continuation; "
                "not a resumable checkpoint; "
                if args.allow_forensic_nonresumable_state
                else "authenticated safe-checkpoint controller continuation; "
            )
            + "synchronous exact $003A92 interval fences; hook-count-complete "
            "observations; not fresh-boot or performance proof"
        ),
        "time_unix": time.time(),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "state_mame_tick": args.state_mame_tick,
        "allow_forensic_nonresumable_state": args.allow_forensic_nonresumable_state,
        "state_authentication": state_auth,
        "loaded_state_validation": loaded_validation,
        "load_response": load_response,
        "timeline": str(args.timeline),
        "timeline_sha256": sha256(args.timeline),
        "end_mame_tick": args.end_mame_tick,
        "gameplay_native": args.gameplay_native,
        "runtime_controls": runtime_controls,
        "emulator": str(args.nexen),
        "emulator_sha256": sha256(args.nexen),
        "hooks": {
            "exec": [
                {"label": label, "address": f"{address:06X}"}
                for label, address in args.exec_hook
            ],
            "write": [
                {
                    "label": label,
                    "start": f"{start:06X}",
                    "end": f"{end:06X}",
                }
                for label, start, end in args.write_hook
            ],
            "install_diag": install_diag,
        },
        "input_responses": input_responses,
        "boundaries": boundaries,
        "intervals": intervals,
        "event_log": str(event_path),
        "event_log_sha256": sha256(event_path),
        "event_count": len(all_events),
        "half_open_event_count": sum(
            bool(row["in_half_open_interval"]) for row in all_events
        ),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "output": str(summary_path),
                "intervals": len(intervals),
                "events": len(all_events),
                "half_open_events": summary["half_open_event_count"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
