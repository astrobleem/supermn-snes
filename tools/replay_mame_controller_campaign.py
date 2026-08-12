#!/usr/bin/env python3
"""Replay the retained MAME controller movie from a fresh SNES power-on.

The arcade movie is not replayed by SNES video-frame number.  Its controller
transitions are keyed to the original game's update stream, then applied at
the same pre-body ``$003A92`` update entry in MAME and Nexen.  Nexen's native
debugger stops synchronously before that SA-1 instruction executes, so even a
slow Stage 3 changes elapsed SNES video time without shortening controller
holds in game time or coalescing pending-IRQ updates.

This is an organic controller-path diagnostic.  It never changes the ROM file
or game work RAM.  The exact game-update stop uses the native SA-1 entry while
the translation gate is armed and the matching rising IRAM virtual-PC edge
when the selected ROM has already disabled that gate.  Either stop is nested
inside an in-flight main SNES opcode and is therefore forensic-only.  Resumable recovery states are
accepted only after rendezvousing to the next main-SNES pre-opcode boundary,
when synchronous capture leaves the live machine unchanged and a fresh Nexen
process restores and continues without a CPU or memory transplant.  The
campaign retains cold-boot/title/start evidence, checks
task-stack floors and liveness, compares player state at every MAME input
transition, and checks the retained Stage 1-3 boss-health sequence.  Focused
opcode-boundary three-way tools remain the authority for registers, CCR/X,
stack residue, and complete mapped-work comparisons after a discrepancy is
identified.
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
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from mame_0287 import MAME
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_TIMELINE = EVIDENCE / "full-playback-timeline-v1" / "timeline.jsonl"
DEFAULT_BOSS_FIXTURES = EVIDENCE / "boss-health-stage123-fixtures-v3" / "fixtures.json"
DEFAULT_MAME_ORIGIN_WORK = (
    EVIDENCE
    / "gameplay-origin-mame-220-223-v1"
    / "mame-tick-00221.work.bin"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-safe-checkpoint-publish/Nexen"
)
MAME_MOVIE = ROOT / "inp" / "superman_play.inp"

# The two compatibility exceptions predate additions confined to the campaign
# harness, not to the serialized machine.  `64d...` produced the accepted
# fresh native-on a976 root through its tick-14,743 safe state; later changes
# added the native-off IRAM-PC stop and honest partial-prefix reporting, neither
# of which changes the native-on `$92:DB82` continuation.  `d68...` immediately
# preceded the audited post-divergence continuation fix.  Their pre-divergence
# controller scheduling, checkpoint format, MAME/Nexen identities, and all
# emulation inputs are unchanged.  Keeping this finite allowlist is
# intentionally different from accepting arbitrary runner drift: every other
# identity field (and every other runner hash) remains an exact resume gate.
# `0b731...` produced the current e00f fresh/checkpoint lineage.  Its only
# successor change teaches the harness to replay a controller edge that occurs
# exactly at `resume_mame_tick`; the serialized machine and all earlier input
# scheduling are unchanged.  `da9f...` adds that edge fix and produced the
# retained e00f comparisons immediately before the live-gate origin stopper
# learned to use the already-established IRAM edge when a selected ROM has
# disabled `$071A`; neither change mutates a serialized checkpoint.
# `4763...` is the first fresh run with that live-gate selector; subsequent
# edits only retain the predecessor hashes and clarify provenance wording.
# `889...` produced the first audited interpreted safe-checkpoint lineage.
# `bd6...` adds a terminal snapshot to failed interpreted entry waits but does
# not alter emulator state, controller scheduling, or checkpoint contents.
# `2030...` produced the green paced-VTIME lineage through tick 6,500.  Its
# successor only guards a zero-entry event batch when the resume tick itself is
# a controller edge; it changes neither the serialized parent state nor the
# input schedule represented by that state.
RESUME_COMPATIBLE_CAMPAIGN_SCRIPT_SHA256S = frozenset(
    {
        "64d43359d189bf6f34e69bdc7d9deb6fc5eab8f56a73642a43549f4dc77d5a1b",
        "d68aad155123ccda2d405119d43771a06215684f12af7313868111e18b88ed5c",
        "0b731603e466e2c433ba6ec1c9fd705b574d42c2cf89d2777c2132ffaf7016a9",
        "da9f120aa46067c01841122f5055524c02e0d3d4da20ae04522a8ab40ed67974",
        "4763a2a1ff648ad1de682bd5b6cca406c07a8c8974ba5ac8ff7eede2e2bdb734",
        "889e1b2ba99489f40c4a00d7e11235dbcd23bc5e6244a87df9325ecf00be8062",
        "bd6ace3df65ad56cb0cdd7b4578a39bcbdf315f936611abc5e83099acd75107f",
        "2030c2135c724b172670f4322630bbaa9112ef3e941e64dc478d8d1043e179a6",
        "efdb1da62e85e8f20e7f55d95014faed324ac8f47618981f4f93f4c4dd43e426",
    }
)

sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


class AuditedMcpSession(McpSession):
    """Record direct architectural mutations issued by a harness."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.architectural_mutations: list[dict[str, Any]] = []

    def tool(self, name: str, args: dict | None = None) -> Any:
        if name in {"write_memory", "set_cpu_state"}:
            self.architectural_mutations.append(
                {
                    "tool": name,
                    "arguments": dict(args or {}),
                }
            )
        return super().tool(name, args)


PLAYER_A6 = 0xF01302
PLAYER_BASE = 0x400000 | ((PLAYER_A6 - 0x60) & 0xFFFF)
TASK_CONTEXT_START = 0x40000A
TASK_FLOOR_START = 0xC10882
TICK_IRAM = 0x0760
TICK_POST_WRITE = 0x00F5A6
TICK_POST_WRITE_ROM_OFFSET = 0x0075A6
TICK_POST_WRITE_ORIGINAL = bytes.fromhex("1860")  # CLC; RTS
TICK_POST_WRITE_STABLE = bytes.fromhex("80fe")  # BRA -2
TICK_RELEASE_EQUIVALENT = 0x00F5C0
TICK_RELEASE_ROM_OFFSET = 0x0075C0
HALT_IRAM = 0x004E
PLAYER_HEALTH_LOW = 0x4012B5
MAME_FRAME_TO_TICK = 75
# Exact-stop occurrence batches stay deliberately small.  The MCP debugger's
# per-occurrence bookkeeping grows on this ROM; batches near 240 can exceed
# the transport timeout even though the underlying game remains live.
MAX_TICK_HOOK_STEP = 32
RUN_UNTIL_CHUNK_FRAMES = 600
MIN_TICK_VIDEO_FRAME_BUDGET = 600
VIDEO_FRAME_BUDGET_PER_TICK = 64
STACK_WINDOW_RADIUS = 32


def generated_native_symbol(path: Path, bank: int, label: str) -> int:
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == label:
            return (bank << 16) | (
                int(fields[0].split(":")[-1], 16) & 0xFFFF
            )
    raise RuntimeError(f"{path}: missing symbol {label}")


ENTRY_3A92_NATIVE = generated_native_symbol(
    ROOT / "src/escbank.sym", 0x92, "entry_3a92"
)
INTERPRETER_HALT_SPIN = generated_native_symbol(
    ROOT / "src/interp.sym", 0x00, "ispin"
)
# With the translated gameplay root disabled, the native entry above is
# intentionally unreachable.  Nexen's IRAM edge stop exposes the equivalent
# rising virtual-PC boundary before the interpreted $003A92 body executes.
M68K_PC_IRAM = 0x0040
M68K_GAME_UPDATE_ENTRY = 0x00003A92
INTERPRETED_ENTRY_EDGE_MAX_BATCH = 8
INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY = 256

BUTTON_NAMES = (
    (McpSession.BTN_A, "a"),
    (McpSession.BTN_B, "b"),
    (McpSession.BTN_SELECT, "select"),
    (McpSession.BTN_START, "start"),
    (McpSession.BTN_UP, "up"),
    (McpSession.BTN_DOWN, "down"),
    (McpSession.BTN_LEFT, "left"),
    (McpSession.BTN_RIGHT, "right"),
)

# The byte at A6-$23 is the arcade player's top-level action state.  The
# controller movie reaches every value below organically.  Keep the names
# deliberately narrow: states 3/4/5 are phases of the observed crate-pickup
# sequence, while idle, walking, and directional flight all share state zero
# and are distinguished by position/input evidence rather than guessed labels.
ACTION_NAMES = {
    0: "movement_or_idle",
    1: "button1_attack",
    2: "button2_kick",
    3: "crate_pickup_phase_1",
    4: "crate_pickup_phase_3",
    5: "crate_pickup_phase_2",
    7: "crate_throw",
    8: "player_hurt",
    9: "death_respawn_or_transition",
    10: "crate_carried",
}


@dataclass(frozen=True)
class InputEvent:
    tick: int
    buttons: int
    reference: dict[str, Any]


@dataclass(frozen=True)
class BossEvent:
    tick: int
    name: str
    stage: int
    record: int
    expected_health: int
    kind: str
    frame: int


_ACTIVE_SESSION: McpSession | None = None
_ACTIVE_STATE_DIR: Path | None = None
_ACTIVE_SHOT_DIR: Path | None = None


class CampaignFailure(RuntimeError):
    def __init__(self, classification: str, detail: dict[str, Any]):
        super().__init__(classification)
        self.classification = classification
        self.detail = dict(detail)
        # Capture while the context-managed emulator is still alive.  The
        # outer campaign handler runs after McpSession.__exit__, which is too
        # late to ask the server for the exact failure boundary.
        if (
            _ACTIVE_SESSION is not None
            and _ACTIVE_STATE_DIR is not None
            and _ACTIVE_SHOT_DIR is not None
        ):
            try:
                state_path = _ACTIVE_STATE_DIR / "failure.mss"
                shot_path = _ACTIVE_SHOT_DIR / "failure.png"
                self.detail["state"] = save_state(_ACTIVE_SESSION, state_path)
                self.detail["screenshot"] = screenshot(
                    _ACTIVE_SESSION, shot_path
                )
            except Exception as capture_error:
                self.detail["capture_error"] = repr(capture_error)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--boss-fixtures", type=Path, default=DEFAULT_BOSS_FIXTURES)
    parser.add_argument(
        "--mame-origin-work",
        type=Path,
        default=DEFAULT_MAME_ORIGIN_WORK,
        help=(
            "exact 64 KiB MAME work-RAM oracle at --mame-origin-tick; "
            "$F01C62 credit lineage must match before differential replay"
        ),
    )
    parser.add_argument("--mesen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument(
        "--resume-source-dependencies",
        type=Path,
        help=(
            "authenticated historical Nexen Dependencies.zip used only for "
            "cross-ROM checkpoint resume identity; the executable and managed "
            "assembly still come from --mesen"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--resume-state",
        type=Path,
        help=(
            "Continue from a retained post-entry safe campaign checkpoint "
            "instead of power-on; exact SA-1 entry states are rejected. "
            "Requires --resume-mame-tick and --resume-lineage-events"
        ),
    )
    parser.add_argument(
        "--resume-mame-tick",
        type=int,
        help="MAME tick represented by --resume-state",
    )
    parser.add_argument(
        "--resume-lineage-events",
        type=Path,
        help=(
            "events.jsonl that proves --resume-state came from a fresh-power-on "
            "campaign of this exact ROM"
        ),
    )
    parser.add_argument(
        "--allow-resume-rom-migration",
        action="store_true",
        help=(
            "focused diagnostic only: authenticate the checkpoint against its "
            "original fresh-boot ROM, then continue under a different selected "
            "ROM while retaining both hashes; never fresh-boot proof"
        ),
    )
    parser.add_argument(
        "--migrate-vtime-irq-clock",
        action="store_true",
        help=(
            "cross-ROM diagnostic only: derive the candidate-private VTIME "
            "IRQ interval phase from the authenticated predecessor checkpoint "
            "and write only $40401C-$40401F before resume"
        ),
    )
    parser.add_argument("--port", type=int, default=9230)
    parser.add_argument("--mame-origin-tick", type=int, default=221)
    parser.add_argument(
        "--mame-end-tick",
        type=int,
        default=61000,
        help="Arcade movie tick to reach (61000 is just beyond the Stage 3 boss).",
    )
    parser.add_argument(
        "--input-apply-delay-entries",
        type=int,
        choices=(0, 1),
        default=0,
        help=(
            "diagnostic controller-latch timing: apply a movie transition "
            "at T (default) or after one additional $3A92 entry (T+1)"
        ),
    )
    parser.add_argument(
        "--retain-input-prestate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "At each applied controller transition, retain the latest paused "
            "pre-input save state; at an observed discrepancy immediately copy "
            "it to a named immutable pre-failure state. Diagnostic evidence is kept off "
            "by default because synchronous state writes add replay cost."
        ),
    )
    parser.add_argument(
        "--retain-input-prestate-tick",
        type=int,
        action="append",
        default=[],
        metavar="MAME_TICK",
        help=(
            "Retain the paused state immediately before applying only the "
            "specified movie input transition. Unlike --retain-input-prestate, "
            "this avoids synchronous saves at every transition while still "
            "preserving a deterministic pre-failure state. May be repeated."
        ),
    )
    parser.add_argument(
        "--cold-boot-frame",
        type=int,
        default=5248,
        help=(
            "video frame at which to insert the first credit; 5248 matches "
            "the retained MAME movie's deterministic gameplay-origin RNG"
        ),
    )
    parser.add_argument(
        "--retain-boot-screen-frame",
        type=int,
        action="append",
        default=[],
        metavar="VIDEO_FRAME",
        help=(
            "during a fresh power-on prefix, retain a screenshot at this "
            "pre-credit video frame; may be repeated"
        ),
    )
    parser.add_argument(
        "--expected-origin-rng",
        type=lambda value: int(value, 0),
        default=0x00C8,
        help=(
            "required $F0170E RNG state at the first fresh gameplay "
            "boundary (default: retained MAME tick-221 value 0x00c8)"
        ),
    )
    parser.add_argument(
        "--coin-pulses",
        type=int,
        default=8,
        help=(
            "separate Select/coin edges before Start; eight reproduces the "
            "retained MAME movie's seven-credit gameplay origin"
        ),
    )
    parser.add_argument(
        "--coin-frames",
        type=int,
        default=4,
        help="video frames to hold Select for each separate coin pulse",
    )
    parser.add_argument(
        "--coin-gap-frames",
        type=int,
        default=4,
        help="neutral video frames between separate coin pulses",
    )
    parser.add_argument(
        "--credited-wait-frames",
        type=int,
        default=155,
        help=(
            "neutral frames after the last coin; defaults preserve the prior "
            "215-frame coin-to-Start interval and origin RNG"
        ),
    )
    parser.add_argument(
        "--start-frames",
        type=int,
        default=61,
        help=(
            "exact Start hold before the gameplay-spawn hook; 61 preserves "
            "the retained MAME-aligned power-on sequence"
        ),
    )
    parser.add_argument(
        "--spawn-timeout-frames",
        type=int,
        default=1200,
        help=(
            "legacy option name: maximum exact game-update entries to inspect "
            "for the organic player-spawn health initialization"
        ),
    )
    parser.add_argument(
        "--sample-ticks",
        type=int,
        default=250,
        help="Detailed liveness/task/renderer sample interval in MAME ticks.",
    )
    parser.add_argument(
        "--checkpoint-ticks",
        type=int,
        default=1000,
        help="Retained recovery-state interval in MAME ticks.",
    )
    parser.add_argument(
        "--strict-player-reference",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require health/X/Y/action equality at every MAME input transition.",
    )
    parser.add_argument(
        "--allow-incomplete-coverage",
        action="store_true",
        help=(
            "focused-prefix diagnostic only: retain and report missing "
            "controller/action/boss/death coverage instead of failing the "
            "completion gate; result is partial-green only if no oracle "
            "divergence is observed, never a full campaign claim"
        ),
    )
    parser.add_argument(
        "--gameplay-native",
        choices=("on", "off"),
        default="on",
        help=(
            "run the post-origin controller campaign with the ordinary "
            "gameplay native gates enabled (default) or disabled for the "
            "required interpreter/native three-way differential"
        ),
    )
    parser.add_argument(
        "--diagnose-snes-exec-address",
        type=lambda value: int(value, 0),
        help=(
            "focused post-origin diagnostic: synchronously stop before the "
            "first S-CPU execution of this exact 24-bit address, retain a "
            "compact live snapshot, and end without running the controller "
            "campaign; accepts decimal or 0x-prefixed input"
        ),
    )
    parser.add_argument(
        "--diagnose-snes-exec-max-frames",
        type=int,
        default=3000,
        help=(
            "video-frame budget for --diagnose-snes-exec-address "
            "(default: 3000)"
        ),
    )
    parser.add_argument(
        "--diagnose-snes-trace-tail",
        type=int,
        default=0,
        help=(
            "with --diagnose-snes-exec-address, enable Nexen's S-CPU trace "
            "ring at the authenticated origin and retain this many final "
            "instructions in a separate JSON artifact (default: disabled; "
            "maximum: 1000)"
        ),
    )
    parser.add_argument(
        "--diagnose-snes-call-stack",
        action="store_true",
        help=(
            "with --diagnose-snes-exec-address, retain Nexen's existing "
            "debugger call stack at the exact stop; requires a diagnostic "
            "Nexen build exposing the read-only get_call_stack MCP tool"
        ),
    )
    parser.add_argument(
        "--continue-oracle-divergences",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Log player/death/respawn/boss oracle mismatches and continue so "
            "later organic-path coverage can be collected.  Halts, invalid "
            "task stacks, and renderer stalls remain fatal.  Results after "
            "the first mismatch are coverage evidence, not exact-state proof."
        ),
    )
    parser.add_argument(
        "--progress-events",
        type=int,
        default=250,
        help="Print progress after this many processed controller transitions.",
    )
    parser.add_argument(
        "--retain-boundary-state",
        type=int,
        action="append",
        default=[],
        metavar="MAME_TICK",
        help=(
            "Retain an additional save state at this exact movie-tick "
            "boundary; may be repeated to preserve a pre-failure state."
        ),
    )
    parser.add_argument(
        "--safe-checkpoint-tick",
        type=int,
        action="append",
        default=[],
        metavar="MAME_TICK",
        help=(
            "After completing this exact movie-tick entry, rendezvous to the "
            "next main-SNES pre-opcode boundary and retain a resumable "
            "checkpoint. May be repeated."
        ),
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("MAME timeline", args.timeline),
        ("boss fixtures", args.boss_fixtures),
        ("MAME origin work RAM", args.mame_origin_work),
        ("emulator", args.mesen),
        ("MAME movie", MAME_MOVIE),
        ("MAME", MAME),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if any(tick < args.mame_origin_tick for tick in args.retain_input_prestate_tick):
        parser.error(
            "--retain-input-prestate-tick must not precede --mame-origin-tick"
        )
    resume_values = (
        args.resume_state,
        args.resume_mame_tick,
        args.resume_lineage_events,
    )
    if any(value is not None for value in resume_values) and not all(
        value is not None for value in resume_values
    ):
        parser.error(
            "--resume-state, --resume-mame-tick, and "
            "--resume-lineage-events must be supplied together"
        )
    if args.resume_state is not None:
        for label, path in (
            ("resume state", args.resume_state),
            ("resume lineage event log", args.resume_lineage_events),
        ):
            if not path.is_file():
                parser.error(f"missing {label}: {path}")
        if not (
            args.mame_origin_tick
            <= args.resume_mame_tick
            < args.mame_end_tick
        ):
            parser.error(
                "--resume-mame-tick must be within the requested movie range"
            )
        if args.retain_boot_screen_frame:
            parser.error(
                "--retain-boot-screen-frame is valid only for fresh power-on"
            )
    elif args.allow_resume_rom_migration:
        parser.error("--allow-resume-rom-migration requires --resume-state")
    if (
        args.resume_source_dependencies is not None
        and not args.allow_resume_rom_migration
    ):
        parser.error(
            "--resume-source-dependencies requires "
            "--allow-resume-rom-migration"
        )
    if (
        args.resume_source_dependencies is not None
        and not args.resume_source_dependencies.is_file()
    ):
        parser.error(
            "missing resume source dependencies: "
            f"{args.resume_source_dependencies}"
        )
    if (
        args.migrate_vtime_irq_clock
        and not args.allow_resume_rom_migration
    ):
        parser.error(
            "--migrate-vtime-irq-clock requires "
            "--allow-resume-rom-migration"
        )
    if args.mame_end_tick <= args.mame_origin_tick:
        parser.error("--mame-end-tick must be greater than --mame-origin-tick")
    if args.mame_origin_work.stat().st_size != 0x10000:
        parser.error("MAME origin work RAM must be exactly 64 KiB")
    if not 0 <= args.expected_origin_rng <= 0xFFFF:
        parser.error("--expected-origin-rng must be in 0..0xffff")
    invalid_boundaries = [
        tick
        for tick in (
            list(args.retain_boundary_state)
            + list(args.safe_checkpoint_tick)
        )
        if not args.mame_origin_tick <= tick <= args.mame_end_tick
    ]
    if invalid_boundaries:
        parser.error(
            "--retain-boundary-state values must be within the requested "
            f"movie range: {invalid_boundaries}"
        )
    for value in (
        args.cold_boot_frame,
        args.coin_pulses,
        args.coin_frames,
        args.start_frames,
        args.spawn_timeout_frames,
        args.sample_ticks,
        args.checkpoint_ticks,
        args.progress_events,
    ):
        if value <= 0:
            parser.error("frame/tick intervals must be positive")
    if args.coin_gap_frames < 0 or args.credited_wait_frames < 0:
        parser.error("coin gap and credited wait frames cannot be negative")
    invalid_boot_screens = [
        frame
        for frame in args.retain_boot_screen_frame
        if not 0 < frame < args.cold_boot_frame
    ]
    if invalid_boot_screens:
        parser.error(
            "--retain-boot-screen-frame values must be positive and precede "
            f"--cold-boot-frame: {invalid_boot_screens}"
        )
    return args


def configure_dotnet(emulator: Path) -> None:
    # The exact Mesen wrapper owns a .NET 8 binary; current Nexen owns .NET 10.
    dotnet = (
        "/home/chad/.dotnet8"
        if emulator.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )
    other = (
        "/home/chad/.dotnet10"
        if dotnet.endswith("dotnet8")
        else "/home/chad/.dotnet8"
    )
    os.environ["DOTNET_ROOT"] = dotnet
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet, other)
    ]
    os.environ["PATH"] = ":".join([dotnet, other, *current])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def nexen_identity(
    executable: Path,
    source_dependencies_override: Path | None = None,
) -> dict[str, Any]:
    """Identify managed MCP code and its embedded native core."""
    executable = executable.resolve()
    identity: dict[str, Any] = {
        "executable": str(executable),
        "apphost_sha256": sha256(executable),
    }
    managed = executable.with_name("Nexen.dll")
    if not managed.is_file():
        raise RuntimeError(f"Nexen managed assembly is missing: {managed}")
    identity.update(
        {
            "managed_assembly": str(managed),
            "managed_assembly_sha256": sha256(managed),
        }
    )
    deps = executable.with_name("Nexen.deps.json")
    if deps.is_file():
        identity.update(
            {
                "deps_manifest": str(deps),
                "deps_manifest_sha256": sha256(deps),
            }
        )
    source_dependencies = (
        source_dependencies_override.resolve()
        if source_dependencies_override is not None
        else next(
            (
                parent / "UI" / "Dependencies.zip"
                for parent in executable.parents
                if (parent / "UI" / "Dependencies.zip").is_file()
            ),
            None,
        )
    )
    if source_dependencies is not None:
        with zipfile.ZipFile(source_dependencies) as archive:
            native_core = archive.read("NexenCore.so")
        identity.update(
            {
                "source_dependencies_zip": str(source_dependencies),
                "source_dependencies_zip_sha256": sha256(
                    source_dependencies
                ),
                "embedded_native_core_member": "NexenCore.so",
                "embedded_native_core_sha256": digest(native_core),
            }
        )
    return identity


