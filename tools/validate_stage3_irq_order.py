#!/usr/bin/env python3
"""Three-way regression for the fresh Stage-3 task-15 IRQ-order failure.

This validator intentionally fails against the current production ROM.  It
compares an original-code MAME work-RAM capture with matching authenticated
safe-checkpoint continuations with gameplay escapes disabled and preserved.
The test is a scheduler-order gate, not a claim about fresh Stage-3 completion
or end-to-end rate.
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
FRAME_REGISTER_NAMES = tuple(
    [f"D{number}" for number in range(8)]
    + [f"A{number}" for number in range(7)]
)
FRAME_REGISTER_BYTES = len(FRAME_REGISTER_NAMES) * 4
FRAME_BYTES = FRAME_REGISTER_BYTES + 2 + 4
GAME_REGIONS = {
    "primary_enemy_record": (0x02DA, 0x034A),
    "boss_record_window": (0x0A50, 0x0AE0),
    "player_record": (0x12A2, 0x1312),
    "rng_state": (0x170E, 0x1710),
    "collision_tables": (0x3734, 0x3CC4),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-summary", type=Path, required=True)
    parser.add_argument("--native-off-summary", type=Path, required=True)
    parser.add_argument("--native-on-summary", type=Path, required=True)
    parser.add_argument(
        "--ticks",
        default="14744,14745,14746,14747",
        help="comma-separated retained MAME logical ticks",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-red",
        action="store_true",
        help="write a retained diagnostic report and exit zero if the gate is red",
    )
    args = parser.parse_args()
    for path in (
        args.mame_summary,
        args.native_off_summary,
        args.native_on_summary,
    ):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    try:
        args.ticks = tuple(int(value, 0) for value in args.ticks.split(","))
    except ValueError:
        parser.error("--ticks must be comma-separated integers")
    if not args.ticks or len(set(args.ticks)) != len(args.ticks):
        parser.error("--ticks must contain at least one unique tick")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_from_metadata(value: str, owner: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else owner.parent / path


def read_work(path: Path, expected_sha256: str) -> bytes:
    data = path.read_bytes()
    if len(data) != WORK_SIZE:
        raise RuntimeError(f"{path}: expected {WORK_SIZE} bytes, got {len(data)}")
    observed_sha256 = sha256(path)
    if observed_sha256 != expected_sha256:
        raise RuntimeError(
            f"{path}: metadata SHA-256 {expected_sha256}, got {observed_sha256}"
        )
    return data


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def task_frame(work: bytes) -> dict[str, Any]:
    saved_sp = be32(work, TASK_CONTEXT_SLOT)
    if saved_sp >> 16 != 0x00F0:
        raise RuntimeError(f"task {TASK}: saved SP is outside work RAM: {saved_sp:08X}")
    offset = saved_sp & 0xFFFF
    if offset + FRAME_BYTES + 4 > len(work):
        raise RuntimeError(f"task {TASK}: frame crosses work-RAM end")
    registers = {
        name: be32(work, offset + index * 4)
        for index, name in enumerate(FRAME_REGISTER_NAMES)
    }
    sr = be16(work, offset + FRAME_REGISTER_BYTES)
    return {
        "saved_sp": f"{saved_sp:08X}",
        "live_a7": f"{0x00F00000 | (offset + FRAME_BYTES):08X}",
        "registers": {name: f"{value:08X}" for name, value in registers.items()},
        "sr": f"{sr:04X}",
        "ccr_xnzvc": sr & 0x1F,
        "interrupt_mask": (sr >> 8) & 7,
        "pc": f"{be32(work, offset + FRAME_REGISTER_BYTES + 2):08X}",
        "return_pc": f"{be32(work, offset + FRAME_BYTES):08X}",
        "frame_plus_return_hex": work[offset : offset + FRAME_BYTES + 4].hex(),
    }


def first_differences(left: bytes, right: bytes, start: int, end: int) -> list[str]:
    return [
        f"F0{offset:04X}"
        for offset in range(start, end)
        if left[offset] != right[offset]
    ][:32]


def boundary_rows(summary: dict[str, Any], summary_path: Path) -> dict[int, dict[str, Any]]:
    log_path = path_from_metadata(summary["capture_log"], summary_path)
    rows: dict[int, dict[str, Any]] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") != "boundary":
            continue
        tick = int(row["mame_tick"])
        if tick in rows:
            raise RuntimeError(f"{log_path}: duplicate boundary for tick {tick}")
        rows[tick] = row
    return rows


def mame_rows(summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = {int(row["tick"]): row for row in summary["captures"]}
    if len(rows) != len(summary["captures"]):
        raise RuntimeError("MAME summary has duplicate capture ticks")
    return rows


def native_snapshot(row: dict[str, Any], owner: Path) -> tuple[bytes, dict[str, Any]]:
    work_meta = row["work"]
    work_path = path_from_metadata(work_meta["path"], owner)
    work = read_work(work_path, work_meta["sha256"])
    span = row["spans"]
    if len(span) != 1:
        raise RuntimeError(f"expected one exact span at MAME tick {row['mame_tick']}")
    return work, {
        "work": str(work_path.resolve()),
        "work_sha256": work_meta["sha256"],
        "task15": task_frame(work),
        "live_m68k": row["m68k"],
        "virtual_irq": {
            "countdown_00ac": row["virtual_irq_countdown"],
            "pending_00aa": row["virtual_irq_pending"],
        },
        "task_mask": row["task_mask"],
        "snes_tick": row["snes_tick"],
        "sa1_cycles": span[0]["sa1_cycles"],
        "video_frames": span[0]["video_frames"],
    }


def classify_result(
    configuration_checks: dict[str, bool], ticks: list[dict[str, Any]]
) -> tuple[int | None, str | None]:
    """Classify only the diagnostic signature this gate can actually prove.

    A red file is not automatically a virtual-IRQ result: corrupt inputs,
    mismatched checkpoints, or a native-only mismatch need different triage.
    The known timing signature requires valid comparison inputs and both SNES
    modes to retain one identical task frame that differs from original MAME.
    """
    if not all(configuration_checks.values()):
        return None, "invalid-comparison-input"
    for row in ticks:
        checks = row["checks"]
        if all(checks.values()):
            continue
        if (
            checks["task15_frame_native_off_native_on"]
            and not checks["task15_frame_mame_native_off"]
            and not checks["task15_frame_mame_native_on"]
        ):
            return int(row["mame_tick"]), "hardware-boundary/virtual-IRQ timing"
        return int(row["mame_tick"]), "unclassified-three-way divergence"
    return None, None


def main() -> int:
    args = parse_args()
    mame_summary = read_json(args.mame_summary)
    native_off_summary = read_json(args.native_off_summary)
    native_on_summary = read_json(args.native_on_summary)
    mame = mame_rows(mame_summary)
    native_off = boundary_rows(native_off_summary, args.native_off_summary)
    native_on = boundary_rows(native_on_summary, args.native_on_summary)

    configuration_checks = {
        "native_off_is_disabled": native_off_summary.get("gameplay_native")
        in {"off", "all-off"},
        "native_on_preserves_production_gates": (
            native_on_summary.get("gameplay_native") == "preserve"
        ),
        "same_safe_state": (
            native_off_summary.get("state_sha256")
            == native_on_summary.get("state_sha256")
        ),
        "same_production_rom": (
            native_off_summary.get("rom_sha256")
            == native_on_summary.get("rom_sha256")
        ),
        "native_off_state_authenticated": bool(
            native_off_summary.get("loaded_state_validation", {}).get("authenticated")
        ),
        "native_on_state_authenticated": bool(
            native_on_summary.get("loaded_state_validation", {}).get("authenticated")
        ),
    }
    ticks: list[dict[str, Any]] = []
    all_tick_checks: list[bool] = []
    for tick in args.ticks:
        try:
            mame_row = mame[tick]
            off_row = native_off[tick]
            on_row = native_on[tick]
        except KeyError as error:
            raise RuntimeError(f"missing retained tick {tick}: {error}") from error
        mame_path = path_from_metadata(mame_row["path"], args.mame_summary)
        mame_work = read_work(mame_path, mame_row["sha256"])
        off_work, off = native_snapshot(off_row, args.native_off_summary)
        on_work, on = native_snapshot(on_row, args.native_on_summary)
        mame_frame = task_frame(mame_work)
        regions: dict[str, Any] = {}
        region_checks: list[bool] = []
        for name, (start, end) in GAME_REGIONS.items():
            off_diff = first_differences(mame_work, off_work, start, end)
            on_diff = first_differences(mame_work, on_work, start, end)
            regions[name] = {
                "mame_vs_native_off": off_diff,
                "mame_vs_native_on": on_diff,
                "native_off_vs_native_on": first_differences(off_work, on_work, start, end),
            }
            region_checks.extend((not off_diff, not on_diff))
        frame_checks = {
            "task15_frame_mame_native_off": (
                mame_frame["frame_plus_return_hex"]
                == off["task15"]["frame_plus_return_hex"]
            ),
            "task15_frame_mame_native_on": (
                mame_frame["frame_plus_return_hex"]
                == on["task15"]["frame_plus_return_hex"]
            ),
            "task15_frame_native_off_native_on": (
                off["task15"]["frame_plus_return_hex"]
                == on["task15"]["frame_plus_return_hex"]
            ),
        }
        tick_checks = {**frame_checks, "game_regions_exact": all(region_checks)}
        all_tick_checks.extend(tick_checks.values())
        ticks.append(
            {
                "mame_tick": tick,
                "mame": {
                    "work": str(mame_path.resolve()),
                    "work_sha256": mame_row["sha256"],
                    "task15": mame_frame,
                },
                "native_off": off,
                "native_on": on,
                "work_byte_differences": {
                    "mame_vs_native_off": sum(
                        left != right for left, right in zip(mame_work, off_work)
                    ),
                    "mame_vs_native_on": sum(
                        left != right for left, right in zip(mame_work, on_work)
                    ),
                    "native_off_vs_native_on": sum(
                        left != right for left, right in zip(off_work, on_work)
                    ),
                },
                "game_regions": regions,
                "checks": tick_checks,
            }
        )

    result = "green" if all(configuration_checks.values()) and all(all_tick_checks) else "red"
    first_failure_tick, classification = classify_result(configuration_checks, ticks)
    report = {
        "result": result,
        "scope": (
            "fresh-lineage authenticated Stage-3 task-15 virtual-IRQ ordering; "
            "MAME original code, SNES gameplay-native off, and SNES production "
            "native-on. Not fresh-boot completion, fps, or renderer proof."
        ),
        "first_failure_tick": first_failure_tick,
        "classification": classification,
        "pre_failure_state": native_on_summary.get("state"),
        "pre_failure_state_sha256": native_on_summary.get("state_sha256"),
        "rom_sha256": native_on_summary.get("rom_sha256"),
        "mame": {
            "summary": str(args.mame_summary.resolve()),
            "executable": mame_summary.get("mame"),
            "executable_sha256": mame_summary.get("mame_sha256"),
        },
        "native_off": {
            "summary": str(args.native_off_summary.resolve()),
            "gameplay_native": native_off_summary.get("gameplay_native"),
        },
        "native_on": {
            "summary": str(args.native_on_summary.resolve()),
            "gameplay_native": native_on_summary.get("gameplay_native"),
        },
        "configuration_checks": configuration_checks,
        "ticks": ticks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result == "green" or args.allow_red else 1


if __name__ == "__main__":
    raise SystemExit(main())
