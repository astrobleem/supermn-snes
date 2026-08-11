#!/usr/bin/env python3
"""Validate the campaign's exact $0259B0 IRQ seam in three configurations.

MAME and native-on expose task 15 as a saved scheduler frame.  Native-off is
captured immediately before the same logical instruction, so its live D/A
registers, CCR/X/mask, A7, and caller return are compared with that frame.
Game-owned player/enemy/boss, RNG, and collision records must also agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


WORK_SIZE = 0x10000
TASK = 15
TASK_CONTEXT_SLOT = 0x000A + TASK * 4
FRAME_REGISTERS = tuple(
    [f"D{index}" for index in range(8)]
    + [f"A{index}" for index in range(7)]
)
FRAME_REGISTER_BYTES = len(FRAME_REGISTERS) * 4
FRAME_BYTES = FRAME_REGISTER_BYTES + 2 + 4
EXPECTED_PC = 0x000259B0
EXPECTED_RETURN = 0x000242BE
GAME_REGIONS = {
    "primary_enemy_record": (0x02DA, 0x034A),
    "boss_record_window": (0x0A50, 0x0AE0),
    "player_record": (0x12A2, 0x1312),
    "rng_state": (0x170E, 0x1710),
    "collision_tables": (0x3734, 0x3CC4),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata_path(value: str, owner: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else owner.parent / path


def read_work(path: Path, expected_sha256: str | None = None) -> bytes:
    data = path.read_bytes()
    if len(data) != WORK_SIZE:
        raise RuntimeError(
            f"{path}: expected {WORK_SIZE} work bytes, observed {len(data)}"
        )
    actual = sha256(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(
            f"{path}: metadata SHA-256 {expected_sha256}, observed {actual}"
        )
    return data


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def decode_task_frame(work: bytes) -> dict[str, Any]:
    saved_sp = be32(work, TASK_CONTEXT_SLOT)
    if saved_sp >> 16 != 0x00F0:
        raise RuntimeError(
            f"task {TASK} saved SP is not in work RAM: ${saved_sp:08X}"
        )
    offset = saved_sp & 0xFFFF
    if offset + FRAME_BYTES + 4 > len(work):
        raise RuntimeError(f"task {TASK} frame crosses work-RAM end")
    registers = {
        name: be32(work, offset + index * 4)
        for index, name in enumerate(FRAME_REGISTERS)
    }
    sr = be16(work, offset + FRAME_REGISTER_BYTES)
    pc = be32(work, offset + FRAME_REGISTER_BYTES + 2)
    return {
        "saved_sp": saved_sp,
        "live_a7": 0x00F00000 | (offset + FRAME_BYTES),
        "registers": registers,
        "sr": sr,
        "ccr_xnzvc": sr & 0x1F,
        "interrupt_mask": (sr >> 8) & 7,
        "pc": pc,
        "return_pc": be32(work, offset + FRAME_BYTES),
        "frame_hex": work[offset : offset + FRAME_BYTES].hex(),
        "frame_plus_return_hex": work[
            offset : offset + FRAME_BYTES + 4
        ].hex(),
    }


def first_differences(
    left: bytes, right: bytes, start: int, end: int
) -> list[str]:
    return [
        f"F0{offset:04X}"
        for offset in range(start, end)
        if left[offset] != right[offset]
    ][:32]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-summary", type=Path, required=True)
    parser.add_argument("--tick", type=int, default=14746)
    parser.add_argument("--native-off-summary", type=Path, required=True)
    parser.add_argument("--native-on-trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.mame_summary,
        args.native_off_summary,
        args.native_on_trace,
    ):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    mame_meta = json.loads(args.mame_summary.read_text(encoding="utf-8"))
    off_meta = json.loads(
        args.native_off_summary.read_text(encoding="utf-8")
    )
    on_meta = json.loads(args.native_on_trace.read_text(encoding="utf-8"))

    captures = [
        row for row in mame_meta["captures"] if int(row["tick"]) == args.tick
    ]
    if len(captures) != 1:
        raise RuntimeError(
            f"MAME summary has {len(captures)} captures for tick {args.tick}"
        )
    mame_row = captures[0]
    mame_path = metadata_path(mame_row["path"], args.mame_summary)
    off_row = off_meta["entry_work"]
    off_path = metadata_path(off_row["path"], args.native_off_summary)
    on_row = on_meta["end_work"]
    on_path = metadata_path(on_row["path"], args.native_on_trace)

    mame_work = read_work(mame_path, mame_row["sha256"])
    off_work = read_work(off_path, off_row["sha256"])
    on_work = read_work(on_path, on_row["sha256"])

    mame_frame = decode_task_frame(mame_work)
    on_frame = decode_task_frame(on_work)
    off_entry = off_meta["entry"]["m68k"]
    off_registers = {
        name: int(value, 16)
        for name, value in off_entry["registers"].items()
    }

    checks: dict[str, bool] = {
        "mame_task15_pc_0259b0": mame_frame["pc"] == EXPECTED_PC,
        "native_on_task15_pc_0259b0": on_frame["pc"] == EXPECTED_PC,
        "task15_frame_exact": (
            on_frame["frame_hex"] == mame_frame["frame_hex"]
        ),
        "mame_return_0242be": (
            mame_frame["return_pc"] == EXPECTED_RETURN
        ),
        "native_on_return_0242be": (
            on_frame["return_pc"] == EXPECTED_RETURN
        ),
        "task15_frame_plus_return_exact": (
            on_frame["frame_plus_return_hex"]
            == mame_frame["frame_plus_return_hex"]
        ),
        "native_off_logical_pc_0259b0": (
            int(off_meta["entry"]["logical_pc"]) == EXPECTED_PC
        ),
        "native_off_registers_match_frame": all(
            off_registers[name] == mame_frame["registers"][name]
            for name in FRAME_REGISTERS
        ),
        "native_off_a7_matches_post_frame": (
            off_registers["A7"] == mame_frame["live_a7"]
        ),
        "native_off_ccr_matches_frame": (
            int(off_entry["ccr_xnzvc"]) == mame_frame["ccr_xnzvc"]
        ),
        "native_off_mask_matches_frame": (
            int(off_entry["interrupt_mask"])
            == mame_frame["interrupt_mask"]
        ),
        "native_off_return_0242be": (
            be32(off_work, off_registers["A7"] & 0xFFFF)
            == EXPECTED_RETURN
        ),
        "native_off_configuration": off_meta["gameplay_native"] == "off",
        "native_off_exact_occurrence": int(
            off_meta["skip_logical_hits"]
        ) == 27,
        "native_on_production_gates_preserved": all(
            value == "preserve" for value in on_meta["gate_request"].values()
        ),
        "native_on_real_irq_stop": (
            on_meta["stable_stop_patch"]["address"] == "92DB82"
            and len(on_meta["skipped_stop_hits"]) == 1
        ),
        "native_on_controller_preserved": bool(on_meta["preserve_input"]),
    }

    regions = {}
    for name, (start, end) in GAME_REGIONS.items():
        off_differences = first_differences(
            mame_work, off_work, start, end
        )
        on_differences = first_differences(mame_work, on_work, start, end)
        regions[name] = {
            "start": f"F0{start:04X}",
            "end_exclusive": f"F0{end:04X}",
            "native_off_equal": not off_differences,
            "native_on_equal": not on_differences,
            "native_off_first_differences": off_differences,
            "native_on_first_differences": on_differences,
        }
        checks[f"{name}_threeway_exact"] = (
            not off_differences and not on_differences
        )

    result = "green" if all(checks.values()) else "red"
    report = {
        "result": result,
        "scope": (
            "exact campaign $0259B0 task-15 IRQ seam; MAME arcade, "
            "Nexen native-off logical entry, and production native-on saved "
            "scheduler frame; not fps or fresh-boot proof"
        ),
        "classification": "native/HLE call-bridge stack/return contract",
        "tick": args.tick,
        "expected_resume_pc": f"{EXPECTED_PC:08X}",
        "expected_return_pc": f"{EXPECTED_RETURN:08X}",
        "mame": {
            "summary": str(args.mame_summary.resolve()),
            "work": str(mame_path.resolve()),
            "work_sha256": sha256(mame_path),
            "frame": mame_frame,
        },
        "native_off": {
            "summary": str(args.native_off_summary.resolve()),
            "work": str(off_path.resolve()),
            "work_sha256": sha256(off_path),
            "pre_failure_state": off_meta["entry_state"],
            "entry": off_meta["entry"],
        },
        "native_on": {
            "trace": str(args.native_on_trace.resolve()),
            "work": str(on_path.resolve()),
            "work_sha256": sha256(on_path),
            "rom_sha256": on_meta["rom_sha256"],
            "pre_failure_state": {
                "path": on_meta["state"],
                "sha256": on_meta["state_sha256"],
            },
            "frame": on_frame,
        },
        "game_regions": regions,
        "checks": checks,
        "failed_checks": [
            name for name, passed in checks.items() if not passed
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
