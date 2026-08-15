#!/usr/bin/env python3
"""Capture every framebuffer while replaying real controller input from a state.

This is a same-emulator continuation diagnostic.  It loads one retained state,
records an emulator movie using only the MCP controller path, then replays that
movie one frame at a time while retaining every framebuffer and PPU snapshot.
This avoids legacy Mesen's zero-frame one-frame input command without skipping
intervening frames.  By default it never writes ROM, game RAM, renderer RAM, or
gate state.  Explicit cross-ROM migration options are recorded as interventions
and exist only to diagnose a new ROM from an old checkpoint.
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
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


BUTTONS = {
    "neutral": 0,
    "select": McpSession.BTN_SELECT,
    "start": McpSession.BTN_START,
    "right": McpSession.BTN_RIGHT,
    "left": McpSession.BTN_LEFT,
    "up": McpSession.BTN_UP,
    "down": McpSession.BTN_DOWN,
    "b": McpSession.BTN_B,
    "b+right": McpSession.BTN_B | McpSession.BTN_RIGHT,
}

VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
QUEUE_PROMOTER_WRAM_OFFSET = 0x0ED00
QUEUE_PROMOTER_LENGTH = 0x0300
QUEUE_CODE_MARK_OFFSET = 0x089D8
EARLY_OBJ_BATCH_HELPER = 0xE9D160
EARLY_OBJ_BATCH_OLD = bytes.fromhex("2220cde95c008e7f")
EARLY_OBJ_BATCH_LAB = bytes.fromhex("2220cde92200d0e95c008e7f")
OBJ_BATCH_FIRST_LAB = bytes.fromhex("2200d0e92220cde95c008e7f")
OBJ_STAGE_RECORDS = (0xE9D800, 0x007C)
OBJ_STAGE_GROUP_HALF = (0xE9DBD8, 0x0076)
OBJ_BATCH_DISPATCH = 0xE9D600
OBJ_BATCH_DISPATCH_OLD = bytes.fromhex(
    "08c220afac747ec95ba5f00ac95aa5f00a285c00d0e9285c00d9e9285c40d6e9"
)
OBJ_BATCH_YIELD_DMA0_LAB = bytes.fromhex(
    "08e220ad111ff002286bc220"
    "afac747ec95ba5f00ac95aa5f00a285c00d0e9285c00d9e9285c40d6e9"
)
# service_pending_dma0 is copied into the live $7F WRAM execution mirror at
# boot.  A checkpoint lab must patch that executed copy, not the inactive
# source bytes in ROM bank $E9.
DMA0_SERVICE_TAIL = 0x7F8A61
DMA0_SERVICE_TAIL_OLD = bytes.fromhex(
    "2220cde99c111fa9018d0b422240c3e92240cde960"
)
DMA0_MAP_VMADDR_ZERO_LAB = bytes.fromhex(
    "2220cde99c16219c17219c111fa9018d0b422240c3e92240cde960"
)
EARLY_CAMERA_MANIFEST_CALL_OFFSET = 0x2CFB3F
EARLY_CAMERA_MANIFEST_CALL_OLD = bytes.fromhex("2200dc9e")
EARLY_CAMERA_MANIFEST_CALL_LAB = bytes.fromhex("22c5fb99")
EARLY_CAMERA_SA1_HELPER_OFFSET = 0x2CFBC5
CAMERA_MAILBOX_VALID_SA1_HELPER_LAB = bytes.fromhex(
    "e220af8934418f620141a9a58f630141c2205c00dc9e"
)
EARLY_CAMERA_NMI_ENTRY_OFFSET = 0x29CF00
EARLY_CAMERA_NMI_ENTRY_OLD = bytes.fromhex("af220141")
EARLY_CAMERA_NMI_ENTRY_LAB = bytes.fromhex("5c20dae9")
EARLY_CAMERA_NMI_HELPER_OFFSET = 0x29DA20
CAMERA_MAILBOX_VALID_NMI_HELPER_LAB = bytes.fromhex(
    "af630141c9a5d00ea9008f630141af6201412220c7e9af2201415c04cfe9"
)
EARLY_CAMERA_BATCH_ENTRY_OFFSET = 0x29DA40
EARLY_CAMERA_BATCH_ENTRY_OLD = bytes.fromhex("af220141")
EARLY_CAMERA_BATCH_ENTRY_LAB = bytes.fromhex("5c80dae9")
EARLY_CAMERA_BATCH_HELPER_OFFSET = 0x29DA80
CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB = bytes.fromhex(
    "af630141c9a5d00ea9008f630141af6201412220c7e9af2201415c44dae9"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9270)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, default=30)
    parser.add_argument(
        "--movie",
        type=Path,
        help="reuse an already recorded CurrentState input movie",
    )
    parser.add_argument(
        "--movie-frames",
        type=int,
        help="actual emulated frames in --movie (required with --movie)",
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help="inject the selected ROM's 5A22 renderer mirror after state load",
    )
    parser.add_argument(
        "--reserve-bg-slot-zero-migration",
        action="store_true",
        help=(
            "reset the legacy BG cache to the slot-zero-blank contract and force "
            "one full rebuild; requires --refresh-video-mirror"
        ),
    )
    parser.add_argument(
        "--shift-bg-slots-for-reserved-zero",
        action="store_true",
        help=(
            "preserve a legacy displayed BG by shifting its tilemap, VRAM records, "
            "and cache ownership from slots 0..190 to 1..191; requires an idle, "
            "queue-free checkpoint and --refresh-video-mirror"
        ),
    )
    parser.add_argument(
        "--early-obj-batch-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: patch the ROM helper in emulator "
            "memory so a due OBJ-pattern batch runs before wake/snapshot work"
        ),
    )
    parser.add_argument(
        "--obj-batch-first-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: run the due OBJ-pattern batch before "
            "the old-scene presenter and wake/snapshot work"
        ),
    )
    parser.add_argument(
        "--obj-stage-dma4-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: move foreground OBJ prefetch staging "
            "from NMI-owned DMA channel 5 to otherwise-unused channel 4"
        ),
    )
    parser.add_argument(
        "--obj-batch-yield-dma0-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: defer an OBJ-pattern batch while a "
            "DMA0 descriptor still owns the shared VRAM address registers"
        ),
    )
    parser.add_argument(
        "--dma0-map-vmaddr-zero-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: restore VRAM word address zero before "
            "servicing the known pending 4 KiB BG-map DMA0 descriptor"
        ),
    )
    parser.add_argument(
        "--early-camera-valid-mailbox-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: publish the stable raw camera with an "
            "A5 marker before each private manifest and consume it before NMI "
            "presentation"
        ),
    )
    parser.add_argument(
        "--camera-mailbox-valid-control-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: seed and consume one raw-camera/A5 "
            "publication under continuous movie cadence without installing "
            "the SA-1 producer"
        ),
    )
    parser.add_argument(
        "--early-camera-valid-mailbox-preboundary-lab",
        action="store_true",
        help=(
            "checkpoint diagnostic only: install the complete producer/consumer "
            "at the authenticated frame-141 pre-boundary PC without seeding a "
            "publication into an already-active manifest call"
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(emulator: Path) -> None:
    selected = (
        "/home/chad/.dotnet10"
        if emulator.name == "Nexen"
        else "/home/chad/.dotnet8"
    )
    other = (
        "/home/chad/.dotnet8"
        if selected.endswith("dotnet10")
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = selected
    existing = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (selected, other)
    ]
    os.environ["PATH"] = ":".join([selected, other, *existing])


def advance_one(m: McpSession) -> dict[str, Any]:
    before = int(m.get_state().get("frameCount", 0))
    responses: list[dict[str, Any]] = []
    for _attempt in range(8):
        response = m.run_frames(1)
        m.pause()
        after = int(m.get_state().get("frameCount", 0))
        responses.append(response)
        if after == before + 1:
            return {"before": before, "after": after, "responses": responses}
        if after != before:
            raise RuntimeError(
                f"one-frame movie playback advanced {after - before} frames: "
                f"{responses}"
            )
    raise RuntimeError(f"one-frame movie playback made no progress: {responses}")


def advance_recording_to(m: McpSession, target: int) -> None:
    """Advance an active recording monotonically to one exact video frame."""
    current = int(m.get_state().get("frameCount", 0))
    if current > target:
        raise RuntimeError(f"recording already passed frame {target}: {current}")
    while current < target:
        m.run_frames(min(250, target - current))
        m.pause()
        observed = int(m.get_state().get("frameCount", 0))
        if observed <= current or observed > target:
            raise RuntimeError(
                "recording did not advance monotonically: "
                f"{current}->{observed}, target={target}"
            )
        current = observed


def advance_recording_with_input(
    m: McpSession, buttons: int, frames: int
) -> dict[str, Any]:
    """Record one continuous held input despite partial timed-input returns.

    Legacy Mesen can return from a timed ``set_input`` request before all of
    its requested video frames have executed.  Reissuing the same held mask at
    the exact paused boundary preserves the edge while completing the span.
    A zero-progress or overshooting response is a harness failure.
    """

    start = int(m.get_state().get("frameCount", 0))
    target = start + frames
    current = start
    responses: list[dict[str, Any]] = []
    while current < target:
        remaining = target - current
        response = m.set_input(buttons, remaining)
        m.pause()
        observed = int(m.get_state().get("frameCount", 0))
        responses.append(
            {
                "before": current,
                "after": observed,
                "requested": remaining,
                "advanced": observed - current,
                "response": response,
            }
        )
        if observed <= current or observed > target + 1:
            raise RuntimeError(
                "timed controller input did not advance monotonically: "
                f"{current}->{observed}, target={target}, response={response}"
            )
        current = observed
    return {
        "mode": "continuous_timed_input",
        "buttons": buttons,
        "target_frame": target,
        "observed_frame": current,
        "overshoot_frames": current - target,
        "responses": responses,
    }


def controller_input_failure(
    rows: list[dict[str, Any]], button_mask: int
) -> dict[str, Any] | None:
    """Reject a claimed held input that never reaches the game mailbox."""

    if button_mask == 0:
        return None
    observed = [str(row.get("input_mailbox", "")) for row in rows]
    if any(value and int(value, 16) != 0 for value in observed):
        return None
    return {
        "kind": "controller_input_not_observed",
        "requested_button_mask": button_mask,
        "sampled_frames": len(rows),
        "observed_input_mailbox_values": sorted(set(observed)),
        "meaning": "setup failure; the framebuffer span cannot prove gameplay input",
    }


def write_checked(
    m: McpSession, offset: int, data: bytes, label: str
) -> dict[str, Any]:
    m.write_memory("snesWorkRam", offset, data.hex())
    observed = bytes(m.read_memory("snesWorkRam", offset, len(data)))
    if observed != data:
        raise RuntimeError(f"{label} intervention did not verify")
    return {
        "region": f"snesWorkRam ${offset:05X}-${offset + len(data) - 1:05X}",
        "length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "reason": label,
    }


def apply_obj_batch_order_lab(
    m: McpSession, phase: str, batch_first: bool
) -> dict[str, Any]:
    """Install a runtime-only leading-edge OBJ-batch experiment.

    The ordinary ROM is unchanged.  This replaces the batch-due helper's
    ``present -> wake`` tail with ``present -> OBJ batch -> wake`` so the same
    retained checkpoint can test whether late-VBlank entry, rather than tile
    volume, causes the measured 7+7+2 drain cadence.
    """
    current = bytes(
        m.read_memory("snesMemory", EARLY_OBJ_BATCH_HELPER, len(EARLY_OBJ_BATCH_LAB))
    )
    if not (
        current.startswith(EARLY_OBJ_BATCH_OLD)
        or current == EARLY_OBJ_BATCH_LAB
    ):
        raise RuntimeError(
            "early OBJ-batch lab helper does not match the authenticated seam: "
            f"{current.hex()}"
        )
    replacement = OBJ_BATCH_FIRST_LAB if batch_first else EARLY_OBJ_BATCH_LAB
    m.write_memory("snesMemory", EARLY_OBJ_BATCH_HELPER, replacement.hex())
    observed = bytes(
        m.read_memory("snesMemory", EARLY_OBJ_BATCH_HELPER, len(replacement))
    )
    if observed != replacement:
        raise RuntimeError("OBJ-batch ordering runtime intervention did not verify")
    return {
        "region": (
            f"snesMemory ${EARLY_OBJ_BATCH_HELPER:06X}-"
            f"${EARLY_OBJ_BATCH_HELPER + len(replacement) - 1:06X}"
        ),
        "length": len(replacement),
        "bytes": replacement.hex(),
        "phase": phase,
        "reason": (
            "runtime-only checkpoint lab: service a due OBJ-pattern batch "
            + (
                "before the old-scene presenter and wake/snapshot work"
                if batch_first
                else "after the old-scene presenter but before wake/snapshot work"
            )
            + "; ordinary ROM file is unchanged"
        ),
    }


def obj_staging_dma4_bytes(data: bytes) -> bytes:
    """Retarget one authenticated foreground staging helper from DMA5 to DMA4."""

    patched = data
    for register in range(7):
        opcode = 0x9C if register in (0, 6) else 0x8D
        old = bytes((opcode, 0x50 + register, 0x43))
        new = bytes((opcode, 0x40 + register, 0x43))
        old_count = patched.count(old)
        new_count = patched.count(new)
        if (old_count, new_count) == (1, 0):
            patched = patched.replace(old, new, 1)
        elif (old_count, new_count) != (0, 1):
            raise RuntimeError(
                "OBJ staging helper DMA-register seam is not authenticated: "
                f"register={register}, old={old_count}, new={new_count}"
            )
    old_enable = bytes.fromhex("a9208d0b42")
    new_enable = bytes.fromhex("a9108d0b42")
    old_count = patched.count(old_enable)
    new_count = patched.count(new_enable)
    if (old_count, new_count) == (1, 0):
        patched = patched.replace(old_enable, new_enable, 1)
    elif (old_count, new_count) != (0, 1):
        raise RuntimeError(
            "OBJ staging helper MDMAEN seam is not authenticated: "
            f"old={old_count}, new={new_count}"
        )
    return patched


def apply_obj_staging_dma4_lab(m: McpSession, phase: str) -> list[dict[str, Any]]:
    """Isolate foreground prefetch staging from NMI-owned DMA channel 5."""

    interventions: list[dict[str, Any]] = []
    for address, length in (OBJ_STAGE_RECORDS, OBJ_STAGE_GROUP_HALF):
        original = bytes(m.read_memory("snesMemory", address, length))
        replacement = obj_staging_dma4_bytes(original)
        m.write_memory("snesMemory", address, replacement.hex())
        observed = bytes(m.read_memory("snesMemory", address, length))
        if observed != replacement:
            raise RuntimeError(
                f"OBJ staging DMA4 runtime intervention failed at ${address:06X}"
            )
        interventions.append(
            {
                "region": f"snesMemory ${address:06X}-${address + length - 1:06X}",
                "length": length,
                "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": hashlib.sha256(replacement).hexdigest(),
                "phase": phase,
                "reason": (
                    "runtime-only checkpoint lab: foreground ROM-to-WRAM OBJ "
                    "prefetch staging uses otherwise-unused DMA channel 4 while "
                    "NMI retains private channel 5; ordinary ROM is unchanged"
                ),
            }
        )
    return interventions


def apply_obj_batch_yield_dma0_lab(
    m: McpSession, phase: str
) -> dict[str, Any]:
    """Keep a pending DMA0 descriptor's write-only VMADDR target undisturbed."""

    replacement = OBJ_BATCH_YIELD_DMA0_LAB
    current = bytes(
        m.read_memory("snesMemory", OBJ_BATCH_DISPATCH, len(replacement))
    )
    expected = OBJ_BATCH_DISPATCH_OLD + bytes(
        len(replacement) - len(OBJ_BATCH_DISPATCH_OLD)
    )
    if current not in (expected, replacement):
        raise RuntimeError(
            "OBJ-batch DMA0-yield seam is not authenticated: " + current.hex()
        )
    m.write_memory("snesMemory", OBJ_BATCH_DISPATCH, replacement.hex())
    observed = bytes(
        m.read_memory("snesMemory", OBJ_BATCH_DISPATCH, len(replacement))
    )
    if observed != replacement:
        raise RuntimeError("OBJ-batch DMA0-yield intervention did not verify")
    return {
        "region": (
            f"snesMemory ${OBJ_BATCH_DISPATCH:06X}-"
            f"${OBJ_BATCH_DISPATCH + len(replacement) - 1:06X}"
        ),
        "length": len(replacement),
        "before_sha256": hashlib.sha256(current).hexdigest(),
        "after_sha256": hashlib.sha256(replacement).hexdigest(),
        "phase": phase,
        "reason": (
            "runtime-only checkpoint lab: an OBJ pattern batch yields while "
            "DMA0 pending owns the write-only VRAM address; ordinary ROM is unchanged"
        ),
    }


