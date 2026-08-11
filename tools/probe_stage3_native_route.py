#!/usr/bin/env python3
"""Retain a bounded native-off/native-on route proof from one Stage-3 state.

This is deliberately narrower than the sustained-rate harness: it verifies
that one assembled SA-1 body is reached organically under real neutral input,
while retaining exact before/after states.  It is checkpoint evidence only;
neither a fresh-boot claim nor a performance measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_render_helpers as base  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_u16(session: base.McpSession, address: int) -> int:
    return int.from_bytes(
        session.read_memory("Sa1Memory", address, 2), "little"
    )


def write_u16(session: base.McpSession, address: int, value: int) -> None:
    session.write_memory(
        "Sa1Memory", address, (value & 0xFFFF).to_bytes(2, "little").hex()
    )


def read_tick(session: base.McpSession) -> int:
    return int.from_bytes(
        session.read_memory("snesMemory", 0x401C56, 2), "big"
    )


def drain_hits(session: base.McpSession, handle: int) -> int:
    hits = 0
    for _ in range(16):
        rows = session.drain_notifications(timeout=0.05)
        for row in rows:
            if (
                row.get("method") == "notifications/mesen/hookFired"
                and int(row.get("params", {}).get("handle", -1)) == handle
            ):
                hits += 1
        if not rows:
            break
    return hits


def wait_for_file(path: Path) -> None:
    for _ in range(200):
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"save state did not appear: {path}")


def save_state(session: base.McpSession, path: Path) -> dict[str, object]:
    response = session.save_state(path)
    wait_for_file(path)
    return {"path": str(path), "sha256": sha256(path), "response": response}


def capture_variant(
    *,
    gate: int,
    args: argparse.Namespace,
    port: int,
) -> dict[str, object]:
    name = "native_on" if gate else "native_off"
    directory = args.output / name
    directory.mkdir()
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=directory / "nexen.stderr.log",
    ) as session:
        session.pause()
        session.load_state(str(args.state))
        session.pause()
        write_u16(session, 0x071A, gate)
        write_u16(session, 0x073A, gate)
        before = {
            "tick": read_tick(session),
            "halt": read_u16(session, 0x4E),
            "xlat_gate_071a": read_u16(session, 0x071A),
            "fetch_gate_073a": read_u16(session, 0x073A),
        }
        pre_state = save_state(session, directory / "pre-route.mss")
        hook = session.add_exec_hook(args.native_entry, cpu_type="Sa1")
        session.drain_notifications(timeout=0.05)
        try:
            response = session.set_input(0, args.frames)
            session.pause()
            hits = drain_hits(session, hook)
        finally:
            session.remove_hook(hook)
            session.drain_notifications(timeout=0.05)
        after = {
            "tick": read_tick(session),
            "halt": read_u16(session, 0x4E),
            "xlat_gate_071a": read_u16(session, 0x071A),
            "fetch_gate_073a": read_u16(session, 0x073A),
        }
        post_state = save_state(session, directory / "post-route.mss")
    healthy = (
        after["tick"] > before["tick"]
        and after["halt"] == 0
        and after["xlat_gate_071a"] == gate
        and after["fetch_gate_073a"] == gate
        and (hits == 0 if gate == 0 else hits >= args.minimum_on_hits)
    )
    return {
        "event": "variant",
        "name": name,
        "gates": {"071a": gate, "073a": gate},
        "before": before,
        "after": after,
        "input": {"port": 0, "buttons": 0, "frames_requested": args.frames},
        "input_response": response,
        "native_entry": f"{args.native_entry:06X}",
        "native_entry_hits": hits,
        "pre_route_state": pre_state,
        "post_route_state": post_state,
        "result": "green" if healthy else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-entry", type=lambda value: int(value, 16), required=True)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--minimum-on-hits", type=int, default=1)
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument(
        "--gates",
        default="0,1",
        help="comma-separated subset of native gates to run (default: 0,1)",
    )
    args = parser.parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    if args.frames <= 0 or args.minimum_on_hits <= 0:
        parser.error("--frames and --minimum-on-hits must be positive")
    try:
        gates = [int(value, 0) for value in args.gates.split(",")]
    except ValueError as exc:
        parser.error(f"invalid --gates: {exc}")
    if not gates or any(gate not in (0, 1) for gate in gates) or len(set(gates)) != len(gates):
        parser.error("--gates must contain a nonempty unique subset of 0,1")
    for label, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    args.output.mkdir(parents=True)
    provenance = {
        "event": "provenance",
        "scope": (
            "checkpointed exact-Nexen native-route A/B with neutral real "
            "port-0 input and retained before/after states; not fresh boot, "
            "FPS, or whole-program semantic proof"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "native_entry": f"{args.native_entry:06X}",
        "gates_requested": gates,
    }
    rows: list[dict[str, object]] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)
    for index, gate in enumerate(gates):
        port = args.port + index
        row = capture_variant(gate=gate, args=args, port=port)
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    result = "green" if all(row["result"] == "green" for row in rows[1:]) else "red"
    summary = {"event": "summary", "result": result}
    rows.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (args.output / "route.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return 0 if result == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
