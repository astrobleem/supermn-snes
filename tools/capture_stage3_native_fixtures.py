#!/usr/bin/env python3
"""Capture exact-Mesen architectural fixtures with the PC-ring recorder.

This is a checkpointed fixture generator for bounded three-way differentials,
not fresh-boot or performance evidence.  It forces both native gates off so a
requested 68000 PC is reached through the interpreter, freezes before that
instruction executes, and retains:

* every D/A register and CCR/X;
* all 64 KiB of the SNES work-RAM backing allocation;
* the genuine stacked return and surrounding residue; and
* a same-emulator pre-entry save state.

The selected ROM must have been built with ``PC_RING=1``.  A normal production
ROM deliberately branches over the recorder call and cannot satisfy this
harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
DEBUG_SPIN = 0x00E2CF
DEBUG_RELEASE = 0x00E2D2
FULL_WORK_SIZE = 0x10000

sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_targets(text: str) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    seen: set[int] = set()
    for item in text.split(","):
        fields = item.strip().split(":")
        if len(fields) != 2:
            raise ValueError(
                f"invalid target {item!r}; expected hexadecimal-PC:count"
            )
        pc, count = int(fields[0], 16), int(fields[1], 0)
        if not 0 <= pc <= 0xFFFFFF or count <= 0 or pc in seen:
            raise ValueError(f"invalid or duplicate target {item!r}")
        seen.add(pc)
        result.append((pc, count))
    if not result:
        raise ValueError("no targets requested")
    return result


def read_u16(m: McpSession, address: int) -> int:
    return int(m.read_u16(address, "Sa1Memory"))


def write_u16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, "Sa1Memory")


def captured_regs(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("Sa1Memory", 0x00, 0x40))
    names = [f"D{index}" for index in range(8)] + [
        f"A{index}" for index in range(8)
    ]
    return {
        name: int.from_bytes(
            raw[index * 4 : index * 4 + 4], "little"
        )
        for index, name in enumerate(names)
    }


def captured_sr(m: McpSession) -> int:
    ccr = (
        (1 if read_u16(m, 0x6E) else 0)
        | ((1 if read_u16(m, 0x72) else 0) << 1)
        | ((1 if read_u16(m, 0x60) else 0) << 2)
        | ((1 if read_u16(m, 0x70) else 0) << 3)
        | ((1 if read_u16(m, 0xA2) else 0) << 4)
    )
    return 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | ccr


def refresh_video_mirror(
    m: McpSession,
    rom_data: bytes,
) -> dict[str, object]:
    mirror = rom_data[
        VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
    ]
    if len(mirror) != VIDEO_WRAM_LENGTH:
        raise RuntimeError("selected ROM has a short video mirror")
    before = bytes(
        m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        )
    )
    for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
        m.write_memory(
            "snesWorkRam",
            VIDEO_WRAM_OFFSET + offset,
            mirror[offset : offset + 0x1000].hex(),
        )
    observed = bytes(
        m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        )
    )
    if observed != mirror:
        raise RuntimeError("selected-ROM video mirror refresh did not verify")
    return {
        "kind": "checkpoint_video_mirror_refresh",
        "region": "snesWorkRam $7F:8000-$AFFF",
        "length": VIDEO_WRAM_LENGTH,
        "differing_bytes": sum(a != b for a, b in zip(before, mirror)),
        "sha256": hashlib.sha256(mirror).hexdigest(),
    }


def release_freeze(m: McpSession, spin_hook: int) -> int:
    m.remove_hook(spin_hook)
    write_u16(m, 0x0714, 1)
    release_hook = m.add_exec_hook(DEBUG_RELEASE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        hit = m.run_until(max_frames=4, hook_handle=release_hook)
        m.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"recorder release did not reach $00:E2D2: {hit!r}"
            )
    finally:
        m.remove_hook(release_hook)
        m.drain_notifications(timeout=0.05)
    return m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")


def wait_for_save(path: Path) -> None:
    for _ in range(600):
        if path.is_file() and path.stat().st_size:
            return
        import time

        time.sleep(0.05)
    raise TimeoutError(f"save state did not appear: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--targets", required=True, type=parse_targets)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=9160)
    args = parser.parse_args()

    for label, path in (
        ("PC-ring ROM", args.rom),
        ("checkpoint", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    rom = args.rom.resolve()
    state = args.state.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True)
    rom_data = rom.read_bytes()
    if len(rom_data) != 0x400000:
        parser.error("expected a 4 MiB ROM")
    # Production branches over both per-fetch recorder calls.  PC_RING=1
    # restores the same JSR in the normal and alternate fetch paths.
    pc_ring_call = bytes.fromhex("2081e2")
    pc_ring_offsets = (0x00EB, 0x80EB)
    pc_ring_bytes = [
        rom_data[offset : offset + len(pc_ring_call)]
        for offset in pc_ring_offsets
    ]
    if pc_ring_bytes != [pc_ring_call, pc_ring_call]:
        parser.error("selected ROM is not a PC_RING=1 diagnostic build")

    rows: list[dict[str, object]] = []
    provenance: dict[str, object] = {
        "event": "provenance",
        "scope": (
            "checkpointed exact-Mesen PC-ring architectural fixtures; both "
            "native gates forced off; not fps or fresh-boot evidence"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "mesen": str(args.mesen.resolve()),
        "mesen_sha256": sha256(args.mesen),
        "targets": [
            {"pc": f"{pc:06X}", "count": count}
            for pc, count in args.targets
        ],
        "pc_ring_recorder_calls": {
            f"file_0x{offset:04X}": value.hex()
            for offset, value in zip(pc_ring_offsets, pc_ring_bytes)
        },
        "capture_gates": {"071a": 0, "073a": 0},
    }
    rows.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    with McpSession(
        rom=str(rom),
        mesen=str(args.mesen.resolve()),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "mesen.stderr.log",
    ) as m:
        for target, count in args.targets:
            m.pause()
            m.load_state(str(state))
            m.pause()
            intervention = refresh_video_mirror(m, rom_data)
            m.set_input(0, 1)
            m.pause()
            write_u16(m, 0x071A, 0)
            write_u16(m, 0x073A, 0)
            spin_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            try:
                for index in range(count):
                    write_u16(m, 0x0710, target & 0xFFFF)
                    write_u16(m, 0x0712, 0)
                    write_u16(m, 0x0714, 0)
                    write_u16(m, 0x0716, (target >> 16) & 0xFF)
                    write_u16(m, 0x0718, 0xFFF8)
                    write_u16(m, 0x0730, 0x5A5A)
                    advanced = 0
                    hit: dict[str, object] = {}
                    attempts = 0
                    while advanced < 3600 and attempts < 16:
                        attempts += 1
                        hit = m.run_until(
                            max_frames=min(900, 3600 - advanced),
                            hook_handle=spin_hook,
                        )
                        m.pause()
                        advanced += int(hit.get("framesAdvanced", 0))
                        if (hit or {}).get("reason") == "hookFired":
                            break
                    observed_pc = read_u16(m, 0x40) | (
                        (read_u16(m, 0x42) & 0xFF) << 16
                    )
                    if (
                        (hit or {}).get("reason") != "hookFired"
                        or read_u16(m, 0x0712) != 1
                        or observed_pc != target
                    ):
                        raise RuntimeError(
                            f"${target:06X} case {index} failed to freeze: "
                            f"hit={hit!r}, marker={read_u16(m, 0x0712)}, "
                            f"pc=${observed_pc:06X}, frames={advanced}, "
                            f"attempts={attempts}"
                        )
                    regs = captured_regs(m)
                    work = bytes(
                        m.read_memory(
                            "snesMemory", 0x400000, FULL_WORK_SIZE
                        )
                    )
                    a4off = regs["A4"] & 0xFFFF
                    a7off = regs["A7"] & 0xFFFF
                    if a7off > FULL_WORK_SIZE - 4:
                        raise RuntimeError(
                            f"unmapped A7 in fixture: ${regs['A7']:08X}"
                        )
                    return_pc = int.from_bytes(
                        work[a7off : a7off + 4], "big"
                    ) & 0xFFFFFF
                    case_dir = output / f"{target:06x}-{index:02d}"
                    case_dir.mkdir()
                    work_path = case_dir / "entry.work.bin"
                    state_path = case_dir / "pre-entry.mss"
                    work_path.write_bytes(work)
                    m.save_state(str(state_path))
                    wait_for_save(state_path)
                    row: dict[str, object] = {
                        "event": "fixture",
                        "target": f"{target:06X}",
                        "index": index,
                        "frame": int(
                            m.get_state().get("frameCount", 0)
                        ),
                        "sa1_cycle": int(
                            m.get_cpu_state("Sa1")["cycleCount"]
                        ),
                        "tick": int.from_bytes(
                            work[0x1C56:0x1C58], "big"
                        ),
                        "sr": captured_sr(m),
                        "regs": regs,
                        "a4": f"{regs['A4'] & 0xFFFFFF:06X}",
                        "a7": f"{regs['A7'] & 0xFFFFFF:06X}",
                        "return_pc": f"{return_pc:06X}",
                        "state": work[(a4off + 0x16) & 0xFFFF],
                        "substate": work[(a4off + 0x17) & 0xFFFF],
                        "object_record_hex": bytes(
                            work[(a4off + offset) & 0xFFFF]
                            for offset in range(0x40)
                        ).hex(),
                        "stack_window_hex": work[
                            max(0, a7off - 64) :
                            min(FULL_WORK_SIZE, a7off + 16)
                        ].hex(),
                        "work": str(work_path),
                        "work_sha256": sha256(work_path),
                        "pre_entry_state": str(state_path),
                        "pre_entry_state_sha256": sha256(state_path),
                        "intervention": intervention,
                        "gates": {"071a": 0, "073a": 0},
                    }
                    (case_dir / "entry.json").write_text(
                        json.dumps(row, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    rows.append(row)
                    print(json.dumps(row, sort_keys=True), flush=True)
                    if index + 1 < count:
                        spin_hook = release_freeze(m, spin_hook)
                        m.drain_notifications(timeout=0.05)
            finally:
                try:
                    m.remove_hook(spin_hook)
                except Exception:
                    pass
                m.drain_notifications(timeout=0.05)

    summary = {
        "event": "summary",
        "fixture_count": sum(
            row.get("event") == "fixture" for row in rows
        ),
        "result": "green",
    }
    rows.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (output / "fixtures.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
    os.environ["PATH"] = (
        "/home/chad/.dotnet8:/home/chad/.dotnet10:"
        + os.environ.get("PATH", "")
    )
    raise SystemExit(main())