def apply_dma0_map_vmaddr_zero_lab(
    m: McpSession, phase: str
) -> dict[str, Any]:
    """Restore the authenticated BG-map target immediately before DMA0 service."""

    replacement = DMA0_MAP_VMADDR_ZERO_LAB
    current = bytes(
        m.read_memory("snesMemory", DMA0_SERVICE_TAIL, len(replacement))
    )
    expected = DMA0_SERVICE_TAIL_OLD + bytes(
        len(replacement) - len(DMA0_SERVICE_TAIL_OLD)
    )
    if current not in (expected, replacement):
        raise RuntimeError(
            "DMA0 BG-map VMADDR restore seam is not authenticated: " + current.hex()
        )
    m.write_memory("snesMemory", DMA0_SERVICE_TAIL, replacement.hex())
    observed = bytes(
        m.read_memory("snesMemory", DMA0_SERVICE_TAIL, len(replacement))
    )
    if observed != replacement:
        raise RuntimeError("DMA0 BG-map VMADDR restore intervention did not verify")
    return {
        "region": (
            f"snesMemory ${DMA0_SERVICE_TAIL:06X}-"
            f"${DMA0_SERVICE_TAIL + len(replacement) - 1:06X}"
        ),
        "length": len(replacement),
        "before_sha256": hashlib.sha256(current).hexdigest(),
        "after_sha256": hashlib.sha256(replacement).hexdigest(),
        "phase": phase,
        "reason": (
            "runtime-only exact-checkpoint lab: restore VMADDR=$0000 for the "
            "known $7E:9000 4 KiB BG-map descriptor immediately before DMA0; "
            "ordinary ROM is unchanged"
        ),
    }


