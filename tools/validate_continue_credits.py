#!/usr/bin/env python3
"""Regress the one-credit continue rule from an organic pre-continue state.

The fixture is the retained tick-7560 state from the fresh, one-credit
controller campaign.  Starting the game consumed that credit, so the fixture
has zero remaining credits and is waiting on the continue screen.  The test
branches it without memory injection:

* Start alone must not continue or create a free credit.
* A real Select/coin edge followed by Start must consume that credit and
  return the player from transition action 9 to normal action 0.

Both branches run with gameplay native escapes enabled and disabled.  This is
focused checkpoint coverage; the fixture's campaign lineage and the separate
fresh-boot campaign remain the authority for organic provenance.
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
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    EVIDENCE
    / "tick07560-preinput-state-final-34fe-v1"
    / "states"
    / "snes-tick-07560.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
GAMEPLAY_NATIVE_GATES = (0x071A, 0x073A)

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9260)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("pre-continue state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    work = b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x0800))
    return {
        "label": label,
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "snes_tick": campaign.tick16(m),
        "credits_f01c62": int.from_bytes(work[0x1C62:0x1C64], "big"),
        "player": campaign.player_snapshot(m),
        "m68k": campaign.register_snapshot(m),
        "pc68k": int.from_bytes(iram[0x40:0x44], "little") & 0xFFFFFF,
        "halt": campaign.halt16(m),
        "task_mask": int.from_bytes(work[2:4], "big"),
        "virtual_irq_pending": int.from_bytes(iram[0xAA:0xAC], "little"),
        "virtual_irq_countdown": int.from_bytes(iram[0xAC:0xAE], "little"),
        "work_64k_sha256": digest(work),
        "collision_4k_sha256": digest(work[0x3000:0x4000]),
        "gates": {
            f"{address:04x}": int.from_bytes(
                iram[address : address + 2], "little"
            )
            for address in GAMEPLAY_NATIVE_GATES
        },
    }


def set_native(m: McpSession, enabled: bool) -> None:
    for address in GAMEPLAY_NATIVE_GATES:
        m.write_u16(address, int(enabled), "Sa1Memory")


def run_schedule(
    m: McpSession,
    schedule: list[tuple[str, int, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    states = [snapshot(m, "pre_input")]
    spans: list[dict[str, Any]] = []
    for label, buttons, ticks in schedule:
        campaign.set_held_input(m, buttons)
        spans.extend(campaign.run_tick_delta(m, ticks))
        states.append(snapshot(m, label))
    return states, spans


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states_dir = output / "states"
    shots_dir = output / "screenshots"
    states_dir.mkdir()
    shots_dir.mkdir()
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    schedules = {
        "start_without_coin": [
            ("after_start_hold", McpSession.BTN_START, 4),
            ("after_neutral_observation", 0, 40),
        ],
        "coin_then_start": [
            ("after_coin_hold", McpSession.BTN_SELECT, 4),
            ("after_coin_release", 0, 2),
            ("after_start_hold", McpSession.BTN_START, 4),
            ("after_respawn_observation", 0, 40),
        ],
    }
    cases: list[dict[str, Any]] = []
    stderr = output / "emulator.stderr.log"
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr,
    ) as m:
        m.pause()
        for native_enabled in (True, False):
            for branch, schedule in schedules.items():
                m.load_state(args.state.resolve())
                m.pause()
                campaign.set_held_input(m, 0)
                set_native(m, native_enabled)
                pre_path = (
                    states_dir
                    / f"{'native-on' if native_enabled else 'native-off'}"
                    f"-{branch}-pre.mss"
                )
                pre_state = campaign.save_state(m, pre_path)
                snapshots, spans = run_schedule(m, schedule)
                shot_path = (
                    shots_dir
                    / f"{'native-on' if native_enabled else 'native-off'}"
                    f"-{branch}-post.png"
                )
                post_shot = campaign.screenshot(m, shot_path)
                initial = snapshots[0]
                final = snapshots[-1]
                if branch == "start_without_coin":
                    green = (
                        initial["credits_f01c62"] == 0
                        and initial["player"]["action"] == 9
                        and final["credits_f01c62"] == 0
                        and final["player"]["action"] == 9
                    )
                else:
                    release = next(
                        row
                        for row in snapshots
                        if row["label"] == "after_coin_release"
                    )
                    green = (
                        initial["credits_f01c62"] == 0
                        and initial["player"]["action"] == 9
                        and release["credits_f01c62"] == 1
                        and final["credits_f01c62"] == 0
                        and final["player"]["action"] == 0
                    )
                cases.append(
                    {
                        "name": branch,
                        "gameplay_native": (
                            "on" if native_enabled else "off"
                        ),
                        "result": "green" if green else "red",
                        "pre_state": pre_state,
                        "post_screenshot": post_shot,
                        "snapshots": snapshots,
                        "spans": spans,
                    }
                )

    result = "green" if all(row["result"] == "green" for row in cases) else "red"
    summary = {
        "scope": (
            "checkpointed one-credit continue-rule regression from an "
            "organically retained pre-continue state; real controller input, "
            "no work-RAM injection; not fresh-boot or full-playthrough proof"
        ),
        "result": result,
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "fixture_state": str(args.state.resolve()),
        "fixture_state_sha256": sha256(args.state),
        "oracle_basis": {
            "mame_zero_credit_wait_pc": "0044FC",
            "mame_start_credit_consume_pc": "004BFE",
            "credit_address": "F01C62",
            "classification": (
                "stale/oracle input-lineage mismatch, not interpreter or "
                "native/HLE logic"
            ),
        },
        "cases": cases,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    retained_state = output / "fixture-pre-continue.mss"
    shutil.copy2(args.state, retained_state)
    print(
        json.dumps(
            {
                "result": result,
                "cases": [
                    {
                        "name": row["name"],
                        "gameplay_native": row["gameplay_native"],
                        "result": row["result"],
                    }
                    for row in cases
                ],
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
