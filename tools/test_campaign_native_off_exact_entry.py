#!/usr/bin/env python3
"""Regression for native-off campaign exact-edge and transport semantics."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tools" / "replay_mame_controller_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAMPAIGN}")
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


class PartialFrameSession:
    """Paused MCP reply sequence: timeout after 116, then exact remainder."""

    def __init__(self) -> None:
        self.frame = 0
        self.advances = [116, 4]

    def tool(self, name: str, args: dict) -> dict:
        if name != "set_input":
            raise AssertionError(f"unexpected tool: {name}")
        return {"isPaused": True}

    def get_state(self) -> dict:
        return {"frameCount": self.frame, "isPaused": True}

    def run_frames(self, requested: int) -> dict:
        advanced = self.advances.pop(0)
        if advanced > requested:
            raise AssertionError("fake response overshot request")
        start = self.frame
        self.frame += advanced
        return {
            "startFrame": start,
            "endFrame": self.frame,
            "framesAdvanced": advanced,
            "requested": requested,
            "isPaused": True,
            "timedOut": advanced != requested,
        }


class ZeroProgressSession(PartialFrameSession):
    def __init__(self) -> None:
        super().__init__()
        self.advances = [0]


class GateSession:
    def __init__(self, *, xlat: int, choke: int, virtual_pc: int, sa1_pc: int):
        self.xlat = xlat
        self.choke = choke
        self.virtual_pc = virtual_pc
        self.sa1_pc = sa1_pc

    def read_memory(self, memory_type: str, address: int, size: int) -> bytes:
        if (memory_type, address, size) == ("Sa1Memory", 0x071A, 2):
            return self.xlat.to_bytes(2, "little")
        if (memory_type, address, size) == ("Sa1Memory", 0x073A, 2):
            return self.choke.to_bytes(2, "little")
        if (memory_type, address, size) == (
            "Sa1Memory",
            campaign.M68K_PC_IRAM,
            4,
        ):
            return self.virtual_pc.to_bytes(4, "little")
        raise AssertionError(f"unexpected read: {(memory_type, address, size)!r}")

    def get_cpu_state(self, cpu_type: str) -> dict:
        if cpu_type != "Sa1":
            raise AssertionError(f"unexpected CPU: {cpu_type}")
        return {
            "k": (self.sa1_pc >> 16) & 0xFF,
            "pc": self.sa1_pc & 0xFFFF,
        }


class HookSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def add_exec_hook(self, *args: object, **kwargs: object) -> int:
        self.calls.append(("exec", args, kwargs))
        return 41

    def add_write_hook(self, *args: object, **kwargs: object) -> int:
        self.calls.append(("write", args, kwargs))
        return 42


class InterpretedBatchFailureSession:
    """One complete batch followed by a five-of-eight exact-stop timeout."""

    def __init__(self) -> None:
        self.frame = 100
        self.cycles = 1_000_000
        self.virtual_pc = campaign.M68K_GAME_UPDATE_ENTRY
        self.calls = 0

    def get_state(self) -> dict:
        return {"frameCount": self.frame, "isPaused": True}

    def get_cpu_state(self, cpu_type: str) -> dict:
        if cpu_type != "Sa1":
            raise AssertionError(f"unexpected CPU: {cpu_type}")
        return {
            "k": 0xF2,
            "pc": 0x8408 if self.calls == 2 else 0x8F56,
            "cycleCount": self.cycles,
        }

    def read_memory(self, memory_type: str, address: int, size: int) -> bytes:
        if (memory_type, address, size) == (
            "Sa1Memory",
            campaign.M68K_PC_IRAM,
            4,
        ):
            return self.virtual_pc.to_bytes(4, "little")
        if (memory_type, address, size) == ("Sa1Memory", 0x0010, 2):
            return b"\0\0"
        raise AssertionError(f"unexpected read: {(memory_type, address, size)!r}")

    def tool(self, name: str, args: dict) -> dict:
        if name != "run_to_exact_iram_exec_edge":
            raise AssertionError(f"unexpected tool: {name}")
        self.calls += 1
        requested = int(args["occurrences"])
        self.frame += 80 if self.calls == 1 else int(args["maxFrames"])
        self.cycles += 8_000_000 if self.calls == 1 else 90_000_000
        success = self.calls == 1
        observed = requested if success else 5
        self.virtual_pc = (
            campaign.M68K_GAME_UPDATE_ENTRY if success else 0x02582E
        )
        return {
            "reason": "breakpoint" if success else "maxFrames",
            "hit": success,
            "isPaused": True,
            "exactStopRemoved": True,
            "exactStopTriggered": success,
            "exactStopBreakDelivered": success,
            "exactStopHandle": 1,
            "requestedOccurrences": requested,
            "observedOccurrences": observed,
            "iramAddress": campaign.M68K_PC_IRAM,
            "observedValue": self.virtual_pc,
            "predicateMatched": success,
            "edgeRequired": True,
            "cleanupPauseApplied": False,
            "cycleCount": self.cycles,
            "triggerCycleCount": self.cycles if success else 0,
            "endFrame": self.frame,
            "triggerFrame": self.frame if success else 0,
        }


def main() -> None:
    if campaign.interpreted_entry_batch_counts(0) != []:
        raise AssertionError("zero interpreted entries should issue no stop")
    if campaign.interpreted_entry_batch_counts(8) != [8]:
        raise AssertionError("native-off batch boundary changed")
    if campaign.interpreted_entry_batch_counts(17) != [8, 8, 1]:
        raise AssertionError("large native-off request lost exact-edge chunks")

    failure_session = InterpretedBatchFailureSession()
    original_terminal_snapshot = campaign.game_update_wait_terminal_snapshot
    original_halt16 = campaign.halt16
    try:
        campaign.game_update_wait_terminal_snapshot = lambda _m, cpu: {
            "halt": 0,
            "sa1_pc": ((int(cpu["k"]) & 0xFF) << 16)
            | (int(cpu["pc"]) & 0xFFFF),
        }
        campaign.halt16 = lambda _m: 0
        campaign.run_interpreted_game_update_entries(failure_session, 17)
    except campaign.CampaignFailure as error:
        detail = error.detail
        expected_progress = {
            "completed_entries_before_failure": 8,
            "completed_batches_before_failure": 1,
            "failed_batch_index": 1,
            "failed_batch_requested_entries": 8,
            "failed_batch_observed_entries": 5,
            "observed_entries_before_failure": 13,
        }
        actual_progress = {
            key: detail.get(key) for key in expected_progress
        }
        if actual_progress != expected_progress:
            raise AssertionError(
                f"failed-batch progress lost: {actual_progress!r}"
            )
        completed = detail.get("completed_batch_summaries")
        failed = detail.get("failed_batch_summary")
        if not isinstance(completed, list) or len(completed) != 1:
            raise AssertionError("completed batch summary was not retained")
        if not isinstance(failed, dict) or failed.get("batch_index") != 1:
            raise AssertionError("failed batch summary was not retained")
        if failed.get("observed_entries") != 5:
            raise AssertionError("failed batch partial count was not retained")
    else:
        raise AssertionError("failed interpreted batch was accepted")
    finally:
        campaign.game_update_wait_terminal_snapshot = original_terminal_snapshot
        campaign.halt16 = original_halt16

    session = PartialFrameSession()
    runs = campaign.run_exact_frames(session, buttons=0, frames=120)
    if session.frame != 120 or len(runs) != 2:
        raise AssertionError("partial paused frame advance was not resumed")
    if not runs[0]["partial_timeout_resumed"]:
        raise AssertionError("partial wall-clock timeout was not labelled")
    if runs[1]["partial_timeout_resumed"]:
        raise AssertionError("completed frame request was mislabelled")

    try:
        campaign.run_exact_frames(ZeroProgressSession(), buttons=0, frames=1)
    except campaign.CampaignFailure as error:
        if error.detail.get("reason") != "video_frame_advance_failed":
            raise
    else:
        raise AssertionError("zero-progress timeout was accepted")

    native = GateSession(
        xlat=1,
        choke=1,
        virtual_pc=0,
        sa1_pc=campaign.ENTRY_3A92_NATIVE,
    )
    interpreted = GateSession(
        xlat=0,
        choke=0,
        virtual_pc=campaign.M68K_GAME_UPDATE_ENTRY,
        sa1_pc=0xF282E9,
    )
    if campaign.active_game_update_gate(native)["mode"] != "native":
        raise AssertionError("armed translation gate lost native boundary")
    if campaign.active_game_update_gate(interpreted)["mode"] != "interpreted":
        raise AssertionError("cleared translation gate did not select IRAM edge")
    if not campaign.at_active_game_update_entry(native, "native"):
        raise AssertionError("native exact entry was not recognized")
    if not campaign.at_active_game_update_entry(interpreted, "interpreted"):
        raise AssertionError("interpreted exact edge was not recognized")

    native_hook_session = HookSession()
    native_hook = campaign.install_game_update_reentry_hook(
        native_hook_session, "native"
    )
    if native_hook_session.calls != [
        (
            "exec",
            (campaign.ENTRY_3A92_NATIVE,),
            {"cpu_type": "Sa1"},
        )
    ] or native_hook["kind"] != "sa1_exec_native_3a92":
        raise AssertionError("native safe-checkpoint reentry hook changed")

    interpreted_hook_session = HookSession()
    interpreted_hook = campaign.install_game_update_reentry_hook(
        interpreted_hook_session, "interpreted"
    )
    expected_interpreted_call = [
        (
            "write",
            (campaign.M68K_PC_IRAM,),
            {
                "cpu_type": "Sa1",
                "match_value": campaign.M68K_GAME_UPDATE_ENTRY & 0xFF,
                "match_value_mask": 0xFF,
            },
        )
    ]
    if (
        interpreted_hook_session.calls != expected_interpreted_call
        or interpreted_hook["kind"] != "sa1_write_iram_pc_low_92"
    ):
        raise AssertionError("interpreted safe-checkpoint hook is not exact")

    original_native = campaign.run_game_update_entries
    original_interpreted = campaign.run_interpreted_game_update_entries
    try:
        campaign.run_game_update_entries = lambda _m, count: [
            {"route": "native", "requested_entries": count}
        ]
        campaign.run_interpreted_game_update_entries = lambda _m, count: [
            {"route": "interpreted", "requested_entries": count}
        ]
        native_span = campaign.run_active_game_update_entries(native, 1)[0]
        interpreted_span = campaign.run_active_game_update_entries(
            interpreted, 1
        )[0]
    finally:
        campaign.run_game_update_entries = original_native
        campaign.run_interpreted_game_update_entries = original_interpreted
    if native_span["route"] != "native":
        raise AssertionError("active native route selected the wrong stopper")
    if interpreted_span["route"] != "interpreted":
        raise AssertionError("ROM-disabled route still selected native address")

    native_iram = bytearray(0x800)
    interpreted_iram = bytearray(0x800)
    interpreted_iram[campaign.M68K_PC_IRAM : campaign.M68K_PC_IRAM + 4] = (
        campaign.M68K_GAME_UPDATE_ENTRY.to_bytes(4, "little")
    )
    interpreted_iram[0x071A:0x071C] = (0).to_bytes(2, "little")
    if (
        campaign.nested_game_update_entry_route(
            campaign.ENTRY_3A92_NATIVE, bytes(native_iram)
        )
        != "native_sa1"
    ):
        raise AssertionError("native nested entry lost forensic classification")
    if (
        campaign.nested_game_update_entry_route(
            0xF282E9, bytes(interpreted_iram)
        )
        != "interpreted_iram"
    ):
        raise AssertionError("IRAM exact edge was mislabelled resumable")
    interpreted_iram[campaign.M68K_PC_IRAM] ^= 1
    if campaign.nested_game_update_entry_route(
        0xF282E9, bytes(interpreted_iram)
    ) is not None:
        raise AssertionError("ordinary interpreted pause was marked exact-entry")

    source = CAMPAIGN.read_text(encoding="utf-8")
    required = (
        '"run_to_exact_iram_exec_edge"',
        "M68K_PC_IRAM",
        "M68K_GAME_UPDATE_ENTRY",
        "interpreted_pc_003a92_rising_edge_pre_body",
        "run_active_game_update_entries",
        "install_game_update_reentry_hook",
        "zero_additional_game_update_entries",
        "post_entry_safe_proof",
        "iram_exact_entry_nested_forensic",
        'if args.gameplay_native == "off"',
        "--allow-incomplete-coverage",
        '"partial-green"',
        '"partial-with-oracle-divergences"',
    )
    missing = [needle for needle in required if needle not in source]
    if missing:
        raise AssertionError(f"native-off campaign safeguards removed: {missing}")
    print("campaign native-off exact-entry regression: green")


if __name__ == "__main__":
    main()