def apply_early_camera_valid_mailbox_lab(
    m: McpSession,
    phase: str,
    *,
    include_producer: bool = True,
    preboundary_seedless: bool = False,
    serialized_checkpoint_from_patched_recording: bool = False,
    patch_code: bool = True,
    touch_state: bool = True,
) -> list[dict[str, Any]]:
    """Install the complete raw-camera/A5 producer-consumer checkpoint lab."""

    producer_patches = (
        (
            EARLY_CAMERA_MANIFEST_CALL_OFFSET,
            EARLY_CAMERA_MANIFEST_CALL_OLD,
            EARLY_CAMERA_MANIFEST_CALL_LAB,
            "$99:FB3F-$FB42",
            "route manifest construction through the stable-camera publisher",
        ),
        (
            EARLY_CAMERA_SA1_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_SA1_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_SA1_HELPER_LAB,
            "$99:FBC5-$FBDA",
            "publish raw camera and A5 before private manifest work",
        ),
    )
    consumer_patches = (
        (
            EARLY_CAMERA_NMI_ENTRY_OFFSET,
            EARLY_CAMERA_NMI_ENTRY_OLD,
            EARLY_CAMERA_NMI_ENTRY_LAB,
            "$E9:CF00-$CF03",
            "route ordinary presentation through stable-camera intake",
        ),
        (
            EARLY_CAMERA_NMI_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_NMI_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_NMI_HELPER_LAB,
            "$E9:DA20-$DA3D",
            "consume the A5 camera publication before ordinary presentation",
        ),
        (
            EARLY_CAMERA_BATCH_ENTRY_OFFSET,
            EARLY_CAMERA_BATCH_ENTRY_OLD,
            EARLY_CAMERA_BATCH_ENTRY_LAB,
            "$E9:DA40-$DA43",
            "route batch-owned presentation through stable-camera intake",
        ),
        (
            EARLY_CAMERA_BATCH_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB,
            "$E9:DA80-$DA9D",
            "consume the A5 camera publication before batch presentation",
        ),
    )
    patches = (
        (*producer_patches, *consumer_patches)
        if include_producer
        else consumer_patches
    )
    patch_observations: list[
        tuple[int, bytes, bytes, str, str, bytes]
    ] = []
    all_installed = True
    for address, expected, replacement, region, reason in patches:
        current = bytes(m.read_memory("snesPrgRom", address, len(replacement)))
        padded_expected = expected + bytes(len(replacement) - len(expected))
        if current not in (padded_expected, replacement):
            raise RuntimeError(
                f"valid-mailbox lab expected {region}={padded_expected.hex()} "
                f"or the installed replacement, observed {current.hex()}"
            )
        all_installed = all_installed and current == replacement
        patch_observations.append(
            (address, padded_expected, replacement, region, reason, current)
        )

    interventions: list[dict[str, Any]] = []
    if patch_code:
        for address, _expected, replacement, region, reason, current in patch_observations:
            m.write_memory("snesPrgRom", address, replacement.hex())
            observed = bytes(m.read_memory("snesPrgRom", address, len(replacement)))
            if observed != replacement:
                raise RuntimeError(f"valid-mailbox lab did not verify at {region}")
            interventions.append(
                {
                    "kind": "checkpoint_early_camera_valid_mailbox_code",
                    "memory_type": "snesPrgRom",
                    "file_offset": f"0x{address:06X}",
                    "region": region,
                    "original": current.hex(),
                    "replacement": replacement.hex(),
                    "phase": phase,
                    "producer_installed": include_producer,
                    "preboundary_seedless": preboundary_seedless,
                    "installed_before_state_restore": not touch_state,
                    "reason": reason,
                    "meaning": "runtime diagnostic intervention; never acceptance evidence",
                }
            )
    elif not all_installed:
        raise RuntimeError(
            "valid-mailbox state handling requires code installed before "
            f"state restore; phase={phase}"
        )

    if not touch_state:
        return interventions

    sa1 = m.get_cpu_state("Sa1")
    sa1_pc = ((int(sa1.get("k", 0)) & 0xFF) << 16) | (
        int(sa1.get("pc", 0)) & 0xFFFF
    )
    manifest_pc = 0x9EDC00 <= sa1_pc < 0x9EDE14
    manifest_obj_x_helper_pc = 0x9EE1A0 <= sa1_pc < 0x9EE1FA
    at_seed_seam = manifest_pc or manifest_obj_x_helper_pc
    at_authenticated_preboundary = (
        phase == "record"
        and preboundary_seedless
        and sa1_pc in (0x0084A9, 0x0084B3)
    )
    prior_mailbox = bytes(m.read_memory("Sa1Memory", 0x410162, 2))
    serialized_mailbox_valid = (
        phase == "playback"
        and serialized_checkpoint_from_patched_recording
        and (
            prior_mailbox[1] in (0x00, 0xA5)
            or preboundary_seedless
        )
    )
    if not (at_seed_seam or at_authenticated_preboundary) and not (
        (phase == "playback" and all_installed) or serialized_mailbox_valid
    ):
        raise RuntimeError(
            "valid-mailbox lab requires either the proven manifest seed seam "
            "or the serialized state from a movie recorded with the patch in "
            "this invocation; "
            f"phase={phase}, SA-1 PC=${sa1_pc:06X}, "
            f"all_installed={all_installed}, mailbox={prior_mailbox.hex()}, "
            f"preboundary_seedless={preboundary_seedless}, "
            "serialized_checkpoint_from_patched_recording="
            f"{serialized_checkpoint_from_patched_recording}"
        )

    if serialized_mailbox_valid:
        raw_camera = prior_mailbox[:1]
        replacement = prior_mailbox
        seed_reason = (
            "preserve the exact mailbox state serialized by the patched "
            "recording; do not resample or republish after movie restore"
        )
        seed_kind = "checkpoint_early_camera_valid_mailbox_preserved"
    elif at_seed_seam:
        raw_camera = bytes(m.read_memory("Sa1Memory", 0x413489, 1))
        replacement = raw_camera + bytes((0xA5,))
        m.write_memory("Sa1Memory", 0x410162, replacement.hex())
        if bytes(m.read_memory("Sa1Memory", 0x410162, 2)) != replacement:
            raise RuntimeError("valid-mailbox checkpoint seed did not verify")
        seed_reason = (
            "the retained checkpoint is already inside the manifest call "
            "whose patched entry would have published this stable camera"
        )
        seed_kind = "checkpoint_early_camera_valid_mailbox_seed"
    elif at_authenticated_preboundary:
        raw_camera = prior_mailbox[:1]
        replacement = prior_mailbox
        seed_reason = (
            "install before the next paced boundary without publishing a "
            "camera sample from outside the quiescent manifest seam"
        )
        seed_kind = "checkpoint_early_camera_valid_mailbox_preboundary"
    else:
        if prior_mailbox[1] not in (0x00, 0xA5):
            raise RuntimeError(
                "CurrentState movie did not preserve a valid A5 mailbox state: "
                f"{prior_mailbox.hex()}"
            )
        raw_camera = prior_mailbox[:1]
        replacement = prior_mailbox
        seed_reason = (
            "preserve the exact mailbox state serialized with the already-"
            "installed CurrentState movie; do not resample a non-quiescent camera"
        )
        seed_kind = "checkpoint_early_camera_valid_mailbox_preserved"
    interventions.append(
        {
            "kind": seed_kind,
            "memory_type": "Sa1Memory",
            "region": "$41:0162-$0163",
            "sa1_pc": f"0x{sa1_pc:06X}",
            "original": prior_mailbox.hex(),
            "replacement": replacement.hex(),
            "raw_camera": raw_camera[0],
            "phase": phase,
            "producer_installed": include_producer,
            "preboundary_seedless": preboundary_seedless,
            "reason": seed_reason,
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    )
    return interventions


def shift_tilemap_slots(data: bytes) -> bytes:
    if len(data) != 0x1000:
        raise ValueError("BG tilemap must be 4 KiB")
    shifted = bytearray(data)
    for offset in range(0, len(data), 2):
        word = int.from_bytes(data[offset:offset + 2], "little")
        if word == 0:
            continue
        tile = word & 0x03FF
        if tile > 0x02FB:
            raise RuntimeError(f"BG tile {tile} cannot shift by four")
        shifted[offset:offset + 2] = (
            (word & 0xFC00) | (tile + 4)
        ).to_bytes(2, "little")
    return bytes(shifted)


def shift_legacy_bg_cache(m: McpSession) -> list[dict[str, Any]]:
    def read(offset: int, length: int) -> bytes:
        return bytes(m.read_memory("snesWorkRam", offset, length))

    busy = int.from_bytes(read(0x0899C, 2), "little")
    queue_states = [
        int.from_bytes(read(offset, 2), "little")
        for offset in (0x089D2, 0x089D6)
    ]
    if busy or any(queue_states):
        raise RuntimeError(
            "slot-shift migration requires renderer idle and both queues empty: "
            f"busy={busy}, queues={queue_states}"
        )

    high_water = int.from_bytes(read(0x000DC, 2), "little")
    free_count = int.from_bytes(read(0x089C2, 2), "little")
    if not 1 <= high_water <= 0x00BF or free_count > 0x00C0:
        raise RuntimeError(
            f"legacy BG allocator cannot shift: high_water={high_water}, "
            f"free_count={free_count}"
        )

    codes = read(0x0A000, 0x0400)
    old_slots = read(0x0A400, 0x0400)
    new_slots = bytearray(old_slots)
    reverse = bytearray(0x0180)
    live: list[tuple[int, int]] = []
    for offset in range(0, 0x0400, 2):
        code = int.from_bytes(codes[offset:offset + 2], "little")
        mapped = int.from_bytes(old_slots[offset:offset + 2], "little")
        if code == 0:
            new_slots[offset:offset + 2] = b"\x00\x00"
            continue
        if code == 0xFFFF:
            raise RuntimeError("legacy BG hash contains a tombstone")
        if mapped >= 0x00BF:
            raise RuntimeError(f"live BG slot {mapped} cannot shift")
        shifted = mapped + 1
        new_slots[offset:offset + 2] = shifted.to_bytes(2, "little")
        reverse[shifted * 2:shifted * 2 + 2] = code.to_bytes(2, "little")
        live.append((code, shifted))
    if len({slot for _code, slot in live}) != len(live):
        raise RuntimeError("legacy BG hash maps multiple codes to one slot")

    old_free = bytearray(read(0x07C00, 0x00C0))
    for index in range(free_count):
        if old_free[index] >= 0x00BF:
            raise RuntimeError(f"free BG slot {old_free[index]} cannot shift")
        old_free[index] += 1

    staged = shift_tilemap_slots(read(0x09000, 0x1000))
    displayed = bytes(m.read_memory("snesVideoRam", 0x0000, 0x1000))
    displayed_shifted = shift_tilemap_slots(displayed)
    graphics = bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000))
    graphics_shifted = bytes(0x80) + graphics[:-0x80]

    writes = [
        write_checked(m, 0x0A400, bytes(new_slots), "shift live BG hash slots by one"),
        write_checked(m, 0x0D000, bytes(reverse), "rebuild shifted BG reverse ownership"),
        write_checked(m, 0x07C00, bytes(old_free), "shift BG free-list slots by one"),
        write_checked(m, 0x09000, staged, "shift staged BG tilemap by four tiles"),
        write_checked(
            m,
            0x000DC,
            (high_water + 1).to_bytes(2, "little"),
            "advance BG high-water past the reserved blank slot",
        ),
        write_checked(
            m,
            0x089D0,
            (0xB7C5).to_bytes(2, "little"),
            "install reserved-blank reverse-map marker",
        ),
    ]
    m.write_memory("snesVideoRam", 0x0000, displayed_shifted.hex())
    if bytes(m.read_memory("snesVideoRam", 0x0000, 0x1000)) != displayed_shifted:
        raise RuntimeError("shifted displayed BG tilemap did not verify")
    writes.append(
        {
            "region": "snesVideoRam $0000-$0FFF",
            "length": 0x1000,
            "sha256": hashlib.sha256(displayed_shifted).hexdigest(),
            "reason": "shift displayed BG tilemap by four tiles",
        }
    )
    m.write_memory("snesVideoRam", 0x2000, graphics_shifted.hex())
    if bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000)) != graphics_shifted:
        raise RuntimeError("shifted BG graphics records did not verify")
    writes.append(
        {
            "region": "snesVideoRam $2000-$7FFF",
            "length": 0x6000,
            "sha256": hashlib.sha256(graphics_shifted).hexdigest(),
            "reason": "shift BG graphics records and clear physical slot zero",
        }
    )
    return writes


