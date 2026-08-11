#!/usr/bin/env python3
"""Reconstruct an authenticated campaign boundary from a retained checkpoint.

This is a diagnostic bridge for focused three-way differentials.  It verifies
the checkpoint's fresh-boot lineage, restores the serialized controller mask,
replays the retained MAME controller transitions through a requested boundary,
and saves the exact post-event SNES state.  The output is a declared
checkpoint continuation, never fresh-boot proof by itself.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import replay_mame_controller_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]
MAME_ORIGIN_TICK = 221


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=campaign.DEFAULT_ROM)
    parser.add_argument("--timeline", type=Path, default=campaign.DEFAULT_TIMELINE)
    parser.add_argument("--nexen", type=Path, default=campaign.DEFAULT_NEXEN)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--lineage-events", type=Path, required=True)
    parser.add_argument("--checkpoint-mame-tick", type=int, required=True)
    parser.add_argument("--target-mame-tick", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9470)
    args = parser.parse_args()
    if args.target_mame_tick < args.checkpoint_mame_tick:
        parser.error("target tick must not precede the checkpoint tick")
    for label, path in (
        ("ROM", args.rom),
        ("timeline", args.timeline),
        ("Nexen", args.nexen),
        ("checkpoint", args.state),
        ("lineage events", args.lineage_events),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    campaign.configure_dotnet(args.nexen)
    rom = args.rom.resolve()
    rom_hash = campaign.sha256(rom)
    lineage = campaign.validate_resume_lineage(
        args.lineage_events.resolve(),
        args.state.resolve(),
        args.checkpoint_mame_tick,
        rom_hash,
    )
    inputs, _tick_rows = campaign.load_timeline(
        args.timeline,
        MAME_ORIGIN_TICK,
        args.target_mame_tick + 1,
    )
    initial_buttons = campaign.buttons_at_tick(
        inputs,
        MAME_ORIGIN_TICK,
        args.checkpoint_mame_tick,
    )
    events_by_tick: dict[int, list[campaign.InputEvent]] = defaultdict(list)
    for event in inputs:
        if args.checkpoint_mame_tick < event.tick <= args.target_mame_tick:
            events_by_tick[event.tick].append(event)

    args.output.mkdir(parents=True)
    applied: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    with campaign.McpSession(
        rom=rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        resume_context = lineage["resume_context"]
        if campaign.tick16(m) != int(resume_context["snes_tick"]):
            raise RuntimeError("checkpoint SNES tick does not match lineage")
        if initial_buttons != int(resume_context["current_buttons"]):
            raise RuntimeError("checkpoint controller mask does not match lineage")
        campaign.set_held_input(m, initial_buttons)

        current_mame_tick = args.checkpoint_mame_tick
        current_buttons = initial_buttons
        for target_tick in sorted(events_by_tick):
            spans.extend(
                campaign.run_tick_delta(m, target_tick - current_mame_tick)
            )
            current_mame_tick = target_tick
            for event in events_by_tick[target_tick]:
                current_buttons = event.buttons
                response = campaign.set_held_input(m, current_buttons)
                applied.append(
                    {
                        "mame_tick": target_tick,
                        "buttons": current_buttons,
                        "response": response,
                    }
                )
        if current_mame_tick < args.target_mame_tick:
            spans.extend(
                campaign.run_tick_delta(
                    m, args.target_mame_tick - current_mame_tick
                )
            )
            current_mame_tick = args.target_mame_tick

        m.pause()
        prestate = campaign.save_state(
            m, args.output / f"post-event-{current_mame_tick:05d}.mss"
        )
        screenshot = campaign.screenshot(
            m, args.output / f"post-event-{current_mame_tick:05d}.png"
        )
        snapshot = {
            "frame": int(m.get_state().get("frameCount", 0)),
            "snes_tick": campaign.tick16(m),
            "halt": campaign.halt16(m),
            "m68k": campaign.register_snapshot(m),
            "player": campaign.player_snapshot(m),
            "task_mask": int.from_bytes(
                m.read_memory("snesMemory", 0x400002, 2), "big"
            ),
            "pending_dma0": m.read_memory(
                "snesWorkRam", 0x1F11, 1
            )[0],
            "frame_request_ack": m.read_memory(
                "snesMemory", 0x3300, 4
            ).hex(),
            "work_64k_sha256": campaign.digest(
                b"".join(
                    m.read_memory(
                        "snesMemory", 0x400000 + offset, 0x4000
                    )
                    for offset in range(0, 0x10000, 0x4000)
                )
            ),
        }

    result = {
        "scope": (
            "authenticated current-ROM checkpoint continuation to an exact "
            "post-controller-event boundary; no game-memory writes; focused "
            "prestate generation, not fresh-boot proof"
        ),
        "rom": str(rom),
        "rom_sha256": rom_hash,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": campaign.sha256(args.nexen),
        "checkpoint": str(args.state.resolve()),
        "checkpoint_sha256": campaign.sha256(args.state),
        "checkpoint_mame_tick": args.checkpoint_mame_tick,
        "target_mame_tick": args.target_mame_tick,
        "lineage": lineage,
        "load_response": load_response,
        "initial_buttons": initial_buttons,
        "final_buttons": current_buttons,
        "applied_events": applied,
        "spans": spans,
        "runtime_game_memory_writes": [],
        "prestate": prestate,
        "screenshot": screenshot,
        "snapshot": snapshot,
    }
    output = args.output / "summary.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "summary": str(output),
            "prestate": prestate,
            "mame_tick": current_mame_tick,
            "snes_tick": snapshot["snes_tick"],
            "halt": snapshot["halt"],
            "buttons": current_buttons,
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
