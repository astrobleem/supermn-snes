#!/usr/bin/env python3
"""Same-state differential for a focused native scheduler span.

Use the interpreter's exact-PC freeze control to capture a real $0532 switch-out,
then run that identical complete emulator state under OLD_ROM and NEW_ROM until
the exact downstream $075C fetch.  Scheduler-select is disabled for this narrow
span so the second exact-PC freeze remains reachable; switch-out and the native
disabled-task scan stay enabled.  The comparison covers the emulated 68K
register/flag file, scheduler scratch, all work RAM, and video shadow.  This is a
focused checkpoint differential, not an FPS measurement.
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
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
ENTRY_68K = 0x0532
EXIT_68K = 0x075C


def parse_u24(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFFFFFF:
        raise argparse.ArgumentTypeError("address must fit in 24 bits")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-rom", required=True, type=Path)
    parser.add_argument("--new-rom", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument(
        "--pre-state",
        type=Path,
        help="retained exact-$0532 state; skips recapturing from --state",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7530)
    parser.add_argument("--entry", type=parse_u24, default=ENTRY_68K)
    parser.add_argument("--exit", dest="exit_pc", type=parse_u24, default=EXIT_68K)
    parser.add_argument(
        "--select-gate",
        action="store_true",
        help="enable the native $075C selector while replaying the focused span",
    )
    parser.add_argument(
        "--ignore-pc-ring",
        action="store_true",
        help=(
            "report but do not gate on the $0048 pointer and $0400-$05FF "
            "diagnostic fetch ring (for candidates that deliberately remove a fetch)"
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_dotnet() -> None:
    root = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    path = [item for item in os.environ.get("PATH", "").split(":") if item != root]
    os.environ["PATH"] = ":".join([root, *path])


def byte_diffs(old: bytes, new: bytes, limit: int = 24) -> dict[str, Any]:
    offsets = [index for index, pair in enumerate(zip(old, new)) if pair[0] != pair[1]]
    offsets.extend(range(min(len(old), len(new)), max(len(old), len(new))))
    return {
        "count": len(offsets),
        "first": [
            {
                "offset": offset,
                "old": old[offset] if offset < len(old) else None,
                "new": new[offset] if offset < len(new) else None,
            }
            for offset in offsets[:limit]
        ],
    }


def selected_byte_diffs(
    old: bytes, new: bytes, offsets: range | list[int], limit: int = 24
) -> dict[str, Any]:
    changed = [offset for offset in offsets if old[offset] != new[offset]]
    return {
        "count": len(changed),
        "first": [
            {"offset": offset, "old": old[offset], "new": new[offset]}
            for offset in changed[:limit]
        ],
    }


DMA_STAGE_START = 0x0100
DMA_STAGE_END = DMA_STAGE_START + 60


def snapshot(m: McpSession) -> dict[str, Any]:
    m.pause()
    return {
        "iram": bytes(m.read_memory("Sa1Memory", 0x000000, 0x0800)),
        "work": bytes(m.read_memory("snesMemory", 0x400000, 0x10000)),
        "video": bytes(m.read_memory("snesMemory", 0x410000, 0x8000)),
        "cpu": dict(m.get_cpu_state("Sa1")),
        "machine": dict(m.get_state()),
    }


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def exact_pc_freeze(m: McpSession, address: int, release: bool, max_frames: int) -> None:
    def r16(offset: int) -> int:
        return le16(m.read_memory("Sa1Memory", offset, 2))

    m.pause()
    already_frozen = bool(r16(0x0712))
    m.write_u16(0x0712, 0, "Sa1Memory")
    m.write_u16(0x0714, 0, "Sa1Memory")
    m.write_u16(0x0716, 0, "Sa1Memory")
    m.write_u16(0x0710, address, "Sa1Memory")
    if release or already_frozen:
        # df_gap otherwise clears the (already retargeted) one-shot $0710
        # immediately after leaving the prior freeze.  Soak checkpoints are
        # normally parked at $0818, so detect and release that state instead
        # of waiting forever inside its existing debug spin.
        m.write_u16(0x0730, 0x5A5A, "Sa1Memory")
        m.write_u16(0x0714, 1, "Sa1Memory")
        release = True
    for _ in range(max_frames):
        m.run_frames(1)
        m.pause()
        if release:
            m.write_u16(0x0714, 0, "Sa1Memory")
            release = False
        if r16(0x0712):
            pc = le16(m.read_memory("Sa1Memory", 0x0040, 2))
            bank = le16(m.read_memory("Sa1Memory", 0x0042, 2)) & 0xFF
            if ((bank << 16) | pc) != address:
                # Some retained checkpoints have the marker cleared while
                # the SA-1 is still parked in the old $0818 freeze loop.  A
                # requested frame then reasserts that stale marker.  Retarget
                # and release it in-place; the persistent gate keeps the new
                # address armed until its real fetch.
                m.write_u16(0x0712, 0, "Sa1Memory")
                m.write_u16(0x0710, address, "Sa1Memory")
                m.write_u16(0x0716, 0, "Sa1Memory")
                m.write_u16(0x0730, 0x5A5A, "Sa1Memory")
                m.write_u16(0x0714, 1, "Sa1Memory")
                release = True
                continue
            return
    m.pause()
    iram = bytes(m.read_memory("Sa1Memory", 0x000000, 0x0800))
    emulated_pc = ((le16(iram[0x42:0x44]) & 0xFF) << 16) | le16(
        iram[0x40:0x42]
    )
    marker = le16(iram[0x0712:0x0714])
    cpu = dict(m.get_cpu_state("Sa1"))
    raise RuntimeError(
        f"exact-PC freeze ${address:06X} not reached in {max_frames} frames; "
        f"last 68K PC=${emulated_pc:06X}, marker=${marker:04X}, "
        f"SA-1={json.dumps(cpu, sort_keys=True)}"
    )


def session(rom: Path, nexen: Path, port: int, stderr_log: Path) -> McpSession:
    return McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    )


def main() -> int:
    args = parse_args()
    paths = (args.old_rom, args.new_rom, args.state, args.nexen)
    if args.pre_state is not None:
        paths = (*paths, args.pre_state)
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_dotnet()

    pre_state = args.output / "pre_switchout.mss"
    if args.pre_state is not None:
        shutil.copy2(args.pre_state, pre_state)
        with session(
            args.old_rom,
            args.nexen,
            args.port,
            args.output / "capture.stderr.log",
        ) as m:
            m.pause()
            m.load_state(pre_state)
            captured = snapshot(m)
        captured_pc = (
            (le16(captured["iram"][0x42:0x44]) & 0xFF) << 16
        ) | le16(captured["iram"][0x40:0x42])
        if captured_pc != args.entry:
            raise RuntimeError(
                f"--pre-state PC ${captured_pc:06X}, expected ${args.entry:06X}"
            )
    else:
        with session(
            args.old_rom,
            args.nexen,
            args.port,
            args.output / "capture.stderr.log",
        ) as m:
            m.pause()
            m.load_state(args.state)
            m.pause()
            exact_pc_freeze(m, args.entry, release=False, max_frames=30)
            m.save_state(pre_state)
            captured = snapshot(m)

    outputs: dict[str, dict[str, Any]] = {}
    for index, (label, rom) in enumerate((('old', args.old_rom), ('new', args.new_rom)), 1):
        with session(
            rom,
            args.nexen,
            args.port + index,
            args.output / f"{label}.stderr.log",
        ) as m:
            m.pause()
            m.load_state(pre_state)
            m.pause()
            # The default switch-out test forces the downstream selector to
            # hand $075C back to the interpreter.  Selector-focused tests can
            # instead retain its production magic gate and park at a later PC.
            m.write_u16(
                0x0736, 0x5EEC if args.select_gate else 0, "Sa1Memory"
            )
            start = snapshot(m)
            exact_pc_freeze(m, args.exit_pc, release=True, max_frames=5)
            end = snapshot(m)
        for region in ("iram", "work", "video"):
            (args.output / f"{label}_{region}.bin").write_bytes(end[region])
        outputs[label] = {"start": start, "end": end}

    old_iram = outputs["old"]["end"]["iram"]
    new_iram = outputs["new"]["end"]["iram"]
    old_sp = int(outputs["old"]["end"]["cpu"].get("sp", -1))
    new_sp = int(outputs["new"]["end"]["cpu"].get("sp", -2))
    # $0788 begins immediately above the highest native instrumentation cell
    # ($0786).  When both variants end with the same S, bytes through S are
    # popped/free native-stack residue; live return bytes above S remain in the
    # observable comparison.
    free_stack_offsets: list[int] = []
    if old_sp == new_sp and 0x0788 <= old_sp < len(old_iram):
        free_stack_offsets = list(range(0x0788, old_sp + 1))
    pc_ring_offsets = (
        [0x48, 0x49, *range(0x0400, 0x0600)] if args.ignore_pc_ring else []
    )
    native_only = (
        set(range(DMA_STAGE_START, DMA_STAGE_END))
        | set(free_stack_offsets)
        | set(pc_ring_offsets)
    )
    observable_offsets = [
        offset for offset in range(len(old_iram)) if offset not in native_only
    ]
    memory_diffs = {
        "iram_observable": selected_byte_diffs(
            old_iram, new_iram, observable_offsets
        ),
        "iram_dma_staging": selected_byte_diffs(
            old_iram, new_iram, list(range(DMA_STAGE_START, DMA_STAGE_END))
        ),
        "iram_native_stack_free_residue": selected_byte_diffs(
            old_iram, new_iram, free_stack_offsets
        ),
        "iram_diagnostic_pc_ring": selected_byte_diffs(
            old_iram, new_iram, pc_ring_offsets
        ),
        "work": byte_diffs(outputs["old"]["end"]["work"], outputs["new"]["end"]["work"]),
        "video": byte_diffs(outputs["old"]["end"]["video"], outputs["new"]["end"]["video"]),
    }
    ignored_cpu_fields = {"cycleCount"}
    old_cpu = {
        key: value
        for key, value in outputs["old"]["end"]["cpu"].items()
        if key not in ignored_cpu_fields
    }
    new_cpu = {
        key: value
        for key, value in outputs["new"]["end"]["cpu"].items()
        if key not in ignored_cpu_fields
    }
    cpu_diffs = {
        key: {"old": old_cpu.get(key), "new": new_cpu.get(key)}
        for key in sorted(set(old_cpu) | set(new_cpu))
        if old_cpu.get(key) != new_cpu.get(key)
    }
    result = {
        "scope": "same-state focused native scheduler differential; not fps",
        "entry_68k": f"{args.entry:06X}",
        "exit_68k": f"{args.exit_pc:06X}",
        "select_gate": args.select_gate,
        "diagnostic_pc_ring_ignored": args.ignore_pc_ring,
        "old_rom": str(args.old_rom.resolve()),
        "old_rom_sha256": sha256(args.old_rom),
        "new_rom": str(args.new_rom.resolve()),
        "new_rom_sha256": sha256(args.new_rom),
        "source_state": str(args.state.resolve()),
        "source_state_sha256": sha256(args.state),
        "supplied_pre_state": (
            str(args.pre_state.resolve()) if args.pre_state is not None else None
        ),
        "captured_state_sha256": sha256(pre_state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "captured_68k_pc": (
            (le16(captured["iram"][0x42:0x44]) & 0xFF) << 16
        ) | le16(captured["iram"][0x40:0x42]),
        "memory_diffs": memory_diffs,
        "cpu_diffs_excluding_cycle_count": cpu_diffs,
    }
    # Both variants spend the rest of the host-requested video frame in the
    # freeze loop, so native A/X/Y/P/PC phase is not an observable contract.
    # The emulated machine memory is the load-bearing comparison.
    # IRAM $0100-$013B is the declared DMA staging buffer, while popped native
    # stack bytes through the identical final S are implementation residue. A
    # caller may additionally exempt the diagnostic-only fetch ring when the
    # candidate's entire purpose is to remove a redundant fetch. Retain and
    # report every exempt-region difference, but gate the semantic verdict on
    # all emulated and live-native bytes outside those explicit regions.
    green = all(
        memory_diffs[name]["count"] == 0
        for name in ("iram_observable", "work", "video")
    )
    result["result"] = "green" if green else "red"
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