def apply_checkpoint_migration(
    m: McpSession,
    rom_bytes: bytes,
    reserve_slot_zero: bool,
    shift_slot_zero: bool,
) -> list[dict[str, Any]]:
    interventions: list[dict[str, Any]] = []
    if reserve_slot_zero:
        busy = int.from_bytes(
            m.read_memory("snesWorkRam", 0x0899C, 2), "little"
        )
        queue_states = [
            int.from_bytes(m.read_memory("snesWorkRam", offset, 2), "little")
            for offset in (0x089D2, 0x089D6)
        ]
        generations = [
            int.from_bytes(m.read_memory("snesWorkRam", offset, 2), "little")
            for offset in (0x0899A, 0x089A0, 0x089A4)
        ]
        if busy or any(queue_states) or len(set(generations)) != 1:
            raise RuntimeError(
                "full BG checkpoint migration requires a drained renderer: "
                f"busy={busy}, queues={queue_states}, generations={generations}. "
                "Continue the checkpoint without migration to an idle saved "
                "state, then retry."
            )
    mirror = rom_bytes[VIDEO_FILE_BASE:VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH]
    if len(mirror) != VIDEO_WRAM_LENGTH:
        raise RuntimeError("selected ROM does not contain the video mirror span")
    for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
        chunk = mirror[offset:offset + 0x1000]
        interventions.append(
            write_checked(
                m,
                VIDEO_WRAM_OFFSET + offset,
                chunk,
                "cross-ROM checkpoint video-mirror refresh",
            )
        )
    interventions.append(
        write_checked(
            m,
            QUEUE_CODE_MARK_OFFSET,
            bytes(2),
            "force the selected ROM's lazy queue-promoter installation",
        )
    )
    interventions.append(
        write_checked(
            m,
            QUEUE_PROMOTER_WRAM_OFFSET,
            bytes(QUEUE_PROMOTER_LENGTH),
            "remove the checkpoint's superseded queue-promoter code",
        )
    )
    if shift_slot_zero:
        interventions.extend(shift_legacy_bg_cache(m))
        return interventions
    if not reserve_slot_zero:
        return interventions

    # A cross-ROM checkpoint may originate from an in-flight capture; the
    # guard above requires a drained state before this migration runs. Merely
    # invalidating the 5A22 cache and setting its local manifest to $FFFF is
    # insufficient: snapshot_acquire_paced waits for a new private generation,
    # and the next organic producer snapshot can legitimately publish a zero
    # manifest because the SA-1 already acknowledged this live X1 image. That
    # used to replace the forced manifest before the worker claimed it.
    #
    # Seed the consumer cache from the authoritative, paused live X1 planes and
    # publish the seeded cache as one new private renderer generation. Clearing
    # old queue markers is required because their sparse payloads are relative
    # to the superseded ROM lineage.
    live_bg = bytes(m.read_memory("snesMemory", 0x414800, 0x0800))
    live_palette = bytes(m.read_memory("snesMemory", 0x412000, 0x0400))
    interventions.append(
        write_checked(
            m,
            0x02000,
            live_bg,
            "seed renderer BG code/color cache from paused live X1 planes",
        )
    )
    interventions.append(
        write_checked(
            m,
            0x02800,
            live_palette,
            "seed renderer palette cache from paused live X1 palette",
        )
    )
    for offset, label in (
        (0x089D2, "discard primary queue from superseded ROM lineage"),
        (0x089D6, "discard secondary queue from superseded ROM lineage"),
    ):
        interventions.append(write_checked(m, offset, bytes(2), label))
    for offset, length, label in (
        (0x0A000, 0x0800, "clear legacy BG code/slot hash"),
        (0x0D000, 0x0180, "clear legacy BG reverse ownership"),
        (0x07C00, 0x00C0, "clear legacy BG free list"),
    ):
        interventions.append(write_checked(m, offset, bytes(length), label))
    interventions.append(
        write_checked(
            m,
            0x089F0,
            bytes([0xFF]) * 16,
            (
                "invalidate the superseded checkpoint's applied BG column map "
                "so the selected ROM rebuilds its 1 KiB offset lookup"
            ),
        )
    )
    for offset, value, label in (
        (0x089C2, 0x0000, "reset BG free-list count"),
        (0x000DC, 0x0001, "start BG artwork allocation at physical slot one"),
        (0x089D0, 0xB7C5, "install reserved-blank reverse-map marker"),
        (0x089C4, 0x0000, "clear legacy prepared-list length"),
        (0x08982, 0x0000, "invalidate legacy raw BG cache marker"),
        (0x08990, 0x0001, "force a BG renderer event"),
        (0x089BC, 0xFFFF, "force one complete BG rebuild"),
        (0x089BE, 0x0001, "force the seeded live palette to the renderer"),
    ):
        interventions.append(
            write_checked(m, offset, value.to_bytes(2, "little"), label)
        )
    generation = int.from_bytes(
        m.read_memory("snesWorkRam", 0x089A0, 2), "little"
    )
    forced_generation = (generation + 2) & 0xFFFE
    if forced_generation == 0:
        forced_generation = 2
    interventions.append(
        write_checked(
            m,
            0x0899A,
            forced_generation.to_bytes(2, "little"),
            "publish the seeded cache as a complete private generation",
        )
    )
    frame_ack = int.from_bytes(
        m.read_memory("snesMemory", 0x003302, 2), "little"
    )
    forced_request = (frame_ack + 1) & 0xFFFF
    if forced_request == 0:
        forced_request = 1
    interventions.append(
        write_checked(
            m,
            0x01F1E,
            forced_request.to_bytes(2, "little"),
            "publish the forced local BG rebuild to the idle render worker",
        )
    )
    return interventions


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("frame counts must be positive")
    if (args.movie is None) != (args.movie_frames is None):
        raise SystemExit("--movie and --movie-frames must be supplied together")
    if args.movie_frames is not None and args.movie_frames <= 0:
        raise SystemExit("--movie-frames must be positive")
    if args.reserve_bg_slot_zero_migration and not args.refresh_video_mirror:
        raise SystemExit(
            "--reserve-bg-slot-zero-migration requires --refresh-video-mirror"
        )
    if args.shift_bg_slots_for_reserved_zero and not args.refresh_video_mirror:
        raise SystemExit(
            "--shift-bg-slots-for-reserved-zero requires --refresh-video-mirror"
        )
    if (
        args.reserve_bg_slot_zero_migration
        and args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit("select only one BG slot-zero migration strategy")
    if args.early_obj_batch_lab and args.obj_batch_first_lab:
        raise SystemExit("select only one OBJ-batch ordering lab")
    valid_camera_labs = sum(
        bool(value)
        for value in (
            args.early_camera_valid_mailbox_lab,
            args.camera_mailbox_valid_control_lab,
            args.early_camera_valid_mailbox_preboundary_lab,
        )
    )
    if valid_camera_labs > 1:
        raise SystemExit("select only one valid-camera mailbox lab")
    if args.movie is not None and valid_camera_labs:
        raise SystemExit(
            "valid-camera mailbox labs must record and replay one movie in "
            "the same invocation so preloaded code provenance is authenticated"
        )
    if args.movie is not None and (
        args.refresh_video_mirror
        or args.reserve_bg_slot_zero_migration
        or args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit(
            "cross-ROM migration must be captured in a newly recorded CurrentState movie"
        )
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("emulator", args.emulator),
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
    configure_dotnet(args.emulator)
    button_mask = BUTTONS[args.buttons]
    rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    provenance = {
        "scope": (
            "same-emulator retained-state controller movie and frame-exact "
            "framebuffer replay; explicitly labeled cross-ROM interventions "
            "when requested"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": button_mask,
        "frames": args.frames,
        "checkpoint_step": args.checkpoint_step,
        "runtime_memory_writes": interventions,
    }

    if args.movie is not None:
        movie_path = args.movie.resolve()
        if not movie_path.is_file():
            raise FileNotFoundError(f"movie not found: {movie_path}")
        recorded_frames = int(args.movie_frames)
        capture_frames = recorded_frames
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "recorded_frames": recorded_frames,
            "reused": True,
        }
    else:
        movie_path = output / "input.mmo"
        with McpSession(
            rom=rom,
            mesen=args.emulator.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=300.0,
            stderr_log=output / "record-emulator.stderr.log",
        ) as m:
            m.pause()
            if valid_camera_labs:
                interventions.extend(
                    apply_early_camera_valid_mailbox_lab(
                        m,
                        "record",
                        include_producer=(
                            args.early_camera_valid_mailbox_lab
                            or args.early_camera_valid_mailbox_preboundary_lab
                        ),
                        preboundary_seedless=(
                            args.early_camera_valid_mailbox_preboundary_lab
                        ),
                        patch_code=True,
                        touch_state=False,
                    )
                )
            m.load_state(args.state.resolve())
            m.pause()
            if args.refresh_video_mirror:
                interventions.extend(
                    apply_checkpoint_migration(
                        m,
                        rom.read_bytes(),
                        args.reserve_bg_slot_zero_migration,
                        args.shift_bg_slots_for_reserved_zero,
                    )
                )
            if args.early_obj_batch_lab or args.obj_batch_first_lab:
                interventions.append(
                    apply_obj_batch_order_lab(
                        m, "record", args.obj_batch_first_lab
                    )
                )
            if args.obj_stage_dma4_lab:
                interventions.extend(apply_obj_staging_dma4_lab(m, "record"))
            if args.obj_batch_yield_dma0_lab:
                interventions.append(
                    apply_obj_batch_yield_dma0_lab(m, "record")
                )
            if args.dma0_map_vmaddr_zero_lab:
                interventions.append(
                    apply_dma0_map_vmaddr_zero_lab(m, "record")
                )
            if (
                args.early_camera_valid_mailbox_lab
                or args.camera_mailbox_valid_control_lab
                or args.early_camera_valid_mailbox_preboundary_lab
            ):
                interventions.extend(
                    apply_early_camera_valid_mailbox_lab(
                        m,
                        "record",
                        include_producer=(
                            args.early_camera_valid_mailbox_lab
                            or args.early_camera_valid_mailbox_preboundary_lab
                        ),
                        preboundary_seedless=(
                            args.early_camera_valid_mailbox_preboundary_lab
                        ),
                        patch_code=False,
                        touch_state=True,
                    )
                )
            initial_shot = capture.take_screenshot(
                m, output / "record-initial.png"
            )
            record_response = m.record_movie(
                movie_path,
                author="supermn-snes framebuffer gate",
                description=(
                    f"{args.buttons} controller continuation from authenticated state"
                ),
                from_="CurrentState",
            )
            # Legacy Mesen can materialize a post-load frame while taking the
            # screenshot or entering CurrentState recording.  Controller
            # timing begins only after record_movie returns, so anchor the
            # requested span at that exact boundary.
            record_start_frame = int(m.get_state().get("frameCount", 0))
            input_response = advance_recording_with_input(
                m, button_mask, args.frames
            )
            record_end_frame = int(m.get_state().get("frameCount", 0))
            stop_response = m.stop_movie()
        capture.wait_for_file(movie_path)
        recorded_frames = record_end_frame - record_start_frame
        if recorded_frames <= 0:
            raise RuntimeError("controller movie made no emulated-frame progress")
        if recorded_frames < args.frames or recorded_frames > args.frames + 1:
            raise RuntimeError(
                "controller movie did not cover the requested frame window: "
                f"requested={args.frames}, recorded={recorded_frames}, "
                f"response={input_response}"
            )
        # A legacy timed input can cross two actual video frames when only one
        # remains.  Keep that extra input row in the authenticated movie, but
        # stop replay at the exact requested boundary.
        capture_frames = args.frames
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "record_start_frame": record_start_frame,
            "record_end_frame": record_end_frame,
            "recorded_frames": recorded_frames,
            "requested_frames": args.frames,
            "captured_frames": capture_frames,
            "reused": False,
            "initial_screenshot": initial_shot,
            "record_response": record_response,
            "input_response": input_response,
            "stop_response": stop_response,
        }

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "playback-emulator.stderr.log",
    ) as m:
        m.pause()
        if valid_camera_labs:
            interventions.extend(
                apply_early_camera_valid_mailbox_lab(
                    m,
                    "playback",
                    include_producer=(
                        args.early_camera_valid_mailbox_lab
                        or args.early_camera_valid_mailbox_preboundary_lab
                    ),
                    preboundary_seedless=(
                        args.early_camera_valid_mailbox_preboundary_lab
                    ),
                    patch_code=True,
                    touch_state=False,
                )
            )
        play_response = m.play_movie(movie_path)
        m.pause()
        if args.early_obj_batch_lab or args.obj_batch_first_lab:
            interventions.append(
                apply_obj_batch_order_lab(
                    m, "playback", args.obj_batch_first_lab
                )
            )
        if args.obj_stage_dma4_lab:
            interventions.extend(apply_obj_staging_dma4_lab(m, "playback"))
        if args.obj_batch_yield_dma0_lab:
            interventions.append(
                apply_obj_batch_yield_dma0_lab(m, "playback")
            )
        if args.dma0_map_vmaddr_zero_lab:
            interventions.append(
                apply_dma0_map_vmaddr_zero_lab(m, "playback")
            )
        if (
            args.early_camera_valid_mailbox_lab
            or args.camera_mailbox_valid_control_lab
            or args.early_camera_valid_mailbox_preboundary_lab
        ):
            interventions.extend(
                apply_early_camera_valid_mailbox_lab(
                    m,
                    "playback",
                    include_producer=(
                        args.early_camera_valid_mailbox_lab
                        or args.early_camera_valid_mailbox_preboundary_lab
                    ),
                    preboundary_seedless=(
                        args.early_camera_valid_mailbox_preboundary_lab
                    ),
                    serialized_checkpoint_from_patched_recording=(
                        args.movie is None
                    ),
                    patch_code=False,
                    touch_state=True,
                )
            )
        start_frame = int(m.get_state().get("frameCount", 0))
        initial = capture.snapshot(m)
        initial["relative_frame"] = 0
        try:
            initial["screenshot"] = capture.take_screenshot(
                m, output / "frame-000000.png"
            )
        except Exception as error:
            # Legacy Mesen can decline a screenshot immediately after restoring
            # a CurrentState movie, before the first replayed vblank.  The
            # recorder captured that exact pre-movie framebuffer already.
            fallback = (
                output / "record-initial.png"
                if (output / "record-initial.png").is_file()
                else movie_path.parent / "record-initial.png"
            )
            if not fallback.is_file():
                raise
            target = output / "frame-000000.png"
            shutil.copy2(fallback, target)
            initial["screenshot"] = {
                "path": str(target),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
                "source": str(fallback),
                "reason": "exact recorder framebuffer fallback",
                "playback_capture_error": repr(error),
            }
        initial["checkpoint"] = capture.save_checkpoint(
            m, output / "frame-000000.mss"
        )
        rows.append(initial)

        for relative in range(1, capture_frames + 1):
            advance = advance_one(m)
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            row["input_advance"] = advance
            row["screenshot"] = capture.take_screenshot(
                m, output / f"frame-{relative:06d}.png"
            )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
        movie_state_before_stop = m.movie_state()
        playback_stop_response = m.stop_movie()

    coverage = {
        "game_tick_start": rows[0]["tick"],
        "game_tick_end": rows[-1]["tick"],
        "video_frame_start": start_frame,
        "video_frame_end": rows[-1]["frame"],
        "captured_video_frames": len(rows),
        "complete": len(rows) == capture_frames + 1,
    }
    input_failure = controller_input_failure(rows, button_mask)
    acceptance_gate = unknown_diagnostic_gate(
        "framebuffer_capture",
        "Capture success is evidence availability, not visual correctness.",
    )
    acceptance_gate["rom_sha256"] = provenance["rom_sha256"]
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "provenance": provenance,
        "start_video_frame": start_frame,
        "end_video_frame": rows[-1]["frame"],
        "play_response": play_response,
        "movie_state_before_stop": movie_state_before_stop,
        "playback_stop_response": playback_stop_response,
        "coverage": coverage,
        "input_validation": {
            "status": "red" if input_failure is not None else "green",
            "failure": input_failure,
        },
        "captures": rows,
        "acceptance_gate": acceptance_gate,
    }
    report_path = output / "results.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "failed" if input_failure is not None else "captured",
                "frames": len(rows),
                "start_video_frame": start_frame,
                "end_video_frame": rows[-1]["frame"],
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 2 if input_failure is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
