#!/usr/bin/env python3
"""Classify one organic player-damage tick against the arcade movie.

The retained MAME movie first damages Superman during tick 1157 -> 1158.
This tool:

* captures exact MAME boundaries at ticks 1000, 1157, and 1158;
* retains MAME and SNES pre/post save states and complete mapped work RAM;
* replays the real controller transitions from the fresh-run tick-1000
  checkpoint with production native gates on and with the gameplay xlat/choke
  gates off while retaining the scheduler machinery required by that loaded
  coroutine state;
* records registers, CCR/X, stack residue, object/collision state, health
  writes, task contexts, and virtual-IRQ state; and
* classifies whether the missed organic hit is native/HLE-local or was already
  present in the shared interpreter/hardware-boundary state.

This is a focused checkpoint differential.  The checkpoint is retained by
``replay_mame_controller_campaign.py`` from a separately evidenced fresh boot;
this tool never presents its state-loaded replays as fresh-ROM proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_TIMELINE = EVIDENCE / "full-playback-timeline-v1" / "timeline.jsonl"
DEFAULT_CHECKPOINT = (
    EVIDENCE
    / "fresh-controller-campaign-5382968-nexen-v1"
    / "states"
    / "checkpoint-01000.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
MAME_MCP = Path("/home/chad/mame-mcp")
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MOVIE = ROOT / "inp" / "superman_play.inp"
MAME_CFG = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
MAME_STANDALONE_LUA = (
    MAME_TRACE / "capture_organic_player_damage.lua"
)

CHECKPOINT_MAME_TICK = 1000
PRE_DAMAGE_TICK = 1157
POST_DAMAGE_TICK = 1158
EXPECTED_MAME_FRAMES = {
    # MAME's screen:frame_number() is one behind the Lua exporter's
    # frame_done counter used by timeline.jsonl.
    CHECKPOINT_MAME_TICK: 1073,
    PRE_DAMAGE_TICK: 1230,
    POST_DAMAGE_TICK: 1231,
}
EARLY_SCREEN_FRAME_TICK_BIAS = 73
WORK_BASE = 0xF00000
WORK_SIZE = 0x4000
PLAYER_BASE_OFFSET = 0x12A2
PLAYER_SIZE = 0x70
PLAYER_HEALTH_OFFSET = 0x12B4
PLAYER_ACTION_OFFSET = 0x12DF
ENEMY_BASE_OFFSET = 0x02DA
ENEMY_SIZE = 0x70
COLLISION_OFFSET = 0x3734
COLLISION_SIZE = 0x02C0
FIRST_ATTACK_OFFSET = 0x37F4
FIRST_ATTACK_SIZE = 0x10
RNG_STATE_OFFSET = 0x170E
TICK_IRAM = 0x0760
HALT_IRAM = 0x004E
NATIVE_GATES = {
    "xlat": 0x071A,
    "loop": 0x072E,
    "pacing": 0x0734,
    "select": 0x0736,
    "choke": 0x073A,
    "switch_in": 0x073C,
}
ORGANIC_DISABLE_GATES = ("xlat", "choke")
REG_NAMES = tuple(
    [f"D{index}" for index in range(8)]
    + [f"A{index}" for index in range(8)]
)


sys.path.insert(0, str(MAME_MCP))
sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))

from mame_mcp.session import MameSession  # noqa: E402
import mesen_mcp.session as _mesen_session  # noqa: E402

_mesen_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9240)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--checkpoint-mame-tick",
        type=int,
        default=CHECKPOINT_MAME_TICK,
        help="MAME tick represented by --checkpoint",
    )
    parser.add_argument(
        "--pre-damage-tick",
        type=int,
        default=PRE_DAMAGE_TICK,
        help="Last boundary before the expected player-health change",
    )
    parser.add_argument(
        "--post-damage-tick",
        type=int,
        default=POST_DAMAGE_TICK,
        help="Boundary immediately after --pre-damage-tick",
    )
    parser.add_argument(
        "--native-off-max-frames-per-tick",
        type=int,
        default=192,
        help=(
            "Maximum video-frame budget per emulated game tick while "
            "replaying with gameplay-native gates disabled."
        ),
    )
    parser.add_argument(
        "--native-off-max-frames-per-run",
        type=int,
        default=8,
        help=(
            "Maximum video frames in one Nexen run_until call while native "
            "gameplay gates are disabled.  Small chunks keep an interpreted "
            "timeout observable and interruptible."
        ),
    )
    parser.add_argument(
        "--native-off-wall-timeout",
        type=float,
        default=300.0,
        help=(
            "Wall-clock seconds allowed for one native-off tick span before "
            "the focused replay reports a timeout."
        ),
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("timeline", args.timeline),
        ("checkpoint", args.checkpoint),
        ("Nexen/Mesen", args.nexen),
        ("MAME", MAME),
        ("MAME movie", MAME_MOVIE),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.native_off_max_frames_per_tick <= 0:
        parser.error("--native-off-max-frames-per-tick must be positive")
    if args.native_off_max_frames_per_run <= 0:
        parser.error("--native-off-max-frames-per-run must be positive")
    if args.native_off_wall_timeout <= 0:
        parser.error("--native-off-wall-timeout must be positive")
    if not (
        0
        < args.checkpoint_mame_tick
        <= args.pre_damage_tick
        < args.post_damage_tick
    ):
        parser.error(
            "damage ticks must be ordered at or after the checkpoint"
        )
    if args.post_damage_tick != args.pre_damage_tick + 1:
        parser.error("--post-damage-tick must immediately follow the pre tick")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def be16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def le16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def le32(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def rng_next(state: int) -> int:
    """Original $000412 signed-positive gameplay RNG recurrence."""
    return (176 * (state or 1)) % 32749


def rng_forward_distance(start: int, target: int) -> int | None:
    """Return the forward recurrence distance within one complete cycle."""
    state = start
    if state == target:
        return 0
    for distance in range(1, 32750):
        state = rng_next(state)
        if state == target:
            return distance
    return None


def wait_for_file(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(path)


def mismatch_offsets(left: bytes, right: bytes) -> list[int]:
    if len(left) != len(right):
        raise ValueError(f"length mismatch: {len(left)} != {len(right)}")
    return [
        offset
        for offset, (lhs, rhs) in enumerate(zip(left, right))
        if lhs != rhs
    ]


def summarized_diff(left: bytes, right: bytes, base: int = 0) -> dict[str, Any]:
    offsets = mismatch_offsets(left, right)
    return {
        "different_bytes": len(offsets),
        "first_offsets": [f"{base + offset:04X}" for offset in offsets[:64]],
        "equal": not offsets,
    }


def decode_collision_record(address: int, raw: bytes) -> dict[str, Any]:
    return {
        "address": f"F0{address:04X}",
        "raw": raw.hex(),
        "words": [be16(raw, offset) for offset in range(0, len(raw), 2)],
        "active": be16(raw),
    }


def decode_object(offset: int, raw: bytes) -> dict[str, Any]:
    return {
        "address": f"F0{offset:04X}",
        "raw": raw.hex(),
        "type": be16(raw, 0x00),
        "health_byte_03": raw[0x03],
        "flags": [raw[index] for index in (0x04, 0x06, 0x07, 0x08)],
        "animation_count": be16(raw, 0x0E),
        "animation_pointer": f"{be32(raw, 0x10):08X}",
        "frame_pointer": f"{be32(raw, 0x14):08X}",
        "action": raw[0x23],
        "world_x": be16(raw, 0x2E),
        "world_y": be16(raw, 0x32),
        "screen_x": be16(raw, 0x3E),
        "screen_y": be16(raw, 0x40),
        "collision_pointers": [
            f"{be32(raw, index):08X}" for index in (0x46, 0x4A, 0x4E)
        ],
        "timer": be16(raw, 0x5E),
    }


def decode_work(work: bytes) -> dict[str, Any]:
    collision = work[COLLISION_OFFSET : COLLISION_OFFSET + COLLISION_SIZE]
    positive = []
    for relative in range(0, len(collision), 0x10):
        raw = collision[relative : relative + 0x10]
        active = be16(raw)
        if 0 < active < 0x8000:
            positive.append(
                decode_collision_record(COLLISION_OFFSET + relative, raw)
            )
    return {
        "sha256": digest(work),
        "task_mask": be16(work, 0x0002),
        "task_contexts": [
            f"{be32(work, 0x000A + index * 4):08X}"
            for index in range(16)
        ],
        "rng_state": be16(work, RNG_STATE_OFFSET),
        "player": decode_object(
            PLAYER_BASE_OFFSET,
            work[PLAYER_BASE_OFFSET : PLAYER_BASE_OFFSET + PLAYER_SIZE],
        ),
        "player_health": be16(work, PLAYER_HEALTH_OFFSET),
        "player_action": work[PLAYER_ACTION_OFFSET],
        "enemy": decode_object(
            ENEMY_BASE_OFFSET,
            work[ENEMY_BASE_OFFSET : ENEMY_BASE_OFFSET + ENEMY_SIZE],
        ),
        "first_attack": decode_collision_record(
            FIRST_ATTACK_OFFSET,
            work[FIRST_ATTACK_OFFSET : FIRST_ATTACK_OFFSET + FIRST_ATTACK_SIZE],
        ),
        "positive_collision_records": positive,
    }


def mame_registers(raw: dict[str, Any]) -> dict[str, Any]:
    regs = {
        name: int(raw[name]) & 0xFFFFFFFF
        for name in REG_NAMES[:-1]
    }
    # capture_game_tick fires after the $3A92 MOVEM has pushed 60 bytes.
    regs["A7"] = (int(raw["SP"]) + 60) & 0xFFFFFFFF
    sr = int(raw["SR"]) & 0xFFFF
    a7 = regs["A7"] & 0xFFFF
    return {
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "sr": f"{sr:04X}",
        "ccr_xnzvc": sr & 0x1F,
        "interrupt_mask": (sr >> 8) & 7,
        "usp": f"{int(raw['USP']) & 0xFFFFFFFF:08X}",
        "entry_a7_reconstructed": f"{regs['A7']:08X}",
        "captured_sp_after_movem": f"{int(raw['SP']) & 0xFFFFFFFF:08X}",
        "stack_window_address": f"F0{(a7 - 32) & 0xFFFF:04X}",
    }


def retain_mame_capture(
    output: Path,
    name: str,
    tick: int,
    captured: dict[str, Any],
) -> dict[str, Any]:
    frame = int(captured["frame"])
    if frame != EXPECTED_MAME_FRAMES[tick]:
        raise RuntimeError(
            f"MAME tick {tick}: frame {frame}, "
            f"expected {EXPECTED_MAME_FRAMES[tick]}"
        )
    work = bytes.fromhex(captured["hex"])
    if len(work) != WORK_SIZE:
        raise RuntimeError(f"MAME tick {tick}: work length {len(work)}")
    work_path = output / f"{name}.work.bin"
    work_path.write_bytes(work)
    raw_regs = captured["registers"]
    a7 = ((int(raw_regs["SP"]) + 60) & 0xFFFF)
    stack_start = (a7 - 32) & 0xFFFF
    stack = bytes(
        work[(stack_start + index) & 0x3FFF]
        for index in range(64)
    )
    result = {
        "name": name,
        "tick": tick,
        "frame": frame,
        "capture_pc": f"{int(captured['pc']) & 0xFFFFFF:06X}",
        "work": {
            "path": str(work_path),
            "sha256": sha256(work_path),
            "size": len(work),
        },
        "state": decode_work(work),
        "m68k": {
            **mame_registers(raw_regs),
            "stack_window": stack.hex(),
        },
        "_work": work,
    }
    return result


def probe_absolute_mame_tick(
    session: MameSession,
    timeout: float,
) -> dict[str, int]:
    """Consume one boundary and identify its absolute movie tick.

    The bridge is loaded by an unthrottled command line before Python can
    pause it, so one or more early ticks can pass before the first capture is
    armed.  Up through this Stage-1 window the retained movie has one tick per
    screen frame and screen frame = tick + 73.  Probing once makes every later
    ``nth`` relative to an observed absolute boundary rather than assuming the
    bridge won the startup race.
    """
    captured = session.cmd(
        "capture_game_tick",
        addr=WORK_BASE,
        len=2,
        nth=1,
        maxFrames=240,
        timeout=timeout,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME absolute-tick probe missed: {captured!r}")
    frame = int(captured["frame"])
    tick = frame - EARLY_SCREEN_FRAME_TICK_BIAS
    if tick <= 0 or tick >= CHECKPOINT_MAME_TICK:
        raise RuntimeError(
            f"MAME absolute-tick probe frame {frame} mapped to tick {tick}"
        )
    return {"frame": frame, "tick": tick}


def mame_damage_capture(output: Path, timeout: float) -> dict[str, Any]:
    mame_oracle = mame_identity()
    live = (output / "mame-live").resolve()
    cfg = (live / "cfg").resolve()
    nvram = (live / "nvram").resolve()
    for path in (live, cfg, nvram):
        path.mkdir(parents=True, exist_ok=True)
    if MAME_CFG.is_file():
        shutil.copy2(MAME_CFG, cfg / MAME_CFG.name)

    session = MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(MAME_TRACE / "roms"),
        workdir=str(live),
        extra_args=[
            "-playback",
            MAME_MOVIE.name,
            "-input_directory",
            str(MAME_MOVIE.parent),
            "-cfg_directory",
            str(cfg),
            "-nvram_directory",
            str(nvram),
            "-video",
            "none",
            "-sound",
            "none",
            "-throttle",
        ],
    )
    captures: dict[str, dict[str, Any]] = {}
    damage_events: Any = []
    try:
        session.launch(boot_wait=25)
        # Install the health tap before any audited boundary.  Issuing a bridge
        # command between the pre/post captures can permit a video frame to
        # pass before the next capture is armed.
        installed = session.exec_lua(
            "if ORGANIC_DAMAGE_TAP then ORGANIC_DAMAGE_TAP:remove() end; "
            "ORGANIC_DAMAGE_EVENTS={}; "
            "local cpu=M.devices[':maincpu']; "
            "local prog=cpu.spaces['program']; "
            "ORGANIC_DAMAGE_TAP=prog:install_write_tap("
            "0xF012B4,0xF012B5,'organic_player_damage',"
            "function(offset,data,mask) "
            "local r={}; "
            "for n,e in pairs(cpu.state) do "
            "r[n]=e.value & 0xFFFFFFFF end; "
            "ORGANIC_DAMAGE_EVENTS[#ORGANIC_DAMAGE_EVENTS+1]={"
            "offset=offset,data=data,mask=mask,"
            "pc=cpu.state['PC'].value & 0xFFFFFF,"
            "sr=cpu.state['SR'].value & 0xFFFF,regs=r}; "
            "return data end); return true"
        )
        if installed is not True:
            raise RuntimeError("MAME health write tap did not install")
        session.pause()
        initial_probe = probe_absolute_mame_tick(session, timeout)

        first = session.cmd(
            "capture_game_tick",
            addr=WORK_BASE,
            len=WORK_SIZE,
            nth=CHECKPOINT_MAME_TICK - initial_probe["tick"],
            maxFrames=EXPECTED_MAME_FRAMES[CHECKPOINT_MAME_TICK] + 120,
            timeout=timeout,
        )
        captures["tick1000"] = retain_mame_capture(
            output, "mame-tick-01000", CHECKPOINT_MAME_TICK, first
        )

        pre = session.cmd(
            "capture_game_tick",
            addr=WORK_BASE,
            len=WORK_SIZE,
            nth=PRE_DAMAGE_TICK - CHECKPOINT_MAME_TICK,
            maxFrames=PRE_DAMAGE_TICK - CHECKPOINT_MAME_TICK + 120,
            timeout=timeout,
        )
        captures["pre"] = retain_mame_capture(
            output, "mame-pre-tick-01157", PRE_DAMAGE_TICK, pre
        )

        # These calls must remain adjacent.
        post = session.cmd(
            "capture_game_tick",
            addr=WORK_BASE,
            len=WORK_SIZE,
            nth=1,
            maxFrames=120,
            timeout=timeout,
        )
        captures["post"] = retain_mame_capture(
            output, "mame-post-tick-01158", POST_DAMAGE_TICK, post
        )
        damage_events = session.exec_lua(
            "local answer=ORGANIC_DAMAGE_EVENTS or {}; "
            "if ORGANIC_DAMAGE_TAP then "
            "ORGANIC_DAMAGE_TAP:remove(); ORGANIC_DAMAGE_TAP=nil end; "
            "return answer"
        )
    finally:
        session.stop()

    captures["pre"]["state_file"] = capture_mame_prestate(output, timeout)

    pre_work = captures["pre"].pop("_work")
    post_work = captures["post"].pop("_work")
    tick1000_work = captures["tick1000"].pop("_work")
    return {
        "binary": str(MAME),
        "binary_sha256": mame_oracle["sha256"],
        "version": mame_oracle["version"],
        "snap_revision": mame_oracle["snap_revision"],
        "gnome_content_revision": mame_oracle[
            "gnome_content_revision"
        ],
        "movie": str(MAME_MOVIE),
        "movie_sha256": sha256(MAME_MOVIE),
        "captures": captures,
        "initial_probe": initial_probe,
        "health_write_events": damage_events,
        "expected_transition": {
            "health": [
                be16(pre_work, PLAYER_HEALTH_OFFSET),
                be16(post_work, PLAYER_HEALTH_OFFSET),
            ],
            "action": [
                pre_work[PLAYER_ACTION_OFFSET],
                post_work[PLAYER_ACTION_OFFSET],
            ],
        },
        "_work": {
            "tick1000": tick1000_work,
            "pre": pre_work,
            "post": post_work,
        },
    }


def capture_mame_prestate(output: Path, timeout: float) -> dict[str, Any]:
    """Retain the pre-damage MAME state without perturbing the adjacent oracle."""
    live = (output / "mame-prestate-live").resolve()
    cfg = (live / "cfg").resolve()
    nvram = (live / "nvram").resolve()
    states = (output / "mame-prestate-states").resolve()
    for path in (live, cfg, nvram, states):
        path.mkdir(parents=True, exist_ok=True)
    if MAME_CFG.is_file():
        shutil.copy2(MAME_CFG, cfg / MAME_CFG.name)
    state_name = "organic-damage-pre-tick-01157"
    response: dict[str, Any] | None = None
    session = MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(MAME_TRACE / "roms"),
        workdir=str(live),
        state_directory=str(states),
        extra_args=[
            "-playback",
            MAME_MOVIE.name,
            "-input_directory",
            str(MAME_MOVIE.parent),
            "-cfg_directory",
            str(cfg),
            "-nvram_directory",
            str(nvram),
            "-video",
            "none",
            "-sound",
            "none",
            "-throttle",
        ],
    )
    try:
        session.launch(boot_wait=25)
        session.pause()
        initial_probe = probe_absolute_mame_tick(session, timeout)
        pre = session.cmd(
            "capture_game_tick",
            addr=WORK_BASE,
            len=2,
            nth=PRE_DAMAGE_TICK - initial_probe["tick"],
            maxFrames=EXPECTED_MAME_FRAMES[PRE_DAMAGE_TICK] + 120,
            timeout=timeout,
        )
        frame = int(pre["frame"])
        if frame != EXPECTED_MAME_FRAMES[PRE_DAMAGE_TICK]:
            raise RuntimeError(
                f"MAME pre-state replay reached frame {frame}, expected "
                f"{EXPECTED_MAME_FRAMES[PRE_DAMAGE_TICK]}"
            )
        response = session.save_state(state_name)
        # MAME queues state serialization for a safe boundary.  Advance only
        # this separate replay to flush the requested file.
        session.cmd(
            "capture_game_tick",
            addr=WORK_BASE,
            len=2,
            nth=1,
            maxFrames=120,
            timeout=timeout,
        )
    finally:
        session.stop()
    path = states / "superman" / f"{state_name}.sta"
    wait_for_file(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
        "save_response": response,
        "initial_probe": initial_probe,
        "requested_at_tick": PRE_DAMAGE_TICK,
        "requested_at_frame": EXPECTED_MAME_FRAMES[PRE_DAMAGE_TICK],
        "note": (
            "save requested while paused at the exact tick-1157 capture; "
            "a separate replay was advanced only to flush MAME's queued write"
        ),
    }


def standalone_boundary(
    capture_dir: Path,
    row: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    tick = int(row["tick"])
    path = capture_dir / f"mame-tick-{tick:05d}.work.bin"
    work_full = path.read_bytes()
    if len(work_full) != 0x10000:
        raise RuntimeError(
            f"{path}: expected 64 KiB, got {len(work_full)} bytes"
        )
    work = work_full[:WORK_SIZE]
    raw_regs = dict(row)
    raw_regs["SP"] = int(row["A7"])
    expected = (
        tick + 74,
        int(reference["health"]),
        int(reference["player_x"]),
        int(reference["player_y"]),
        int(reference["action"]),
    )
    observed = (
        int(row["frame"]),
        int(row["health"]),
        int(row["player_x"]),
        int(row["player_y"]),
        int(row["action"]),
    )
    if observed != expected:
        raise RuntimeError(
            f"MAME tick {tick}: observed {observed}, expected {expected}"
        )
    a7 = ((int(row["A7"]) + 60) & 0xFFFF)
    stack_start = (a7 - 32) & 0xFFFF
    stack = bytes(
        work_full[(stack_start + index) & 0xFFFF]
        for index in range(64)
    )
    return {
        "name": str(row["name"]),
        "tick": tick,
        "frame": int(row["frame"]),
        "input_ports": {
            "in0": int(row["in0"]),
            "in2": int(row["in2"]),
        },
        "work": {
            "path": str(path),
            "sha256": sha256(path),
            "size": len(work_full),
            "mapped_16k_sha256": digest(work),
            "upper_48k_sha256": digest(work_full[WORK_SIZE:]),
        },
        "state": decode_work(work),
        "m68k": {
            **mame_registers(raw_regs),
            "stack_window": stack.hex(),
        },
        "_work": work,
    }


def mame_damage_capture_standalone(
    output: Path,
    timeout: float,
    tick_rows: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Run the exact movie uninterrupted under the standalone Lua oracle."""
    mame_oracle = mame_identity()
    capture_dir = (output / "mame-original").resolve()
    cfg = capture_dir / "cfg"
    nvram = capture_dir / "nvram"
    states = capture_dir / "states"
    for path in (capture_dir, cfg, nvram, states):
        path.mkdir(parents=True, exist_ok=True)
    command = [
        str(MAME),
        "superman",
        "-rompath",
        str(MAME_TRACE / "roms"),
        "-input_directory",
        str(MAME_MOVIE.parent),
        "-playback",
        MAME_MOVIE.name,
        "-video",
        "none",
        "-sound",
        "none",
        "-nothrottle",
        "-skip_gameinfo",
        "-autoboot_script",
        str(MAME_STANDALONE_LUA),
        "-autoboot_delay",
        "0",
        "-state_directory",
        str(states),
        "-nvram_directory",
        str(nvram),
        "-cfg_directory",
        str(cfg),
    ]
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        ORGANIC_DAMAGE_OUT=str(capture_dir),
        ORGANIC_DAMAGE_TICKS=",".join(
            str(tick)
            for tick in (
                CHECKPOINT_MAME_TICK,
                PRE_DAMAGE_TICK,
                POST_DAMAGE_TICK,
            )
        ),
        ORGANIC_DAMAGE_SAVE_TICK=str(PRE_DAMAGE_TICK),
        ORGANIC_DAMAGE_HEALTH_MIN=str(PRE_DAMAGE_TICK),
        ORGANIC_DAMAGE_HEALTH_MAX=str(POST_DAMAGE_TICK),
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    stdout_path = capture_dir / "mame.stdout.log"
    stderr_path = capture_dir / "mame.stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"standalone MAME exited {completed.returncode}; see {stderr_path}"
        )
    capture_path = capture_dir / "capture.jsonl"
    rows = [
        json.loads(line)
        for line in capture_path.read_text(encoding="utf-8").splitlines()
    ]
    boundaries = {
        int(row["tick"]): row
        for row in rows
        if row.get("event") == "boundary"
    }
    required = {
        CHECKPOINT_MAME_TICK,
        PRE_DAMAGE_TICK,
        POST_DAMAGE_TICK,
    }
    if set(boundaries) != required:
        raise RuntimeError(
            f"standalone MAME boundaries {sorted(boundaries)}, "
            f"expected {sorted(required)}"
        )
    health_rows = [
        row for row in rows if row.get("event") == "health_write"
    ]
    expected_pre_health = int(
        tick_rows[PRE_DAMAGE_TICK]["health"]
    )
    expected_post_health = int(
        tick_rows[POST_DAMAGE_TICK]["health"]
    )
    expected_health_writes = 1 if expected_pre_health != expected_post_health else 0
    if len(health_rows) != expected_health_writes:
        raise RuntimeError(
            f"expected {expected_health_writes} organic health writes, "
            f"got {len(health_rows)}"
        )
    if health_rows:
        health = health_rows[0]
        if (
            int(health["tick"]) != PRE_DAMAGE_TICK
            or int(health["old"]) != expected_pre_health
            or int(health["new"]) != expected_post_health
            or int(health["PC"]) != 0x012CEA
        ):
            raise RuntimeError(f"unexpected MAME health event: {health}")
        prewrite_path = capture_dir / f"{health['name']}.work.bin"
        prewrite_kind = "health_write_preimage"
    else:
        # A spurious console-only hit has no arcade health-write preimage.
        # Retain the exact pre-tick boundary instead so the three-way report
        # still has an authenticated arcade work image for the no-write case.
        prewrite_path = (
            capture_dir / f"mame-tick-{PRE_DAMAGE_TICK:05d}.work.bin"
        )
        prewrite_kind = "pre_tick_boundary_no_health_write"
    prewrite = prewrite_path.read_bytes()
    if len(prewrite) != 0x10000:
        raise RuntimeError(f"{prewrite_path}: bad pre-write work size")
    state_path = (
        states
        / "superman"
        / f"organic-player-damage-pre-tick-{PRE_DAMAGE_TICK:05d}.sta"
    )
    wait_for_file(state_path)

    captures = {
        "checkpoint": standalone_boundary(
            capture_dir,
            boundaries[CHECKPOINT_MAME_TICK],
            tick_rows[CHECKPOINT_MAME_TICK],
        ),
        "pre": standalone_boundary(
            capture_dir,
            boundaries[PRE_DAMAGE_TICK],
            tick_rows[PRE_DAMAGE_TICK],
        ),
        "post": standalone_boundary(
            capture_dir,
            boundaries[POST_DAMAGE_TICK],
            tick_rows[POST_DAMAGE_TICK],
        ),
    }
    captures["pre"]["state_file"] = {
        "path": str(state_path),
        "sha256": sha256(state_path),
        "size": state_path.stat().st_size,
        "requested_synchronously_at_tick": PRE_DAMAGE_TICK,
    }
    return {
        "binary": str(MAME),
        "binary_sha256": mame_oracle["sha256"],
        "version": mame_oracle["version"],
        "snap_revision": mame_oracle["snap_revision"],
        "gnome_content_revision": mame_oracle[
            "gnome_content_revision"
        ],
        "movie": str(MAME_MOVIE),
        "movie_sha256": sha256(MAME_MOVIE),
        "capture_script": str(MAME_STANDALONE_LUA),
        "capture_script_sha256": sha256(MAME_STANDALONE_LUA),
        "capture_log": str(capture_path),
        "capture_log_sha256": sha256(capture_path),
        "stdout": {
            "path": str(stdout_path),
            "sha256": sha256(stdout_path),
        },
        "stderr": {
            "path": str(stderr_path),
            "sha256": sha256(stderr_path),
        },
        "captures": captures,
        "health_write_events": health_rows,
        "health_prewrite_work": {
            "kind": prewrite_kind,
            "path": str(prewrite_path),
            "sha256": sha256(prewrite_path),
            "size": len(prewrite),
        },
        "expected_transition": {
            "health": [
                int(tick_rows[PRE_DAMAGE_TICK]["health"]),
                int(tick_rows[POST_DAMAGE_TICK]["health"]),
            ],
            "action": [
                int(tick_rows[PRE_DAMAGE_TICK]["action"]),
                int(tick_rows[POST_DAMAGE_TICK]["action"]),
            ],
        },
        "_work": {
            "checkpoint": captures["checkpoint"]["_work"],
            "pre": captures["pre"]["_work"],
            "post": captures["post"]["_work"],
        },
    }


