#!/usr/bin/env python3
"""Prove that a production gameplay checkpoint responds to the real controller.

Two fresh Nexen processes load the same production cold-boot checkpoint.  The
control process stays idle; the active process holds the selected port-0
buttons (Right+B by default).  No BW-RAM input injection is used.  Both variants
advance the same number of emulated video frames in one uninterrupted run and retain
coherent state, RAM, and screenshot evidence for a deterministic differential.

This is a focused interaction/liveness check, not an end-to-end FPS harness.
Use recovery_baseline.py for performance claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/current-cold-boot-300-v2/final.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = ROOT / "build/playability-20260720/current-real-controls"
SUPERVISOR_SOURCE_OFFSET = 0x095F
SUPERVISOR_TARGET_OFFSET = 0xF000
SUPERVISOR_LENGTH = 0x37

EXPECTED_GATES = {
    "loop": 1,
    "escape": 1,
    "choke": 1,
    "swin": 0xA55A,
    "select": 0x5EEC,
    "latch": 1,
}
PACING_CATCHUP_DEBT_MAX = 10

# WRAM execution addresses in the production video supervisor.  These are
# execution hooks, not FRAME_REQ/FRAME_ACK observations: ACK is claimed before
# the expensive draw and can coalesce several requests into one visual update.
# vf_tick is explicitly .org-pinned; the other phase entries are pinned by the
# renderer layout seams audited by the production build.
RENDER_HOOKS = {
    "render_start": 0x7F8918,
    "snapshot_start": 0x7FA100,
    "snapshot_direct": 0x7FA300,
    "snapshot_palette_dma": 0x7FA600,
    "snapshot_bg_dma": 0x7FA615,
    "snapshot_manifest_dma": 0x7FA62F,
    "snapshot_prepared_dma": 0x7FAABC,
    "ppu_build_cached": 0x7F9C1B,
    "bg_dispatch": 0x7F9B00,
    "frame_build_start": 0x7F80BA,
    "bg_heavy_start": 0x7F847E,
    "bg_incremental_start": 0x7FA680,
    "bg_incremental_cell": 0x7FA6E5,
    "bg_incremental_slot_ready": 0x7FA706,
    "bg_incremental_coordinates": 0x7FA742,
    "bg_dispatch_full": 0x7F9B25,
    "bg_slot_extended": 0x7FA800,
    "bg_slot_hit": 0x7FA835,
    "bg_slot_insert": 0x7FA83D,
    "bg_cache_reclaim": 0x7FA88D,
    "bg_prepared_start": 0x7FAAEB,
    "bg_prepared_hash": 0x7FAAF6,
    "bg_prepared_runs": 0x7FAB39,
    "bg_tile_run_dma": 0x7FAB81,
    "bg_no_slot": 0x7FA889,
    "bg_incremental_overflow": 0x7FA7B5,
    "bg_incremental_fallback": 0x7FA6E3,
    "bg_tile_dma": 0x7F859E,
    "bg_upload_start": 0x7F86D0,
    "obj_heavy_start": 0x7FA400,
    "obj_palette_fill": 0x7F82AB,
    "obj_upload_start": 0x7F9C27,
    "ppu_flush_start": 0x7F9D12,
    # First instruction after vid_frame returns.  This is the current pinned
    # vf_tick sequence's completion boundary, before renderer-busy is cleared.
    "render_complete": 0x7F8924,
}

# Optional fine-grained probes for the current pinned fast-OBJ layout.  Keep
# these out of the default phase set: the per-entry hooks are intentionally
# noisy and are useful only for short, checkpointed renderer attribution.
OBJ_HOOKS = {
    "obj_legacy_manifest_entry": 0x7FA45A,
    "obj_packed_entry": 0x7FAF60,
    "obj_palette_lookup": 0x7F8278,
    "obj_tile_lookup": 0x7F8756,
    "obj_oam_entry": 0x7FA4D5,
    "obj_manifest_done": 0x7FA4CD,
    "obj_hide_tail": 0x7FA570,
    "obj_palette_cache": 0x7FA593,
    "obj_upload_queue": 0x7FAC6E,
    "obj_tile_dma": 0x7FACA4,
    "obj_oam_dma": 0x7F8441,
}
GATE_ADDRS = {
    "loop": 0x072E,
    "escape": 0x071A,
    "choke": 0x073A,
    "swin": 0x073C,
    "select": 0x0736,
    "latch": 0x0768,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7591)
    parser.add_argument(
        "--active-buttons",
        type=lambda value: int(value, 0),
        default=McpSession.BTN_RIGHT | McpSession.BTN_B,
        help="Nexen port-0 button mask for the active variant (default: Right+B).",
    )
    parser.add_argument(
        "--expected-game-input",
        type=lambda value: int(value, 0),
        default=0x8100,
        help="Expected 16-bit game input-cache/mailbox value for active buttons.",
    )
    parser.add_argument(
        "--expected-game-p1",
        type=lambda value: int(value, 0),
        default=0xE7,
        help="Expected arcade-format P1 input byte for the active buttons.",
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "Lab only: replace the checkpoint's $7F:8000-$AFFF WRAM mirror "
            "with the current ROM bytes before running."
        ),
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=4,
        help="Number of 120-video-frame blocks to run without pausing.",
    )
    parser.add_argument(
        "--video-frames",
        type=int,
        help="Exact held-frame count; overrides --cycles for focused positioning.",
    )
    parser.add_argument(
        "--phase-hooks",
        action="store_true",
        help=(
            "Register every renderer phase hook. Use only with --cycles 1; "
            "longer runs can exceed Nexen's notification queue. The default "
            "uses only the true render-completion boundary."
        ),
    )
    parser.add_argument(
        "--obj-hooks",
        action="store_true",
        help=(
            "Add fine-grained fast-OBJ execution hooks. Use only with "
            "--phase-hooks and --cycles 1."
        ),
    )
    parser.add_argument(
        "--save-held-states",
        action="store_true",
        help="Retain each variant's exact held-final checkpoint for focused follow-up.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bg_offset_table() -> bytes:
    """Reproduce vid_init's immutable 16x32-cell -> SNES map lookup."""
    table = bytearray()
    for column in range(16):
        for offset in range(32):
            raw_x = column * 8 + (offset & 1) * 4
            value = (
                (offset & ~1) * 64
                + (raw_x & 0x3F)
                + (0x0800 if raw_x & 0x40 else 0)
            )
            table.extend(value.to_bytes(2, "little"))
    return bytes(table)


