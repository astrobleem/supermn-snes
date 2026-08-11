#!/usr/bin/env python3
"""Regress the native $13BE sentinel-route stack convention.

The retained exact-boundary forensic state fences each `$003A92` native entry
and records route hooks plus the task-5 saved-SP margin.  The CE58-specific
D18A bridge must preserve that context across every entry; a four-byte drift
or terminal failure is a regression.  This is bounded checkpoint evidence,
not fresh-boot or playability evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # type: ignore  # noqa: E402

_session.validate_mesen_build = lambda *_a, **_k: None
from mesen_mcp import McpSession  # type: ignore  # noqa: E402


TARGET = 0x92DB82
TASK_CONTEXT = 0x40000A + 5 * 4
TASK_FLOOR = 0xC10882 + 5 * 4
ROUTE_HOOKS = {
    "fetch_choke": 0x00F980,
    "xlat_dispatch": 0x94F900,
    "entry_13be_table": 0x94AB04,
    "entry_13be_direct": 0x92A5C1,
    "entry_swo": 0x92FA00,
}


def symbol_cpu(name: str) -> int:
    for raw in (ROOT / "src/escbank.sym").read_text(
        encoding="utf-8-sig"
    ).splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing escape symbol {name!r}")


def assert_repair_seams(rom: Path) -> dict[str, str]:
    """Pin the generic-push and CE58 no-push conventions in the packed ROM."""

    data = rom.read_bytes()
    file_base = 0x290000

    def file_offset(cpu: int) -> int:
        return file_base + (cpu - 0x8000)

    generic = file_offset(symbol_cpu("entry_d18a"))
    entry = symbol_cpu("entry_d18a")
    body = symbol_cpu("entry_d18a_body")
    bridge_label = symbol_cpu("brce58_7")
    bridge = file_offset(bridge_label - 3)
    generic_expected = bytes.fromhex("c230a5408554a542855622aee500")
    bridge_expected = bytes((0x4C, entry & 0xFF, (entry >> 8) & 0xFF))
    if data[generic : generic + len(generic_expected)] != generic_expected:
        raise RuntimeError(
            "generic D18A synthetic-push prologue changed: "
            f"{data[generic:generic + len(generic_expected)].hex()}"
        )
    if data[bridge : bridge + 3] != bridge_expected:
        raise RuntimeError(
            "CE58 D18A bridge no longer enters the balanced push/pop path: "
            f"{data[bridge:bridge + 3].hex()} != {bridge_expected.hex()}"
        )
    return {
        "generic_d18a": f"{generic:06X}",
        "entry_d18a": f"{entry:04X}",
        "entry_d18a_body": f"{body:04X}",
        "ce58_bridge": f"{bridge:06X}",
        "generic_prologue": generic_expected.hex(),
        "ce58_bridge_balanced_push_bytes": bridge_expected.hex(),
    }


def be32(m: McpSession, address: int) -> int:
    return int.from_bytes(bytes(m.read_memory("snesMemory", address, 4)), "big")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--nexen", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--entries", type=int, default=44)
    p.add_argument("--port", type=int, default=9568)
    return p.parse_args()


def hook_rows(m: McpSession) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in m.drain_notifications(timeout=0.25)
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    seams = assert_repair_seams(args.rom)
    proc = subprocess.Popen(
        [
            "env",
            "DOTNET_ROOT=/home/chad/.dotnet10",
            str(args.nexen),
            "--mcp",
            f"--mcp-port={args.port}",
            str(args.rom),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2.0)
        with McpSession(
            rom=str(args.rom),
            mesen=str(args.nexen),
            port=args.port,
            boot_wait=1.0,
            socket_timeout=300.0,
        ) as m:
            m.load_state(str(args.state))
            m.drain_notifications(timeout=0.25)
            handles = {
                m.add_exec_hook(address, cpu_type="Sa1"): label
                for label, address in ROUTE_HOOKS.items()
            }
            m.drain_notifications(timeout=0.25)
            rows: list[dict[str, Any]] = []
            for entry in range(1, args.entries + 1):
                before = be32(m, TASK_CONTEXT)
                floor = be32(m, TASK_FLOOR)
                result = dict(
                    m.tool(
                        "run_to_exact_exec_stop",
                        {
                            "address": TARGET,
                            "cpuType": "Sa1",
                            "maxFrames": 100,
                            "occurrences": 1,
                        },
                    )
                )
                events = hook_rows(m)
                counts = {
                    label: sum(1 for row in events if handles.get(int(row.get("handle", -1))) == label)
                    for label in ROUTE_HOOKS
                }
                after = be32(m, TASK_CONTEXT)
                rows.append(
                    {
                        "entry": entry,
                        "before_context": f"{before:08X}",
                        "after_context": f"{after:08X}",
                        "floor": f"{floor:08X}",
                        "margin_before": before - floor,
                        "margin_after": after - floor,
                        "route_counts": counts,
                        "run": result,
                    }
                )
                if result.get("reason") != "breakpoint" or not result.get("hit"):
                    break
            return {"rows": rows, "seams": seams}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = run(args)
    rows = result["rows"]
    stable_rows = [
        row["margin_before"] == row["margin_after"]
        for row in rows
        if row["run"].get("hit")
    ]
    table_hits = sum(row["route_counts"]["entry_13be_table"] for row in rows)
    direct_hits = sum(row["route_counts"]["entry_13be_direct"] for row in rows)
    checks = {
        "retained_entries_reached": sum(bool(row["run"].get("hit")) for row in rows) >= min(args.entries, 43),
        "table_route_observed": table_hits > 0,
        "direct_route_not_observed": direct_hits == 0,
        "every_completed_entry_preserves_context": bool(stable_rows)
        and all(stable_rows),
        "no_terminal_entry_failure": (
            rows[-1]["entry"] == args.entries
            and rows[-1]["run"].get("hit") is True
            and rows[-1]["margin_before"] > 0
        ),
    }
    summary = {
        "result": "green" if all(checks.values()) else "red",
        "classification": "native-interpreter-sentinel-route-stack-convention",
        "scope": "retained exact-boundary forensic regression; not fresh-boot or playability proof",
        "rom": str(args.rom.resolve()),
        "state": str(args.state.resolve()),
        "seams": result["seams"],
        "entries_requested": args.entries,
        "checks": checks,
        "table_hits": table_hits,
        "direct_hits": direct_hits,
        "rows": rows,
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": summary["result"], "checks": checks, "output": str(args.output)}))
    return 1 if summary["result"] == "red" else 0


if __name__ == "__main__":
    raise SystemExit(main())
