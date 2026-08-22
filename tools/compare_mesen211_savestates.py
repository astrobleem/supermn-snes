#!/usr/bin/env python3
"""Compare two Legacy Mesen 2.1.1 MSS files without launching an emulator.

The container layout and serializer records follow Mesen2's
``Core/Shared/SaveStateManager.cpp`` and ``Utilities/Serializer.cpp``.  The
report is diagnostic only: it exposes serialized changes but cannot establish
that either checkpoint is a safe resumable boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def parse_mss(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data[:3] != b"MSS":
        raise ValueError(f"not an MSS file: {path}")
    offset = 3
    emu_version, offset = read_u32(data, offset)
    format_version, offset = read_u32(data, offset)
    console_type, offset = read_u32(data, offset)
    framebuffer_size, offset = read_u32(data, offset)
    width, offset = read_u32(data, offset)
    height, offset = read_u32(data, offset)
    scale_percent, offset = read_u32(data, offset)
    video_compressed_size, offset = read_u32(data, offset)
    video = zlib.decompress(data[offset : offset + video_compressed_size])
    offset += video_compressed_size
    if len(video) != framebuffer_size:
        raise ValueError(f"framebuffer size mismatch in {path}")
    name_length, offset = read_u32(data, offset)
    rom_name = data[offset : offset + name_length].decode("utf-8")
    offset += name_length
    compressed = data[offset]
    offset += 1
    if compressed != 1:
        raise ValueError(f"expected compressed serializer payload in {path}")
    state_size, offset = read_u32(data, offset)
    state_compressed_size, offset = read_u32(data, offset)
    state = zlib.decompress(data[offset : offset + state_compressed_size])
    offset += state_compressed_size
    if len(state) != state_size or offset != len(data):
        raise ValueError(f"serializer size mismatch in {path}")

    values: dict[str, bytes] = {}
    cursor = 0
    while cursor < len(state):
        end = state.index(0, cursor)
        key = state[cursor:end].decode("ascii")
        cursor = end + 1
        value_size, cursor = read_u32(state, cursor)
        values[key] = state[cursor : cursor + value_size]
        cursor += value_size
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "header": {
            "emu_version": emu_version,
            "format_version": format_version,
            "console_type": console_type,
            "rom_name": rom_name,
            "framebuffer_size": framebuffer_size,
            "width": width,
            "height": height,
            "scale_percent": scale_percent,
            "video_sha256": hashlib.sha256(video).hexdigest(),
            "state_size": state_size,
            "state_sha256": hashlib.sha256(state).hexdigest(),
        },
        "values": values,
    }


def changed_ranges(before: bytes, after: bytes) -> list[list[int]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    ranges: list[list[int]] = []
    for index in changed:
        if not ranges or index > ranges[-1][1] + 1:
            ranges.append([index, index])
        else:
            ranges[-1][1] = index
    return ranges


def scalar(data: bytes) -> dict[str, Any]:
    return {"hex_le": data.hex(), "unsigned_le": int.from_bytes(data, "little")}


def summarize_value(before: bytes, after: bytes, max_ranges: int) -> dict[str, Any]:
    if len(before) != len(after):
        return {"before_size": len(before), "after_size": len(after)}
    if len(before) <= 8:
        return {"size": len(before), "before": scalar(before), "after": scalar(after)}
    ranges = changed_ranges(before, after)
    excerpts = []
    for start, end in ranges[:max_ranges]:
        excerpts.append(
            {
                "start": start,
                "end": end,
                "before_hex": before[start : end + 1].hex(),
                "after_hex": after[start : end + 1].hex(),
            }
        )
    return {
        "size": len(before),
        "changed_bytes": sum(left != right for left, right in zip(before, after)),
        "changed_range_count": len(ranges),
        "changed_ranges": excerpts,
        "omitted_range_count": max(0, len(ranges) - len(excerpts)),
    }


def focus(values: dict[str, bytes]) -> dict[str, Any]:
    iram = values["cart.coprocessor.iRam"]
    names = {
        "sa1_pc": "cart.coprocessor.cpu.pc",
        "sa1_sp": "cart.coprocessor.cpu.sp",
        "sa1_ps": "cart.coprocessor.cpu.ps",
        "sa1_irq_source": "cart.coprocessor.cpu.irqSource",
        "s_cpu_to_sa1_irq_requested": "cart.coprocessor.sa1IrqRequested",
        "s_cpu_to_sa1_irq_enabled": "cart.coprocessor.sa1IrqEnabled",
        "sa1_to_s_cpu_irq_requested": "cart.coprocessor.cpuIrqRequested",
        "sa1_to_s_cpu_irq_enabled": "cart.coprocessor.cpuIrqEnabled",
    }
    result = {name: scalar(values[key]) for name, key in names.items()}
    result.update(
        {
            "virtual_68k_pc": scalar(iram[0x40:0x44]),
            "virtual_irq_countdown_ac": scalar(iram[0xAC:0xAE]),
            "sa1_stack_07f0_07ff": iram[0x7F0:0x800].hex(),
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-ranges", type=int, default=32)
    args = parser.parse_args()
    before = parse_mss(args.before)
    after = parse_mss(args.after)
    before_values = before.pop("values")
    after_values = after.pop("values")
    changed = sorted(
        key
        for key in before_values.keys() & after_values.keys()
        if before_values[key] != after_values[key]
    )
    report = {
        "scope": "disk-only Legacy Mesen serialized-state comparison; diagnostic, not resumability evidence",
        "before": before,
        "after": after,
        "changed_key_count": len(changed),
        "only_before": sorted(before_values.keys() - after_values.keys()),
        "only_after": sorted(after_values.keys() - before_values.keys()),
        "focus": {"before": focus(before_values), "after": focus(after_values)},
        "changed_values": {
            key: summarize_value(before_values[key], after_values[key], args.max_ranges)
            for key in changed
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "changed_key_count": len(changed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