VIDEO_WRAM_ROM_OFFSET = 0x298000
VIDEO_WRAM_WORK_OFFSET = 0x18000
VIDEO_WRAM_CPU_ADDRESS = 0x7F8000
VIDEO_WRAM_LENGTH = 0x3000
VTIME_STATE_CPU_ADDRESS = 0x404000
VTIME_STATE_LENGTH = 0x20
VTIME_MAGIC = 0xC71E
VTIME_VALID = 0x0001
VTIME_CLOCK_PHASE_OFFSET = 0x1C
VTIME_CLOCK_VALID_OFFSET = 0x1E
VTIME_CLOCK_VALID_VALUE = 0x5A17
VTIME_BASE_UNITS = 69_650
VTIME_FRACTION_INCREMENT = 50
VTIME_FRACTION_DENOMINATOR = 5_743
VTIME_CLOCK_INITIAL_BUCKET = 1


def refresh_video_wram(
    m: McpSession,
    rom: Path,
) -> dict[str, Any]:
    """Reapply rc_copy to executable WRAM in a retained checkpoint.

    A save state serializes the $7F:8000-$AFFF supervisor/renderer mirror, so
    loading it with a newer ROM does not by itself exercise newer code in that
    window. This is a checkpoint-only, reset-equivalent code migration. It
    deliberately does not alter game RAM or claim fresh-boot coverage.
    """

    rom_data = rom.read_bytes()
    end = VIDEO_WRAM_ROM_OFFSET + VIDEO_WRAM_LENGTH
    if len(rom_data) < end:
        raise RuntimeError(
            f"ROM is too short for video WRAM source: {len(rom_data):#x} < {end:#x}"
        )
    source = rom_data[VIDEO_WRAM_ROM_OFFSET:end]
    before = bytes(
        m.read_memory(
            "snesWorkRam",
            VIDEO_WRAM_WORK_OFFSET,
            VIDEO_WRAM_LENGTH,
        )
    )
    differing = [
        index
        for index, (old, new) in enumerate(zip(before, source, strict=True))
        if old != new
    ]
    cpu = m.get_cpu_state("Snes")
    cpu_pc = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
    pc_offset = cpu_pc - VIDEO_WRAM_CPU_ADDRESS
    if any(pc_offset - 4 <= index <= pc_offset + 4 for index in differing):
        raise RuntimeError(
            "refusing to refresh changed video WRAM around the paused "
            f"5A22 instruction: PC={cpu_pc:#08x}"
        )
    for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
        chunk = source[offset : offset + 0x1000]
        m.write_memory(
            "snesWorkRam",
            VIDEO_WRAM_WORK_OFFSET + offset,
            chunk.hex(),
        )
    after = bytes(
        m.read_memory(
            "snesWorkRam",
            VIDEO_WRAM_WORK_OFFSET,
            VIDEO_WRAM_LENGTH,
        )
    )
    if after != source:
        raise RuntimeError("video WRAM refresh did not read back exactly")
    return {
        "kind": "checkpoint_video_wram_code_refresh",
        "reset_equivalent": "rc_copy",
        "fresh_boot_proof": False,
        "rom_file_offset": f"{VIDEO_WRAM_ROM_OFFSET:06X}",
        "cpu_address": f"{VIDEO_WRAM_CPU_ADDRESS:06X}",
        "work_ram_offset": f"{VIDEO_WRAM_WORK_OFFSET:05X}",
        "length": VIDEO_WRAM_LENGTH,
        "paused_snes_pc": f"{cpu_pc:06X}",
        "differing_bytes": len(differing),
        "first_differing_offsets": differing[:64],
        "before_sha256": digest(before),
        "after_sha256": digest(after),
        "rom_source_sha256": digest(source),
    }


def derive_vtime_interval_clock(
    fractional_phase: int,
    remain_units: int,
) -> dict[str, int]:
    """Derive the candidate-private modulo-5 interval clock from old VTIME state."""

    if not 0 <= fractional_phase < VTIME_FRACTION_DENOMINATOR:
        raise RuntimeError(
            f"invalid predecessor VTIME fractional phase: {fractional_phase}"
        )
    phase = 0
    interval_extra = 0
    interval_start_bucket = VTIME_CLOCK_INITIAL_BUCKET
    reloads = 0
    while phase != fractional_phase:
        interval_start_bucket = (
            interval_start_bucket + interval_extra
        ) % 5
        phase += VTIME_FRACTION_INCREMENT
        if phase >= VTIME_FRACTION_DENOMINATOR:
            phase -= VTIME_FRACTION_DENOMINATOR
            interval_extra = 1
        else:
            interval_extra = 0
        reloads += 1
        if reloads > VTIME_FRACTION_DENOMINATOR:
            raise RuntimeError(
                "predecessor VTIME fractional phase is unreachable"
            )
    interval_units = VTIME_BASE_UNITS + interval_extra
    if not 0 <= remain_units <= interval_units:
        raise RuntimeError(
            "predecessor VTIME remaining countdown is outside its interval: "
            f"remain={remain_units}, interval={interval_units}"
        )
    completed_bucket = (
        interval_start_bucket + interval_units - remain_units
    ) % 5
    encoded = interval_start_bucket | (0x8000 if interval_extra else 0)
    return {
        "fractional_phase": fractional_phase,
        "remain_units": remain_units,
        "reloads_mod_5743": reloads,
        "interval_extra_unit": interval_extra,
        "interval_start_bucket": interval_start_bucket,
        "completed_phase_bucket": completed_bucket,
        "encoded_interval_clock": encoded,
    }


