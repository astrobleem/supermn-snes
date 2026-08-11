#!/usr/bin/env python3
"""Trace player-native entries and coordinate writes across exact SNES ticks.

This is a checkpoint diagnostic for a production ROM.  It loads an explicitly
named state, applies only real port-0 controller input, installs non-pausing
SA-1 hooks, and advances to the next production tick-counter write.  Native
gate overrides are explicit classification controls and are recorded in the
result; ordinary game memory is not altered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
TICK_IRAM = 0x0760
# The live virtual-IRQ reload is the bank-$97 campaign helper.  Its current
# production literal is $7000; the bank-$00 reset literal is not the gameplay
# seam.  Keep this byte-precise because the probe must reject a different ROM.
IRQ_RELOAD_IMMEDIATE_ROM_OFFSET = 0x2BE5C3
IRQ_RELOAD_IMMEDIATE_EXPECTED = bytes.fromhex("0070")
# The production $0818 paced-wait release normally writes one to the virtual
# MC68000 IRQ countdown.  A reversible override is useful for proving an IRQ
# work-point without changing the candidate ROM.
PACING_IRQ_DELAY_IMMEDIATE_ROM_OFFSET = 0x2CFBA2
PACING_IRQ_DELAY_IMMEDIATE_EXPECTED = bytes.fromhex("0100")
WORK_BASE = 0x400000
WORK_SIZE = 0x10000
PLAYER_X = 0x4012E4
WALL_RESPONSE_START = 0x403A60
COLLISION_TABLE_START = 0x403734
COLLISION_TABLE_END = 0x403CC3
PLAYER_COLLISION_POINTER_START = 0x4012CA
PLAYER_COLLISION_POINTER_END = 0x4012DD
PLAYER_NATIVE_HOOKS = {
    "entry_13282t": 0x9FE000,
    "entry_13314t": 0x9FD800,
    "entry_1337et": 0x9FBA00,
    "entry_133eat": 0x9FEC00,
    "entry_13468t": 0x9FF100,
    "entry_13538t": 0x9FF700,
    "entry_135e0": 0x94DB20,
}
WALL_NATIVE_HOOKS = {
    "entry_d18a": 0x92AB9E,
    "Ld18a_d1d4": 0x92AD18,
    "Lfd18a_18": 0x92AD23,
    "Lfd18a_19": 0x92AD59,
    "Ld18a_d1ec": 0x92AD7F,
    "Lfd18a_20": 0x92AD9A,
    "Ld18a_d1fc": 0x92ADC0,
    "d18a_sub_store": 0x92F100,
    "entry_25110": 0x978000,
    "h25110_stage2_try": 0x9D8000,
    "h25s2_scan": 0x9D804D,
    "h25s2_qualifying": 0x9D807C,
    "h25s2_fast_done": 0x9D80F3,
    "h25s2_fallback": 0x9D810C,
    "h25110_stage2_overlap": 0x9DE800,
    "h25s2_overlap_done": 0x9DEA2A,
    "entry_12e56": 0x97A000,
    "L12e56_12ec0": 0x97A1D1,
    "L12e56_12ef0": 0x97A2C4,
    "L12e56_12f00": 0x97A317,
    "L12e56_12f06": 0x97A342,
    "L12e56_12f1e": 0x97A3BF,
    "entry_12af6": 0x97C000,
    "L12af6_12b18": 0x97C09F,
    "L12af6_12b26": 0x97C0C3,
    "L12af6_12b48": 0x97C157,
    "L12af6_12b62": 0x97C1CE,
}
WALL_WRITE_HOOKS = {
    WALL_RESPONSE_START + 0: "wall_response_x_write",
    WALL_RESPONSE_START + 1: "wall_response_y_write",
    WALL_RESPONSE_START + 2: "wall_response_type_high_write",
    WALL_RESPONSE_START + 3: "wall_response_type_low_write",
}
PACING_INPUT_HOOKS = {
    "nmi_pacing_wram": 0x7F8F00,
    "irq_pacing_wram": 0x7F8F40,
    "pacing_try_wake": 0x7F8E00,
    "ptw_deadline_due": 0x7F8E2B,
    "pacing_sample_joy": 0x7F8E8A,
    "psj_loop": 0x7F8E9B,
}
PACING_INPUT_WRITE_HOOKS = {
    0x7E1F12: "pacing_sample_low_write",
    0x7E1F13: "pacing_sample_high_write",
    0x410000: "joy_mailbox_low_write",
    0x410001: "joy_mailbox_high_write",
}
SYMBOL_BANKS = {
    "escbank.sym": 0x92,
    "escbank2.sym": 0x94,
    "escbank3.sym": 0x97,
    "escbank4.sym": 0x98,
    "escbank5.sym": 0x99,
    "escbank6.sym": 0x95,
    "escbank7.sym": 0x9D,
    "escbank8.sym": 0x9E,
    "escbank9.sym": 0x9F,
}
SYMBOL_LINE = re.compile(
    r"\s*[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4,6})\s+"
    r"([0-9A-Za-z_]+)(?:\s|$)"
)
NATIVE_ESCAPE_BANKS = frozenset(range(0x92, 0xA0))

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0xA0)
    parser.add_argument(
        "--preserve-input",
        action="store_true",
        help="do not replace the controller state serialized in the checkpoint",
    )
    parser.add_argument(
        "--transition-buttons",
        type=lambda value: int(value, 0),
        help="replace held input after --transition-after completed ticks",
    )
    parser.add_argument("--transition-after", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=1)
    parser.add_argument("--trace-count", type=int, default=1_000)
    parser.add_argument(
        "--xlat-gate",
        choices=("preserve", "on", "off"),
        default="preserve",
    )
    parser.add_argument(
        "--choke-gate",
        choices=("preserve", "on", "off"),
        default="preserve",
    )
    parser.add_argument(
        "--scheduler-gates",
        choices=("preserve", "on", "off"),
        default="preserve",
        help=(
            "preserve or override the $0736 selector and $073c switch-in "
            "native scheduler gates"
        ),
    )
    parser.add_argument(
        "--loop-gate",
        choices=("preserve", "on", "off"),
        default="preserve",
        help=(
            "preserve or override the $072e loop/scheduler fast-path gate; "
            "off is the complete interpreted-loop classification arm"
        ),
    )
    parser.add_argument(
        "--pacing-gate",
        choices=("preserve", "on", "off"),
        default="preserve",
        help=(
            "preserve or override the $0734 production paced-wait/render "
            "HLE gate; include this in a complete native-root-off run"
        ),
    )
    parser.add_argument(
        "--set-d7",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: replace the live emulated MC68000 D7 register "
            "after state load; the intervention is recorded"
        ),
    )
    parser.add_argument(
        "--set-work-word",
        action="append",
        default=[],
        metavar="OFFSET=VALUE",
        help=(
            "diagnostic only: replace one big-endian $F0 work-RAM word "
            "after state load; repeat for a focused causal experiment"
        ),
    )
    parser.add_argument(
        "--set-irq-countdown",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: replace the serialized virtual-IRQ countdown "
            "$00AC after state load; the intervention is recorded"
        ),
    )
    parser.add_argument(
        "--irq-reload",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: temporarily replace the virtual-IRQ reload "
            "immediate; ROM bytes are restored and recorded"
        ),
    )
    parser.add_argument(
        "--pacing-irq-delay",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: replace the production $0818 paced-wait "
            "virtual-IRQ countdown immediate; ROM bytes are restored"
        ),
    )
    parser.add_argument(
        "--stop-at-first-x-write",
        action="store_true",
        help="stop before the first player-X low-byte write instead of a tick",
    )
    parser.add_argument(
        "--stop-at-work-write",
        type=lambda value: int(value, 0),
        help=(
            "stop before the first write to this 16-bit $F0xxxx work-RAM "
            "offset instead of completing a tick"
        ),
    )
    parser.add_argument(
        "--stop-at-work-write-value",
        type=lambda value: int(value, 0),
        help=(
            "with --stop-at-work-write, stop only when the written byte "
            "matches this value"
        ),
    )
    parser.add_argument(
        "--stop-max-frames",
        type=int,
        default=480,
        help="maximum video frames to search for a focused stop",
    )
    parser.add_argument(
        "--allow-stop-timeout",
        action="store_true",
        help=(
            "retain a no-match result instead of failing when a focused "
            "stop is not reached within --stop-max-frames"
        ),
    )
    parser.add_argument(
        "--watch-work-write",
        type=lambda value: int(value, 0),
        action="append",
        default=[],
        help=(
            "record every write to this 16-bit $F0xxxx work-RAM offset; "
            "repeat for multiple bytes"
        ),
    )
    parser.add_argument(
        "--watch-irq-countdown",
        action="store_true",
        help=(
            "record every SA-1 write to the virtual-IRQ countdown $00AC-$00AD"
        ),
    )
    parser.add_argument(
        "--all-entry-hooks",
        action="store_true",
        help="hook every assembled entry_* symbol, not only player bodies",
    )
    parser.add_argument(
        "--exec-hook",
        action="append",
        default=[],
        metavar="LABEL=ADDRESS",
        help=(
            "add a non-pausing SA-1 execution hook at a hexadecimal address; "
            "repeat for multiple focused seams"
        ),
    )
    parser.add_argument(
        "--stop-at-exec-hook",
        metavar="LABEL=ADDRESS",
        help=(
            "stop before one focused SA-1 execution seam and retain the "
            "native trace/register state"
        ),
    )
    parser.add_argument(
        "--stabilize-stop",
        action="store_true",
        help=(
            "temporarily replace the first two bytes at --stop-at-exec-hook "
            "with BRA -2 so delayed debugger pausing cannot execute past the "
            "requested seam; the ROM bytes are restored before state save"
        ),
    )
    parser.add_argument(
        "--stop-skip-hits",
        type=int,
        default=0,
        help=(
            "ignore this many earlier occurrences of --stop-at-exec-hook "
            "before installing the stable stop; useful for same-PC consecutive "
            "tick comparisons"
        ),
    )
    parser.add_argument(
        "--wall-collision-hooks",
        action="store_true",
        help=(
            "add exact $25110 producer/$12e56 consumer execution seams and "
            "writes to the player wall-response record"
        ),
    )
    parser.add_argument(
        "--pacing-input-hooks",
        action="store_true",
        help=(
            "record 5A22 NMI/IRQ controller-sampling seams plus private-sample "
            "and shared-mailbox writes"
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
        "--interpret-25110",
        action="store_true",
        help=(
            "classification only: temporarily change the native $025110 "
            "canonical-A5 branch to its existing interpreter fallback; the "
            "ROM bytes are restored before the retained post-state"
        ),
    )
    parser.add_argument(
        "--interpret-1f1c0",
        action="store_true",
        help=(
            "classification only: temporarily bypass the native-hot "
            "$01F1C0 object-list leaf and enter its generated table body; "
            "the ROM bytes are restored before exit"
        ),
    )
    parser.add_argument(
        "--interpret-scheduler",
        action="store_true",
        help=(
            "classification only: temporarily park the $0532 switch-out, "
            "$074C selector scan, and $0796 switch-in loop-hook arms while "
            "retaining the $0818 paced boundary; the ROM bytes are restored "
            "before the retained post-state"
        ),
    )
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9257)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--skip-final-state",
        action="store_true",
        help="diagnostic-only: omit the post-trace save when dense hooks make Nexen's save acknowledgement unreliable",
    )
    args = parser.parse_args()
    if args.ticks < 1 or args.ticks > 16:
        parser.error("--ticks must be in 1..16")
    if args.trace_count < 1 or args.trace_count > 1_000:
        parser.error("--trace-count must be in 1..1000")
    if not 0 <= args.buttons <= 0x0FFF:
        parser.error("--buttons must be in 0..0x0fff")
    if (
        args.stop_at_work_write is not None
        and not 0 <= args.stop_at_work_write <= 0xFFFF
    ):
        parser.error("--stop-at-work-write must be in 0..0xffff")
    if any(not 0 <= address <= 0xFFFF for address in args.watch_work_write):
        parser.error("--watch-work-write must be in 0..0xffff")
    stop_requests = sum(
        (
            bool(args.stop_at_first_x_write),
            args.stop_at_work_write is not None,
            args.stop_at_exec_hook is not None,
        )
    )
    if stop_requests > 1:
        parser.error(
            "the --stop-at-* controls are mutually exclusive"
        )
    if args.stabilize_stop and args.stop_at_exec_hook is None:
        parser.error("--stabilize-stop requires --stop-at-exec-hook")
    if args.stop_skip_hits < 0:
        parser.error("--stop-skip-hits cannot be negative")
    if args.stop_skip_hits and args.stop_at_exec_hook is None:
        parser.error("--stop-skip-hits requires --stop-at-exec-hook")
    if (
        args.stop_at_work_write_value is not None
        and args.stop_at_work_write is None
    ):
        parser.error(
            "--stop-at-work-write-value requires --stop-at-work-write"
        )
    if (
        args.stop_at_work_write_value is not None
        and not 0 <= args.stop_at_work_write_value <= 0xFF
    ):
        parser.error("--stop-at-work-write-value must be in 0..0xff")
    if args.stop_max_frames < 1:
        parser.error("--stop-max-frames must be positive")
    if args.pacing_irq_delay is not None and not 1 <= args.pacing_irq_delay <= 0xFFFF:
        parser.error("--pacing-irq-delay must be in 1..0xffff")
    if args.set_d7 is not None and not 0 <= args.set_d7 <= 0xFFFFFFFF:
        parser.error("--set-d7 must be in 0..0xffffffff")
    parsed_work_words: list[tuple[int, int]] = []
    for spec in args.set_work_word:
        try:
            offset_text, value_text = spec.split("=", 1)
            offset = int(offset_text, 0)
            value = int(value_text, 0)
        except ValueError:
            parser.error(
                f"invalid --set-work-word {spec!r}; expected OFFSET=VALUE"
            )
        if not 0 <= offset <= 0xFFFE or offset & 1:
            parser.error(
                f"invalid --set-work-word offset {offset_text!r}; "
                "expected an even value in 0..0xfffe"
            )
        if not 0 <= value <= 0xFFFF:
            parser.error(
                f"invalid --set-work-word value {value_text!r}; "
                "expected 0..0xffff"
            )
        parsed_work_words.append((offset, value))
    args.parsed_work_words = parsed_work_words
    if (
        args.set_irq_countdown is not None
        and not 1 <= args.set_irq_countdown <= 0xFFFF
    ):
        parser.error("--set-irq-countdown must be in 1..0xffff")
    if args.irq_reload is not None and not 1 <= args.irq_reload <= 0xFFFF:
        parser.error("--irq-reload must be in 1..0xffff")
    parsed_exec_hooks: dict[str, int] = {}
    for spec in args.exec_hook:
        try:
            label, address_text = spec.split("=", 1)
            address = int(address_text, 0)
        except ValueError:
            parser.error(
                f"invalid --exec-hook {spec!r}; expected LABEL=ADDRESS"
            )
        if not label or not 0 <= address <= 0xFFFFFF:
            parser.error(
                f"invalid --exec-hook {spec!r}; expected LABEL=ADDRESS"
            )
        if label in parsed_exec_hooks:
            parser.error(f"duplicate --exec-hook label: {label}")
        parsed_exec_hooks[label] = address
    parsed_stop_exec_hook: tuple[str, int] | None = None
    if args.stop_at_exec_hook is not None:
        try:
            label, address_text = args.stop_at_exec_hook.split("=", 1)
            address = int(address_text, 0)
        except ValueError:
            parser.error(
                "invalid --stop-at-exec-hook; expected LABEL=ADDRESS"
            )
        if not label or not 0 <= address <= 0xFFFFFF:
            parser.error(
                "invalid --stop-at-exec-hook; expected LABEL=ADDRESS"
            )
        if label in parsed_exec_hooks:
            parser.error(
                f"--stop-at-exec-hook label duplicates --exec-hook: {label}"
            )
        parsed_stop_exec_hook = (label, address)
    args.exec_hooks = parsed_exec_hooks
    args.stop_exec_hook = parsed_stop_exec_hook
    if (
        args.transition_buttons is not None
        and not 0 <= args.transition_buttons <= 0x0FFF
    ):
        parser.error("--transition-buttons must be in 0..0x0fff")
    if not 1 <= args.transition_after < args.ticks:
        if args.transition_buttons is not None:
            parser.error("--transition-after must be in 1..ticks-1")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(data), "little")


def sa1_program_counter(cpu: dict[str, Any]) -> int:
    """Return the 24-bit SA-1 program counter from an MCP CPU snapshot."""

    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (
        int(cpu.get("pc", 0)) & 0xFFFF
    )


def native_escape_in_flight(cpu: dict[str, Any]) -> bool:
    """Whether a restored state will resume inside an escape-bank handler.

    A gate changes dispatch for *future* MC68000 calls only.  It cannot turn an
    already serialized SA-1 handler back into the interpreter, so treating
    such a state as an exact native-off variant would be false evidence.
    """

    return ((sa1_program_counter(cpu) >> 16) & 0xFF) in NATIVE_ESCAPE_BANKS


def gate_mutation_requested(args: argparse.Namespace) -> bool:
    return any(
        request != "preserve"
        for request in (
            args.xlat_gate,
            args.choke_gate,
            args.scheduler_gates,
            args.loop_gate,
            args.pacing_gate,
        )
    )


def read_full_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", WORK_BASE + offset, 0x4000))
        for offset in range(0, WORK_SIZE, 0x4000)
    )


def boundary_snapshot(m: McpSession) -> dict[str, Any]:
    virtual = bytes(m.read_memory("Sa1Memory", 0x0040, 6))
    return {
        "tick": le16(m.read_memory("Sa1Memory", TICK_IRAM, 2)),
        "frame": int(m.get_state().get("frameCount", 0)),
        # The virtual 68000 PC/opcode identify the logical writer even when
        # a native or interpreter write hook stops in SA-1 code.
        "pc68k": f"{int.from_bytes(virtual[0:4], 'little') & 0xFFFFFF:06X}",
        "opcode68k": f"{le16(virtual[4:6]):04X}",
        "player": campaign.player_snapshot(m),
        "m68k": campaign.register_snapshot(m),
        "gates": {
            "071a": le16(m.read_memory("Sa1Memory", 0x071A, 2)),
            "072e": le16(m.read_memory("Sa1Memory", 0x072E, 2)),
            "0734": le16(m.read_memory("Sa1Memory", 0x0734, 2)),
            "0736": le16(m.read_memory("Sa1Memory", 0x0736, 2)),
            "073a": le16(m.read_memory("Sa1Memory", 0x073A, 2)),
            "073c": le16(m.read_memory("Sa1Memory", 0x073C, 2)),
        },
        "virtual_irq": {
            "pending_00aa": le16(
                m.read_memory("Sa1Memory", 0x00AA, 2)
            ),
            "countdown_00ac": le16(
                m.read_memory("Sa1Memory", 0x00AC, 2)
            ),
            "m68k_mask_007c": le16(
                m.read_memory("Sa1Memory", 0x007C, 2)
            ),
        },
        "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
        "wall_response": bytes(
            m.read_memory("snesMemory", WALL_RESPONSE_START, 4)
        ).hex(),
    }


def hook_params(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def assembled_symbol_addresses() -> dict[str, list[int]]:
    """Return labels owned by each freshly assembled escape bank.

    Poppy also emits imported absolute symbols (for example ``97A000``) into
    other banks' .sym files.  Those values are not offsets in the containing
    bank and must not be converted into plausible-looking duplicate hooks.
    """

    by_label: dict[str, set[int]] = {}
    for filename, bank in SYMBOL_BANKS.items():
        path = ROOT / "src" / filename
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = SYMBOL_LINE.match(line)
            if match is None:
                continue
            offset = int(match.group(1), 16)
            if offset > 0xFFFF:
                continue
            address = (bank << 16) | offset
            by_label.setdefault(match.group(2), set()).add(address)
    return {
        label: sorted(addresses)
        for label, addresses in by_label.items()
    }


def resolved_hooks(fallbacks: dict[str, int]) -> dict[str, int]:
    """Resolve diagnostic seams from current symbols, retaining fixed fallback."""

    symbols = assembled_symbol_addresses()
    resolved = {}
    for label, fallback in fallbacks.items():
        candidates = symbols.get(label, [])
        if len(candidates) == 1:
            resolved[label] = candidates[0]
        elif fallback in candidates or not candidates:
            resolved[label] = fallback
        else:
            raise RuntimeError(
                f"ambiguous assembled symbol {label}: "
                + ", ".join(f"{address:06X}" for address in candidates)
            )
    return resolved


def all_entry_hooks() -> dict[str, int]:
    by_address: dict[int, list[str]] = {}
    for label, addresses in assembled_symbol_addresses().items():
        if not label.startswith("entry_"):
            continue
        for address in addresses:
            by_address.setdefault(address, []).append(label)
    # The same generated label may be imported into several .sym files.  A
    # label-only dictionary key silently retained the final importer and could
    # therefore hook the wrong runtime bank.  Include the resolved address so
    # every distinct assembled seam remains independently observable.
    return {
        f"{'|'.join(sorted(set(labels)))}@{address:06X}": address
        for address, labels in by_address.items()
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = (
        "/home/chad/.dotnet8"
        if args.nexen.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )

    stop_mode = (
        args.stop_at_first_x_write
        or args.stop_at_work_write is not None
        or args.stop_exec_hook is not None
    )
    if stop_mode:
        # Nexen's run_until currently pauses on any installed matching hook,
        # even when a particular hook_handle is supplied.  A focused stop
        # must therefore install only its target; ancillary notification
        # hooks would stop the machine first and misidentify the seam.
        native_hooks: dict[str, int] = {}
    else:
        native_hooks = (
            all_entry_hooks()
            if args.all_entry_hooks
            else resolved_hooks(PLAYER_NATIVE_HOOKS)
        )
        if args.wall_collision_hooks:
            native_hooks = {
                **native_hooks,
                **resolved_hooks(WALL_NATIVE_HOOKS),
            }
        native_hooks = {**native_hooks, **args.exec_hooks}
    if args.stop_exec_hook is not None:
        native_hooks[args.stop_exec_hook[0]] = args.stop_exec_hook[1]
    snes_hooks = (
        PACING_INPUT_HOOKS
        if args.pacing_input_hooks and not stop_mode
        else {}
    )
    result: dict[str, Any] = {
        "scope": (
            "checkpointed production-ROM player-native execution/write trace; "
            "real held controller input; any native-gate overrides are "
            "explicitly recorded; no ordinary game-memory writes; "
            "not fresh-boot or performance evidence"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "emulator": str(args.nexen),
        "emulator_sha256": sha256(args.nexen),
        "buttons": args.buttons,
        "preserve_input": args.preserve_input,
        "transition_buttons": args.transition_buttons,
        "transition_after": (
            args.transition_after
            if args.transition_buttons is not None
            else None
        ),
        "requested_ticks": args.ticks,
        "irq_reload": args.irq_reload,
        "pacing_irq_delay": args.pacing_irq_delay,
        "stop_max_frames": args.stop_max_frames,
        "allow_stop_timeout": args.allow_stop_timeout,
        "work_write_stop": (
            {
                "offset": f"{args.stop_at_work_write:04X}",
                "value": (
                    f"{args.stop_at_work_write_value:02X}"
                    if args.stop_at_work_write_value is not None
                    else None
                ),
            }
            if args.stop_at_work_write is not None
            else None
        ),
        "gate_request": {
            "xlat_071a": args.xlat_gate,
            "choke_073a": args.choke_gate,
            "scheduler_0736_073c": args.scheduler_gates,
            "loop_072e": args.loop_gate,
            "pacing_0734": args.pacing_gate,
        },
        "native_hooks": {
            label: f"{address:06X}"
            for label, address in native_hooks.items()
        },
        "snes_hooks": {
            label: f"{address:06X}"
            for label, address in snes_hooks.items()
        },
        "runtime_game_memory_writes": [],
        "boundaries": [],
        "events": [],
    }

    with McpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        result["load_state_response"] = m.load_state(args.state)
        m.pause()
        loaded_sa1_cpu = m.get_cpu_state("Sa1")
        loaded_sa1_pc = sa1_program_counter(loaded_sa1_cpu)
        result["loaded_sa1"] = {
            "pc": f"{loaded_sa1_pc:06X}",
            "native_escape_in_flight": native_escape_in_flight(
                loaded_sa1_cpu
            ),
        }
        if gate_mutation_requested(args) and native_escape_in_flight(
            loaded_sa1_cpu
        ):
            rejection = {
                "scope": (
                    "rejected post-load native-gate mutation; an escape-bank "
                    "handler is serialized in flight, so this state cannot "
                    "become an exact native-off/on variant by changing gates"
                ),
                "state": str(args.state),
                "state_sha256": result["state_sha256"],
                "rom_sha256": result["rom_sha256"],
                "gate_request": result["gate_request"],
                "loaded_sa1": result["loaded_sa1"],
                "result": "rejected",
            }
            (args.output / "rejected-gate-mutation.json").write_text(
                json.dumps(rejection, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise RuntimeError(
                "refusing post-load native-gate mutation while a native "
                f"escape is in flight at ${loaded_sa1_pc:06X}; prepare the "
                "variant before capturing its checkpoint"
            )
        irq_reload_patch: dict[str, Any] | None = None
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
                "rom_offset": (
                    f"{IRQ_RELOAD_IMMEDIATE_ROM_OFFSET:06X}"
                ),
                "before": original.hex(),
                "temporary": replacement.hex(),
                "value": args.irq_reload,
                "restored": True,
            }
            result["runtime_game_memory_writes"].append(irq_reload_patch)
        pacing_irq_delay_patch: dict[str, Any] | None = None
        if args.pacing_irq_delay is not None:
            original = bytes(
                m.read_memory(
                    "snesPrgRom",
                    PACING_IRQ_DELAY_IMMEDIATE_ROM_OFFSET,
                    2,
                )
            )
            expected = PACING_IRQ_DELAY_IMMEDIATE_EXPECTED
            if original != expected:
                raise RuntimeError(
                    "paced-wait IRQ-delay seam changed: expected "
                    f"{expected.hex()}, found {original.hex()}"
                )
            replacement = args.pacing_irq_delay.to_bytes(2, "little")
            m.write_memory(
                "snesPrgRom",
                PACING_IRQ_DELAY_IMMEDIATE_ROM_OFFSET,
                replacement.hex(),
            )
            pacing_irq_delay_patch = {
                "kind": "debugger_paced_wait_irq_delay_classification",
                "rom_offset": (
                    f"{PACING_IRQ_DELAY_IMMEDIATE_ROM_OFFSET:06X}"
                ),
                "before": original.hex(),
                "temporary": replacement.hex(),
                "value": args.pacing_irq_delay,
                "restored": True,
            }
            result["runtime_game_memory_writes"].append(
                pacing_irq_delay_patch
            )
        if args.refresh_video_wram:
            result["runtime_game_memory_writes"].append(
                campaign.refresh_video_wram(m, args.rom)
            )
        interpreted_25110_patch: dict[str, Any] | None = None
        if args.interpret_25110:
            # $97:8018 is the size-neutral BCC from entry_25110's canonical-A5
            # guard.  BRA +6 enters the immediately following h25110_interp
            # fallback after the wrapper has installed the skipped JSR return.
            # This isolates only the long collision root while preserving the
            # rest of the checkpoint's production-native execution.
            patch_offset = 0x2B8018
            original = bytes(
                m.read_memory("snesPrgRom", patch_offset, 2)
            )
            if original != bytes.fromhex("9006"):
                raise RuntimeError(
                    "$025110 interpreter-classification seam changed: "
                    f"expected 9006, found {original.hex()}"
                )
            m.write_memory("snesPrgRom", patch_offset, "8006")
            interpreted_25110_patch = {
                "kind": "debugger_native_root_classification",
                "label": "interpret_25110",
                "address": "978018",
                "rom_offset": f"{patch_offset:06X}",
                "before": original.hex(),
                "after": "8006",
            }
            result["runtime_game_memory_writes"].append(
                interpreted_25110_patch
            )
        interpreted_1f1c0_patch: dict[str, Any] | None = None
        if args.interpret_1f1c0:
            patch_offset = 0x2BFC60
            original = bytes(
                m.read_memory("snesPrgRom", patch_offset, 4)
            )
            if original != bytes.fromhex("5c00ab9d"):
                raise RuntimeError(
                    "$01F1C0 native-leaf seam changed: expected 5c00ab9d, "
                    f"found {original.hex()}"
                )
            replacement = bytes.fromhex("5c64fc97")
            m.write_memory(
                "snesPrgRom", patch_offset, replacement.hex()
            )
            interpreted_1f1c0_patch = {
                "kind": "debugger_native_leaf_classification",
                "label": "interpret_1f1c0",
                "address": "97FC60",
                "rom_offset": f"{patch_offset:06X}",
                "before": original.hex(),
                "after": replacement.hex(),
            }
            result["runtime_game_memory_writes"].append(
                interpreted_1f1c0_patch
            )
        interpreted_scheduler_patches: list[dict[str, Any]] = []
        if args.interpret_scheduler:
            # Park only the three scheduler accelerators.  Clearing $072E is
            # not an equivalent control: it also removes the paced $0818
            # selector and therefore makes the campaign tick marker
            # unobservable.  Each patch changes one CMP immediate to $FFFF,
            # so the unmodified miss path interprets the original logical PC.
            for label, address, patch_offset, expected in (
                ("switch_out_0532", 0x00FFCA, 0x007FCB, "3205"),
                ("scheduler_scan_074c", 0x00F9AA, 0x0079AB, "4c07"),
                ("switch_in_0796", 0x00FFD3, 0x007FD4, "9607"),
            ):
                original = bytes(
                    m.read_memory("snesPrgRom", patch_offset, 2)
                )
                if original != bytes.fromhex(expected):
                    raise RuntimeError(
                        f"{label} interpreter-classification seam changed: "
                        f"expected {expected}, found {original.hex()}"
                    )
                m.write_memory("snesPrgRom", patch_offset, "ffff")
                patch = {
                    "kind": "debugger_scheduler_classification",
                    "label": label,
                    "address": f"{address:06X}",
                    "rom_offset": f"{patch_offset:06X}",
                    "before": original.hex(),
                    "after": "ffff",
                }
                interpreted_scheduler_patches.append(patch)
                result["runtime_game_memory_writes"].append(patch)
        gate_requests = [
            (0x071A, args.xlat_gate, "xlat_071a", 1),
            (0x073A, args.choke_gate, "choke_073a", 1),
            (0x0736, args.scheduler_gates, "selector_0736", 0x5EEC),
            (0x073C, args.scheduler_gates, "switch_in_073c", 0xA55A),
            (0x072E, args.loop_gate, "loop_072e", 1),
            (0x0734, args.pacing_gate, "pacing_0734", 1),
        ]
        for address, request, label, on_value in gate_requests:
            if request == "preserve":
                continue
            before = le16(m.read_memory("Sa1Memory", address, 2))
            after = on_value if request == "on" else 0
            m.write_u16(address, after, "Sa1Memory")
            result["runtime_game_memory_writes"].append(
                {
                    "kind": "native_gate_classification",
                    "label": label,
                    "address": f"{address:04X}",
                    "before": before,
                    "after": after,
                }
            )
        if args.set_d7 is not None:
            before_low = le16(m.read_memory("Sa1Memory", 0x001C, 2))
            before_high = le16(m.read_memory("Sa1Memory", 0x001E, 2))
            before = before_low | (before_high << 16)
            m.write_u16(0x001C, args.set_d7 & 0xFFFF, "Sa1Memory")
            m.write_u16(0x001E, (args.set_d7 >> 16) & 0xFFFF, "Sa1Memory")
            result["runtime_game_memory_writes"].append(
                {
                    "kind": "m68k_register_classification",
                    "label": "D7",
                    "before": f"{before:08X}",
                    "after": f"{args.set_d7:08X}",
                }
            )
        for offset, value in args.parsed_work_words:
            address = 0x400000 + offset
            before = le16(m.read_memory("Sa1Memory", address, 2))
            m.write_u16(address, value, "Sa1Memory")
            result["runtime_game_memory_writes"].append(
                {
                    "kind": "work_ram_classification",
                    "label": f"F0{offset:04X}",
                    "address": f"{address:06X}",
                    "before": f"{before:04X}",
                    "after": f"{value:04X}",
                }
            )
        if args.set_irq_countdown is not None:
            before = le16(m.read_memory("Sa1Memory", 0x00AC, 2))
            m.write_u16(
                0x00AC,
                args.set_irq_countdown,
                "Sa1Memory",
            )
            result["runtime_game_memory_writes"].append(
                {
                    "kind": "virtual_irq_classification",
                    "label": "countdown_00ac",
                    "address": "00AC",
                    "before": before,
                    "after": args.set_irq_countdown,
                }
            )
        if args.preserve_input:
            result["input_response"] = {
                "preserved_serialized_controller": True,
            }
        else:
            result["input_response"] = campaign.set_held_input(
                m,
                args.buttons,
            )
        result["boundaries"].append(boundary_snapshot(m))
        if result["boundaries"][-1]["halt"]:
            raise RuntimeError("loaded state is halted")
        start_work = read_full_work(m)
        start_work_path = args.output / "start.work.bin"
        start_work_path.write_bytes(start_work)
        result["start_work"] = {
            "path": str(start_work_path),
            "sha256": hashlib.sha256(start_work).hexdigest(),
        }

        handles: dict[int, str] = {
            m.add_exec_hook(address, cpu_type="Sa1"): label
            for label, address in native_hooks.items()
        }
        handles.update(
            {
                m.add_exec_hook(address, cpu_type="Snes"): label
                for label, address in snes_hooks.items()
            }
        )
        x_low_handle = -1
        stop_work_handle = -1
        stop_exec_handle = -1
        stop_exec_label = (
            args.stop_exec_hook[0]
            if args.stop_exec_hook is not None
            else None
        )
        for handle, label in handles.items():
            if label == stop_exec_label:
                stop_exec_handle = handle
        write_hooks: dict[int, str] = {}
        if not stop_mode or args.stop_at_first_x_write:
            write_hooks.update(
                {
                    PLAYER_X: "player_x_high_write",
                    PLAYER_X + 1: "player_x_low_write",
                }
            )
        if not stop_mode:
            for work_offset in args.watch_work_write:
                write_hooks[0x400000 | work_offset] = (
                    f"work_F0{work_offset:04X}_write"
                )
            if args.watch_irq_countdown:
                write_hooks.update(
                    {
                        0x00AC: "virtual_irq_countdown_low_write",
                        0x00AD: "virtual_irq_countdown_high_write",
                    }
                )
        if args.stop_at_work_write is not None:
            stop_work_address = 0x400000 | args.stop_at_work_write
            write_hooks[stop_work_address] = (
                f"work_F0{args.stop_at_work_write:04X}_write"
            )
        if args.wall_collision_hooks and not stop_mode:
            write_hooks.update(WALL_WRITE_HOOKS)
        for address, label in write_hooks.items():
            hook_args: dict[str, Any] = {"cpu_type": "Sa1"}
            if (
                args.stop_at_work_write_value is not None
                and args.stop_at_work_write is not None
                and address == (0x400000 | args.stop_at_work_write)
            ):
                hook_args.update(
                    match_value=args.stop_at_work_write_value,
                    match_value_mask=0xFF,
                )
            handle = m.add_write_hook(address, **hook_args)
            handles[handle] = label
            if address == PLAYER_X + 1:
                x_low_handle = handle
            if (
                args.stop_at_work_write is not None
                and address == (0x400000 | args.stop_at_work_write)
            ):
                stop_work_handle = handle
        if args.wall_collision_hooks and not stop_mode:
            for start, end, label in (
                (
                    COLLISION_TABLE_START,
                    COLLISION_TABLE_END,
                    "collision_table_write",
                ),
                (
                    PLAYER_COLLISION_POINTER_START,
                    PLAYER_COLLISION_POINTER_END,
                    "player_collision_pointer_write",
                ),
            ):
                handle = m.add_write_hook(
                    start,
                    end_address=end,
                    cpu_type="Sa1",
                )
                handles[handle] = label
                write_hooks[start] = label
        if args.pacing_input_hooks and not stop_mode:
            for address, label in PACING_INPUT_WRITE_HOOKS.items():
                handle = m.add_write_hook(address, cpu_type="Snes")
                handles[handle] = label
                write_hooks[address] = label
        m.drain_notifications(timeout=0.05)

        stable_stop_patch: dict[str, Any] | None = None
        stable_stop_patch_installed = False
        if args.stabilize_stop:
            assert args.stop_exec_hook is not None
            stop_address = args.stop_exec_hook[1]
            stop_bank = (stop_address >> 16) & 0xFF
            stop_offset = stop_address & 0xFFFF
            if not 0x80 <= stop_bank <= 0xBF or stop_offset < 0x8000:
                raise RuntimeError(
                    "--stabilize-stop supports mapped SA-1 ROM addresses "
                    f"$80:8000-$BF:FFFF, got ${stop_address:06X}"
                )
            rom_offset = (
                (stop_bank - 0x40) * 0x8000
                + (stop_offset & 0x7FFF)
            )
            original = bytes(
                m.read_memory("snesPrgRom", rom_offset, 2)
            )
            stable_stop_patch = {
                "kind": "debugger_stable_stop",
                "address": f"{stop_address:06X}",
                "rom_offset": f"{rom_offset:06X}",
                "original": original.hex(),
                "temporary": "80fe",
                "architectural_effect": (
                    "none before the hooked entry; delayed resume self-loops "
                    "without touching emulated MC68000 state"
                ),
            }
            result["stable_stop_patch"] = stable_stop_patch
            if args.stop_skip_hits == 0:
                m.write_memory("snesPrgRom", rom_offset, "80fe")
                stable_stop_patch_installed = True

        try:
            if (
                args.stop_at_first_x_write
                or args.stop_at_work_write is not None
                or args.stop_exec_hook is not None
            ):
                # Prime Nexen's trace buffer before resuming.  The write hook
                # stops before the byte is committed, leaving the writer PC
                # and native registers directly observable.
                m.trace_log(count=1, cpu_type="Sa1")
                stop_handle = (
                    x_low_handle
                    if args.stop_at_first_x_write
                    else (
                        stop_work_handle
                        if args.stop_at_work_write is not None
                        else stop_exec_handle
                    )
                )
                skipped_stop_hits: list[dict[str, Any]] = []
                for index in range(args.stop_skip_hits):
                    skipped_response = m.run_until(
                        max_frames=args.stop_max_frames,
                        hook_handle=stop_handle,
                    )
                    m.pause()
                    skipped_rows = hook_params(
                        m.drain_notifications(timeout=0.10)
                    )
                    skipped_stop_hits.append(
                        {
                            "index": index + 1,
                            "response": skipped_response,
                            "sa1_cpu_after_delayed_pause": (
                                m.get_cpu_state("Sa1")
                            ),
                            "boundary_after_delayed_pause": (
                                boundary_snapshot(m)
                            ),
                            "notifications": skipped_rows,
                        }
                    )
                    if skipped_response.get("reason") != "hookFired":
                        raise RuntimeError(
                            "skipped execution-hook occurrence timed out: "
                            f"{skipped_response}"
                        )
                if skipped_stop_hits:
                    result["skipped_stop_hits"] = skipped_stop_hits
                if (
                    stable_stop_patch is not None
                    and not stable_stop_patch_installed
                ):
                    m.write_memory(
                        "snesPrgRom",
                        int(stable_stop_patch["rom_offset"], 16),
                        stable_stop_patch["temporary"],
                    )
                    stable_stop_patch_installed = True
                response = m.run_until(
                    max_frames=args.stop_max_frames,
                    hook_handle=stop_handle,
                )
                m.pause()
                rows = hook_params(m.drain_notifications(timeout=0.10))
                for params in rows:
                    handle = int(params.get("handle", -1))
                    params["label"] = handles.get(handle, "unknown")
                    result["events"].append(params)
                result["write_stop"] = {
                    "response": response,
                    "sa1_cpu": m.get_cpu_state("Sa1"),
                    "boundary": boundary_snapshot(m),
                    "m68k": campaign.register_snapshot(m),
                    "player": campaign.player_snapshot(m),
                    # Retain the coherent work-RAM image at the stop seam.
                    # This is especially useful for collision/object entries:
                    # a delayed debugger notification can leave the live
                    # machine paused several frames later, while the work
                    # image read here is still the architectural state at the
                    # actual stop point.
                    "work_sha256": hashlib.sha256(
                        read_full_work(m)
                    ).hexdigest(),
                    "work_path": str(
                        (args.output / "write-stop.work.bin")
                    ),
                    "iram_locals": {
                        f"{offset:04X}": le16(
                            m.read_memory("Sa1Memory", offset, 2)
                        )
                        for offset in (0x00, 0x04, 0x14, 0x18, 0x20, 0x24, 0x50, 0x52, 0x54, 0x56, 0x9E, 0xA2, 0xAC)
                    },
                    "trace": m.trace_log(
                        count=args.trace_count,
                        cpu_type="Sa1",
                    ),
                }
                (args.output / "write-stop.work.bin").write_bytes(
                    read_full_work(m)
                )
                if (
                    response.get("reason") != "hookFired"
                    and not args.allow_stop_timeout
                ):
                    raise RuntimeError(
                        f"work-RAM write stop timed out: {response}"
                    )
            for _index in range(
                0
                if (
                    args.stop_at_first_x_write
                    or args.stop_at_work_write is not None
                    or args.stop_exec_hook is not None
                )
                else args.ticks
            ):
                before_tick = le16(
                    m.read_memory("Sa1Memory", TICK_IRAM, 2)
                )
                target = (before_tick + 1) & 0xFFFF
                m.drain_notifications(timeout=0.02)
                responses: list[dict[str, Any]] = []
                boundary = boundary_snapshot(m)
                # Frame polling avoids the pre-write/pre-execution stop
                # semantics of Nexen hooks while keeping every native-entry
                # and coordinate-write notification.  Fail if more than one
                # game tick can cross a single video-frame poll.
                for _attempt in range(480):
                    response = m.run_frames(1)
                    responses.append(response)
                    m.pause()
                    rows = hook_params(
                        m.drain_notifications(timeout=0.10)
                    )
                    for params in rows:
                        handle = int(params.get("handle", -1))
                        params["label"] = handles.get(handle, "unknown")
                        result["events"].append(params)
                    boundary = boundary_snapshot(m)
                    if boundary["tick"] == target:
                        break
                    if boundary["tick"] != before_tick:
                        raise RuntimeError(
                            f"tick overshoot: wanted {target}, "
                            f"got {boundary['tick']}"
                        )
                else:
                    raise RuntimeError(
                        f"tick {before_tick}->{target} timed out after 480 frames"
                    )
                boundary["run_responses"] = responses
                result["boundaries"].append(boundary)
                if boundary["tick"] != target:
                    raise RuntimeError(
                        f"tick overshoot: wanted {target}, got {boundary['tick']}"
                    )
                if boundary["halt"]:
                    raise RuntimeError(f"halt after tick {target}")
                if (
                    args.transition_buttons is not None
                    and _index + 1 == args.transition_after
                ):
                    result["transition_response"] = campaign.set_held_input(
                        m,
                        args.transition_buttons,
                    )
        finally:
            for handle in list(handles):
                m.remove_hook(handle)
            if stable_stop_patch is not None and stable_stop_patch_installed:
                m.write_memory(
                    "snesPrgRom",
                    int(stable_stop_patch["rom_offset"], 16),
                    stable_stop_patch["original"],
                )
            if interpreted_25110_patch is not None:
                m.write_memory(
                    "snesPrgRom",
                    int(interpreted_25110_patch["rom_offset"], 16),
                    interpreted_25110_patch["before"],
                )
            if interpreted_1f1c0_patch is not None:
                m.write_memory(
                    "snesPrgRom",
                    int(interpreted_1f1c0_patch["rom_offset"], 16),
                    interpreted_1f1c0_patch["before"],
                )
            for patch in interpreted_scheduler_patches:
                m.write_memory(
                    "snesPrgRom",
                    int(patch["rom_offset"], 16),
                    patch["before"],
                )
            if irq_reload_patch is not None:
                m.write_memory(
                    "snesPrgRom",
                    IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                    irq_reload_patch["before"],
                )
            if pacing_irq_delay_patch is not None:
                m.write_memory(
                    "snesPrgRom",
                    PACING_IRQ_DELAY_IMMEDIATE_ROM_OFFSET,
                    pacing_irq_delay_patch["before"],
                )
            m.drain_notifications(timeout=0.05)

        end_work = read_full_work(m)
        end_work_path = args.output / "end.work.bin"
        end_work_path.write_bytes(end_work)
        result["end_work"] = {
            "path": str(end_work_path),
            "sha256": hashlib.sha256(end_work).hexdigest(),
            "changed_bytes": sum(
                before != after
                for before, after in zip(start_work, end_work)
            ),
        }
        if not args.skip_final_state:
            final_state = args.output / "post-trace.mss"
            result["final_state_response"] = campaign.save_state(m, final_state)
            result["final_state_sha256"] = sha256(final_state)

    result["event_counts"] = {
        label: sum(
            1 for row in result["events"] if row.get("label") == label
        )
        for label in [*native_hooks, *snes_hooks, *write_hooks.values()]
    }
    output = args.output / "trace.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "boundaries": result["boundaries"],
                "event_counts": result["event_counts"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
