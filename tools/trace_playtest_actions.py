#!/usr/bin/env python3
"""Replay short real-controller action schedules in exact Mesen.

This is an interactive-path crash diagnostic, not performance evidence.  It
loads a caller-supplied checkpoint, applies only port-0 controller input, and
records player state, liveness, renderer state, task-stack floors, screenshots,
and a save state at the first halt/stall/invalid saved stack.

Schedule syntax is a comma-separated list of ``buttons:frames`` actions:

    right:120,none:20,b:6,none:30
    right+b:6,right:30

The complete schedule can be repeated with ``--repeat``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
PLAYER_A6 = 0xF01302
PLAYER_BASE = 0x400000 | ((PLAYER_A6 - 0x60) & 0xFFFF)
CONTEXT_START = 0x40000A
FLOOR_START = 0xC10882

BUTTONS = {
    "none": 0,
    "a": McpSession.BTN_A,
    "b": McpSession.BTN_B,
    "x": McpSession.BTN_X,
    "y": McpSession.BTN_Y,
    "select": McpSession.BTN_SELECT,
    "start": McpSession.BTN_START,
    "up": McpSession.BTN_UP,
    "down": McpSession.BTN_DOWN,
    "left": McpSession.BTN_LEFT,
    "right": McpSession.BTN_RIGHT,
}


@dataclass(frozen=True)
class Action:
    label: str
    buttons: int
    frames: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=8930)
    parser.add_argument(
        "--schedule",
        required=True,
        help="Comma-separated buttons:frames actions; combine buttons with +.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--screenshot-every",
        type=int,
        default=1,
        help="Capture every N completed actions; zero disables periodic captures.",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=0,
        help="Save state every N completed actions; zero saves only initial/failure/final.",
    )
    parser.add_argument(
        "--stall-video-frames",
        type=int,
        default=90,
        help="Stop after this many advanced video frames without a game tick.",
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "After loading a compatible older checkpoint, replace the "
            "$7F:8000-$AFFF renderer mirror with the selected ROM's image."
        ),
    )
    return parser.parse_args()


def configure_dotnet8() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *current])


def parse_schedule(text: str) -> list[Action]:
    actions: list[Action] = []
    for raw_action in text.split(","):
        raw_action = raw_action.strip()
        if not raw_action:
            continue
        try:
            button_text, frame_text = raw_action.rsplit(":", 1)
            frames = int(frame_text, 0)
        except ValueError as exc:
            raise ValueError(
                f"invalid action {raw_action!r}; expected buttons:frames"
            ) from exc
        if frames <= 0:
            raise ValueError(f"action frames must be positive: {raw_action!r}")
        mask = 0
        names = [name.strip().lower() for name in button_text.split("+")]
        for name in names:
            if name not in BUTTONS:
                raise ValueError(
                    f"unknown button {name!r}; choices: {sorted(BUTTONS)}"
                )
            mask |= BUTTONS[name]
        label = "+".join(names)
        actions.append(Action(label, mask, frames))
    if not actions:
        raise ValueError("schedule contains no actions")
    return actions


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def le32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def cpu_pc(state: dict[str, Any]) -> int:
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (
        int(state.get("pc", 0)) & 0xFFFF
    )


def wait_for_file(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def save_state(m: McpSession, path: Path) -> dict[str, Any]:
    response = m.save_state(path)
    wait_for_file(path)
    return {"path": str(path), "sha256": sha256(path), "response": response}


def take_screenshot(m: McpSession, path: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), path)
    return {"path": str(path), "sha256": sha256(path), "response": response}


def player_snapshot(m: McpSession) -> dict[str, Any]:
    local = bytes(m.read_memory("snesMemory", PLAYER_BASE, 0x80))

    def byte(offset: int) -> int:
        return local[0x60 + offset]

    def word(offset: int) -> int:
        index = 0x60 + offset
        return be16(local[index : index + 2])

    return {
        "active_task_a6": le32(m.read_memory("Sa1Memory", 0x0038, 4))
        & 0xFFFFFF,
        "health": word(-0x4E),
        "previous_input": byte(-0x43),
        "input": byte(-0x44),
        "action_state": byte(-0x23),
        "animation": word(-0x1A),
        "animation_step": word(-0x18),
        "animation_delay": word(-0x16),
        "animation_substep": word(-0x14),
        "animation_pointer": int.from_bytes(
            local[0x60 - 0x12 : 0x60 - 0x0E], "big"
        ),
        "x": word(-0x1E),
        "y": word(-0x22),
        "flags": byte(-0x24),
        "locals_sha256": hashlib.sha256(local).hexdigest(),
    }


def task_snapshot(m: McpSession, floors: list[int]) -> dict[str, Any]:
    raw = bytes(m.read_memory("snesMemory", CONTEXT_START, 16 * 4))
    values = [
        int.from_bytes(raw[index * 4 : index * 4 + 4], "big")
        for index in range(16)
    ]
    initialized = [
        {
            "task": index,
            "saved_sp": value,
            "floor": floors[index],
            "margin": value - floors[index],
            "valid": value >= floors[index] and (value >> 16) == 0x00F0,
        }
        for index, value in enumerate(values)
        if value
    ]
    return {
        "task_mask": int.from_bytes(
            m.read_memory("snesMemory", 0x400002, 2), "big"
        ),
        "initialized": initialized,
        "invalid": [entry for entry in initialized if not entry["valid"]],
        "minimum_margin": min(
            (entry["margin"] for entry in initialized), default=None
        ),
    }


def snapshot(
    m: McpSession,
    floors: list[int],
    label: str,
    action_index: int,
) -> dict[str, Any]:
    state = m.get_state()
    sa1 = dict(m.get_cpu_state("Sa1"))
    snes = dict(m.get_cpu_state("Snes"))
    virtual = bytes(m.read_memory("Sa1Memory", 0x0040, 0x70))
    request_ack = bytes(m.read_memory("snesMemory", 0x3300, 4))
    renderer = bytes(m.read_memory("snesWorkRam", 0x89A0, 0x3A))
    ppu = m.get_ppu_state()
    bg1 = ppu["layers"][0]
    scroll_packed = bytes(m.read_memory("snesWorkRam", 0x8994, 2))
    x1_scrolly = [
        m.read_memory("snesMemory", 0x413401 + column * 0x20, 1)[0]
        for column in (2, 4, 6, 8, 9)
    ]
    tasks = task_snapshot(m, floors)
    return {
        "label": label,
        "action_index": action_index,
        "frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "pc68k": le32(virtual[0:4]) & 0xFFFFFF,
        "opcode68k": le16(virtual[4:6]),
        "halt": le16(virtual[0x0E:0x10]),
        "ac": le16(virtual[0x6C:0x6E]),
        "sa1_pc": cpu_pc(sa1),
        "snes_pc": cpu_pc(snes),
        "frame_request": le16(request_ack[0:2]),
        "frame_ack": le16(request_ack[2:4]),
        "render_complete": le16(renderer[2:4]),
        "render_generation": le16(renderer[4:6]),
        "render_queue_drops": le16(renderer[0x34:0x36]),
        "render_queue_primary": le16(renderer[0x32:0x34]),
        "render_queue_secondary": le16(renderer[0x36:0x38]),
        "manifest_length": le16(renderer[0x1A:0x1C]),
        "last_obj_count": le16(renderer[0x12:0x14]),
        "obj_slots": le16(m.read_memory("snesWorkRam", 0x00DE, 2)),
        "bg1_hscroll": int(bg1["hscroll"]),
        "bg1_vscroll": int(bg1["vscroll"]),
        "scroll_packed": le16(scroll_packed),
        "x1_scrolly_columns_2_4_6_8_9": x1_scrolly,
        "title_text_meta": le16(
            m.read_memory("snesWorkRam", 0x89BE, 2)
        ),
        "player": player_snapshot(m),
        **tasks,
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.output = args.output.resolve()
    args.mesen = args.mesen.resolve()
    if args.repeat <= 0:
        raise SystemExit("--repeat must be positive")
    if args.screenshot_every < 0 or args.save_every < 0:
        raise SystemExit("capture cadences must be non-negative")
    if args.stall_video_frames <= 0:
        raise SystemExit("--stall-video-frames must be positive")
    actions = parse_schedule(args.schedule) * args.repeat
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    args.output.mkdir(parents=True, exist_ok=False)
    configure_dotnet8()

    result: dict[str, Any] = {
        "scope": (
            "checkpointed exact-Mesen real-controller action diagnostic; "
            + (
                "selected-ROM video mirror injected after state load; "
                if args.refresh_video_mirror
                else "no runtime memory writes; "
            )
            + "not FPS or cold-boot evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "mesen": str(args.mesen.resolve()),
        "mesen_sha256": sha256(args.mesen),
        "schedule": [
            {"label": action.label, "buttons": action.buttons, "frames": action.frames}
            for action in actions
        ],
        "runtime_memory_writes": [],
        "samples": [],
        "screenshots": [],
        "states": [],
        "failure": None,
        "trace_at_failure": None,
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.refresh_video_mirror:
            video_mirror = args.rom.read_bytes()[
                VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
            ]
            if len(video_mirror) != VIDEO_WRAM_LENGTH:
                raise RuntimeError("selected ROM does not contain the video mirror span")
            for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
                chunk = video_mirror[offset : offset + 0x1000]
                m.write_memory(
                    "snesWorkRam",
                    VIDEO_WRAM_OFFSET + offset,
                    chunk.hex(),
                )
            observed = bytes(
                m.read_memory(
                    "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
                )
            )
            if observed != video_mirror:
                raise RuntimeError("selected-ROM video mirror injection did not verify")
            result["runtime_memory_writes"].append(
                {
                    "region": "snesWorkRam $7F:8000-$AFFF",
                    "source": (
                        f"selected ROM file ${VIDEO_FILE_BASE:06X}-"
                        f"${VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH - 1:06X}"
                    ),
                    "length": VIDEO_WRAM_LENGTH,
                    "sha256": hashlib.sha256(video_mirror).hexdigest(),
                }
            )
        floor_raw = bytes(m.read_memory("snesMemory", FLOOR_START, 16 * 4))
        floors = [
            int.from_bytes(floor_raw[index * 4 : index * 4 + 4], "big")
            for index in range(16)
        ]
        result["floors"] = floors
        initial = snapshot(m, floors, "initial", -1)
        result["samples"].append(initial)
        result["screenshots"].append(
            take_screenshot(m, args.output / "initial.png")
        )
        result["states"].append(save_state(m, args.output / "initial.mss"))
        m.trace_log(count=1, cpu_type="Sa1")

        stagnant_video_frames = 0
        previous_tick = initial["tick"]
        failed = False
        for index, action in enumerate(actions):
            before_frame = int(m.get_state().get("frameCount", 0))
            input_response = m.set_input(action.buttons, action.frames)
            m.pause()
            after_frame = int(m.get_state().get("frameCount", 0))
            advanced_frames = after_frame - before_frame
            sample = snapshot(
                m, floors, f"{index:04d}_{action.label}", index
            )
            sample.update(
                {
                    "buttons": action.buttons,
                    "requested_frames": action.frames,
                    "advanced_frames": advanced_frames,
                    "input_response": input_response,
                }
            )
            if sample["tick"] == previous_tick:
                stagnant_video_frames += advanced_frames
            else:
                stagnant_video_frames = 0
            previous_tick = sample["tick"]
            sample["stagnant_video_frames"] = stagnant_video_frames
            result["samples"].append(sample)

            if args.screenshot_every and (
                (index + 1) % args.screenshot_every == 0
            ):
                result["screenshots"].append(
                    take_screenshot(
                        m,
                        args.output
                        / f"action-{index:04d}-{action.label.replace('+', '_')}.png",
                    )
                )
            if args.save_every and (index + 1) % args.save_every == 0:
                result["states"].append(
                    save_state(m, args.output / f"action-{index:04d}.mss")
                )

            reasons = []
            if sample["halt"]:
                reasons.append(f"halt_{sample['halt']:04x}")
            if sample["invalid"]:
                reasons.append("invalid_saved_stack")
            if stagnant_video_frames >= args.stall_video_frames:
                reasons.append("game_tick_stall")
            if reasons:
                result["failure"] = {
                    "action_index": index,
                    "reasons": reasons,
                    "sample": sample,
                }
                result["trace_at_failure"] = m.trace_log(
                    count=1000, cpu_type="Sa1"
                )
                result["states"].append(
                    save_state(m, args.output / "failure.mss")
                )
                result["screenshots"].append(
                    take_screenshot(m, args.output / "failure.png")
                )
                failed = True
                break

        final = snapshot(m, floors, "final", len(result["samples"]) - 2)
        result["final"] = final
        if not failed:
            result["states"].append(
                save_state(m, args.output / "final.mss")
            )
            result["screenshots"].append(
                take_screenshot(m, args.output / "final.png")
            )

    result["result"] = "red" if result["failure"] else "green"
    target = args.output / "results.json"
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": result["result"],
                "failure": result["failure"],
                "final": result["final"],
                "results": str(target),
            },
            sort_keys=True,
        )
    )
    return int(result["failure"] is not None)


if __name__ == "__main__":
    raise SystemExit(main())