def migrate_vtime_irq_clock(m: McpSession) -> dict[str, Any]:
    """Initialize only the new diagnostic IRQ-clock words in an old checkpoint."""

    before = bytes(
        m.read_memory(
            "snesMemory", VTIME_STATE_CPU_ADDRESS, VTIME_STATE_LENGTH
        )
    )
    if len(before) != VTIME_STATE_LENGTH:
        raise RuntimeError("short predecessor VTIME state read")

    def word(offset: int) -> int:
        return int.from_bytes(before[offset : offset + 2], "little")

    checks = {
        "predecessor_magic": word(0x00) == VTIME_MAGIC,
        "predecessor_valid": word(0x02) == VTIME_VALID,
        "deadline_not_due": word(0x18) == 0,
        "overshoot_clear": word(0x0C) == 0,
        "candidate_clock_uninitialized": (
            word(VTIME_CLOCK_PHASE_OFFSET) == 0
            and word(VTIME_CLOCK_VALID_OFFSET) == 0
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(
            f"checkpoint is not eligible for VTIME clock migration: {checks}"
        )
    remain_units = word(0x06) | (word(0x08) << 16)
    derived = derive_vtime_interval_clock(word(0x0A), remain_units)
    payload = (
        int(derived["encoded_interval_clock"]).to_bytes(2, "little")
        + VTIME_CLOCK_VALID_VALUE.to_bytes(2, "little")
    )
    m.write_memory(
        "snesMemory",
        VTIME_STATE_CPU_ADDRESS + VTIME_CLOCK_PHASE_OFFSET,
        payload.hex(),
    )
    after = bytes(
        m.read_memory(
            "snesMemory", VTIME_STATE_CPU_ADDRESS, VTIME_STATE_LENGTH
        )
    )
    expected = bytearray(before)
    expected[
        VTIME_CLOCK_PHASE_OFFSET : VTIME_CLOCK_VALID_OFFSET + 2
    ] = payload
    if after != bytes(expected):
        raise RuntimeError("VTIME clock migration changed undeclared state")
    return {
        "kind": "checkpoint_vtime_irq_clock_initialization",
        "diagnostic_only": True,
        "fresh_boot_proof": False,
        "game_state_write": False,
        "cpu_state_write": False,
        "memory_type": "snesMemory",
        "cpu_address": f"{VTIME_STATE_CPU_ADDRESS + VTIME_CLOCK_PHASE_OFFSET:06X}",
        "length": len(payload),
        "before_sha256": digest(before),
        "after_sha256": digest(after),
        "payload_sha256": digest(payload),
        "checks": checks,
        "derived": derived,
    }


def compact_architectural_mutations(
    mutations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Describe audited writes without copying their large hex bodies."""

    compact: list[dict[str, Any]] = []
    for mutation in mutations:
        arguments = mutation.get("arguments", {})
        hex_data = str(arguments.get("hex", ""))
        try:
            raw = bytes.fromhex(hex_data)
        except ValueError:
            raw = b""
        compact.append(
            {
                "tool": mutation.get("tool"),
                "memory_type": arguments.get("memoryType"),
                "address": arguments.get("address"),
                "length": len(raw),
                "sha256": digest(raw),
            }
        )
    return compact


def validate_video_wram_migration(
    *,
    before_public: dict[str, Any],
    before_raw: tuple[bytes, ...],
    after_public: dict[str, Any],
    after_raw: tuple[bytes, ...],
    selected_rom: Path,
    refresh: dict[str, Any],
    mutations: list[dict[str, Any]],
    vtime_clock_migration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove a migration changed only declared code/private timing state."""

    source = selected_rom.read_bytes()[
        VIDEO_WRAM_ROM_OFFSET : VIDEO_WRAM_ROM_OFFSET + VIDEO_WRAM_LENGTH
    ]
    expected_wram = bytearray(before_raw[2])
    expected_wram[
        VIDEO_WRAM_WORK_OFFSET : VIDEO_WRAM_WORK_OFFSET + VIDEO_WRAM_LENGTH
    ] = source
    expected_work = bytearray(before_raw[1])
    if vtime_clock_migration is not None:
        clock_offset = (
            VTIME_STATE_CPU_ADDRESS - 0x400000 + VTIME_CLOCK_PHASE_OFFSET
        )
        clock_payload = (
            int(
                vtime_clock_migration["derived"]["encoded_interval_clock"]
            ).to_bytes(2, "little")
            + VTIME_CLOCK_VALID_VALUE.to_bytes(2, "little")
        )
        expected_work[clock_offset : clock_offset + len(clock_payload)] = (
            clock_payload
        )
    compact_mutations = compact_architectural_mutations(mutations)
    expected_mutations = [
        {
            "tool": "write_memory",
            "memory_type": "snesWorkRam",
            "address": VIDEO_WRAM_WORK_OFFSET + offset,
            "length": len(source[offset : offset + 0x1000]),
            "sha256": digest(source[offset : offset + 0x1000]),
        }
        for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000)
    ]
    if vtime_clock_migration is not None:
        expected_mutations.append(
            {
                "tool": "write_memory",
                "memory_type": "snesMemory",
                "address": (
                    VTIME_STATE_CPU_ADDRESS + VTIME_CLOCK_PHASE_OFFSET
                ),
                "length": len(clock_payload),
                "sha256": digest(clock_payload),
            }
        )
    changed_public_keys = {"wram_128k_sha256"}
    if vtime_clock_migration is not None:
        changed_public_keys.add("work_64k_sha256")
    unchanged_public_keys = set(before_public) - changed_public_keys
    checks = {
        "selected_rom_source_complete": len(source) == VIDEO_WRAM_LENGTH,
        "refresh_source_matches_selected_rom": (
            refresh.get("rom_source_sha256") == digest(source)
        ),
        "refresh_readback_matches_selected_rom": (
            refresh.get("after_sha256") == digest(source)
        ),
        "audited_writes_exact": compact_mutations == expected_mutations,
        "cpu_ppu_frame_and_other_hashes_unchanged": all(
            before_public[key] == after_public.get(key)
            for key in unchanged_public_keys
        ),
        "all_undeclared_memory_domains_unchanged": all(
            before_raw[index] == after_raw[index]
            for index in range(len(before_raw))
            if index not in ({1, 2} if vtime_clock_migration is not None else {2})
        ),
        "work_ram_exactly_old_state_plus_vtime_clock": (
            after_raw[1] == bytes(expected_work)
        ),
        "wram_exactly_old_state_plus_selected_code": (
            after_raw[2] == bytes(expected_wram)
        ),
        "published_work_hash_exact": (
            after_public.get("work_64k_sha256")
            == digest(bytes(expected_work))
        ),
        "published_wram_hash_exact": (
            after_public.get("wram_128k_sha256") == digest(bytes(expected_wram))
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(
            "cross-ROM checkpoint migration changed state outside the "
            f"declared video-WRAM refresh: {checks}"
        )
    return {
        "kind": "verified_checkpoint_video_wram_code_migration",
        "diagnostic_only": True,
        "fresh_boot_proof": False,
        "game_state_write": False,
        "cpu_state_write": False,
        "checks": checks,
        "refresh": refresh,
        "vtime_clock_migration": vtime_clock_migration,
        "architectural_mutations": compact_mutations,
    }


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


def button_label(mask: int) -> str:
    names = [name for bit, name in BUTTON_NAMES if mask & bit]
    return "+".join(names) if names else "none"


def load_timeline(
    path: Path, origin_tick: int, end_tick: int
) -> tuple[list[InputEvent], dict[int, dict[str, Any]]]:
    tick_rows: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            tick = int(row.get("tick", -1))
            if tick < origin_tick or tick > end_tick:
                continue
            if row.get("event") == "tick":
                pc = int(row.get("pc", -1))
                boundary_kind = row.get("boundary_kind")
                if not 0x003A92 <= pc <= 0x003AB0 or boundary_kind not in (
                    None,
                    "tick_start_3a92",
                ):
                    raise RuntimeError(
                        f"timeline tick {tick} is not a MAME $3A92 "
                        f"tick-start boundary: pc={pc:06X}, "
                        f"boundary={boundary_kind!r}"
                    )
                if tick in tick_rows:
                    raise RuntimeError(
                        f"timeline has duplicate tick-start {tick}"
                    )
                tick_rows[tick] = row
    if origin_tick not in tick_rows:
        raise RuntimeError(f"timeline lacks origin tick {origin_tick}")
    missing = sorted(set(range(origin_tick, end_tick + 1)) - set(tick_rows))
    if missing:
        preview = missing[:16]
        raise RuntimeError(
            f"timeline lacks {len(missing)} tick-start rows; "
            f"first missing: {preview}"
        )
    # The exporter's separate `input` rows are emitted from frame_done after
    # the next game update can already have changed player state.  Their tick
    # labels are therefore not a uniform architectural boundary.  Derive
    # physical controller transitions from the exact $3A92 tick-start rows.
    inputs: list[InputEvent] = []
    previous_buttons = int(tick_rows[origin_tick]["snes_buttons"])
    for tick in sorted(tick_rows):
        if tick <= origin_tick:
            continue
        row = tick_rows[tick]
        buttons = int(row["snes_buttons"])
        if buttons != previous_buttons:
            inputs.append(InputEvent(tick, buttons, row))
            previous_buttons = buttons
    # A focused window may legitimately contain only a held controller mask.
    # Keep the per-tick rows as the authority and return an empty transition
    # list; callers still authenticate the origin row and can advance the
    # requested interval without fabricating an input edge.
    return inputs, tick_rows


def load_boss_events(path: Path, end_tick: int) -> list[BossEvent]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    answer: list[BossEvent] = []
    for row in manifest["cases"]:
        stage = int(row["stage"])
        if stage not in (1, 2, 3):
            continue
        tick = int(row["frame"]) - MAME_FRAME_TO_TICK
        if tick > end_tick:
            continue
        answer.append(
            BossEvent(
                tick=tick,
                name=str(row["name"]),
                stage=stage,
                record=int(str(row["record"]), 16),
                expected_health=int(row["expected_after"]) & 0xFFFF,
                kind=str(row["kind"]),
                frame=int(row["frame"]),
            )
        )
    return sorted(answer, key=lambda item: (item.tick, item.name))


def wait_for_file(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def require_paused(m: McpSession, context: str) -> dict[str, Any]:
    """Require an already-stopped emulator without issuing a step-like pause."""
    state = dict(m.get_state())
    if state.get("isPaused") is not True:
        raise RuntimeError(f"{context}: Nexen is not paused: {state}")
    return state


def pause_for_startup(m: McpSession) -> dict[str, Any] | None:
    """Pause only the uncontrolled startup run, then verify the request."""
    if bool(m.get_state().get("isPaused")):
        return None
    response = dict(m.pause())
    require_paused(m, "startup pause")
    return response


def checkpoint_machine_snapshot(
    m: McpSession,
) -> tuple[dict[str, Any], tuple[bytes, ...]]:
    """Capture complete MCP-visible checkpoint state while already paused."""
    state = require_paused(m, "checkpoint snapshot")
    iram = bytes(m.read_memory("sa1Memory", 0, 0x800))
    work = bytes(m.read_memory("snesMemory", 0x400000, 0x10000))
    wram = b"".join(
        bytes(m.read_memory("snesWorkRam", offset, 0x10000))
        for offset in (0, 0x10000)
    )
    vram = bytes(m.read_memory("snesVideoRam", 0, 0x10000))
    cgram = bytes(m.read_memory("snesCgRam", 0, 0x200))
    oam = bytes(m.read_memory("snesSpriteRam", 0, 0x220))
    spc_ram = bytes(m.read_memory("spcMemory", 0, 0x10000))
    public = {
        "sa1": dict(m.get_cpu_state("Sa1")),
        "snes": dict(m.get_cpu_state("Snes")),
        "frame_count": int(state.get("frameCount", 0)),
        "ppu": dict(m.get_ppu_state()),
        "sa1_iram_sha256": digest(iram),
        "work_64k_sha256": digest(work),
        "wram_128k_sha256": digest(wram),
        "vram_64k_sha256": digest(vram),
        "cgram_512_sha256": digest(cgram),
        "oam_544_sha256": digest(oam),
        "spc_ram_64k_sha256": digest(spc_ram),
    }
    return public, (iram, work, wram, vram, cgram, oam, spc_ram)


def nested_game_update_entry_route(current_pc: int, iram: bytes) -> str | None:
    """Classify native and interpreted exact stops nested in the S-CPU run."""

    if current_pc == ENTRY_3A92_NATIVE:
        return "native_sa1"
    if len(iram) >= 0x71C:
        virtual_pc = le32(iram[M68K_PC_IRAM : M68K_PC_IRAM + 4]) & 0xFFFFFF
        xlat = le16(iram[0x071A:0x071C])
        if xlat == 0 and virtual_pc == M68K_GAME_UPDATE_ENTRY:
            return "interpreted_iram"
    return None


def install_game_update_reentry_hook(
    m: McpSession, route: str
) -> dict[str, Any]:
    """Watch for a second GAME_TICK while rendezvousing off its entry."""

    if route == "native":
        address = ENTRY_3A92_NATIVE
        handle = m.add_exec_hook(address, cpu_type="Sa1")
        return {
            "handle": handle,
            "route": route,
            "kind": "sa1_exec_native_3a92",
            "address": address,
            "match_value": None,
            "match_value_mask": 0,
        }
    if route == "interpreted":
        # The exact IRAM stopper has already observed the low-byte write that
        # made virtual PC $003A92.  A later matching write to $0040 therefore
        # means another interpreted GAME_TICK began before the S-CPU reached
        # its safe architectural boundary.
        address = M68K_PC_IRAM
        match_value = M68K_GAME_UPDATE_ENTRY & 0xFF
        handle = m.add_write_hook(
            address,
            cpu_type="Sa1",
            match_value=match_value,
            match_value_mask=0xFF,
        )
        return {
            "handle": handle,
            "route": route,
            "kind": "sa1_write_iram_pc_low_92",
            "address": address,
            "match_value": match_value,
            "match_value_mask": 0xFF,
        }
    raise RuntimeError(f"unsupported safe-checkpoint route: {route}")


def save_state(
    m: McpSession,
    path: Path,
    *,
    boundary_kind: str | None = None,
    post_entry_safe_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_public, before_raw = checkpoint_machine_snapshot(m)
    cpu = before_public["sa1"]
    current_pc = (
        ((int(cpu.get("k", 0)) & 0xFF) << 16)
        | (int(cpu.get("pc", 0)) & 0xFFFF)
    )
    observed_entry_route = nested_game_update_entry_route(
        current_pc, before_raw[0]
    )
    nested_entry_route = observed_entry_route
    at_nested_game_update_entry = observed_entry_route is not None
    if boundary_kind is None:
        if observed_entry_route == "native_sa1":
            boundary_kind = "sa1_exact_entry_nested_forensic"
        elif observed_entry_route == "interpreted_iram":
            boundary_kind = "iram_exact_entry_nested_forensic"
        else:
            boundary_kind = "ordinary_paused_boundary"
    resumable_checkpoint = (
        boundary_kind == "post_entry_safe_snes_boundary"
    )
    if resumable_checkpoint and observed_entry_route == "native_sa1":
        raise RuntimeError(
            "refusing to label a native exact-entry stop as a resumable "
            f"post-entry S-CPU boundary: sa1_pc={current_pc:06X}"
        )
    if resumable_checkpoint and observed_entry_route == "interpreted_iram":
        proof_checks = {
            "proof_present": isinstance(post_entry_safe_proof, dict),
            "interpreted_route": (
                isinstance(post_entry_safe_proof, dict)
                and post_entry_safe_proof.get("route") == "interpreted"
            ),
            "boundary_pc": (
                isinstance(post_entry_safe_proof, dict)
                and int(post_entry_safe_proof.get("boundary_sa1_pc", -1))
                == current_pc
            ),
            "left_exact_stop_pc": (
                isinstance(post_entry_safe_proof, dict)
                and int(post_entry_safe_proof.get("source_sa1_pc", -1))
                != current_pc
            ),
            "rendezvous_checks": (
                isinstance(post_entry_safe_proof, dict)
                and bool(post_entry_safe_proof.get("rendezvous_checks"))
                and all(
                    bool(value)
                    for value in post_entry_safe_proof[
                        "rendezvous_checks"
                    ].values()
                )
            ),
        }
        if not all(proof_checks.values()):
            raise RuntimeError(
                "refusing to label an interpreted $003A92 virtual-PC "
                "state as post-entry safe without exact-stop removal and "
                f"SA-1 progress proof: checks={proof_checks}, "
                f"sa1_pc={current_pc:06X}"
            )
        # The interpreter can still expose virtual PC $003A92 while already
        # executing its body.  Once the exact stop has been removed, the SA-1
        # has advanced away from the stop PC, no second entry fired, and the
        # S-CPU reached its next pre-opcode boundary, this is not a nested
        # debugger-entry state.
        at_nested_game_update_entry = False
        nested_entry_route = None
    # Nexen normally returns completion metadata.  A dense exact-entry trace
    # can instead return only the requested path after the file has already
    # been fully written (the MCP response itself is lost while the server is
    # draining the hook queue).  Never issue a burst of retry saves here: that
    # wedges the MCP socket and turns a valid cold boot into EBADF.  We accept
    # a unique, stable, non-empty file while retaining the weaker response
    # contract explicitly in the evidence below.
    response = dict(m.save_state(path.resolve()))
    response_complete = (
        response.get("completed") is True
        and response.get("atomicRename") is True
        and path.is_file()
        and int(response.get("size", -1)) == path.stat().st_size
    )
    client_observed_stable_file = False
    if not response_complete and path.is_file():
        stable_deadline = time.monotonic() + 2.0
        previous_size = -1
        while time.monotonic() < stable_deadline:
            size = path.stat().st_size
            if size > 0 and size == previous_size:
                client_observed_stable_file = True
                response = {
                    **response,
                    "path": str(path.resolve()),
                    "completed": True,
                    "size": size,
                    "atomicRename": False,
                    "clientObservedStableFile": True,
                }
                break
            previous_size = size
            time.sleep(0.05)
    response_complete = response_complete or client_observed_stable_file
    if (
        not response_complete
        or not path.is_file()
        or int(response.get("size", -1)) != path.stat().st_size
    ):
        raise RuntimeError(
            f"save-state write was not synchronously completed: {response}"
        )
    after_public, after_raw = checkpoint_machine_snapshot(m)
    if after_public != before_public or after_raw != before_raw:
        raise RuntimeError(
            "save-state capture mutated the live paused machine: "
            f"public_equal={after_public == before_public}, "
            f"memory_equal={after_raw == before_raw}"
        )
    result = {
        "path": str(path),
        "sha256": sha256(path),
        "response": response,
        "synchronous_completed": True,
        "atomic_rename": response.get("atomicRename") is True,
        "response_contract": (
            "client_observed_stable_file"
            if client_observed_stable_file
            else "server_completion_metadata"
        ),
        "active_run_reloaded": False,
        "active_run_memory_restored": False,
        "live_state_unchanged": True,
        "boundary_kind": boundary_kind,
        "entry_exact_bundle": at_nested_game_update_entry,
        "nested_sa1_entry_nonresumable": at_nested_game_update_entry,
        "nested_game_update_entry_route": nested_entry_route,
        "observed_game_update_entry_route": observed_entry_route,
        "post_entry_safe_proof": post_entry_safe_proof,
        "resumable_checkpoint": resumable_checkpoint,
    }
    if not at_nested_game_update_entry and not resumable_checkpoint:
        return result

    required_cpu_keys = (
        "pc",
        "k",
        "a",
        "x",
        "y",
        "sp",
        "d",
        "dbr",
        "ps",
        "cycleCount",
        "emulationMode",
        "nmiFlagCounter",
        "irqLock",
        "needNmi",
        "irqSource",
        "prevIrqSource",
        "stopStateValue",
    )
    for cpu_name in ("sa1", "snes"):
        missing = [
            key
            for key in required_cpu_keys
            if key not in before_public[cpu_name]
        ]
        if missing:
            raise RuntimeError(
                "checkpoint CPU API lacks exact interrupt state for "
                f"{cpu_name}: {missing}"
            )
    iram_path = path.with_suffix(path.suffix + ".sa1-iram.bin")
    iram_path.write_bytes(before_raw[0])
    result.update(
        {
            "resume_sa1_state": {
                "cpuType": "Sa1",
                **{key: cpu[key] for key in required_cpu_keys},
            },
            "resume_sa1_iram": {
                "path": str(iram_path.resolve()),
                "sha256": sha256(iram_path),
                "size": iram_path.stat().st_size,
            },
            "resume_validation": before_public,
        }
    )
    return result


def safe_checkpoint_rendezvous(
    m: McpSession,
    path: Path,
    *,
    mame_tick: int,
    current_buttons: int,
) -> dict[str, Any]:
    """Complete the interrupted SNES opcode and save at its next boundary."""

    require_paused(m, "safe checkpoint source")
    gate = active_game_update_gate(m)
    route = str(gate["mode"])
    if not at_active_game_update_entry(m, route):
        raise RuntimeError(
            "safe checkpoint source is not the active exact $003A92 "
            f"entry: route={route}, gate={gate}, sa1_pc={sa1_pc(m):06X}"
        )
    before_public, _before_raw = checkpoint_machine_snapshot(m)
    before_tick = tick16(m)
    source_sa1_pc = sa1_pc(m)
    hook_spec = install_game_update_reentry_hook(m, route)
    hook = int(hook_spec["handle"])
    m.drain_notifications(timeout=0.05)
    response: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    try:
        response = dict(
            m.tool(
                "run_to_next_cpu_boundary",
                {"cpuType": "Snes", "maxFrames": 60},
            )
        )
        rows = list(m.drain_notifications(timeout=0.1))
    finally:
        m.remove_hook(hook)
        rows.extend(m.drain_notifications(timeout=0.05))

    require_paused(m, "safe checkpoint rendezvous")
    if response is None:
        raise RuntimeError("safe checkpoint rendezvous returned no response")
    entry_hits = [
        row
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
        and int(row.get("params", {}).get("handle", -1)) == hook
    ]
    after_public, _after_raw = checkpoint_machine_snapshot(m)
    after_sa1 = after_public["sa1"]
    boundary_sa1_pc = (
        ((int(after_sa1.get("k", 0)) & 0xFF) << 16)
        | (int(after_sa1.get("pc", 0)) & 0xFFFF)
    )
    after_snes = after_public["snes"]
    trigger_address = (
        ((int(after_snes.get("k", 0)) & 0xFF) << 16)
        | (int(after_snes.get("pc", 0)) & 0xFFFF)
    )
    checks = {
        "hit": response.get("hit") is True,
        "reason": response.get("reason") == "breakpoint",
        "cpu": str(response.get("cpuType", "")).lower() == "snes",
        "paused": response.get("isPaused") is True,
        "match_any": response.get("matchAnyAddress") is True,
        "zero_cycle_floor": int(response.get("cycleFloor", -1)) == 0,
        "one_occurrence": (
            int(response.get("requestedOccurrences", -1)) == 1
            and int(response.get("observedOccurrences", -1)) == 1
        ),
        "exact_stop_removed": response.get("exactStopRemoved") is True,
        "exact_stop_triggered": (
            response.get("exactStopTriggered") is True
        ),
        "break_delivered": (
            response.get("exactStopBreakDelivered") is True
        ),
        "trigger_address": (
            int(response.get("triggerAddress", -1)) == trigger_address
        ),
        "trigger_cycle": (
            int(response.get("triggerCycleCount", -1))
            == int(after_snes.get("cycleCount", -2))
        ),
        "response_cycle": (
            int(response.get("cycleCount", -1))
            == int(after_snes.get("cycleCount", -2))
        ),
        "response_frame": (
            int(response.get("endFrame", -1))
            == int(after_public["frame_count"])
        ),
        "snes_running": (
            str(after_snes.get("stopState", "")).lower() == "running"
            and int(after_snes.get("stopStateValue", -1)) == 0
        ),
        "sa1_left_exact_stop_pc": boundary_sa1_pc != source_sa1_pc,
        "zero_additional_game_update_entries": not entry_hits,
    }
    if not all(checks.values()):
        raise RuntimeError(
            "safe checkpoint rendezvous failed: "
            f"checks={checks}, response={response}, entry_hits={entry_hits}"
        )

    post_entry_safe_proof = {
        "route": route,
        "source_sa1_pc": source_sa1_pc,
        "boundary_sa1_pc": boundary_sa1_pc,
        "rendezvous_checks": checks,
    }
    saves = [
        save_state(
            m,
            path if index == 0 else path.with_name(
                f"{path.stem}.repeat-{index}{path.suffix}"
            ),
            boundary_kind="post_entry_safe_snes_boundary",
            post_entry_safe_proof=post_entry_safe_proof,
        )
        for index in range(3)
    ]
    save_hashes = [row["sha256"] for row in saves]
    if len(set(save_hashes)) != 1:
        raise RuntimeError(
            "safe checkpoint repeated saves are not byte-identical: "
            f"{save_hashes}"
        )
    return {
        "mame_tick_completed": mame_tick,
        "resume_mame_tick": mame_tick + 1,
        "current_buttons": current_buttons,
        "before_snes_tick": before_tick,
        "after_snes_tick": tick16(m),
        "before": before_public,
        "after": after_public,
        "rendezvous": response,
        "checks": checks,
        "entry_hook_handle": hook,
        "entry_hook_events": entry_hits,
        "entry_hook": {
            **hook_spec,
            "active_gate": gate,
        },
        "state": saves[0],
        "repeat_states": saves[1:],
        "repeat_save_hashes": save_hashes,
        "byte_identical_repeated_saves": True,
        "phase": "post_entry_safe_snes_boundary",
    }


def screenshot(m: McpSession, path: Path) -> dict[str, Any]:
    before_public, before_raw = checkpoint_machine_snapshot(m)
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), path)
    after_public, after_raw = checkpoint_machine_snapshot(m)
    if after_public != before_public or after_raw != before_raw:
        raise RuntimeError(
            "screenshot capture mutated the live paused machine: "
            f"public_equal={after_public == before_public}, "
            f"memory_equal={after_raw == before_raw}"
        )
    return {
        "path": str(path),
        "sha256": sha256(path),
        "response": response,
        "live_state_unchanged": True,
    }


def set_held_input(m: McpSession, buttons: int) -> dict[str, Any]:
    return m.tool(
        "set_input",
        {"port": 0, "buttons": buttons & 0x0FFF, "hold": True},
    )


def run_exact_frames(m: McpSession, buttons: int, frames: int) -> list[dict[str, Any]]:
    input_response = set_held_input(m, buttons)
    responses: list[dict[str, Any]] = []
    remaining = frames
    while remaining:
        before = int(m.get_state().get("frameCount", 0))
        requested = min(120, remaining)
        response = m.run_frames(requested)
        require_paused(m, "run_frames return")
        after = int(m.get_state().get("frameCount", 0))
        advanced = after - before
        responses.append(
            {
                "before": before,
                "after": after,
                "requested": requested,
                "advanced": advanced,
                "response": response,
                "input_response": input_response if not responses else None,
            }
        )
        # The IRAM-edge debugger variant can hit its wall-clock request limit
        # a few frames before a 120-frame request completes.  It still
        # returns a cleanly paused, integral video-frame boundary, so resume
        # from that exact boundary rather than discarding 116 already
        # executed frames and calling the result a game failure.  Zero or
        # overshot progress remains a real transport/hardware-boundary error.
        if (
            advanced <= 0
            or advanced > requested
            or response.get("isPaused") is not True
        ):
            raise CampaignFailure(
                "hardware-boundary/timing",
                {
                    "reason": "video_frame_advance_failed",
                    "buttons": buttons,
                    "remaining": remaining,
                    "response": response,
                    "before": before,
                    "after": after,
                },
            )
        responses[-1]["overshoot"] = 0
        responses[-1]["partial_timeout_resumed"] = bool(
            response.get("timedOut") is True and advanced < requested
        )
        remaining -= advanced
    return responses


def run_coin_pulses(
    m: McpSession,
    pulses: int,
    hold_frames: int,
    gap_frames: int,
) -> dict[str, Any]:
    """Insert distinct coin edges without changing memory behind the game."""
    pulse_runs: list[list[dict[str, Any]]] = []
    gap_runs: list[list[dict[str, Any]]] = []
    for index in range(pulses):
        pulse_runs.append(
            run_exact_frames(m, McpSession.BTN_SELECT, hold_frames)
        )
        if index + 1 < pulses and gap_frames:
            gap_runs.append(run_exact_frames(m, 0, gap_frames))
    return {
        "pulses": pulses,
        "hold_frames": hold_frames,
        "gap_frames": gap_frames,
        "total_frames": (
            pulses * hold_frames + max(0, pulses - 1) * gap_frames
        ),
        "pulse_runs": pulse_runs,
        "gap_runs": gap_runs,
    }


def tick16(m: McpSession) -> int:
    return le16(m.read_memory("Sa1Memory", TICK_IRAM, 2))


def halt16(m: McpSession) -> int:
    return le16(m.read_memory("Sa1Memory", HALT_IRAM, 2))


def game_update_wait_terminal_snapshot(
    m: McpSession, sa1_cpu: dict[str, Any]
) -> dict[str, Any]:
    """Capture the small live state needed to classify an entry timeout.

    This runs before the failure save-state path because SA-1 IRAM is not a
    trustworthy post-reload source for a nested debugger boundary.
    """

    try:
        iram = bytes(m.read_memory("Sa1Memory", 0x0000, 0x00B0))
        timer = bytes(m.read_memory("snesMemory", 0x404000, 0x001A))
        scheduler = bytes(m.read_memory("snesMemory", 0x400002, 4))
        snes_cpu = dict(m.get_cpu_state("Snes"))
        shared = bytes(m.read_memory("snesMemory", 0x410120, 0x32))
        request_ack = bytes(m.read_memory("snesMemory", 0x003300, 4))
        control = bytes(m.read_memory("snesMemory", 0x002200, 0x10))
        private = bytes(m.read_memory("snesWorkRam", 0x1F00, 0x20))
        stack = bytes(m.read_memory("snesWorkRam", 0x0100, 0x100))
        stack_pointer = int(snes_cpu.get("sp", 0)) & 0xFFFF
        interrupt_frame: dict[str, Any]
        if (
            snes_cpu.get("emulationMode") is False
            and 0x0100 <= stack_pointer <= 0x01FB
        ):
            frame_offset = stack_pointer - 0x0100 + 1
            saved = stack[frame_offset : frame_offset + 4]
            return_address = (
                (saved[3] << 16) | (saved[2] << 8) | saved[1]
            )
            prior_address = (
                (return_address & 0xFF0000)
                | ((return_address - 1) & 0xFFFF)
            )
            interrupt_frame = {
                "stack_pointer": stack_pointer,
                "saved_ps": saved[0],
                "return_address": return_address,
                "prior_address": prior_address,
                "prior_opcode": int(
                    m.read_memory("snesMemory", prior_address, 1)[0]
                ),
                "raw_hex": saved.hex(),
            }
        else:
            interrupt_frame = {
                "unavailable": True,
                "stack_pointer": stack_pointer,
                "emulation_mode": snes_cpu.get("emulationMode"),
            }
        return {
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "sa1_pc": (
                ((int(sa1_cpu.get("k", 0)) & 0xFF) << 16)
                | (int(sa1_cpu.get("pc", 0)) & 0xFFFF)
            ),
            "sa1_cycles": int(sa1_cpu.get("cycleCount", 0)),
            "m68k_pc": le32(iram[0x40:0x44]) & 0xFFFFFF,
            "m68k_opcode": le16(iram[0x44:0x46]),
            "interpreted_step_count": (
                le16(iram[0x4A:0x4C])
                | (le16(iram[0x4C:0x4E]) << 16)
            ),
            "halt": le16(iram[0x4E:0x50]),
            "tick_0760": le16(
                m.read_memory("Sa1Memory", TICK_IRAM, 2)
            ),
            "virtual_irq_pending_00aa": le16(iram[0xAA:0xAC]),
            "legacy_countdown_00ac": le16(iram[0xAC:0xAE]),
            "a5": le32(iram[0x34:0x38]),
            "a6": le32(iram[0x38:0x3C]),
            "a7": le32(iram[0x3C:0x40]),
            "task_mask_f00002": be16(scheduler[0:2]),
            "current_task_f00004": be16(scheduler[2:4]),
            "snes_cpu": snes_cpu,
            "snes_interrupt_frame": interrupt_frame,
            "snes_stack_0100_01ff_hex": stack.hex(),
            "shared_pacing": {
                "arm_410122": le16(shared[0x02:0x04]),
                "vblank_epoch_41012a": shared[0x0A],
                "last_release_epoch_41012b": shared[0x0B],
                "cadence_marker_41012c": shared[0x0C],
                "scpu_ready_41012d": shared[0x0D],
                "debt_410130": shared[0x10],
                "raw_hex": shared.hex(),
            },
            "request_ack": {
                "frame_request_3300": le16(request_ack[0:2]),
                "frame_ack_3302": le16(request_ack[2:4]),
                "raw_hex": request_ack.hex(),
            },
            "sa1_control_2200_220f_hex": control.hex(),
            "scpu_private_7e1f00_1f1f_hex": private.hex(),
            "vtime": {
                "magic": le16(timer[0x00:0x02]),
                "valid": le16(timer[0x02:0x04]),
                "cost": le16(timer[0x04:0x06]),
                "remain_lo": le16(timer[0x06:0x08]),
                "remain_hi": le16(timer[0x08:0x0A]),
                "phase": le16(timer[0x0A:0x0C]),
                "overshoot": le16(timer[0x0C:0x0E]),
                "opcode": le16(timer[0x0E:0x10]),
                "native_pending": le16(timer[0x14:0x16]),
                "native_current": le16(timer[0x16:0x18]),
                "due": le16(timer[0x18:0x1A]),
            },
        }
    except Exception as error:
        # Classification must retain the original exact-stop failure even if
        # an optional diagnostic memory domain is unavailable.
        return {"capture_error": repr(error)}


def _run_tick_span(
    m: McpSession,
    step: int,
    *,
    stabilize_post_write: bool,
) -> dict[str, Any]:
    """Run to one tick target, optionally stopping exactly after its write."""
    raise RuntimeError(
        "retired tick-span debugger path mutates runtime ROM; "
        "use run_game_update_entries()"
    )

    # Historical implementation retained below for forensic provenance only.
    if step <= 0 or step > MAX_TICK_HOOK_STEP:
        raise ValueError(f"invalid tick span: {step}")
    before_tick = tick16(m)
    target = (before_tick + step) & 0xFFFF
    before_frame = int(m.get_state().get("frameCount", 0))
    hook = m.add_write_hook(
        TICK_IRAM,
        cpu_type="Sa1",
        match_value=target & 0xFF,
        match_value_mask=0xFF,
    )
    stable_patch: dict[str, Any] | None = None
    if stabilize_post_write:
        original = bytes(
            m.read_memory(
                "snesPrgRom",
                TICK_POST_WRITE_ROM_OFFSET,
                len(TICK_POST_WRITE_ORIGINAL),
            )
        )
        if original != TICK_POST_WRITE_ORIGINAL:
            raise RuntimeError(
                "canonical post-tick seam changed: expected "
                f"{TICK_POST_WRITE_ORIGINAL.hex()} at ROM "
                f"{TICK_POST_WRITE_ROM_OFFSET:06X}, found {original.hex()}"
            )
        release = bytes(
            m.read_memory(
                "snesPrgRom",
                TICK_RELEASE_ROM_OFFSET,
                len(TICK_POST_WRITE_ORIGINAL),
            )
        )
        if release != TICK_POST_WRITE_ORIGINAL:
            raise RuntimeError(
                "equivalent exact-tick release seam changed: expected "
                f"{TICK_POST_WRITE_ORIGINAL.hex()} at ROM "
                f"{TICK_RELEASE_ROM_OFFSET:06X}, found {release.hex()}"
            )
        m.write_memory(
            "snesPrgRom",
            TICK_POST_WRITE_ROM_OFFSET,
            TICK_POST_WRITE_STABLE.hex(),
        )
        stable_patch = {
            "kind": "transient_debugger_exact_tick_stop",
            "address": f"{TICK_POST_WRITE:06X}",
            "rom_offset": f"{TICK_POST_WRITE_ROM_OFFSET:06X}",
            "before": TICK_POST_WRITE_ORIGINAL.hex(),
            "temporary": TICK_POST_WRITE_STABLE.hex(),
            "restored_before_observation": True,
        }
    m.drain_notifications(timeout=0.02)
    run_attempts: list[dict[str, Any]] = []
    frame_budget = max(
        MIN_TICK_VIDEO_FRAME_BUDGET,
        step * VIDEO_FRAME_BUDGET_PER_TICK
        + MIN_TICK_VIDEO_FRAME_BUDGET,
    )
    terminal_reason = "frame_budget"
    stable_cpu: dict[str, Any] | None = None
    release_cpu: dict[str, Any] | None = None
    release_response: dict[str, Any] | None = None
    try:
        while True:
            frames_used = (
                int(m.get_state().get("frameCount", 0))
                - before_frame
            )
            remaining_budget = frame_budget - frames_used
            if remaining_budget <= 0:
                break
            requested_frames = min(
                RUN_UNTIL_CHUNK_FRAMES,
                remaining_budget,
            )
            result = dict(
                m.run_until(
                    max_frames=requested_frames,
                    hook_handle=hook,
                )
            )
            require_paused(m, "tick-boundary run_until return")
            result["requestedMaxFrames"] = requested_frames
            run_attempts.append(result)
            current_tick = tick16(m)
            if result.get("reason") == "hookFired":
                terminal_reason = "hookFired"
                break
            # Nexen's run_until also has a real-time safety yield.  On a
            # heavily loaded SA-1 frame it reports that yield as "maxFrames"
            # even when fewer than the requested frames ran.  Continue under
            # the explicit cumulative video-frame bound.
            if current_tick == target:
                terminal_reason = "targetReachedAtYield"
                break
            tick_progress = (current_tick - before_tick) & 0xFFFF
            if tick_progress > step:
                terminal_reason = "tickOvershotTarget"
                break
            if result.get("reason") != "maxFrames":
                terminal_reason = str(result.get("reason", "unknown"))
                break
            if int(result.get("framesAdvanced", 0)) <= 0:
                terminal_reason = "noFrameProgress"
                break
        if stabilize_post_write:
            stable_cpu = dict(m.get_cpu_state("Sa1"))
    finally:
        m.remove_hook(hook)
        if stable_patch is not None:
            m.write_memory(
                "snesPrgRom",
                TICK_POST_WRITE_ROM_OFFSET,
                TICK_POST_WRITE_ORIGINAL.hex(),
            )
        m.drain_notifications(timeout=0.02)

    after_tick = tick16(m)
    if (
        stabilize_post_write
        and after_tick == target
        and stable_cpu is not None
        and int(stable_cpu.get("k", -1)) == 0
        and int(stable_cpu.get("pc", -1))
        == (TICK_POST_WRITE & 0xFFFF)
    ):
        # Nexen has already decoded the temporary BRA while paused.  Merely
        # restoring its ROM bytes leaves that decoded instruction live on
        # resume.  Redirect to the existing lh_nofire CLC;RTS pair instead:
        # it is instruction-, cycle-, flag-, stack-, and return-equivalent to
        # the original continuation, while forcing a clean opcode fetch.
        release_response = dict(
            m.tool(
                "set_cpu_state",
                {
                    "cpuType": "Sa1",
                    "k": 0,
                    "pc": TICK_RELEASE_EQUIVALENT & 0xFFFF,
                },
            )
        )
        release_cpu = dict(m.get_cpu_state("Sa1"))
    after_frame = int(m.get_state().get("frameCount", 0))
    result = {
        "reason": terminal_reason,
        "framesAdvanced": after_frame - before_frame,
        "isPaused": True,
        "frameBudget": frame_budget,
        "attempts": run_attempts,
    }
    event = {
        "before_tick": before_tick,
        "after_tick": after_tick,
        "target_tick": target,
        "tick_delta": step,
        "before_frame": before_frame,
        "after_frame": after_frame,
        "video_frames": after_frame - before_frame,
        "run": result,
        "exact_post_write_stop": stabilize_post_write,
    }
    if stable_patch is not None:
        event["stable_patch"] = stable_patch
        event["stable_cpu"] = stable_cpu
        event["equivalent_release"] = {
            "address": f"{TICK_RELEASE_EQUIVALENT:06X}",
            "rom_offset": f"{TICK_RELEASE_ROM_OFFSET:06X}",
            "opcode": TICK_POST_WRITE_ORIGINAL.hex(),
            "response": release_response,
            "cpu": release_cpu,
        }
    if terminal_reason not in ("hookFired", "targetReachedAtYield"):
        raise CampaignFailure(
            "hardware-boundary/timing",
            {"reason": "game_tick_timeout", "span": event},
        )
    if after_tick != target:
        raise CampaignFailure(
            "hardware-boundary/timing",
            {"reason": "game_tick_hook_overshoot", "span": event},
        )
    if stabilize_post_write and (
        stable_cpu is None
        or int(stable_cpu.get("k", -1)) != 0
        or int(stable_cpu.get("pc", -1)) != (TICK_POST_WRITE & 0xFFFF)
        or release_cpu is None
        or int(release_cpu.get("k", -1)) != 0
        or int(release_cpu.get("pc", -1))
        != (TICK_RELEASE_EQUIVALENT & 0xFFFF)
        or any(
            release_cpu.get(key) != stable_cpu.get(key)
            for key in (
                "a",
                "x",
                "y",
                "sp",
                "d",
                "dbr",
                "ps",
                "emulationMode",
                "cycleCount",
            )
        )
    ):
        raise CampaignFailure(
            "hardware-boundary/timing",
            {
                "reason": "exact_tick_stable_loop_not_observed",
                "span": event,
            },
        )
    if halt16(m):
        raise CampaignFailure(
            "interpreter_or_native_hle",
            {"reason": "interpreter_halt", "halt": halt16(m), "span": event},
        )
    return event


def run_tick_delta(m: McpSession, delta: int) -> list[dict[str, Any]]:
    """Advance exactly *delta* ticks and return at an exact post-write seam."""
    if delta < 0:
        raise ValueError("negative tick delta")
    events: list[dict[str, Any]] = []
    remaining = delta
    while remaining:
        step = min(remaining, MAX_TICK_HOOK_STEP)
        # The stabilizing instruction follows every tick write, so installing
        # it for a multi-tick span would stop at the first tick.  Run an
        # unobserved prefix first, then stabilize only the final boundary.
        if step > 1:
            events.append(
                _run_tick_span(
                    m,
                    step - 1,
                    stabilize_post_write=False,
                )
            )
        events.append(
            _run_tick_span(
                m,
                1,
                stabilize_post_write=True,
            )
        )
        remaining -= step
    return events


def sa1_pc(m: McpSession) -> int:
    state = m.get_cpu_state("Sa1")
    return (
        (int(state.get("k", 0)) & 0xFF) << 16
        | (int(state.get("pc", 0)) & 0xFFFF)
    )


def run_game_update_entries(
    m: McpSession,
    count: int,
    *,
    max_entries_per_chunk: int = MAX_TICK_HOOK_STEP,
    video_frame_budget_per_entry: int = VIDEO_FRAME_BUDGET_PER_TICK,
    minimum_frame_budget: int = MIN_TICK_VIDEO_FRAME_BUDGET,
) -> list[dict[str, Any]]:
    """Advance exactly *count* native $003A92 update entries.

    Unlike the historical $0818 counter, this remains one-to-one when a slow
    update overruns VBlank and a pending IRQ starts another update before the
    main idle loop is fetched.
    """

    if count < 0:
        raise ValueError("negative game-update entry count")
    if max_entries_per_chunk <= 0:
        raise ValueError("max_entries_per_chunk must be positive")
    if video_frame_budget_per_entry <= 0 or minimum_frame_budget <= 0:
        raise ValueError("game-update frame budgets must be positive")
    if count == 0:
        return []
    require_paused(m, "game-update exact-stop start")
    before_cpu = dict(m.get_cpu_state("Sa1"))
    before_frame = int(m.get_state().get("frameCount", 0))
    previous_cycles = int(before_cpu.get("cycleCount", 0))
    # Keep each MCP request below the real-time socket window.  A single
    # request for a long span is semantically equivalent, but on a slow
    # native path it can take longer than the transport allows and leaves the
    # campaign with a misleading Bad-file-descriptor/TimeoutError.  Each
    # exact-stop chunk still ends at the same $003A92 pre-body boundary, so
    # no game-time or controller ordering is changed.
    remaining = count
    chunk_results: list[dict[str, Any]] = []
    observed = 0
    frame_budget_total = 0
    while remaining:
        chunk = min(remaining, max_entries_per_chunk)
        chunk_before_cpu = dict(m.get_cpu_state("Sa1"))
        chunk_before_frame = int(m.get_state().get("frameCount", 0))
        chunk_budget = max(
            minimum_frame_budget,
            chunk * video_frame_budget_per_entry + minimum_frame_budget,
        )
        frame_budget_total += chunk_budget
        result = dict(
            m.tool(
                "run_to_exact_exec_stop",
                {
                    "address": ENTRY_3A92_NATIVE,
                    "cpuType": "Sa1",
                    "maxFrames": chunk_budget,
                    "occurrences": chunk,
                },
            )
        )
        chunk_after_cpu = dict(m.get_cpu_state("Sa1"))
        chunk_after_frame = int(m.get_state().get("frameCount", 0))
        chunk_observed = int(result.get("observedOccurrences", 0))
        chunk_response_pc = (
            ((int(result.get("k", 0)) & 0xFF) << 16)
            | (int(result.get("pc", 0)) & 0xFFFF)
        )
        chunk_ok = (
            result.get("reason") == "breakpoint"
            and bool(result.get("hit"))
            and bool(result.get("isPaused"))
            and bool(result.get("exactStopRemoved"))
            and int(result.get("exactStopHandle", 0)) > 0
            and bool(result.get("exactStopTriggered"))
            and bool(result.get("exactStopBreakDelivered"))
            and chunk_response_pc == ENTRY_3A92_NATIVE
            and int(result.get("requestedOccurrences", -1)) == chunk
            and chunk_observed == chunk
            and int(result.get("cycleCount", -1))
            == int(chunk_after_cpu.get("cycleCount", -2))
            and int(result.get("triggerCycleCount", -1))
            == int(chunk_after_cpu.get("cycleCount", -2))
            and int(result.get("cyclesAdvanced", -1))
            == (
                int(chunk_after_cpu.get("cycleCount", 0))
                - int(chunk_before_cpu.get("cycleCount", 0))
            )
            and int(result.get("triggerFrame", -1))
            == int(result.get("endFrame", -2))
            and int(result.get("endFrame", -1)) == chunk_after_frame
        )
        chunk_results.append(
            {
                "requested_entries": chunk,
                "frame_budget": chunk_budget,
                "before_frame": chunk_before_frame,
                "after_frame": chunk_after_frame,
                "result": result,
            }
        )
        if not chunk_ok:
            terminal_halt = halt16(m)
            terminal_pc = (
                ((int(chunk_after_cpu.get("k", 0)) & 0xFF) << 16)
                | (int(chunk_after_cpu.get("pc", 0)) & 0xFFFF)
            )
            terminal_snapshot = game_update_wait_terminal_snapshot(
                m, chunk_after_cpu
            )
            # A frame-cap response is only the debugger's terminal condition.
            # If the machine entered the interpreter's production halt loop
            # while the exact stop was armed, report the earlier ROM failure
            # instead of misclassifying its secondary lack of future entries
            # as a hardware-boundary/timing timeout.
            if terminal_halt or terminal_pc == INTERPRETER_HALT_SPIN:
                raise CampaignFailure(
                    "interpreter_or_native_hle",
                    {
                        "reason": (
                            "interpreter_halt_during_game_update_entry_wait"
                        ),
                        "halt": terminal_halt,
                        "terminal_sa1_pc": f"{terminal_pc:06X}",
                        "interpreter_halt_spin": (
                            f"{INTERPRETER_HALT_SPIN:06X}"
                        ),
                        "terminal_snapshot": terminal_snapshot,
                        "requested_entries": count,
                        "chunk_requested_entries": chunk,
                        "observed_entries": chunk_observed,
                        "frame_budget": chunk_budget,
                        "run": result,
                        "chunks": chunk_results,
                    },
                )
            raise CampaignFailure(
                "hardware-boundary/timing",
                {
                    "reason": "game_update_entry_exact_stop_failed",
                    "requested_entries": count,
                    "chunk_requested_entries": chunk,
                    "observed_entries": chunk_observed,
                    "frame_budget": chunk_budget,
                    "terminal_snapshot": terminal_snapshot,
                    "run": result,
                    "chunks": chunk_results,
                },
            )
        observed += chunk_observed
        remaining -= chunk

    after_cpu = dict(m.get_cpu_state("Sa1"))
    after_frame = int(m.get_state().get("frameCount", 0))
    result = {
        "reason": "breakpoint",
        "hit": True,
        "isPaused": True,
        "exactStopRemoved": True,
        "exactStopTriggered": True,
        "exactStopBreakDelivered": True,
        "exactStopHandle": 1,
        "requestedOccurrences": count,
        "observedOccurrences": observed,
        "k": int(after_cpu.get("k", 0)),
        "pc": int(after_cpu.get("pc", 0)),
        "cycleCount": int(after_cpu.get("cycleCount", 0)),
        "triggerCycleCount": int(after_cpu.get("cycleCount", 0)),
        "cyclesAdvanced": int(after_cpu.get("cycleCount", 0))
        - int(before_cpu.get("cycleCount", 0)),
        "triggerFrame": after_frame,
        "endFrame": after_frame,
        "chunks": chunk_results,
    }
    current_pc = (
        ((int(after_cpu.get("k", 0)) & 0xFF) << 16)
        | (int(after_cpu.get("pc", 0)) & 0xFFFF)
    )
    if current_pc != ENTRY_3A92_NATIVE:
        raise CampaignFailure(
            "hardware-boundary/timing",
            {
                "reason": "game_update_entry_breakpoint_wrong_pc",
                "expected_pc": f"{ENTRY_3A92_NATIVE:06X}",
                "observed_pc": f"{current_pc:06X}",
                "run": result,
            },
        )
    current_cycles = int(after_cpu.get("cycleCount", 0))
    if current_cycles <= previous_cycles:
        raise CampaignFailure(
            "stale save-state data_or_harness",
            {
                "reason": "game_update_entries_without_cycle_progress",
                "pc": f"{current_pc:06X}",
                "before_cycles": previous_cycles,
                "after_cycles": current_cycles,
                "run": result,
            },
        )
    if halt16(m):
        raise CampaignFailure(
            "interpreter_or_native_hle",
            {
                "reason": "interpreter_halt_at_game_update_entry",
                "halt": halt16(m),
                "observed_entries": observed,
            },
        )
    return [
        {
            "boundary": "native_entry_003A92",
            "native_pc": f"{ENTRY_3A92_NATIVE:06X}",
            "requested_entries": count,
            "observed_entries": observed,
            "zero_progress_hits": int(
                result.get("zeroProgressStops", 0)
            ),
            "attempts": len(chunk_results),
            "before_frame": before_frame,
            "after_frame": after_frame,
            "video_frames": after_frame - before_frame,
            "before_cycles": int(before_cpu.get("cycleCount", 0)),
            "after_cycles": int(after_cpu.get("cycleCount", 0)),
            "sa1_cycles": (
                int(after_cpu.get("cycleCount", 0))
                - int(before_cpu.get("cycleCount", 0))
            ),
            "frame_budget": frame_budget_total,
            "first_run": chunk_results[0]["result"],
            "last_run": chunk_results[-1]["result"],
            "chunk_runs": chunk_results,
        }
    ]


def interpreted_entry_batch_counts(count: int) -> list[int]:
    """Bound native-off exact requests without changing logical edges."""

    if count < 0:
        raise ValueError("negative game-update entry count")
    return [
        min(INTERPRETED_ENTRY_EDGE_MAX_BATCH, count - start)
        for start in range(0, count, INTERPRETED_ENTRY_EDGE_MAX_BATCH)
    ]


def run_interpreted_game_update_entries(
    m: McpSession,
    count: int,
) -> list[dict[str, Any]]:
    """Advance exact `$003A92` entries after gameplay natives are disabled.

    The native `$92:DB82` entry cannot fire with `$071A/$073A` cleared.  The
    old native-only stopper therefore timed out at the very first disabled
    update and falsely labelled the failed transport a gameplay result.  The
    project IRAM-edge Nexen build provides the matching rising virtual-PC edge
    at IRAM `$0040`; use that edge before the interpreted `$003A92` body
    instead.  This changes debugger control only--no ROM, work RAM, input, or
    scheduler state is patched.
    """

    if count < 0:
        raise ValueError("negative game-update entry count")
    if count == 0:
        return []
    require_paused(m, "interpreted game-update exact-stop start")
    before_cpu = dict(m.get_cpu_state("Sa1"))
    before_frame = int(m.get_state().get("frameCount", 0))
    responses: list[dict[str, Any]] = []
    completed_entries = 0
    batch_summaries: list[dict[str, Any]] = []
    for batch_index, batch_count in enumerate(
        interpreted_entry_batch_counts(count)
    ):
        batch_before_cpu = dict(m.get_cpu_state("Sa1"))
        batch_before_frame = int(m.get_state().get("frameCount", 0))
        frame_budget = max(
            MIN_TICK_VIDEO_FRAME_BUDGET,
            batch_count * INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY
            + MIN_TICK_VIDEO_FRAME_BUDGET,
        )
        response = dict(
            m.tool(
                "run_to_exact_iram_exec_edge",
                {
                    "iramAddress": M68K_PC_IRAM,
                    "value": M68K_GAME_UPDATE_ENTRY,
                    "mask": 0xFFFFFFFF,
                    "maxFrames": frame_budget,
                    "occurrences": batch_count,
                },
            )
        )
        batch_after_cpu = dict(m.get_cpu_state("Sa1"))
        batch_after_frame = int(m.get_state().get("frameCount", 0))
        virtual_pc = int.from_bytes(
            bytes(m.read_memory("Sa1Memory", M68K_PC_IRAM, 4)), "little"
        ) & 0xFFFFFF
        checks = {
            "reason": response.get("reason") == "breakpoint",
            "hit": response.get("hit") is True,
            "paused": response.get("isPaused") is True,
            "stop_removed": response.get("exactStopRemoved") is True,
            "stop_triggered": response.get("exactStopTriggered") is True,
            "break_delivered": response.get("exactStopBreakDelivered") is True,
            "handle": int(response.get("exactStopHandle", 0)) > 0,
            "requested_occurrences": (
                int(response.get("requestedOccurrences", -1))
                == batch_count
            ),
            "observed_occurrences": (
                int(response.get("observedOccurrences", -1))
                == batch_count
            ),
            "iram_address": (
                int(response.get("iramAddress", -1)) == M68K_PC_IRAM
            ),
            "observed_value": (
                int(response.get("observedValue", -1))
                == M68K_GAME_UPDATE_ENTRY
            ),
            "predicate_matched": response.get("predicateMatched") is True,
            "rising_edge": response.get("edgeRequired") is True,
            "no_cleanup_pause": response.get("cleanupPauseApplied") is False,
            "virtual_pc": virtual_pc == M68K_GAME_UPDATE_ENTRY,
            "cycle_count": (
                int(response.get("cycleCount", -1))
                == int(batch_after_cpu.get("cycleCount", -2))
            ),
            "trigger_cycle_count": (
                int(response.get("triggerCycleCount", -1))
                == int(batch_after_cpu.get("cycleCount", -2))
            ),
            "end_frame": (
                int(response.get("endFrame", -1)) == batch_after_frame
            ),
            "trigger_frame": (
                int(response.get("triggerFrame", -1)) == batch_after_frame
            ),
            "cycle_progress": (
                int(batch_after_cpu.get("cycleCount", 0))
                > int(batch_before_cpu.get("cycleCount", 0))
            ),
            "frame_progress": batch_after_frame >= batch_before_frame,
        }
        response["campaign_boundary_checks"] = checks
        response["campaign_boundary_before_frame"] = batch_before_frame
        response["campaign_boundary_after_frame"] = batch_after_frame
        responses.append(response)
        observed_in_batch = max(
            0, int(response.get("observedOccurrences", 0))
        )
        batch_summary = {
            "batch_index": batch_index,
            "requested_entries": batch_count,
            "observed_entries": observed_in_batch,
            "before_frame": batch_before_frame,
            "after_frame": batch_after_frame,
            "video_frames": batch_after_frame - batch_before_frame,
            "before_cycles": int(batch_before_cpu.get("cycleCount", 0)),
            "after_cycles": int(batch_after_cpu.get("cycleCount", 0)),
            "sa1_cycles": (
                int(batch_after_cpu.get("cycleCount", 0))
                - int(batch_before_cpu.get("cycleCount", 0))
            ),
        }
        if not all(checks.values()):
            failure_progress = {
                "completed_entries_before_failure": completed_entries,
                "completed_batches_before_failure": batch_index,
                "failed_batch_index": batch_index,
                "failed_batch_requested_entries": batch_count,
                "failed_batch_observed_entries": observed_in_batch,
                "observed_entries_before_failure": (
                    completed_entries + observed_in_batch
                ),
                "completed_batch_summaries": batch_summaries,
                "failed_batch_summary": batch_summary,
            }
            terminal_snapshot = game_update_wait_terminal_snapshot(
                m, batch_after_cpu
            )
            terminal_halt = int(terminal_snapshot.get("halt", halt16(m)))
            terminal_pc = int(
                terminal_snapshot.get(
                    "sa1_pc",
                    ((int(batch_after_cpu.get("k", 0)) & 0xFF) << 16)
                    | (int(batch_after_cpu.get("pc", 0)) & 0xFFFF),
                )
            )
            if terminal_halt or terminal_pc == INTERPRETER_HALT_SPIN:
                raise CampaignFailure(
                    "interpreter_or_native_hle",
                    {
                        "reason": (
                            "interpreter_halt_during_interpreted_game_update_"
                            "entry_wait"
                        ),
                        "halt": terminal_halt,
                        "terminal_sa1_pc": f"{terminal_pc:06X}",
                        "interpreter_halt_spin": (
                            f"{INTERPRETER_HALT_SPIN:06X}"
                        ),
                        "terminal_snapshot": terminal_snapshot,
                        "requested_entries": count,
                        "batch_requested_entries": batch_count,
                        "virtual_pc": f"{virtual_pc:06X}",
                        "checks": checks,
                        "response": response,
                        **failure_progress,
                    },
                )
            raise CampaignFailure(
                "hardware-boundary/timing",
                {
                    "reason": "interpreted_game_update_entry_exact_stop_failed",
                    "requested_entries": count,
                    "batch_requested_entries": batch_count,
                    "virtual_pc": f"{virtual_pc:06X}",
                    "terminal_snapshot": terminal_snapshot,
                    "checks": checks,
                    "response": response,
                    **failure_progress,
                },
            )
        if halt16(m):
            raise CampaignFailure(
                "interpreter_or_native_hle",
                {"reason": "interpreter_halt", "halt": halt16(m)},
            )
        completed_entries += batch_count
        batch_summaries.append(batch_summary)

    after_cpu = dict(m.get_cpu_state("Sa1"))
    after_frame = int(m.get_state().get("frameCount", 0))
    return [
        {
            "boundary": "interpreted_pc_003a92_rising_edge_pre_body",
            "virtual_pc": f"{M68K_GAME_UPDATE_ENTRY:06X}",
            "requested_entries": count,
            "observed_entries": count,
            "attempts": len(responses),
            "before_frame": before_frame,
            "after_frame": after_frame,
            "video_frames": after_frame - before_frame,
            "before_cycles": int(before_cpu.get("cycleCount", 0)),
            "after_cycles": int(after_cpu.get("cycleCount", 0)),
            "sa1_cycles": (
                int(after_cpu.get("cycleCount", 0))
                - int(before_cpu.get("cycleCount", 0))
            ),
            "frame_budget": sum(
                max(
                    MIN_TICK_VIDEO_FRAME_BUDGET,
                    batch * INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY
                    + MIN_TICK_VIDEO_FRAME_BUDGET,
                )
                for batch in interpreted_entry_batch_counts(count)
            ),
            "batch_summaries": batch_summaries,
            "chunk_runs": responses,
        }
    ]


def active_game_update_gate(m: McpSession) -> dict[str, Any]:
    """Return the live boundary route for the `$003A92` game update."""

    xlat = le16(m.read_memory("Sa1Memory", 0x071A, 2))
    choke = le16(m.read_memory("Sa1Memory", 0x073A, 2))
    return {
        "mode": "interpreted" if xlat == 0 else "native",
        "xlat_071a": xlat,
        "choke_073a": choke,
    }


def run_active_game_update_entries(
    m: McpSession, count: int
) -> list[dict[str, Any]]:
    """Use the exact boundary that is reachable under the live gate state."""

    gate = active_game_update_gate(m)
    spans = (
        run_interpreted_game_update_entries(m, count)
        if gate["mode"] == "interpreted"
        else run_game_update_entries(m, count)
    )
    for span in spans:
        span["active_gate"] = gate
    return spans


def game_update_entries_between_ticks(
    current_tick: int, target_tick: int
) -> int:
    """Return required entries, including a valid zero-entry resume edge."""

    if target_tick < current_tick:
        raise ValueError(
            f"target tick {target_tick} precedes current tick {current_tick}"
        )
    return target_tick - current_tick


def final_span_is_interpreted(spans: list[dict[str, Any]]) -> bool:
    """Classify a completed span without indexing an empty resume-edge batch."""

    return bool(spans) and spans[-1]["active_gate"]["mode"] == "interpreted"


def at_active_game_update_entry(m: McpSession, mode: str) -> bool:
    """Confirm the paused machine is at the selected pre-body boundary."""

    if mode == "native":
        return sa1_pc(m) == ENTRY_3A92_NATIVE
    if mode == "interpreted":
        virtual_pc = int.from_bytes(
            bytes(m.read_memory("Sa1Memory", M68K_PC_IRAM, 4)), "little"
        ) & 0xFFFFFF
        return virtual_pc == M68K_GAME_UPDATE_ENTRY
    raise ValueError(f"unknown game-update boundary mode: {mode}")


def player_snapshot(m: McpSession) -> dict[str, Any]:
    raw = bytes(m.read_memory("snesMemory", PLAYER_BASE, 0x80))

    def byte(offset: int) -> int:
        return raw[0x60 + offset]

    def word(offset: int) -> int:
        index = 0x60 + offset
        return be16(raw[index : index + 2])

    return {
        "health": word(-0x4E),
        "previous_input": byte(-0x43),
        "input": byte(-0x44),
        "action": byte(-0x23),
        "flags": byte(-0x24),
        "animation": word(-0x1A),
        "animation_step": word(-0x18),
        "x": word(-0x1E),
        "y": word(-0x22),
        # The MAME movie labels its $D00601/$D00603 X1-001 device bytes
        # scroll_x/scroll_y.  On SNES they are the exact mirrored bytes below.
        # They carry the upper horizontal column-position controls whose loss
        # produced the reported Stage-3 vertical blue strip.
        "x1_ctrl_3601": int(
            m.read_memory("snesMemory", 0x413601, 1)[0]
        ),
        "x1_ctrl_3603": int(
            m.read_memory("snesMemory", 0x413603, 1)[0]
        ),
        "locals_sha256": digest(raw),
    }


def register_snapshot(m: McpSession) -> dict[str, Any]:
    raw = bytes(m.read_memory("Sa1Memory", 0x0000, 0xB0))
    names = (
        "D0",
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
        "D6",
        "D7",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
    )
    regs = {
        name: le32(raw[index * 4 : index * 4 + 4])
        for index, name in enumerate(names)
    }
    ccr = (
        ((le16(raw[0xA2:0xA4]) & 1) << 4)
        | ((le16(raw[0x70:0x72]) & 1) << 3)
        | ((le16(raw[0x60:0x62]) & 1) << 2)
        | ((le16(raw[0x72:0x74]) & 1) << 1)
        | (le16(raw[0x6E:0x70]) & 1)
    )
    a7 = regs["A7"] & 0xFFFF
    stack_start = (a7 - STACK_WINDOW_RADIUS) & 0xFFFF
    return {
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "ccr_xnzvc": ccr,
        "interrupt_mask": le16(raw[0x7C:0x7E]) & 7,
        "stack_window": {
            "address": f"F0{stack_start:04X}",
            "hex": bytes(
                m.read_memory(
                    "snesMemory",
                    0x400000 | stack_start,
                    STACK_WINDOW_RADIUS * 2,
                )
            ).hex(),
        },
    }


def task_snapshot(m: McpSession, floors: list[int]) -> dict[str, Any]:
    raw = bytes(m.read_memory("snesMemory", TASK_CONTEXT_START, 16 * 4))
    saved = [
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
        for index, value in enumerate(saved)
        if value
    ]
    return {
        "task_mask": be16(m.read_memory("snesMemory", 0x400002, 2)),
        "initialized": initialized,
        "invalid": [row for row in initialized if not row["valid"]],
        "minimum_margin": min(
            (row["margin"] for row in initialized), default=None
        ),
    }


def boss_healths(m: McpSession) -> dict[str, int]:
    return {
        "stage1_f00a74": be16(m.read_memory("snesMemory", 0x400A76, 2)),
        "stage2_f00a70": be16(m.read_memory("snesMemory", 0x400A72, 2)),
        "stage3_f00a58": be16(m.read_memory("snesMemory", 0x400A5A, 2)),
    }


def detailed_snapshot(
    m: McpSession,
    floors: list[int],
    label: str,
    mame_tick: int,
) -> dict[str, Any]:
    state = m.get_state()
    virtual = bytes(m.read_memory("Sa1Memory", 0x0040, 0x70))
    renderer = bytes(m.read_memory("snesWorkRam", 0x89A0, 0x3A))
    request_ack = bytes(m.read_memory("snesMemory", 0x3300, 4))
    work = bytes(m.read_memory("snesMemory", 0x400000, 0x4000))
    tasks = task_snapshot(m, floors)
    return {
        "label": label,
        "mame_tick": mame_tick,
        "video_frame": int(state.get("frameCount", 0)),
        "snes_game_tick": tick16(m),
        "pc68k": le32(virtual[0:4]) & 0xFFFFFF,
        "opcode68k": le16(virtual[4:6]),
        "halt": le16(virtual[0x0E:0x10]),
        "ac": le16(virtual[0x6C:0x6E]),
        "virtual_irq_pending": le16(
            m.read_memory("Sa1Memory", 0x00AA, 2)
        ),
        "virtual_irq_countdown": le16(
            m.read_memory("Sa1Memory", 0x00AC, 2)
        ),
        "frame_request": le16(request_ack[0:2]),
        "frame_ack": le16(request_ack[2:4]),
        "render_complete": le16(renderer[2:4]),
        "render_generation": le16(renderer[4:6]),
        "render_queue_primary": le16(renderer[0x32:0x34]),
        "render_queue_drops": le16(renderer[0x34:0x36]),
        "render_queue_secondary": le16(renderer[0x36:0x38]),
        "player": player_snapshot(m),
        "boss_health": boss_healths(m),
        "credits": be16(work[0x1C62:0x1C64]),
        "rng_state": be16(work[0x170E:0x1710]),
        "work_16k_sha256": digest(work),
        "collision_4k_sha256": digest(work[0x3000:0x4000]),
        "m68k": register_snapshot(m),
        "gates": {
            "xlat_071a": le16(m.read_memory("Sa1Memory", 0x071A, 2)),
            "pacing_0734": le16(m.read_memory("Sa1Memory", 0x0734, 2)),
            "select_0736": le16(m.read_memory("Sa1Memory", 0x0736, 2)),
            "choke_073a": le16(m.read_memory("Sa1Memory", 0x073A, 2)),
            "swin_073c": le16(m.read_memory("Sa1Memory", 0x073C, 2)),
        },
        **tasks,
    }


def compare_player(
    observed: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    mapping = {
        "health": "health",
        "x": "player_x",
        "y": "player_y",
        "action": "action",
        "x1_ctrl_3601": "scroll_x",
        "x1_ctrl_3603": "scroll_y",
    }
    mismatches = {
        target: {
            "mame": int(reference[source]),
            "snes": int(observed[target]),
        }
        for target, source in mapping.items()
        if int(observed[target]) != int(reference[source])
    }
    return {
        "result": "green" if not mismatches else "red",
        "mismatches": mismatches,
        "mame": {target: int(reference[source]) for target, source in mapping.items()},
        "snes": {target: int(observed[target]) for target in mapping},
    }


def player_health_alive(value: int) -> bool:
    """Return the arcade player's signed-word liveness state.

    Damage is subtracted as a word and can cross zero without landing on
    exactly ``$0000``.  Values such as ``$FFFC`` are therefore dead, not a
    giant positive health total.  Keep this helper shared by timeline event
    scheduling and the live SNES observer so wrapped deaths retain the same
    evidence as exact-zero deaths.
    """

    health = value & 0xFFFF
    return 0 < health < 0x8000


def emit(stream: TextIO, event: str, **fields: Any) -> None:
    stream.write(json.dumps({"event": event, **fields}, sort_keys=True) + "\n")
    stream.flush()


def note_oracle_divergence(
    summary: dict[str, Any],
    kind: str,
    mame_tick: int,
    detail: dict[str, Any],
) -> None:
    summary["oracle_divergence_count"] += 1
    counts = summary["oracle_divergence_kinds"]
    counts[kind] = int(counts.get(kind, 0)) + 1
    if summary["first_oracle_divergence"] is None:
        summary["first_oracle_divergence"] = {
            "kind": kind,
            "mame_tick": mame_tick,
            **detail,
        }


def retain_input_prestate_for_divergence(
    states_dir: Path,
    latest_input_prestate: dict[str, Any] | None,
    *,
    kind: str,
    mame_tick: int,
) -> dict[str, Any] | None:
    """Freeze the input state that existed before an observed divergence.

    The campaign ordinarily reuses ``pre-input-latest.mss`` so opt-in input
    evidence does not create thousands of files.  That is sufficient only for
    a fail-fast run.  A continuation can observe a mismatch and later replace
    that file at the next controller edge, which destroys the deterministic
    pre-failure artifact.  Copy it immediately, including its SA-1 IRAM
    sidecar, and retain the original exact-boundary metadata rather than
    claiming a new safe checkpoint was created.
    """
    if latest_input_prestate is None:
        return None
    source_state = latest_input_prestate.get("state")
    if not isinstance(source_state, dict):
        return None
    source_path = Path(str(source_state.get("path", "")))
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.is_file():
        return None
    safe_kind = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in kind
    )
    retained_path = states_dir / (
        f"pre-failure-{safe_kind}-tick-{mame_tick:05d}.mss"
    )
    if not retained_path.exists():
        shutil.copy2(source_path, retained_path)
    if sha256(retained_path) != sha256(source_path):
        raise RuntimeError("copied pre-failure state failed authentication")
    source_iram = Path(f"{source_path}.sa1-iram.bin")
    retained_iram = Path(f"{retained_path}.sa1-iram.bin")
    if source_iram.is_file() and not retained_iram.exists():
        shutil.copy2(source_iram, retained_iram)
    if source_iram.is_file() and (
        not retained_iram.is_file()
        or sha256(retained_iram) != sha256(source_iram)
    ):
        raise RuntimeError("copied pre-failure SA-1 IRAM failed authentication")
    retained: dict[str, Any] = {
        "path": str(retained_path),
        "sha256": sha256(retained_path),
        "source": str(source_path),
        "source_sha256": sha256(source_path),
        "copied_at_first_observation": True,
        "live_state_unchanged": True,
        "boundary_kind": "pre_input_apply_exact_entry_forensic",
        "input": latest_input_prestate,
    }
    if source_iram.is_file():
        retained["sa1_iram_sidecar"] = {
            "path": str(retained_iram),
            "sha256": sha256(retained_iram),
            "source": str(source_iram),
            "source_sha256": sha256(source_iram),
        }
    return retained


def record_oracle_divergence(
    summary: dict[str, Any],
    log: TextIO,
    states_dir: Path,
    latest_input_prestate: dict[str, Any] | None,
    *,
    kind: str,
    mame_tick: int,
    detail: dict[str, Any],
) -> None:
    """Record a mismatch and preserve its deterministic pre-input artifact."""
    retained = retain_input_prestate_for_divergence(
        states_dir, latest_input_prestate, kind=kind, mame_tick=mame_tick
    )
    enriched = dict(detail)
    if retained is not None:
        enriched["pre_failure_input_state"] = retained
        summary.setdefault("pre_failure_states", []).append(retained)
    note_oracle_divergence(summary, kind, mame_tick, enriched)
    emit(
        log,
        "oracle_divergence",
        kind=kind,
        mame_tick=mame_tick,
        detail=enriched,
    )


def fail_on_player_reference_mismatch(
    strict_player_reference: bool,
    continue_oracle_divergences: bool,
) -> bool:
    """Keep strict controller checks compatible with coverage continuation.

    ``--strict-player-reference`` remains the normal exact-prefix gate.  Once
    the caller has explicitly requested ``--continue-oracle-divergences``, a
    mismatch is retained and counted but must not abort the organic suffix.
    Hard halt, task-stack, and renderer failures are deliberately handled
    outside this predicate and remain fatal.
    """
    return strict_player_reference and not continue_oracle_divergences


def allowed_resume_identity_mismatch(
    key: str,
    expected: Any,
    observed: Any,
    *,
    allow_rom_migration: bool = False,
) -> bool:
    """Allow audited runner drift and candidate symbols only in migration."""
    predecessor_runner = (
        key == "campaign_script_sha256"
        and isinstance(expected, str)
        and isinstance(observed, str)
        and expected != observed
        and observed in RESUME_COMPATIBLE_CAMPAIGN_SCRIPT_SHA256S
    )
    candidate_symbol_table = (
        allow_rom_migration
        and key == "native_symbol_table_sha256"
        and isinstance(expected, str)
        and isinstance(observed, str)
        and expected != observed
    )
    relocated_source_dependencies = (
        allow_rom_migration
        and key == "emulator_identity"
        and isinstance(expected, dict)
        and isinstance(observed, dict)
        and expected != observed
        and {
            name: value
            for name, value in expected.items()
            if name != "source_dependencies_zip"
        }
        == {
            name: value
            for name, value in observed.items()
            if name != "source_dependencies_zip"
        }
    )
    return (
        predecessor_runner
        or candidate_symbol_table
        or relocated_source_dependencies
    )


def buttons_at_tick(
    events: list[InputEvent], origin_tick: int, target_tick: int
) -> int:
    buttons = 0
    for event in events:
        if event.tick > target_tick:
            break
        if event.tick > origin_tick:
            buttons = event.buttons
    return buttons


def segment_initial_buttons(
    events: list[InputEvent],
    origin_tick: int,
    segment_origin_tick: int,
    *,
    resumed: bool,
) -> int:
    """Return the physical input represented by the loaded segment boundary.

    A safe checkpoint is created after completing tick T and resumes at T+1.
    If T+1 is itself an input edge, the serialized controller still represents
    tick T.  The edge must be compared and applied at the resumed exact entry,
    not installed early while rendezvousing from the main-SNES safe boundary.
    """

    represented_tick = segment_origin_tick - 1 if resumed else segment_origin_tick
    return buttons_at_tick(events, origin_tick, represented_tick)


def input_transition_belongs_to_segment(
    event_tick: int,
    segment_origin_tick: int,
    *,
    resumed: bool,
) -> bool:
    """Include a resume-tick edge exactly once in the child segment."""

    return event_tick > segment_origin_tick or (
        resumed and event_tick == segment_origin_tick
    )


def validate_resume_lineage(
    event_path: Path,
    state_path: Path,
    resume_tick: int,
    rom_sha256: str,
    expected_identity: dict[str, Any],
    *,
    allow_rom_migration: bool = False,
) -> dict[str, Any]:
    """Authenticate a safe checkpoint and its exact fresh-boot ROM lineage."""

    raw_lines = event_path.read_bytes().splitlines(keepends=True)
    indexed_rows = [
        (index, json.loads(line))
        for index, line in enumerate(raw_lines)
        if line.strip()
    ]
    rows = [row for _index, row in indexed_rows]
    provenance_rows = [
        (index, row)
        for index, row in indexed_rows
        if row.get("event") == "provenance"
    ]
    if len(provenance_rows) != 1 or provenance_rows[0][0] != 0:
        raise RuntimeError(
            "resume lineage requires exactly one first-line provenance event"
        )
    provenance = provenance_rows[0][1]
    lineage_rom_sha256 = provenance.get("rom_sha256")
    if (
        lineage_rom_sha256 != rom_sha256
        and not allow_rom_migration
    ):
        raise RuntimeError(
            "resume lineage ROM hash does not match the selected ROM"
        )
    identity_mismatches: dict[str, dict[str, Any]] = {}
    identity_compatibility_exceptions: dict[str, dict[str, Any]] = {}
    for key, value in expected_identity.items():
        observed = provenance.get(key)
        if observed == value:
            continue
        detail = {"expected": value, "observed": observed}
        if allowed_resume_identity_mismatch(
            key,
            value,
            observed,
            allow_rom_migration=allow_rom_migration,
        ):
            identity_compatibility_exceptions[key] = detail
        else:
            identity_mismatches[key] = detail
    if identity_mismatches:
        raise RuntimeError(
            "resume lineage oracle/control identity mismatch: "
            f"{identity_mismatches}"
        )

    lineage_kind = provenance.get("lineage_kind")
    parent_lineage = None
    if lineage_kind == "checkpoint_continuation":
        embedded_parent = provenance.get("resume_lineage")
        if not isinstance(embedded_parent, dict):
            raise RuntimeError(
                "checkpoint-continuation lineage lacks its authenticated "
                "parent"
            )
        parent_events = Path(str(embedded_parent.get("events", "")))
        if not parent_events.is_absolute():
            parent_events = ROOT / parent_events
        parent_checkpoint = embedded_parent.get("checkpoint")
        parent_context = embedded_parent.get("resume_context")
        if (
            not parent_events.is_file()
            or not isinstance(parent_checkpoint, dict)
            or not isinstance(parent_context, dict)
        ):
            raise RuntimeError(
                "checkpoint-continuation parent paths/metadata are invalid"
            )
        parent_state = Path(str(parent_checkpoint.get("path", "")))
        if not parent_state.is_absolute():
            parent_state = ROOT / parent_state
        if not parent_state.is_file():
            raise RuntimeError(
                "checkpoint-continuation parent state is missing"
            )
        parent_resume_tick = int(
            parent_context.get("resume_mame_tick", -1)
        )
        parent_lineage = validate_resume_lineage(
            parent_events,
            parent_state,
            parent_resume_tick,
            str(lineage_rom_sha256),
            expected_identity,
            allow_rom_migration=(
                allow_rom_migration
                or embedded_parent.get("lineage_has_rom_migration") is True
            ),
        )
        parent_fingerprint_fields = (
            "accepted_prefix_sha256",
            "accepted_prefix_lines",
            "checkpoint_sha256",
            "fresh_boot_rom_sha256",
            "selected_rom_sha256",
        )
        # A parent may legitimately continue recording *after* it has made
        # this atomic safe checkpoint.  The checkpoint's accepted prefix is
        # the complete causal history of the resumed machine; the later log
        # tail cannot change that state.  Its whole-file digest is retained
        # in provenance for audit, but must not reject a child solely because
        # a parent appended post-checkpoint observations.
        parent_fingerprint_mismatches = {
            field: {
                "embedded": embedded_parent.get(field),
                "revalidated": parent_lineage.get(field),
            }
            for field in parent_fingerprint_fields
            if embedded_parent.get(field) != parent_lineage.get(field)
        }
        embedded_root_identity = embedded_parent.get("root_identity")
        revalidated_root_identity = parent_lineage.get("root_identity")
        root_identity_mismatches = {
            key: {
                "embedded": (
                    embedded_root_identity.get(key)
                    if isinstance(embedded_root_identity, dict)
                    else None
                ),
                "revalidated": (
                    revalidated_root_identity.get(key)
                    if isinstance(revalidated_root_identity, dict)
                    else None
                ),
            }
            for key in expected_identity
            if not isinstance(embedded_root_identity, dict)
            or not isinstance(revalidated_root_identity, dict)
            or embedded_root_identity.get(key)
            != revalidated_root_identity.get(key)
        }
        if root_identity_mismatches:
            parent_fingerprint_mismatches["root_identity"] = {
                "mismatches": root_identity_mismatches,
            }
        if parent_fingerprint_mismatches:
            raise RuntimeError(
                "checkpoint-continuation parent authentication changed: "
                f"{parent_fingerprint_mismatches}"
            )
    elif lineage_kind != "fresh_power_on_root":
        raise RuntimeError(
            "resume lineage is neither a fresh-power-on root nor an "
            "authenticated checkpoint continuation"
        )

    state_hash = sha256(state_path)
    checkpoints = [
        row
        for row in rows
        if row.get("event") == "safe_checkpoint"
        and int(row.get("resume_mame_tick", -1)) == resume_tick
    ]
    matching = [
        (index, row)
        for index, row in indexed_rows
        if row.get("event") == "safe_checkpoint"
        and int(row.get("resume_mame_tick", -1)) == resume_tick
        and row.get("state", {}).get("sha256") == state_hash
    ]
    if len(checkpoints) != 1 or len(matching) != 1:
        raise RuntimeError(
            "resume tick does not have exactly one authenticated safe "
            "checkpoint: "
            f"tick={resume_tick}, rows={len(checkpoints)}, "
            f"matching={len(matching)}"
        )
    checkpoint_index, checkpoint_row = matching[0]
    checkpoint_state = checkpoint_row.get("state")
    if not isinstance(checkpoint_state, dict):
        raise RuntimeError("resume checkpoint state metadata is missing")
    required_safe_bundle = {
        "resumable_checkpoint": checkpoint_state.get(
            "resumable_checkpoint"
        )
        is True,
        "safe_boundary_kind": checkpoint_state.get("boundary_kind")
        == "post_entry_safe_snes_boundary",
        "not_entry_exact_bundle": checkpoint_state.get(
            "entry_exact_bundle"
        )
        is False,
        "not_nested_sa1_entry": checkpoint_state.get(
            "nested_sa1_entry_nonresumable"
        )
        is False,
        "synchronous_completed": checkpoint_state.get(
            "synchronous_completed"
        )
        is True,
        "atomic_rename": checkpoint_state.get("atomic_rename") is True,
        "live_state_unchanged": checkpoint_state.get(
            "live_state_unchanged"
        )
        is True,
        "active_run_not_reloaded": checkpoint_state.get(
            "active_run_reloaded"
        )
        is False,
        "active_run_not_restored": checkpoint_state.get(
            "active_run_memory_restored"
        )
        is False,
        "resume_validation": isinstance(
            checkpoint_state.get("resume_validation"), dict
        ),
        "resume_sa1_state": isinstance(
            checkpoint_state.get("resume_sa1_state"), dict
        ),
        "resume_sa1_iram": isinstance(
            checkpoint_state.get("resume_sa1_iram"), dict
        ),
    }
    if not all(required_safe_bundle.values()):
        raise RuntimeError(
            "resume checkpoint is not an atomic post-entry safe bundle: "
            f"{required_safe_bundle}"
        )
    resume_context = checkpoint_row.get("resume_context")
    if not isinstance(resume_context, dict):
        raise RuntimeError(
            "resume checkpoint predates the required post-event context"
        )
    if (
        resume_context.get("phase") != "post_entry_safe_snes_boundary"
        or int(resume_context.get("mame_tick_completed", -1))
        != resume_tick - 1
        or int(resume_context.get("resume_mame_tick", -1))
        != resume_tick
    ):
        raise RuntimeError("resume checkpoint context has the wrong phase/tick")
    accepted_prefix = b"".join(raw_lines[: checkpoint_index + 1])
    fresh_boot_rom_sha256 = (
        parent_lineage["fresh_boot_rom_sha256"]
        if parent_lineage is not None
        else lineage_rom_sha256
    )
    current_rom_migration = (
        {
            "kind": "explicit_checkpoint_rom_migration",
            "fresh_boot_rom_sha256": fresh_boot_rom_sha256,
            "checkpoint_rom_sha256": lineage_rom_sha256,
            "selected_rom_sha256": rom_sha256,
            "fresh_boot_proof": False,
            "diagnostic_only": True,
        }
        if lineage_rom_sha256 != rom_sha256
        else None
    )
    lineage_has_rom_migration = bool(
        current_rom_migration is not None
        or (
            parent_lineage is not None
            and parent_lineage.get("lineage_has_rom_migration") is True
        )
    )
    return {
        "events": str(event_path.resolve()),
        "events_sha256": sha256(event_path),
        "identity_compatibility_exceptions": identity_compatibility_exceptions,
        "accepted_prefix_sha256": digest(accepted_prefix),
        "accepted_prefix_lines": checkpoint_index + 1,
        "excluded_tail_lines": len(raw_lines) - checkpoint_index - 1,
        "checkpoint": checkpoint_state,
        "resume_context": resume_context,
        "checkpoint_sha256": state_hash,
        "fresh_boot_rom_sha256": fresh_boot_rom_sha256,
        "checkpoint_rom_sha256": lineage_rom_sha256,
        "selected_rom_sha256": rom_sha256,
        "rom_migration": current_rom_migration,
        "lineage_has_rom_migration": lineage_has_rom_migration,
        "fresh_boot_time_unix": (
            parent_lineage["fresh_boot_time_unix"]
            if parent_lineage is not None
            else provenance.get("time_unix")
        ),
        "fresh_boot_emulator_sha256": (
            parent_lineage["fresh_boot_emulator_sha256"]
            if parent_lineage is not None
            else provenance.get("emulator_sha256")
        ),
        "fresh_boot_emulator_identity": (
            parent_lineage["fresh_boot_emulator_identity"]
            if parent_lineage is not None
            else provenance.get("emulator_identity")
        ),
        "root_identity": (
            parent_lineage["root_identity"]
            if parent_lineage is not None
            else {
                key: provenance.get(key) for key in expected_identity
            }
        ),
        "fresh_boot_campaign_configuration": (
            parent_lineage["fresh_boot_campaign_configuration"]
            if parent_lineage is not None
            else provenance.get("campaign_configuration", {})
        ),
        "lineage_kind": lineage_kind,
        "lineage_depth": (
            int(parent_lineage.get("lineage_depth", 0)) + 1
            if parent_lineage is not None
            else 0
        ),
        "parent_lineage": parent_lineage,
    }


def input_coverage(
    events: list[InputEvent],
    origin_tick: int,
    end_tick: int,
    initial_buttons: int = 0,
) -> dict[str, Any]:
    segment_events = [
        event for event in events if origin_tick < event.tick <= end_tick
    ]
    boundaries = [(origin_tick, initial_buttons)]
    boundaries.extend((event.tick, event.buttons) for event in segment_events)
    boundaries.append((end_tick, boundaries[-1][1]))
    durations: dict[str, int] = defaultdict(int)
    max_holds: dict[str, int] = defaultdict(int)
    for (start, mask), (end, _next) in zip(boundaries, boundaries[1:]):
        duration = max(0, end - start)
        label = button_label(mask)
        durations[label] += duration
        for bit, name in BUTTON_NAMES:
            if mask & bit:
                max_holds[name] = max(max_holds[name], duration)
    return {
        "transition_count": len(segment_events),
        "buttons_seen": {
            name: bool(initial_buttons & bit)
            or any(event.buttons & bit for event in segment_events)
            for bit, name in BUTTON_NAMES
        },
        "maximum_contiguous_hold_ticks": dict(sorted(max_holds.items())),
        "mask_duration_ticks": dict(sorted(durations.items())),
    }


def campaign_input_coverage(
    events: list[InputEvent],
    origin_tick: int,
    end_tick: int,
    initial_buttons: int,
    *,
    cold_boot_coin_pulses: int,
    cold_boot_start_frames: int,
) -> dict[str, Any]:
    """Combine gameplay-movie masks with the real pre-game controller inputs.

    Select/coin and Start are intentionally issued before the synchronized
    gameplay timeline begins.  Counting only movie-tick masks therefore made
    every otherwise-complete fresh run fail its controller coverage gate.
    Keep the two phases explicit and expose their union as ``buttons_seen``.
    """

    coverage = input_coverage(
        events,
        origin_tick,
        end_tick,
        initial_buttons,
    )
    gameplay_seen = dict(coverage["buttons_seen"])
    cold_boot_seen = {
        name: (
            (name == "select" and cold_boot_coin_pulses > 0)
            or (name == "start" and cold_boot_start_frames > 0)
        )
        for _bit, name in BUTTON_NAMES
    }
    coverage["gameplay_buttons_seen"] = gameplay_seen
    coverage["cold_boot_buttons_seen"] = cold_boot_seen
    coverage["buttons_seen"] = {
        name: bool(gameplay_seen[name] or cold_boot_seen[name])
        for _bit, name in BUTTON_NAMES
    }
    return coverage


def main() -> int:
    global _ACTIVE_SESSION, _ACTIVE_STATE_DIR, _ACTIVE_SHOT_DIR

    args = parse_args()
    if (
        args.diagnose_snes_exec_address is None
        and (args.diagnose_snes_trace_tail or args.diagnose_snes_call_stack)
    ):
        raise SystemExit(
            "--diagnose-snes-trace-tail/--diagnose-snes-call-stack require "
            "--diagnose-snes-exec-address"
        )
    mame = mame_identity()
    configure_dotnet(args.mesen)
    rom = args.rom.resolve()
    rom_data = rom.read_bytes()
    if len(rom_data) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_data[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    inputs, tick_rows = load_timeline(
        args.timeline, args.mame_origin_tick, args.mame_end_tick
    )
    boss_events = load_boss_events(args.boss_fixtures, args.mame_end_tick)
    mame_origin_work = args.mame_origin_work.read_bytes()
    mame_origin_credits = be16(mame_origin_work[0x1C62:0x1C64])
    segment_origin_tick = (
        args.resume_mame_tick
        if args.resume_mame_tick is not None
        else args.mame_origin_tick
    )
    root_initial_buttons = int(
        tick_rows[args.mame_origin_tick]["snes_buttons"]
    )
    initial_buttons = segment_initial_buttons(
        inputs,
        args.mame_origin_tick,
        segment_origin_tick,
        resumed=args.resume_state is not None,
    )
    rom_hash = sha256(rom)
    emulator_identity = nexen_identity(
        args.mesen,
        args.resume_source_dependencies,
    )
    resume_identity = {
        "emulator_sha256": sha256(args.mesen),
        "emulator_identity": emulator_identity,
        "mame_sha256": mame["sha256"],
        "mame_movie_sha256": sha256(MAME_MOVIE),
        "mame_timeline_sha256": sha256(args.timeline),
        "boss_fixtures_sha256": sha256(args.boss_fixtures),
        "mame_origin_work_sha256": sha256(args.mame_origin_work),
        "mame_origin_tick": args.mame_origin_tick,
        "exact_boundary_tool": "run_to_exact_exec_stop",
        "campaign_script_sha256": sha256(Path(__file__).resolve()),
        "checkpoint_validator_sha256": sha256(
            ROOT / "tools" / "validate_campaign_checkpoint_bundle.py"
        ),
        "mcp_python_client_sha256": sha256(
            Path(_session.__file__).resolve()
        ),
        "nexen_bridge_sha256": sha256(
            ROOT / "tools" / "nexen_mcp_bridge.py"
        ),
        "native_symbol_table_sha256": sha256(
            ROOT / "src" / "escbank.sym"
        ),
    }
    resume_lineage = None
    if args.resume_state is not None:
        resume_lineage = validate_resume_lineage(
            args.resume_lineage_events.resolve(),
            args.resume_state.resolve(),
            segment_origin_tick,
            rom_hash,
            resume_identity,
            allow_rom_migration=args.allow_resume_rom_migration,
        )
        if (
            args.allow_resume_rom_migration
            and resume_lineage["rom_migration"] is None
        ):
            raise SystemExit(
                "--allow-resume-rom-migration requires the selected ROM to "
                "differ from the checkpoint ROM"
            )
    fresh_boot_configuration = (
        resume_lineage["fresh_boot_campaign_configuration"]
        if resume_lineage is not None
        else {
            "coin_pulses": args.coin_pulses,
            "start_frames": args.start_frames,
        }
    )
    segment_boss_events = [
        event for event in boss_events if event.tick > segment_origin_tick
    ]
    args.output.mkdir(parents=True, exist_ok=False)
    states_dir = args.output / "states"
    shots_dir = args.output / "screenshots"
    states_dir.mkdir()
    shots_dir.mkdir()
    event_path = args.output / "events.jsonl"
    summary_path = args.output / "summary.json"
    retained_rom = args.output / "campaign-rom.sfc"
    shutil.copy2(rom, retained_rom)
    if sha256(retained_rom) != rom_hash:
        raise RuntimeError("retained campaign ROM copy failed authentication")

    scope = (
        "fresh-power-on production-ROM replay of a retained MAME 0.287 "
        "human controller movie, synchronized one-to-one at the logical "
        "$003A92 game-update entry through its live native or interpreted "
        "exact boundary; no save-state load, ROM patch, or "
        "game-state write; organic path "
        "diagnostic, not FPS or full-playthrough proof"
    )
    if resume_lineage is not None:
        scope = (
            "authenticated checkpoint continuation of a fresh-power-on "
            "production-ROM replay of a retained MAME 0.287 human controller "
            "movie, synchronized one-to-one at the logical $003A92 game-update "
            "entry through its live native or interpreted exact boundary; one "
            "declared save-state load, no ROM patch "
            "or game-state write; organic-path "
            "continuation diagnostic, not uninterrupted fresh-boot, FPS, or "
            "full-playthrough proof"
        )
        if resume_lineage["lineage_has_rom_migration"]:
            scope = (
                "explicit cross-ROM checkpoint continuation diagnostic: the "
                "save state is authenticated to its original fresh-power-on "
                "ROM lineage, then resumed under the selected candidate ROM "
                "with all hashes retained; permitted architectural writes are "
                "the verified reset-equivalent executable-video-WRAM refresh "
                "and, only when explicitly requested, a four-byte derived "
                "candidate-private VTIME IRQ-clock initialization; no arcade "
                "game-state or CPU-state write; not "
                "fresh-boot, FPS, or full-playthrough proof"
            )
    if args.continue_oracle_divergences:
        scope += (
            "; oracle-divergence continuation enabled: only the prefix before "
            "the first mismatch is exact-state evidence, while the suffix is "
            "organic controller-path coverage; hard emulator/task/renderer "
            "failures remain fatal"
        )
    if args.gameplay_native == "off":
        scope += (
            "; native-off classification mode: the exact boundary follows the "
            "live $071A route, including a ROM-selected interpreted origin; "
            "any still-armed $071A/$073A gates are cleared after the fresh "
            "gameplay-origin comparison. This is a fresh controller "
            "differential, not an untouched production run"
        )
    if args.diagnose_snes_exec_address is not None:
        scope += (
            "; focused S-CPU exact-execution diagnostic enabled after the "
            "authenticated gameplay origin: one synchronous private debugger "
            "stop captures the requested pre-opcode boundary; no machine write"
        )
        if args.diagnose_snes_trace_tail:
            scope += (
                "; a bounded final S-CPU instruction tail is retained in a "
                "separate disk artifact"
            )
        else:
            scope += "; no instruction transcript"
        if args.diagnose_snes_call_stack:
            scope += (
                "; Nexen's pre-existing debugger call stack is retained "
                "without enabling tracing"
            )
    runtime_memory_writes: list[dict[str, Any]] = []
    if resume_lineage is not None and resume_lineage["rom_migration"] is not None:
        runtime_memory_writes.append(
            {
                "kind": "checkpoint_video_wram_code_refresh",
                "memory_type": "snesWorkRam",
                "offset": VIDEO_WRAM_WORK_OFFSET,
                "cpu_address": VIDEO_WRAM_CPU_ADDRESS,
                "length": VIDEO_WRAM_LENGTH,
                "source": "selected ROM reset-copy region",
                "game_state_write": False,
                "fresh_boot_proof": False,
            }
        )
        if args.migrate_vtime_irq_clock:
            runtime_memory_writes.append(
                {
                    "kind": "checkpoint_vtime_irq_clock_initialization",
                    "memory_type": "snesMemory",
                    "cpu_address": (
                        VTIME_STATE_CPU_ADDRESS + VTIME_CLOCK_PHASE_OFFSET
                    ),
                    "length": 4,
                    "source": (
                        "derived from authenticated predecessor VTIME "
                        "fractional phase/countdown"
                    ),
                    "game_state_write": False,
                    "fresh_boot_proof": False,
                }
            )
    provenance = {
        "scope": scope,
        "lineage_kind": (
            "checkpoint_continuation"
            if resume_lineage is not None
            else "fresh_power_on_root"
        ),
        "time_unix": time.time(),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(rom),
        "rom_sha256": rom_hash,
        "rom_size": len(rom_data),
        "retained_rom": str(retained_rom),
        "retained_rom_sha256": rom_hash,
        "testflag": 0,
        "emulator": str(args.mesen.resolve()),
        "emulator_sha256": sha256(args.mesen),
        "emulator_identity": emulator_identity,
        "mame": mame["path"],
        "mame_sha256": mame["sha256"],
        "mame_version": mame["version"],
        "mame_snap_revision": mame["snap_revision"],
        "mame_gnome_content_revision": mame[
            "gnome_content_revision"
        ],
        "mame_movie": str(MAME_MOVIE),
        "mame_movie_sha256": sha256(MAME_MOVIE),
        "mame_timeline": str(args.timeline.resolve()),
        "mame_timeline_sha256": sha256(args.timeline),
        "boss_fixtures": str(args.boss_fixtures.resolve()),
        "boss_fixtures_sha256": sha256(args.boss_fixtures),
        "mame_origin_work": str(args.mame_origin_work.resolve()),
        "mame_origin_work_sha256": sha256(args.mame_origin_work),
        "mame_origin_credits_f01c62": mame_origin_credits,
        "mame_origin_tick": args.mame_origin_tick,
        "exact_boundary_tool": "run_to_exact_exec_stop",
        "campaign_script_sha256": resume_identity[
            "campaign_script_sha256"
        ],
        "checkpoint_validator_sha256": resume_identity[
            "checkpoint_validator_sha256"
        ],
        "mcp_python_client_sha256": resume_identity[
            "mcp_python_client_sha256"
        ],
        "nexen_bridge_sha256": resume_identity[
            "nexen_bridge_sha256"
        ],
        "native_symbol_table_sha256": resume_identity[
            "native_symbol_table_sha256"
        ],
        "segment_origin_tick": segment_origin_tick,
        "mame_end_tick": args.mame_end_tick,
        "runtime_memory_writes": runtime_memory_writes,
        "resume_lineage": resume_lineage,
        "input_transport": "real port-0 controller override",
        "campaign_configuration": {
            "cold_boot_frame": args.cold_boot_frame,
            "retained_boot_screen_frames": sorted(
                set(args.retain_boot_screen_frame)
            ),
            "expected_origin_rng": args.expected_origin_rng,
            "coin_pulses": args.coin_pulses,
            "coin_frames": args.coin_frames,
            "coin_gap_frames": args.coin_gap_frames,
            "credited_wait_frames": args.credited_wait_frames,
            "expected_credited_prompt_credits": args.coin_pulses,
            "expected_gameplay_origin_credits": args.coin_pulses - 1,
            "start_frames": args.start_frames,
            "spawn_timeout_frames": args.spawn_timeout_frames,
            "sample_ticks": args.sample_ticks,
            "checkpoint_ticks": args.checkpoint_ticks,
            "migrate_vtime_irq_clock": args.migrate_vtime_irq_clock,
            "retain_input_prestates": {
                "all_transitions": args.retain_input_prestate,
                "selected_ticks": sorted(
                    set(args.retain_input_prestate_tick)
                ),
            },
            "exact_tick_boundary": {
                "logical_seam": "pre-body $003A92 game-update entry",
                "sa1_address": f"{ENTRY_3A92_NATIVE:06X}",
                "mame_boundary": (
                    "first $F00000 read in $003A92 prologue; PC $003AA4 "
                    "under MAME prefetch"
                ),
                "route": (
                    "MCP-private counted synchronous pre-opcode stop; one "
                    "resume per requested span and one-shot removal"
                ),
                "tool": "run_to_exact_exec_stop",
                "debugger_control_extension_only": True,
                "debugger_control_build_modified": True,
                "control_extension_only": True,
                "emulation_core_or_rom_modified": True,
                "emulation_semantics_or_rom_modified": False,
                "one_to_one_across_0818_overruns": True,
            },
            "post_gate_exact_tick_boundary": (
                {
                    "logical_seam": (
                        "rising virtual-PC edge before interpreted $003A92 "
                        "body"
                    ),
                    "iram_address": f"{M68K_PC_IRAM:04X}",
                    "virtual_pc_value": f"{M68K_GAME_UPDATE_ENTRY:06X}",
                    "tool": "run_to_exact_iram_exec_edge",
                    "edge": "rising",
                    "why_not_native_sa1_address": (
                        "$92:DB82 is intentionally unreachable after "
                        "$071A/$073A are cleared"
                    ),
                    "debugger_control_extension_only": True,
                    "emulation_semantics_or_rom_modified": False,
                }
                if args.gameplay_native == "off"
                else None
            ),
            "strict_player_reference": args.strict_player_reference,
            "allow_incomplete_coverage": args.allow_incomplete_coverage,
            "gameplay_native": args.gameplay_native,
            "diagnose_snes_exec_address": (
                f"{args.diagnose_snes_exec_address:06X}"
                if args.diagnose_snes_exec_address is not None
                else None
            ),
            "diagnose_snes_exec_max_frames": (
                args.diagnose_snes_exec_max_frames
            ),
            "diagnose_snes_trace_tail": args.diagnose_snes_trace_tail,
            "diagnose_snes_call_stack": args.diagnose_snes_call_stack,
            "continue_oracle_divergences": (
                args.continue_oracle_divergences
            ),
            "retained_boundary_states": sorted(
                set(args.retain_boundary_state)
            ),
            "safe_checkpoint_ticks": sorted(
                set(args.safe_checkpoint_tick)
            ),
            "input_apply_delay_entries": args.input_apply_delay_entries,
            "retain_input_prestate": args.retain_input_prestate,
        },
        "controller_alignment": {
            "gameplay_origin_mame_tick": args.mame_origin_tick,
            "gameplay_origin_rng_address": "F0170E",
            "gameplay_origin_rng_expected": args.expected_origin_rng,
            "input_apply_boundary": (
                "T"
                if args.input_apply_delay_entries == 0
                else "T+1 $003A92 entry (diagnostic)"
            ),
            "input_response_compare_boundary": "T+2 tick start",
            "basis": (
                "MAME $003A92 tick-start / SNES virtual-PC $003A92 rising "
                "edge after classification gates are cleared; unlike $0818, "
                "this remains one-to-one across a pending-IRQ overrun"
                if args.gameplay_native == "off"
                else "MAME $003A92 tick-start / SNES native $003A92 entry; "
                "unlike $0818, this remains one-to-one across a pending-IRQ "
                "overrun"
            ),
        },
        # A safe-checkpoint continuation is part of the same authenticated
        # fresh controller movie.  Test the requested buttons across that
        # whole movie prefix, not just this child segment: otherwise a
        # control exercised before a checkpoint (for example A) is
        # spuriously reported absent when the later segment has no new A
        # edge.  The timeline digest is part of the resume identity, so this
        # remains bound to the same original controller evidence.
        "input_coverage": campaign_input_coverage(
            inputs,
            args.mame_origin_tick,
            args.mame_end_tick,
            root_initial_buttons,
            cold_boot_coin_pulses=int(
                fresh_boot_configuration.get("coin_pulses", 0)
            ),
            cold_boot_start_frames=int(
                fresh_boot_configuration.get("start_frames", 0)
            ),
        ),
        "segment_input_coverage": campaign_input_coverage(
            inputs,
            segment_origin_tick,
            args.mame_end_tick,
            initial_buttons,
            cold_boot_coin_pulses=0,
            cold_boot_start_frames=0,
        ),
    }
    prefix_context = (
        resume_lineage["resume_context"]
        if resume_lineage is not None
        else {}
    )
    summary: dict[str, Any] = {
        **provenance,
        "result": "red",
        "failure": None,
        "cold_boot": {},
        "processed_input_transitions": int(
            prefix_context.get("processed_input_transitions", 0)
        ),
        "boss_events_green": int(
            prefix_context.get("boss_events_green", 0)
        ),
        "boss_events_red": int(prefix_context.get("boss_events_red", 0)),
        "boss_events_total": len(boss_events),
        "player_reference_green": int(
            prefix_context.get("player_reference_green", 0)
        ),
        "player_reference_red": int(
            prefix_context.get("player_reference_red", 0)
        ),
        "death_reference_green": int(
            prefix_context.get("death_reference_green", 0)
        ),
        "death_reference_red": int(
            prefix_context.get("death_reference_red", 0)
        ),
        "oracle_divergence_count": int(
            prefix_context.get("oracle_divergence_count", 0)
        ),
        "oracle_divergence_kinds": dict(
            prefix_context.get("oracle_divergence_kinds", {})
        ),
        "first_oracle_divergence": prefix_context.get(
            "first_oracle_divergence"
        ),
        "pre_failure_states": list(
            prefix_context.get("pre_failure_states", [])
        ),
        "deaths_observed": list(
            prefix_context.get("deaths_observed", [])
        ),
        "actions_observed": [],
        "action_milestones": [],
        "x1_control_pairs_observed": [],
        "states": [],
        "screenshots": [],
        "samples": int(prefix_context.get("samples", 0)),
        "prefix_coverage": prefix_context,
    }
    actions_seen: set[int] = set()
    latest_input_prestate: dict[str, Any] | None = None

    with event_path.open("x", encoding="utf-8") as log:
        emit(log, "provenance", **provenance)
        try:
            with AuditedMcpSession(
                rom=rom,
                mesen=args.mesen.resolve(),
                cwd=ROOT,
                port=args.port,
                boot_wait=6.0,
                socket_timeout=300.0,
                stderr_log=args.output / "emulator.stderr.log",
            ) as m:
                _ACTIVE_SESSION = m
                _ACTIVE_STATE_DIR = states_dir
                _ACTIVE_SHOT_DIR = shots_dir
                pause_for_startup(m)
                mapped_origin_tick = segment_origin_tick
                if args.resume_state is None:
                    # Continuous cold-boot lineage: never load a state.
                    boot_runs: list[dict[str, Any]] = []
                    boot_screens: list[dict[str, Any]] = []
                    for requested_frame in sorted(
                        set(args.retain_boot_screen_frame)
                    ):
                        boot_runs.extend(
                            run_exact_frames(
                                m,
                                0,
                                max(
                                    0,
                                    requested_frame
                                    - int(m.get_state()["frameCount"]),
                                ),
                            )
                        )
                        observed_frame = int(
                            m.get_state().get("frameCount", 0)
                        )
                        retained = {
                            "requested_frame": requested_frame,
                            "observed_frame": observed_frame,
                            "screenshot": screenshot(
                                m,
                                shots_dir
                                / f"boot-screen-frame-{observed_frame:05d}.png",
                            ),
                        }
                        boot_screens.append(retained)
                        summary["screenshots"].append(
                            retained["screenshot"]
                        )
                    boot_runs.extend(
                        run_exact_frames(
                            m,
                            0,
                            max(
                                0,
                                args.cold_boot_frame
                                - int(m.get_state()["frameCount"]),
                            ),
                        )
                    )
                    cold_title = {
                        "snapshot": detailed_snapshot(
                            m, [0] * 16, "cold_title", args.mame_origin_tick
                        ),
                        "state": save_state(m, states_dir / "cold-title.mss"),
                        "screenshot": screenshot(
                            m, shots_dir / "cold-title.png"
                        ),
                    }
                    summary["states"].append(cold_title["state"])
                    summary["screenshots"].append(cold_title["screenshot"])

                    coin_runs = run_coin_pulses(
                        m,
                        args.coin_pulses,
                        args.coin_frames,
                        args.coin_gap_frames,
                    )
                    credited_runs = run_exact_frames(
                        m, 0, args.credited_wait_frames
                    )
                    credited = {
                        "snapshot": detailed_snapshot(
                            m,
                            [0] * 16,
                            "credited_prompt",
                            args.mame_origin_tick,
                        ),
                        "state": save_state(
                            m, states_dir / "credited-prompt.mss"
                        ),
                        "screenshot": screenshot(
                            m, shots_dir / "credited-prompt.png"
                        ),
                    }
                    summary["states"].append(credited["state"])
                    summary["screenshots"].append(
                        credited["screenshot"]
                    )
                    credited_count = int(
                        credited["snapshot"]["credits"]
                    )
                    if credited_count != args.coin_pulses:
                        raise CampaignFailure(
                            "hardware-boundary/timing_or_boot_alignment",
                            {
                                "reason": "credited_prompt_credit_mismatch",
                                "credit_address": "F01C62",
                                "expected_credits": args.coin_pulses,
                                "observed_credits": credited_count,
                                "coin_sequence": coin_runs,
                            },
                        )
                    start_runs = run_exact_frames(
                        m, McpSession.BTN_START, args.start_frames
                    )

                    # Advance one exact game-update entry at a time and retain
                    # the first stable pre-body boundary after the organic
                    # player-spawn update has initialized 20 HP.  Ordinary
                    # write hooks notify asynchronously and are not an exact
                    # stop primitive.
                    set_held_input(m, 0)
                    spawn_entry_spans: list[dict[str, Any]] = []
                    spawn_observation: dict[str, Any] | None = None
                    for entry_index in range(1, args.spawn_timeout_frames + 1):
                        span = run_active_game_update_entries(m, 1)[0]
                        player = player_snapshot(m)
                        if int(player["health"]) == 20:
                            spawn_entry_spans.append(span)
                            spawn_observation = {
                                "entry_index": entry_index,
                                "player": player,
                                "snes_tick": tick16(m),
                                "video_frame": int(
                                    m.get_state().get("frameCount", 0)
                                ),
                            }
                            break
                    if spawn_observation is None:
                        raise CampaignFailure(
                            "interpreter_or_native_hle",
                            {
                                "reason": (
                                    "player_spawn_health_missing_at_exact_entry"
                                ),
                                "entry_budget": args.spawn_timeout_frames,
                            },
                        )
                    spawn_run = {
                        "reason": "exact_game_update_entry",
                        "entry_spans": spawn_entry_spans,
                        "observation": spawn_observation,
                    }

                    summary["cold_boot"] = {
                        "boot_runs": boot_runs,
                        "boot_screens": boot_screens,
                        "coin_runs": coin_runs,
                        "credited_runs": credited_runs,
                        "start_runs": start_runs,
                        "spawn_run": spawn_run,
                        "cold_title": cold_title,
                        "credited_prompt": credited,
                    }
                else:
                    restore_mutation_start = len(
                        m.architectural_mutations
                    )
                    load_response = m.load_state(
                        args.resume_state.resolve()
                    )
                    require_paused(m, "checkpoint load")
                    checkpoint_state = resume_lineage["checkpoint"]
                    expected_machine = checkpoint_state.get(
                        "resume_validation"
                    )
                    iram_info = checkpoint_state.get("resume_sa1_iram")
                    if (
                        checkpoint_state.get(
                            "resumable_checkpoint"
                        )
                        is not True
                        or checkpoint_state.get("boundary_kind")
                        != "post_entry_safe_snes_boundary"
                        or checkpoint_state.get(
                            "entry_exact_bundle"
                        )
                        is not False
                        or checkpoint_state.get(
                            "nested_sa1_entry_nonresumable"
                        )
                        is not False
                        or not isinstance(expected_machine, dict)
                        or not isinstance(iram_info, dict)
                    ):
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": (
                                    "resume_requires_atomic_post_entry_safe_"
                                    "bundle"
                                )
                            },
                        )
                    iram_path = Path(str(iram_info.get("path", "")))
                    if (
                        not iram_path.is_file()
                        or iram_path.stat().st_size != 0x800
                        or sha256(iram_path) != iram_info.get("sha256")
                    ):
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": "resume_sa1_iram_sidecar_invalid",
                                "path": str(iram_path),
                            },
                        )
                    loaded_public, loaded_raw = checkpoint_machine_snapshot(m)
                    expected_iram = iram_path.read_bytes()
                    if (
                        loaded_public != expected_machine
                        or loaded_raw[0] != expected_iram
                    ):
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": (
                                    "atomic_checkpoint_load_state_mismatch"
                                ),
                                "public_equal": (
                                    loaded_public == expected_machine
                                ),
                                "iram_equal": loaded_raw[0] == expected_iram,
                                "expected": expected_machine,
                                "observed": loaded_public,
                            },
                        )
                    resume_context = resume_lineage["resume_context"]
                    if tick16(m) != int(resume_context["snes_tick"]):
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": "resume_snes_tick_mismatch",
                                "expected": resume_context["snes_tick"],
                                "observed": tick16(m),
                            },
                        )
                    checkpoint_buttons = int(
                        resume_context["current_buttons"]
                    )
                    expected_checkpoint_buttons = buttons_at_tick(
                        inputs,
                        args.mame_origin_tick,
                        segment_origin_tick - 1,
                    )
                    if checkpoint_buttons != expected_checkpoint_buttons:
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": "resume_controller_context_mismatch",
                                "timeline_buttons_before_resume": (
                                    expected_checkpoint_buttons
                                ),
                                "checkpoint_buttons": checkpoint_buttons,
                            },
                        )
                    if initial_buttons != checkpoint_buttons:
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": (
                                    "resume_segment_initial_input_mismatch"
                                ),
                                "resume_tick": segment_origin_tick,
                                "timeline_buttons_before_resume": (
                                    initial_buttons
                                ),
                                "checkpoint_buttons": checkpoint_buttons,
                            },
                        )
                    load_mutations = m.architectural_mutations[
                        restore_mutation_start:
                    ]
                    if load_mutations:
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": (
                                    "checkpoint_atomic_load_used_"
                                    "architectural_transplant"
                                ),
                                "mutations": compact_architectural_mutations(
                                    load_mutations
                                ),
                            },
                        )
                    migration_validation = None
                    if resume_lineage["rom_migration"] is not None:
                        migration_mutation_start = len(
                            m.architectural_mutations
                        )
                        refresh = refresh_video_wram(m, rom)
                        vtime_clock_migration = None
                        if args.migrate_vtime_irq_clock:
                            vtime_clock_migration = migrate_vtime_irq_clock(m)
                        migrated_public, migrated_raw = (
                            checkpoint_machine_snapshot(m)
                        )
                        migration_mutations = m.architectural_mutations[
                            migration_mutation_start:
                        ]
                        try:
                            migration_validation = (
                                validate_video_wram_migration(
                                    before_public=loaded_public,
                                    before_raw=loaded_raw,
                                    after_public=migrated_public,
                                    after_raw=migrated_raw,
                                    selected_rom=rom,
                                    refresh=refresh,
                                    mutations=migration_mutations,
                                    vtime_clock_migration=(
                                        vtime_clock_migration
                                    ),
                                )
                            )
                        except RuntimeError as exc:
                            raise CampaignFailure(
                                "stale save-state data",
                                {
                                    "reason": (
                                        "checkpoint_rom_migration_"
                                        "verification_failed"
                                    ),
                                    "error": str(exc),
                                    "mutations": (
                                        compact_architectural_mutations(
                                            migration_mutations
                                        )
                                    ),
                                },
                            ) from exc
                    restore_mutations = m.architectural_mutations[
                        restore_mutation_start:
                    ]
                    set_held_input(m, checkpoint_buttons)
                    resume_entry_spans = run_active_game_update_entries(m, 1)
                    resume_boundary_mode = resume_entry_spans[-1][
                        "active_gate"
                    ]["mode"]
                    if not at_active_game_update_entry(
                        m, resume_boundary_mode
                    ):
                        raise CampaignFailure(
                            "hardware-boundary/timing",
                            {
                                "reason": (
                                    "safe_checkpoint_failed_to_reach_resume_"
                                    "entry"
                                ),
                                "resume_tick": segment_origin_tick,
                                "observed_sa1_pc": f"{sa1_pc(m):06X}",
                                "boundary_mode": resume_boundary_mode,
                                "entry_spans": resume_entry_spans,
                            },
                        )
                    summary["resume"] = {
                        "load_response": load_response,
                        "state": str(args.resume_state.resolve()),
                        "state_sha256": sha256(args.resume_state),
                        "lineage": resume_lineage,
                        "restored_buttons": checkpoint_buttons,
                        "resume_tick_buttons": buttons_at_tick(
                            inputs,
                            args.mame_origin_tick,
                            segment_origin_tick,
                        ),
                        "resume_tick_input_edge": (
                            buttons_at_tick(
                                inputs,
                                args.mame_origin_tick,
                                segment_origin_tick,
                            )
                            != checkpoint_buttons
                        ),
                        "atomic_load_verified": True,
                        "architectural_mutations_during_restore": (
                            compact_architectural_mutations(
                                restore_mutations
                            )
                        ),
                        "no_cpu_or_memory_transplant": (
                            not restore_mutations
                        ),
                        "no_game_or_cpu_state_transplant": True,
                        "rom_migration": migration_validation,
                        "phase": resume_context.get("phase"),
                        "safe_boundary_to_resume_entry": (
                            resume_entry_spans
                        ),
                    }

                if args.resume_state is None:
                    origin_entry_spans = spawn_entry_spans
                    summary["cold_boot"][
                        "gameplay_origin_entry"
                    ] = origin_entry_spans
                else:
                    resume_boundary_mode = resume_entry_spans[-1][
                        "active_gate"
                    ]["mode"]
                    if (
                        resume_context.get("phase")
                        != "post_entry_safe_snes_boundary"
                        or not at_active_game_update_entry(
                            m, resume_boundary_mode
                        )
                    ):
                        raise CampaignFailure(
                            "stale save-state data",
                            {
                                "reason": (
                                    "resume_is_not_at_game_update_entry"
                                ),
                                "expected_phase": (
                                    "post_entry_safe_snes_boundary"
                                ),
                                "observed_phase": resume_context.get("phase"),
                                "expected_sa1_pc": (
                                    f"{ENTRY_3A92_NATIVE:06X}"
                                ),
                                "observed_sa1_pc": f"{sa1_pc(m):06X}",
                                "boundary_mode": resume_boundary_mode,
                            },
                        )

                snes_origin_tick = tick16(m)
                origin_reference = tick_rows[mapped_origin_tick]
                origin_player = player_snapshot(m)
                origin_compare = compare_player(origin_player, origin_reference)
                if args.strict_player_reference and origin_compare["result"] != "green":
                    raise CampaignFailure(
                        "hardware-boundary/timing_or_boot_alignment",
                        {
                            "reason": "gameplay_origin_player_mismatch",
                            "mame_tick": mapped_origin_tick,
                            "comparison": origin_compare,
                        },
                    )

                floor_raw = bytes(
                    m.read_memory("snesMemory", TASK_FLOOR_START, 16 * 4)
                )
                floors = [
                    int.from_bytes(
                        floor_raw[index * 4 : index * 4 + 4], "big"
                    )
                    for index in range(16)
                ]
                origin = detailed_snapshot(
                    m,
                    floors,
                    (
                        "resume_origin"
                        if args.resume_state is not None
                        else "gameplay_origin"
                    ),
                    mapped_origin_tick,
                )
                if (
                    args.resume_state is None
                    and int(origin["rng_state"]) != args.expected_origin_rng
                ):
                    raise CampaignFailure(
                        "hardware-boundary/timing_or_boot_alignment",
                        {
                            "reason": "gameplay_origin_rng_mismatch",
                            "mame_tick": mapped_origin_tick,
                            "rng_address": "F0170E",
                            "expected_rng": args.expected_origin_rng,
                            "observed_rng": int(origin["rng_state"]),
                            "cold_boot_frame": args.cold_boot_frame,
                        },
                    )
                if args.resume_state is None:
                    expected_origin_credits = args.coin_pulses - 1
                    if int(origin["credits"]) != expected_origin_credits:
                        raise CampaignFailure(
                            "hardware-boundary/timing_or_boot_alignment",
                            {
                                "reason": "gameplay_origin_credit_mismatch",
                                "mame_tick": mapped_origin_tick,
                                "credit_address": "F01C62",
                                "expected_credits": expected_origin_credits,
                                "observed_credits": int(origin["credits"]),
                                "coin_pulses": args.coin_pulses,
                            },
                        )
                    if int(origin["credits"]) != mame_origin_credits:
                        raise CampaignFailure(
                            "stale save-state data_or_input_lineage",
                            {
                                "reason": "mame_origin_credit_lineage_mismatch",
                                "mame_tick": mapped_origin_tick,
                                "credit_address": "F01C62",
                                "mame_credits": mame_origin_credits,
                                "snes_credits": int(origin["credits"]),
                                "coin_pulses": args.coin_pulses,
                                "mame_origin_work": str(
                                    args.mame_origin_work.resolve()
                                ),
                            },
                        )
                origin_stem = (
                    "resume-origin"
                    if args.resume_state is not None
                    else "gameplay-origin"
                )
                origin_state = save_state(
                    m, states_dir / f"{origin_stem}.mss"
                )
                origin_shot = screenshot(
                    m, shots_dir / f"{origin_stem}.png"
                )
                summary["states"].append(origin_state)
                summary["screenshots"].append(origin_shot)
                origin_record = {
                    "origin": origin,
                    "origin_state": origin_state,
                    "origin_screenshot": origin_shot,
                    "origin_player_comparison": origin_compare,
                }
                if args.resume_state is None:
                    summary["cold_boot"].update(origin_record)
                else:
                    summary["resume"].update(origin_record)
                emit(
                    log,
                    (
                        "resume_origin"
                        if args.resume_state is not None
                        else "gameplay_origin"
                    ),
                    mame_tick=mapped_origin_tick,
                    snes_tick=snes_origin_tick,
                    player=origin_player,
                    comparison=origin_compare,
                    frame=int(m.get_state().get("frameCount", 0)),
                )

                if args.diagnose_snes_exec_address is not None:
                    address = args.diagnose_snes_exec_address
                    if not 0 <= address <= 0xFFFFFF:
                        raise CampaignFailure(
                            "harness_or_unclassified",
                            {
                                "reason": "diagnostic_snes_address_out_of_range",
                                "address": address,
                            },
                        )
                    if args.diagnose_snes_exec_max_frames <= 0:
                        raise CampaignFailure(
                            "harness_or_unclassified",
                            {
                                "reason": "diagnostic_snes_frame_budget_invalid",
                                "frame_budget": (
                                    args.diagnose_snes_exec_max_frames
                                ),
                            },
                        )
                    if not 0 <= args.diagnose_snes_trace_tail <= 1000:
                        raise CampaignFailure(
                            "harness_or_unclassified",
                            {
                                "reason": "diagnostic_snes_trace_tail_invalid",
                                "trace_tail": args.diagnose_snes_trace_tail,
                            },
                        )
                    trace_enable_response: dict[str, Any] | None = None
                    if args.diagnose_snes_trace_tail:
                        trace_enable_response = dict(
                            m.trace_log(count=1, cpu_type="Snes")
                        )
                    response = dict(
                        m.tool(
                            "run_to_exact_exec_stop",
                            {
                                "address": address,
                                "cpuType": "Snes",
                                "maxFrames": (
                                    args.diagnose_snes_exec_max_frames
                                ),
                                "occurrences": 1,
                            },
                        )
                    )
                    snes_cpu = dict(m.get_cpu_state("Snes"))
                    stopped_address = (
                        ((int(snes_cpu.get("k", 0)) & 0xFF) << 16)
                        | (int(snes_cpu.get("pc", 0)) & 0xFFFF)
                    )
                    window_start = (
                        (address & 0xFF0000)
                        | ((address - 8) & 0xFFFF)
                    )
                    trace_artifact: dict[str, Any] | None = None
                    if args.diagnose_snes_trace_tail:
                        trace_path = args.output / "snes-trace-tail.json"
                        trace = dict(
                            m.trace_log(
                                count=args.diagnose_snes_trace_tail,
                                cpu_type="Snes",
                            )
                        )
                        trace_path.write_text(
                            json.dumps(trace, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        trace_artifact = {
                            "path": str(trace_path.resolve()),
                            "sha256": sha256(trace_path),
                            "requested_tail_rows": (
                                args.diagnose_snes_trace_tail
                            ),
                            "trace_enable_response": trace_enable_response,
                        }
                    call_stack_artifact: dict[str, Any] | None = None
                    if args.diagnose_snes_call_stack:
                        call_stack_path = args.output / "snes-call-stack.json"
                        call_stack = dict(
                            m.tool(
                                "get_call_stack", {"cpuType": "Snes"}
                            )
                        )
                        call_stack_path.write_text(
                            json.dumps(
                                call_stack, indent=2, sort_keys=True
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        call_stack_artifact = {
                            "path": str(call_stack_path.resolve()),
                            "sha256": sha256(call_stack_path),
                            "frame_count": int(call_stack.get("count", 0)),
                        }
                    detail = {
                        "reason": (
                            "focused_snes_exec_stop_reached"
                            if stopped_address == address
                            and response.get("reason") == "breakpoint"
                            and response.get("hit") is True
                            else "focused_snes_exec_stop_not_reached"
                        ),
                        "requested_address": f"{address:06X}",
                        "stopped_address": f"{stopped_address:06X}",
                        "frame_budget": args.diagnose_snes_exec_max_frames,
                        "response": response,
                        "opcode_window_start": f"{window_start:06X}",
                        "opcode_window_hex": bytes(
                            m.read_memory("snesMemory", window_start, 16)
                        ).hex(),
                        "terminal_snapshot": (
                            game_update_wait_terminal_snapshot(
                                m, dict(m.get_cpu_state("Sa1"))
                            )
                        ),
                        "trace_tail_artifact": trace_artifact,
                        "call_stack_artifact": call_stack_artifact,
                        "bounded_trace_tail": bool(trace_artifact),
                        "instruction_transcript": bool(trace_artifact),
                        "architectural_writes": False,
                    }
                    raise CampaignFailure(
                        "focused_snes_control_flow_diagnostic", detail
                    )

                # The cold boot and first matched logical entry establish the
                # title, credit, RNG, spawn, and controller lineage.  An
                # interpreter-only ROM may already have cleared both gates;
                # otherwise clear them only now.  Retain both cases explicitly
                # so a ROM-selected route is not misreported as a debugger
                # mutation.
                if args.gameplay_native == "off":
                    native_controls = []
                    for address in (0x071A, 0x073A):
                        before = le16(
                            m.read_memory("Sa1Memory", address, 2)
                        )
                        if before:
                            m.write_memory("Sa1Memory", address, "0000")
                        native_controls.append(
                            {
                                "kind": "native_gate_classification",
                                "address": f"{address:04X}",
                                "before": before,
                                "after": 0,
                                "changed": bool(before),
                            }
                        )
                    summary["native_gate_controls"] = native_controls
                    emit(
                        log,
                        "native_gate_configuration",
                        mode="off",
                        controls=native_controls,
                        mame_tick=mapped_origin_tick,
                        snes_tick=tick16(m),
                    )

                events_by_tick: dict[int, list[tuple[str, Any]]] = defaultdict(list)
                previous_timeline_health = int(
                    tick_rows[mapped_origin_tick]["health"]
                )
                for tick in sorted(tick_rows):
                    if tick <= mapped_origin_tick:
                        continue
                    row = tick_rows[tick]
                    health = int(row["health"])
                    if (
                        player_health_alive(previous_timeline_health)
                        and not player_health_alive(health)
                    ):
                        if tick - 1 > mapped_origin_tick:
                            events_by_tick[tick - 1].append(
                                ("death_pre", row)
                            )
                        events_by_tick[tick].append(("death_compare", row))
                    elif (
                        not player_health_alive(previous_timeline_health)
                        and player_health_alive(health)
                    ):
                        events_by_tick[tick].append(("respawn_compare", row))
                    previous_timeline_health = health
                for event in inputs:
                    if input_transition_belongs_to_segment(
                        event.tick,
                        mapped_origin_tick,
                        resumed=args.resume_state is not None,
                    ):
                        # The movie's tick-T boundary has sampled the newly
                        # observed physical input, but gameplay has not
                        # consumed it yet.  Compare that state first, then
                        # install the SNES controller at the matched native
                        # $3A92 entry.  Both expose its response at T+2.
                        events_by_tick[event.tick].append(
                            ("input_compare", event)
                        )
                        apply_tick = (
                            event.tick + args.input_apply_delay_entries
                        )
                        if apply_tick <= args.mame_end_tick:
                            events_by_tick[apply_tick].append(
                                ("input_apply", event)
                            )
                    if (
                        mapped_origin_tick
                        < event.tick + 2
                        <= args.mame_end_tick
                    ):
                        events_by_tick[event.tick + 2].append(
                            ("input_response_compare", event)
                        )
                for event in boss_events:
                    if event.tick - 1 > mapped_origin_tick:
                        events_by_tick[event.tick - 1].append(("boss_pre", event))
                    if event.tick > mapped_origin_tick:
                        events_by_tick[event.tick].append(("boss", event))
                for boundary_tick in sorted(
                    set(args.retain_boundary_state)
                ):
                    if boundary_tick > mapped_origin_tick:
                        events_by_tick[boundary_tick].append(
                            ("retained_boundary_state", boundary_tick)
                        )
                sample = (
                    (
                        (mapped_origin_tick + args.sample_ticks)
                        // args.sample_ticks
                    )
                    * args.sample_ticks
                )
                while sample <= args.mame_end_tick:
                    events_by_tick[sample].append(("sample", sample))
                    sample += args.sample_ticks
                checkpoint = (
                    (
                        mapped_origin_tick
                        + args.checkpoint_ticks
                    )
                    // args.checkpoint_ticks
                    * args.checkpoint_ticks
                )
                while checkpoint <= args.mame_end_tick:
                    events_by_tick[checkpoint].append(("checkpoint", checkpoint))
                    checkpoint += args.checkpoint_ticks
                for safe_tick in sorted(set(args.safe_checkpoint_tick)):
                    if safe_tick > mapped_origin_tick:
                        events_by_tick[safe_tick].append(
                            ("safe_checkpoint", safe_tick)
                        )
                events_by_tick[args.mame_end_tick].append(
                    ("campaign_end", args.mame_end_tick)
                )

                current_mame_tick = mapped_origin_tick
                current_buttons = initial_buttons
                previous_player = origin_player
                actions_seen = (
                    set(
                        int(value)
                        for value in resume_lineage["resume_context"].get(
                            "actions_seen", []
                        )
                    )
                    if resume_lineage is not None
                    else set()
                )
                actions_seen.add(int(origin_player["action"]))
                retained_action_milestones = set(actions_seen)
                x1_control_pairs_seen = {
                    (
                        int(origin_player["x1_ctrl_3601"]),
                        int(origin_player["x1_ctrl_3603"]),
                    )
                }
                last_render_complete = int(origin["render_complete"])
                last_frame_request = int(origin["frame_request"])
                processed_inputs = int(
                    prefix_context.get("processed_input_transitions", 0)
                )

                for target_tick in sorted(events_by_tick):
                    if target_tick < current_mame_tick:
                        continue
                    entry_count = game_update_entries_between_ticks(
                        current_mame_tick, target_tick
                    )
                    spans = (
                        run_active_game_update_entries(m, entry_count)
                        if entry_count
                        else []
                    )
                    current_mame_tick = target_tick
                    if final_span_is_interpreted(spans):
                        # Retain the debugger's own counted rising-edge reply;
                        # the native address is deliberately absent in this
                        # configuration, so a final virtual PC alone would
                        # be weaker evidence than the exact-stop contract.
                        emit(
                            log,
                            "interpreted_game_update_boundary",
                            mame_tick=target_tick,
                            spans=spans,
                        )
                    light_player = player_snapshot(m)
                    x1_control_pairs_seen.add(
                        (
                            int(light_player["x1_ctrl_3601"]),
                            int(light_player["x1_ctrl_3603"]),
                        )
                    )
                    action = int(light_player["action"])
                    actions_seen.add(action)
                    if action not in retained_action_milestones:
                        action_name = ACTION_NAMES.get(
                            action, f"unknown_{action:02x}"
                        )
                        milestone_state = save_state(
                            m,
                            states_dir
                            / (
                                f"first-action-{action:02d}-"
                                f"{action_name}-tick-{target_tick:05d}.mss"
                            ),
                        )
                        milestone_shot = screenshot(
                            m,
                            shots_dir
                            / (
                                f"first-action-{action:02d}-"
                                f"{action_name}-tick-{target_tick:05d}.png"
                            ),
                        )
                        milestone = {
                            "action": action,
                            "name": action_name,
                            "mame_tick": target_tick,
                            "snes_tick": tick16(m),
                            "video_frame": int(
                                m.get_state().get("frameCount", 0)
                            ),
                            "buttons": current_buttons,
                            "player": light_player,
                            "state": milestone_state,
                            "screenshot": milestone_shot,
                        }
                        retained_action_milestones.add(action)
                        summary["action_milestones"].append(milestone)
                        summary["states"].append(milestone_state)
                        summary["screenshots"].append(milestone_shot)
                        emit(log, "action_milestone", **milestone)
                    if (
                        player_health_alive(
                            int(previous_player["health"])
                        )
                        and not player_health_alive(
                            int(light_player["health"])
                        )
                    ):
                        death = {
                            "mame_tick": target_tick,
                            "frame": int(m.get_state().get("frameCount", 0)),
                            "before": previous_player,
                            "after": light_player,
                        }
                        summary["deaths_observed"].append(death)
                        emit(log, "death", **death)
                    previous_player = light_player

                    if halt16(m):
                        raise CampaignFailure(
                            "interpreter_or_native_hle",
                            {
                                "reason": "interpreter_halt",
                                "mame_tick": target_tick,
                                "halt": halt16(m),
                            },
                        )

                    for kind, payload in events_by_tick[target_tick]:
                        if kind == "death_pre":
                            death_tick = target_tick + 1
                            state = save_state(
                                m,
                                states_dir
                                / f"pre-death-tick-{death_tick:05d}.mss",
                            )
                            summary["states"].append(state)
                            emit(
                                log,
                                "death_pre_state",
                                mame_tick=target_tick,
                                death_tick=death_tick,
                                snes_tick=tick16(m),
                                frame=int(
                                    m.get_state().get("frameCount", 0)
                                ),
                                player=light_player,
                                expected_after=payload,
                                state=state,
                            )
                        elif kind in ("death_compare", "respawn_compare"):
                            comparison = compare_player(light_player, payload)
                            if comparison["result"] == "green":
                                summary["death_reference_green"] += 1
                            else:
                                summary["death_reference_red"] += 1
                            emit(
                                log,
                                kind,
                                mame_tick=target_tick,
                                snes_tick=tick16(m),
                                frame=int(m.get_state().get("frameCount", 0)),
                                player=light_player,
                                comparison=comparison,
                                spans=spans,
                            )
                            if comparison["result"] != "green":
                                divergence = {
                                    "event": kind,
                                    "comparison": comparison,
                                }
                                record_oracle_divergence(
                                    summary,
                                    log,
                                    states_dir,
                                    latest_input_prestate,
                                    kind=kind,
                                    mame_tick=target_tick,
                                    detail=divergence,
                                )
                                if not args.continue_oracle_divergences:
                                    raise CampaignFailure(
                                        "interpreter_native_or_timing",
                                        {
                                            "reason": (
                                                "organic_death_or_respawn_diverged"
                                            ),
                                            **divergence,
                                            "mame_tick": target_tick,
                                        },
                                    )
                        elif kind == "input_compare":
                            input_event: InputEvent = payload
                            comparison = compare_player(
                                light_player, input_event.reference
                            )
                            if comparison["result"] == "green":
                                summary["player_reference_green"] += 1
                            else:
                                summary["player_reference_red"] += 1
                            emit(
                                log,
                                "input_compare",
                                mame_tick=target_tick,
                                snes_tick=tick16(m),
                                frame=int(m.get_state().get("frameCount", 0)),
                                buttons=current_buttons,
                                expected_buttons=input_event.buttons,
                                player=light_player,
                                comparison=comparison,
                                spans=spans,
                            )
                            if comparison["result"] != "green":
                                divergence = {
                                    "previous_buttons": current_buttons,
                                    "next_buttons": input_event.buttons,
                                    "comparison": comparison,
                                }
                                record_oracle_divergence(
                                    summary,
                                    log,
                                    states_dir,
                                    latest_input_prestate,
                                    kind="input_compare",
                                    mame_tick=target_tick,
                                    detail=divergence,
                                )
                            if (
                                comparison["result"] != "green"
                                and fail_on_player_reference_mismatch(
                                    args.strict_player_reference,
                                    args.continue_oracle_divergences,
                                )
                            ):
                                raise CampaignFailure(
                                    "interpreter_native_or_timing",
                                    {
                                        "reason": "organic_player_state_diverged",
                                        "mame_tick": target_tick,
                                        "previous_buttons": current_buttons,
                                        "next_buttons": input_event.buttons,
                                        "comparison": comparison,
                                    },
                                )
                        elif kind == "input_response_compare":
                            input_event = payload
                            reference_tick = input_event.tick + 2
                            comparison = compare_player(
                                light_player,
                                tick_rows[reference_tick],
                            )
                            if comparison["result"] == "green":
                                summary["player_reference_green"] += 1
                            else:
                                summary["player_reference_red"] += 1
                            emit(
                                log,
                                "input_response_compare",
                                mame_tick=target_tick,
                                source_input_tick=input_event.tick,
                                snes_tick=tick16(m),
                                frame=int(m.get_state().get("frameCount", 0)),
                                buttons=current_buttons,
                                player=light_player,
                                comparison=comparison,
                                spans=spans,
                            )
                            if comparison["result"] != "green":
                                divergence = {
                                    "source_input_tick": input_event.tick,
                                    "buttons": current_buttons,
                                    "comparison": comparison,
                                }
                                record_oracle_divergence(
                                    summary,
                                    log,
                                    states_dir,
                                    latest_input_prestate,
                                    kind="input_response_compare",
                                    mame_tick=target_tick,
                                    detail=divergence,
                                )
                            if (
                                comparison["result"] != "green"
                                and fail_on_player_reference_mismatch(
                                    args.strict_player_reference,
                                    args.continue_oracle_divergences,
                                )
                            ):
                                raise CampaignFailure(
                                    "hardware-boundary/timing_or_gameplay",
                                    {
                                        "reason": (
                                            "organic_player_input_response_diverged"
                                        ),
                                        "mame_tick": target_tick,
                                        "source_input_tick": input_event.tick,
                                        "buttons": current_buttons,
                                        "comparison": comparison,
                                    },
                                )
                        elif kind == "input_apply":
                            input_event = payload
                            retain_this_input_prestate = (
                                args.retain_input_prestate
                                or input_event.tick
                                in args.retain_input_prestate_tick
                            )
                            if retain_this_input_prestate:
                                prestate_path = (
                                    states_dir / "pre-input-latest.mss"
                                )
                                prestate = save_state(m, prestate_path)
                                latest_input_prestate = {
                                    "mame_tick": target_tick,
                                    "effective_mame_tick": input_event.tick,
                                    "snes_tick": tick16(m),
                                    "buttons_before": current_buttons,
                                    "buttons_after": input_event.buttons,
                                    "label": button_label(input_event.buttons),
                                    "state": prestate,
                                }
                                emit(
                                    log,
                                    "input_pre_state",
                                    **latest_input_prestate,
                                )
                            emit(
                                log,
                                "input_apply",
                                mame_tick=target_tick,
                                effective_mame_tick=input_event.tick,
                                snes_tick=tick16(m),
                                frame=int(m.get_state().get("frameCount", 0)),
                                previous_buttons=current_buttons,
                                buttons=input_event.buttons,
                                label=button_label(input_event.buttons),
                                player=light_player,
                                spans=spans,
                            )
                            set_held_input(m, input_event.buttons)
                            current_buttons = input_event.buttons
                            processed_inputs += 1
                            summary["processed_input_transitions"] = processed_inputs
                            if processed_inputs % args.progress_events == 0:
                                print(
                                    json.dumps(
                                        {
                                            "event": "progress",
                                            "input_events": processed_inputs,
                                            "mame_tick": target_tick,
                                            "snes_tick": tick16(m),
                                            "video_frame": int(
                                                m.get_state().get("frameCount", 0)
                                            ),
                                            "player": light_player,
                                        },
                                        sort_keys=True,
                                    ),
                                    flush=True,
                                )
                        elif kind == "boss_pre":
                            boss: BossEvent = payload
                            path = (
                                states_dir
                                / f"pre-{boss.name}-tick-{target_tick:05d}.mss"
                            )
                            retained = save_state(m, path)
                            summary["states"].append(retained)
                            emit(
                                log,
                                "boss_pre_state",
                                mame_tick=target_tick,
                                boss=boss.__dict__,
                                state=retained,
                            )
                        elif kind == "boss":
                            boss = payload
                            observed_health = be16(
                                m.read_memory(
                                    "snesMemory",
                                    0x400000 | ((boss.record + 2) & 0xFFFF),
                                    2,
                                )
                            )
                            green = observed_health == boss.expected_health
                            emit(
                                log,
                                "boss",
                                mame_tick=target_tick,
                                snes_tick=tick16(m),
                                boss=boss.__dict__,
                                observed_health=observed_health,
                                result="green" if green else "red",
                                player=light_player,
                            )
                            if not green:
                                summary["boss_events_red"] += 1
                                divergence = {
                                    "boss": boss.__dict__,
                                    "observed_health": observed_health,
                                }
                                record_oracle_divergence(
                                    summary,
                                    log,
                                    states_dir,
                                    latest_input_prestate,
                                    kind="boss",
                                    mame_tick=target_tick,
                                    detail=divergence,
                                )
                                if not args.continue_oracle_divergences:
                                    raise CampaignFailure(
                                        "interpreter_native_or_timing",
                                        {
                                            "reason": (
                                                "organic_boss_health_mismatch"
                                            ),
                                            "mame_tick": target_tick,
                                            **divergence,
                                        },
                                    )
                            else:
                                summary["boss_events_green"] += 1
                            if boss.kind == "init" or boss.name.endswith(
                                ("hit-13", "hit-37", "hit-06")
                            ):
                                snap = detailed_snapshot(
                                    m,
                                    floors,
                                    boss.name,
                                    target_tick,
                                )
                                shot = screenshot(
                                    m, shots_dir / f"{boss.name}.png"
                                )
                                state = save_state(
                                    m, states_dir / f"{boss.name}.mss"
                                )
                                summary["screenshots"].append(shot)
                                summary["states"].append(state)
                                emit(
                                    log,
                                    "boss_milestone",
                                    snapshot=snap,
                                    screenshot=shot,
                                    state=state,
                                )
                        elif kind == "retained_boundary_state":
                            boundary_tick = int(payload)
                            state = save_state(
                                m,
                                states_dir
                                / f"retained-boundary-{boundary_tick:05d}.mss",
                            )
                            summary["states"].append(state)
                            emit(
                                log,
                                "retained_boundary_state",
                                mame_tick=boundary_tick,
                                snes_tick=tick16(m),
                                frame=int(
                                    m.get_state().get("frameCount", 0)
                                ),
                                player=light_player,
                                state=state,
                            )
                        elif kind == "sample":
                            snap = detailed_snapshot(
                                m, floors, f"sample-{target_tick}", target_tick
                            )
                            if snap["invalid"]:
                                raise CampaignFailure(
                                    "hardware-boundary/timing",
                                    {
                                        "reason": "task_stack_floor_violation",
                                        "mame_tick": target_tick,
                                        "invalid": snap["invalid"],
                                    },
                                )
                            if (
                                snap["render_complete"] == last_render_complete
                                and snap["frame_request"] != last_frame_request
                            ):
                                raise CampaignFailure(
                                    "renderer",
                                    {
                                        "reason": "renderer_stopped_while_requests_advanced",
                                        "mame_tick": target_tick,
                                        "snapshot": snap,
                                    },
                                )
                            last_render_complete = int(snap["render_complete"])
                            last_frame_request = int(snap["frame_request"])
                            summary["samples"] += 1
                            emit(log, "sample", snapshot=snap)
                        elif kind == "checkpoint":
                            state = save_state(
                                m,
                                states_dir / f"checkpoint-{target_tick:05d}.mss",
                            )
                            resume_context = {
                                "phase": "game_update_entry_post_events",
                                "mame_tick": target_tick,
                                "snes_tick": tick16(m),
                                "video_frame": int(
                                    m.get_state().get("frameCount", 0)
                                ),
                                "current_buttons": current_buttons,
                                "player": player_snapshot(m),
                                "actions_seen": sorted(actions_seen),
                                "task_floors": floors,
                                "processed_input_transitions": processed_inputs,
                                "player_reference_green": summary[
                                    "player_reference_green"
                                ],
                                "player_reference_red": summary[
                                    "player_reference_red"
                                ],
                                "death_reference_green": summary[
                                    "death_reference_green"
                                ],
                                "death_reference_red": summary[
                                    "death_reference_red"
                                ],
                                "boss_events_green": summary[
                                    "boss_events_green"
                                ],
                                "boss_events_red": summary[
                                    "boss_events_red"
                                ],
                                "oracle_divergence_count": summary[
                                    "oracle_divergence_count"
                                ],
                                "oracle_divergence_kinds": summary[
                                    "oracle_divergence_kinds"
                                ],
                                "first_oracle_divergence": summary[
                                    "first_oracle_divergence"
                                ],
                                "samples": summary["samples"],
                                "deaths_observed": summary[
                                    "deaths_observed"
                                ],
                                "last_render_complete": last_render_complete,
                                "last_frame_request": last_frame_request,
                            }
                            summary["states"].append(state)
                            emit(
                                log,
                                "checkpoint",
                                mame_tick=target_tick,
                                state=state,
                                resume_context=resume_context,
                            )
                        elif kind == "safe_checkpoint":
                            safe_tick = int(payload)
                            safe = safe_checkpoint_rendezvous(
                                m,
                                states_dir
                                / f"safe-checkpoint-{safe_tick:05d}.mss",
                                mame_tick=safe_tick,
                                current_buttons=current_buttons,
                            )
                            safe_context = {
                                "phase": safe["phase"],
                                "mame_tick_completed": safe_tick,
                                "resume_mame_tick": safe[
                                    "resume_mame_tick"
                                ],
                                "snes_tick": safe["after_snes_tick"],
                                "video_frame": int(
                                    m.get_state().get("frameCount", 0)
                                ),
                                "current_buttons": current_buttons,
                                "player": player_snapshot(m),
                                "actions_seen": sorted(actions_seen),
                                "task_floors": floors,
                                "processed_input_transitions": (
                                    processed_inputs
                                ),
                                "player_reference_green": summary[
                                    "player_reference_green"
                                ],
                                "player_reference_red": summary[
                                    "player_reference_red"
                                ],
                                "death_reference_green": summary[
                                    "death_reference_green"
                                ],
                                "death_reference_red": summary[
                                    "death_reference_red"
                                ],
                                "boss_events_green": summary[
                                    "boss_events_green"
                                ],
                                "boss_events_red": summary[
                                    "boss_events_red"
                                ],
                                "oracle_divergence_count": summary[
                                    "oracle_divergence_count"
                                ],
                                "oracle_divergence_kinds": summary[
                                    "oracle_divergence_kinds"
                                ],
                                "first_oracle_divergence": summary[
                                    "first_oracle_divergence"
                                ],
                                "samples": summary["samples"],
                                "deaths_observed": summary[
                                    "deaths_observed"
                                ],
                                "last_render_complete": (
                                    last_render_complete
                                ),
                                "last_frame_request": last_frame_request,
                            }
                            summary["states"].append(safe["state"])
                            summary["states"].extend(
                                safe["repeat_states"]
                            )
                            emit(
                                log,
                                "safe_checkpoint",
                                mame_tick=safe_tick,
                                resume_mame_tick=safe[
                                    "resume_mame_tick"
                                ],
                                safe=safe,
                                state=safe["state"],
                                resume_context=safe_context,
                            )
                        elif kind == "campaign_end":
                            end_snapshot = detailed_snapshot(
                                m, floors, "campaign_end", target_tick
                            )
                            end_state = save_state(
                                m, states_dir / "campaign-end.mss"
                            )
                            end_shot = screenshot(
                                m, shots_dir / "campaign-end.png"
                            )
                            summary["end"] = end_snapshot
                            summary["states"].append(end_state)
                            summary["screenshots"].append(end_shot)
                            emit(
                                log,
                                "campaign_end",
                                snapshot=end_snapshot,
                                state=end_state,
                                screenshot=end_shot,
                            )

                summary["actions_observed"] = sorted(actions_seen)
                summary["x1_control_pairs_observed"] = [
                    {
                        "d00601_413601": first,
                        "d00603_413603": second,
                    }
                    for first, second in sorted(x1_control_pairs_seen)
                ]
                required_actions = set(ACTION_NAMES)
                missing_actions = sorted(required_actions - actions_seen)
                missing_buttons = sorted(
                    name
                    for name, seen in provenance["input_coverage"][
                        "buttons_seen"
                    ].items()
                    if not seen
                )
                coverage_gaps = {
                    "missing_actions": missing_actions,
                    "missing_buttons": missing_buttons,
                    "boss_events_green": summary["boss_events_green"],
                    "boss_events_red": summary["boss_events_red"],
                    "boss_events_total": summary["boss_events_total"],
                    "deaths_observed": len(summary["deaths_observed"]),
                    "death_reference_green": summary["death_reference_green"],
                    "death_reference_red": summary["death_reference_red"],
                }
                summary["coverage_gaps"] = coverage_gaps
                if (
                    (missing_actions or missing_buttons)
                    and not args.allow_incomplete_coverage
                ):
                    raise CampaignFailure(
                        "coverage",
                        {
                            "reason": "required_controller_or_action_coverage_missing",
                            "missing_actions": missing_actions,
                            "missing_buttons": missing_buttons,
                            "actions_observed": sorted(actions_seen),
                        },
                    )
                if summary["boss_events_red"]:
                    raise CampaignFailure(
                        "interpreter_native_or_timing",
                        {
                            "reason": "boss_oracle_mismatch",
                            "green": summary["boss_events_green"],
                            "red": summary["boss_events_red"],
                            "total": summary["boss_events_total"],
                        },
                    )
                if summary["death_reference_red"]:
                    raise CampaignFailure(
                        "interpreter_native_or_timing",
                        {
                            "reason": "death_respawn_oracle_mismatch",
                            "deaths_observed": len(
                                summary["deaths_observed"]
                            ),
                            "death_reference_green": summary[
                                "death_reference_green"
                            ],
                            "death_reference_red": summary[
                                "death_reference_red"
                            ],
                        },
                    )
                if not args.allow_incomplete_coverage and (
                    summary["boss_events_green"]
                    != summary["boss_events_total"]
                    or not summary["deaths_observed"]
                ):
                    raise CampaignFailure(
                        "interpreter_native_or_timing",
                        {
                            "reason": "boss_or_death_oracle_coverage_incomplete",
                            **coverage_gaps,
                        },
                    )
                summary["result"] = (
                    (
                        "partial-with-oracle-divergences"
                        if summary["oracle_divergence_count"]
                        else "partial-green"
                    )
                    if args.allow_incomplete_coverage
                    else (
                        "coverage-complete-with-oracle-divergences"
                        if summary["oracle_divergence_count"]
                        else "green"
                    )
                )
                set_held_input(m, 0)
                summary["architectural_mutations"] = list(
                    m.architectural_mutations
                )

        except CampaignFailure as failure:
            summary["failure"] = {
                "classification": failure.classification,
                **failure.detail,
            }
            if (
                args.retain_input_prestate
                or args.retain_input_prestate_tick
            ):
                latest_path = states_dir / "pre-input-latest.mss"
                if latest_path.is_file():
                    retained_path = states_dir / "pre-failure-input.mss"
                    shutil.copy2(latest_path, retained_path)
                    latest_iram = Path(f"{latest_path}.sa1-iram.bin")
                    retained_iram = Path(f"{retained_path}.sa1-iram.bin")
                    if latest_iram.is_file():
                        shutil.copy2(latest_iram, retained_iram)
                    retained = {
                        "path": str(retained_path),
                        "sha256": sha256(retained_path),
                        "source": str(latest_path),
                        "synchronous_completed": True,
                        "copied_after_failure": True,
                        "live_state_unchanged": True,
                        "boundary_kind": "pre_input_apply",
                    }
                    if retained_iram.is_file():
                        retained["sa1_iram_sidecar"] = {
                            "path": str(retained_iram),
                            "sha256": sha256(retained_iram),
                        }
                    if latest_input_prestate is not None:
                        retained["input"] = latest_input_prestate
                    summary["failure"]["pre_failure_input_state"] = retained
                    summary["states"].append(retained)
            # The session may still be usable.  Preserve the exact observed
            # failure boundary in addition to the preceding periodic/boss state.
            if "state" in summary["failure"]:
                summary["states"].append(summary["failure"]["state"])
            if "screenshot" in summary["failure"]:
                summary["screenshots"].append(
                    summary["failure"]["screenshot"]
                )
            emit(log, "failure", failure=summary["failure"])
        except Exception as failure:
            summary["failure"] = {
                "classification": "harness_or_unclassified",
                "reason": repr(failure),
            }
            try:
                failure_state = save_state(m, states_dir / "failure.mss")
                failure_shot = screenshot(m, shots_dir / "failure.png")
                summary["states"].append(failure_state)
                summary["screenshots"].append(failure_shot)
                summary["failure"]["state"] = failure_state
                summary["failure"]["screenshot"] = failure_shot
            except Exception as capture_error:
                summary["failure"]["capture_error"] = repr(capture_error)
            emit(log, "failure", failure=summary["failure"])
        finally:
            _ACTIVE_SESSION = None
            _ACTIVE_STATE_DIR = None
            _ACTIVE_SHOT_DIR = None

    summary["actions_observed"] = sorted(actions_seen)
    summary["event_log"] = str(event_path)
    summary["event_log_sha256"] = sha256(event_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "failure": summary["failure"],
                "processed_input_transitions": summary[
                    "processed_input_transitions"
                ],
                "boss_events": {
                    "green": summary["boss_events_green"],
                    "red": summary["boss_events_red"],
                    "total": summary["boss_events_total"],
                },
                "oracle_divergences": {
                    "total": summary["oracle_divergence_count"],
                    "kinds": summary["oracle_divergence_kinds"],
                    "first": summary["first_oracle_divergence"],
                },
                "deaths_observed": len(summary["deaths_observed"]),
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return (
        0
        if summary["result"]
        in (
            "green",
            "partial-green",
            "partial-with-oracle-divergences",
            "coverage-complete-with-oracle-divergences",
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