def le16(data: bytes) -> int:
    return data[0] | data[1] << 8


def le32(data: bytes) -> int:
    return le16(data) | le16(data[2:]) << 16


def stack_state(m: McpSession) -> dict[str, Any]:
    def r32(address: int) -> int:
        return le32(m.read_memory("Sa1Memory", address, 4))

    floor_bytes = m.read_memory("snesMemory", 0xC10882, 16 * 4)
    floors = [
        int.from_bytes(floor_bytes[index * 4 : index * 4 + 4], "big")
        for index in range(16)
    ]
    a5 = r32(0x0034) & 0xFFFFFF
    if not 0xF00000 <= a5 <= 0xF0FFFF:
        return {
            "a5": a5,
            "initialized": 0,
            "minimum_margin": None,
            "below_floor": [],
            "tasks": [],
        }

    base = a5 - 0xF00000
    tasks = []
    below_floor = []
    for index, floor in enumerate(floors):
        saved_sp = int.from_bytes(
            m.read_memory("snesMemory", 0x400000 + base + 0x0A + index * 4, 4),
            "big",
        )
        descriptor = int.from_bytes(
            m.read_memory("snesMemory", 0x400000 + base + 0x4E + index * 4, 4),
            "big",
        )
        if saved_sp == 0:
            continue
        task = {
            "index": index,
            "descriptor": descriptor,
            "saved_sp": saved_sp,
            "floor": floor,
            "margin": saved_sp - floor,
        }
        tasks.append(task)
        if task["margin"] < 0:
            below_floor.append(task)
    return {
        "a5": a5,
        "initialized": len(tasks),
        "minimum_margin": min((task["margin"] for task in tasks), default=None),
        "below_floor": below_floor,
        "tasks": tasks,
    }


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    def r32(address: int, memory_type: str = "Sa1Memory") -> int:
        return le32(m.read_memory(memory_type, address, 4))

    state = m.get_state()
    frame_request = r16(0x3300, "snesMemory")
    frame_ack = r16(0x3302, "snesMemory")
    return {
        "label": label,
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "pc68k": r32(0x0040) & 0xFFFFFF,
        "halt": r16(0x004E),
        "task_mask": r16(0x400002, "snesMemory"),
        "sound_ring_ptr": m.read_memory("snesMemory", 0x401C40, 4).hex(),
        "gates": {name: r16(address) for name, address in GATE_ADDRS.items()},
        "production_pacing_gate": r16(0x0734),
        "pacing_initialized": m.read_memory("snesMemory", 0x41012C, 1)[0],
        "pacing_supervisor_ready": m.read_memory("snesMemory", 0x41012D, 1)[0],
        "pacing_catchup_debt": m.read_memory("snesMemory", 0x410130, 1)[0],
        "frame_request": frame_request,
        "frame_ack": frame_ack,
        "frame_request_ack_lag": (frame_request - frame_ack) & 0xFFFF,
        "render_complete_count": r16(0x89A2, "snesWorkRam"),
        "render_complete_generation": r16(0x89A4, "snesWorkRam"),
        "render_ready_sequence": r16(0x1F1E, "snesWorkRam"),
        "render_queue_primary_state": r16(0x89D2, "snesWorkRam"),
        "render_queue_drops": r16(0x89D4, "snesWorkRam"),
        "render_queue_secondary_state": r16(0x89D6, "snesWorkRam"),
        "render_palette_change_count": r16(0x89A8, "snesWorkRam"),
        "render_bg_change_count": r16(0x89AA, "snesWorkRam"),
        "render_obj_change_count": r16(0x89AC, "snesWorkRam"),
        "render_last_obj_count": r16(0x89B2, "snesWorkRam"),
        "render_last_obj_palette_banks": r16(0x89B4, "snesWorkRam"),
        "render_obj_tile_slots": r16(0x89B6, "snesWorkRam"),
        "render_obj_queue_count": r16(0x89C6, "snesWorkRam"),
        "render_obj_restart_reason": r16(0x89C8, "snesWorkRam"),
        "render_obj_restart_slots": r16(0x89CA, "snesWorkRam"),
        "render_obj_restart_queue": r16(0x89CC, "snesWorkRam"),
        "render_bg_tile_slots": r16(0x00DC, "snesWorkRam"),
        "input_real_cache": f"{r16(0x1F12, 'snesWorkRam'):04x}",
        "input_mailbox": f"{r16(0x410000, 'snesMemory'):04x}",
        "input_injection": f"{r16(0x410002, 'snesMemory'):04x}",
        # The C-Chip input task stores P1 at $F01C4E and coins at $F01C50;
        # $1C50 was mislabeled as P1 in an older ad-hoc probe.
        "game_p1": f"{m.read_memory('snesMemory', 0x401C4E, 1)[0]:02x}",
        "game_coin": f"{m.read_memory('snesMemory', 0x401C50, 1)[0]:02x}",
        "stack": stack_state(m),
    }