def snes_registers(m: McpSession) -> dict[str, Any]:
    raw = bytes(m.read_memory("Sa1Memory", 0x0000, 0xB0))
    regs = {
        name: le32(raw, index * 4)
        for index, name in enumerate(REG_NAMES)
    }
    ccr = (
        ((le16(raw, 0xA2) & 1) << 4)
        | ((le16(raw, 0x70) & 1) << 3)
        | ((le16(raw, 0x60) & 1) << 2)
        | ((le16(raw, 0x72) & 1) << 1)
        | (le16(raw, 0x6E) & 1)
    )
    a7 = regs["A7"] & 0xFFFF
    stack_start = (a7 - 32) & 0xFFFF
    stack = bytes(
        m.read_memory(
            "snesMemory", 0x400000 | stack_start, 64
        )
    )
    return {
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "ccr_xnzvc": ccr,
        "interrupt_mask": le16(raw, 0x7C) & 7,
        "stack_window_address": f"F0{stack_start:04X}",
        "stack_window": stack.hex(),
    }


def hook_rows(notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in notifications
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def snes_boundary(
    m: McpSession,
    name: str,
    mame_tick: int,
    output: Path,
) -> dict[str, Any]:
    work = bytes(m.read_memory("snesMemory", 0x400000, WORK_SIZE))
    work_path = output / f"{name}.work.bin"
    work_path.write_bytes(work)
    iram = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0800))
    task_contexts = bytes(m.read_memory("snesMemory", 0x40000A, 16 * 4))
    state = m.get_state()
    return {
        "name": name,
        "mame_tick": mame_tick,
        "snes_tick": le16(iram, TICK_IRAM),
        "video_frame": int(state.get("frameCount", 0)),
        "halt": le16(iram, HALT_IRAM),
        "pc68k": f"{le32(iram, 0x40) & 0xFFFFFF:06X}",
        "opcode68k": f"{le16(iram, 0x44):04X}",
        "virtual_irq_pending": le16(iram, 0xAA),
        "virtual_irq_countdown": le16(iram, 0xAC),
        "task_mask": be16(work, 0x0002),
        "task_contexts": [
            f"{be32(task_contexts, index * 4):08X}" for index in range(16)
        ],
        "gates": {
            label: le16(iram, address)
            for label, address in NATIVE_GATES.items()
        },
        "work": {
            "path": str(work_path),
            "sha256": sha256(work_path),
            "size": len(work),
        },
        "state": decode_work(work),
        "m68k": snes_registers(m),
        "_work": work,
    }


