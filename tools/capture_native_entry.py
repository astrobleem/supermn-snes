#!/usr/bin/env python3
"""Capture an organically reached SA-1 native entry from a production checkpoint.

The harness loads an existing organically armed save state, applies controller
input through Nexen's port API, and stops on an SA-1 execution hook.  It never
writes emulated RAM, registers, gates, or scheduler state.  The result is
checkpointed entry-state evidence, never an end-to-end fps measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

from capture_start_transition import snapshot
from profile_tick_ring import CLAMP, EXPECTED_CLAMP_BYTES, EXPECTED_GATES


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--entry", type=parse_int, required=True)
    parser.add_argument(
        "--guard-anchor",
        type=parse_int,
        help="distinct post-guard execution PC used to associate the preceding A7 reads",
    )
    parser.add_argument(
        "--guard-write-anchor",
        type=parse_int,
        help="distinct post-guard SA-1 write address used as the stop hook",
    )
    parser.add_argument(
        "--select-last-guard",
        action="store_true",
        help="select the last complete guard signature retained after the entry stop",
    )
    parser.add_argument(
        "--association-write",
        type=parse_int,
        help="observe a target-specific SA-1 write after the guard without stopping on it",
    )
    parser.add_argument("--association-write-end", type=parse_int)
    parser.add_argument("--association-value", type=parse_int)
    parser.add_argument("--association-value-mask", type=parse_int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7579)
    parser.add_argument("--buttons", type=parse_int, default=0)
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=0,
        help=(
            "advance this many real $00:F5A3 production tick boundaries before "
            "arming the native-entry hook"
        ),
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help=(
            "save prepared.mss immediately after the requested warmup and exit; "
            "used with exact-entry spin labs that cannot themselves warm up"
        ),
    )
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def configure_dotnet(executable: Path) -> None:
    root = "/home/chad/.dotnet10" if executable.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if executable.name == "Nexen" else "/home/chad/.dotnet10"
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["DOTNET_ROOT"] = root
    os.environ["PATH"] = ":".join([root, other, *current])


def current_sa1_pc(session: McpSession) -> int:
    state = session.get_cpu_state("Sa1")
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)


def hook_params(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def main() -> int:
    args = parse_args()
    rom = args.rom.resolve()
    state_path = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state_path), ("Nexen", nexen)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if not 0 <= args.entry <= 0xFFFFFF:
        raise SystemExit("--entry must be a 24-bit address")
    if args.guard_anchor is not None and args.guard_write_anchor is not None:
        raise SystemExit("choose only one of --guard-anchor and --guard-write-anchor")
    if args.select_last_guard and (
        args.guard_anchor is not None or args.guard_write_anchor is not None
    ):
        raise SystemExit("--select-last-guard cannot be combined with an anchor")
    if args.association_write_end is not None and args.association_write is None:
        raise SystemExit("--association-write-end requires --association-write")
    if args.association_value is not None and args.association_write is None:
        raise SystemExit("--association-value requires --association-write")
    if args.max_frames <= 0 or args.timeout <= 0:
        raise SystemExit("--max-frames and --timeout must be positive")
    if args.warmup_ticks < 0:
        raise SystemExit("--warmup-ticks cannot be negative")
    if args.prepare_only and not args.warmup_ticks:
        raise SystemExit("--prepare-only requires --warmup-ticks")

    rom_data = rom.read_bytes()
    if len(rom_data) != 0x400000:
        raise SystemExit(f"expected a 4 MiB ROM: {rom}")
    testflag = int.from_bytes(rom_data[0x77E0:0x77E2], "little")
    if testflag != 0:
        raise SystemExit(f"TESTFLAG must be zero, got {testflag:#06x}")
    if rom_data[0x75A3:0x75A6] != EXPECTED_CLAMP_BYTES:
        raise SystemExit("real $0818 tick-hook bytes do not match this harness")

    output.mkdir(parents=True, exist_ok=False)
    log_path = output / "capture.jsonl"
    stderr_path = output / "nexen.stderr.log"
    configure_dotnet(nexen)

    rows: list[dict[str, Any]] = []

    def emit(event: str, **fields: Any) -> None:
        row = {"event": event, "time": time.time(), **fields}
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    emit(
        "provenance",
        scope="organic native-entry checkpoint capture; not fps",
        project_commit=git_value("rev-parse", "HEAD"),
        project_status=git_value("status", "--short").splitlines(),
        rom=str(rom),
        rom_sha256=sha256(rom),
        state=str(state_path),
        state_sha256=sha256(state_path),
        nexen=str(nexen),
        nexen_sha256=sha256(nexen),
        testflag=testflag,
        entry=f"{args.entry:06X}",
        guard_anchor=(
            f"{args.guard_anchor:06X}" if args.guard_anchor is not None else None
        ),
        guard_write_anchor=(
            f"{args.guard_write_anchor:06X}"
            if args.guard_write_anchor is not None
            else None
        ),
        select_last_guard=args.select_last_guard,
        association_write=(
            f"{args.association_write:06X}"
            if args.association_write is not None
            else None
        ),
        association_write_end=(
            f"{args.association_write_end:06X}"
            if args.association_write_end is not None
            else None
        ),
        association_value=args.association_value,
        association_value_mask=args.association_value_mask,
        stop_hook=(
            f"write:{args.guard_write_anchor:06X}"
            if args.guard_write_anchor is not None
            else f"exec:{args.guard_anchor:06X}"
            if args.guard_anchor is not None
            else f"exec:{args.entry:06X}"
        ),
        buttons=args.buttons,
        warmup_ticks=args.warmup_ticks,
        prepare_only=args.prepare_only,
        input_transport="nexen_port0_manual_4016",
        runtime_memory_pokes=[],
    )

    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr_path,
    ) as session:
        session.pause()
        session.load_state(state_path)
        session.pause()
        before = snapshot(session)
        if before["gates"] != EXPECTED_GATES or before["halt"] != 0:
            raise RuntimeError(f"checkpoint is not healthy: {before}")
        emit("capture_start", **before)

        session.tool(
            "set_input", {"port": 0, "buttons": args.buttons, "hold": True}
        )
        if args.warmup_ticks:
            warmup_hook = session.add_exec_hook(CLAMP, cpu_type="Sa1")
            session.drain_notifications(timeout=0.05)
            warmup_started = time.monotonic()
            observed_ticks = 0
            session.resume()
            try:
                while time.monotonic() - warmup_started < args.timeout:
                    for params in hook_params(
                        session.drain_notifications(timeout=0.25)
                    ):
                        if int(params.get("handle", -1)) == warmup_hook:
                            observed_ticks += 1
                    if observed_ticks >= args.warmup_ticks:
                        session.pause()
                        break
                    time.sleep(0.01)
                else:
                    session.pause()
                    raise TimeoutError(
                        "native-entry warmup timed out after "
                        f"{args.timeout:.1f} seconds"
                    )
            finally:
                session.remove_hook(warmup_hook)
                session.drain_notifications(timeout=0.05)
            emit(
                "warmup_finished",
                requested_ticks=args.warmup_ticks,
                observed_tick_hooks=observed_ticks,
                wall_seconds=time.monotonic() - warmup_started,
                **snapshot(session),
            )
            if args.prepare_only:
                prepared_state = output / "prepared.mss"
                session.save_state(prepared_state)
                emit(
                    "prepared_state",
                    state=str(prepared_state),
                    state_sha256=sha256(prepared_state),
                    **snapshot(session),
                )
                with log_path.open("x", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, sort_keys=True) + "\n")
                return 0
        anchored = args.guard_anchor is not None or args.guard_write_anchor is not None
        if args.guard_write_anchor is not None:
            hook = session.add_write_hook(args.guard_write_anchor, cpu_type="Sa1")
        else:
            stop_address = (
                args.guard_anchor if args.guard_anchor is not None else args.entry
            )
            hook = session.add_exec_hook(stop_address, cpu_type="Sa1")
        # Hook the emulated A7 register bytes too.  In a live dual-CPU run the
        # notification-triggered pause can land after the native routine has
        # returned, but these read notifications retain the values observed by
        # the entry guard at exact SA-1 cycle stamps.
        need_guard_notifications = (
            anchored or args.select_last_guard or args.association_write is not None
        )
        a7_hook = (
            session.add_read_hook(0x003C, 0x003F, cpu_type="Sa1")
            if need_guard_notifications
            else None
        )
        # Retain the other direct-page reads made by the standard native-entry
        # guard as well.  These exact-cycle notifications distinguish an
        # address-shape rejection from an IRQ-budget rejection even when the
        # live dual-CPU pause lands after the native entry has returned.
        a5_hook = (
            session.add_read_hook(0x0034, 0x0037, cpu_type="Sa1")
            if need_guard_notifications
            else None
        )
        ac_hook = (
            session.add_read_hook(0x00AC, 0x00AD, cpu_type="Sa1")
            if need_guard_notifications
            else None
        )
        association_hook = (
            session.add_write_hook(
                args.association_write,
                args.association_write_end,
                cpu_type="Sa1",
                match_value=(args.association_value or 0),
                match_value_mask=args.association_value_mask,
            )
            if args.association_write is not None
            else None
        )
        session.drain_notifications(timeout=0.1)
        association_hit: dict[str, Any] | None = None
        notifications: list[dict[str, Any]] = []
        first_stop_pc: int | None = None
        first_stop_a7: int | None = None
        first_stop_return_bytes: bytes | None = None
        try:
            hit = session.run_until(max_frames=args.max_frames, hook_handle=hook)
            session.pause()
            first_stop_pc = current_sa1_pc(session)
            first_stop_raw_regs = bytes(
                session.read_memory("Sa1Memory", 0x00, 0x40)
            )
            first_stop_a7 = int.from_bytes(first_stop_raw_regs[0x3C:0x40], "little")
            first_stop_return_bytes = bytes(
                session.read_memory(
                    "snesMemory", 0x400000 | (first_stop_a7 & 0xFFFF), 4
                )
            )
            entry_dp = bytes(session.read_memory("Sa1Memory", 0x0000, 0x0100))
            entry_work = bytes(
                session.read_memory("snesMemory", 0x400000, 0x10000)
            )
            entry_video = bytes(
                session.read_memory("snesMemory", 0x410000, 0x10000)
            )
            entry_state_path = output / "entry.mss"
            session.save_state(entry_state_path)
            if association_hook is not None:
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(f"target entry stop failed before association: {hit!r}")
                first_notifications = hook_params(
                    session.drain_notifications(timeout=0.5)
                )
                notifications.extend(first_notifications)
                observed = [
                    row
                    for row in first_notifications
                    if int(row.get("handle", -1)) == association_hook
                ]
                if observed:
                    association_hit = {
                        "reason": "hookObservedDuringEntryPause",
                        "isPaused": True,
                        "framesAdvanced": (hit or {}).get("framesAdvanced", 0),
                    }
                else:
                    association_hit = session.run_until(
                        max_frames=args.max_frames, hook_handle=association_hook
                    )
            session.pause()
            notifications.extend(
                hook_params(session.drain_notifications(timeout=0.5))
            )
        finally:
            session.remove_hook(hook)
            if a7_hook is not None:
                session.remove_hook(a7_hook)
            if a5_hook is not None:
                session.remove_hook(a5_hook)
            if ac_hook is not None:
                session.remove_hook(ac_hook)
            if association_hook is not None:
                session.remove_hook(association_hook)
            session.drain_notifications(timeout=0.1)

        actual_pc = current_sa1_pc(session)
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"entry hook was not reached: hit={hit!r}, actual_pc=${actual_pc:06X}"
            )
        raw_regs = bytes(session.read_memory("Sa1Memory", 0x00, 0x40))
        regs = {
            **{
                f"D{index}": int.from_bytes(
                    raw_regs[index * 4 : index * 4 + 4], "little"
                )
                for index in range(8)
            },
            **{
                f"A{index}": int.from_bytes(
                    raw_regs[0x20 + index * 4 : 0x24 + index * 4], "little"
                )
                for index in range(8)
            },
        }

        entry_events: list[dict[str, Any]] = []
        guard_association = "first exact A7 guard signature retained after entry stop"
        candidate_notifications = notifications
        exact_entry_pause = (
            not anchored
            and not args.select_last_guard
            and first_stop_pc == args.entry
        )
        if args.guard_write_anchor is not None:
            guard_association = (
                "last exact A7 guard signature retained when execution stopped "
                f"on distinct post-guard SA-1 write ${args.guard_write_anchor:06X}"
            )
        elif args.guard_anchor is not None:
            guard_association = (
                "last exact A7 guard signature retained when execution stopped "
                f"on distinct post-guard execution anchor ${args.guard_anchor:06X}"
            )
        elif args.select_last_guard:
            guard_association = (
                "last exact A7 guard signature retained after target entry-hook stop"
            )
        association_events = [
            row
            for row in notifications
            if association_hook is not None
            and int(row.get("handle", -1)) == association_hook
        ]
        association_cycle = (
            min(int(row.get("cycleCount", -1)) for row in association_events)
            if association_events
            else None
        )
        if association_hook is not None and (
            association_hit or {}
        ).get("reason") not in ("hookFired", "hookObservedDuringEntryPause"):
            raise RuntimeError(
                "target entry fired but the association write stop was not reached: "
                f"association_hit={association_hit!r}, notifications={notifications[:32]!r}"
            )
        read_events = [
            row
            for row in candidate_notifications
            if a7_hook is not None and int(row.get("handle", -1)) == a7_hook
        ]
        entry_cycle = (
            int(entry_events[0]["cycleCount"])
            if entry_events and "cycleCount" in entry_events[0]
            else None
        )
        if entry_cycle is not None:
            read_events = [
                row
                for row in read_events
                if int(row.get("cycleCount", -1)) >= entry_cycle
            ]
        # The guard's exact signature is high word ($3E/$3F), followed within
        # a handful of cycles by low word ($3C/$3D).  Earlier low-word reads in
        # a live scheduler tick are unrelated A7 accesses and must not be
        # paired with the guard's later high word.
        guard_candidates: list[list[dict[str, Any]]] = []
        for index in range(len(read_events) - 3):
            candidate = read_events[index : index + 4]
            if [int(row.get("address", -1)) for row in candidate] != [
                0x003E,
                0x003F,
                0x003C,
                0x003D,
            ]:
                continue
            first_cycle = int(candidate[0].get("cycleCount", -1))
            last_cycle = int(candidate[-1].get("cycleCount", -1))
            if first_cycle >= 0 and last_cycle - first_cycle <= 64:
                guard_candidates.append(candidate)
        if association_cycle is not None:
            guard_candidates = [
                candidate
                for candidate in guard_candidates
                if int(candidate[-1].get("cycleCount", -1)) < association_cycle
            ]
            guard_association = (
                "last exact A7 guard signature before target-specific SA-1 "
                f"write at ${args.association_write:06X}"
            )
        elif association_hit is not None:
            guard_association = (
                "last exact A7 guard signature between atomic target-entry stop "
                f"and target-specific SA-1 write stop at ${args.association_write:06X}"
            )
        if not guard_candidates and not exact_entry_pause:
            raise RuntimeError(
                "entry fired but the exact A7 guard reads were not retained: "
                f"entry_events={entry_events!r}, reads={read_events[:16]!r}"
            )
        if exact_entry_pause:
            guard_reads: list[dict[str, Any]] = []
            entry_a7 = int(first_stop_a7)
            guard_association = (
                "direct DP A7 read at first atomic stop on exact target entry PC"
            )
        else:
            guard_reads = (
                guard_candidates[-1]
                if anchored
                or args.select_last_guard
                or association_cycle is not None
                or association_hit is not None
                else guard_candidates[0]
            )
            guard_values = {
                int(row["address"]): int(row.get("value", 0)) & 0xFF
                for row in guard_reads
            }
            entry_a7 = sum(
                guard_values[0x003C + index] << (8 * index) for index in range(4)
            )

        guard_cycle = (
            int(guard_reads[0].get("cycleCount", -1)) if guard_reads else None
        )
        guard_trace_reads = [
            row
            for row in notifications
            if int(row.get("handle", -1))
            in {
                handle
                for handle in (a5_hook, a7_hook, ac_hook)
                if handle is not None
            }
            and (
                guard_cycle is None
                or abs(int(row.get("cycleCount", -1)) - guard_cycle) <= 512
            )
        ]

        after = snapshot(session)
        emit(
            "entry_hit",
            **after,
            hit=hit,
            post_pause_pc=f"{actual_pc:06X}",
            first_stop_pc=(
                f"{first_stop_pc:06X}" if first_stop_pc is not None else None
            ),
            first_stop_a7=(
                f"{first_stop_a7:08X}" if first_stop_a7 is not None else None
            ),
            first_stop_return_bytes=(
                first_stop_return_bytes.hex()
                if first_stop_return_bytes is not None
                else None
            ),
            entry_cycle=entry_cycle,
            guard_anchor_cycle=(
                None
            ),
            guard_association=guard_association,
            guard_candidate_cycles=[
                int(candidate[0].get("cycleCount", -1))
                for candidate in guard_candidates
            ],
            association_write_cycle=association_cycle,
            association_hit=association_hit,
            association_write_events=association_events,
            guard_read_cycle=(
                int(guard_reads[0].get("cycleCount", -1)) if guard_reads else None
            ),
            guard_trace_reads=guard_trace_reads,
            entry_a7=f"{entry_a7:08X}",
            exact_a7_read_events=guard_reads,
            post_pause_registers={name: f"{value:08X}" for name, value in regs.items()},
            a7_return_bytes=bytes(
                session.read_memory("snesMemory", 0x400000 | (entry_a7 & 0xFFFF), 4)
            ).hex(),
            entry_state=str(entry_state_path),
        )

    (output / "entry-dp.bin").write_bytes(entry_dp)
    (output / "entry-work.bin").write_bytes(entry_work)
    (output / "entry-video.bin").write_bytes(entry_video)
    with log_path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
