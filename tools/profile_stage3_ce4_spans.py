#!/usr/bin/env python3
"""Non-pausing exact-emulator attribution of the native CE4 renderer in Stage 3.

This profiler deliberately does not require the diagnostic PC ring.  It loads
the retained Stage-3 checkpoint into an exact emulator, migrates only the
selected production ROM's video mirror/renderer metadata, normalizes the seven
documented production gates, and records cycle-stamped execution hooks between
real ``$00F5A3`` tick boundaries.

The result classifies every ``hce4_entry -> hce4_hot_done`` span by immutable
shape helper or generic loop.  It is checkpointed native-span attribution, not
FPS, fresh-boot proof, or a semantic differential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import measure_stage3_checkpoint as measure
import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = ROOT / "build/playtest/stage3.mss"
CLAMP = 0x00F5A3
EXPECTED_GATES = {
    "loop_072e": 1,
    "xlat_071a": 1,
    "pacing_0734": 1,
    "select_0736": 0x5EEC,
    "fetch_chokepoint_073a": 1,
    "switch_in_073c": 0xA55A,
    "production_latch_0768": 1,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(executable: Path) -> None:
    root = (
        "/home/chad/.dotnet10"
        if executable.name == "Nexen"
        else "/home/chad/.dotnet8"
    )
    other = (
        "/home/chad/.dotnet8"
        if executable.name == "Nexen"
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def symbols(path: Path, bank: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) < 2 or ":" not in fields[0]:
            continue
        result[fields[1]] = (
            (bank << 16) | int(fields[0].split(":", 1)[1], 16)
        )
    return result


def hook_map(detail: str) -> dict[str, int]:
    bank94 = symbols(ROOT / "src/escbank2.sym", 0x94)
    bank95 = symbols(ROOT / "src/escbank6.sym", 0x95)
    bank9d = symbols(ROOT / "src/escbank7.sym", 0x9D)
    bank9f = symbols(ROOT / "src/escbank9.sym", 0x9F)
    requested = {
        "hce4_entry": bank94,
        "hce4_guards_done": bank94,
        "hce4_outer_loop": bank94,
        "hce4_rows_done": bank94,
        "hce4_exit_exhausted": bank94,
        "hce4_hot_done": bank94,
        "hce4_cold": bank94,
        "hce4_shape_try": bank95,
        "hce4_shape_3762e": bank95,
        "hce4_shape_341c2": bank95,
        "hce4_shape_337f0": bank95,
        "hce4_shape_33c0a": bank95,
        "hce4_shape_428d6": bank95,
        "hce4_shape_4288a": bank95,
        "hce4_shape_finish": bank95,
        "hce4_shape_try_ext": bank9d,
        "hce4_ext_shape_33f6e": bank9d,
        "hce4_ext_shape_ca8e": bank9d,
        "hce4_ext_shape_3762e_hidden": bank9d,
        "hce4_ext_shape_42a": bank9d,
        "hce4_ext_shape_2x2": bank9d,
        "hce4_ext_exhausted": bank9d,
        "hce4_ext_fill": bank9d,
        "hce4_fast_render_2x2": bank9f,
        "hce4_stage3_panel_render": bank9f,
    }
    missing = [
        name for name, available in requested.items() if name not in available
    ]
    if missing:
        raise RuntimeError(f"missing CE4 symbols: {missing}")
    available_hooks = {
        name: available[name] for name, available in requested.items()
    }
    if detail == "core":
        selected = {
            "hce4_entry",
            "hce4_hot_done",
            "hce4_cold",
        }
    elif detail == "classify":
        # Do not hook the inner generic row/outer-loop labels here.  They can
        # fire often enough to make exact Nexen instrumentation dominate the
        # emulation.  A completed hot span that visits none of the immutable
        # shape labels is the generic path.
        selected = {
            "hce4_entry",
            "hce4_hot_done",
            "hce4_cold",
            "hce4_shape_3762e",
            "hce4_shape_341c2",
            "hce4_shape_337f0",
            "hce4_shape_33c0a",
            "hce4_shape_428d6",
            "hce4_shape_4288a",
            "hce4_ext_shape_33f6e",
            "hce4_ext_shape_ca8e",
            "hce4_ext_shape_3762e_hidden",
            "hce4_ext_shape_42a",
            "hce4_ext_shape_2x2",
            "hce4_fast_render_2x2",
            "hce4_stage3_panel_render",
        }
    else:
        selected = set(available_hooks)
    return {
        name: address
        for name, address in available_hooks.items()
        if name in selected
    }


def notifications(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        if row.get("method") == "notifications/mesen/hookFired":
            yield row.get("params", {})


def stats(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
        "sum": sum(values),
    }


def classify(labels: list[str]) -> str:
    priority = (
        "hce4_shape_3762e",
        "hce4_shape_341c2",
        "hce4_shape_337f0",
        "hce4_shape_33c0a",
        "hce4_shape_428d6",
        "hce4_shape_4288a",
        "hce4_ext_shape_33f6e",
        "hce4_ext_shape_ca8e",
        "hce4_ext_shape_3762e_hidden",
        "hce4_ext_shape_42a",
        "hce4_ext_shape_2x2",
        "hce4_fast_render_2x2",
        "hce4_stage3_panel_render",
    )
    for label in priority:
        if label in labels:
            return label
    if "hce4_outer_loop" in labels:
        return "generic_loop"
    if "hce4_cold" in labels:
        return "guard_fallback"
    return "generic_or_other_hot"


def analyze(
    clamp_events: list[dict[str, Any]],
    body_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    all_spans: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(
        zip(clamp_events, clamp_events[1:])
    ):
        start = int(left["cycleCount"])
        end = int(right["cycleCount"])
        inside = sorted(
            (
                event
                for event in body_events
                if start < int(event["cycleCount"]) < end
            ),
            key=lambda event: int(event["cycleCount"]),
        )
        spans: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        unmatched_ends = 0
        for event in inside:
            label = str(event["label"])
            cycle = int(event["cycleCount"])
            if label == "hce4_entry":
                if pending is not None:
                    pending["status"] = "unmatched_start"
                    spans.append(pending)
                pending = {
                    "start_cycle": cycle,
                    "labels": [label],
                    "status": "pending",
                }
                continue
            if pending is None:
                if label in ("hce4_hot_done", "hce4_cold"):
                    unmatched_ends += 1
                continue
            pending["labels"].append(label)
            if label in ("hce4_hot_done", "hce4_cold"):
                pending.update(
                    {
                        "end_cycle": cycle,
                        "cycles": cycle - int(pending["start_cycle"]),
                        "classification": classify(pending["labels"]),
                        "status": (
                            "complete"
                            if label == "hce4_hot_done"
                            else "fallback"
                        ),
                    }
                )
                spans.append(pending)
                pending = None
        if pending is not None:
            pending["status"] = "unmatched_start"
            spans.append(pending)
        complete = [
            span for span in spans if span.get("cycles") is not None
        ]
        interval = {
            "index": index,
            "start_cycle": start,
            "end_cycle": end,
            "total_cycles": end - start,
            "ce4_span_cycles": sum(
                int(span["cycles"]) for span in complete
            ),
            "ce4_calls": len(complete),
            "classifications": dict(
                Counter(
                    str(span["classification"]) for span in complete
                )
            ),
            "unmatched_starts": sum(
                span["status"] == "unmatched_start" for span in spans
            ),
            "unmatched_ends": unmatched_ends,
            "spans": spans,
        }
        intervals.append(interval)
        all_spans.extend(complete)

    by_class: dict[str, list[int]] = defaultdict(list)
    for span in all_spans:
        by_class[str(span["classification"])].append(int(span["cycles"]))
    count = max(1, len(intervals))
    aggregate = {
        "ticks": len(intervals),
        "tick_cycles": stats(
            [int(interval["total_cycles"]) for interval in intervals]
        ),
        "ce4_span_cycles_per_tick": (
            sum(int(span["cycles"]) for span in all_spans) / count
        ),
        "ce4_calls_per_tick": len(all_spans) / count,
        "classifications": {
            label: {
                "cycles": stats(values),
                "cycles_per_tick": sum(values) / count,
                "calls_per_tick": len(values) / count,
            }
            for label, values in sorted(by_class.items())
        },
        "unmatched_starts": sum(
            int(interval["unmatched_starts"]) for interval in intervals
        ),
        "unmatched_ends": sum(
            int(interval["unmatched_ends"]) for interval in intervals
        ),
    }
    return intervals, aggregate


def analyze_ordered(
    clamp_events: list[dict[str, Any]],
    body_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Classify calls when an emulator omits per-hook cycle timestamps."""

    intervals: list[dict[str, Any]] = []
    all_complete: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(
        zip(clamp_events, clamp_events[1:])
    ):
        start = int(left["ordinal"])
        end = int(right["ordinal"])
        inside = sorted(
            (
                event
                for event in body_events
                if start < int(event["ordinal"]) < end
            ),
            key=lambda event: int(event["ordinal"]),
        )
        spans: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        unmatched_ends = 0
        for event in inside:
            label = str(event["label"])
            ordinal = int(event["ordinal"])
            if label == "hce4_entry":
                if pending is not None:
                    pending["status"] = "unmatched_start"
                    spans.append(pending)
                pending = {
                    "start_ordinal": ordinal,
                    "labels": [label],
                    "status": "pending",
                }
                continue
            if pending is None:
                if label in ("hce4_hot_done", "hce4_cold"):
                    unmatched_ends += 1
                continue
            pending["labels"].append(label)
            if label in ("hce4_hot_done", "hce4_cold"):
                pending.update(
                    {
                        "end_ordinal": ordinal,
                        "classification": classify(pending["labels"]),
                        "status": (
                            "complete"
                            if label == "hce4_hot_done"
                            else "fallback"
                        ),
                    }
                )
                spans.append(pending)
                all_complete.append(pending)
                pending = None
        if pending is not None:
            pending["status"] = "unmatched_start"
            spans.append(pending)
        intervals.append(
            {
                "index": index,
                "start_ordinal": start,
                "end_ordinal": end,
                "ce4_calls": len(
                    [span for span in spans if "end_ordinal" in span]
                ),
                "classifications": dict(
                    Counter(
                        str(span["classification"])
                        for span in spans
                        if "classification" in span
                    )
                ),
                "unmatched_starts": sum(
                    span["status"] == "unmatched_start" for span in spans
                ),
                "unmatched_ends": unmatched_ends,
                "spans": spans,
            }
        )

    count = max(1, len(intervals))
    class_counts = Counter(
        str(span["classification"]) for span in all_complete
    )
    aggregate = {
        "ticks": len(intervals),
        "hook_timing": "ordered_only_no_cycle_stamps",
        "ce4_calls_per_tick": len(all_complete) / count,
        "classifications": {
            label: {
                "count": occurrences,
                "calls_per_tick": occurrences / count,
            }
            for label, occurrences in sorted(class_counts.items())
        },
        "unmatched_starts": sum(
            int(interval["unmatched_starts"]) for interval in intervals
        ),
        "unmatched_ends": sum(
            int(interval["unmatched_ends"]) for interval in intervals
        ),
    }
    return intervals, aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--emulator",
        type=Path,
        default=base.DEFAULT_NEXEN,
        help=(
            "exact emulator binary or MCP controller; the project Nexen is "
            "the default"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9340)
    parser.add_argument("--ticks", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--detail",
        choices=("core", "classify", "full"),
        default="core",
        help=(
            "core records only entry/exit timing; classify adds low-frequency "
            "shape labels; full also hooks hot inner-loop seams"
        ),
    )
    args = parser.parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.emulator = args.emulator.resolve()
    args.output = args.output.resolve()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("emulator", args.emulator),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.ticks < 1 or args.timeout <= 0:
        parser.error("--ticks and --timeout must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    rom = args.rom.read_bytes()
    if len(rom) != 4 * 1024 * 1024:
        parser.error("ROM must be exactly 4 MiB")
    if int.from_bytes(rom[0x77E0:0x77E2], "little") != 0:
        parser.error("TESTFLAG must be zero")

    hooks = {"clamp": CLAMP, **hook_map(args.detail)}
    result: dict[str, Any] = {
        "scope": (
            "checkpointed exact-emulator non-pausing Stage-3 native CE4 span "
            "attribution; not fps, fresh-boot proof, or semantic evidence"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator),
        "emulator_sha256": sha256(args.emulator),
        "hook_addresses": {
            name: f"{address:06X}" for name, address in hooks.items()
        },
        "requested_ticks": args.ticks,
        "detail": args.detail,
        "interventions": [],
        "time": time.time(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = args.output.with_suffix(".emulator.stderr.log")
    configure_dotnet(args.emulator)

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.emulator),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=max(240.0, args.timeout + 30.0),
        stderr_log=stderr_log,
    ) as session:
        session.pause()
        result["load_state_response"] = session.load_state(str(args.state))
        session.pause()
        result["interventions"].extend(
            measure.migrate_checkpoint_video(session, rom)
        )
        gates_before = measure.gates(session)
        for name, address in measure.GATE_ADDRS.items():
            measure.write_u16(session, address, EXPECTED_GATES[name])
        gates_after = measure.gates(session)
        if gates_after != EXPECTED_GATES:
            raise RuntimeError(
                f"production gate normalization failed: {gates_after}"
            )
        result["interventions"].append(
            {
                "kind": "checkpoint_production_gate_normalization",
                "before": gates_before,
                "after": gates_after,
            }
        )
        handles = {
            label: session.add_exec_hook(address, cpu_type="Sa1")
            for label, address in hooks.items()
        }
        by_handle = {handle: label for label, handle in handles.items()}
        session.drain_notifications(timeout=0.05)
        clamp_events: list[dict[str, Any]] = []
        body_events: list[dict[str, Any]] = []
        event_ordinal = 0
        started = time.monotonic()
        session.resume()
        try:
            while (
                len(clamp_events) < args.ticks + 1
                and time.monotonic() - started < args.timeout
            ):
                rows = session.drain_notifications(timeout=0.25)
                for params in notifications(rows):
                    label = by_handle.get(int(params.get("handle", -1)))
                    if label is None:
                        continue
                    event_ordinal += 1
                    event = {
                        **params,
                        "label": label,
                        "ordinal": event_ordinal,
                    }
                    if label == "clamp":
                        clamp_events.append(event)
                    else:
                        body_events.append(event)
                time.sleep(0.005)
        finally:
            session.pause()
            for handle in handles.values():
                session.remove_hook(handle)
        if len(clamp_events) < args.ticks + 1:
            raise TimeoutError(
                f"captured {len(clamp_events)}/{args.ticks + 1} tick hooks "
                f"in {time.monotonic() - started:.1f}s"
            )
        result["wall_seconds_informational"] = time.monotonic() - started
        result["end_gates"] = measure.gates(session)
        result["halt"] = measure.read_u16(session, 0x004E)

    cycle_stamped = all(
        "cycleCount" in event for event in [*clamp_events, *body_events]
    )
    if cycle_stamped:
        clamp_events.sort(key=lambda event: int(event["cycleCount"]))
        body_events.sort(key=lambda event: int(event["cycleCount"]))
        intervals, aggregate = analyze(
            clamp_events[: args.ticks + 1], body_events
        )
        aggregate["hook_timing"] = "cycle_stamped"
    else:
        clamp_events.sort(key=lambda event: int(event["ordinal"]))
        body_events.sort(key=lambda event: int(event["ordinal"]))
        intervals, aggregate = analyze_ordered(
            clamp_events[: args.ticks + 1], body_events
        )
    result["intervals"] = intervals
    result["aggregate"] = aggregate
    result["result"] = (
        "green"
        if result["end_gates"] == EXPECTED_GATES
        and result["halt"] == 0
        and aggregate["ticks"] == args.ticks
        and aggregate["unmatched_starts"] == 0
        and aggregate["unmatched_ends"] == 0
        else "red"
    )
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": result["result"],
                "rom_sha256": result["rom_sha256"],
                "aggregate": aggregate,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
