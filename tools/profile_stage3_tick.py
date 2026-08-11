#!/usr/bin/env python3
"""Attribute complete Stage-3 gameplay ticks at the real interpreter fetch seam.

This is a checkpointed exact-Mesen diagnostic, not FPS or fresh-boot evidence.
It loads a caller-supplied state, optionally migrates the selected ROM's renderer
mirror, advances to the next real ``$00:F5A3`` tick boundary, and then stops at
``lh_off`` for every genuinely interpreted MC68000 instruction.  Consecutive
SA-1 cycle counts charge native spans, waits, IRQ work, and interpreter work to
the MC68000 PC that triggered them.

Unlike the PC-ring profiler, this method perturbs wall-clock execution by
pausing at each fetch.  Emulated SA-1 cycle deltas remain useful for hotspot
selection, but the result is neither an uninterrupted cadence measurement nor
an end-to-end performance claim.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from capstone import CS_ARCH_M68K, CS_MODE_BIG_ENDIAN, Cs


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import measure_stage3_checkpoint as stage3
import trace_playtest_actions as trace


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = ROOT / "build/playtest/stage3.mss"
DEFAULT_MESEN = ROOT / "tools/mesen211_mcp_controller.sh"
DEFAULT_OUTPUT = ROOT / "build/stage3-tick-profile"

TICK_BOUNDARY = 0x00F5A3
LH_OFF = 0x0080FB
EXPECTED_GATES = {
    "loop_072e": 1,
    "xlat_071a": 1,
    "pacing_0734": 1,
    "select_0736": 0x5EEC,
    "fetch_chokepoint_073a": 1,
    "switch_in_073c": 0xA55A,
    "production_latch_0768": 1,
}
MAX_FETCHES_PER_TICK = 20_000

# Native bank-$98 addresses for the guarded fusion entered by the bank-$99
# $02429C task body. These hooks are checkpoint-profiler diagnostics only;
# they do not modify production code or state.
TASK_2429C_HOOKS = {
    "h2429c_empty_helpers_entry": 0x988E53,
    "h2429c_empty_helpers_check": 0x988E5B,
    "h2429c_empty_helpers_hit": 0x988EC3,
    "h2429c_empty_helpers_miss": 0x988EE9,
}

# Entry and branch landmarks for the $025110 collision routine.  These are
# profiling-only execution hooks: they make no changes to the live ROM or
# state.  The paced generated Stage-1 path is deliberately separate from the
# compact Stage-2 continuation because the former must retain interruptible
# logical-instruction cadence.
COLLISION_25110_HOOKS = {
    "h25110_entry": 0x978000,
    "h25110_native_guard_accept": 0x97E5D5,
    "h25110_native_guard_reject": 0x97E5D7,
    "h25110_interpreter_fallback": 0x978020,
    # The packed preamble intentionally bypasses the diagnostic counter at
    # $978002; byte-audit the resulting BRA target rather than relying on the
    # source-label offset before that packing pass.
    "h25110_canonical_entry": 0x97802E,
    "h25110_stage4_start": 0x9794BD,
    "h25110_stage5_select": 0x97963F,
    "h25110_stage5_wide": 0x97966C,
    "h25110_paced_generated_stage1": 0x95F3E0,
    "h25110_stage2_try": 0x9D8000,
    "h25110_stage2_fallback": 0x9D8117,
    "h25110_stage2_overlap": 0x9DE800,
}

# The two bounded object-pool scans are generated static-call bodies in bank
# $9D. These hooks prove that real gameplay reaches the currently accepted
# scanner implementations.
POOL_SCANNER_HOOKS = {
    "pool_2498c_entry": 0x9DB000,
    "pool_249c2_entry": 0x9DB800,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=9166)
    parser.add_argument("--ticks", type=int, default=3)
    parser.add_argument("--top", type=int, default=160)
    parser.add_argument(
        "--trace-ce4-shapes",
        action="store_true",
        help=(
            "also classify the low-frequency native $000CE4 renderer paths "
            "visited between consecutive interpreted-fetch stops"
        ),
    )
    parser.add_argument(
        "--trace-2429c-path",
        action="store_true",
        help=(
            "classify the guarded $02429C no-work-helper fusion between "
            "consecutive interpreted-fetch stops"
        ),
    )
    parser.add_argument(
        "--trace-25110-path",
        action="store_true",
        help=(
            "count the native $025110 collision entry, paced Stage-1, and "
            "guarded Stage-2 branches between interpreted-fetch stops"
        ),
    )
    parser.add_argument(
        "--trace-pool-scanners",
        action="store_true",
        help=(
            "count real Stage-3 entries into the $02498C/$0249C2 native "
            "object-pool scanner bodies"
        ),
    )
    parser.add_argument(
        "--no-refresh-video-mirror",
        action="store_true",
        help="Do not migrate the selected ROM's video mirror/renderer metadata.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(executable: Path) -> None:
    """Select the runtime required by the requested MCP emulator.

    The legacy Mesen wrapper is a .NET 8 executable, whereas the supported
    Nexen oracle is a .NET 10 publish.  This profiler originally hard-coded
    the former, which made a Nexen profile fail before it could load the
    authenticated checkpoint.
    """

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


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def cpu_cycles(m: trace.McpSession) -> int:
    return int(m.get_cpu_state("Sa1").get("cycleCount", 0))


def r16(m: trace.McpSession, address: int) -> int:
    return trace.le16(m.read_memory("Sa1Memory", address, 2))


def r32(m: trace.McpSession, address: int) -> int:
    return trace.le32(m.read_memory("Sa1Memory", address, 4))


def point(m: trace.McpSession) -> dict[str, int]:
    state = m.get_state()
    return {
        "cycles": cpu_cycles(m),
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(m, 0x0760),
        "pc": r32(m, 0x0040) & 0xFFFFFF,
        "halt": r16(m, 0x004E),
    }


def collision_records(
    m: trace.McpSession, start: int, count: int
) -> list[dict[str, int | str]]:
    """Read the non-mutating collision fields of consecutive 68000 records."""

    raw = m.read_memory("snesMemory", 0x400000 + start, count * 16)
    records: list[dict[str, int | str]] = []
    for index in range(count):
        offset = index * 16
        word = lambda at: int.from_bytes(raw[offset + at : offset + at + 2], "big")
        records.append(
            {
                "record": f"F0{start + offset:04X}",
                "active": word(0),
                "type": word(10),
                "response": word(14),
            }
        )
    return records


def production_gates(m: trace.McpSession) -> dict[str, int]:
    return {
        name: r16(m, address)
        for name, address in stage3.GATE_ADDRS.items()
    }


def instruction_text(rom: bytes, pc: int, md: Cs) -> str:
    offset = 0x10000 + pc
    if not 0 <= offset < len(rom):
        return "outside retained MC68000 image"
    instruction = next(md.disasm(rom[offset : offset + 10], pc), None)
    if instruction is None:
        return "undecodable"
    return " ".join(
        part for part in (instruction.mnemonic, instruction.op_str) if part
    )


def summarize(
    intervals: list[dict[str, Any]], rom: bytes, top: int
) -> dict[str, Any]:
    cycles: collections.Counter[int] = collections.Counter()
    fires: collections.Counter[int] = collections.Counter()
    for interval in intervals:
        for event in interval["events"]:
            pc = int(event["pc"])
            cycles[pc] += int(event["cycles"])
            fires[pc] += 1

    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    rows = [
        {
            "pc": f"{pc:06X}",
            "cycles": cost,
            "cycles_per_tick": cost / len(intervals),
            "fires": fires[pc],
            "fires_per_tick": fires[pc] / len(intervals),
            "average_cycles": cost / fires[pc],
            "instruction": instruction_text(rom, pc, md),
        }
        for pc, cost in cycles.most_common(top)
    ]
    totals = [int(interval["total_cycles"]) for interval in intervals]
    frames = [
        int(interval["end"]["frame"]) - int(interval["start"]["frame"])
        for interval in intervals
    ]
    fetches = [len(interval["events"]) for interval in intervals]
    return {
        "ticks": len(intervals),
        "total_attributed_cycles": sum(totals),
        "cycles_per_tick": sum(totals) / len(totals),
        "frames_per_tick": sum(frames) / len(frames),
        "genuinely_interpreted_fetches_per_tick": sum(fetches) / len(fetches),
        "rows": rows,
    }


def main() -> int:
    args = parse_args()
    if args.ticks < 1 or args.top < 1:
        raise SystemExit("--ticks and --top must be positive")
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.mesen = args.mesen.resolve()
    args.output = args.output.resolve()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    configure_dotnet(args.mesen)
    rom = args.rom.read_bytes()
    if len(rom) != 4 * 1024 * 1024:
        raise SystemExit(f"expected a 4 MiB ROM, got {len(rom)} bytes")
    if int.from_bytes(rom[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("TESTFLAG must be zero")

    result: dict[str, Any] = {
        "scope": (
            "exact-Mesen production-ROM complete Stage-3 tick fetch-boundary "
            "attribution; checkpointed and stop-by-stop; not fps, uninterrupted "
            "cadence, or fresh-boot evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "mesen": str(args.mesen),
        "mesen_sha256": sha256(args.mesen),
        "tick_hook": f"{TICK_BOUNDARY:06X}",
        "fetch_hook": f"{LH_OFF:06X}",
        "interventions": [],
    }

    with trace.McpSession(
        rom=args.rom,
        mesen=args.mesen,
        cwd=ROOT,
        port=args.port,
        boot_wait=5.0,
        socket_timeout=300.0,
        stderr_log=args.output / "mesen.stderr.log",
    ) as m:
        m.pause()
        result["load_state_response"] = m.load_state(args.state)
        m.pause()
        if not args.no_refresh_video_mirror:
            result["interventions"].extend(
                stage3.migrate_checkpoint_video(m, rom)
            )

        before_gates = production_gates(m)
        if before_gates != EXPECTED_GATES:
            raise RuntimeError(
                f"checkpoint production gates mismatch: {before_gates} "
                f"!= {EXPECTED_GATES}"
            )
        if r16(m, 0x004E):
            raise RuntimeError("checkpoint interpreter is halted")

        # Establish neutral real-controller state before choosing the next full
        # boundary.  This is a one-frame organic advance, not a game-state poke.
        input_before = int(m.get_state().get("frameCount", 0))
        input_response = m.set_input(0, 1)
        m.pause()
        result["neutral_input_sync"] = {
            "frame_before": input_before,
            "frame_after": int(m.get_state().get("frameCount", 0)),
            "response": input_response,
        }

        tick_handle = m.add_exec_hook(TICK_BOUNDARY, cpu_type="Sa1")
        sync_response = m.run_until(max_frames=240, hook_handle=tick_handle)
        m.pause()
        m.remove_hook(tick_handle)
        if sync_response.get("reason") != "hookFired":
            raise RuntimeError(f"failed to reach tick boundary: {sync_response}")
        sync = point(m)
        if sync["halt"]:
            raise RuntimeError("interpreter halted at tick synchronization")
        result["sync"] = sync
        result["pre_tick_collision_records"] = {
            # $25774's 12-by-4 Stage-4 grid and the two Stage-5 outer
            # ranges.  This read is observational only and makes any future
            # compaction claim reviewable against the actual Stage-3 shape.
            "stage4_outer_and_stage5_narrow": collision_records(
                m, 0x3734, 12
            ),
            "stage4_inner": collision_records(m, 0x3C74, 4),
            "stage5_wide_outer": collision_records(m, 0x37F4, 32),
        }
        result["pre_tick_state"] = trace.save_state(
            m, args.output / "pre-tick.mss"
        )

        fetch_handle = m.add_exec_hook(LH_OFF, cpu_type="Sa1")
        trace_handles: dict[int, str] = {}
        if args.trace_ce4_shapes:
            from profile_stage3_ce4_spans import hook_map

            trace_handles.update({
                m.add_exec_hook(address, cpu_type="Sa1"): label
                for label, address in hook_map("classify").items()
            })
            m.drain_notifications(timeout=0.05)
            result["ce4_trace_hooks"] = {
                label: f"{address:06X}"
                for label, address in hook_map("classify").items()
            }
        if args.trace_2429c_path:
            trace_handles.update({
                m.add_exec_hook(address, cpu_type="Sa1"): label
                for label, address in TASK_2429C_HOOKS.items()
            })
            m.drain_notifications(timeout=0.05)
            result["2429c_trace_hooks"] = {
                label: f"{address:06X}"
                for label, address in TASK_2429C_HOOKS.items()
            }
        if args.trace_25110_path:
            trace_handles.update({
                m.add_exec_hook(address, cpu_type="Sa1"): label
                for label, address in COLLISION_25110_HOOKS.items()
            })
            m.drain_notifications(timeout=0.05)
            result["25110_trace_hooks"] = {
                label: f"{address:06X}"
                for label, address in COLLISION_25110_HOOKS.items()
            }
        if args.trace_pool_scanners:
            trace_handles.update({
                m.add_exec_hook(address, cpu_type="Sa1"): label
                for label, address in POOL_SCANNER_HOOKS.items()
            })
            m.drain_notifications(timeout=0.05)
            result["pool_scanner_trace_hooks"] = {
                label: f"{address:06X}"
                for label, address in POOL_SCANNER_HOOKS.items()
            }
        intervals: list[dict[str, Any]] = []
        start = sync
        previous = sync
        events: list[dict[str, int]] = []
        try:
            while len(intervals) < args.ticks:
                response = m.run_until(max_frames=240, hook_handle=fetch_handle)
                m.pause()
                if response.get("reason") != "hookFired":
                    failure = point(m)
                    result["fetch_failure"] = {
                        "after_complete_ticks": len(intervals),
                        "current_events": len(events),
                        "response": response,
                        "point": failure,
                        "state": trace.save_state(
                            m, args.output / "fetch-failure.mss"
                        ),
                        "gates": production_gates(m),
                    }
                    (args.output / "profile-failure.json").write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n"
                    )
                    raise RuntimeError(
                        "lost lh_off fetch hook after "
                        f"{len(intervals)} ticks/{len(events)} current fetches: "
                        f"{response}"
                    )
                native_labels = [
                    trace_handles[int(row.get("params", {}).get("handle", -1))]
                    for row in m.drain_notifications(timeout=0.01)
                    if row.get("method") == "notifications/mesen/hookFired"
                    and int(row.get("params", {}).get("handle", -1))
                    in trace_handles
                ]
                current = point(m)
                gap = current["cycles"] - previous["cycles"]
                if gap < 0:
                    raise RuntimeError("SA-1 cycle count moved backwards")
                event = {"pc": previous["pc"], "cycles": gap}
                if native_labels:
                    event["native_labels"] = native_labels
                events.append(event)
                if current["halt"]:
                    raise RuntimeError(
                        f"interpreter halted at MC68000 ${current['pc']:06X}"
                    )
                if current["tick"] != start["tick"]:
                    intervals.append(
                        {
                            "index": len(intervals),
                            "start": start,
                            "end": current,
                            "total_cycles": current["cycles"] - start["cycles"],
                            "events": events,
                        }
                    )
                    start = current
                    events = []
                elif len(events) > MAX_FETCHES_PER_TICK:
                    raise RuntimeError(
                        f"more than {MAX_FETCHES_PER_TICK} fetches without a tick"
                    )
                previous = current
        finally:
            m.remove_hook(fetch_handle)
            for handle in trace_handles:
                m.remove_hook(handle)

        result["end"] = point(m)
        result["end_state"] = trace.save_state(
            m, args.output / "end.mss"
        )
        result["end_gates"] = production_gates(m)
        if result["end_gates"] != EXPECTED_GATES:
            raise RuntimeError("production gates changed during attribution")
        result["intervals"] = intervals

    result.update(summarize(result["intervals"], rom, args.top))
    if args.trace_ce4_shapes:
        ce4_paths: collections.Counter[str] = collections.Counter()
        ce4_cycles: collections.Counter[str] = collections.Counter()
        for interval in result["intervals"]:
            for event in interval["events"]:
                if int(event["pc"]) != 0x000CE4:
                    continue
                labels = list(event.get("native_labels", []))
                path = next(
                    (
                        label
                        for label in labels
                        if label
                        not in ("hce4_entry", "hce4_hot_done", "hce4_cold")
                    ),
                    "guard_fallback"
                    if "hce4_cold" in labels
                    else "generic_or_other_hot",
                )
                ce4_paths[path] += 1
                ce4_cycles[path] += int(event["cycles"])
        result["ce4_path_attribution"] = [
            {
                "path": path,
                "fires": ce4_paths[path],
                "fires_per_tick": ce4_paths[path] / len(result["intervals"]),
                "cycles": ce4_cycles[path],
                "cycles_per_tick": (
                    ce4_cycles[path] / len(result["intervals"])
                ),
                "average_cycles": ce4_cycles[path] / ce4_paths[path],
            }
            for path, _count in ce4_paths.most_common()
        ]
    if args.trace_2429c_path:
        task_hooks: collections.Counter[str] = collections.Counter()
        for interval in result["intervals"]:
            for event in interval["events"]:
                for label in event.get("native_labels", []):
                    if label.startswith("h2429c_empty_helpers_"):
                        task_hooks[label] += 1
        entries = task_hooks["h2429c_empty_helpers_entry"]
        hits = task_hooks["h2429c_empty_helpers_hit"]
        misses = task_hooks["h2429c_empty_helpers_miss"]
        result["2429c_fusion"] = {
            "hook_counts": dict(sorted(task_hooks.items())),
            "entries": entries,
            "hits": hits,
            "misses": misses,
            "every_observed_entry_hit": entries > 0 and hits == entries,
        }
    if args.trace_25110_path:
        collision_hooks: collections.Counter[str] = collections.Counter()
        for interval in result["intervals"]:
            for event in interval["events"]:
                for label in event.get("native_labels", []):
                    if label.startswith("h25110_"):
                        collision_hooks[label] += 1
        result["25110_path"] = {
            "hook_counts": dict(sorted(collision_hooks.items())),
            "entries": collision_hooks["h25110_entry"],
            "native_guard_accept": collision_hooks[
                "h25110_native_guard_accept"
            ],
            "native_guard_reject": collision_hooks[
                "h25110_native_guard_reject"
            ],
            "interpreter_fallback": collision_hooks[
                "h25110_interpreter_fallback"
            ],
            "paced_generated_stage1": collision_hooks[
                "h25110_paced_generated_stage1"
            ],
            "stage4_start": collision_hooks["h25110_stage4_start"],
            "stage5_select": collision_hooks["h25110_stage5_select"],
            "stage5_wide": collision_hooks["h25110_stage5_wide"],
            "stage2_try": collision_hooks["h25110_stage2_try"],
            "stage2_fallback": collision_hooks["h25110_stage2_fallback"],
            "stage2_overlap": collision_hooks["h25110_stage2_overlap"],
        }
    if args.trace_pool_scanners:
        pool_hooks: collections.Counter[str] = collections.Counter()
        for interval in result["intervals"]:
            for event in interval["events"]:
                for label in event.get("native_labels", []):
                    if label.startswith("pool_24"):
                        pool_hooks[label] += 1
        result["pool_scanners"] = {
            "hook_counts": dict(sorted(pool_hooks.items())),
            "2498c_entries": pool_hooks["pool_2498c_table_entry"],
            "249c2_entries": pool_hooks["pool_249c2_table_entry"],
            "both_entries_observed": (
                pool_hooks["pool_2498c_table_entry"] > 0
                and pool_hooks["pool_249c2_table_entry"] > 0
            ),
        }
    output = args.output / "profile.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "rom_sha256": result["rom_sha256"],
                "ticks": result["ticks"],
                "cycles_per_tick": result["cycles_per_tick"],
                "frames_per_tick": result["frames_per_tick"],
                "fetches_per_tick": result[
                    "genuinely_interpreted_fetches_per_tick"
                ],
                "top": result["rows"][:20],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