def require_healthy(label: str, snap: dict[str, Any]) -> None:
    if snap["halt"] != 0:
        raise RuntimeError(f"{label}: interpreter halted: {snap['halt']:#06x}")
    if snap["gates"] != EXPECTED_GATES:
        raise RuntimeError(f"{label}: production gate mismatch: {snap['gates']}")
    if (
        snap["production_pacing_gate"] != 1
        or snap["pacing_initialized"] != 0xA5
        or snap["pacing_supervisor_ready"] != 0x5A
        or snap["pacing_catchup_debt"] > PACING_CATCHUP_DEBT_MAX
    ):
        raise RuntimeError(f"{label}: production pacing is not armed")
    if snap["input_injection"] != "0000":
        raise RuntimeError(f"{label}: virtual input was not idle")
    if snap["stack"]["below_floor"]:
        raise RuntimeError(f"{label}: task stack crossed its floor")
    # Exact-video-frame stops can land after the SA-1 publishes a frame but
    # before the following NMI acknowledges it.  Do not impose a lag bound at
    # those artificial pause points; monotonic acknowledgement advancement is
    # the liveness contract below, and every observed lag is retained.


def copy_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    source = Path(response["path"])
    shutil.copy2(source, target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def render_hook_evidence(
    notifications: list[dict[str, Any]],
    handles: dict[int, str],
    hook_definitions: dict[str, int],
    target: Path,
) -> dict[str, Any]:
    """Retain raw phase hooks and summarize completed visual draws."""
    events = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = dict(notification.get("params", {}))
        label = handles.get(int(params.get("handle", -1)))
        if label is None:
            continue
        events.append(
            {
                "label": label,
                "address": int(params.get("address", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "frame": int(params.get("frame", 0)),
                "cpu_type": params.get("cpuType"),
                "kind": params.get("kind"),
            }
        )

    target.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    )
    counts = {
        label: sum(event["label"] == label for event in events)
        for label in hook_definitions
    }

    completed = []
    current: dict[str, Any] | None = None
    for event in events:
        label = event["label"]
        if label == "render_start":
            current = {
                "start_cycle": event["cycle_count"],
                "start_frame": event["frame"],
                "phases": {label: event["cycle_count"]},
            }
        elif current is not None:
            current["phases"].setdefault(label, event["cycle_count"])
            if label == "render_complete":
                current["complete_cycle"] = event["cycle_count"]
                current["complete_frame"] = event["frame"]
                current["cycles"] = (
                    current["complete_cycle"] - current["start_cycle"]
                )
                current["video_frame_span"] = (
                    current["complete_frame"] - current["start_frame"]
                )
                completed.append(current)
                current = None

    cycles = [item["cycles"] for item in completed]
    frame_spans = [item["video_frame_span"] for item in completed]
    return {
        "scope": "checkpointed 5A22 execution-hook visual throughput; not FPS",
        "raw_events": str(target),
        "raw_events_sha256": sha256(target),
        "counts": counts,
        "observed_completed_renders": counts.get("render_complete", 0),
        "matched_completed_renders": len(completed),
        "incomplete_render_at_stop": current is not None,
        "completed_render_cycles": cycles,
        "completed_render_video_frame_spans": frame_spans,
        "completed_renders": completed,
    }


def run_variant(
    args: argparse.Namespace,
    name: str,
    active: bool,
    port: int,
) -> dict[str, Any]:
    stderr_path = args.output / f"{name}.stderr.log"
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr_path,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        mirror_intervention = None
        if args.refresh_video_mirror:
            cpu = m.get_cpu_state("Snes")
            cpu_pc = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
            rom_bytes = args.rom.read_bytes()[0x298000 : 0x298000 + 0x3000]
            old_bytes = m.read_memory("snesWorkRam", 0x18000, 0x3000)
            differing = [
                index
                for index, (old, new) in enumerate(zip(old_bytes, rom_bytes))
                if old != new
            ]
            pc_offset = cpu_pc - 0x7F8000
            if any(pc_offset - 4 <= index <= pc_offset + 4 for index in differing):
                raise RuntimeError(
                    "refusing to replace WRAM bytes around the 5A22's current "
                    f"instruction: PC={cpu_pc:#08x}"
                )
            for offset in range(0, len(rom_bytes), 0x1000):
                chunk = rom_bytes[offset : offset + 0x1000]
                m.write_memory("snesWorkRam", 0x18000 + offset, chunk.hex())
            observed = m.read_memory("snesWorkRam", 0x18000, 0x3000)
            if observed != rom_bytes:
                raise RuntimeError("WRAM video mirror refresh did not read back exactly")
            supervisor = rom_bytes[
                SUPERVISOR_SOURCE_OFFSET :
                SUPERVISOR_SOURCE_OFFSET + SUPERVISOR_LENGTH
            ]
            old_supervisor = bytes(
                m.read_memory(
                    "snesWorkRam", SUPERVISOR_TARGET_OFFSET, SUPERVISOR_LENGTH
                )
            )
            if (
                0x7EF000 <= cpu_pc < 0x7EF000 + SUPERVISOR_LENGTH
                and old_supervisor != supervisor
            ):
                raise RuntimeError(
                    "refusing to replace the live WRAM supervisor around "
                    f"PC={cpu_pc:#08x}"
                )
            m.write_memory(
                "snesWorkRam", SUPERVISOR_TARGET_OFFSET, supervisor.hex()
            )
            observed_supervisor = bytes(
                m.read_memory(
                    "snesWorkRam", SUPERVISOR_TARGET_OFFSET, SUPERVISOR_LENGTH
                )
            )
            if observed_supervisor != supervisor:
                raise RuntimeError("WRAM supervisor refresh did not read back exactly")
            old_ready_sequence = int.from_bytes(
                m.read_memory("snesWorkRam", 0x1F1E, 2), "little"
            )
            checkpoint_frame_ack = int.from_bytes(
                m.read_memory("Sa1Memory", 0x3302, 2), "little"
            )
            m.write_memory(
                "snesWorkRam",
                0x1F1E,
                checkpoint_frame_ack.to_bytes(2, "little").hex(),
            )
            if int.from_bytes(
                m.read_memory("snesWorkRam", 0x1F1E, 2), "little"
            ) != checkpoint_frame_ack:
                raise RuntimeError("render-ready checkpoint migration did not verify")
            offset_table = bg_offset_table()
            m.write_memory("snesWorkRam", 0x7500, offset_table.hex())
            observed_offset_table = m.read_memory(
                "snesWorkRam", 0x7500, len(offset_table)
            )
            if observed_offset_table != offset_table:
                raise RuntimeError("BG offset-table checkpoint migration did not verify")
            mirror_intervention = {
                "kind": "checkpoint_lab_wram_video_mirror_refresh",
                "cpu_pc": cpu_pc,
                "length": len(rom_bytes),
                "differing_bytes": len(differing),
                "first_differing_offsets": differing[:64],
                "sha256": hashlib.sha256(observed).hexdigest(),
                "supervisor": {
                    "address": "7E:F000",
                    "length": SUPERVISOR_LENGTH,
                    "differing_bytes": sum(
                        old != new
                        for old, new in zip(old_supervisor, supervisor)
                    ),
                    "sha256": hashlib.sha256(supervisor).hexdigest(),
                },
                "render_ready_sequence": {
                    "address": "7E:1F1E",
                    "checkpoint": old_ready_sequence,
                    "normalized_to_frame_ack": checkpoint_frame_ack,
                },
                "bg_offset_table": {
                    "address": "7E:7500",
                    "length": len(offset_table),
                    "sha256": hashlib.sha256(offset_table).hexdigest(),
                },
            }
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        initial = snapshot(m, "initial")
        require_healthy(f"{name}/initial", initial)
        (args.output / f"{name}-initial-render-wram.bin").write_bytes(
            m.read_memory("snesWorkRam", 0x0000, 0x10000)
        )

        held_buttons = args.active_buttons if active else 0
        m.tool(
            "set_input",
            {"port": 0, "buttons": held_buttons, "hold": True},
        )
        hook_definitions = dict(RENDER_HOOKS) if args.phase_hooks else {}
        if args.obj_hooks:
            hook_definitions.update(OBJ_HOOKS)
        hook_handles = {}
        if hook_definitions:
            hook_handles = {
                m.add_exec_hook(address, cpu_type="Snes"): label
                for label, address in hook_definitions.items()
            }
            m.drain_notifications(timeout=0.05)
        held_video_frames = (
            args.video_frames if args.video_frames is not None else args.cycles * 120
        )
        m.run_frames(held_video_frames)
        render_hooks = None
        if hook_definitions:
            render_hooks = render_hook_evidence(
                m.drain_notifications(timeout=0.25),
                hook_handles,
                hook_definitions,
                args.output / f"{name}-render-hooks.jsonl",
            )

        held = snapshot(m, "held_final")
        require_healthy(f"{name}/held_final", held)
        (args.output / f"{name}-held-render-wram.bin").write_bytes(
            m.read_memory("snesWorkRam", 0x0000, 0x10000)
        )
        held_state = None
        if args.save_held_states:
            held_state_path = args.output / f"{name}-held.mss"
            held_state_response = m.save_state(held_state_path.resolve())
            deadline = time.monotonic() + 5.0
            while (
                (not held_state_path.is_file() or held_state_path.stat().st_size == 0)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not held_state_path.is_file() or held_state_path.stat().st_size == 0:
                raise RuntimeError(f"Nexen did not flush held state: {held_state_path}")
            held_state = {
                "path": str(held_state_path),
                "sha256": sha256(held_state_path),
                "response": held_state_response,
            }
        screenshot = copy_screenshot(m, args.output / f"{name}.png")
        work_ram = m.read_memory("snesMemory", 0x400000, 0x10000)
        (args.output / f"{name}-workram.bin").write_bytes(work_ram)

        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        m.run_frames(8)
        released = snapshot(m, "released")
        require_healthy(f"{name}/released", released)
        return {
            "active": active,
            "port": port,
            "mirror_intervention": mirror_intervention,
            "buttons": {
                "held": held_buttons,
                "transport": "nexen_port0_manual_4016",
            },
            "initial": initial,
            "held_final": held,
            "released": released,
            "held_state": held_state,
            "render_hooks": render_hooks,
            "screenshot": screenshot,
            "work_ram": {
                "path": str(args.output / f"{name}-workram.bin"),
                "sha256": hashlib.sha256(work_ram).hexdigest(),
            },
        }


def main() -> int:
    args = parse_args()
    if not 0 <= args.active_buttons <= 0x0FFF:
        raise SystemExit("--active-buttons must be a 12-bit Nexen controller mask")
    if not 0 <= args.expected_game_input <= 0xFFFF:
        raise SystemExit("--expected-game-input must be a 16-bit value")
    if not 0 <= args.expected_game_p1 <= 0xFF:
        raise SystemExit("--expected-game-p1 must be an 8-bit value")
    held_video_frames = (
        args.video_frames if args.video_frames is not None else args.cycles * 120
    )
    if held_video_frames <= 0:
        raise SystemExit("held video-frame count must be positive")
    if args.phase_hooks and held_video_frames > 120:
        raise SystemExit("--phase-hooks is limited to 120 held video frames")
    if args.obj_hooks and not args.phase_hooks:
        raise SystemExit("--obj-hooks requires --phase-hooks")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    idle = run_variant(args, "idle", False, args.port)
    active = run_variant(args, "right-attack", True, args.port + 1)
    idle_ram = (args.output / "idle-workram.bin").read_bytes()
    active_ram = (args.output / "right-attack-workram.bin").read_bytes()
    differing_offsets = [
        index for index, (left, right) in enumerate(zip(idle_ram, active_ram))
        if left != right
    ]

    verdict = {
        "real_input_seen": (
            active["held_final"]["input_real_cache"]
            == f"{args.expected_game_input:04x}"
            and active["held_final"]["input_mailbox"]
            == f"{args.expected_game_input:04x}"
            and active["held_final"]["game_p1"]
            == f"{args.expected_game_p1:02x}"
        ),
        "virtual_injection_idle": (
            active["held_final"]["input_injection"] == "0000"
        ),
        "game_state_diverged_from_idle": bool(differing_offsets),
        "screenshot_diverged_from_idle": (
            idle["screenshot"]["sha256"] != active["screenshot"]["sha256"]
        ),
        "both_healthy_after_release": all(
            variant["released"]["halt"] == 0
            and not variant["released"]["stack"]["below_floor"]
            for variant in (idle, active)
        ),
        "renderer_ack_advances": all(
            variant["held_final"]["frame_ack"] != variant["initial"]["frame_ack"]
            for variant in (idle, active)
        ),
        "renderer_completion_advances": all(
            variant["held_final"]["render_complete_count"]
            != variant["initial"]["render_complete_count"]
            for variant in (idle, active)
        ),
    }
    result = {
        "scope": (
            "injected same-checkpoint renderer/input differential; not FPS"
            if args.refresh_video_mirror
            else "production-checkpoint real-controller interaction differential; not FPS"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "checkpoint": str(args.state.resolve()),
        "checkpoint_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "video_frames_held": held_video_frames,
        "active_buttons": args.active_buttons,
        "expected_game_input": f"{args.expected_game_input:04x}",
        "expected_game_p1": f"{args.expected_game_p1:02x}",
        "idle": idle,
        "active": active,
        "differential": {
            "work_ram_differing_bytes": len(differing_offsets),
            "work_ram_first_differing_offsets": differing_offsets[:256],
            "idle_tick_delta": (
                idle["held_final"]["tick"] - idle["initial"]["tick"]
            )
            & 0xFFFF,
            "active_tick_delta": (
                active["held_final"]["tick"] - active["initial"]["tick"]
            )
            & 0xFFFF,
            "idle_completed_render_delta": (
                idle["held_final"]["render_complete_count"]
                - idle["initial"]["render_complete_count"]
            )
            & 0xFFFF,
            "active_completed_render_delta": (
                active["held_final"]["render_complete_count"]
                - active["initial"]["render_complete_count"]
            )
            & 0xFFFF,
            "idle_palette_change_delta": (
                idle["held_final"]["render_palette_change_count"]
                - idle["initial"]["render_palette_change_count"]
            )
            & 0xFFFF,
            "active_palette_change_delta": (
                active["held_final"]["render_palette_change_count"]
                - active["initial"]["render_palette_change_count"]
            )
            & 0xFFFF,
            "idle_bg_change_delta": (
                idle["held_final"]["render_bg_change_count"]
                - idle["initial"]["render_bg_change_count"]
            )
            & 0xFFFF,
            "active_bg_change_delta": (
                active["held_final"]["render_bg_change_count"]
                - active["initial"]["render_bg_change_count"]
            )
            & 0xFFFF,
            "idle_obj_change_delta": (
                idle["held_final"]["render_obj_change_count"]
                - idle["initial"]["render_obj_change_count"]
            )
            & 0xFFFF,
            "active_obj_change_delta": (
                active["held_final"]["render_obj_change_count"]
                - active["initial"]["render_obj_change_count"]
            )
            & 0xFFFF,
        },
        "verdict": verdict,
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"results": str(result_path), **verdict}, sort_keys=True))
    return 0 if all(verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
