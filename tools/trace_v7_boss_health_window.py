#!/usr/bin/env python3
"""Bounded v7 Stage-1 boss-health write trace from an exact checkpoint.

This is a diagnostic continuation only.  It loads the supplied serialized
checkpoint without ROM/WRAM migration or patches, watches the mapped
MC68000-$F00A76 health word, and records paused Nexen hook notifications plus
small state observations.  It is not fresh-boot, semantic, visual, FPS, or
playthrough evidence.
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
MESEN_PY = Path("/home/chad/Mesen2/python")
V7_SHA256 = "45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72"
HEALTH_ADDR = 0x400A76  # mapped physical window for MC68000 $F00A76
HEALTH_END = HEALTH_ADDR + 1  # inclusive two-byte physical watch range
TICK_ADDR = 0x0760  # established game-tick publication in SA-1 IRAM
LOGICAL_PC_ADDR = 0x0040  # 32-bit little-endian MC68000 PC shadow
EXPECTED_NEXEN_DLL_SHA256 = "7e15c1d8ac5157be5df8c6419ffc91ee84f662454c0a15d4edde457258e3ebc6"
EXPECTED_NEXEN_DEPS_SHA256 = "6745974f302b812786f5bd0d0904eef01e983fefe9f48814342837b7e8a44046"

sys.path.insert(0, str(MESEN_PY))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def be16(m: McpSession, address: int) -> int:
    return int.from_bytes(bytes(m.read_memory("snesMemory", address, 2)), "big")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--nexen", type=Path, required=True, help="exact combined Nexen executable")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--port", type=int, default=8897)
    p.add_argument("--mame-completed-tick", type=int, required=True)
    p.add_argument("--expected-snes-start-tick", type=int, required=True)
    p.add_argument("--end-snes-tick", type=int, required=True)
    p.add_argument("--held-buttons", type=lambda x: int(x, 0), required=True)
    p.add_argument("--expected-pre-health", type=int, required=True)
    p.add_argument("--expected-new-health", type=int, required=True)
    p.add_argument("--expected-owner-pc", type=lambda x: int(x, 0), action="append", required=True)
    p.add_argument("--expected-state-sha256", required=True)
    p.add_argument("--expected-iram-sha256", required=True)
    p.add_argument("--bulk-trace", type=Path, required=True, help="raw hook-event JSONL path")
    p.add_argument("--max-video-frames", type=int, default=8)
    return p.parse_args()


def hook_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row.get("params", {}))
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def read_word(m: McpSession) -> int:
    return be16(m, HEALTH_ADDR)


def cpu_snapshot(m: McpSession) -> dict[str, Any]:
    cpu = dict(m.get_cpu_state("Sa1"))
    logical_pc = int.from_bytes(bytes(m.read_memory("Sa1Memory", LOGICAL_PC_ADDR, 4)), "little") & 0xFFFFFF
    return {
        "sa1_pc": ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF),
        "logical_m68k_pc": logical_pc,
        "sa1": cpu,
    }


def main() -> int:
    args = parse_args()
    for label, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            raise SystemExit(f"missing {label}: {path}")
    if args.output.exists() or args.bulk_trace.exists():
        raise SystemExit("refusing existing output or bulk trace")
    if args.end_snes_tick < args.expected_snes_start_tick:
        raise SystemExit("end SNES tick precedes expected start")
    if args.mame_completed_tick != args.expected_snes_start_tick + 6:
        raise SystemExit("MAME completed tick must be six ahead of the retained SNES tick")
    if not 0 <= args.held_buttons <= 0x0FFF or args.max_video_frames < 1:
        raise SystemExit("invalid input mask or frame budget")
    rom_sha = sha256(args.rom)
    if rom_sha != V7_SHA256:
        raise SystemExit(f"refusing non-v7 ROM: {rom_sha} != {V7_SHA256}")
    rom_bytes = args.rom.read_bytes()
    if len(rom_bytes) != 0x400000 or int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production/Testflag ROM")
    state_sha = sha256(args.state)
    if state_sha != args.expected_state_sha256:
        raise SystemExit(f"state SHA mismatch: {state_sha}")
    iram_path = Path(str(args.state) + ".sa1-iram.bin")
    if not iram_path.is_file() or sha256(iram_path) != args.expected_iram_sha256:
        raise SystemExit("SA-1 IRAM sidecar missing or SHA mismatch")
    dll = args.nexen.with_name("Nexen.dll")
    deps = args.nexen.with_name("Nexen.deps.json")
    if not dll.is_file() or not deps.is_file():
        raise SystemExit("combined Nexen managed DLL/deps missing")
    if sha256(dll) != EXPECTED_NEXEN_DLL_SHA256 or sha256(deps) != EXPECTED_NEXEN_DEPS_SHA256:
        raise SystemExit("combined Nexen managed/deps identity mismatch")
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:/home/chad/.dotnet8:" + os.environ.get("PATH", "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = args.output.parent / (args.output.stem + ".nexen.stderr.log")
    raw: list[dict[str, Any]] = []
    committed = None
    frames_advanced = 0
    with McpSession(rom=args.rom.resolve(), mesen=args.nexen.resolve(), cwd=ROOT, port=args.port,
                    boot_wait=8.0, socket_timeout=120.0, stderr_log=stderr_log) as m:
        m.pause(); m.load_state(str(args.state.resolve())); m.pause()
        start_tick = int.from_bytes(bytes(m.read_memory("Sa1Memory", TICK_ADDR, 2)), "little")
        if start_tick != args.expected_snes_start_tick:
            raise RuntimeError(f"checkpoint SNES tick {start_tick} != expected {args.expected_snes_start_tick}")
        if read_word(m) != args.expected_pre_health:
            raise RuntimeError("checkpoint pre-health mismatch")
        m.tool("set_input", {"port": 0, "buttons": args.held_buttons, "hold": True})
        hook = m.add_write_hook(HEALTH_ADDR, end_address=HEALTH_END, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            while frames_advanced < args.max_video_frames:
                before_frame = int(m.get_state().get("frameCount", 0))
                result = m.run_until(
                    max_frames=min(120, args.max_video_frames - frames_advanced),
                    hook_handle=hook,
                )
                m.pause(); after_frame = int(m.get_state().get("frameCount", 0))
                frames_advanced += max(0, after_frame - before_frame)
                for row in hook_events(m.drain_notifications(timeout=0.05)):
                    raw.append({"order": len(raw), "params": row, "pre_health": read_word(m),
                                "tick": int.from_bytes(bytes(m.read_memory("Sa1Memory", TICK_ADDR, 2)), "little"),
                                **cpu_snapshot(m)})
                if raw:
                    break
                if result.get("reason") == "error":
                    raise RuntimeError(f"Nexen run error: {result!r}")
            if not raw:
                raise RuntimeError("health write did not occur within frame budget")
            m.remove_hook(hook)
            before_commit = int(m.get_state().get("frameCount", 0))
            m.run_frames(1); m.pause()
            committed = {"health": read_word(m), "frames_advanced_after_hook": int(m.get_state().get("frameCount", 0)) - before_commit}
        finally:
            try: m.remove_hook(hook)
            except Exception: pass
            m.drain_notifications(timeout=0.05)
    args.bulk_trace.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in raw), encoding="utf-8")
    owner = raw[0].get("logical_m68k_pc", -1)
    write_bytes: dict[int, int] = {}
    for row in raw:
        params = row["params"]
        address = params.get("address")
        value = params.get("value", params.get("newValue"))
        if isinstance(address, int) and isinstance(value, int):
            if HEALTH_ADDR <= address <= HEALTH_END:
                write_bytes[address] = value & 0xFF
    write_word = (
        (write_bytes[HEALTH_ADDR] << 8) | write_bytes[HEALTH_END]
        if set(write_bytes) == {HEALTH_ADDR, HEALTH_END}
        else None
    )
    report = {"scope": "one-entry exact v7 checkpoint health-write diagnostic; no migration/patch; pre-store hook plus one-frame commit confirmation",
              "rom_sha256": rom_sha, "state_sha256": state_sha, "iram_sha256": args.expected_iram_sha256,
              "mame_completed_tick": args.mame_completed_tick, "expected_snes_start_tick": args.expected_snes_start_tick,
              "end_snes_tick": args.end_snes_tick, "held_buttons": args.held_buttons,
              "health_range": [f"{HEALTH_ADDR:06X}", f"{HEALTH_END:06X}"], "frames_advanced": frames_advanced,
              "pre_health": args.expected_pre_health,
              "hook_write_bytes": {
                  f"{address:06X}": value
                  for address, value in sorted(write_bytes.items())
              },
              "hook_write_word": write_word,
              "committed": committed,
              "logical_owner_pc": owner, "allowed_owner_pcs": args.expected_owner_pc,
              "notification_context_allowed": owner in args.expected_owner_pc,
              "notification_pc_scope": (
                  "observational hook context only; not original-routine "
                  "ownership proof"
              ),
              "event_order": [r["order"] for r in raw],
              "bulk_trace": str(args.bulk_trace.resolve()), "native_targets": "none; interpreted init/damage"}
    report["pass"] = (
        write_word == args.expected_new_health
        and committed is not None
        and committed["health"] == args.expected_new_health
        and args.expected_snes_start_tick
        <= int(raw[0]["tick"])
        <= args.end_snes_tick
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "frames_advanced": frames_advanced, "committed": committed}, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
