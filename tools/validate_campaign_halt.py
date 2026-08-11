#!/usr/bin/env python3
"""Classify the tick-6619 campaign halt from one exact SNES checkpoint.

The retained state is paused immediately after the real controller transition
at MAME tick 6619.  Run that identical serialized state in two configurations:

* production native gates preserved;
* every interpreter/native, scheduler, choke, and loop gate disabled.

Each arm stops before the low-byte write that commits the interpreter's
``$DEAD`` marker, or at the next production game tick.  Thus the same tool is
both a pre-fix classifier and a post-fix no-halt regression.  Full work RAM,
task contexts, collision data, virtual 68000 state, IRQ cadence, an SA-1 trace,
and a pre-terminal save state are retained.  Gate overrides are classification
writes to private IRAM only; ordinary game memory is never changed.
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
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "campaign-halt-prestate-a08508d-tick6619-v1"
    / "post-event-06619.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
TICK_IRAM = 0x0760
HALT_IRAM = 0x004E
WORK_BASE = 0x400000
WORK_SIZE = 0x10000
COLLISION_START = 0x3734
COLLISION_END = 0x3C74
TASK_CONTEXT_START = 0x0004
TASK_CONTEXT_SIZE = 16 * 4
GATES = (
    (0x071A, "xlat_071a"),
    (0x073A, "choke_073a"),
    (0x0736, "selector_0736"),
    (0x073C, "switch_in_073c"),
    (0x072E, "loop_072e"),
)

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402
import trace_player_native_tick as player_trace  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9490)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0x80)
    parser.add_argument("--max-video-frames", type=int, default=480)
    parser.add_argument("--trace-count", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--all-entry-hooks",
        action="store_true",
        help="record every assembled native entry seam during each arm",
    )
    parser.add_argument(
        "--1e7c0-internal-hooks",
        dest="internal_1e7c0_hooks",
        action="store_true",
        help="record every labeled block inside the native $01E7C0 root",
    )
    parser.add_argument(
        "--variant",
        choices=(
            "native-on-production",
            "xlat-off",
            "choke-off",
            "scheduler-off",
            "loop-off",
            "entry-1e7c0-off",
            "native-off-all-gates",
        ),
        action="append",
        help=(
            "configuration arm to run; repeat as needed (default: production "
            "and all gates off)"
        ),
    )
    args = parser.parse_args()
    if not 0 <= args.buttons <= 0x0FFF:
        parser.error("--buttons must be in 0..0x0fff")
    if args.max_video_frames < 1:
        parser.error("--max-video-frames must be positive")
    if not 1 <= args.trace_count <= 1000:
        parser.error("--trace-count must be in 1..1000")
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


def le32(data: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(data), "little")


def be16(data: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(data), "big")


def read_full_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", WORK_BASE + offset, 0x4000))
        for offset in range(0, WORK_SIZE, 0x4000)
    )


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    virtual = bytes(m.read_memory("Sa1Memory", 0x0040, 0x70))
    work_head = bytes(m.read_memory("snesMemory", WORK_BASE, 0x4000))
    task_context = bytes(
        m.read_memory(
            "snesMemory",
            WORK_BASE + TASK_CONTEXT_START,
            TASK_CONTEXT_SIZE,
        )
    )
    collision = bytes(
        m.read_memory(
            "snesMemory",
            WORK_BASE + COLLISION_START,
            COLLISION_END - COLLISION_START,
        )
    )
    cpu = m.get_cpu_state("Sa1")
    return {
        "label": label,
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", TICK_IRAM, 2)),
        "halt": le16(m.read_memory("Sa1Memory", HALT_IRAM, 2)),
        "pc68k": f"{le32(virtual[0:4]) & 0xFFFFFF:06X}",
        "opcode68k": f"{le16(virtual[4:6]):04X}",
        "sa1_cpu": cpu,
        "m68k": campaign.register_snapshot(m),
        "player": campaign.player_snapshot(m),
        "task_mask": be16(work_head[2:4]),
        "task_context_hex": task_context.hex(),
        "collision_sha256": hashlib.sha256(collision).hexdigest(),
        "work_16k_sha256": hashlib.sha256(work_head).hexdigest(),
        "virtual_irq_pending": le16(
            m.read_memory("Sa1Memory", 0x00AA, 2)
        ),
        "virtual_irq_countdown": le16(
            m.read_memory("Sa1Memory", 0x00AC, 2)
        ),
        "gates": {
            name: le16(m.read_memory("Sa1Memory", address, 2))
            for address, name in GATES
        },
    }


def cadence_sample(m: McpSession) -> dict[str, Any]:
    cpu = m.get_cpu_state("Sa1")
    return {
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", TICK_IRAM, 2)),
        "halt": le16(m.read_memory("Sa1Memory", HALT_IRAM, 2)),
        "pc68k": f"{le32(m.read_memory('Sa1Memory', 0x0040, 4)) & 0xFFFFFF:06X}",
        "sa1_pc": f"{((int(cpu.get('k', 0)) << 16) | int(cpu.get('pc', 0))):06X}",
        "task_mask": be16(m.read_memory("snesMemory", WORK_BASE + 2, 2)),
        "irq_pending": le16(m.read_memory("Sa1Memory", 0x00AA, 2)),
        "irq_countdown": le16(m.read_memory("Sa1Memory", 0x00AC, 2)),
    }


def hook_rows(
    m: McpSession,
    handles: dict[int, str],
) -> list[dict[str, Any]]:
    answer: list[dict[str, Any]] = []
    for notification in m.drain_notifications(timeout=0.05):
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = dict(notification.get("params", {}))
        handle = int(params.get("handle", -1))
        if handle in handles:
            answer.append({"label": handles[handle], **params})
    return answer


def internal_1e7c0_hooks() -> dict[str, int]:
    hooks: dict[str, int] = {}
    for filename, bank in (
        ("escbank3.sym", 0x97),
        ("escbank4.sym", 0x98),
    ):
        for line in (ROOT / "src" / filename).read_text(
            encoding="utf-8"
        ).splitlines():
            fields = line.split()
            if len(fields) != 2 or "1e7c0" not in fields[1].lower():
                continue
            offset_text = fields[0].split(":", 1)[-1]
            # Imported long-address constants appear in another bank's
            # symbol file.  Hook only labels physically assembled here.
            if len(offset_text) != 4:
                continue
            offset = int(offset_text, 16)
            hooks[f"{fields[1]}@{bank:02X}{offset:04X}"] = (
                (bank << 16) | offset
            )
    return hooks


def run_variant(
    args: argparse.Namespace,
    variant: str,
    disabled_gates: set[str],
    output: Path,
    port: int,
) -> dict[str, Any]:
    output.mkdir(parents=True)
    gate_writes: list[dict[str, Any]] = []
    terminal = "timeout"
    responses: list[dict[str, Any]] = []
    cadence: list[dict[str, Any]] = []
    fired: list[dict[str, Any]] = []
    runtime_rom_patches: list[dict[str, Any]] = []

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        input_response = campaign.set_held_input(m, args.buttons)
        for address, name in GATES:
            if name not in disabled_gates:
                continue
            before = le16(m.read_memory("Sa1Memory", address, 2))
            m.write_u16(address, 0, "Sa1Memory")
            gate_writes.append(
                {
                    "kind": "native_gate_classification",
                    "name": name,
                    "address": f"{address:04X}",
                    "before": before,
                    "after": 0,
                }
            )

        restore_rom_patches: list[tuple[int, bytes]] = []
        if variant == "entry-1e7c0-off":
            # Diagnostic-only selective demotion: the existing read-only
            # guard fallback publishes emulated PC $01E7C0 and re-enters the
            # interpreter.  This changes no architectural state before the
            # root and leaves every other native/scheduler gate enabled.
            rom_offset = 0x2C2E00
            original = bytes(
                m.read_memory("snesPrgRom", rom_offset, 4)
            )
            replacement = bytes.fromhex("5cb8ae98")
            if original != bytes.fromhex("c230a534"):
                raise RuntimeError(
                    "entry_1e7c0 bytes moved: "
                    f"expected c230a534, got {original.hex()}"
                )
            m.write_memory(
                "snesPrgRom",
                rom_offset,
                replacement.hex(),
            )
            restore_rom_patches.append((rom_offset, original))
            runtime_rom_patches.append(
                {
                    "kind": "selective_native_classification",
                    "entry": "98AE00",
                    "target": "98AEB8 h1e7c0_guard_fallback",
                    "rom_offset": f"{rom_offset:06X}",
                    "before": original.hex(),
                    "temporary": replacement.hex(),
                    "architectural_effect_before_entry": "none",
                }
            )

        start = snapshot(m, "start")
        if start["halt"]:
            raise RuntimeError(f"{variant}: input state already halted")
        start_work = read_full_work(m)
        (output / "start.work.bin").write_bytes(start_work)
        start_tick = int(start["tick"])
        target_tick = (start_tick + 1) & 0xFFFF

        # The 65816 stores $DEAD little-endian, so the first committing byte at
        # $004E is $AD.  The hook freezes before that write.
        handles: dict[int, str] = {}
        halt_handle = m.add_write_hook(
            HALT_IRAM,
            cpu_type="Sa1",
            match_value=0xAD,
            match_value_mask=0xFF,
        )
        handles[halt_handle] = "halt_low_write"
        if args.all_entry_hooks:
            for entry_label, address in player_trace.all_entry_hooks().items():
                handle = m.add_exec_hook(address, cpu_type="Sa1")
                handles[handle] = entry_label
        if args.internal_1e7c0_hooks:
            for entry_label, address in internal_1e7c0_hooks().items():
                handle = m.add_exec_hook(address, cpu_type="Sa1")
                handles[handle] = entry_label
        m.drain_notifications(timeout=0.05)
        m.trace_log(count=1, cpu_type="Sa1")
        cadence.append(cadence_sample(m))

        try:
            for _index in range(args.max_video_frames):
                response = m.run_frames(1)
                m.pause()
                responses.append(response)
                rows = hook_rows(m, handles)
                fired.extend(rows)
                if any(
                    row.get("label") == "halt_low_write"
                    for row in rows
                ):
                    terminal = "pre_halt_write"
                    break
                current_tick = le16(
                    m.read_memory("Sa1Memory", TICK_IRAM, 2)
                )
                cadence.append(cadence_sample(m))
                if current_tick == target_tick:
                    terminal = "next_tick"
                    break
                if current_tick != start_tick:
                    terminal = "tick_overshoot"
                    break
        finally:
            for handle in handles:
                m.remove_hook(handle)
            m.drain_notifications(timeout=0.05)

        m.pause()
        end = snapshot(m, terminal)
        end_work = read_full_work(m)
        (output / "end.work.bin").write_bytes(end_work)
        trace = m.trace_log(count=args.trace_count, cpu_type="Sa1")
        for rom_offset, original in restore_rom_patches:
            m.write_memory("snesPrgRom", rom_offset, original.hex())
        terminal_state = campaign.save_state(
            m, output / f"{terminal}.mss"
        )
        screenshot = campaign.screenshot(
            m, output / f"{terminal}.png"
        )

    result = {
        "variant": variant,
        "disabled_gates": sorted(disabled_gates),
        "load_response": load_response,
        "input_response": input_response,
        "buttons": args.buttons,
        "runtime_game_memory_writes": gate_writes,
        "runtime_rom_patches": runtime_rom_patches,
        "terminal": terminal,
        "start": start,
        "end": end,
        "video_frames": end["video_frame"] - start["video_frame"],
        "tick_delta": (int(end["tick"]) - int(start["tick"])) & 0xFFFF,
        "halt_hook_events": fired,
        "native_entry_events": [
            row for row in fired if row.get("label") != "halt_low_write"
        ],
        "run_responses": responses,
        "irq_cadence": cadence,
        "trace": trace,
        "state": terminal_state,
        "screenshot": screenshot,
        "work": {
            "start_path": str(output / "start.work.bin"),
            "start_sha256": hashlib.sha256(start_work).hexdigest(),
            "end_path": str(output / "end.work.bin"),
            "end_sha256": hashlib.sha256(end_work).hexdigest(),
            "changed_bytes": sum(a != b for a, b in zip(start_work, end_work)),
        },
    }
    result_path = output / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(result_path),
        "sha256": sha256(result_path),
        "terminal": terminal,
        "video_frames": result["video_frames"],
        "tick_delta": result["tick_delta"],
        "halt_hook_events": sum(
            row.get("label") == "halt_low_write" for row in fired
        ),
        "native_entry_events": sum(
            row.get("label") != "halt_low_write" for row in fired
        ),
        "start": start,
        "end": end,
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    gate_sets = {
        "native-on-production": set(),
        "xlat-off": {"xlat_071a"},
        "choke-off": {"choke_073a"},
        "scheduler-off": {"selector_0736", "switch_in_073c"},
        "loop-off": {"loop_072e"},
        "entry-1e7c0-off": set(),
        "native-off-all-gates": {name for _address, name in GATES},
    }
    requested = args.variant or [
        "native-on-production",
        "native-off-all-gates",
    ]
    arms = [
        run_variant(
            args,
            variant,
            gate_sets[variant],
            args.output / variant,
            args.port + index,
        )
        for index, variant in enumerate(requested)
    ]
    by_name = {Path(arm["path"]).parent.name: arm for arm in arms}
    production = by_name.get("native-on-production")
    native_off = (
        by_name.get("native-off-all-gates")
        or by_name.get("xlat-off")
        or by_name.get("entry-1e7c0-off")
    )
    if (
        production is not None
        and native_off is not None
        and production["terminal"] == "pre_halt_write"
        and native_off["terminal"] == "next_tick"
    ):
        classification = "native_hle"
    elif (
        production is not None
        and native_off is not None
        and production["terminal"] == "next_tick"
        and native_off["terminal"] == "next_tick"
    ):
        classification = "no_halt_production_and_native_off"
    elif len(arms) >= 2 and all(
        arm["terminal"] == "pre_halt_write" for arm in arms
    ):
        classification = "interpreter_or_shared_state"
    else:
        classification = "unresolved"
    summary = {
        "scope": (
            "identical retained tick-6619 checkpoint, real controller mask, "
            "production native-on versus all native gates off; pre-$DEAD "
            "write or next-tick terminal; full work/stack/task/collision and "
            "IRQ-cadence capture; checkpoint differential, not fresh boot"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "arms": arms,
        "classification": classification,
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": str(summary_path),
                "classification": classification,
                "arms": [
                    {
                        "terminal": arm["terminal"],
                        "video_frames": arm["video_frames"],
                        "tick_delta": arm["tick_delta"],
                        "halt_hook_events": arm["halt_hook_events"],
                    }
                    for arm in arms
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if classification != "unresolved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
