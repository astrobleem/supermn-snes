#!/usr/bin/env python3
"""Probe one exact `$02429C` F3 parent→interpreted-child→return route."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

import sys

sys.path.insert(0, str(ROOT / "tools"))
import validate_175a0_native as common  # noqa: E402
import validate_2429c_native as root_validator  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol(path: Path, name: str) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing {name} in {path}")


def read_u16(m: common.base.McpSession, address: int) -> int:
    return int.from_bytes(m.read_memory("Sa1Memory", address, 2), "little")


def snapshot(m: common.base.McpSession) -> dict[str, object]:
    a7 = read_u16(m, 0x3C) | (read_u16(m, 0x3E) << 16)
    virtual_pc = read_u16(m, 0x40) | ((read_u16(m, 0x42) & 0xFF) << 16)
    return {
        "sa1_pc": f"{int(m.get_cpu_state('Sa1')['pc']):06X}",
        "virtual_pc": f"{virtual_pc:06X}",
        "a7": f"{a7:08X}",
        "gate_071a": read_u16(m, 0x071A),
        "stack_top": bytes(
            m.read_memory("snesMemory", 0x400000 + (a7 & 0xFFFF), 8)
        ).hex(),
    }


def run_to(m: common.base.McpSession, pc: int) -> tuple[dict, dict[str, object]]:
    hook = m.add_exec_hook(pc, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        response = m.run_until(max_frames=8, hook_handle=hook)
        m.pause()
        return response, snapshot(m)
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)


def prepare(m: common.base.McpSession, nat: Path, case: common.LiveCase) -> None:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(
        common.base.le32(case.regs[name]) for name in common.base.REG_NAMES
    )
    m.write_memory(common.base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            common.base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset:offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)
    flags = case.sr & common.base.CCR_MASK
    for address, value in (
        (0x6E, flags & 1),
        (0x72, (flags >> 1) & 1),
        (0x60, (flags >> 2) & 1),
        (0x70, (flags >> 3) & 1),
        (0xA2, (flags >> 4) & 1),
        (0x7C, (case.sr >> 8) & 7),
        (0x40, root_validator.ENTRY_PC & 0xFFFF),
        (0x42, root_validator.ENTRY_PC >> 16),
        (0xA4, case.regs["A7"] & 0xFFFF),
        (0xA6, case.regs["A7"] >> 16),
        (0xA8, 1),
        (0xAA, 0),
        (0xAC, 0xFFFF),
        (0x0702, 0),
        (0x0704, 1),
        (0x071A, 1),
        (0x072E, 0),
        (0x0734, 0),
        (0x073A, 0),
    ):
        common.write_u16(m, address, value)
    common.base.set_sa1_pc(m, 0xF38000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--nat", type=Path, default=Path("/tmp/b0_native.mss"))
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=common.base.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9354)
    args = parser.parse_args()
    for path in (args.rom, args.nat, args.fixtures, args.nexen):
        if not path.exists():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")

    case = root_validator.load_cases(args.fixtures, 1)[0]
    syms = ROOT / "src/vtime_esc5_root.sym"
    gateway = 0xF30000 | symbol(syms, "vtime_esc5_ojmp_gateway")
    inext = 0x00D128
    return_dispatch = 0xF30000 | symbol(syms, "vtime_esc5_return_dispatch")
    rows: dict[str, object] = {
        "scope": "one forced exact F3 parent/child route; diagnostic only",
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "fixture": case.name,
    }
    with common.base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output.with_suffix(".stderr.log"),
    ) as m:
        prepare(m, args.nat.resolve(), case)
        rows["entry"] = snapshot(m)
        response, state = run_to(m, gateway)
        rows["parent_gateway"] = {"response": response, **state}
        response, state = run_to(m, inext)
        rows["child_inext"] = {"response": response, **state}
        response, state = run_to(m, return_dispatch)
        rows["return_dispatch"] = {"response": response, **state}
        return_pc = int(str(state["virtual_pc"]), 16)
        returns = root_validator.RETURN_CONTINUATIONS[:11]
        matching = [item for item in returns if item[1] == return_pc]
        if len(matching) != 1:
            rows["result"] = "red"
        else:
            continuation = matching[0][2]
            continuation_pc = 0xF30000 | symbol(syms, continuation)
            response, state = run_to(m, continuation_pc)
            rows["parent_continuation"] = {
                "symbol": continuation,
                "response": response,
                **state,
            }
            rows["result"] = "green" if state["gate_071a"] == 1 else "red"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "result": rows["result"],
        "summary": str(args.output),
        "gateway": rows.get("parent_gateway"),
        "child": rows.get("child_inext"),
        "return": rows.get("return_dispatch"),
        "continuation": rows.get("parent_continuation"),
    }, sort_keys=True))
    return 0 if rows["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
