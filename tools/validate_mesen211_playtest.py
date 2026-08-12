#!/usr/bin/env python3
"""Replay the reported coin/start/charge sequence in Mesen 2.1.1.

The input path is Mesen's real port-0 controller override.  No game, gate,
sound, palette, or renderer memory is written.  A Mesen-created checkpoint is
required so emulator-specific rendering failures are never investigated with
a Nexen state.

This is checkpointed compatibility evidence, not a cold-boot, performance, or
full-playability claim.
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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

from capture_gameplay_audio import analyze_wav


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"
REAL_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
TICK_HOOK = 0x00F5A3
CHARGED_SHOT_ENTRY_HOOK = 0x92EFFB
CHARGED_SHOT_CONTINUATION_HOOK = 0x94B580


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=8830)
    parser.add_argument("--coin-count", type=int, default=1)
    parser.add_argument("--coin-frames", type=int, default=16)
    parser.add_argument("--coin-gap-frames", type=int, default=30)
    parser.add_argument("--start-frames", type=int, default=16)
    parser.add_argument("--transition-frames", type=int, default=450)
    parser.add_argument("--transition-capture-step", type=int, default=1)
    parser.add_argument("--settle-frames", type=int, default=300)
    parser.add_argument(
        "--charge-ready-timeout-frames",
        type=int,
        default=300,
        help=(
            "maximum idle-controller frames to wait after settling until "
            "Superman is grounded and able to begin a charge"
        ),
    )
    parser.add_argument(
        "--charge-frames",
        type=int,
        default=900,
        help=(
            "frame request passed to legacy Mesen's timed input override; "
            "actual emulated frames are measured independently"
        ),
    )
    parser.add_argument("--minimum-charge-frames", type=int, default=180)
    parser.add_argument("--post-release-frames", type=int, default=600)
    parser.add_argument("--stall-frames", type=int, default=60)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


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


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def le32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def player_state(m: McpSession) -> dict[str, Any]:
    a6 = 0xF01302
    base = 0x400000 | ((a6 - 0x60) & 0xFFFF)
    raw = m.read_memory("snesMemory", base, 0x80)

    def byte(offset: int) -> int:
        return raw[0x60 + offset]

    def word(offset: int) -> int:
        index = 0x60 + offset
        return be16(raw[index : index + 2])

    return {
        "active_task_a6": le32(
            m.read_memory("Sa1Memory", 0x0038, 4)
        )
        & 0xFFFFFF,
        "health": word(-0x4E),
        "input": byte(-0x44),
        "previous_input": byte(-0x43),
        "action_state": byte(-0x23),
        "flags": byte(-0x24),
        "animation": word(-0x1A),
        "animation_step": word(-0x18),
        "x": word(-0x1E),
        "y": word(-0x22),
        "locals_sha256": digest(raw),
    }


def charge_ready(player: dict[str, Any]) -> bool:
    return (
        int(player["health"]) > 0
        and int(player["input"]) == 0xFF
        and int(player["y"]) == 112
        and (int(player["flags"]) & 0x08) == 0
    )


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    state = m.get_state()
    virtual = m.read_memory("Sa1Memory", 0x0040, 0x10)
    doorbell = m.read_memory("snesMemory", 0x3300, 4)
    render = m.read_memory("snesWorkRam", 0x89A2, 4)
    meta = m.read_memory("snesWorkRam", 0x89D2, 8)
    tad = m.read_memory("snesWorkRam", 0x1F00, 0x20)
    return {
        "label": label,
        "frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "pc68k": le32(virtual[0:4]) & 0xFFFFFF,
        "opcode68k": le16(virtual[4:6]),
        "halt": le16(virtual[0x0E:0x10]),
        "task_mask": be16(
            m.read_memory("snesMemory", 0x400002, 2)
        ),
        "frame_request": le16(doorbell[0:2]),
        "frame_ack": le16(doorbell[2:4]),
        "render_complete_count": le16(render[0:2]),
        "render_complete_generation": le16(render[2:4]),
        "render_queue_primary": le16(meta[0:2]),
        "render_queue_drops": le16(meta[2:4]),
        "render_queue_secondary": le16(meta[4:6]),
        "input_mailbox": m.read_memory(
            "snesMemory", 0x410000, 2
        ).hex(),
        "input_injection": m.read_memory(
            "snesMemory", 0x410002, 2
        ).hex(),
        "tad": {
            "raw": tad.hex(),
            "state": tad[0x02],
            "previous_command": tad[0x05],
            "next_song": tad[0x0C],
            "next_command": tad[0x0D],
            "sound_tick_cursor": le16(tad[0x14:0x16]),
            "drained_count": tad[0x16],
            "last_arcade_command": tad[0x17],
            "sound_tick_calls": le16(tad[0x1C:0x1E]),
        },
        "palette": {
            "live_sha256": digest(
                m.read_memory("snesMemory", 0x412000, 0x400)
            ),
            "cache_sha256": digest(
                m.read_memory("snesWorkRam", 0x2800, 0x400)
            ),
            "staging_sha256": digest(
                m.read_memory("snesWorkRam", 0x8000, 0x200)
            ),
            "cgram_sha256": digest(
                m.read_memory("snesCgRam", 0, 0x200)
            ),
        },
        "player": player_state(m),
    }


def take_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "bytes": target.stat().st_size,
        "response": response,
    }


def wait_for_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def save_state(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.save_state(target)
    wait_for_file(target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def run_exact_frames(m: McpSession, count: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    remaining = count
    while remaining:
        result = m.run_frames(remaining)
        advanced = int(result.get("framesAdvanced", 0))
        if advanced <= 0 or advanced > remaining:
            raise RuntimeError(
                f"invalid run progress: remaining={remaining}, result={result}"
            )
        results.append(result)
        remaining -= advanced
        m.pause()
    return results


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
        label = handles.get(int(params.get("handle", -1)))
        if label is None:
            continue
        events.append(
            {
                "label": label,
                "frame": int(params.get("frame", 0)),
                "address": int(params.get("address", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "cpu_type": params.get("cpuType"),
            }
        )
    return events


def main() -> int:
    args = parse_args()
    positive = (
        args.coin_frames,
        args.coin_gap_frames,
        args.start_frames,
        args.transition_frames,
        args.transition_capture_step,
        args.charge_ready_timeout_frames,
        args.charge_frames,
        args.minimum_charge_frames,
        args.post_release_frames,
        args.stall_frames,
    )
    if args.coin_count < 0 or min(positive) <= 0 or args.settle_frames < 0:
        raise SystemExit("frame counts must be positive (settle may be zero)")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    transition_dir = output / "transition"
    release_dir = output / "release"
    transition_dir.mkdir()
    release_dir.mkdir()
    configure_dotnet8()

    result: dict[str, Any] = {
        "scope": (
            "checkpointed Mesen 2.1.1 coin/start/charged-shot compatibility "
            "diagnostic; real port-0 input; no runtime memory writes; not "
            "cold-boot, performance, stability, or full-playability evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "mesen": str(args.mesen.resolve()),
        "mesen_sha256": sha256(args.mesen),
        "mesen_2_1_1_binary": str(REAL_MESEN),
        "mesen_2_1_1_binary_sha256": sha256(REAL_MESEN),
        "input_transport": "Mesen port-0 controller override",
        "runtime_memory_pokes": [],
        "schedule": {
            "coin_count": args.coin_count,
            "coin_frames": args.coin_frames,
            "coin_gap_frames": args.coin_gap_frames,
            "start_frames": args.start_frames,
            "transition_frames": args.transition_frames,
            "transition_capture_step": args.transition_capture_step,
            "settle_frames": args.settle_frames,
            "charge_ready_timeout_frames": (
                args.charge_ready_timeout_frames
            ),
            "charge_frames": args.charge_frames,
            "minimum_charge_frames": args.minimum_charge_frames,
            "post_release_frames": args.post_release_frames,
        },
    }
    transition: list[dict[str, Any]] = []
    release: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    first_stall: dict[str, Any] | None = None
    transition_wav_path = output / "title-through-transition.wav"
    gameplay_wav_path = output / "gameplay-charge-release.wav"

    with McpSession(
        rom=rom,
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        result["title_start"] = snapshot(m, "title_start")
        result["title_start_screenshot"] = take_screenshot(
            m, output / "title-start.png"
        )
        result["title_start_state"] = save_state(
            m, output / "title-start.mss"
        )
        audio_recording = False
        m.record_audio(transition_wav_path)
        audio_recording = True
        try:
            result["coin_runs"] = []
            for coin_index in range(1, args.coin_count + 1):
                coin_run = m.set_input(
                    McpSession.BTN_SELECT, args.coin_frames
                )
                coin_state = snapshot(m, f"after_coin_{coin_index}")
                gap_run = run_exact_frames(m, args.coin_gap_frames)
                result["coin_runs"].append(
                    {
                        "coin": coin_index,
                        "run": coin_run,
                        "state": coin_state,
                        "gap_run": gap_run,
                    }
                )
            result["after_coin"] = snapshot(m, "after_coin")
            result["start_run"] = m.set_input(
                McpSession.BTN_START, args.start_frames
            )
            result["after_start"] = snapshot(m, "after_start")
            result["after_start_screenshot"] = take_screenshot(
                m, output / "after-start.png"
            )

            for index in range(1, args.transition_frames + 1):
                run_exact_frames(m, 1)
                snap = snapshot(m, f"transition_{index:04d}")
                if (
                    index == 1
                    or index == args.transition_frames
                    or index % args.transition_capture_step == 0
                ):
                    snap["screenshot"] = take_screenshot(
                        m, transition_dir / f"frame-{index:04d}.png"
                    )
                transition.append(snap)
                if index % 50 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "transition_progress",
                                "relative_frame": index,
                                "video_frame": snap["frame"],
                                "tick": snap["tick"],
                                "task_mask": snap["task_mask"],
                                "render_complete": snap[
                                    "render_complete_count"
                                ],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

            result["transition_end_state"] = save_state(
                m, output / "transition-end.mss"
            )
            result["settle_run"] = run_exact_frames(
                m, args.settle_frames
            )
            ready_initial = player_state(m)
            ready_player = ready_initial
            ready_frames = 0
            while (
                not charge_ready(ready_player)
                and ready_frames < args.charge_ready_timeout_frames
            ):
                run_exact_frames(m, 1)
                ready_frames += 1
                ready_player = player_state(m)
            result["charge_ready_wait"] = {
                "timeout_frames": args.charge_ready_timeout_frames,
                "frames_waited": ready_frames,
                "ready": charge_ready(ready_player),
                "initial_player": ready_initial,
                "final_player": ready_player,
            }
            result["before_charge"] = snapshot(m, "before_charge")
            result["before_charge_screenshot"] = take_screenshot(
                m, output / "before-charge.png"
            )
            m.stop_audio()
            audio_recording = False
            m.record_audio(gameplay_wav_path)
            audio_recording = True

            handles: dict[int, str] = {}
            for address, label in (
                (TICK_HOOK, "game_tick"),
                (CHARGED_SHOT_ENTRY_HOOK, "charged_shot_entry"),
                (
                    CHARGED_SHOT_CONTINUATION_HOOK,
                    "charged_shot_continuation",
                ),
            ):
                handle = m.add_exec_hook(address, cpu_type="Sa1")
                handles[handle] = label
            m.drain_notifications(timeout=0.05)
            charge_start_frame = int(
                m.get_state().get("frameCount", 0)
            )
            charge_response = m.set_input(
                McpSession.BTN_B, args.charge_frames
            )
            charge_end_frame = int(
                m.get_state().get("frameCount", 0)
            )
            result["charge_run"] = {
                "response": charge_response,
                "start_frame": charge_start_frame,
                "end_frame": charge_end_frame,
                "actual_frames": charge_end_frame - charge_start_frame,
            }
            events.extend(
                hook_events(m.drain_notifications(timeout=0.05), handles)
            )
            result["held"] = snapshot(m, "held")
            result["held_screenshot"] = take_screenshot(
                m, output / "held.png"
            )
            result["held_state"] = save_state(m, output / "held.mss")

            stagnant_frames = 0
            previous_tick = int(result["held"]["tick"])
            capture_release = {
                1,
                2,
                3,
                4,
                8,
                16,
                32,
                60,
                120,
                240,
                480,
                args.post_release_frames,
            }
            for index in range(1, args.post_release_frames + 1):
                run_exact_frames(m, 1)
                chunk_events = hook_events(
                    m.drain_notifications(timeout=0.01), handles
                )
                events.extend(chunk_events)
                snap = snapshot(m, f"release_{index:04d}")
                if index in capture_release:
                    snap["screenshot"] = take_screenshot(
                        m, release_dir / f"frame-{index:04d}.png"
                    )
                if int(snap["tick"]) == previous_tick:
                    stagnant_frames += 1
                else:
                    stagnant_frames = 0
                    previous_tick = int(snap["tick"])
                release.append(snap)
                if first_stall is None and stagnant_frames >= args.stall_frames:
                    first_stall = {
                        "relative_frame": index,
                        "stagnant_frames": stagnant_frames,
                        "snapshot": snap,
                        "state": save_state(
                            m, output / "first-stall.mss"
                        ),
                        "screenshot": take_screenshot(
                            m, output / "first-stall.png"
                        ),
                    }
                    break
                if index % 60 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "release_progress",
                                "relative_frame": index,
                                "video_frame": snap["frame"],
                                "tick": snap["tick"],
                                "halt": snap["halt"],
                                "render_complete": snap[
                                    "render_complete_count"
                                ],
                                "stagnant_frames": stagnant_frames,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

            for handle in handles:
                m.remove_hook(handle)
            result["final"] = snapshot(m, "final")
            result["final_screenshot"] = take_screenshot(
                m, output / "final.png"
            )
            result["final_state"] = save_state(m, output / "final.mss")
        finally:
            try:
                m.pause()
            except Exception:
                pass
            if audio_recording:
                try:
                    m.stop_audio()
                except Exception:
                    pass

    transition_path = output / "transition.jsonl"
    transition_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in transition)
    )
    release_path = output / "release.jsonl"
    release_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in release)
    )
    hooks_path = output / "hooks.jsonl"
    hooks_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in events)
    )
    result["transition"] = {
        "path": str(transition_path),
        "sha256": sha256(transition_path),
        "frames": len(transition),
    }
    result["release"] = {
        "path": str(release_path),
        "sha256": sha256(release_path),
        "frames": len(release),
    }
    result["hooks"] = {
        "path": str(hooks_path),
        "sha256": sha256(hooks_path),
        "counts": {
            label: sum(event["label"] == label for event in events)
            for label in (
                "game_tick",
                "charged_shot_entry",
                "charged_shot_continuation",
            )
        },
    }
    result["stall"] = first_stall
    result["transition_audio"] = analyze_wav(transition_wav_path)
    result["gameplay_audio"] = analyze_wav(gameplay_wav_path)
    held = result["held"]
    final = result["final"]
    checks = {
        "transition_completed": len(transition) == args.transition_frames,
        "charge_hold_reached_requested_minimum": (
            result["charge_run"]["actual_frames"]
            >= args.minimum_charge_frames
        ),
        "charge_started_from_ready_state": result["charge_ready_wait"][
            "ready"
        ],
        "charged_shot_entry_reached": (
            result["hooks"]["counts"]["charged_shot_entry"] > 0
        ),
        "charged_shot_continuation_reached": (
            result["hooks"]["counts"]["charged_shot_continuation"] > 0
        ),
        "no_sustained_tick_stall": first_stall is None,
        "interpreter_not_halted": final["halt"] == 0,
        "ticks_progressed_after_release": (
            (final["tick"] - held["tick"]) & 0xFFFF
        )
        > 0,
        "renderer_progressed_after_release": (
            (
                final["render_complete_count"]
                - held["render_complete_count"]
            )
            & 0xFFFF
        )
        > 0,
        "gameplay_audio_has_no_internal_750ms_silence": (
            not result["gameplay_audio"]["internal_quiet_runs_750ms"]
        ),
    }
    result["checks"] = checks
    result["result"] = "green" if all(checks.values()) else "red"
    result_path = output / "results.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "event": "complete",
                "result": result["result"],
                "rom_sha256": result["rom_sha256"],
                "failed_checks": [
                    name for name, passed in checks.items() if not passed
                ],
                "hooks": result["hooks"]["counts"],
                "stall_frame": (
                    first_stall["relative_frame"]
                    if first_stall is not None
                    else None
                ),
                "gameplay_audio": {
                    "duration_s": result["gameplay_audio"]["duration_s"],
                    "active_duration_s": result["gameplay_audio"][
                        "active_duration_s"
                    ],
                    "quiet_runs_750ms": result["gameplay_audio"][
                        "internal_quiet_runs_750ms"
                    ],
                },
                "results": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
