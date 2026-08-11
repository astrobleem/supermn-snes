#!/usr/bin/env python3
"""Capture production SNES work state at exact retained-movie ticks.

By default, the starting state must be an authenticated post-entry safe
controller-campaign checkpoint with a declared MAME tick and lineage event
log.  Exact nested SA-1 entry states are debugger-forensic artifacts: Nexen
can serialize them, but they are not resumable campaign checkpoints.  They
are rejected unless the caller explicitly selects the forensic override.

Controller transitions are installed at the same tick boundary used by
replay_mame_controller_campaign.py.  This is a checkpointed bisection aid,
not fresh-boot proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    EVIDENCE
    / "fresh-controller-campaign-5382968-nexen-v1"
    / "states"
    / "gameplay-origin.mss"
)
DEFAULT_TIMELINE = EVIDENCE / "full-playback-timeline-v1" / "timeline.jsonl"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen"
)
GAMEPLAY_NATIVE_GATES = (0x071A, 0x073A)
ALL_NATIVE_GATES = (
    0x072E,  # loop fast path
    0x071A,  # translated/native instruction escapes
    0x0734,  # production paced-wait/render HLE
    0x0736,  # native scheduler selector
    0x073A,  # fetch chokepoint
    0x073C,  # native scheduler switch-in
)
M68K_PC_IRAM = 0x0040
M68K_GAME_UPDATE_ENTRY = 0x00003A92
INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY = 256
# The IRAM-edge debugger keeps per-occurrence state until its reply.  Fully
# interpreted Stage 3 entries can take long enough that a large batch exceeds
# the MCP transport timeout even though every individual entry is healthy.
# Keep this deliberately small; each batch still stops on the same rising
# virtual-PC edge, before the $003A92 body executes.
INTERPRETED_ENTRY_EDGE_MAX_BATCH = 8
# The live virtual-IRQ reload is the bank-$97 campaign helper.  The bank-$00
# reset literal is not the gameplay seam.  Keep this exact so diagnostic ROM
# patches reject any candidate with a different implementation.
IRQ_RELOAD_IMMEDIATE_ROM_OFFSET = 0x2BE5C3
IRQ_RELOAD_IMMEDIATE_EXPECTED = bytes.fromhex("0070")

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_ticks(value: str) -> list[int]:
    ticks = sorted({int(item, 0) for item in value.split(",") if item.strip()})
    if not ticks or any(tick < 0 or tick > 0xFFFF for tick in ticks):
        raise argparse.ArgumentTypeError("ticks must be comma-separated 0..65535")
    return ticks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--state-mame-tick",
        type=int,
        default=222,
        help=(
            "last MAME tick completed by --state; a safe checkpoint resumes "
            "at this value plus one"
        ),
    )
    parser.add_argument(
        "--state-lineage-events",
        type=Path,
        help=(
            "fresh-campaign events.jsonl authenticating --state as a "
            "post-entry safe checkpoint of this exact ROM"
        ),
    )
    parser.add_argument(
        "--allow-forensic-nonresumable-state",
        action="store_true",
        help=(
            "diagnostic only: allow an unverified or explicitly nested "
            "exact-entry state; output remains classified nonresumable and "
            "cannot support a production-ROM behavior claim"
        ),
    )
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--ticks", type=parse_ticks, required=True)
    parser.add_argument(
        "--save-ticks",
        type=parse_ticks,
        default=[],
        help="captured tick labels that should also retain an exact .mss state",
    )
    parser.add_argument(
        "--safe-save-ticks",
        type=parse_ticks,
        default=[],
        help=(
            "captured tick labels that should retain an authenticated "
            "post-entry resumable checkpoint; unlike --save-ticks, this "
            "completes the interrupted SA-1 opcode and rendezvouses at the "
            "next safe main-SNES boundary"
        ),
    )
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9245)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--gameplay-native",
        choices=(
            "preserve",
            "on",
            "off",
            "xlat-off",
            "choke-off",
            "all-off",
        ),
        default="preserve",
        help=(
            "optionally force both gameplay gates, or disable just xlat/choke, "
            "after loading the state; all-off disables the loop, selector, "
            "and switch-in gates as well"
        ),
    )
    parser.add_argument(
        "--refresh-video-wram",
        action="store_true",
        help=(
            "after state load, repeat the cold-boot rc_copy of current-ROM "
            "$E9:8000-$AFFF into executable WRAM $7F:8000-$AFFF; this is an "
            "explicit stale-checkpoint code migration, not fresh-boot proof"
        ),
    )
    parser.add_argument(
        "--input-apply-offset",
        type=int,
        choices=(-1, 0, 1),
        default=0,
        help=(
            "apply a movie transition at T (default); -1 exists only to "
            "reproduce superseded pre-alignment checkpoints, while +1 is a "
            "focused input-mailbox ordering diagnostic"
        ),
    )
    parser.add_argument(
        "--irq-reload",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: temporarily replace the gameplay virtual-IRQ "
            "reload immediate; the ROM bytes are restored and the intervention "
            "is recorded"
        ),
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("timeline", args.timeline),
        ("emulator", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.state_lineage_events is not None:
        if not args.state_lineage_events.is_file():
            parser.error(
                "missing state lineage event log: "
                f"{args.state_lineage_events}"
            )
    elif not args.allow_forensic_nonresumable_state:
        parser.error(
            "--state-lineage-events is required unless "
            "--allow-forensic-nonresumable-state is explicitly selected"
        )
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.state_mame_tick > args.ticks[0]:
        parser.error("first capture tick precedes state tick")
    unknown_save_ticks = sorted(set(args.save_ticks) - set(args.ticks))
    if unknown_save_ticks:
        parser.error(
            "--save-ticks must be a subset of --ticks; unknown: "
            + ",".join(str(tick) for tick in unknown_save_ticks)
        )
    unknown_safe_save_ticks = sorted(
        set(args.safe_save_ticks) - set(args.ticks)
    )
    if unknown_safe_save_ticks:
        parser.error(
            "--safe-save-ticks must be a subset of --ticks; unknown: "
            + ",".join(str(tick) for tick in unknown_safe_save_ticks)
        )
    if args.safe_save_ticks:
        overlap = sorted(set(args.save_ticks) & set(args.safe_save_ticks))
        if overlap:
            parser.error(
                "--save-ticks and --safe-save-ticks cannot overlap: "
                + ",".join(str(tick) for tick in overlap)
            )
        if args.allow_forensic_nonresumable_state:
            parser.error(
                "--safe-save-ticks cannot descend from a forensic state"
            )
        if args.gameplay_native != "preserve":
            parser.error(
                "--safe-save-ticks requires --gameplay-native preserve"
            )
        if args.refresh_video_wram or args.irq_reload is not None:
            parser.error(
                "--safe-save-ticks forbids code migration and ROM patches"
            )
        if args.input_apply_offset != 0:
            parser.error(
                "--safe-save-ticks requires --input-apply-offset 0"
            )
    if args.irq_reload is not None and not 1 <= args.irq_reload <= 0xFFFF:
        parser.error("--irq-reload must be in 1..0xffff")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_matching_state_metadata(
    value: Any,
    state_sha256: str,
) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if value.get("sha256") == state_sha256:
            return dict(value)
        for child in value.values():
            match = _find_matching_state_metadata(child, state_sha256)
            if match is not None:
                return match
    elif isinstance(value, list):
        for child in value:
            match = _find_matching_state_metadata(child, state_sha256)
            if match is not None:
                return match
    return None


def state_metadata_from_log(
    event_path: Path,
    state_sha256: str,
) -> dict[str, Any] | None:
    with event_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            match = _find_matching_state_metadata(
                json.loads(line),
                state_sha256,
            )
            if match is not None:
                return match
    return None


def authenticate_start_state(
    *,
    state: Path,
    state_mame_tick: int,
    rom: Path,
    timeline: Path,
    nexen: Path,
    lineage_events: Path | None,
    allow_forensic_nonresumable_state: bool,
) -> dict[str, Any]:
    """Classify a replay start state before launching an emulator."""

    state_hash = sha256(state)
    if lineage_events is None:
        if not allow_forensic_nonresumable_state:
            raise RuntimeError(
                "state has no authenticated safe-checkpoint lineage"
            )
        return {
            "classification": "unverified_forensic_override",
            "resumable_checkpoint": False,
            "production_behavior_evidence": False,
            "state_sha256": state_hash,
            "lineage_events": None,
            "explicit_override": True,
        }

    events = lineage_events.resolve()
    declared = state_metadata_from_log(events, state_hash)
    selected_emulator_identity = campaign.nexen_identity(nexen)
    try:
        lineage = campaign.validate_resume_lineage(
            events,
            state.resolve(),
            state_mame_tick + 1,
            sha256(rom),
            {
                "emulator_sha256": sha256(nexen),
                "mame_timeline_sha256": sha256(timeline),
            },
        )
        resume_context = lineage["resume_context"]
        if (
            int(resume_context.get("mame_tick_completed", -1))
            != state_mame_tick
            or int(resume_context.get("resume_mame_tick", -1))
            != state_mame_tick + 1
        ):
            raise RuntimeError(
                "safe-checkpoint completed/resume tick contract mismatch"
            )
        retained_emulator_identity = lineage.get(
            "fresh_boot_emulator_identity"
        )
        if not isinstance(retained_emulator_identity, dict):
            raise RuntimeError(
                "safe-checkpoint lineage lacks emulator core identity"
            )
        core_identity_keys = (
            "apphost_sha256",
            "embedded_native_core_sha256",
            "source_dependencies_zip_sha256",
        )
        core_identity_checks = {
            key: (
                selected_emulator_identity.get(key)
                == retained_emulator_identity.get(key)
            )
            for key in core_identity_keys
        }
        if not all(core_identity_checks.values()):
            raise RuntimeError(
                "selected Nexen does not match the checkpoint's emulation "
                f"core identity: {core_identity_checks}"
            )
    except Exception as error:
        if not allow_forensic_nonresumable_state:
            detail = ""
            if declared is not None:
                detail = (
                    "; declared boundary_kind="
                    f"{declared.get('boundary_kind')!r}, "
                    "nested_sa1_entry_nonresumable="
                    f"{declared.get('nested_sa1_entry_nonresumable')!r}, "
                    "resumable_checkpoint="
                    f"{declared.get('resumable_checkpoint')!r}"
                )
            raise RuntimeError(
                "state is not an authenticated post-entry safe checkpoint"
                f"{detail}: {error}"
            ) from error
        return {
            "classification": (
                "explicit_nested_entry_forensic_override"
                if declared is not None
                and declared.get("nested_sa1_entry_nonresumable") is True
                else "unverified_forensic_override"
            ),
            "resumable_checkpoint": False,
            "production_behavior_evidence": False,
            "state_sha256": state_hash,
            "lineage_events": str(events),
            "lineage_events_sha256": sha256(events),
            "declared_state_metadata": declared,
            "selected_emulator_identity": selected_emulator_identity,
            "lineage_validation_error": repr(error),
            "explicit_override": True,
        }

    managed_surface_equal = (
        selected_emulator_identity.get("managed_assembly_sha256")
        == retained_emulator_identity.get("managed_assembly_sha256")
        and selected_emulator_identity.get("deps_manifest_sha256")
        == retained_emulator_identity.get("deps_manifest_sha256")
    )
    return {
        "classification": "authenticated_post_entry_safe_checkpoint",
        "resumable_checkpoint": True,
        "production_behavior_evidence": True,
        "state_sha256": state_hash,
        "lineage_events": str(events),
        "lineage_events_sha256": sha256(events),
        "lineage": lineage,
        "selected_emulator_identity": selected_emulator_identity,
        "retained_emulator_identity": retained_emulator_identity,
        "emulator_core_identity_checks": core_identity_checks,
        "managed_mcp_surface_equal": managed_surface_equal,
        "managed_mcp_surface_classification": (
            "exact_retained_surface"
            if managed_surface_equal
            else "compatible_surface_extension_same_emulation_core"
        ),
        "explicit_override": False,
    }


def validate_loaded_start_state(
    m: campaign.AuditedMcpSession,
    state_resumability: dict[str, Any],
) -> dict[str, Any]:
    """Prove the fresh process restored the authenticated safe machine."""

    if not state_resumability.get("resumable_checkpoint"):
        return {
            "authenticated": False,
            "reason": "forensic_nonresumable_override",
        }
    lineage = state_resumability["lineage"]
    checkpoint = lineage["checkpoint"]
    mutations = list(m.architectural_mutations)
    if mutations:
        raise RuntimeError(
            "architectural mutation occurred before safe-state validation: "
            f"{mutations}"
        )
    expected_public = checkpoint.get("resume_validation")
    iram_info = checkpoint.get("resume_sa1_iram")
    if not isinstance(expected_public, dict) or not isinstance(iram_info, dict):
        raise RuntimeError("safe checkpoint lacks exact restore metadata")
    actual_public, actual_raw = campaign.checkpoint_machine_snapshot(m)
    public_equal = actual_public == expected_public
    iram_path = Path(str(iram_info.get("path", "")))
    if (
        not iram_path.is_file()
        or sha256(iram_path) != iram_info.get("sha256")
        or iram_path.stat().st_size != int(iram_info.get("size", -1))
    ):
        raise RuntimeError(
            "safe checkpoint SA-1 IRAM sidecar is missing or unauthenticated"
        )
    expected_iram = iram_path.read_bytes()
    iram_equal = actual_raw[0] == expected_iram
    if not public_equal or not iram_equal:
        raise RuntimeError(
            "fresh Nexen process did not restore the authenticated safe "
            f"machine: public_equal={public_equal}, iram_equal={iram_equal}"
        )
    return {
        "authenticated": True,
        "public_state_equal": True,
        "sa1_iram_equal": True,
        "sa1_iram_sidecar": str(iram_path.resolve()),
        "sa1_iram_sidecar_sha256": sha256(iram_path),
        "architectural_mutations_before_validation": mutations,
    }


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def read_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )


def interpreted_entry_batch_counts(count: int) -> list[int]:
    """Split an exact interpreted-entry request without changing its edges."""

    if count < 0:
        raise ValueError("negative game-update entry count")
    return [
        min(INTERPRETED_ENTRY_EDGE_MAX_BATCH, count - start)
        for start in range(0, count, INTERPRETED_ENTRY_EDGE_MAX_BATCH)
    ]


def run_game_update_boundaries(
    m: McpSession,
    count: int,
    *,
    xlat_native_enabled: bool,
) -> list[dict[str, Any]]:
    """Advance exact update entries under the selected root configuration.

    An authenticated checkpoint is paused after completed movie tick T at a
    safe main-SNES boundary; the next exact game-update entry represents
    T+1. With $071A cleared before release, that next entry reaches
    interpreted logical PC $003A92. Observe its rising IRAM-PC edge instead
    of waiting for a native-bank hook that cannot fire in this configuration.
    """

    if count < 0:
        raise ValueError("negative game-update entry count")
    if count == 0:
        return []
    if xlat_native_enabled:
        return campaign.run_game_update_entries(m, count)

    # With the translation root off, `$92:DB82` is intentionally unreachable:
    # waiting for it gives a misleading 664-frame timeout after the game has
    # already continued.  The project Nexen build exposes the corresponding
    # rising edge of the virtual 68000 PC in SA-1 IRAM.  Stop there instead,
    # before the interpreted `$003A92` body runs.
    responses: list[dict[str, Any]] = []
    for batch_count in interpreted_entry_batch_counts(count):
        response = dict(
            m.tool(
                "run_to_exact_iram_exec_edge",
                {
                    "iramAddress": M68K_PC_IRAM,
                    "value": M68K_GAME_UPDATE_ENTRY,
                    "mask": 0xFFFFFFFF,
                    "maxFrames": max(
                        campaign.MIN_TICK_VIDEO_FRAME_BUDGET,
                        batch_count * INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY
                        + campaign.MIN_TICK_VIDEO_FRAME_BUDGET,
                    ),
                    "occurrences": batch_count,
                },
            )
        )
        after_cpu = dict(m.get_cpu_state("Sa1"))
        after_frame = int(m.get_state().get("frameCount", 0))
        virtual_pc = int.from_bytes(
            bytes(m.read_memory("Sa1Memory", M68K_PC_IRAM, 4)), "little"
        ) & 0xFFFFFF
        required = (
            response.get("reason") == "breakpoint"
            and response.get("hit") is True
            and response.get("isPaused") is True
            and response.get("exactStopRemoved") is True
            and response.get("exactStopTriggered") is True
            and response.get("exactStopBreakDelivered") is True
            and int(response.get("exactStopHandle", 0)) > 0
            and int(response.get("requestedOccurrences", -1)) == batch_count
            and int(response.get("observedOccurrences", -1)) == batch_count
            and int(response.get("iramAddress", -1)) == M68K_PC_IRAM
            and int(response.get("observedValue", -1))
            == M68K_GAME_UPDATE_ENTRY
            and response.get("predicateMatched") is True
            and response.get("edgeRequired") is True
            and response.get("cleanupPauseApplied") is False
            and virtual_pc == M68K_GAME_UPDATE_ENTRY
            and int(response.get("cycleCount", -1))
            == int(after_cpu.get("cycleCount", -2))
            and int(response.get("triggerCycleCount", -1))
            == int(after_cpu.get("cycleCount", -2))
            and int(response.get("endFrame", -1)) == after_frame
            and int(response.get("triggerFrame", -1)) == after_frame
        )
        if not required:
            raise campaign.CampaignFailure(
                "hardware-boundary/timing",
                {
                    "reason": "interpreted_game_update_entry_exact_stop_failed",
                    "requested_entries": batch_count,
                    "virtual_pc": f"{virtual_pc:06X}",
                    "response": response,
                },
            )
        if campaign.halt16(m):
            raise campaign.CampaignFailure(
                "interpreter_or_native_hle",
                {"reason": "interpreter_halt", "halt": campaign.halt16(m)},
            )
        responses.append(response)
    return [
        {
            "boundary": "interpreted_pc_003a92_rising_edge_pre_body",
            "requested_entries": count,
            "observed_entries": count,
            "sa1_cycles": sum(
                int(response.get("cyclesAdvanced", 0)) for response in responses
            ),
            "video_frames": sum(
                int(response.get("framesAdvanced", 0)) for response in responses
            ),
            "result": {"batches": responses},
        }
    ]


def capture(
    m: McpSession,
    output: Path,
    tick: int,
) -> dict[str, Any]:
    work = read_work(m)
    path = output / f"snes-tick-{tick:05d}.work.bin"
    path.write_bytes(work)
    iram = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0800))
    state = m.get_state()
    m68k = campaign.register_snapshot(m)
    return {
        "event": "boundary",
        "mame_tick": tick,
        "snes_tick": le16(iram[0x0760:0x0762]),
        "video_frame": int(state.get("frameCount", 0)),
        "halt": le16(iram[0x004E:0x0050]),
        "pc68k": f"{int.from_bytes(iram[0x40:0x44], 'little') & 0xFFFFFF:06X}",
        "ccr_xnzvc": m68k["ccr_xnzvc"],
        "m68k": m68k,
        "interrupt_mask": le16(iram[0x7C:0x7E]) & 7,
        "virtual_irq_pending": le16(iram[0xAA:0xAC]),
        "virtual_irq_countdown": le16(iram[0xAC:0xAE]),
        "task_mask": be16(work[2:4]),
        "gates": {
            "072e": le16(iram[0x072E:0x0730]),
            "071a": le16(iram[0x071A:0x071C]),
            "0734": le16(iram[0x0734:0x0736]),
            "0736": le16(iram[0x0736:0x0738]),
            "073a": le16(iram[0x073A:0x073C]),
            "073c": le16(iram[0x073C:0x073E]),
        },
        "player": campaign.player_snapshot(m),
        "work": {
            "path": str(path),
            "sha256": sha256(path),
            "size": len(work),
            "mapped_16k_sha256": digest(work[:0x4000]),
            "upper_48k_sha256": digest(work[0x4000:]),
        },
    }


def main() -> int:
    args = parse_args()
    state_resumability = authenticate_start_state(
        state=args.state,
        state_mame_tick=args.state_mame_tick,
        rom=args.rom,
        timeline=args.timeline,
        nexen=args.nexen,
        lineage_events=args.state_lineage_events,
        allow_forensic_nonresumable_state=(
            args.allow_forensic_nonresumable_state
        ),
    )
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    dotnet = (
        "/home/chad/.dotnet8"
        if args.nexen.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = dotnet
    tick_rows: dict[int, dict[str, Any]] = {}
    with args.timeline.open(encoding="utf-8") as stream:
        for line in stream:
            raw = json.loads(line)
            tick = int(raw.get("tick", -1))
            if not args.state_mame_tick <= tick <= args.ticks[-1]:
                continue
            if raw.get("event") == "tick":
                tick_rows[tick] = raw
    missing_ticks = [
        tick
        for tick in [args.state_mame_tick, *args.ticks]
        if tick not in tick_rows
    ]
    if missing_ticks:
        raise RuntimeError(f"timeline missing ticks: {missing_ticks}")
    input_context_validation: dict[str, Any]
    if state_resumability["resumable_checkpoint"]:
        retained_buttons = int(
            state_resumability["lineage"]["resume_context"][
                "current_buttons"
            ]
        )
        timeline_buttons = int(
            tick_rows[args.state_mame_tick]["snes_buttons"]
        )
        if retained_buttons != timeline_buttons:
            raise RuntimeError(
                "safe-checkpoint controller context does not match the "
                f"timeline at completed tick {args.state_mame_tick}: "
                f"checkpoint={retained_buttons}, timeline={timeline_buttons}"
            )
        input_context_validation = {
            "authenticated": True,
            "completed_mame_tick": args.state_mame_tick,
            "checkpoint_buttons": retained_buttons,
            "timeline_buttons": timeline_buttons,
            "equal": True,
        }
    else:
        input_context_validation = {
            "authenticated": False,
            "reason": "forensic_nonresumable_override",
        }
    # The exporter's separate `input` rows are emitted from frame_done, after
    # the game update can already have changed player state.  Derive physical
    # transitions from exact per-tick rows so each event's reference snapshot
    # describes the same architectural boundary captured below.
    inputs: list[campaign.InputEvent] = []
    previous_buttons = int(
        tick_rows[args.state_mame_tick]["snes_buttons"]
    )
    for tick in sorted(tick_rows):
        if tick <= args.state_mame_tick:
            continue
        row = tick_rows[tick]
        buttons = int(row["snes_buttons"])
        if buttons != previous_buttons:
            inputs.append(campaign.InputEvent(tick, buttons, row))
            previous_buttons = buttons
    events: dict[int, list[campaign.InputEvent]] = {}
    for event in inputs:
        if args.state_mame_tick < event.tick <= args.ticks[-1]:
            events.setdefault(
                event.tick + args.input_apply_offset,
                [],
            ).append(event)

    provenance = {
        "event": "provenance",
        "scope": (
            "authenticated checkpoint continuation at exact retained-movie "
            "game-update entries; real controller timeline; no fresh-boot "
            "claim"
        ),
        "time_unix": time.time(),
        "lineage_kind": (
            "checkpoint_continuation"
            if state_resumability["resumable_checkpoint"]
            else "forensic_nonresumable"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "emulator": str(args.nexen.resolve()),
        "emulator_sha256": sha256(args.nexen),
        "emulator_identity": campaign.nexen_identity(
            args.nexen.resolve()
        ),
        "mame_timeline": str(args.timeline.resolve()),
        "mame_timeline_sha256": sha256(args.timeline),
        "resume_lineage": (
            state_resumability["lineage"]
            if state_resumability["resumable_checkpoint"]
            else None
        ),
        "source_state": str(args.state.resolve()),
        "source_state_sha256": sha256(args.state),
        "source_lineage_events": (
            str(args.state_lineage_events.resolve())
            if args.state_lineage_events is not None
            else None
        ),
        "source_lineage_events_sha256": (
            sha256(args.state_lineage_events)
            if args.state_lineage_events is not None
            else None
        ),
        "state_mame_tick": args.state_mame_tick,
        "segment_resume_tick": args.state_mame_tick + 1,
        "gameplay_native": args.gameplay_native,
        "input_apply_offset": args.input_apply_offset,
        "refresh_video_wram": args.refresh_video_wram,
        "irq_reload": args.irq_reload,
        "capture_script_sha256": sha256(Path(__file__).resolve()),
        "campaign_helper_sha256": sha256(
            Path(campaign.__file__).resolve()
        ),
        "campaign_configuration": (
            state_resumability["lineage"].get(
                "fresh_boot_campaign_configuration",
                {},
            )
            if state_resumability["resumable_checkpoint"]
            else {}
        ),
        "runtime_memory_writes": [],
    }
    metadata: list[dict[str, Any]] = [
        provenance,
        {
            "event": "start_state_resumability",
            **state_resumability,
        },
        {
            "event": "start_state_input_context",
            **input_context_validation,
        },
    ]
    loaded_state_validation: dict[str, Any] | None = None
    load_response: dict[str, Any] | None = None
    stderr = args.output / "emulator.stderr.log"
    with campaign.AuditedMcpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr,
    ) as m:
        campaign.pause_for_startup(m)
        load_response = dict(m.load_state(args.state.resolve()))
        campaign.require_paused(m, "checkpoint load")
        loaded_state_validation = validate_loaded_start_state(
            m,
            state_resumability,
        )
        metadata.append(
            {
                "event": "loaded_start_state_validation",
                **loaded_state_validation,
            }
        )
        video_wram_refresh = None
        if args.refresh_video_wram:
            video_wram_refresh = campaign.refresh_video_wram(
                m,
                args.rom.resolve(),
            )
            metadata.append(
                {
                    "event": "checkpoint_code_refresh",
                    **video_wram_refresh,
                }
            )
        legacy_mesen = args.nexen.name == "mesen211_mcp_controller.sh"
        if args.gameplay_native == "all-off":
            for address in ALL_NATIVE_GATES:
                m.write_u16(address, 0, "Sa1Memory")
        elif args.gameplay_native != "preserve":
            gate_values = {
                "on": (1, 1),
                "off": (0, 0),
                "xlat-off": (0, 1),
                "choke-off": (1, 0),
            }[args.gameplay_native]
            for address, gate_value in zip(
                GAMEPLAY_NATIVE_GATES, gate_values, strict=True
            ):
                m.write_u16(address, gate_value, "Sa1Memory")
        irq_reload_patch = None
        if args.irq_reload is not None:
            original = bytes(
                m.read_memory(
                    "snesPrgRom",
                    IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                    2,
                )
            )
            expected = IRQ_RELOAD_IMMEDIATE_EXPECTED
            if original != expected:
                raise RuntimeError(
                    "virtual-IRQ reload seam changed: expected "
                    f"{expected.hex()}, found {original.hex()}"
                )
            replacement = args.irq_reload.to_bytes(2, "little")
            m.write_memory(
                "snesPrgRom",
                IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                replacement.hex(),
            )
            irq_reload_patch = {
                "kind": "debugger_virtual_irq_reload_classification",
                "rom_offset": f"{IRQ_RELOAD_IMMEDIATE_ROM_OFFSET:06X}",
                "before": original.hex(),
                "after": replacement.hex(),
                "value": args.irq_reload,
                "restored_after_capture": True,
            }
            metadata.append({"event": "irq_reload_patch", **irq_reload_patch})
        current_tick = args.state_mame_tick
        xlat_native_enabled = (
            int(m.read_u16(GAMEPLAY_NATIVE_GATES[0], "Sa1Memory")) != 0
        )
        current_buttons = int(tick_rows[current_tick]["snes_buttons"])
        if not legacy_mesen:
            campaign.set_held_input(m, current_buttons)
        elif current_buttons:
            raise RuntimeError(
                "legacy Mesen cannot install a persistent held input without "
                "advancing a frame; start this neutral-only replay from a "
                "checkpoint whose serialized controller is neutral"
            )

        try:
            for target in sorted(set(args.ticks) | set(events)):
                # The production campaign is synchronized by exact
                # $003A92 game-update entries.  The old $0818 debugger path
                # patched live ROM and is intentionally retired; using it
                # here also made checkpoint bisections follow a different
                # boundary contract from the fresh campaign.
                spans = run_game_update_boundaries(
                    m,
                    target - current_tick,
                    xlat_native_enabled=xlat_native_enabled,
                )
                current_tick = target
                for event in events.get(target, []):
                    if legacy_mesen:
                        raise RuntimeError(
                            "legacy Mesen persistent-input transition reached; "
                            "use its frame-driven controller replay path"
                        )
                    campaign.set_held_input(m, event.buttons)
                    current_buttons = event.buttons
                    metadata.append(
                        {
                            "event": "input_apply",
                            "at_mame_tick": target,
                            "effective_mame_tick": event.tick,
                            "buttons": event.buttons,
                            "label": campaign.button_label(event.buttons),
                        }
                    )
                if target in args.ticks:
                    row = capture(m, args.output, target)
                    if target in args.save_ticks:
                        states_dir = args.output / "states"
                        states_dir.mkdir(exist_ok=True)
                        row["save_state"] = campaign.save_state(
                            m,
                            states_dir / f"snes-tick-{target:05d}.mss",
                        )
                    if target in args.safe_save_ticks:
                        if not xlat_native_enabled:
                            raise RuntimeError(
                                "safe checkpoint requires the native "
                                "$003A92 entry boundary"
                            )
                        states_dir = args.output / "states"
                        states_dir.mkdir(exist_ok=True)
                        safe = campaign.safe_checkpoint_rendezvous(
                            m,
                            states_dir
                            / f"safe-checkpoint-{target:05d}.mss",
                            mame_tick=target,
                            current_buttons=current_buttons,
                        )
                        safe_context = {
                            "phase": safe["phase"],
                            "mame_tick_completed": target,
                            "resume_mame_tick": safe[
                                "resume_mame_tick"
                            ],
                            "snes_tick": safe["after_snes_tick"],
                            "video_frame": int(
                                m.get_state().get("frameCount", 0)
                            ),
                            "current_buttons": current_buttons,
                            "player": campaign.player_snapshot(m),
                        }
                        row["safe_checkpoint"] = safe
                        metadata.append(
                            {
                                "event": "safe_checkpoint",
                                "mame_tick": target,
                                "resume_mame_tick": safe[
                                    "resume_mame_tick"
                                ],
                                "state": safe["state"],
                                "safe": safe,
                                "resume_context": safe_context,
                            }
                        )
                    reference = tick_rows[target]
                    row["player_comparison"] = campaign.compare_player(
                        row["player"], reference
                    )
                    row["held_buttons"] = current_buttons
                    row["spans"] = spans
                    if row["halt"]:
                        raise RuntimeError(f"halt at tick {target}: {row}")
                    metadata.append(row)
                    print(
                        json.dumps(
                            {
                                "mame_tick": target,
                                "snes_tick": row["snes_tick"],
                                "video_frame": row["video_frame"],
                                "player": row["player"],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
        except campaign.CampaignFailure as failure:
            m.pause()
            failure_dir = args.output / "failure"
            failure_dir.mkdir(exist_ok=True)
            detail = {
                "classification": failure.classification,
                **failure.detail,
                "last_completed_mame_tick": current_tick,
                "held_buttons": current_buttons,
                "frame": int(m.get_state().get("frameCount", 0)),
                "snes_tick": campaign.tick16(m),
                "halt": campaign.halt16(m),
                "player": campaign.player_snapshot(m),
                "state": campaign.save_state(
                    m, failure_dir / "pre-failure.mss"
                ),
                "screenshot": campaign.screenshot(
                    m, failure_dir / "pre-failure.png"
                ),
            }
            failure_path = args.output / "failure.json"
            failure_path.write_text(
                json.dumps(detail, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise RuntimeError(
                f"checkpoint replay failed; retained {failure_path}: "
                f"{json.dumps(detail, sort_keys=True)}"
            ) from failure
        finally:
            if irq_reload_patch is not None:
                m.write_memory(
                    "snesPrgRom",
                    IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                    irq_reload_patch["before"],
                )
                m.drain_notifications(timeout=0.02)

    log_path = args.output / "captures.jsonl"
    log_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in metadata),
        encoding="utf-8",
    )
    summary = {
        "scope": (
            f"checkpointed {args.gameplay_native} replay at exact retained-"
            "movie ticks; "
            "controller transitions applied at their declared tick boundary; "
            + (
                "authenticated safe-checkpoint continuation; not fresh-boot "
                "proof"
                if state_resumability["resumable_checkpoint"]
                else "explicit nonresumable forensic-state diagnostic; not "
                "production behavior or fresh-boot proof"
            )
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "emulator": str(args.nexen.resolve()),
        "emulator_sha256": sha256(args.nexen),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "state_mame_tick": args.state_mame_tick,
        "state_resumability": state_resumability,
        "loaded_state_validation": loaded_state_validation,
        "load_response": load_response,
        "input_context_validation": input_context_validation,
        "allow_forensic_nonresumable_state": (
            args.allow_forensic_nonresumable_state
        ),
        "timeline": str(args.timeline.resolve()),
        "timeline_sha256": sha256(args.timeline),
        "ticks": args.ticks,
        "save_ticks": args.save_ticks,
        "safe_save_ticks": args.safe_save_ticks,
        "gameplay_native": args.gameplay_native,
        "refresh_video_wram": args.refresh_video_wram,
        "video_wram_refresh": video_wram_refresh,
        "input_apply_offset": args.input_apply_offset,
        "irq_reload": args.irq_reload,
        "irq_reload_patch": irq_reload_patch,
        "capture_log": str(log_path),
        "capture_log_sha256": sha256(log_path),
        "all_player_references_green": all(
            row.get("player_comparison", {}).get("result") == "green"
            for row in metadata
            if row.get("event") == "boundary"
        ),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
