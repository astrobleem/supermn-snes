#!/usr/bin/env python3
"""Three-way regression for the Stage-3 false collision/respawn chain.

The gate consumes exact controller-movie captures at their named MAME tick
boundaries.  It is deliberately narrow: an upstream virtual-IRQ ordering
fault shifts a Stage-3 collision producer, then the original $025110 logic
legitimately writes a negative response marker at $F03A02.  The player
consumer consequently treats that marker as damage on the following update.

Current production evidence is intentionally red.  A candidate is green only
when original MAME code, SNES gameplay-native off, and production native-on all
retain the same clear response marker and player record.  This is a focused
correctness gate, not a fresh-playthrough or rate result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


WORK_SIZE = 0x10000
MARKER_OFFSET = 0x3A02
PLAYER_HEALTH = 0x12B4
PLAYER_ACTION = 0x12DF
PLAYER_Y = 0x12E0
PLAYER_X = 0x12E4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-dir", type=Path, required=True)
    parser.add_argument("--native-off-dir", type=Path, required=True)
    parser.add_argument("--native-on-dir", type=Path, required=True)
    parser.add_argument(
        "--marker-tick",
        type=int,
        default=14839,
        help="boundary at which $F03A02 must still be clear",
    )
    parser.add_argument(
        "--death-tick",
        type=int,
        default=14840,
        help="following boundary at which the player must still be alive",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-red",
        action="store_true",
        help="retain a known-failing diagnostic report without failing CI",
    )
    args = parser.parse_args()
    if args.death_tick != args.marker_tick + 1:
        parser.error("--death-tick must immediately follow --marker-tick")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolved_path(value: str, owner: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else owner.parent / path


def read_work(path: Path, expected_sha256: str) -> bytes:
    data = path.read_bytes()
    if len(data) != WORK_SIZE:
        raise RuntimeError(f"{path}: expected {WORK_SIZE} bytes, got {len(data)}")
    observed = sha256(path)
    if observed != expected_sha256:
        raise RuntimeError(f"{path}: expected SHA-256 {expected_sha256}, got {observed}")
    return data


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def player(work: bytes) -> dict[str, int]:
    return {
        "health": be16(work, PLAYER_HEALTH),
        "action": work[PLAYER_ACTION],
        "x": be16(work, PLAYER_X),
        "y": be16(work, PLAYER_Y),
    }


def mame_rows(summary: dict[str, Any], owner: Path) -> dict[int, tuple[bytes, dict[str, Any]]]:
    rows: dict[int, tuple[bytes, dict[str, Any]]] = {}
    for row in summary.get("captures", []):
        tick = int(row["tick"])
        path = resolved_path(str(row["path"]), owner)
        rows[tick] = (read_work(path, str(row["sha256"])), row)
    return rows


def snes_rows(summary: dict[str, Any], owner: Path) -> dict[int, tuple[bytes, dict[str, Any]]]:
    log = resolved_path(str(summary["capture_log"]), owner)
    rows: dict[int, tuple[bytes, dict[str, Any]]] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") != "boundary":
            continue
        tick = int(row["mame_tick"])
        work_meta = row["work"]
        path = resolved_path(str(work_meta["path"]), log)
        rows[tick] = (read_work(path, str(work_meta["sha256"])), row)
    return rows


def row_snapshot(work: bytes, row: dict[str, Any], owner: Path, mame: bool) -> dict[str, Any]:
    path = (
        resolved_path(str(row["path"]), owner)
        if mame
        else resolved_path(str(row["work"]["path"]), owner)
    )
    return {
        "marker_f03a02": f"{be16(work, MARKER_OFFSET):04X}",
        "player": player(work),
        "work": str(path.resolve()),
        "work_sha256": sha256(path),
        "boundary": {
            "mame_tick": int(row["tick"] if mame else row["mame_tick"]),
            "snes_tick": None if mame else int(row["snes_tick"]),
        },
    }


def exact(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left["marker_f03a02"] == right["marker_f03a02"] and left["player"] == right["player"]


def main() -> int:
    args = parse_args()
    mame_summary_path = args.mame_dir / "summary.json"
    off_summary_path = args.native_off_dir / "summary.json"
    on_summary_path = args.native_on_dir / "summary.json"
    mame_summary = read_json(mame_summary_path)
    off_summary = read_json(off_summary_path)
    on_summary = read_json(on_summary_path)
    mame = mame_rows(mame_summary, mame_summary_path)
    off = snes_rows(off_summary, off_summary_path)
    on = snes_rows(on_summary, on_summary_path)
    ticks = (args.marker_tick, args.death_tick)
    for tick in ticks:
        if tick not in mame or tick not in off or tick not in on:
            raise RuntimeError(f"missing exact boundary {tick}")

    evidence: dict[str, dict[int, dict[str, Any]]] = {"mame": {}, "native_off": {}, "native_on": {}}
    for tick in ticks:
        evidence["mame"][tick] = row_snapshot(*mame[tick], mame_summary_path, True)
        evidence["native_off"][tick] = row_snapshot(*off[tick], off_summary_path, False)
        evidence["native_on"][tick] = row_snapshot(*on[tick], on_summary_path, False)

    marker = args.marker_tick
    death = args.death_tick
    configuration = {
        "mame_original_capture_green": mame_summary.get("result") == "green",
        "native_off_gameplay_escapes_disabled": off_summary.get("gameplay_native") == "off",
        "native_on_production_escapes_preserved": on_summary.get("gameplay_native") == "preserve",
        "same_rom": off_summary.get("rom_sha256") == on_summary.get("rom_sha256"),
        "same_authenticated_checkpoint": (
            off_summary.get("state_sha256") == on_summary.get("state_sha256")
            and bool(off_summary.get("loaded_state_validation", {}).get("authenticated"))
            and bool(on_summary.get("loaded_state_validation", {}).get("authenticated"))
        ),
    }
    checks = {
        "mame_marker_clear": evidence["mame"][marker]["marker_f03a02"] == "0000",
        "native_off_marker_matches_mame": exact(evidence["mame"][marker], evidence["native_off"][marker]),
        "native_on_marker_matches_mame": exact(evidence["mame"][marker], evidence["native_on"][marker]),
        "native_off_post_player_matches_mame": exact(evidence["mame"][death], evidence["native_off"][death]),
        "native_on_post_player_matches_mame": exact(evidence["mame"][death], evidence["native_on"][death]),
    }
    current_signature = {
        "both_snes_modes_share_nonzero_marker": (
            evidence["native_off"][marker]["marker_f03a02"]
            == evidence["native_on"][marker]["marker_f03a02"]
            != evidence["mame"][marker]["marker_f03a02"]
        ),
        "both_snes_modes_share_false_respawn": (
            evidence["native_off"][death]["player"]
            == evidence["native_on"][death]["player"]
            != evidence["mame"][death]["player"]
            and evidence["native_on"][death]["player"]["action"] == 9
            and evidence["native_on"][death]["player"]["health"] == 20
        ),
    }
    result = "green" if all(configuration.values()) and all(checks.values()) else "red"
    report = {
        "result": result,
        "scope": (
            "exact Stage-3 false-hit controller-chain regression: MAME original, "
            "SNES gameplay-native off, and SNES production native-on; not a "
            "fresh-boot completion, performance, or full-playthrough result"
        ),
        "classification_if_current_signature": (
            "hardware-boundary/virtual-IRQ timing: both SNES configurations "
            "share the shifted collision input; $025110 then follows its normal "
            "collision response path"
        ),
        "marker_address": "F03A02",
        "marker_tick": marker,
        "death_tick": death,
        "rom_sha256": on_summary.get("rom_sha256"),
        "pre_failure_state": {
            "path": on_summary.get("state"),
            "sha256": on_summary.get("state_sha256"),
        },
        "configuration": configuration,
        "checks": checks,
        "current_failure_signature": current_signature,
        "evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result == "green" or args.allow_red else 1


if __name__ == "__main__":
    raise SystemExit(main())
