#!/usr/bin/env python3
"""Compare one organic $01E7C0 script record at exact native seams.

The reference ROM is first parked at the bank-$97 cold trampoline on a record
whose A2 or A3 script word is nonzero.  That exact live checkpoint is then
replayed through both ROMs from ``h1e7c0_hot_loop`` and sampled at:

* the unchanged generated ``L1e7c0_1e94a`` script seam; and
* the common ``h1e7c0_hot_reentry`` after the record's DBRA backedge.

This is checkpointed differential evidence, not an end-to-end FPS test.  The
temporary BRA loops are restored before every replay and never enter a ROM
artifact on disk.
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
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

import capture_1e7c0_cold as coldcap


SPIN = bytes.fromhex("80fe")
CHUNK = 0x4000
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]
FLAG_OFFSETS = {"Z": 0x60, "C": 0x6E, "N": 0x70, "V": 0x72, "X": 0xA2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", required=True, type=Path)
    parser.add_argument("--candidate-rom", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nexen", type=Path, default=coldcap.DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7630)
    parser.add_argument("--max-cold-edges", type=int, default=32)
    parser.add_argument(
        "--script-occurrence",
        type=int,
        default=0,
        help="zero-based script-state cold edge to checkpoint",
    )
    parser.add_argument(
        "--buttons",
        type=lambda value: int(value, 0),
        default=McpSession.BTN_RIGHT | McpSession.BTN_B,
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_chunks(session: McpSession, address: int, length: int) -> bytes:
    result = bytearray()
    for offset in range(0, length, CHUNK):
        size = min(CHUNK, length - offset)
        result.extend(session.read_memory("snesMemory", address + offset, size))
    return bytes(result)


def native_pc(session: McpSession) -> int:
    state = session.get_cpu_state("Sa1")
    return ((int(state.get("k", 0)) << 16) | int(state.get("pc", 0))) & 0xFFFFFF


def set_native_pc(session: McpSession, address: int) -> None:
    state = dict(session.get_cpu_state("Sa1"))
    state["pc"] = address & 0xFFFF
    state["k"] = (address >> 16) & 0xFF
    allowed = (
        "cpuType",
        "pc",
        "k",
        "a",
        "x",
        "y",
        "sp",
        "d",
        "dbr",
        "ps",
        "emulationMode",
    )
    session.tool(
        "set_cpu_state", {key: state[key] for key in allowed if key in state}
    )


def require_hit(
    session: McpSession, handle: int, address: int, label: str, max_frames: int
) -> None:
    session.drain_notifications(timeout=0.05)
    hit = session.run_until(max_frames=max_frames, hook_handle=handle)
    session.pause()
    actual = native_pc(session)
    if (hit or {}).get("reason") != "hookFired" or actual != address:
        raise RuntimeError(
            f"{label}: expected ${address:06X}, got ${actual:06X}: {hit!r}"
        )


def find_script_checkpoint(
    *,
    rom: Path,
    state: Path,
    nexen: Path,
    output: Path,
    port: int,
    buttons: int,
    max_edges: int,
    script_occurrence: int,
    cold: int,
    generated: int,
) -> tuple[Path, dict[str, Any]]:
    checkpoint = output / "script-record-cold.mss"
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=output / "checkpoint-nexen.stderr.log",
    ) as session:
        session.pause()
        session.load_state(state)
        session.pause()
        session.tool("set_input", {"port": 0, "buttons": buttons, "hold": True})

        original_cold = bytes(session.read_memory("snesMemory", cold, 2))
        original_generated = bytes(
            session.read_memory("snesMemory", generated, 2)
        )
        session.write_memory("snesMemory", cold, SPIN.hex())
        cold_hook = session.add_exec_hook(cold, cpu_type="Sa1")
        try:
            script_index = 0
            for index in range(max_edges):
                require_hit(
                    session,
                    cold_hook,
                    cold,
                    f"cold edge {index}",
                    max_frames=1200,
                )
                capture = coldcap.decode_capture(session, index)
                is_script = capture["inferred_guard"] in (
                    "a2-script-state",
                    "a3-script-state",
                )
                if is_script and script_index == script_occurrence:
                    capture["script_occurrence"] = script_index
                    response = session.save_state(checkpoint.resolve())
                    deadline = time.monotonic() + 5.0
                    while time.monotonic() < deadline:
                        if checkpoint.is_file() and checkpoint.stat().st_size:
                            break
                        time.sleep(0.05)
                    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
                        raise RuntimeError(
                            f"checkpoint save did not create {checkpoint}: {response!r}"
                        )
                    return checkpoint, capture
                if is_script:
                    script_index += 1

                # Execute this cold record through the unchanged generated body,
                # park at its common re-entry, then arm the next cold edge.
                session.write_memory("snesMemory", generated, SPIN.hex())
                session.write_memory("snesMemory", cold, original_cold.hex())
                session.remove_hook(cold_hook)
                generated_hook = session.add_exec_hook(generated, cpu_type="Sa1")
                require_hit(
                    session,
                    generated_hook,
                    generated,
                    f"cold edge {index} generated handoff",
                    max_frames=16,
                )
                session.write_memory("snesMemory", cold, SPIN.hex())
                session.write_memory(
                    "snesMemory", generated, original_generated.hex()
                )
                session.remove_hook(generated_hook)
                cold_hook = session.add_exec_hook(cold, cpu_type="Sa1")
        finally:
            session.pause()
            session.write_memory("snesMemory", cold, original_cold.hex())
            session.write_memory(
                "snesMemory", generated, original_generated.hex()
            )
            try:
                session.remove_hook(cold_hook)
            except Exception:
                pass
    raise RuntimeError(f"no script-state cold edge in first {max_edges} edges")


def architectural_state(dp: bytes) -> dict[str, Any]:
    regs = {
        name: int.from_bytes(dp[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(REG_NAMES)
    }
    flags = {
        name: int.from_bytes(dp[offset : offset + 2], "little")
        for name, offset in FLAG_OFFSETS.items()
    }
    ccr = (
        ((flags["X"] & 1) << 4)
        | ((flags["N"] & 1) << 3)
        | ((flags["Z"] & 1) << 2)
        | ((flags["V"] & 1) << 1)
        | (flags["C"] & 1)
    )
    return {
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "pc": f"{int.from_bytes(dp[0x40:0x44], 'little') & 0xFFFFFF:06X}",
        "flags": flags,
        "ccr": f"{ccr:02X}",
        "interrupt_mask": int.from_bytes(dp[0x7C:0x7E], "little") & 7,
        "usp": f"{int.from_bytes(dp[0xA4:0xA8], 'little'):08X}",
        "halt": f"{int.from_bytes(dp[0x4E:0x50], 'little'):04X}",
    }


def capture_stop(
    *,
    name: str,
    rom: Path,
    checkpoint: Path,
    nexen: Path,
    output: Path,
    port: int,
    buttons: int,
    loop: int,
    cold: int,
    generated: int,
    stop: int,
    stop_name: str,
) -> dict[str, Any]:
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=output / f"{name}-{stop_name}-nexen.stderr.log",
    ) as session:
        session.pause()
        pristine = {
            address: bytes(session.read_memory("snesMemory", address, 2))
            for address in (loop, cold, generated, stop)
        }
        session.load_state(checkpoint)
        session.pause()
        for address, data in pristine.items():
            session.write_memory("snesMemory", address, data.hex())
        session.tool("set_input", {"port": 0, "buttons": buttons, "hold": True})
        set_native_pc(session, loop)

        # Nexen hook notifications carry the exact hit but the live SA-1 can
        # advance before the debugger pause is applied.  A temporary self-loop
        # at the sampling seam makes the eventual coherent read atomic.
        session.write_memory("snesMemory", stop, SPIN.hex())
        if bytes(session.read_memory("snesMemory", stop, 2)) != SPIN:
            raise RuntimeError(f"{name} {stop_name}: temporary stop loop rejected")

        start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        hook = session.add_exec_hook(stop, cpu_type="Sa1")
        try:
            require_hit(
                session,
                hook,
                stop,
                f"{name} {stop_name}",
                max_frames=120,
            )
        finally:
            session.remove_hook(hook)
        end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        dp = bytes(session.read_memory("Sa1Memory", 0, 0xB0))
        work = read_chunks(session, 0x400000, 0x10000)
        (output / f"{name}-{stop_name}-dp.bin").write_bytes(dp)
        (output / f"{name}-{stop_name}-game-ram.bin").write_bytes(work)
        cpu = session.get_cpu_state("Sa1")
        return {
            "name": name,
            "stop": stop_name,
            "rom_sha256": sha256_file(rom),
            "sa1_cycle_delta": end_cycles - start_cycles,
            "native_cpu": {
                key: int(cpu[key])
                for key in ("a", "x", "y", "sp", "d", "dbr", "k", "pc", "ps")
                if key in cpu
            },
            "architectural": architectural_state(dp),
            "scratch_80_9f": dp[0x80:0xA0].hex(),
            "game_ram_sha256": sha256_bytes(work),
        }


def dict_differences(left: Any, right: Any, prefix: str = "") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                differences.append(
                    {"path": path, "reference": left.get(key), "candidate": right.get(key)}
                )
            else:
                differences.extend(dict_differences(left[key], right[key], path))
        return differences
    if left != right:
        return [{"path": prefix, "reference": left, "candidate": right}]
    return []


def byte_differences(left: bytes, right: bytes) -> dict[str, Any]:
    offsets = [index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]]
    return {
        "count": len(offsets),
        "first": [
            {"offset": offset, "reference": left[offset], "candidate": right[offset]}
            for offset in offsets[:64]
        ],
    }


def compare_stop(output: Path, stop_name: str, reference: dict, candidate: dict) -> dict:
    left = (output / f"reference-{stop_name}-game-ram.bin").read_bytes()
    right = (output / f"candidate-{stop_name}-game-ram.bin").read_bytes()
    architectural_differences = dict_differences(
        reference["architectural"], candidate["architectural"]
    )
    game_ram = byte_differences(left, right)
    return {
        "stop": stop_name,
        "architectural_match": not architectural_differences,
        "architectural_differences": architectural_differences,
        "game_ram_match": game_ram["count"] == 0,
        "game_ram_differences": game_ram,
        "reference_cycles": reference["sa1_cycle_delta"],
        "candidate_cycles": candidate["sa1_cycle_delta"],
        "local_cycle_delta": (
            candidate["sa1_cycle_delta"] - reference["sa1_cycle_delta"]
        ),
        "scratch_match": reference["scratch_80_9f"] == candidate["scratch_80_9f"],
        "reference_scratch_80_9f": reference["scratch_80_9f"],
        "candidate_scratch_80_9f": candidate["scratch_80_9f"],
    }


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    if args.max_cold_edges <= 0:
        raise SystemExit("--max-cold-edges must be positive")
    if args.script_occurrence < 0:
        raise SystemExit("--script-occurrence must be nonnegative")
    if not 0 <= args.buttons <= 0x0FFF:
        raise SystemExit("--buttons must be a 12-bit Nexen controller mask")
    for path in (
        args.reference_rom,
        args.candidate_rom,
        args.state,
        args.nexen,
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True)

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    esc3 = ROOT / "src/escbank3.sym"
    esc4 = ROOT / "src/escbank4.sym"
    cold = coldcap.symbol_address(esc3, 0x97, "h1e7c0_hot_cold")
    loop = coldcap.symbol_address(esc3, 0x97, "h1e7c0_hot_loop")
    reentry = coldcap.symbol_address(esc3, 0x97, "h1e7c0_hot_reentry")
    generated = coldcap.symbol_address(esc4, 0x98, "L1e7c0_1e7cc")
    script_seam = coldcap.symbol_address(esc4, 0x98, "L1e7c0_1e94a")

    checkpoint, target = find_script_checkpoint(
        rom=args.reference_rom.resolve(),
        state=args.state.resolve(),
        nexen=args.nexen.resolve(),
        output=args.output,
        port=args.port,
        buttons=args.buttons,
        max_edges=args.max_cold_edges,
        script_occurrence=args.script_occurrence,
        cold=cold,
        generated=generated,
    )

    samples: dict[str, dict[str, dict[str, Any]]] = {}
    run_index = 0
    for stop_name, stop in (("script-seam", script_seam), ("record-reentry", reentry)):
        samples[stop_name] = {}
        for name, rom in (
            ("reference", args.reference_rom.resolve()),
            ("candidate", args.candidate_rom.resolve()),
        ):
            run_index += 1
            samples[stop_name][name] = capture_stop(
                name=name,
                rom=rom,
                checkpoint=checkpoint.resolve(),
                nexen=args.nexen.resolve(),
                output=args.output,
                port=args.port + run_index,
                buttons=args.buttons,
                loop=loop,
                cold=cold,
                generated=generated,
                stop=stop,
                stop_name=stop_name,
            )

    comparisons = {
        stop_name: compare_stop(
            args.output,
            stop_name,
            pair["reference"],
            pair["candidate"],
        )
        for stop_name, pair in samples.items()
    }
    passed = all(
        comparison["architectural_match"] and comparison["game_ram_match"]
        for comparison in comparisons.values()
    )
    summary = {
        "scope": "checkpointed one-record differential; not fps",
        "passed": passed,
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_sha256": sha256_file(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_sha256": sha256_file(args.candidate_rom),
        "source_state": str(args.state.resolve()),
        "source_state_sha256": sha256_file(args.state),
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": sha256_file(checkpoint),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256_file(args.nexen),
        "buttons": args.buttons,
        "addresses": {
            "loop": f"{loop:06X}",
            "cold": f"{cold:06X}",
            "generated": f"{generated:06X}",
            "script_seam": f"{script_seam:06X}",
            "record_reentry": f"{reentry:06X}",
        },
        "target": target,
        "samples": samples,
        "comparisons": comparisons,
    }
    with (args.output / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
