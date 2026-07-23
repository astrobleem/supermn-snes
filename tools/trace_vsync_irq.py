#!/usr/bin/env python3
"""Trace the R5VNMI02/R5VNMI03 inter-CPU cadence handshake without pausing mid-run.

This is a checkpointed pacing-lab diagnostic, not an FPS harness.  It installs
cycle-stamped execution/write hooks on both CPUs, runs one uninterrupted frame
window, then records whether the SA-1 request reached the 5A22 IRQ handler and
which arm/epoch path the WRAM snapshot helper took.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_ROM = (
    ROOT
    / "build/playability-20260719/"
    "caf6-semantic-hle-v6-render-cache-v17b-event-irq-returnp-lab/"
    "interp_vsync_lab.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260719/"
    "caf6-semantic-hle-v6-render-cache-v17b-event-irq-returnp-checkpoint-probe/"
    "final.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = (
    ROOT
    / "build/playability-20260719/"
    "caf6-semantic-hle-v6-render-cache-v17b-event-irq-returnp-trace"
)

LAB_MARKER_OFFSET = 0x2CFF00
LAB_MARKERS = (b"R5VNMI02", b"R5VNMI03")

EXEC_HOOKS = {
    # SA-1 production tick boundary and lab cadence handler.
    "sa1_clamp": ("Sa1", 0x00F5A3),
    "sa1_vsync_wait": ("Sa1", 0x99FB15),
    "sa1_epoch_ready": ("Sa1", 0x99FB2F),
    # 5A22 supervisor/render phases.  wl_blob is copied from $E9:8954 to
    # $7E:F000, so the two in-blob addresses below are the runtime locations.
    "snes_frame_ready": ("Snes", 0x7EF02A),
    "snes_sound_tick": ("Snes", 0x7F9800),
    "snes_sound_done": ("Snes", 0x7F9877),
    "snes_vf_tick": ("Snes", 0x7F8918),
    "snes_snapshot_acquire": ("Snes", 0x7FA100),
    "snes_vid_frame": ("Snes", 0x7F80BA),
    "snes_vid_bg": ("Snes", 0x7F8478),
    "snes_vid_obj": ("Snes", 0x7F9D00),
    "snes_ppu_flush": ("Snes", 0x7F9D12),
    "snes_vf_done": ("Snes", 0x7F8924),
    "snes_frame_done": ("Snes", 0x7EF035),
    "snes_vid_init": ("Snes", 0x7F807B),
    "snes_bg_cache_init": ("Snes", 0x7F8818),
    "snes_supervisor_boot": ("Snes", 0x7F882E),
    "snes_rc_copy": ("Snes", 0x7F898B),
    # 5A22 vector trampolines and WRAM-resident handler/helper entries.
    "snes_irq_trampoline": ("Snes", 0x009428),
    "snes_nmi_trampoline": ("Snes", 0x00942C),
    "snes_try_wake": ("Snes", 0x7F8E00),
    "snes_arm_seen": ("Snes", 0x7F8E09),
    "snes_deadline_due": ("Snes", 0x7F8E17),
    "snes_nmi_handler": ("Snes", 0x7F8F00),
    "snes_irq_handler": ("Snes", 0x7F8F40),
}

WRITE_HOOKS = {
    # SA-1-side IRQ request/enable/clear and 5A22-side acknowledge/enable.
    "sa1_scnt_write": ("Sa1", 0x002209, 0x002209),
    "sa1_cie_write": ("Sa1", 0x00220A, 0x00220A),
    "sa1_cic_write": ("Sa1", 0x00220B, 0x00220B),
    "snes_ccnt_write": ("Snes", 0x002200, 0x002200),
    "snes_sie_write": ("Snes", 0x002201, 0x002201),
    "snes_sic_write": ("Snes", 0x002202, 0x002202),
    # Arm word, vblank epoch, last-release epoch, and init marker.
    "sa1_cadence_write": ("Sa1", 0x410122, 0x41012C),
    "snes_cadence_write": ("Snes", 0x410122, 0x41012C),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=0.05)
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
    dotnet10 = "/home/chad/.dotnet10"
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet10
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet10, dotnet8)
    ]
    os.environ["PATH"] = ":".join([dotnet10, dotnet8, *current])


def hook_notifications(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        if row.get("method") == "notifications/mesen/hookFired":
            yield row.get("params", {})


def cpu_brief(m: McpSession, cpu_type: str) -> dict[str, Any]:
    state = dict(m.get_cpu_state(cpu_type))
    keys = ("pc", "k", "sp", "ps", "a", "x", "y", "d", "dbr", "cycleCount")
    result = {key: state.get(key) for key in keys if key in state}
    if "pc" in state:
        result["linear_pc"] = (int(state.get("k", 0)) << 16) | int(state["pc"])
    return result


def paused_snapshot(m: McpSession) -> dict[str, Any]:
    return {
        "snes_cpu": cpu_brief(m, "Snes"),
        "sa1_cpu": cpu_brief(m, "Sa1"),
        "tick_0760": int.from_bytes(m.read_memory("Sa1Memory", 0x0760, 2), "little"),
        "cadence_snes_view": m.read_memory("snesMemory", 0x410122, 0x0B).hex(),
        "cadence_sa1_view": m.read_memory("Sa1Memory", 0x410122, 0x0B).hex(),
        "snes_sa1_status_2300": m.read_memory("snesMemory", 0x2300, 1).hex(),
        "sa1_cpu_status_2300": m.read_memory("Sa1Memory", 0x2300, 1).hex(),
    }


def main() -> int:
    args = parse_args()
    rom = args.rom.resolve()
    state = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    if args.timeout <= 0 or args.poll_seconds <= 0:
        raise SystemExit("--timeout and --poll-seconds must be positive")
    for label, path in (("ROM", rom), ("state", state), ("Nexen", nexen)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    marker = rom.read_bytes()[LAB_MARKER_OFFSET : LAB_MARKER_OFFSET + 8]
    if marker not in LAB_MARKERS:
        raise SystemExit(
            f"refusing non-R5VNMI02/R5VNMI03 ROM: marker was {marker!r}"
        )
    output.mkdir(parents=True, exist_ok=False)
    configure_dotnet(nexen)

    rows: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "time": time.time(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_status": git_value("status", "--porcelain=v1").splitlines(),
        "harness": str(Path(__file__).resolve()),
        "harness_sha256": sha256(Path(__file__).resolve()),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "marker": marker.decode(),
        "frames": args.frames,
        "timeout": args.timeout,
        "runtime_pokes": [],
        "hooks_pause_cpu": False,
        "evidence_scope": f"checkpointed {marker.decode()} handshake trace; not fps",
        "exec_hooks": {
            label: {"cpu": cpu, "address": f"{address:06X}"}
            for label, (cpu, address) in EXEC_HOOKS.items()
        },
        "write_hooks": {
            label: {"cpu": cpu, "start": f"{start:06X}", "end": f"{end:06X}"}
            for label, (cpu, start, end) in WRITE_HOOKS.items()
        },
    }
    rows.append(provenance)

    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        start = paused_snapshot(m)
        rows.append({"event": "start", "time": time.time(), **start})

        handles: dict[str, int] = {}
        for label, (cpu_type, address) in EXEC_HOOKS.items():
            handles[label] = m.add_exec_hook(address, cpu_type=cpu_type)
        for label, (cpu_type, start_address, end_address) in WRITE_HOOKS.items():
            handles[label] = m.add_write_hook(
                start_address, end_address, cpu_type=cpu_type
            )
        labels_by_handle = {handle: label for label, handle in handles.items()}
        m.drain_notifications(timeout=0.05)

        sequence = 0
        nmi_frames = 0

        def collect(notifications: Iterable[dict[str, Any]]) -> None:
            nonlocal sequence, nmi_frames
            for params in hook_notifications(notifications):
                handle = int(params.get("handle", -1))
                label = labels_by_handle.get(handle)
                if label is None:
                    continue
                rows.append(
                    {
                        "event": "hook",
                        "sequence": sequence,
                        "label": label,
                        **params,
                    }
                )
                sequence += 1
                if label == "snes_nmi_handler":
                    nmi_frames += 1

        wall_start = time.monotonic()
        m.resume()
        while nmi_frames < args.frames and time.monotonic() - wall_start < args.timeout:
            collect(m.drain_notifications(timeout=args.poll_seconds))
        m.pause()
        collect(m.drain_notifications(timeout=0.5))
        run_result = {
            "requested_nmi_frames": args.frames,
            "observed_nmi_frames": nmi_frames,
            "timed_out": nmi_frames < args.frames,
            "wall_seconds": time.monotonic() - wall_start,
        }
        for handle in handles.values():
            m.remove_hook(handle)
        m.pause()
        end = paused_snapshot(m)
        rows.append(
            {
                "event": "end",
                "time": time.time(),
                "run_result": run_result,
                **end,
            }
        )

    hook_rows = [row for row in rows if row["event"] == "hook"]
    counts = Counter(str(row["label"]) for row in hook_rows)
    frames_by_label: dict[str, list[int]] = defaultdict(list)
    for row in hook_rows:
        if "frame" in row:
            frames_by_label[str(row["label"])].append(int(row["frame"]))
    summary = {
        "event": "summary",
        "time": time.time(),
        "hook_counts": dict(sorted(counts.items())),
        "hook_frames": {
            label: sorted(set(frames))
            for label, frames in sorted(frames_by_label.items())
        },
        "ticks_advanced": (int(end["tick_0760"]) - int(start["tick_0760"])) & 0xFFFF,
        "snes_irq_handler_fired": counts["snes_irq_handler"] > 0,
        "sa1_request_writes": counts["sa1_scnt_write"],
        "snes_ack_writes": counts["snes_sic_write"],
        "deadline_due_hits": counts["snes_deadline_due"],
    }
    rows.append(summary)

    trace_path = output / "trace.jsonl"
    with trace_path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)
    print(f"raw trace: {trace_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
