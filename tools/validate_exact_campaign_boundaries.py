#!/usr/bin/env python3
"""Regress exact, resumable campaign tick stops in Nexen.

Nexen applies debugger pause requests at a later safe boundary.  The campaign
therefore parks the SA-1 immediately after ``INC $0760``, restores the ROM, and
redirects to an existing instruction-equivalent ``CLC; RTS`` continuation.
This focused validator proves that two consecutive stops and a saved-state
reload all advance exactly one tick without leaving the temporary loop active.
It is harness evidence, not fresh-boot or gameplay-semantic proof.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import replay_mame_controller_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=campaign.DEFAULT_ROM)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=campaign.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9518)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def seam_bytes(m: campaign.McpSession) -> dict[str, str]:
    return {
        "post_write": bytes(
            m.read_memory(
                "snesPrgRom",
                campaign.TICK_POST_WRITE_ROM_OFFSET,
                2,
            )
        ).hex(),
        "equivalent_release": bytes(
            m.read_memory(
                "snesPrgRom",
                campaign.TICK_RELEASE_ROM_OFFSET,
                2,
            )
        ).hex(),
    }


def exact_step(m: campaign.McpSession, label: str) -> dict[str, Any]:
    before = campaign.tick16(m)
    spans = campaign.run_tick_delta(m, 1)
    after = campaign.tick16(m)
    if len(spans) != 1 or not spans[0]["exact_post_write_stop"]:
        raise RuntimeError(f"{label}: missing exact final span: {spans}")
    if after != ((before + 1) & 0xFFFF):
        raise RuntimeError(f"{label}: tick {before:#06x}->{after:#06x}")
    seams = seam_bytes(m)
    expected = campaign.TICK_POST_WRITE_ORIGINAL.hex()
    if seams != {
        "post_write": expected,
        "equivalent_release": expected,
    }:
        raise RuntimeError(f"{label}: ROM seam was not restored: {seams}")
    cpu = dict(m.get_cpu_state("Sa1"))
    if (
        int(cpu.get("k", -1)) != 0
        or int(cpu.get("pc", -1))
        != (campaign.TICK_RELEASE_EQUIVALENT & 0xFFFF)
    ):
        raise RuntimeError(f"{label}: release PC is not exact: {cpu}")
    if campaign.halt16(m):
        raise RuntimeError(f"{label}: interpreter halted")
    return {
        "label": label,
        "before_tick": before,
        "after_tick": after,
        "spans": spans,
        "restored_seams": seams,
        "release_cpu": cpu,
    }


def open_session(
    args: argparse.Namespace,
    stderr_log: Path,
    port: int,
) -> campaign.McpSession:
    return campaign.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    )


def main() -> int:
    args = parse_args()
    campaign.configure_dotnet(args.nexen)
    output = args.output.resolve()
    output.mkdir(parents=True)
    os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet10")
    retained = output / "exact-release.mss"
    cases: list[dict[str, Any]] = []

    with open_session(
        args, output / "first-session.stderr.log", args.port
    ) as m:
        m.pause()
        load = m.load_state(args.state.resolve())
        m.pause()
        cases.append(exact_step(m, "first"))
        cases.append(exact_step(m, "consecutive"))
        retained_response = campaign.save_state(m, retained)

    with open_session(
        args, output / "reload-session.stderr.log", args.port + 1
    ) as m:
        m.pause()
        reload_response = m.load_state(retained.resolve())
        m.pause()
        cases.append(exact_step(m, "saved_state_reload"))

    result = {
        "scope": (
            "focused Nexen exact-tick debugger-stop regression; two consecutive "
            "stops plus saved-state resume; no controller or game-state writes; "
            "not fresh-boot, gameplay-semantic, or performance proof"
        ),
        "result": "green",
        "rom": str(args.rom.resolve()),
        "rom_sha256": campaign.sha256(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": campaign.sha256(args.nexen),
        "input_state": str(args.state.resolve()),
        "input_state_sha256": campaign.sha256(args.state),
        "initial_load_response": load,
        "retained_state": retained_response,
        "reload_response": reload_response,
        "debugger_intervention": {
            "temporary_rom_patch": {
                "address": f"{campaign.TICK_POST_WRITE:06X}",
                "before": campaign.TICK_POST_WRITE_ORIGINAL.hex(),
                "temporary": campaign.TICK_POST_WRITE_STABLE.hex(),
                "restored_each_stop": True,
            },
            "decoded_loop_release": {
                "from": f"{campaign.TICK_POST_WRITE:06X}",
                "to": f"{campaign.TICK_RELEASE_EQUIVALENT:06X}",
                "opcode_at_both_continuations": (
                    campaign.TICK_POST_WRITE_ORIGINAL.hex()
                ),
                "changed_native_register": "PC only",
            },
            "game_state_writes": False,
        },
        "cases": cases,
    }
    summary = output / "summary.json"
    summary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": "green",
                "summary": str(summary),
                "ticks": [
                    [case["before_tick"], case["after_tick"]]
                    for case in cases
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
