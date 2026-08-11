#!/usr/bin/env python3
"""Three-way regression for the first organic enemy-motion divergence.

The retained controller movie reaches a byte-identical player/enemy/collision
state at MAME tick 910 and SNES replay label 911.  During the following tick,
the arcade's $01D5F0 physics coroutine executes::

    ASL.L #2,D6
    ASL.L #2,D7
    SUB.L D6,$2E(A1)
    SUB.L D7,$32(A1)

An older checked-in native body shifted only D6.w/D7.w.  This validator loads
the exact retained SNES prestate twice, runs one tick with gameplay native
dispatch disabled and enabled, and compares both results with the uninterrupted
MAME movie oracle.  It also checks the transpiler and deployed body for the
full 32-bit pair-shift lowering.

This is a focused checkpoint differential.  The separately retained cold-boot
campaign remains the fresh-ROM proof; no state-loaded result is labeled as
fresh boot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import capstone


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    EVIDENCE
    / "organic-enemy-first-step-snes-pre-5382968-nexen-v1"
    / "states"
    / "snes-tick-00911.mss"
)
DEFAULT_MAME_DIR = EVIDENCE / "organic-enemy-first-step-mame-v1"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_SOURCE = ROOT / "src" / "escbank3.pasm"
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"
MAME_PRE_TICK = 910
MAME_POST_TICK = 911
SNES_PRE_LABEL = 911
NATIVE_ENTRY = 0x97EC00
TICK_IRAM = 0x0760
HALT_IRAM = 0x004E
GAMEPLAY_NATIVE_GATES = {
    "xlat": 0x071A,
    "choke": 0x073A,
}
IRQ_FIELDS = {
    "interrupt_mask": 0x007C,
    "virtual_irq_pending": 0x00AA,
    "virtual_irq_countdown": 0x00AC,
}
REGIONS = {
    "player_record": (0x12A2, 0x70),
    "player_health": (0x12B4, 2),
    "enemy_record": (0x02DA, 0x70),
    "enemy_fixed_point_position": (0x0308, 8),
    "collision_table": (0x3734, 0x02C0),
}
PAIR_SHIFT = (
    "    asl $18\n"
    "    rol $1A\n"
    "    asl $18\n"
    "    rol $1A\n"
    "    asl $1C\n"
    "    rol $1E\n"
    "    asl $1C\n"
    "    rol $1E\n"
)
CASE_SCOPE = (
    "focused state-loaded three-way differential from the exact first "
    "organic divergence prestate; not fresh-boot proof"
)


sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--mame-dir", type=Path, default=DEFAULT_MAME_DIR)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9253)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("SNES prestate", args.state),
        ("MAME directory", args.mame_dir),
        ("Nexen", args.nexen),
        ("native source", args.source),
        ("arcade program", args.program),
    ):
        if not path.exists():
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


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def le16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def be16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def read_full_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )


def mismatch(
    expected: bytes,
    actual: bytes,
    base: int = 0,
    limit: int = 32,
) -> dict[str, Any]:
    offsets = [
        index
        for index, (left, right) in enumerate(zip(expected, actual))
        if left != right
    ]
    return {
        "equal": not offsets,
        "different_bytes": len(offsets),
        "first": [
            {
                "address": f"F0{base + index:04X}",
                "mame": expected[index],
                "snes": actual[index],
            }
            for index in offsets[:limit]
        ],
    }


def region_comparison(expected: bytes, actual: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, (offset, size) in REGIONS.items():
        result[name] = mismatch(
            expected[offset : offset + size],
            actual[offset : offset + size],
            offset,
        )
    result["mapped_work"] = mismatch(expected[:0x4000], actual[:0x4000])
    result["all_required_regions_equal"] = all(
        result[name]["equal"] for name in REGIONS
    )
    return result


def load_mame_oracle(directory: Path) -> dict[str, Any]:
    pre_path = directory / f"mame-tick-{MAME_PRE_TICK:05d}.work.bin"
    post_path = directory / f"mame-tick-{MAME_POST_TICK:05d}.work.bin"
    log_path = directory / "capture.jsonl"
    for path in (pre_path, post_path, log_path):
        if not path.is_file():
            raise RuntimeError(f"missing MAME oracle component: {path}")
    pre = pre_path.read_bytes()
    post = post_path.read_bytes()
    if len(pre) != 0x10000 or len(post) != 0x10000:
        raise RuntimeError("MAME work dumps must each be exactly 64 KiB")
    boundaries: dict[int, dict[str, Any]] = {}
    writes: list[dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("event") == "boundary":
                boundaries[int(row["tick"])] = row
            elif row.get("event") == "enemy_position_write":
                writes.append(row)
    if set((MAME_PRE_TICK, MAME_POST_TICK)) - set(boundaries):
        raise RuntimeError("MAME capture log lacks required boundaries")

    def boundary(tick: int, work: bytes) -> dict[str, Any]:
        row = boundaries[tick]
        sp = int(row["A7"]) & 0xFFFF
        stack_start = max(0, sp - 32)
        stack_end = min(0x10000, sp + 32)
        return {
            "tick": tick,
            "frame": int(row["frame"]),
            "pc": f"{int(row['PC']) & 0xFFFFFF:06X}",
            "sr": f"{int(row['SR']) & 0xFFFF:04X}",
            "ccr_xnzvc": int(row["SR"]) & 0x1F,
            "interrupt_mask": (int(row["SR"]) >> 8) & 7,
            "registers": {
                name: f"{int(row[name]) & 0xFFFFFFFF:08X}"
                for name in (
                    *[f"D{index}" for index in range(8)],
                    *[f"A{index}" for index in range(8)],
                )
            },
            "stack_window": {
                "address": f"F0{stack_start:04X}",
                "hex": work[stack_start:stack_end].hex(),
            },
            "work_sha256": digest(work),
            "player_health": be16(work, 0x12B4),
            "enemy_position": {
                "x": be16(work, 0x0308),
                "y": be16(work, 0x030C),
            },
        }

    return {
        "pre_path": str(pre_path.resolve()),
        "pre_sha256": sha256(pre_path),
        "post_path": str(post_path.resolve()),
        "post_sha256": sha256(post_path),
        "log_path": str(log_path.resolve()),
        "log_sha256": sha256(log_path),
        "pre_boundary": boundary(MAME_PRE_TICK, pre),
        "post_boundary": boundary(MAME_POST_TICK, post),
        "position_writes": writes,
        "_pre": pre,
        "_post": post,
    }


def capture_console(
    m: McpSession,
    output: Path,
    label: str,
) -> tuple[dict[str, Any], bytes]:
    work = read_full_work(m)
    work_path = output / f"{label}.work.bin"
    work_path.write_bytes(work)
    iram = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0800))
    state = m.get_state()
    sa1 = m.get_cpu_state("Sa1")
    task_contexts = work[0x000A : 0x000A + 16 * 4]
    return (
        {
            "label": label,
            "work": {
                "path": str(work_path.resolve()),
                "sha256": sha256(work_path),
                "size": len(work),
                "mapped_sha256": digest(work[:0x4000]),
                "upper_backing_sha256": digest(work[0x4000:]),
            },
            "snes_tick": le16(iram, TICK_IRAM),
            "halt": le16(iram, HALT_IRAM),
            "video_frame": int(state.get("frameCount", 0)),
            "sa1_cycle_count": int(sa1.get("cycleCount", 0)),
            "sa1_pc": (
                f"{int(sa1.get('k', 0)) & 0xFF:02X}:"
                f"{int(sa1.get('pc', 0)) & 0xFFFF:04X}"
            ),
            "m68k": campaign.register_snapshot(m),
            "irq": {
                name: le16(iram, address)
                for name, address in IRQ_FIELDS.items()
            },
            "task_mask": be16(work, 0x0002),
            "task_contexts": [
                f"{int.from_bytes(task_contexts[index:index + 4], 'big'):08X}"
                for index in range(0, len(task_contexts), 4)
            ],
            "gates": {
                name: le16(iram, address)
                for name, address in GAMEPLAY_NATIVE_GATES.items()
            },
            "player_health": be16(work, 0x12B4),
            "enemy_position": {
                "x": be16(work, 0x0308),
                "y": be16(work, 0x030C),
            },
        },
        work,
    )


def hook_hits(
    notifications: list[dict[str, Any]],
    handle: int,
) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in notifications
        if row.get("method") == "notifications/mesen/hookFired"
        and int(row.get("params", {}).get("handle", -1)) == handle
    ]


def advance_one_tick(
    m: McpSession,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    before_tick = campaign.tick16(m)
    target = (before_tick + 1) & 0xFFFF
    before_frame = int(m.get_state().get("frameCount", 0))
    tick_hook = m.add_write_hook(
        TICK_IRAM,
        cpu_type="Sa1",
        match_value=target & 0xFF,
        match_value_mask=0xFF,
    )
    m.drain_notifications(timeout=0.05)
    runs: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    try:
        for _attempt in range(128):
            run = m.run_until(max_frames=480, hook_handle=tick_hook)
            m.pause()
            runs.append(run)
            notifications.extend(m.drain_notifications(timeout=0.05))
            if campaign.tick16(m) == target:
                break
            if run.get("reason") != "hookFired":
                break
        else:
            raise RuntimeError("too many intermediate execution-hook stops")
    finally:
        m.remove_hook(tick_hook)
    notifications.extend(m.drain_notifications(timeout=0.25))
    after_tick = campaign.tick16(m)
    after_frame = int(m.get_state().get("frameCount", 0))
    span = {
        "before_tick": before_tick,
        "after_tick": after_tick,
        "target_tick": target,
        "tick_delta": 1,
        "before_frame": before_frame,
        "after_frame": after_frame,
        "video_frames": after_frame - before_frame,
        "runs": runs,
    }
    if not runs or runs[-1].get("reason") != "hookFired":
        raise RuntimeError(f"game tick timeout: {span}")
    if after_tick != target:
        raise RuntimeError(f"game tick boundary mismatch: {span}")
    if campaign.halt16(m):
        raise RuntimeError(
            f"interpreter halt ${campaign.halt16(m):04X}: {span}"
        )
    return [span], notifications


def run_variant(
    m: McpSession,
    args: argparse.Namespace,
    native_on: bool,
) -> tuple[dict[str, Any], bytes, bytes]:
    label = "native-on" if native_on else "native-off"
    case_dir = args.output / label
    case_dir.mkdir()
    m.pause()
    m.load_state(args.state.resolve())
    m.pause()
    # The retained prestate already has the neutral controller held.  Leave
    # that serialized controller state untouched: legacy Mesen's set_input
    # requires a frame count and would advance the machine before the shared
    # architectural prestate is captured.
    gate_value = 1 if native_on else 0
    for address in GAMEPLAY_NATIVE_GATES.values():
        m.write_u16(address, gate_value, "Sa1Memory")
    prepared_state = campaign.save_state(m, case_dir / "prepared.mss")
    pre, pre_work = capture_console(m, case_dir, "pre")
    if any(value != gate_value for value in pre["gates"].values()):
        raise RuntimeError(f"{label}: gameplay gates did not configure")

    native_hook = m.add_exec_hook(NATIVE_ENTRY, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        spans, notifications = advance_one_tick(m)
        m.pause()
    finally:
        m.remove_hook(native_hook)
    post, post_work = capture_console(m, case_dir, "post")
    post_state = campaign.save_state(m, case_dir / "post.mss")
    route_hits = hook_hits(notifications, native_hook)
    tick_advanced = (
        (post["snes_tick"] - pre["snes_tick"]) & 0xFFFF
    ) == 1
    expected_route = bool(route_hits) if native_on else not route_hits
    result = {
        "label": label,
        "native_on": native_on,
        "prepared_state": prepared_state,
        "post_state": post_state,
        "pre": pre,
        "post": post,
        "spans": spans,
        "video_frames_per_tick": (
            post["video_frame"] - pre["video_frame"]
        ),
        "sa1_cycles_per_tick": (
            post["sa1_cycle_count"] - pre["sa1_cycle_count"]
        ),
        "native_entry": f"{NATIVE_ENTRY:06X}",
        "native_entry_hits": len(route_hits),
        "native_route_result": "green" if expected_route else "red",
        "tick_advanced_once": tick_advanced,
        "halt_clear": pre["halt"] == 0 and post["halt"] == 0,
    }
    return result, pre_work, post_work


def validate_codegen(source_path: Path, program_path: Path) -> dict[str, Any]:
    program = program_path.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
    decoded = list(md.disasm(program[0x01D66E : 0x01D67A], 0x01D66E))
    expected = [
        (0x01D66E, "asl.l", "#$2, d6"),
        (0x01D670, "asl.l", "#$2, d7"),
        (0x01D672, "sub.l", "d6, $2e(a1)"),
        (0x01D676, "sub.l", "d7, $32(a1)"),
    ]
    actual = [
        (ins.address, ins.mnemonic, ins.op_str)
        for ins in decoded
    ]
    arcade_green = actual == expected

    command = [
        sys.executable,
        str(ROOT / "tools" / "transpile.py"),
        "01D5F0",
        "--bank1",
        "--coroutine",
        "--jt=1D606:0:24,1D726:0:24",
        "--bail",
    ]
    generated = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated_green = generated.stdout.count(PAIR_SHIFT) == 1

    source = source_path.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^L1d5f0_1d662:\n(?P<body>.*?)(?=^L1d5f0_1d67e:)",
        source,
    )
    deployed_body = match.group("body") if match else ""
    deployed_green = deployed_body.count(PAIR_SHIFT) == 1
    stale_low_word_pattern = (
        "    lda $18\n"
        "    asl a\n"
        "    asl a\n"
        "    sta $18\n"
        "    lda $1C\n"
        "    asl a\n"
        "    asl a\n"
        "    sta $1C\n"
    )
    stale_low_word_present = stale_low_word_pattern in deployed_body
    return {
        "arcade_instructions": [
            {
                "pc": f"{pc:06X}",
                "mnemonic": mnemonic,
                "operands": operands,
            }
            for pc, mnemonic, operands in actual
        ],
        "arcade_instruction_result": (
            "green" if arcade_green else "red"
        ),
        "transpiler_command": command,
        "transpiler_stderr": generated.stderr.strip(),
        "transpiler_pair_shift_count": generated.stdout.count(PAIR_SHIFT),
        "transpiler_result": "green" if generated_green else "red",
        "deployed_pair_shift_count": deployed_body.count(PAIR_SHIFT),
        "deployed_stale_low_word_pattern": stale_low_word_present,
        "deployed_result": "green" if deployed_green else "red",
        "result": (
            "green"
            if arcade_green and generated_green and deployed_green
            else "red"
        ),
    }


def main() -> int:
    args = parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = (
        "/home/chad/.dotnet8"
        if args.nexen.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )

    oracle = load_mame_oracle(args.mame_dir.resolve())
    mame_pre = oracle.pop("_pre")
    mame_post = oracle.pop("_post")
    static = validate_codegen(args.source, args.program)

    stderr = args.output / "emulator.stderr.log"
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr,
    ) as m:
        native_off, off_pre, off_post = run_variant(m, args, False)
        native_on, on_pre, on_post = run_variant(m, args, True)

    pre_off = region_comparison(mame_pre, off_pre)
    pre_on = region_comparison(mame_pre, on_pre)
    post_off = region_comparison(mame_post, off_post)
    post_on = region_comparison(mame_post, on_post)
    native_off["pre_vs_mame"] = pre_off
    native_off["post_vs_mame"] = post_off
    native_on["pre_vs_mame"] = pre_on
    native_on["post_vs_mame"] = post_on

    pre_green = (
        pre_off["all_required_regions_equal"]
        and pre_on["all_required_regions_equal"]
    )
    off_green = (
        post_off["all_required_regions_equal"]
        and native_off["native_route_result"] == "green"
        and native_off["tick_advanced_once"]
        and native_off["halt_clear"]
    )
    on_green = (
        post_on["all_required_regions_equal"]
        and native_on["native_route_result"] == "green"
        and native_on["tick_advanced_once"]
        and native_on["halt_clear"]
    )
    if pre_green and off_green and not on_green:
        classification = "native/HLE"
    elif not pre_green:
        classification = "stale save-state data or prestate mismatch"
    elif not off_green:
        classification = "interpreter or hardware-boundary/timing"
    else:
        classification = "no semantic discrepancy"

    green = (
        pre_green
        and off_green
        and on_green
        and static["result"] == "green"
    )
    result = {
        "scope": CASE_SCOPE,
        "rom": {
            "path": str(args.rom.resolve()),
            "sha256": sha256(args.rom),
        },
        "emulator": {
            "path": str(args.nexen.resolve()),
            "sha256": sha256(args.nexen),
        },
        "prestate": {
            "path": str(args.state.resolve()),
            "sha256": sha256(args.state),
            "snes_label": SNES_PRE_LABEL,
            "corresponding_mame_tick": MAME_PRE_TICK,
        },
        "mame_oracle": oracle,
        "codegen": static,
        "native_off": native_off,
        "native_on": native_on,
        "classification": classification,
        "prestate_required_regions_equal": pre_green,
        "native_off_result": "green" if off_green else "red",
        "native_on_result": "green" if on_green else "red",
        "result": "green" if green else "red",
    }
    result_path = args.output / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "classification": classification,
                "codegen": static["result"],
                "native_off": result["native_off_result"],
                "native_on": result["native_on_result"],
                "result": result["result"],
                "result_path": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
