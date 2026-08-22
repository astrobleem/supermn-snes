#!/usr/bin/env python3
"""Stop before a dangerous native gm_memset store.

The boot regression reaches gm_memset_far ($99:F5C0) shortly before low SA-1
state is overwritten.  This diagnostic loads a retained checkpoint, stops at
each gm_memset entry, decodes the candidate idiom, then stops at the first byte
or word write-loop instruction before any store executes.  It retains compact
JSON and the pre-store state for the first low-destination write.
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
MESEN_PYTHON = Path("/home/chad/Mesen2/python")
for path in (ROOT / "tools", MESEN_PYTHON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = (
    "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
)

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_EMULATOR = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)
GM_ENTRY = 0x99F5C0
GMS_FB = 0x99F649
GMS_FWLP = 0x99F657
GMS_NO = 0x99F5CF
GMS_TAIL = 0x99F66C


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data[0:2]) | (le16(data[2:4]) << 16)


def be_word_from_bus(raw: bytes) -> int:
    return int.from_bytes(raw[0:2], "big")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hook_rows(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(note.get("params", {}))
        for note in notes
        if note.get("method") == "notifications/mesen/hookFired"
    ]


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def reg_dump(dp: bytes) -> dict[str, int]:
    names = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"] + [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
    ]
    return {
        name: le32(dp[index * 4 : index * 4 + 4])
        for index, name in enumerate(names)
    }


def read68k_code(m: McpSession, pc: int, length: int = 8) -> bytes:
    if (pc >> 16) == 0x00F0:
        return bytes(m.read_memory("snesMemory", 0x400000 | (pc & 0xFFFF), length))
    return bytes(m.read_memory("snesMemory", 0xC10000 + (pc & 0x7FFFF), length))


def decode_candidate(m: McpSession, dp: bytes) -> dict[str, Any]:
    opcode = le16(dp[0x44:0x46])
    masked = opcode & 0xF1F8
    size = 1 if masked == 0x10C0 else 2 if masked == 0x30C0 else 0
    pc = le32(dp[0x40:0x44]) & 0x00FFFFFF
    code = read68k_code(m, pc, 8)
    subq = be_word_from_bus(code[2:4])
    branch = be_word_from_bus(code[4:6])
    dm_index = subq & 0x0007
    dm_off = dm_index * 4
    an_index = (opcode & 0x0E00) >> 9
    an_off = 0x20 + an_index * 4
    dn_index = opcode & 0x0007
    dn_off = dn_index * 4
    regs = reg_dump(dp[0x00:0x40])
    count = le32(dp[dm_off : dm_off + 4])
    dest = le32(dp[an_off : an_off + 4])
    value = le32(dp[dn_off : dn_off + 4])
    accepted = (
        size != 0
        and (subq & 0xFFF8) == 0x5380
        and branch == 0x66FA
        and (count >> 16) == 0
        and (count & 0xFFFF) != 0
        and (dest >> 16) == 0x00F0
    )
    return {
        "pc68k": f"{pc:06X}",
        "opcode": f"{opcode:04X}",
        "code8": code.hex(),
        "size": size,
        "subq": f"{subq:04X}",
        "branch": f"{branch:04X}",
        "dm": f"D{dm_index}",
        "an": f"A{an_index}",
        "dn": f"D{dn_index}",
        "count": count,
        "dest": f"{dest:08X}",
        "dest_low": dest & 0xFFFF,
        "value": f"{value:08X}",
        "accepted": accepted,
        "regs_subset": {
            key: regs[key]
            for key in ("D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "A0", "A1", "A5")
        },
    }


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    state = dict(m.get_state())
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    dp = bytes(m.read_memory("Sa1Memory", 0, 0x800))
    return {
        "label": label,
        "frame": int(state.get("frameCount", 0)),
        "snes_pc": f"{cpu_address(snes):06X}",
        "sa1_pc": f"{cpu_address(sa1):06X}",
        "snes_cpu": snes,
        "sa1_cpu": sa1,
        "tick": le16(dp[0x760:0x762]),
        "task_mask": le16(bytes(m.read_memory("snesMemory", 0x400002, 2))),
        "halt": le16(dp[0x4E:0x50]),
        "dp_40_5f": dp[0x40:0x60].hex(),
        "dp_740_74f": dp[0x740:0x750].hex(),
        "iram_0600_061f": dp[0x600:0x620].hex(),
        "candidate": decode_candidate(m, dp[0x00:0x100]),
    }


def run_to_one(m: McpSession, label: str, address: int, max_frames: int) -> dict[str, Any]:
    m.drain_notifications(timeout=0.05)
    handle = m.add_exec_hook(address, cpu_type="Sa1")
    try:
        hit = dict(m.run_until(max_frames=max_frames, hook_handle=handle))
        m.pause()
        events = hook_rows(m.drain_notifications(timeout=0.2))
        return {"label": label, "address": f"{address:06X}", "hit": hit, "events": events}
    finally:
        m.remove_hook(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--port", type=int, default=8884)
    parser.add_argument("--max-entries", type=int, default=32)
    parser.add_argument("--entry-max-frames", type=int, default=80)
    parser.add_argument("--low-dest-limit", type=lambda value: int(value, 0), default=0x0800)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)

    result: dict[str, Any] = {
        "scope": "gm_memset native escape pre-store diagnostic; not acceptance evidence",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "low_dest_limit": args.low_dest_limit,
        "events": [],
        "samples": [],
        "verdict": "not_run",
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        result["load_state"] = dict(m.load_state(args.state.resolve()))
        m.pause()
        for index in range(args.max_entries):
            entry_event = run_to_one(m, f"gm_entry_{index}", GM_ENTRY, args.entry_max_frames)
            result["events"].append(entry_event)
            if entry_event["hit"].get("reason") != "hookFired":
                result["verdict"] = "entry_not_reached"
                break
            entry = snapshot(m, f"gm_entry_{index}")
            result["samples"].append(entry)
            candidate = entry["candidate"]
            if not candidate["accepted"]:
                run_to_one(m, f"gm_no_{index}", GMS_NO, 2)
                continue
            loop_label = "gms_fb" if candidate["size"] == 1 else "gms_fwlp"
            loop_addr = GMS_FB if candidate["size"] == 1 else GMS_FWLP
            loop_event = run_to_one(m, f"{loop_label}_{index}", loop_addr, 2)
            result["events"].append(loop_event)
            loop = snapshot(m, f"{loop_label}_{index}")
            result["samples"].append(loop)
            loop_cpu = loop["sa1_cpu"]
            if int(loop_cpu.get("x", 0)) < args.low_dest_limit:
                state_path = args.output / f"danger-pre-store-{index}.mss"
                m.save_state(state_path.resolve())
                result["danger_state"] = str(state_path.resolve())
                result["verdict"] = "dangerous_low_destination_before_store"
                break
            run_to_one(m, f"gms_tail_{index}", GMS_TAIL, 4)
        else:
            result["verdict"] = "max_entries_without_danger"

    out = args.output / "results.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": str(out),
                "verdict": result["verdict"],
                "rom_sha256": result["rom_sha256"],
                "samples": [
                    {
                        "label": row["label"],
                        "frame": row["frame"],
                        "sa1_pc": row["sa1_pc"],
                        "pc68k": row["candidate"]["pc68k"],
                        "accepted": row["candidate"]["accepted"],
                        "size": row["candidate"]["size"],
                        "dest": row["candidate"]["dest"],
                        "count": row["candidate"]["count"],
                        "x": row["sa1_cpu"].get("x"),
                    }
                    for row in result["samples"][-8:]
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 1 if result["verdict"].startswith("dangerous") else 0


if __name__ == "__main__":
    raise SystemExit(main())