def save_snes_state(
    m: McpSession, path: Path
) -> dict[str, Any]:
    response = m.save_state(path.resolve())
    wait_for_file(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
        "response": response,
    }


def set_gate(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, "Sa1Memory")


def run_tick_delta_with_budget(
    m: McpSession,
    delta: int,
    max_video_frames_per_tick: int,
    *,
    max_frames_per_run: int | None = None,
    wall_timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Exact tick advance with a wider safety budget for native-off replay."""
    if delta < 0:
        raise ValueError("negative tick delta")
    events: list[dict[str, Any]] = []
    remaining = delta
    while remaining:
        step = min(remaining, campaign.MAX_TICK_HOOK_STEP)
        before_tick = campaign.tick16(m)
        target = (before_tick + step) & 0xFFFF
        before_frame = int(m.get_state().get("frameCount", 0))
        hook = m.add_write_hook(
            TICK_IRAM,
            cpu_type="Sa1",
            match_value=target & 0xFF,
            match_value_mask=0xFF,
        )
        m.drain_notifications(timeout=0.02)
        runs: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []
        settled_after_tick_hook = False
        wall_started = time.monotonic()
        frames_spent = 0
        try:
            frame_budget = max(
                240,
                step * max_video_frames_per_tick + 240,
            )
            while frames_spent < frame_budget:
                if (
                    wall_timeout is not None
                    and time.monotonic() - wall_started >= wall_timeout
                ):
                    break
                run_frames = frame_budget - frames_spent
                if max_frames_per_run is not None:
                    run_frames = min(run_frames, max_frames_per_run)
                run = m.run_until(
                    max_frames=run_frames,
                    hook_handle=hook,
                )
                m.pause()
                runs.append(run)
                frames_advanced = int(run.get("framesAdvanced", 0))
                frames_spent += frames_advanced
                batch = m.drain_notifications(timeout=0.05)
                notifications.extend(batch)
                after_tick = campaign.tick16(m)
                if after_tick == target:
                    break
                fired_handles = {
                    int(row.get("params", {}).get("handle", -1))
                    for row in batch
                    if row.get("method")
                    == "notifications/mesen/hookFired"
                }
                if hook in fired_handles:
                    # A matched write hook pauses before the counter store has
                    # retired.  One video frame commits it while remaining
                    # below both the two-frame production tick and the much
                    # slower interpreted tick measured by this harness.
                    settle = m.run_frames(1)
                    m.pause()
                    settled_after_tick_hook = True
                    notifications.extend(
                        m.drain_notifications(timeout=0.05)
                    )
                    after_tick = campaign.tick16(m)
                    if after_tick == target:
                        break
                    if ((after_tick - target) & 0xFFFF) < 0x8000:
                        raise RuntimeError(
                            "tick-hook settle overshot target: "
                            f"after={after_tick}, target={target}, "
                            f"settle={settle!r}"
                        )
                if run.get("reason") != "hookFired":
                    # A bounded maxFrames return is expected in the very slow
                    # interpreted configuration.  Keep advancing in small
                    # calls until the aggregate frame or wall-clock budget is
                    # exhausted.
                    if frames_advanced <= 0:
                        break
                    continue
        finally:
            m.remove_hook(hook)
            notifications.extend(m.drain_notifications(timeout=0.05))
        after_tick = campaign.tick16(m)
        after_frame = int(m.get_state().get("frameCount", 0))
        event = {
            "before_tick": before_tick,
            "after_tick": after_tick,
            "target_tick": target,
            "tick_delta": step,
            "before_frame": before_frame,
            "after_frame": after_frame,
            "video_frames": after_frame - before_frame,
            "runs": runs,
            "notifications": notifications,
            "settled_after_tick_hook": settled_after_tick_hook,
            "max_video_frames_per_tick": max_video_frames_per_tick,
            "max_frames_per_run": max_frames_per_run,
            "wall_seconds": time.monotonic() - wall_started,
            "wall_timeout": wall_timeout,
        }
        events.append(event)
        if not runs or runs[-1].get("reason") != "hookFired":
            raise RuntimeError(f"game tick timeout: {event}")
        if after_tick != target:
            raise RuntimeError(f"game tick overshoot: {event}")
        if campaign.halt16(m):
            raise RuntimeError(
                f"interpreter halt ${campaign.halt16(m):04X}: {event}"
            )
        remaining -= step
    return events


def replay_console(
    args: argparse.Namespace,
    label: str,
    native_on: bool,
    timeline_inputs: list[campaign.InputEvent],
    checkpoint_buttons: int,
) -> dict[str, Any]:
    case_dir = args.output / label
    states_dir = case_dir / "states"
    states_dir.mkdir(parents=True)
    stderr = case_dir / "emulator.stderr.log"
    result: dict[str, Any] = {
        "label": label,
        "native_on": native_on,
        "checkpoint": {
            "path": str(args.checkpoint.resolve()),
            "sha256": sha256(args.checkpoint),
        },
    }
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr,
    ) as m:
        m.pause()
        m.load_state(args.checkpoint.resolve())
        m.pause()
        campaign.set_held_input(m, checkpoint_buttons)

        initial_gates = {
            name: le16(
                bytes(m.read_memory("Sa1Memory", address, 2))
            )
            for name, address in NATIVE_GATES.items()
        }
        if not native_on:
            # A production checkpoint is suspended inside the coroutine
            # scheduler contract.  Clearing switch-in/select/pacing at that
            # arbitrary point strands the loaded scheduler before another
            # game tick.  The project's established organic gate-off mode
            # disables the two gameplay dispatch paths while retaining that
            # infrastructure; the eventual isolated routine differential
            # disables every gate from a synthetic safe entry.
            for name in ORGANIC_DISABLE_GATES:
                set_gate(m, NATIVE_GATES[name], 0)
        configured_gates = {
            name: le16(
                bytes(m.read_memory("Sa1Memory", address, 2))
            )
            for name, address in NATIVE_GATES.items()
        }
        if native_on and configured_gates != initial_gates:
            raise RuntimeError("production gate state changed unexpectedly")
        if not native_on:
            uncleared = {
                name: configured_gates[name]
                for name in ORGANIC_DISABLE_GATES
                if configured_gates[name]
            }
            scheduler_changed = {
                name: (initial_gates[name], configured_gates[name])
                for name in NATIVE_GATES
                if name not in ORGANIC_DISABLE_GATES
                and initial_gates[name] != configured_gates[name]
            }
            if uncleared or scheduler_changed:
                raise RuntimeError(
                    "organic gameplay gates did not configure: "
                    f"uncleared={uncleared} "
                    f"scheduler_changed={scheduler_changed}"
                )
        result["initial_gates"] = initial_gates
        result["configured_gates"] = configured_gates

        current_mame_tick = CHECKPOINT_MAME_TICK
        current_buttons = checkpoint_buttons
        checkpoint_boundary = snes_boundary(
            m,
            f"{label}-tick-{current_mame_tick:05d}",
            current_mame_tick,
            case_dir,
        )
        result["checkpoint_boundary"] = checkpoint_boundary
        expected_raw_tick = checkpoint_boundary["snes_tick"]
        events_by_tick: dict[int, list[campaign.InputEvent]] = {}
        for event in timeline_inputs:
            if CHECKPOINT_MAME_TICK < event.tick <= PRE_DAMAGE_TICK:
                # Match replay_mame_controller_campaign.py: the tick-T
                # boundary first exposes the new physical input, then the
                # override is installed at T.  Gameplay consumes it on T+1.
                events_by_tick.setdefault(event.tick, []).append(event)

        trace = []
        frame_budget = (
            args.native_off_max_frames_per_tick if not native_on else 12
        )
        run_chunk = (
            args.native_off_max_frames_per_run if not native_on else None
        )
        wall_timeout = (
            args.native_off_wall_timeout if not native_on else None
        )
        for target in sorted(
            set(events_by_tick)
            | {PRE_DAMAGE_TICK}
        ):
            spans = run_tick_delta_with_budget(
                m,
                target - current_mame_tick,
                frame_budget,
                max_frames_per_run=run_chunk,
                wall_timeout=wall_timeout,
            )
            current_mame_tick = target
            expected_raw_tick = (
                expected_raw_tick + sum(int(row["tick_delta"]) for row in spans)
            ) & 0xFFFF
            actual_raw_tick = campaign.tick16(m)
            if actual_raw_tick != expected_raw_tick:
                raise RuntimeError(
                    f"{label}: tick drift {actual_raw_tick} != {expected_raw_tick}"
                )
            trace.append(
                {
                    "mame_tick": target,
                    "snes_tick": actual_raw_tick,
                    "buttons": current_buttons,
                    "player": campaign.player_snapshot(m),
                    "spans": spans,
                }
            )
            for event in events_by_tick.get(target, []):
                campaign.set_held_input(m, event.buttons)
                current_buttons = event.buttons
                trace.append(
                    {
                        "event": "input_apply",
                        "at_mame_tick": target,
                        "effective_mame_tick": event.tick,
                        "buttons": current_buttons,
                        "label": campaign.button_label(current_buttons),
                    }
                )

        pre = snes_boundary(
            m,
            f"{label}-pre-tick-{PRE_DAMAGE_TICK:05d}",
            PRE_DAMAGE_TICK,
            case_dir,
        )
        pre_state = save_snes_state(
            m,
            states_dir / f"{label}-pre-tick-{PRE_DAMAGE_TICK:05d}.mss",
        )

        handles = {
            m.add_write_hook(
                0x400000 + PLAYER_HEALTH_OFFSET,
                0x400000 + PLAYER_HEALTH_OFFSET + 1,
                cpu_type="Sa1",
            ): "player_health",
            m.add_write_hook(
                0x400000 + PLAYER_ACTION_OFFSET,
                cpu_type="Sa1",
            ): "player_action",
            m.add_write_hook(
                0x400000 + FIRST_ATTACK_OFFSET,
                0x400000 + FIRST_ATTACK_OFFSET + FIRST_ATTACK_SIZE - 1,
                cpu_type="Sa1",
            ): "first_attack",
            m.add_write_hook(HALT_IRAM, HALT_IRAM + 1, cpu_type="Sa1"): "halt",
        }
        m.drain_notifications(timeout=0.05)
        tick_span = run_tick_delta_with_budget(
            m,
            1,
            frame_budget,
            max_frames_per_run=run_chunk,
            wall_timeout=wall_timeout,
        )
        current_mame_tick = POST_DAMAGE_TICK
        notes = hook_rows(
            [
                notification
                for span in tick_span
                for notification in span["notifications"]
            ]
        )
        for handle in handles:
            m.remove_hook(handle)
        for row in notes:
            row["label"] = handles.get(int(row.get("handle", -1)), "unknown")

        post = snes_boundary(
            m,
            f"{label}-post-tick-{POST_DAMAGE_TICK:05d}",
            POST_DAMAGE_TICK,
            case_dir,
        )
        post_state = save_snes_state(
            m,
            states_dir / f"{label}-post-tick-{POST_DAMAGE_TICK:05d}.mss",
        )
        result.update(
            {
                "trace": trace,
                "pre": pre,
                "post": post,
                "pre_state": pre_state,
                "post_state": post_state,
                "damage_tick_span": tick_span,
                "write_events": notes,
                "transition": {
                    "health": [
                        pre["state"]["player_health"],
                        post["state"]["player_health"],
                    ],
                    "action": [
                        pre["state"]["player_action"],
                        post["state"]["player_action"],
                    ],
                    "first_attack_active": [
                        pre["state"]["first_attack"]["active"],
                        post["state"]["first_attack"]["active"],
                    ],
                },
            }
        )
    return result


def compare_boundary(
    mame_work: bytes,
    console_work: bytes,
) -> dict[str, Any]:
    ranges = {
        "full_mapped_work": (0, WORK_SIZE),
        "player_record": (PLAYER_BASE_OFFSET, PLAYER_BASE_OFFSET + PLAYER_SIZE),
        "enemy_record": (ENEMY_BASE_OFFSET, ENEMY_BASE_OFFSET + ENEMY_SIZE),
        "collision_table": (
            COLLISION_OFFSET,
            COLLISION_OFFSET + COLLISION_SIZE,
        ),
        "first_attack_record": (
            FIRST_ATTACK_OFFSET,
            FIRST_ATTACK_OFFSET + FIRST_ATTACK_SIZE,
        ),
    }
    return {
        label: summarized_diff(
            mame_work[start:stop],
            console_work[start:stop],
            start,
        )
        for label, (start, stop) in ranges.items()
    }


def stripped(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: stripped(item)
            for key, item in value.items()
            if key != "_work"
        }
    if isinstance(value, list):
        return [stripped(item) for item in value]
    return value


def main() -> int:
    global CHECKPOINT_MAME_TICK
    global PRE_DAMAGE_TICK
    global POST_DAMAGE_TICK
    global EXPECTED_MAME_FRAMES

    args = parse_args()
    mame_identity()
    os.environ.update(mame_environment(os.environ))
    CHECKPOINT_MAME_TICK = args.checkpoint_mame_tick
    PRE_DAMAGE_TICK = args.pre_damage_tick
    POST_DAMAGE_TICK = args.post_damage_tick
    EXPECTED_MAME_FRAMES = {
        tick: tick + EARLY_SCREEN_FRAME_TICK_BIAS
        for tick in (
            CHECKPOINT_MAME_TICK,
            PRE_DAMAGE_TICK,
            POST_DAMAGE_TICK,
        )
    }
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = (
        "/home/chad/.dotnet8"
        if args.nexen.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )

    inputs, tick_rows = campaign.load_timeline(
        # The exact pre-failure checkpoint can fall immediately after the
        # final input transition in this tiny window.  Include one preceding
        # tick so the shared loader has a transition to authenticate; replay
        # still filters events at or before CHECKPOINT_MAME_TICK below.
        args.timeline,
        max(0, CHECKPOINT_MAME_TICK - 1),
        POST_DAMAGE_TICK,
    )
    checkpoint_buttons = int(
        tick_rows[CHECKPOINT_MAME_TICK]["snes_buttons"]
    )
    mame = mame_damage_capture_standalone(
        args.output, args.timeout, tick_rows
    )
    native_off = replay_console(
        args, "native-off", False, inputs, checkpoint_buttons
    )
    native_on = replay_console(
        args, "native-on", True, inputs, checkpoint_buttons
    )

    comparisons = {}
    for boundary, mame_key, console_key in (
        (
            f"checkpoint_tick{CHECKPOINT_MAME_TICK}",
            "checkpoint",
            "checkpoint_boundary",
        ),
        (f"pre_tick{PRE_DAMAGE_TICK}", "pre", "pre"),
        (f"post_tick{POST_DAMAGE_TICK}", "post", "post"),
    ):
        comparisons[boundary] = {}
        for label, console in (
            ("native_off", native_off),
            ("native_on", native_on),
        ):
            comparisons[boundary][label] = compare_boundary(
                mame["_work"][mame_key],
                console[console_key]["_work"],
            )
        comparisons[boundary]["native_off_vs_on"] = compare_boundary(
            native_off[console_key]["_work"],
            native_on[console_key]["_work"],
        )

    off_transition = native_off["transition"]
    on_transition = native_on["transition"]
    arcade_transition = mame["expected_transition"]
    mame_checkpoint_rng = int(
        mame["captures"]["checkpoint"]["state"]["rng_state"]
    )
    off_checkpoint_rng = int(
        native_off["checkpoint_boundary"]["state"]["rng_state"]
    )
    on_checkpoint_rng = int(
        native_on["checkpoint_boundary"]["state"]["rng_state"]
    )
    snes_checkpoint_tick = int(
        native_on["checkpoint_boundary"]["snes_tick"]
    )
    tick_phase_delta = (
        snes_checkpoint_tick - CHECKPOINT_MAME_TICK
    ) & 0xFFFF
    rng_phase_delta = rng_forward_distance(
        mame_checkpoint_rng, on_checkpoint_rng
    )
    phase_alignment = {
        "mame_checkpoint_rng": f"{mame_checkpoint_rng:04X}",
        "native_off_checkpoint_rng": f"{off_checkpoint_rng:04X}",
        "native_on_checkpoint_rng": f"{on_checkpoint_rng:04X}",
        "snes_checkpoint_tick": snes_checkpoint_tick,
        "mame_checkpoint_tick": CHECKPOINT_MAME_TICK,
        "tick_phase_delta": tick_phase_delta,
        "rng_forward_steps_mame_to_snes": rng_phase_delta,
    }
    if (
        off_transition["health"] == arcade_transition["health"]
        and on_transition["health"] != arcade_transition["health"]
    ):
        classification = "native/HLE"
    elif (
        off_transition["health"] != arcade_transition["health"]
        and on_transition["health"] != arcade_transition["health"]
    ):
        if (
            off_transition == on_transition
            and off_checkpoint_rng == on_checkpoint_rng
            and mame_checkpoint_rng != on_checkpoint_rng
            and rng_phase_delta is not None
            and abs(rng_phase_delta - tick_phase_delta) <= 8
        ):
            classification = "hardware-boundary/timing_rng_phase"
        else:
            classification = (
                "interpreter_or_preexisting_hardware_timing_state"
            )
    elif (
        off_transition["health"] == arcade_transition["health"]
        and on_transition["health"] == arcade_transition["health"]
    ):
        classification = "no_longer_reproduces"
    else:
        classification = "unclassified_gate_interaction"

    result = {
        "scope": (
            "exact MAME movie boundaries plus same-checkpoint exact-emulator "
            "gameplay-xlat/choke-off versus production-on organic replay of "
            f"player-damage tick {PRE_DAMAGE_TICK}->{POST_DAMAGE_TICK}; "
            "focused state-loaded classification, not fresh boot"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": sha256(args.checkpoint),
        "checkpoint_mame_tick": CHECKPOINT_MAME_TICK,
        "pre_damage_tick": PRE_DAMAGE_TICK,
        "post_damage_tick": POST_DAMAGE_TICK,
        "checkpoint_buttons": checkpoint_buttons,
        "phase_alignment": phase_alignment,
        "timeline": str(args.timeline.resolve()),
        "timeline_sha256": sha256(args.timeline),
        "emulator": str(args.nexen.resolve()),
        "emulator_sha256": sha256(args.nexen),
        "mame": stripped(mame),
        "native_off": stripped(native_off),
        "native_on": stripped(native_on),
        "comparisons": comparisons,
        "classification": classification,
        "transitions": {
            "mame": arcade_transition,
            "native_off": off_transition,
            "native_on": on_transition,
        },
    }
    result_path = args.output / "results.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": (
                    "green"
                    if classification in ("native/HLE", "no_longer_reproduces")
                    else "red"
                ),
                "classification": classification,
                "transitions": result["transitions"],
                "results": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    # A reproduced discrepancy is intentionally red until its root cause has
    # a focused fix.  Native/HLE classification is evidence, not a pass.
    return 0 if classification == "no_longer_reproduces" else 1


if __name__ == "__main__":
    raise SystemExit(main())
