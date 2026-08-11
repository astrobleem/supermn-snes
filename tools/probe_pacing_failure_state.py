#!/usr/bin/env python3
"""Read serialized S-CPU/pacing state without resuming a forensic failure.

SA-1 IRAM is intentionally excluded: Nexen save states do not provide an
accepted reload contract for that domain at arbitrary paused boundaries.  Use
the campaign's live terminal snapshot for logical-PC/timer truth.  This probe
only asks whether the serialized S-CPU and shared pacing domains explain a
previously observed WAI stall; it is not production or continuation evidence.
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
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-safe-checkpoint-publish/Nexen"
)

sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 2], "little")


def configure_dotnet() -> None:
    dotnet10 = "/home/chad/.dotnet10"
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet10
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet10, dotnet8)
    ]
    os.environ["PATH"] = ":".join([dotnet10, dotnet8, *current])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9366)
    parser.add_argument(
        "--snes-window-address",
        type=lambda value: int(value, 0),
        action="append",
        default=[],
        help=(
            "also read a 16-byte S-CPU memory window centered on this "
            "24-bit address; may be repeated"
        ),
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    configure_dotnet()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr = args.output.with_suffix(".stderr.log")
    report: dict[str, Any] = {
        "scope": (
            "read-only post-load inspection of serialized S-CPU/shared pacing "
            "domains; SA-1 IRAM excluded; not resumable-state, production, "
            "game-semantic, timing-rate, or continuation evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "execution_resumed_after_load": False,
        "architectural_writes_after_load": False,
        "sa1_iram_read_after_load": False,
    }
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=stderr,
    ) as m:
        m.pause()
        report["load_response"] = m.load_state(args.state.resolve())
        m.pause()
        shared = bytes(m.read_memory("snesMemory", 0x410120, 0x32))
        request_ack = bytes(m.read_memory("snesMemory", 0x003300, 4))
        control = bytes(m.read_memory("snesMemory", 0x002200, 0x10))
        private = bytes(m.read_memory("snesWorkRam", 0x1F00, 0x20))
        stack = bytes(m.read_memory("snesWorkRam", 0x0100, 0x100))
        snes_cpu = dict(m.get_cpu_state("Snes"))
        current_address = (
            ((int(snes_cpu.get("k", 0)) & 0xFF) << 16)
            | (int(snes_cpu.get("pc", 0)) & 0xFFFF)
        )
        current_window_start = (
            (current_address & 0xFF0000)
            | ((current_address - 8) & 0xFFFF)
        )
        current_window = bytes(
            m.read_memory("snesMemory", current_window_start, 16)
        )
        extra_windows: list[dict[str, Any]] = []
        for address in args.snes_window_address:
            if not 0 <= address <= 0xFFFFFF:
                parser.error(
                    f"--snes-window-address out of range: {address}"
                )
            start = (address & 0xFF0000) | ((address - 8) & 0xFFFF)
            raw = bytes(m.read_memory("snesMemory", start, 16))
            extra_windows.append(
                {
                    "address": address,
                    "window_start": start,
                    "window_hex": raw.hex(),
                    "prior_byte": raw[7],
                    "current_byte": raw[8],
                }
            )
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
            window_start = (
                (return_address & 0xFF0000)
                | ((return_address - 8) & 0xFFFF)
            )
            cpu_window = bytes(
                m.read_memory("snesMemory", window_start, 16)
            )
            interrupt_frame = {
                "stack_pointer": stack_pointer,
                "saved_ps": saved[0],
                "return_address": return_address,
                "prior_address": prior_address,
                "prior_opcode": int(
                    m.read_memory("snesMemory", prior_address, 1)[0]
                ),
                "return_window_start": window_start,
                "return_window_snes_memory_hex": cpu_window.hex(),
                "raw_hex": saved.hex(),
            }
            if (return_address >> 16) in (0x00, 0x7E, 0x7F):
                wram_offset = return_address & 0x1FFFF
                wram_start = (wram_offset - 8) & 0x1FFFF
                interrupt_frame["return_window_wram_offset"] = wram_start
                interrupt_frame["return_window_snes_wram_hex"] = bytes(
                    m.read_memory("snesWorkRam", wram_start, 16)
                ).hex()
        else:
            interrupt_frame = {
                "unavailable": True,
                "stack_pointer": stack_pointer,
                "emulation_mode": snes_cpu.get("emulationMode"),
            }
        report.update(
            {
                "frame": int(m.get_state().get("frameCount", 0)),
                "snes_cpu": snes_cpu,
                "snes_pc_window": {
                    "current_address": current_address,
                    "window_start": current_window_start,
                    "window_hex": current_window.hex(),
                    "prior_address": (
                        (current_address & 0xFF0000)
                        | ((current_address - 1) & 0xFFFF)
                    ),
                    "prior_byte": current_window[7],
                    "current_byte": current_window[8],
                },
                "extra_snes_windows": extra_windows,
                "sa1_cpu_serialized": dict(m.get_cpu_state("Sa1")),
                "snes_interrupt_frame": interrupt_frame,
                "snes_stack_0100_01ff_hex": stack.hex(),
                "shared_pacing": {
                    "arm_410122": le16(shared, 0x02),
                    "vblank_epoch_41012a": shared[0x0A],
                    "last_release_epoch_41012b": shared[0x0B],
                    "cadence_marker_41012c": shared[0x0C],
                    "scpu_ready_41012d": shared[0x0D],
                    "debt_410130": shared[0x10],
                    "raw_hex": shared.hex(),
                },
                "request_ack": {
                    "frame_request_3300": le16(request_ack, 0),
                    "frame_ack_3302": le16(request_ack, 2),
                    "raw_hex": request_ack.hex(),
                },
                "sa1_control_2200_220f_hex": control.hex(),
                "scpu_private_7e1f00_1f1f_hex": private.hex(),
            }
        )

    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "frame": report["frame"],
                "shared_pacing": report["shared_pacing"],
                "request_ack": report["request_ack"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
