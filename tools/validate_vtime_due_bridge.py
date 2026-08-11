#!/usr/bin/env python3
"""Exercise the synthetic VTIME-due bridge through the retained IRQ reload.

The v6 choke-gateway diagnostic could leave a virtual deadline pending while
the `$0818` self-refetch loop bypassed choke.  The v7 diagnostic mirrors such
a due event to `$AC=1`; the next ordinary iloop must therefore enter the
existing IRQ reload, clear VTIME's due bit, and resume.  This is deliberately
synthetic wiring coverage, not a MAME comparison, gameplay test, rate result,
or production claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen"
)
VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
ILOOP = 0x0080A5
VTIME_RELOAD = 0xF28500

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_sa1_pc(m: McpSession, address: int) -> None:
    state = dict(m.get_cpu_state("Sa1"))
    state.update(
        {
            "pc": address & 0xFFFF,
            "k": (address >> 16) & 0xFF,
            "d": 0,
            "dbr": 0,
            "ps": int(state.get("ps", 0)) | 0x04,
            "emulationMode": False,
        }
    )
    allowed = (
        "cpuType", "pc", "k", "a", "x", "y", "sp", "d", "dbr", "ps",
        "emulationMode",
    )
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def timer(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("snesMemory", VTIME_BASE, 0x1A))
    snapshot = {
        name: int.from_bytes(raw[offset : offset + 2], "little")
        for name, offset in (
            ("magic", 0x00),
            ("valid", 0x02),
            ("remaining_lo", 0x06),
            ("remaining_hi", 0x08),
            ("phase", 0x0A),
            ("due", 0x18),
        )
    }
    snapshot["legacy_countdown_ac"] = int.from_bytes(
        bytes(m.read_memory("Sa1Memory", 0x00AC, 2)), "little"
    )
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9330)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def hit(response: dict[str, Any] | None) -> bool:
    return (response or {}).get("reason") == "hookFired"


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    states = output / "states"
    states.mkdir(parents=True)
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    with McpSession(
        rom=retained_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(str(args.state.resolve()))
        m.pause()
        original = timer(m)
        if original["magic"] != VTIME_MAGIC or original["valid"] != 1:
            raise RuntimeError("source state does not contain live VTIME diagnostic state")
        # Reproduce the handoff produced by both v7 due writers.  This writes
        # only the copied diagnostic console and retains the forced prestate.
        m.write_memory("snesMemory", VTIME_BASE + 0x18, "0100")
        m.write_memory("Sa1Memory", 0x00AC, "0100")
        set_sa1_pc(m, ILOOP)
        forced = timer(m)
        forced_state = campaign.save_state(m, states / "forced-due-prestate.mss")

        reload_hook = m.add_exec_hook(VTIME_RELOAD, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            reload_hit = m.run_until(max_frames=4, hook_handle=reload_hook)
            m.pause()
            at_reload = {
                "timer": timer(m),
                "sa1": m.get_cpu_state("Sa1"),
                "state": campaign.save_state(m, states / "at-reload.mss"),
            }
        finally:
            m.remove_hook(reload_hook)
            m.drain_notifications(timeout=0.05)

        iloop_hook = m.add_exec_hook(ILOOP, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            resumed_hit = m.run_until(max_frames=4, hook_handle=iloop_hook)
            m.pause()
            after = {
                "timer": timer(m),
                "sa1": m.get_cpu_state("Sa1"),
                "state": campaign.save_state(m, states / "after-reload.mss"),
            }
        finally:
            m.remove_hook(iloop_hook)
            m.drain_notifications(timeout=0.05)

    checks = {
        "source_state_has_live_vtime": original["magic"] == VTIME_MAGIC and original["valid"] == 1,
        "forced_due_is_retained": forced["due"] == 1,
        "forced_one_countdown_is_retained": forced["legacy_countdown_ac"] == 1,
        "retained_vtime_reload_reached": hit(reload_hit),
        "returns_to_iloop": hit(resumed_hit),
        "due_cleared_by_retained_reload": after["timer"]["due"] == 0,
        "deadline_phase_advanced_once": after["timer"]["phase"] == (forced["phase"] + 50) % 5743,
    }
    report = {
        "scope": (
            "synthetic v7 VTIME due-to-retained-IRQ bridge regression from a fresh-title "
            "diagnostic state; not MAME equivalence, fresh boot, gameplay, rate, or acceptance"
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "source_state": {"path": str(args.state.resolve()), "sha256": sha256(args.state)},
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE + 0x18:06X}", "hex": "0100"},
            {"region": "Sa1Memory", "address": "0000AC", "hex": "0100"},
        ],
        "original": original,
        "forced": {"timer": forced, "state": forced_state},
        "at_reload": {"hit": reload_hit, **at_reload},
        "after": {"hit": resumed_hit, **after},
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(output / "summary.json")}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
