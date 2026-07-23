#!/usr/bin/env python3
"""Trace production renderer progress around deferred OBJ-cache insertions.

This is checkpointed diagnostic evidence, not an FPS harness.  It finishes the
checkpoint's already-running render before replacing the WRAM video-code mirror,
then holds real Right+B input and stops at successive render-complete hooks.  A
timeout retains CPU/mailbox/cache state so a queue or DMA regression cannot be
mistaken for ordinary renderer debt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
RENDER_COMPLETE = 0x7F8924
OBJ_CACHE_RESTART = 0x7F9C05
PHASES = {"render_complete": RENDER_COMPLETE}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7939)
    parser.add_argument("--renders", type=int, default=40)
    parser.add_argument(
        "--watch-restart-after",
        type=int,
        default=-1,
        help="After this many completed new-code renders, stop at obj_cache_restart.",
    )
    return parser.parse_args()


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def snapshot(m: McpSession, index: int, result: dict | None) -> dict:
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    work = m.read_memory("snesWorkRam", 0x89A0, 0x28)
    req_ack = m.read_memory("snesMemory", 0x3300, 4)
    state = m.get_state()
    return {
        "index": index,
        "result": result,
        "frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "request": le16(req_ack[0:2]),
        "ack": le16(req_ack[2:4]),
        "render_count": le16(work[2:4]),
        "render_generation": le16(work[4:6]),
        "obj_slots": le16(m.read_memory("snesWorkRam", 0x00DE, 2)),
        "queued_tiles": le16(m.read_memory("snesWorkRam", 0x89C6, 2)),
        "restart_reason": le16(m.read_memory("snesWorkRam", 0x89C8, 2)),
        "restart_obj_slots": le16(m.read_memory("snesWorkRam", 0x89CA, 2)),
        "restart_queued_tiles": le16(m.read_memory("snesWorkRam", 0x89CC, 2)),
        "obj_cursor": le16(m.read_memory("snesWorkRam", 0x00E0, 2)),
        "obj_count": le16(m.read_memory("snesWorkRam", 0x00E2, 2)),
        "snes": snes,
        "sa1": sa1,
        "stack": m.read_memory("snesWorkRam", 0x1DC0, 0x40).hex(),
    }


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")

    stderr = args.output / "nexen.stderr.log"
    records: list[dict] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        handles = {
            m.add_exec_hook(address, cpu_type="Snes"): label
            for label, address in PHASES.items()
        }
        completion = next(
            handle for handle, label in handles.items() if label == "render_complete"
        )
        m.drain_notifications(timeout=0.05)

        # Complete the saved state's in-flight old-code render before changing
        # instructions under the 5A22.
        first = m.run_until(max_frames=20, hook_handle=completion)
        m.pause()
        records.append(snapshot(m, -1, first))
        if (first or {}).get("reason") != "hookFired":
            raise RuntimeError(f"checkpoint render did not complete: {first!r}")

        mirror = args.rom.read_bytes()[0x298000 : 0x298000 + 0x3000]
        for offset in range(0, len(mirror), 0x1000):
            m.write_memory(
                "snesWorkRam",
                0x18000 + offset,
                mirror[offset : offset + 0x1000].hex(),
            )
        observed = m.read_memory("snesWorkRam", 0x18000, len(mirror))
        if observed != mirror:
            raise RuntimeError("WRAM video mirror refresh did not verify")
        m.tool(
            "set_input",
            {
                "port": 0,
                "buttons": McpSession.BTN_RIGHT | McpSession.BTN_B,
                "hold": True,
            },
        )

        timed_out = False
        for index in range(args.renders):
            if index == args.watch_restart_after:
                m.remove_hook(completion)
                m.drain_notifications(timeout=0.10)
                restart = m.add_exec_hook(OBJ_CACHE_RESTART, cpu_type="Snes")
                m.drain_notifications(timeout=0.05)
                result = m.run_until(max_frames=20, hook_handle=restart)
                m.pause()
                record = snapshot(m, index, result)
                record["watch"] = "obj_cache_restart"
                records.append(record)
                print(json.dumps(record, sort_keys=True), flush=True)
                state_path = args.output / "restart.mss"
                m.save_state(state_path.resolve())
                deadline = time.monotonic() + 5.0
                while (
                    (not state_path.is_file() or state_path.stat().st_size == 0)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                break
            result = m.run_until(max_frames=20, hook_handle=completion)
            m.pause()
            record = snapshot(m, index, result)
            records.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)
            if (result or {}).get("reason") != "hookFired":
                timed_out = True
                state_path = args.output / "timeout.mss"
                m.save_state(state_path.resolve())
                deadline = time.monotonic() + 5.0
                while (
                    (not state_path.is_file() or state_path.stat().st_size == 0)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                break

        notifications = m.drain_notifications(timeout=0.25)
        events = []
        for notification in notifications:
            if notification.get("method") != "notifications/mesen/hookFired":
                continue
            params = dict(notification.get("params", {}))
            label = handles.get(int(params.get("handle", -1)))
            if label is None:
                continue
            events.append(
                {
                    "label": label,
                    "address": int(params.get("address", 0)),
                    "cycle": int(params.get("cycleCount", 0)),
                    "frame": int(params.get("frame", 0)),
                }
            )

    report = {
        "scope": "checkpointed renderer queue diagnostic; not FPS",
        "rom": str(args.rom),
        "rom_sha256": hashlib.sha256(args.rom.read_bytes()).hexdigest(),
        "state": str(args.state),
        "timed_out": timed_out,
        "records": records,
        "events": events,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"timed_out": timed_out, "results": str(target)}))
    return int(timed_out)


if __name__ == "__main__":
    raise SystemExit(main())
