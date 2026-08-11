#!/usr/bin/env python3
"""Compare Nexen's counted exact-exec stop with its scoped-breakpoint oracle.

This is debugger-control evidence only.  For each requested occurrence count,
the script reloads one state twice, establishes the same exact pre-opcode
$003A92 entry, and then runs the old per-hit scoped breakpoint and the new
core-side counter.  It requires identical CPU, RAM, PPU, frame, task, and IRQ
state at the final boundary and verifies that the one-shot counter is removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-exact-checkpoint-publish/Nexen"
)
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "fresh-campaign-entrysync-3ea4faf-to01100-v1/states/failure.mss"
)

sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def native_symbol(label: str) -> int:
    path = ROOT / "src/escbank.sym"
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == label:
            return 0x920000 | (
                int(fields[0].split(":")[-1], 16) & 0xFFFF
            )
    raise RuntimeError(f"{path}: missing symbol {label}")


ENTRY = native_symbol("entry_3a92")


def le16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def require_paused(m: McpSession, context: str) -> None:
    """Fail if an exact path unexpectedly resumed; never correct by stepping."""
    state = dict(m.get_state())
    if state.get("isPaused") is not True:
        raise RuntimeError(f"{context}: Nexen is not paused: {state}")


def snapshot(m: McpSession) -> tuple[dict[str, Any], tuple[bytes, ...]]:
    require_paused(m, "exact-stop snapshot")
    sa1 = dict(m.get_cpu_state("Sa1"))
    snes = dict(m.get_cpu_state("Snes"))
    state = dict(m.get_state())
    ppu = dict(m.get_ppu_state())
    iram = bytes(m.read_memory("sa1Memory", 0, 0x800))
    work = bytes(m.read_memory("snesMemory", 0x400000, 0x10000))
    wram = b"".join(
        bytes(m.read_memory("snesWorkRam", offset, 0x10000))
        for offset in (0, 0x10000)
    )
    vram = bytes(m.read_memory("snesVideoRam", 0, 0x10000))
    cgram = bytes(m.read_memory("snesCgRam", 0, 0x200))
    oam = bytes(m.read_memory("snesSpriteRam", 0, 0x220))
    spc_ram = bytes(m.read_memory("spcMemory", 0, 0x10000))
    public = {
        "sa1": sa1,
        "snes": snes,
        "frame_count": int(state["frameCount"]),
        "ppu": ppu,
        "sa1_iram_sha256": sha256_bytes(iram),
        "work_64k_sha256": sha256_bytes(work),
        "wram_128k_sha256": sha256_bytes(wram),
        "vram_64k_sha256": sha256_bytes(vram),
        "cgram_512_sha256": sha256_bytes(cgram),
        "oam_544_sha256": sha256_bytes(oam),
        "spc_ram_64k_sha256": sha256_bytes(spc_ram),
        "scheduler": {
            "halt_004e": le16(iram, 0x004E),
            "irq_mask_007c": le16(iram, 0x007C),
            "task_index_00aa": le16(iram, 0x00AA),
            "irq_budget_00ac": le16(iram, 0x00AC),
            "task_mask_f00002": be16(work, 0x0002),
            "game_tick_f01c56": be16(work, 0x1C56),
        },
    }
    return public, (iram, work, wram, vram, cgram, oam, spc_ram)


def exact_address(cpu: dict[str, Any]) -> int:
    return (
        ((int(cpu.get("k", 0)) & 0xFF) << 16)
        | (int(cpu.get("pc", 0)) & 0xFFFF)
    )


def require_stop(stop: dict[str, Any], occurrences: int) -> None:
    is_exact_counter = "exactStopHandle" in stop
    checks = {
        "hit": stop.get("hit") is True,
        "reason": stop.get("reason") == "breakpoint",
        "paused": stop.get("isPaused") is True,
        "requested": int(stop.get("requestedOccurrences", -1))
        == occurrences,
        "occurrences": int(stop.get("observedOccurrences", -1))
        == occurrences,
        "removed": (
            stop.get("exactStopRemoved") is True
            if is_exact_counter
            else stop.get("scopedBreakpointRemoved") is True
        ),
    }
    if is_exact_counter:
        checks.update(
            {
                "handle": int(stop.get("exactStopHandle", 0)) > 0,
                "triggered": stop.get("exactStopTriggered") is True,
                "delivered": (
                    stop.get("exactStopBreakDelivered") is True
                ),
                "trigger_cycle": int(
                    stop.get("triggerCycleCount", -1)
                )
                == int(stop.get("cycleCount", -2)),
                "trigger_frame": int(stop.get("triggerFrame", -1))
                == int(stop.get("endFrame", -2)),
            }
        )
    if not all(checks.values()):
        raise RuntimeError(f"exact stop failed: {checks}; {stop}")


def establish_entry(
    m: McpSession, state: Path, max_frames: int
) -> tuple[dict[str, Any], tuple[bytes, ...]]:
    require_paused(m, "entry establishment start")
    m.load_state(str(state.resolve()))
    require_paused(m, "entry establishment load")
    stop = dict(
        m.tool(
            "run_to_exec_breakpoint",
            {
                "address": ENTRY,
                "cpuType": "Sa1",
                "maxFrames": max_frames,
                "occurrences": 1,
            },
        )
    )
    require_stop(stop, 1)
    snap = snapshot(m)
    if exact_address(snap[0]["sa1"]) != ENTRY:
        raise RuntimeError("entry establishment did not stop at $92:DB82")
    return snap


def run_branch(
    m: McpSession,
    *,
    state: Path,
    tool: str,
    occurrences: int,
    max_frames: int,
) -> dict[str, Any]:
    initial_public, initial_raw = establish_entry(m, state, max_frames)
    require_paused(m, f"{tool} start")
    m.drain_notifications(timeout=0.05)
    started = time.monotonic()
    stop = dict(
        m.tool(
            tool,
            {
                "address": ENTRY,
                "cpuType": "Sa1",
                "maxFrames": max_frames,
                "occurrences": occurrences,
            },
        )
    )
    elapsed = time.monotonic() - started
    require_stop(stop, occurrences)
    final_public, final_raw = snapshot(m)
    response_address = (
        ((int(stop.get("k", 0)) & 0xFF) << 16)
        | (int(stop.get("pc", 0)) & 0xFFFF)
    )
    response_state_checks = {
        "response_pc_matches_snapshot": (
            response_address == exact_address(final_public["sa1"])
        ),
        "response_cycle_matches_snapshot": (
            int(stop.get("cycleCount", -1))
            == int(final_public["sa1"].get("cycleCount", -2))
        ),
        "response_frame_matches_snapshot": (
            int(stop.get("endFrame", -1))
            == int(final_public["frame_count"])
        ),
    }
    if not all(response_state_checks.values()):
        raise RuntimeError(
            f"{tool} response/snapshot mismatch: {response_state_checks}"
        )
    notifications = m.drain_notifications(timeout=0.05)
    hook_notifications = [
        row
        for row in notifications
        if row.get("method") == "notifications/mesen/hookFired"
    ]
    return {
        "tool": tool,
        "stop": stop,
        "elapsed_seconds": elapsed,
        "initial": initial_public,
        "initial_raw": initial_raw,
        "final": final_public,
        "final_raw": final_raw,
        "response_state_checks": response_state_checks,
        "hook_notification_count": len(hook_notifications),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--occurrences",
        type=int,
        action="append",
        default=[],
        help="repeat for each count; default: 1, 100, 1000",
    )
    parser.add_argument("--max-frames", type=int, default=5000)
    parser.add_argument("--port", type=int, default=9545)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.state):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    counts = args.occurrences or [1, 100, 1000]
    if any(count < 1 for count in counts):
        parser.error("--occurrences values must be positive")
    if args.max_frames < max(counts) * 2:
        parser.error("--max-frames must allow at least two frames per occurrence")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    campaign.configure_dotnet(args.nexen)
    args.output.mkdir(parents=True)
    events: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "diagnostic Nexen debugger-control equivalence; counted core-side "
            "exact stop versus retained per-hit scoped breakpoint; not ROM "
            "semantics, fresh-boot gameplay, or fps"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256_file(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256_file(args.nexen),
        "nexen_identity": campaign.nexen_identity(args.nexen),
        "state": str(args.state.resolve()),
        "state_sha256": sha256_file(args.state),
        "entry": f"{ENTRY:06X}",
        "occurrences": counts,
        "core_or_rom_modified_by_test": False,
        "validator_sha256": sha256_file(Path(__file__).resolve()),
        "campaign_harness_sha256": sha256_file(
            ROOT / "tools" / "replay_mame_controller_campaign.py"
        ),
        "time_unix": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    result = "red"
    failure: dict[str, Any] | None = None
    removal: dict[str, Any] | None = None
    try:
        with McpSession(
            rom=str(args.rom.resolve()),
            mesen=str(args.nexen.resolve()),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=600.0,
            stderr_log=args.output / "nexen.stderr.log",
        ) as m:
            campaign.pause_for_startup(m)
            for count in counts:
                control = run_branch(
                    m,
                    state=args.state,
                    tool="run_to_exec_breakpoint",
                    occurrences=count,
                    max_frames=args.max_frames,
                )
                candidate = run_branch(
                    m,
                    state=args.state,
                    tool="run_to_exact_exec_stop",
                    occurrences=count,
                    max_frames=args.max_frames,
                )
                checks = {
                    "identical_initial_public": (
                        control["initial"] == candidate["initial"]
                    ),
                    "identical_initial_ram": (
                        control["initial_raw"] == candidate["initial_raw"]
                    ),
                    "identical_final_public": (
                        control["final"] == candidate["final"]
                    ),
                    "identical_final_ram": (
                        control["final_raw"] == candidate["final_raw"]
                    ),
                    "exact_final_pc": (
                        exact_address(candidate["final"]["sa1"]) == ENTRY
                    ),
                    "candidate_triggered": (
                        candidate["stop"].get("exactStopTriggered") is True
                    ),
                    "candidate_break_delivered": (
                        candidate["stop"].get(
                            "exactStopBreakDelivered"
                        )
                        is True
                    ),
                    "candidate_no_hook_notifications": (
                        candidate["hook_notification_count"] == 0
                    ),
                }
                event = {
                    "event": "equivalence_case",
                    "occurrences": count,
                    "checks": checks,
                    "control": {
                        key: control[key]
                        for key in (
                            "tool",
                            "stop",
                            "elapsed_seconds",
                            "initial",
                            "final",
                            "response_state_checks",
                            "hook_notification_count",
                        )
                    },
                    "candidate": {
                        key: candidate[key]
                        for key in (
                            "tool",
                            "stop",
                            "elapsed_seconds",
                            "initial",
                            "final",
                            "response_state_checks",
                            "hook_notification_count",
                        )
                    },
                    "result": (
                        "green" if all(checks.values()) else "red"
                    ),
                }
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)
                if event["result"] != "green":
                    raise RuntimeError(
                        f"counted exact-stop mismatch at N={count}: {checks}"
                    )

            require_paused(m, "removal check start")
            response = dict(
                m.tool(
                    "run_to_exact_exec_stop",
                    {
                        "address": ENTRY,
                        "cpuType": "Sa1",
                        "maxFrames": args.max_frames,
                        "occurrences": 1,
                    },
                )
            )
            require_stop(response, 1)
            require_paused(m, "removal check return")
            removal = {
                "response": response,
                "previous_handle": candidate["stop"].get(
                    "exactStopHandle"
                ),
                "new_handle": response.get("exactStopHandle"),
                "result": (
                    "green"
                    if response.get("exactStopRemoved") is True
                    and int(response.get("exactStopHandle", 0))
                    != int(
                        candidate["stop"].get("exactStopHandle", 0)
                    )
                    else "red"
                ),
            }
            events.append({"event": "removal_check", **removal})
            if removal["result"] != "green":
                raise RuntimeError("counted exact stop remained armed")
            result = "green"
    except Exception as exc:
        failure = {"reason": repr(exc)}

    event_path = args.output / "events.jsonl"
    with event_path.open("x", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
    case_events = [
        event for event in events if event.get("event") == "equivalence_case"
    ]
    summary = {
        **provenance,
        "result": result,
        "failure": failure,
        "green_cases": sum(
            event.get("result") == "green" for event in case_events
        ),
        "total_cases": len(counts),
        "removal_check": removal,
        "user_breakpoint_coexistence_tested": False,
        "events": str(event_path.resolve()),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
