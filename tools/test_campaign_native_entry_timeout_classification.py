#!/usr/bin/env python3
"""Guard runtime-halt precedence over native-entry exact-stop timeouts."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tools" / "replay_mame_controller_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAMPAIGN}")
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


class HaltedEntrySession:
    """Paused machine that reaches `ispin` before the requested entry."""

    def __init__(self, *, halt: int, pc: int) -> None:
        self.halt = halt
        self.pc = pc
        self.frame = 700
        self.cycles = 123_456
        self.iram = bytearray(0x800)
        self.iram[0x40:0x44] = (0x123456).to_bytes(4, "little")
        self.iram[0x44:0x46] = (0x4AFC).to_bytes(2, "little")
        self.iram[0x4A:0x4E] = (0x08000000).to_bytes(4, "little")
        self.iram[0x4E:0x50] = halt.to_bytes(2, "little")
        self.iram[0xAA:0xAC] = (1).to_bytes(2, "little")
        self.iram[0xAC:0xAE] = (0x2222).to_bytes(2, "little")
        self.iram[campaign.TICK_IRAM : campaign.TICK_IRAM + 2] = (
            225
        ).to_bytes(2, "little")
        self.timer = bytearray(0x1A)
        for offset, value in (
            (0x00, 0xC71E),
            (0x02, 1),
            (0x06, 0x3344),
            (0x08, 1),
            (0x18, 1),
        ):
            self.timer[offset : offset + 2] = value.to_bytes(2, "little")

    def get_state(self) -> dict:
        return {"frameCount": self.frame, "isPaused": True}

    def get_cpu_state(self, cpu_type: str) -> dict:
        if cpu_type == "Snes":
            return {
                "k": 0,
                "pc": 0x942C,
                "sp": 0x01FB,
                "ps": 0x04,
                "emulationMode": False,
                "stopState": "Stopped",
                "stopStateValue": 1,
                "cycleCount": 654_321,
            }
        if cpu_type != "Sa1":
            raise AssertionError(f"unexpected CPU: {cpu_type}")
        return {
            "k": (self.pc >> 16) & 0xFF,
            "pc": self.pc & 0xFFFF,
            "cycleCount": self.cycles,
        }

    def read_memory(self, memory_type: str, address: int, size: int) -> bytes:
        if memory_type == "Sa1Memory" and 0 <= address <= len(self.iram) - size:
            return bytes(self.iram[address : address + size])
        if (memory_type, address, size) == ("snesMemory", 0x404000, 0x1A):
            return bytes(self.timer)
        if (memory_type, address, size) == ("snesMemory", 0x400002, 4):
            return bytes.fromhex("A55A000F")
        if (memory_type, address, size) == ("snesMemory", 0x410120, 0x32):
            shared = bytearray(size)
            shared[0x02:0x04] = (1).to_bytes(2, "little")
            shared[0x0A:0x0D] = bytes((4, 2, 0xA5))
            shared[0x0D] = 0x5A
            shared[0x10] = 10
            return bytes(shared)
        if (memory_type, address, size) == ("snesMemory", 0x003300, 4):
            return bytes.fromhex("06010401")
        if (memory_type, address, size) == ("snesMemory", 0x002200, 0x10):
            return bytes(size)
        if (memory_type, address, size) == ("snesWorkRam", 0x1F00, 0x20):
            return bytes(size)
        if (memory_type, address, size) == ("snesWorkRam", 0x0100, 0x100):
            stack = bytearray(size)
            stack[0xFC:0x100] = bytes.fromhex("4C661000")
            return bytes(stack)
        if (memory_type, address, size) == ("snesMemory", 0x001065, 1):
            return bytes.fromhex("E3")
        raise AssertionError(f"unexpected read: {(memory_type, address, size)!r}")

    def tool(self, name: str, args: dict) -> dict:
        if name != "run_to_exact_exec_stop":
            raise AssertionError(f"unexpected tool: {name}")
        self.frame += int(args["maxFrames"])
        self.cycles += 9_000_000
        return {
            "reason": "maxFrames",
            "hit": False,
            "isPaused": True,
            "exactStopRemoved": True,
            "exactStopHandle": 1,
            "exactStopTriggered": False,
            "exactStopBreakDelivered": False,
            "requestedOccurrences": int(args["occurrences"]),
            "observedOccurrences": 0,
            "k": (self.pc >> 16) & 0xFF,
            "pc": self.pc & 0xFFFF,
            "cycleCount": self.cycles,
            "triggerCycleCount": 0,
            "cyclesAdvanced": 9_000_000,
            "triggerFrame": -1,
            "endFrame": self.frame,
        }


def require_runtime_halt(session: HaltedEntrySession) -> dict:
    try:
        campaign.run_game_update_entries(
            session,
            1,
            max_entries_per_chunk=1,
            video_frame_budget_per_entry=1,
            minimum_frame_budget=1,
        )
    except campaign.CampaignFailure as failure:
        if failure.classification != "interpreter_or_native_hle":
            raise AssertionError(
                f"runtime halt misclassified as {failure.classification!r}"
            )
        if (
            failure.detail.get("reason")
            != "interpreter_halt_during_game_update_entry_wait"
        ):
            raise AssertionError(f"wrong failure detail: {failure.detail!r}")
        return failure.detail
    raise AssertionError("halted exact-entry wait was accepted")


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        unavailable = campaign.capture_unclassified_failure_boundary(
            None,
            temporary_path / "states",
            temporary_path / "shots",
        )
    if unavailable != {
        "capture_error": "MCP session unavailable before context entry completed"
    }:
        raise AssertionError(
            f"pre-session timeout capture was not stable: {unavailable!r}"
        )

    by_marker = require_runtime_halt(
        HaltedEntrySession(halt=0xDEAD, pc=0x001234)
    )
    if by_marker.get("halt") != 0xDEAD:
        raise AssertionError("halt marker was not retained")
    terminal = by_marker.get("terminal_snapshot", {})
    if (
        terminal.get("m68k_pc") != 0x123456
        or terminal.get("m68k_opcode") != 0x4AFC
        or terminal.get("interpreted_step_count") != 0x08000000
        or terminal.get("tick_0760") != 225
        or terminal.get("task_mask_f00002") != 0xA55A
        or terminal.get("current_task_f00004") != 15
        or terminal.get("vtime", {}).get("magic") != 0xC71E
        or terminal.get("snes_cpu", {}).get("stopState") != "Stopped"
        or terminal.get("snes_interrupt_frame", {}).get("return_address")
        != 0x001066
        or terminal.get("shared_pacing", {}).get("arm_410122") != 1
        or terminal.get("request_ack", {}).get("frame_request_3300") != 262
    ):
        raise AssertionError(f"terminal live snapshot was not retained: {terminal!r}")

    by_spin = require_runtime_halt(
        HaltedEntrySession(halt=0, pc=campaign.INTERPRETER_HALT_SPIN)
    )
    if by_spin.get("terminal_sa1_pc") != f"{campaign.INTERPRETER_HALT_SPIN:06X}":
        raise AssertionError("halt-spin PC was not retained")

    print("campaign native-entry timeout classification regression: green")


if __name__ == "__main__":
    main()
