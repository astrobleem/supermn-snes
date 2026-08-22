#!/usr/bin/env python3
"""Capture a compact TESTFLAG one-op diagnostic.

This is not gameplay evidence.  It creates a disposable optest ROM with the
requested opcode words, starts the interpreter's TESTFLAG single-step harness,
runs one vector for a bounded number of video frames, and records enough
SA-1/DP/hook state to classify hangs without widening the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

import optest


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_words(value: str) -> list[int]:
    words = [parse_int(part.strip()) for part in value.split(",") if part.strip()]
    if not words:
        raise argparse.ArgumentTypeError("at least one opcode word is required")
    for word in words:
        if not 0 <= word <= 0xFFFF:
            raise argparse.ArgumentTypeError(f"opcode word out of range: {word:#x}")
    return words


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opwords", type=parse_words, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=Path("build/interp.sfc"))
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7661)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--d0", type=parse_int, default=0)
    parser.add_argument("--d1", type=parse_int, default=0)
    parser.add_argument("--a0", type=parse_int, default=optest.OPND)
    parser.add_argument("--ccr", type=parse_int, default=optest.ccr_bits(x=1))
    return parser.parse_args()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def configure_dotnet(path: Path) -> None:
    root = "/home/chad/.dotnet10" if path.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if root.endswith("dotnet10") else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data[0:2]) | (le16(data[2:4]) << 16)


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def symbol(path: Path, bank: int, name: str) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            _sym_bank, address = fields[0].split(":", 1)
            return ((bank & 0xFF) << 16) | int(address, 16)
    raise KeyError(f"missing symbol {name} in {path}")


def hooks() -> dict[str, int]:
    interp = ROOT / "src" / "interp.sym"
    esc5 = ROOT / "src" / "escbank5.sym"
    names = [
        "op_bitop",
        "op_divu",
        "op_divs",
        "op_or_g",
        "kbad",
        "kbad_aq2",
        "udiv",
        "ea_extw",
        "ea_extw_return",
        "ea_resolve",
        "ea_read",
        "inext",
        "idone",
        "idone_test",
        "test_idle",
    ]
    result = {name: symbol(interp, 0x00, name) for name in names}
    result["eaw5_fix"] = symbol(esc5, 0x99, "eaw5_fix")
    return result


def drain_hook_rows(m: McpSession, labels_by_handle: dict[int, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for note in m.drain_notifications(timeout=0.05):
        if note.get("method") != "notifications/mesen/hookFired":
            continue
        params = note.get("params")
        if isinstance(params, dict):
            row = dict(params)
            row["label"] = labels_by_handle.get(int(row.get("handle", -1)), "unknown")
            rows.append(row)
    return rows


def snapshot(m: McpSession) -> dict[str, Any]:
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    dp = bytes(m.read_memory(optest.DP_SPACE, 0x0000, 0x0100))
    return {
        "emulator": dict(m.get_state()),
        "snes_pc": cpu_address(snes),
        "sa1_pc": cpu_address(sa1),
        "snes_cpu": snes,
        "sa1_cpu": sa1,
        "pc68k": le32(dp[0x40:0x44]) & 0x00FFFFFF,
        "opcode_latched": le16(dp[0x44:0x46]),
        "delta": le16(dp[0x46:0x48]),
        "halt": le16(dp[0x4E:0x50]),
        "fetch_ptr": le32(dp[0x5A:0x5E]) & 0x00FFFFFF,
        "flags": {
            "Z": le16(dp[0x60:0x62]),
            "C": le16(dp[0x6E:0x70]),
            "N": le16(dp[0x70:0x72]),
            "V": le16(dp[0x72:0x74]),
            "X": le16(dp[0xA2:0xA4]),
        },
        "bitop": {
            "bitnum": le16(dp[0x88:0x8A]),
            "mask_lo": le16(dp[0x8A:0x8C]),
            "mask_hi": le16(dp[0x8C:0x8E]),
            "modulo": le16(dp[0x8E:0x90]),
            "ea_kind": le16(dp[0x9E:0xA0]),
            "go": le16(dp[0xA0:0xA2]),
        },
        "regs": {
            "D0": le32(dp[0x00:0x04]),
            "D1": le32(dp[0x04:0x08]),
            "A0": le32(dp[0x20:0x24]),
        },
        "dp_0000_00ff": dp.hex(),
        "sa1_disassembly": m.disassemble(cpu_address(sa1), count=24, cpu_type="Sa1"),
        "sa1_trace": m.trace_log(count=128, cpu_type="Sa1"),
    }


def main() -> int:
    args = parse_args()
    args.output = args.output.resolve()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    args.rom = args.rom.resolve()
    args.nexen = args.nexen.resolve()
    configure_dotnet(args.nexen)

    test_sfc = Path(optest._make_test_sfc(args.opwords))
    result: dict[str, Any] = {
        "scope": "TESTFLAG one-op diagnostic; not gameplay evidence",
        "base_rom": str(args.rom),
        "base_rom_sha256": sha256(args.rom),
        "test_rom_sha256": sha256(test_sfc),
        "opwords": args.opwords,
        "frames": args.frames,
        "nexen": str(args.nexen),
    }

    try:
        with McpSession(
            rom=test_sfc,
            mesen=args.nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=3.0,
            socket_timeout=120.0,
            stderr_log=args.output / "emulator.stderr.log",
        ) as m:
            optest._prepare_interp_session(m)
            vector = optest.Vec(
                {"D0": args.d0, "D1": args.d1, "A0": args.a0},
                ccr=args.ccr,
                opnd=b"\x80\x00\x00\x00",
            )
            m.write_memory(optest.DP_SPACE, 0x00, optest._regblk(vector).hex())
            pc = optest.INTERP_CODE_68K
            m.write_memory(
                optest.DP_SPACE,
                0x40,
                bytes([pc & 0xFF, (pc >> 8) & 0xFF, (pc >> 16) & 0xFF, (pc >> 24) & 0xFF]).hex(),
            )
            for address, value in ((0x60, 0), (0x6E, 1), (0x70, 1), (0x72, 1), (0xA2, 1)):
                m.write_memory(optest.DP_SPACE, address, bytes([value, 0]).hex())
            m.write_memory(optest.DP_SPACE, 0x7C, b"\x07\x00".hex())
            m.write_memory(optest.OPND_SPACE, optest.OPND_ADDR, vector.opnd.hex())
            result["pre"] = snapshot(m)
            labels = hooks()
            handles: dict[int, str] = {}
            for label, address in labels.items():
                handles[m.add_exec_hook(address, cpu_type="Sa1")] = label
            m.drain_notifications(timeout=0.05)
            m.write_memory(optest.DP_SPACE, 0x4E, "0000")
            m.write_memory(optest.DP_SPACE, 0xA0, "0100")
            events: list[dict[str, Any]] = []
            for frame in range(1, args.frames + 1):
                m.run_frames(1)
                events.extend(drain_hook_rows(m, handles))
                halt = le16(bytes(m.read_memory(optest.DP_SPACE, 0x4E, 2)))
                if halt:
                    result["completed_frame"] = frame
                    break
            result["events_first"] = events[:128]
            result["events_last"] = events[-128:]
            result["event_count_retained"] = len(events)
            result["hook_labels"] = labels
            result["hook_diag"] = dict(m.hook_diag())
            result["final"] = snapshot(m)
    finally:
        try:
            test_sfc.unlink()
        except FileNotFoundError:
            pass

    out = args.output / "results.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    final = result["final"]
    print(
        json.dumps(
            {
                "result": str(out),
                "completed_frame": result.get("completed_frame"),
                "event_count": result["event_count_retained"],
                "sa1_pc": final["sa1_pc"],
                "pc68k": final["pc68k"],
                "opcode_latched": final["opcode_latched"],
                "delta": final["delta"],
                "halt": final["halt"],
                "bitop": final["bitop"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
