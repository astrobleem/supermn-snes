#!/usr/bin/env python3
"""Sample framebuffers under a directly held MCP controller input.

This focused checkpoint diagnostic is the non-movie counterpart to
``capture_snes_input_framebuffers.py``. It requests one input step per iteration,
falls back to the frame-step primitive when the paused direct-input request does
not advance, and fails unless every sampled step advances exactly one video
frame. Explicit cross-ROM migrations are imported from that tool, require a
quiescent renderer, and are recorded in full. It is not fresh boot, FPS, an
aligned MAME pixel oracle, or aggregate gameplay acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from capture_snes_input_framebuffers import (  # noqa: E402
    BUTTONS,
    apply_checkpoint_migration,
    configure_dotnet,
    controller_input_failure,
)
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
from validate_fresh_poststart_framebuffers import (  # noqa: E402
    MAX_VERTICAL_BLACK_RUN,
    image_metrics,
)
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


SA1_DEADLINE_IRQ_FILE_OFFSET = 0x2CFB4E
SA1_DEADLINE_IRQ_OLD = bytes.fromhex("8d0922")
SA1_DEADLINE_IRQ_DISABLED_LAB = bytes.fromhex("eaeaea")
EARLY_CAMERA_MANIFEST_CALL_OFFSET = 0x2CFB3F
EARLY_CAMERA_MANIFEST_CALL_OLD = bytes.fromhex("2200dc9e")
EARLY_CAMERA_MANIFEST_CALL_LAB = bytes.fromhex("22c5fb99")
EARLY_CAMERA_SA1_HELPER_OFFSET = 0x2CFBC5
EARLY_CAMERA_SA1_HELPER_LAB = bytes.fromhex(
    "a904008f2201412200dc9e6b"
)
EARLY_CAMERA_NMI_ENTRY_OFFSET = 0x29CF00
EARLY_CAMERA_NMI_ENTRY_OLD = bytes.fromhex("af220141")
EARLY_CAMERA_NMI_ENTRY_LAB = bytes.fromhex("5c20dae9")
EARLY_CAMERA_NMI_HELPER_OFFSET = 0x29DA20
EARLY_CAMERA_NMI_HELPER_LAB = bytes.fromhex(
    "af220141c904d010c22020bca7e220eb2220c7e95c3dcfe95c04cfe9"
)
EARLY_CAMERA_BATCH_ENTRY_OFFSET = 0x29DA40
EARLY_CAMERA_BATCH_ENTRY_OLD = bytes.fromhex("af220141")
EARLY_CAMERA_BATCH_ENTRY_LAB = bytes.fromhex("5c80dae9")
EARLY_CAMERA_BATCH_HELPER_OFFSET = 0x29DA80
EARLY_CAMERA_BATCH_HELPER_LAB = bytes.fromhex(
    "af220141c904d010c22020bca7e220eb2220c7e95c76dae95c44dae9"
)
CAMERA_MAILBOX_SA1_HELPER_LAB = bytes.fromhex(
    "e220af8934418f620141af6301411a8f630141c2202200dc9e6b"
)
CAMERA_MAILBOX_NMI_HELPER_LAB = bytes.fromhex(
    "af630141cfb2717ef00c8fb2717eaf6201412220c7e9af2201415c04cfe9"
)
CAMERA_MAILBOX_BATCH_HELPER_LAB = bytes.fromhex(
    "af630141cfb2717ef00c8fb2717eaf6201412220c7e9af2201415c44dae9"
)
CAMERA_MAILBOX_VALID_SA1_HELPER_LAB = bytes.fromhex(
    "e220af8934418f620141a9a58f630141c2205c00dc9e"
)
CAMERA_MAILBOX_VALID_NMI_HELPER_LAB = bytes.fromhex(
    "af630141c9a5d00ea9008f630141af6201412220c7e9af2201415c04cfe9"
)
CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB = bytes.fromhex(
    "af630141c9a5d00ea9008f630141af6201412220c7e9af2201415c44dae9"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9400)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, default=30)
    parser.add_argument("--visual-grace-frames", type=int, default=100)
    parser.add_argument(
        "--max-vertical-black-run",
        type=int,
        default=MAX_VERTICAL_BLACK_RUN,
        help=(
            "fail closed after the grace window when a near-full-height black "
            "run exceeds this many playfield columns (default: project gate)"
        ),
    )
    parser.add_argument(
        "--max-render-hold-frames",
        type=int,
        default=32,
        help=(
            "fail closed if render_complete does not change for more than this "
            "many consecutive sampled video-frame transitions (default: 32)"
        ),
    )
    parser.add_argument(
        "--stop-at-coherent-idle",
        action="store_true",
        help=(
            "treat --frames as a ceiling and stop after a nonzero frame when "
            "the renderer is idle, both queues are empty, and all generations agree"
        ),
    )
    parser.add_argument(
        "--coherent-idle-settle-frames",
        type=int,
        default=2,
        help=(
            "with --stop-at-coherent-idle, require this many additional "
            "coherent-idle video frames before saving the final state/image "
            "(default: 2, covering legacy Mesen screenshot latency)"
        ),
    )
    parser.add_argument("--refresh-video-mirror", action="store_true")
    parser.add_argument(
        "--legacy-full-bg-map-update",
        action="store_true",
        help=(
            "checkpoint lab only: after refreshing the selected renderer, "
            "restore the raw-map/full-rebuild BG entry points in WRAM"
        ),
    )
    parser.add_argument(
        "--freeze-exact-bg-map",
        action="store_true",
        help=(
            "checkpoint lab only: retain the already-coherent exact BG map "
            "and route later raw-layout changes through the same-layout consumer"
        ),
    )
    parser.add_argument(
        "--initialize-basis9-from-coherent-map",
        action="store_true",
        help=(
            "cross-ROM checkpoint lab only: reconstruct the successor's "
            "nine-bit displayed-map basis from one coherent exact image"
        ),
    )
    parser.add_argument(
        "--park-sa1-at-current-pc",
        action="store_true",
        help=(
            "park the paused SA-1 with a runtime BRA -2 while the 5A22 performs "
            "a checkpoint-only forced rebuild"
        ),
    )
    parser.add_argument(
        "--disable-sa1-deadline-irq-lab",
        action="store_true",
        help=(
            "checkpoint lab only: suppress the SA-1's event-driven S-CPU "
            "deadline request so only the next NMI may release a paced tick"
        ),
    )
    parser.add_argument(
        "--early-quiescent-camera-lab",
        action="store_true",
        help=(
            "checkpoint lab only: publish arm state 4 before manifest build "
            "and let NMI capture that stable camera before presentation"
        ),
    )
    parser.add_argument(
        "--early-camera-mailbox-lab",
        action="store_true",
        help=(
            "checkpoint lab only: publish a stable raw-camera generation "
            "before manifest work without changing scheduler arm ownership"
        ),
    )
    parser.add_argument(
        "--camera-mailbox-seed-control-lab",
        action="store_true",
        help=(
            "checkpoint lab control: write the proposed camera mailbox with "
            "the already-seen generation so no consumer can observe it"
        ),
    )
    parser.add_argument(
        "--camera-mailbox-nmi-control-lab",
        action="store_true",
        help=(
            "checkpoint lab control: install mailbox NMI polling with no new "
            "generation and no SA-1 publisher"
        ),
    )
    parser.add_argument(
        "--camera-mailbox-valid-control-lab",
        action="store_true",
        help=(
            "checkpoint lab control: consume one raw-camera/A5 mailbox "
            "publication without installing the future SA-1 publisher"
        ),
    )
    parser.add_argument(
        "--early-camera-valid-mailbox-lab",
        action="store_true",
        help=(
            "checkpoint lab: publish raw camera plus A5 before every manifest "
            "and consume it before NMI presentation"
        ),
    )
    parser.add_argument("--reserve-bg-slot-zero-migration", action="store_true")
    parser.add_argument("--shift-bg-slots-for-reserved-zero", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coherent_idle(row: dict[str, Any]) -> bool:
    generations = (
        row["snapshot_generation"],
        row["direct_generation"],
        row["rendered_generation"],
    )
    return (
        row["renderer_busy"] == 0
        and row["render_queue_primary"] == 0
        and row["render_queue_secondary"] == 0
        and len(set(generations)) == 1
    )


def renderer_quiescent(row: dict[str, Any]) -> bool:
    """Return whether it is safe to replace the paused WRAM renderer code."""

    return (
        row["renderer_busy"] == 0
        and row["render_queue_primary"] == 0
        and row["render_queue_secondary"] == 0
    )


def apply_legacy_full_bg_map_update(m: McpSession) -> list[dict[str, Any]]:
    """Disable the experimental canonical/incremental BG path in paused WRAM."""

    patches = (
        (
            0x29B780,
            bytes.fromhex("5c93eae9ea"),
            bytes.fromhex("c230eaeaea"),
            "$7F:B780-$B784",
            "restore REP #$30 before the retained raw-map comparison loop",
        ),
        (
            0x29B80F,
            bytes.fromhex("5c73ece9eaeaeaeaeaea"),
            bytes.fromhex("c230eaeaeaeaeaeaeaea"),
            "$7F:B80F-$B818",
            "restore REP #$30 before the retained raw offset-table builder",
        ),
    )
    interventions: list[dict[str, Any]] = []
    for address, expected, replacement, region, reason in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"legacy BG lab expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        verified = bytes(
            m.read_memory("snesPrgRom", address, len(replacement))
        )
        if verified != replacement:
            raise RuntimeError(f"legacy BG lab patch did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_legacy_full_bg_map_update",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": reason,
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )
    return interventions


def apply_freeze_exact_bg_map(m: McpSession) -> list[dict[str, Any]]:
    """Keep a proven coherent exact map fixed while accepting newer scene data."""

    address = 0x29EA93
    expected = bytes.fromhex("c230af96")
    replacement = bytes.fromhex("5c80bce9")  # JML $E9:BC80 (same-layout consumer)
    observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
    if observed != expected:
        raise RuntimeError(
            "fixed-map lab expected snesPrgRom 0x29EA93="
            f"{expected.hex()}, observed {observed.hex()}"
        )
    m.write_memory("snesPrgRom", address, replacement.hex())
    verified = bytes(m.read_memory("snesPrgRom", address, len(replacement)))
    if verified != replacement:
        raise RuntimeError("fixed-map lab ROM intervention did not verify")
    return [
        {
            "kind": "checkpoint_freeze_exact_bg_map",
            "memory_type": "snesPrgRom",
            "file_offset": "0x29EA93",
            "region": "$E9:EA93-$EA96",
            "original": expected.hex(),
            "replacement": replacement.hex(),
            "reason": (
                "test whether raw X1 gap migration is presentation-only when "
                "the coherent identity map and offset table stay fixed"
            ),
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    ]


def disable_sa1_deadline_irq_lab(m: McpSession) -> list[dict[str, Any]]:
    """Test whether post-NMI paced release causes the visible camera hold."""

    address = SA1_DEADLINE_IRQ_FILE_OFFSET
    expected = SA1_DEADLINE_IRQ_OLD
    replacement = SA1_DEADLINE_IRQ_DISABLED_LAB
    observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
    if observed != expected:
        raise RuntimeError(
            "deadline-IRQ lab expected snesPrgRom 0x2CFB4E="
            f"{expected.hex()}, observed {observed.hex()}"
        )
    m.write_memory("snesPrgRom", address, replacement.hex())
    verified = bytes(m.read_memory("snesPrgRom", address, len(replacement)))
    if verified != replacement:
        raise RuntimeError("deadline-IRQ lab patch did not verify")
    return [
        {
            "kind": "checkpoint_disable_sa1_deadline_irq",
            "memory_type": "snesPrgRom",
            "file_offset": "0x2CFB4E",
            "region": "$99:FB4E-$FB50",
            "original": expected.hex(),
            "replacement": replacement.hex(),
            "reason": (
                "isolate a paced wake that becomes due only after the leading "
                "NMI has already presented the preceding scroll target"
            ),
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    ]


def early_quiescent_camera_lab(m: McpSession) -> list[dict[str, Any]]:
    """Expose a stable tick-boundary camera while its manifest is being built."""

    patches = (
        (
            EARLY_CAMERA_MANIFEST_CALL_OFFSET,
            EARLY_CAMERA_MANIFEST_CALL_OLD,
            EARLY_CAMERA_MANIFEST_CALL_LAB,
            "$99:FB3F-$FB42",
            "route the manifest call through the arm-state-4 publisher",
        ),
        (
            EARLY_CAMERA_SA1_HELPER_OFFSET,
            bytes(len(EARLY_CAMERA_SA1_HELPER_LAB)),
            EARLY_CAMERA_SA1_HELPER_LAB,
            "$99:FBC5-$FBD0",
            "publish stable-camera ownership before building private manifest data",
        ),
        (
            EARLY_CAMERA_NMI_ENTRY_OFFSET,
            EARLY_CAMERA_NMI_ENTRY_OLD,
            EARLY_CAMERA_NMI_ENTRY_LAB,
            "$E9:CF00-$CF03",
            "route ordinary NMI presentation through the arm-state-4 gate",
        ),
        (
            EARLY_CAMERA_NMI_HELPER_OFFSET,
            bytes(len(EARLY_CAMERA_NMI_HELPER_LAB)),
            EARLY_CAMERA_NMI_HELPER_LAB,
            "$E9:DA20-$DA3B",
            "capture/publish the quiescent camera before ordinary presentation",
        ),
        (
            EARLY_CAMERA_BATCH_ENTRY_OFFSET,
            EARLY_CAMERA_BATCH_ENTRY_OLD,
            EARLY_CAMERA_BATCH_ENTRY_LAB,
            "$E9:DA40-$DA43",
            "route batch-owned NMI presentation through the same ownership gate",
        ),
        (
            EARLY_CAMERA_BATCH_HELPER_OFFSET,
            bytes(len(EARLY_CAMERA_BATCH_HELPER_LAB)),
            EARLY_CAMERA_BATCH_HELPER_LAB,
            "$E9:DA80-$DA9B",
            "capture/publish the quiescent camera before batch presentation",
        ),
    )
    interventions: list[dict[str, Any]] = []
    for address, expected, replacement, region, reason in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"early-camera lab expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        if bytes(m.read_memory("snesPrgRom", address, len(replacement))) != replacement:
            raise RuntimeError(f"early-camera lab patch did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_early_quiescent_camera_code",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": reason,
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )

    sa1 = m.get_cpu_state("Sa1")
    sa1_pc = ((int(sa1.get("k", 0)) & 0xFF) << 16) | (
        int(sa1.get("pc", 0)) & 0xFFFF
    )
    # The retained pre-hold checkpoint is in rmb_obj_x_visible, a bounded
    # out-of-line subroutine called only by the manifest's OBJ scan.  Admit
    # that exact helper as well as the contiguous manifest body; do not treat
    # arbitrary bank-$9E renderer execution as quiescent ownership.
    manifest_pc = 0x9EDC00 <= sa1_pc < 0x9EDE14
    manifest_obj_x_helper_pc = 0x9EE1A0 <= sa1_pc < 0x9EE1FA
    if not (manifest_pc or manifest_obj_x_helper_pc):
        raise RuntimeError(
            "early-camera checkpoint seed requires SA-1 inside the private "
            f"manifest builder, observed PC ${sa1_pc:06X}"
        )
    prior_arm = bytes(m.read_memory("Sa1Memory", 0x410122, 2))
    if prior_arm != bytes.fromhex("0200"):
        raise RuntimeError(
            "early-camera checkpoint seed expected released arm=2, observed "
            f"{prior_arm.hex()}"
        )
    m.write_memory("Sa1Memory", 0x410122, "0400")
    if bytes(m.read_memory("Sa1Memory", 0x410122, 2)) != bytes.fromhex("0400"):
        raise RuntimeError("early-camera checkpoint arm seed did not verify")
    interventions.append(
        {
            "kind": "checkpoint_early_quiescent_camera_seed",
            "memory_type": "Sa1Memory",
            "region": "$41:0122-$0123",
            "sa1_pc": f"0x{sa1_pc:06X}",
            "original": prior_arm.hex(),
            "replacement": "0400",
            "reason": (
                "the retained checkpoint is already inside the manifest call "
                "that the patched predecessor seam would have marked"
            ),
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    )
    return interventions


def early_camera_mailbox_lab(m: McpSession) -> list[dict[str, Any]]:
    """Publish camera phase before manifest work without changing arm state."""

    patches = (
        (
            EARLY_CAMERA_MANIFEST_CALL_OFFSET,
            EARLY_CAMERA_MANIFEST_CALL_OLD,
            EARLY_CAMERA_MANIFEST_CALL_LAB,
            "$99:FB3F-$FB42",
            "route manifest construction through the camera-mailbox publisher",
        ),
        (
            EARLY_CAMERA_SA1_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_SA1_HELPER_LAB)),
            CAMERA_MAILBOX_SA1_HELPER_LAB,
            "$99:FBC5-$FBDE",
            "publish raw camera then generation before private manifest work",
        ),
        (
            EARLY_CAMERA_NMI_ENTRY_OFFSET,
            EARLY_CAMERA_NMI_ENTRY_OLD,
            EARLY_CAMERA_NMI_ENTRY_LAB,
            "$E9:CF00-$CF03",
            "route ordinary NMI presentation through camera-mailbox intake",
        ),
        (
            EARLY_CAMERA_NMI_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_NMI_HELPER_LAB)),
            CAMERA_MAILBOX_NMI_HELPER_LAB,
            "$E9:DA20-$DA3D",
            "consume a new stable camera generation before ordinary presentation",
        ),
        (
            EARLY_CAMERA_BATCH_ENTRY_OFFSET,
            EARLY_CAMERA_BATCH_ENTRY_OLD,
            EARLY_CAMERA_BATCH_ENTRY_LAB,
            "$E9:DA40-$DA43",
            "route batch-owned NMI presentation through camera-mailbox intake",
        ),
        (
            EARLY_CAMERA_BATCH_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_BATCH_HELPER_LAB)),
            CAMERA_MAILBOX_BATCH_HELPER_LAB,
            "$E9:DA80-$DA9D",
            "consume a new stable camera generation before batch presentation",
        ),
    )
    interventions: list[dict[str, Any]] = []
    for address, expected, replacement, region, reason in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"camera-mailbox lab expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        if bytes(m.read_memory("snesPrgRom", address, len(replacement))) != replacement:
            raise RuntimeError(f"camera-mailbox lab patch did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_early_camera_mailbox_code",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": reason,
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )

    sa1 = m.get_cpu_state("Sa1")
    sa1_pc = ((int(sa1.get("k", 0)) & 0xFF) << 16) | (
        int(sa1.get("pc", 0)) & 0xFFFF
    )
    manifest_pc = 0x9EDC00 <= sa1_pc < 0x9EDE14
    manifest_obj_x_helper_pc = 0x9EE1A0 <= sa1_pc < 0x9EE1FA
    if not (manifest_pc or manifest_obj_x_helper_pc):
        raise RuntimeError(
            "camera-mailbox checkpoint seed requires the proven manifest call "
            f"graph, observed SA-1 PC ${sa1_pc:06X}"
        )
    raw_camera = bytes(m.read_memory("Sa1Memory", 0x413489, 1))
    prior_mailbox = bytes(m.read_memory("Sa1Memory", 0x410162, 2))
    seen_generation = bytes(m.read_memory("snesWorkRam", 0x71B2, 1))[0]
    generation = (seen_generation + 1) & 0xFF
    seeded = raw_camera + bytes((generation,))
    m.write_memory("Sa1Memory", 0x410162, seeded.hex())
    if bytes(m.read_memory("Sa1Memory", 0x410162, 2)) != seeded:
        raise RuntimeError("camera-mailbox checkpoint seed did not verify")
    interventions.append(
        {
            "kind": "checkpoint_early_camera_mailbox_seed",
            "memory_type": "Sa1Memory",
            "region": "$41:0162-$0163",
            "sa1_pc": f"0x{sa1_pc:06X}",
            "original": prior_mailbox.hex(),
            "replacement": seeded.hex(),
            "raw_camera": raw_camera[0],
            "prior_seen_generation": seen_generation,
            "reason": (
                "the retained checkpoint is already inside the manifest call "
                "whose patched entry would have published this stable camera"
            ),
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    )
    return interventions


def camera_mailbox_seed_control_lab(m: McpSession) -> list[dict[str, Any]]:
    """Write proposed mailbox bytes without publishing a new generation."""

    sa1 = m.get_cpu_state("Sa1")
    sa1_pc = ((int(sa1.get("k", 0)) & 0xFF) << 16) | (
        int(sa1.get("pc", 0)) & 0xFFFF
    )
    manifest_pc = 0x9EDC00 <= sa1_pc < 0x9EDE14
    manifest_obj_x_helper_pc = 0x9EE1A0 <= sa1_pc < 0x9EE1FA
    if not (manifest_pc or manifest_obj_x_helper_pc):
        raise RuntimeError(
            "camera-mailbox control requires the proven manifest call graph, "
            f"observed SA-1 PC ${sa1_pc:06X}"
        )
    raw_camera = bytes(m.read_memory("Sa1Memory", 0x413489, 1))
    prior_mailbox = bytes(m.read_memory("Sa1Memory", 0x410162, 2))
    seen_generation = bytes(m.read_memory("snesWorkRam", 0x71B2, 1))[0]
    replacement = raw_camera + bytes((seen_generation,))
    m.write_memory("Sa1Memory", 0x410162, replacement.hex())
    if bytes(m.read_memory("Sa1Memory", 0x410162, 2)) != replacement:
        raise RuntimeError("camera-mailbox control write did not verify")
    return [
        {
            "kind": "checkpoint_camera_mailbox_seed_control",
            "memory_type": "Sa1Memory",
            "region": "$41:0162-$0163",
            "sa1_pc": f"0x{sa1_pc:06X}",
            "original": prior_mailbox.hex(),
            "replacement": replacement.hex(),
            "raw_camera": raw_camera[0],
            "seen_generation": seen_generation,
            "reason": "test mailbox-address safety without publishing to NMI",
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    ]


def camera_mailbox_nmi_control_lab(m: McpSession) -> list[dict[str, Any]]:
    """Install the NMI mailbox redirect without publishing a generation."""

    interventions = camera_mailbox_seed_control_lab(m)
    patches = (
        (
            EARLY_CAMERA_NMI_ENTRY_OFFSET,
            EARLY_CAMERA_NMI_ENTRY_OLD,
            EARLY_CAMERA_NMI_ENTRY_LAB,
            "$E9:CF00-$CF03",
        ),
        (
            EARLY_CAMERA_NMI_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_NMI_HELPER_LAB)),
            CAMERA_MAILBOX_NMI_HELPER_LAB,
            "$E9:DA20-$DA3D",
        ),
        (
            EARLY_CAMERA_BATCH_ENTRY_OFFSET,
            EARLY_CAMERA_BATCH_ENTRY_OLD,
            EARLY_CAMERA_BATCH_ENTRY_LAB,
            "$E9:DA40-$DA43",
        ),
        (
            EARLY_CAMERA_BATCH_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_BATCH_HELPER_LAB)),
            CAMERA_MAILBOX_BATCH_HELPER_LAB,
            "$E9:DA80-$DA9D",
        ),
    )
    for address, expected, replacement, region in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"mailbox NMI control expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        if bytes(m.read_memory("snesPrgRom", address, len(replacement))) != replacement:
            raise RuntimeError(f"mailbox NMI control did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_camera_mailbox_nmi_control",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": "test NMI redirect ABI with no observable mailbox generation",
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )
    return interventions


def camera_mailbox_valid_control_lab(m: McpSession) -> list[dict[str, Any]]:
    """Consume one shared valid marker without a future SA-1 publisher."""

    sa1 = m.get_cpu_state("Sa1")
    sa1_pc = ((int(sa1.get("k", 0)) & 0xFF) << 16) | (
        int(sa1.get("pc", 0)) & 0xFFFF
    )
    manifest_pc = 0x9EDC00 <= sa1_pc < 0x9EDE14
    manifest_obj_x_helper_pc = 0x9EE1A0 <= sa1_pc < 0x9EE1FA
    if not (manifest_pc or manifest_obj_x_helper_pc):
        raise RuntimeError(
            "valid-mailbox control requires the proven manifest call graph, "
            f"observed SA-1 PC ${sa1_pc:06X}"
        )
    patches = (
        (
            EARLY_CAMERA_NMI_ENTRY_OFFSET,
            EARLY_CAMERA_NMI_ENTRY_OLD,
            EARLY_CAMERA_NMI_ENTRY_LAB,
            "$E9:CF00-$CF03",
        ),
        (
            EARLY_CAMERA_NMI_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_NMI_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_NMI_HELPER_LAB,
            "$E9:DA20-$DA3D",
        ),
        (
            EARLY_CAMERA_BATCH_ENTRY_OFFSET,
            EARLY_CAMERA_BATCH_ENTRY_OLD,
            EARLY_CAMERA_BATCH_ENTRY_LAB,
            "$E9:DA40-$DA43",
        ),
        (
            EARLY_CAMERA_BATCH_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_BATCH_HELPER_LAB,
            "$E9:DA80-$DA9D",
        ),
    )
    interventions: list[dict[str, Any]] = []
    for address, expected, replacement, region in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"valid-mailbox control expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        if bytes(m.read_memory("snesPrgRom", address, len(replacement))) != replacement:
            raise RuntimeError(f"valid-mailbox control did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_camera_mailbox_valid_control_code",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": "consume one A5 camera publication without local seen state",
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )
    raw_camera = bytes(m.read_memory("Sa1Memory", 0x413489, 1))
    prior_mailbox = bytes(m.read_memory("Sa1Memory", 0x410162, 2))
    replacement = raw_camera + bytes((0xA5,))
    m.write_memory("Sa1Memory", 0x410162, replacement.hex())
    if bytes(m.read_memory("Sa1Memory", 0x410162, 2)) != replacement:
        raise RuntimeError("valid-mailbox control seed did not verify")
    interventions.append(
        {
            "kind": "checkpoint_camera_mailbox_valid_control_seed",
            "memory_type": "Sa1Memory",
            "region": "$41:0162-$0163",
            "sa1_pc": f"0x{sa1_pc:06X}",
            "original": prior_mailbox.hex(),
            "replacement": replacement.hex(),
            "raw_camera": raw_camera[0],
            "reason": "publish one stable camera sample with an A5 valid marker",
            "meaning": "runtime diagnostic intervention; never acceptance evidence",
        }
    )
    return interventions


def early_camera_valid_mailbox_lab(m: McpSession) -> list[dict[str, Any]]:
    """Install the complete raw-camera/A5 producer-consumer lab."""

    interventions = camera_mailbox_valid_control_lab(m)
    patches = (
        (
            EARLY_CAMERA_MANIFEST_CALL_OFFSET,
            EARLY_CAMERA_MANIFEST_CALL_OLD,
            EARLY_CAMERA_MANIFEST_CALL_LAB,
            "$99:FB3F-$FB42",
        ),
        (
            EARLY_CAMERA_SA1_HELPER_OFFSET,
            bytes(len(CAMERA_MAILBOX_VALID_SA1_HELPER_LAB)),
            CAMERA_MAILBOX_VALID_SA1_HELPER_LAB,
            "$99:FBC5-$FBDA",
        ),
    )
    for address, expected, replacement, region in patches:
        observed = bytes(m.read_memory("snesPrgRom", address, len(expected)))
        if observed != expected:
            raise RuntimeError(
                f"valid-mailbox producer expected {region}={expected.hex()}, "
                f"observed {observed.hex()}"
            )
        m.write_memory("snesPrgRom", address, replacement.hex())
        if bytes(m.read_memory("snesPrgRom", address, len(replacement))) != replacement:
            raise RuntimeError(f"valid-mailbox producer did not verify at {region}")
        interventions.append(
            {
                "kind": "checkpoint_early_camera_valid_mailbox_producer",
                "memory_type": "snesPrgRom",
                "file_offset": f"0x{address:06X}",
                "region": region,
                "original": expected.hex(),
                "replacement": replacement.hex(),
                "reason": "publish the stable camera before each private manifest build",
                "meaning": "runtime diagnostic intervention; never acceptance evidence",
            }
        )
    return interventions


def initialize_basis9_from_coherent_map(
    m: McpSession, row: dict[str, Any]
) -> list[dict[str, Any]]:
    """Seed successor nine-bit BG state from an older coherent exact image."""

    if not coherent_idle(row):
        raise RuntimeError(
            "nine-bit basis migration requires idle queues and equal generations"
        )
    if row["displayed_map_valid"] != 0xA5:
        raise RuntimeError("nine-bit basis migration requires a valid displayed map")
    if row["bg_column_kind"] >= 0xFFFE:
        raise RuntimeError("nine-bit basis migration requires an exact X1 map")
    if row["bg_column_map_applied"] != row["displayed_column_map"]:
        raise RuntimeError(
            "nine-bit basis migration requires accepted/displayed map equality"
        )
    column_map = bytes.fromhex(row["displayed_column_map"])
    if len(column_map) != 16:
        raise RuntimeError("nine-bit basis migration decoded a non-16-byte map")
    direct_phase = int(row["obj_cache_scrollx"]) & 0xFF
    raw_column4 = (int(row["scroll_packed"]) >> 8) & 0xFF
    raw_column4 |= ((int(row["bg_column_kind"]) >> 4) & 1) << 8
    basis = (column_map[4] * 32 + direct_phase - raw_column4) & 0x1FF
    presented_phase = (
        0x40 + basis - (int(row["bg1_hscroll"]) & 0x1FF)
    ) & 0x1FF
    if (presented_phase & 0xFF) != (int(row["presented_scrollx"]) & 0xFF):
        raise RuntimeError(
            "nine-bit basis migration cannot reconcile PPU HScroll with the "
            "serialized presented-camera byte"
        )

    def unwrap(low: int, anchor: int) -> int:
        delta = ((low - (anchor & 0xFF) + 0x80) & 0xFF) - 0x80
        return (anchor + delta) & 0x1FF

    latest_phase = unwrap(int(row["latest_scrollx"]) & 0xFF, direct_phase)
    primary_phase = unwrap(int(row["obj_queue_scrollx"]) & 0xFF, direct_phase)
    secondary_phase = unwrap(
        int(row["obj_queue2_scrollx"]) & 0xFF, direct_phase
    )
    words = (
        basis,
        basis,
        latest_phase,
        presented_phase,
        direct_phase,
        primary_phase,
        secondary_phase,
    )
    encoded = b"".join(value.to_bytes(2, "little") for value in words)
    m.write_memory("snesWorkRam", 0x71A4, encoded.hex())
    if bytes(m.read_memory("snesWorkRam", 0x71A4, len(encoded))) != encoded:
        raise RuntimeError("nine-bit basis migration did not verify")
    return [
        {
            "kind": "checkpoint_initialize_basis9_from_coherent_map",
            "memory_type": "snesWorkRam",
            "region": "$7E:71A4-$71B1",
            "basis": basis,
            "slot4": column_map[4],
            "paired_phase": direct_phase,
            "paired_raw_column4": raw_column4,
            "latest_phase": latest_phase,
            "presented_phase": presented_phase,
            "primary_phase": primary_phase,
            "secondary_phase": secondary_phase,
            "reason": "initialize successor-only state absent from predecessor checkpoint",
            "meaning": "cross-ROM diagnostic intervention; never acceptance evidence",
        }
    ]


def main() -> int:
    args = parse_args()
    if (
        args.frames <= 0
        or args.checkpoint_step <= 0
        or args.coherent_idle_settle_frames < 0
        or args.max_render_hold_frames <= 0
        or args.visual_grace_frames < 0
        or args.max_vertical_black_run < 0
    ):
        raise SystemExit("invalid frame count")
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    if (
        args.reserve_bg_slot_zero_migration
        and args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit("select only one BG slot-zero migration strategy")
    if (
        args.reserve_bg_slot_zero_migration
        or args.shift_bg_slots_for_reserved_zero
    ) and not args.refresh_video_mirror:
        raise SystemExit("BG slot migration requires --refresh-video-mirror")
    if args.legacy_full_bg_map_update and not args.refresh_video_mirror:
        raise SystemExit("legacy full BG map lab requires --refresh-video-mirror")
    if args.initialize_basis9_from_coherent_map and not args.refresh_video_mirror:
        raise SystemExit("nine-bit basis migration requires --refresh-video-mirror")
    if args.freeze_exact_bg_map and args.legacy_full_bg_map_update:
        raise SystemExit("select only one BG map-policy intervention")
    pacing_labs = sum(
        int(selected)
        for selected in (
            args.disable_sa1_deadline_irq_lab,
            args.early_quiescent_camera_lab,
            args.early_camera_mailbox_lab,
            args.camera_mailbox_seed_control_lab,
            args.camera_mailbox_nmi_control_lab,
            args.camera_mailbox_valid_control_lab,
            args.early_camera_valid_mailbox_lab,
        )
    )
    if pacing_labs > 1:
        raise SystemExit("select only one pacing-order intervention")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    configure_dotnet(args.emulator)
    rom = args.rom.resolve()
    rom_bytes = rom.read_bytes()
    if len(rom_bytes) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    idle_streak = 0
    settled_idle_reached = False
    parked_tick: int | None = None
    render_hold_frames = 0
    max_render_hold_frames = 0
    temporal_failure: dict[str, Any] | None = None
    visual_failures: list[dict[str, Any]] = []
    refresh_precondition: dict[str, Any] | None = None
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.refresh_video_mirror or args.freeze_exact_bg_map:
            refresh_precondition = capture.snapshot(m)
            if not renderer_quiescent(refresh_precondition):
                raise RuntimeError(
                    "refusing renderer code intervention while the renderer is "
                    "active or queued: "
                    f"busy={refresh_precondition['renderer_busy']}, "
                    f"primary={refresh_precondition['render_queue_primary']}, "
                    f"secondary={refresh_precondition['render_queue_secondary']}"
                )
        if args.park_sa1_at_current_pc:
            parked_tick = capture.snapshot(m)["tick"]
            interventions.append(
                capture.park_sa1_at_current_pc(
                    m,
                    "retain the drained checkpoint producer park during the forced rebuild",
                )
            )
        if args.refresh_video_mirror:
            interventions.extend(
                apply_checkpoint_migration(
                    m,
                    rom_bytes,
                    args.reserve_bg_slot_zero_migration,
                    args.shift_bg_slots_for_reserved_zero,
                )
            )
        if args.initialize_basis9_from_coherent_map:
            assert refresh_precondition is not None
            interventions.extend(
                initialize_basis9_from_coherent_map(m, refresh_precondition)
            )
        if args.legacy_full_bg_map_update:
            interventions.extend(apply_legacy_full_bg_map_update(m))
        if args.freeze_exact_bg_map:
            interventions.extend(apply_freeze_exact_bg_map(m))
        if args.disable_sa1_deadline_irq_lab:
            interventions.extend(disable_sa1_deadline_irq_lab(m))
        if args.early_quiescent_camera_lab:
            interventions.extend(early_quiescent_camera_lab(m))
        if args.early_camera_mailbox_lab:
            interventions.extend(early_camera_mailbox_lab(m))
        if args.camera_mailbox_seed_control_lab:
            interventions.extend(camera_mailbox_seed_control_lab(m))
        if args.camera_mailbox_nmi_control_lab:
            interventions.extend(camera_mailbox_nmi_control_lab(m))
        if args.camera_mailbox_valid_control_lab:
            interventions.extend(camera_mailbox_valid_control_lab(m))
        if args.early_camera_valid_mailbox_lab:
            interventions.extend(early_camera_valid_mailbox_lab(m))

        for relative in range(args.frames + 1):
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            if parked_tick is not None and row["tick"] != parked_tick:
                raise RuntimeError(
                    "SA-1 producer park failed: "
                    f"tick changed from {parked_tick} to {row['tick']} "
                    f"at relative frame {relative}"
                )
            screenshot_path = output / f"frame-{relative:06d}.png"
            row["screenshot"] = capture.take_screenshot(m, screenshot_path)
            row["image_metrics"] = image_metrics(screenshot_path)
            if (
                relative >= args.visual_grace_frames
                and row["image_metrics"]["max_vertical_black_run"]
                > args.max_vertical_black_run
            ):
                visual_failures.append(
                    {
                        "kind": "vertical_black_band",
                        "relative_frame": relative,
                        "value": row["image_metrics"]["max_vertical_black_run"],
                        "maximum": args.max_vertical_black_run,
                    }
                )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
            if len(rows) > 1:
                if row["render_complete"] == rows[-2]["render_complete"]:
                    render_hold_frames += 1
                else:
                    render_hold_frames = 0
                max_render_hold_frames = max(
                    max_render_hold_frames, render_hold_frames
                )
                if (
                    parked_tick is None
                    and render_hold_frames > args.max_render_hold_frames
                ):
                    temporal_failure = {
                        "kind": "render_complete_stall",
                        "relative_frame": relative,
                        "render_complete": row["render_complete"],
                        "consecutive_held_video_frame_transitions": render_hold_frames,
                        "limit": args.max_render_hold_frames,
                    }
                    break
            if args.stop_at_coherent_idle and relative > 0:
                if coherent_idle(row):
                    idle_streak += 1
                else:
                    idle_streak = 0
                if idle_streak > args.coherent_idle_settle_frames:
                    row["checkpoint"] = capture.save_checkpoint(
                        m, output / "coherent-idle.mss"
                    )
                    settled_idle_reached = True
                    break
            if relative == args.frames:
                break
            before = int(m.get_state().get("frameCount", 0))
            responses = [m.set_input(BUTTONS[args.buttons], 1)]
            m.pause()
            after = int(m.get_state().get("frameCount", 0))
            if after == before:
                # Legacy Mesen can accept a one-frame neutral hold without
                # advancing while paused.  The mask is already installed; use
                # the frame-step primitive and retain both responses.
                responses.append(m.run_frames(1))
                m.pause()
                after = int(m.get_state().get("frameCount", 0))
            row["next_input_step"] = {
                "before_video_frame": before,
                "after_video_frame": after,
                "video_frames_advanced": after - before,
                "responses": responses,
            }
            if after - before != 1:
                raise RuntimeError(
                    "direct framebuffer input step did not advance exactly one "
                    f"video frame at relative frame {relative}: "
                    f"before={before}, after={after}, responses={responses}"
                )
        # The emulator is paused and will now shut down; no additional frame
        # can observe the held mask, so a synthetic release frame is omitted.

    visual_failure_ranges: list[list[int]] = []
    for failure in visual_failures:
        relative = int(failure["relative_frame"])
        if visual_failure_ranges and relative == visual_failure_ranges[-1][1] + 1:
            visual_failure_ranges[-1][1] = relative
        else:
            visual_failure_ranges.append([relative, relative])
    input_failure = controller_input_failure(rows, BUTTONS[args.buttons])
    completed_requested_span = len(rows) == args.frames + 1
    coverage = {
        "game_tick_start": rows[0]["tick"],
        "game_tick_end": rows[-1]["tick"],
        "sample_video_frame_start": rows[0]["frame"],
        "sample_video_frame_end": rows[-1]["frame"],
        "sample_count": len(rows),
        "consecutive_video_frames": all(
            int(current["frame"]) - int(previous["frame"]) == 1
            for previous, current in zip(rows, rows[1:])
        ),
        "complete": bool(
            temporal_failure is None
            and (completed_requested_span or settled_idle_reached)
        ),
    }
    acceptance_gate = unknown_diagnostic_gate(
        "direct_framebuffer_capture",
        "Consecutive checkpoint sampling is not fresh-boot or visual correctness.",
    )
    acceptance_gate["rom_sha256"] = sha256(rom)
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "obj_temporal_capture": True,
        "scope": (
            "checkpointed direct-controller input-step framebuffer sampling; "
            "not fresh boot, FPS, aligned MAME pixels, or aggregate green"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": BUTTONS[args.buttons],
        "requested_frame_ceiling": args.frames,
        "max_render_hold_frames_limit": args.max_render_hold_frames,
        "max_render_hold_frames_observed": max_render_hold_frames,
        "temporal_validation": {
            "status": "red" if temporal_failure is not None else "green",
            "failure": temporal_failure,
            "meaning": (
                "bounded renderer liveness only; not visual correctness or "
                "aggregate gameplay acceptance"
            ),
        },
        "input_validation": {
            "status": "red" if input_failure is not None else "green",
            "failure": input_failure,
        },
        "visual_validation": {
            "status": "red" if visual_failures else "unknown",
            "vertical_black_band_failures": visual_failures,
            "vertical_black_band_ranges": visual_failure_ranges,
            "visual_grace_frames": args.visual_grace_frames,
            "max_vertical_black_run": args.max_vertical_black_run,
            "meaning": (
                "bounded vertical-band regression only; a clear scan remains "
                "UNKNOWN for aggregate visual correctness"
            ),
        },
        "refresh_precondition": refresh_precondition,
        "coherent_idle_settle_frames": args.coherent_idle_settle_frames,
        "final_coherent_idle_streak": idle_streak,
        "stopped_at_coherent_idle": settled_idle_reached,
        "runtime_memory_writes": interventions,
        "coverage": coverage,
        "start_video_frame": rows[0]["frame"],
        "end_video_frame": rows[-1]["frame"],
        "captures": rows,
        "acceptance_gate": acceptance_gate,
    }
    target = output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": (
                    "failed"
                    if temporal_failure is not None or visual_failures or input_failure
                    else "captured"
                ),
                "frames": len(rows),
                "start_video_frame": rows[0]["frame"],
                "end_video_frame": rows[-1]["frame"],
                "start_tick": rows[0]["tick"],
                "end_tick": rows[-1]["tick"],
                "report": str(target),
            },
            sort_keys=True,
        )
    )
    return 2 if temporal_failure is not None or visual_failures or input_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
