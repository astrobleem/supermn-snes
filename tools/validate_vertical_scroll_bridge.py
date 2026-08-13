#!/usr/bin/env python3
"""Exercise the SNES vertical-scroll bridge on Nexen's real 65816/PPU core.

This is an isolated Mesen/Nexen machine-code lab.  It redirects the paused
5A22 to the production helpers, supplies synthetic X1-001 scroll-shadow bytes,
and checks the packed snapshot result, legacy PPU BG1 scroll registers, and the
Mode-2 per-column offset table.  It is not gameplay, cold-boot, stability, or
performance evidence.
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
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_EMULATOR = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "linux-x64/publish/Nexen"
)
DEFAULT_SYMBOLS = ROOT / "src" / "video.sym"

sys.path.insert(0, str(MESEN_PY))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument("--port", type=int, default=8846)
    parser.add_argument("--boot-wait", type=float, default=6.0)
    parser.add_argument(
        "--output",
        type=Path,
        help="also retain the JSON report at this path",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_address(path: Path, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == name:
            bank, offset = fields[0].split(":")
            if int(bank, 16) != 0:
                raise RuntimeError(f"unexpected video symbol bank for {name}: {fields[0]}")
            return 0xE90000 | int(offset, 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def configure_runtime() -> None:
    dotnet10 = "/home/chad/.dotnet10"
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet10
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet10, dotnet8, *current])


def set_cpu(m: McpSession, cpu_type: str, **updates: Any) -> None:
    state = dict(m.get_cpu_state(cpu_type))
    state.update(updates)
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
    m.tool(
        "set_cpu_state",
        {key: state[key] for key in allowed if key in state},
    )


def park_sa1(m: McpSession) -> None:
    m.write_memory("Sa1Memory", 0x0600, "80fe")
    m.write_memory("snesMemory", 0x2201, "00")
    state = m.get_cpu_state("Sa1")
    set_cpu(
        m,
        "Sa1",
        pc=0x0600,
        k=0,
        d=0,
        dbr=0,
        ps=int(state["ps"]) | 0x04,
        emulationMode=False,
    )


def run_helper(
    m: McpSession,
    entry: int,
    return_spin: int,
    *,
    a: int = 0x5A3C,
    x: int = 0x1234,
    y: int = 0x5678,
) -> dict[str, Any]:
    previous = m.get_cpu_state("Snes")
    ps = (int(previous["ps"]) & ~0x30) | 0x04
    return_minus_one = (return_spin - 1) & 0xFFFF
    m.write_memory(
        "snesMemory",
        0x001FEF,
        return_minus_one.to_bytes(2, "little").hex(),
    )
    set_cpu(
        m,
        "Snes",
        pc=entry & 0xFFFF,
        k=(entry >> 16) & 0xFF,
        a=a,
        x=x,
        y=y,
        # Model the two bytes a real JSR would have pushed. The helper's
        # terminal RTS consumes them and returns the logical caller SP to
        # $1FF0 at the runtime-only spin.
        sp=0x1FEE,
        d=0,
        dbr=0,
        ps=ps,
        emulationMode=False,
    )
    hook = m.add_exec_hook(return_spin, cpu_type="Snes")
    m.drain_notifications(timeout=0.05)
    try:
        # The Mode-2 helper can publish a DMA descriptor and wait for the NMI
        # service path.  Allow the handler to return before judging the parked
        # caller PC; short helpers still stop immediately on the same hook.
        for _attempt in range(3):
            result = m.run_until(max_frames=3, hook_handle=hook)
            m.pause()
            state = dict(m.get_cpu_state("Snes"))
            pc = ((int(state["k"]) & 0xFF) << 16) | (
                int(state["pc"]) & 0xFFFF
            )
            if pc == return_spin or (result or {}).get("reason") != "hookFired":
                break
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)
    pc = ((int(state["k"]) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)
    # A helper that waits for one real DMA window can reach the installed
    # return spin on the same boundary where run_until reports maxFrames.  An
    # interrupt can also begin after the exec hook but before the state query;
    # resume through it and require the stable spin rather than sampling the
    # interrupt's temporary registers as a false helper failure.
    if pc != return_spin:
        trace = m.trace_log(count=48, cpu_type="Snes")
        raise RuntimeError(
            f"helper did not return to ${return_spin:06X}: result={result!r}, "
            f"pc=${pc:06X}, trace={trace!r}"
        )
    return state


def run_rtl_helper(
    m: McpSession,
    entry: int,
    return_spin: int,
    *,
    a: int = 0x5A3C,
    m8: bool = False,
) -> dict[str, Any]:
    previous = m.get_cpu_state("Snes")
    ps = (int(previous["ps"]) & ~0x30) | 0x04
    if m8:
        ps |= 0x20
    return_minus_one = (return_spin - 1) & 0xFFFF
    m.write_memory(
        "snesMemory",
        0x001FED,
        return_minus_one.to_bytes(2, "little").hex()
        + f"{(return_spin >> 16) & 0xFF:02x}",
    )
    set_cpu(
        m,
        "Snes",
        pc=entry & 0xFFFF,
        k=(entry >> 16) & 0xFF,
        a=a,
        x=0x1234,
        y=0x5678,
        sp=0x1FEC,
        d=0,
        dbr=0,
        ps=ps,
        emulationMode=False,
    )
    hook = m.add_exec_hook(return_spin, cpu_type="Snes")
    m.drain_notifications(timeout=0.05)
    try:
        for _attempt in range(3):
            result = m.run_until(max_frames=3, hook_handle=hook)
            m.pause()
            state = dict(m.get_cpu_state("Snes"))
            pc = ((int(state["k"]) & 0xFF) << 16) | (
                int(state["pc"]) & 0xFFFF
            )
            if pc == return_spin or (result or {}).get("reason") != "hookFired":
                break
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)
    pc = ((int(state["k"]) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)
    if pc != return_spin:
        raise RuntimeError(
            f"RTL helper did not return to ${return_spin:06X}: "
            f"result={result!r}, state={state!r}"
        )
    return state


def rom_file_offset(cpu_address: int) -> int:
    bank = (cpu_address >> 16) & 0xFF
    if bank < 0xC0:
        raise RuntimeError(f"expected HiROM bank for helper: ${cpu_address:06X}")
    return ((bank & 0x3F) << 16) | (cpu_address & 0xFFFF)


def write_scroll_shadow(
    m: McpSession,
    *,
    scrollx: int,
    sampled: dict[int, int],
) -> None:
    m.write_memory("snesMemory", 0x413489, f"{scrollx & 0xFF:02x}")
    for column in (2, 4, 6, 8, 9):
        value = sampled.get(column, sampled[4])
        m.write_memory(
            "snesMemory",
            0x413401 + column * 0x20,
            f"{value & 0xFF:02x}",
        )


def main() -> int:
    args = parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("emulator", args.emulator),
        ("symbols", args.symbols),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise RuntimeError("expected a 4 MiB production ROM")
    if int.from_bytes(rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise RuntimeError("refusing non-production ROM: TESTFLAG is set")

    capture = symbol_address(args.symbols, "capture_bg_vscroll")
    capture_end = symbol_address(args.symbols, "capture_bg_vscroll_end")
    apply_scroll = symbol_address(args.symbols, "bg_scroll")
    apply_end = symbol_address(args.symbols, "bg_scroll_end")
    apply_opt = symbol_address(args.symbols, "bg_scroll_with_opt")
    apply_opt_end = symbol_address(args.symbols, "bg_scroll_with_opt_end")
    map_commit = symbol_address(args.symbols, "bg_scroll_map_commit")
    map_prepare = symbol_address(args.symbols, "bg_scroll_map_prepare")
    phase_publish = symbol_address(args.symbols, "bg_scroll_phase_publish")
    return_spin = capture_end + 1
    configure_runtime()

    rows: list[dict[str, Any]] = []
    stderr_log = ROOT / "build" / "vertical-scroll-bridge-nexen.stderr.log"
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=args.boot_wait,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.write_memory("snesMemory", 0x4200, "00")
        m.read_memory("snesMemory", 0x4210, 1)
        park_sa1(m)
        # Execute each real PLP+RTS into one runtime-only BRA -2 in the zero
        # seam after capture_bg_vscroll. This keeps the returned state stable
        # despite asynchronous hook delivery without modifying helper code.
        spin_offset = rom_file_offset(return_spin)
        if bytes(m.read_memory("snesPrgRom", spin_offset, 2)) != b"\x00\x00":
            raise RuntimeError("vertical-scroll lab return seam is no longer zero")
        m.write_memory("snesPrgRom", spin_offset, "80fe")
        observed = bytes(m.read_memory("snesPrgRom", spin_offset, 2))
        if observed != bytes.fromhex("80fe"):
            raise RuntimeError(f"failed to install helper spin at file ${spin_offset:06X}")

        cases = (
            ("stage1-wrap", 0x23, {4: 0xF9}, 0x2300),
            ("stage2-motion", 0x7A, {4: 0x40}, 0x7A47),
            ("byte-wrap", 0x55, {4: 0xFF}, 0x5506),
            (
                "stage2-per-column-center",
                0x31,
                {2: 0xF2, 4: 0xEB, 6: 0xEB, 8: 0xEB, 9: 0xEB},
                0x31F2,
            ),
            (
                "stage2-per-column-next",
                0x31,
                {2: 0x7A, 4: 0xFB, 6: 0xFB, 8: 0xFB, 9: 0xFB},
                0x3102,
            ),
        )
        for name, scrollx, sampled, expected in cases:
            write_scroll_shadow(m, scrollx=scrollx, sampled=sampled)
            state = run_helper(m, capture, return_spin)
            observed = int(state["a"]) & 0xFFFF
            preserved = {
                "x": int(state["x"]) & 0xFFFF,
                "y": int(state["y"]) & 0xFFFF,
                "sp": int(state["sp"]) & 0xFFFF,
            }
            passed = observed == expected and preserved == {
                "x": 0x1234,
                "y": 0x5678,
                "sp": 0x1FF0,
            }
            rows.append(
                {
                    "kind": "capture",
                    "name": name,
                    "expected": expected,
                    "observed": observed,
                    "preserved": preserved,
                    "pass": passed,
                }
            )

        apply_cases = (
            ("gameplay", 0x7A47, 0x00, 0x47),
            ("stage2-wrap", 0x31F2, 0x00, 0xF2),
            ("title-guard", 0x7A47, 0x80, 0x00),
        )
        for name, packed, title_high, expected_vscroll in apply_cases:
            m.write_memory("snesWorkRam", 0x72B3, "00")
            m.write_memory("snesWorkRam", 0x8994, packed.to_bytes(2, "little").hex())
            # These are the legacy/irregular-layout register cases.  Exact
            # layouts intentionally keep only the common sub-32 X phase.
            m.write_memory("snesWorkRam", 0x8996, "feff")
            m.write_memory("snesWorkRam", 0x89BF, f"{title_high:02x}")
            run_helper(m, apply_scroll, return_spin)
            layer = m.get_ppu_state()["layers"][0]
            observed_vscroll = int(layer["vscroll"])
            expected_hscroll = (0x40 - ((packed >> 8) & 0xFF)) & 0x3FF
            observed_hscroll = int(layer["hscroll"])
            rows.append(
                {
                    "kind": "apply",
                    "name": name,
                    "expected_vscroll": expected_vscroll,
                    "observed_vscroll": observed_vscroll,
                    "expected_hscroll": expected_hscroll,
                    "observed_hscroll": observed_hscroll,
                    "pass": (
                        observed_vscroll == expected_vscroll
                        and observed_hscroll == expected_hscroll
                    ),
                }
            )

        # Paced gameplay publishes the newest coherent horizontal source byte
        # independently of the slower immutable render candidate.  Prove the
        # valid marker selects it while the accepted-cache vertical byte and
        # legacy-layout arithmetic remain unchanged.
        m.write_memory("snesWorkRam", 0x8994, "477a")
        m.write_memory("snesWorkRam", 0x8996, "feff")
        m.write_memory("snesWorkRam", 0x89BF, "00")
        m.write_memory("snesWorkRam", 0x72B2, "55a555")
        run_helper(m, apply_scroll, return_spin)
        layer = m.get_ppu_state()["layers"][0]
        rows.append(
            {
                "kind": "apply-latest-scroll",
                "name": "paced-latest-over-accepted-cache",
                "accepted_scrollx": 0x7A,
                "latest_scrollx": 0x55,
                "expected_hscroll": (0x40 - 0x55) & 0x3FF,
                "observed_hscroll": int(layer["hscroll"]),
                "expected_vscroll": 0x47,
                "observed_vscroll": int(layer["vscroll"]),
                "pass": (
                    int(layer["hscroll"]) == ((0x40 - 0x55) & 0x3FF)
                    and int(layer["vscroll"]) == 0x47
                ),
            }
        )

        # The sparse title composition and the first full gameplay map are not
        # rotations of one another.  Their strongest delta has only 3/16
        # support, so seed the new source-column-4 slot in the already
        # unwrapped phase domain instead of accepting a false 128-pixel shift.
        displayed_map = bytes([4, 5, 6, 0, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        applied_map = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 0, 0])
        m.write_memory("snesWorkRam", 0x72F0, displayed_map.hex())
        m.write_memory("snesWorkRam", 0x89F0, applied_map.hex())
        m.write_memory("snesWorkRam", 0x8996, "003f")
        m.write_memory("snesWorkRam", 0x72B2, "00a500400000a500800000")
        run_rtl_helper(m, map_prepare, return_spin, m8=True)
        prepared = bytes(m.read_memory("snesWorkRam", 0x72B9, 4))
        run_rtl_helper(m, map_commit, return_spin, m8=True)
        committed = bytes(m.read_memory("snesWorkRam", 0x72B5, 8))
        copied_map = bytes(m.read_memory("snesWorkRam", 0x72F0, 16))
        rows.append(
            {
                "kind": "map-commit",
                "name": "sparse-title-to-gameplay-seeds-phase-domain",
                "raw_center": 0x80,
                "latest_unwrapped_phase": 0,
                "source_column4_physical_basis": 0x80,
                "expected_basis": 0,
                "observed_basis": committed[2],
                "expected_hscroll": 0x040,
                "observed_hscroll": int.from_bytes(committed[0:2], "little"),
                "prepared_pending_basis": prepared.hex(),
                "displayed_map_copied": copied_map == applied_map,
                "pass": (
                    prepared == bytes((0xA5, 0x80, 0x00, 0xA5))
                    and committed[2] == 0
                    and int.from_bytes(committed[0:2], "little") == 0x040
                    and committed[4] == 0
                    and committed[7] == 0
                    and copied_map == applied_map
                ),
            }
        )

        # One source column can cross the two-slot gap without rotating the
        # other populated columns.  The modal delta is zero, so the displayed
        # basis and integrated fallback must remain unchanged.
        displayed_map = bytes(
            [8, 9, 10, 11, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 0, 0]
        )
        applied_map = bytes(
            [8, 9, 10, 11, 12, 15, 0, 1, 2, 3, 4, 5, 6, 7, 0, 0]
        )
        m.write_memory("snesWorkRam", 0x72F0, displayed_map.hex())
        m.write_memory("snesWorkRam", 0x89F0, applied_map.hex())
        m.write_memory("snesWorkRam", 0x8996, "3f00")
        m.write_memory("snesWorkRam", 0x72B3, "a5")
        m.write_memory("snesWorkRam", 0x72B5, "5b00")
        m.write_memory("snesWorkRam", 0x72B7, "c0a500000000")
        run_rtl_helper(m, map_prepare, return_spin, m8=True)
        prepared = bytes(m.read_memory("snesWorkRam", 0x72B9, 4))
        run_rtl_helper(m, map_commit, return_spin, m8=True)
        committed = bytes(m.read_memory("snesWorkRam", 0x72B5, 8))
        copied_map = bytes(m.read_memory("snesWorkRam", 0x72F0, 16))
        rows.append(
            {
                "kind": "map-commit",
                "name": "isolated-column4-does-not-rebase-whole-map",
                "old_basis": 0xC0,
                "expected_basis": 0xC0,
                "observed_basis": committed[2],
                "old_integrated_hscroll": 0x05B,
                "expected_integrated_hscroll": 0x05B,
                "observed_integrated_hscroll": int.from_bytes(
                    committed[0:2], "little"
                ),
                "prepared_pending_basis": prepared.hex(),
                "expected_pending": 0,
                "observed_pending": committed[4],
                "displayed_map_copied": copied_map == applied_map,
                "pass": (
                    prepared == bytes((0xA5, 0x00, 0xC0, 0xA5))
                    and committed[2] == 0xC0
                    and int.from_bytes(committed[0:2], "little") == 0x05B
                    and committed[4] == 0
                    and committed[7] == 0
                    and copied_map == applied_map
                ),
            }
        )

        # When thirteen populated columns rotate left by one physical slot,
        # the same modal policy must commit exactly -32 pixels even though one
        # detached column reports -96 and the two empty columns report zero.
        displayed_map = bytes(
            [14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 0]
        )
        applied_map = bytes(
            [11, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0, 0]
        )
        m.write_memory("snesWorkRam", 0x72F0, displayed_map.hex())
        m.write_memory("snesWorkRam", 0x89F0, applied_map.hex())
        m.write_memory("snesWorkRam", 0x8996, "3f00")
        m.write_memory("snesWorkRam", 0x72B3, "a5")
        m.write_memory("snesWorkRam", 0x72B5, "5b00")
        m.write_memory("snesWorkRam", 0x72B7, "c0a500000000")
        run_rtl_helper(m, map_prepare, return_spin, m8=True)
        prepared = bytes(m.read_memory("snesWorkRam", 0x72B9, 4))
        run_rtl_helper(m, map_commit, return_spin, m8=True)
        committed = bytes(m.read_memory("snesWorkRam", 0x72B5, 8))
        copied_map = bytes(m.read_memory("snesWorkRam", 0x72F0, 16))
        rows.append(
            {
                "kind": "map-commit",
                "name": "modal-populated-rotation-commits-one-slot",
                "old_basis": 0xC0,
                "expected_basis": 0xA0,
                "observed_basis": committed[2],
                "old_integrated_hscroll": 0x05B,
                "expected_integrated_hscroll": 0x03B,
                "observed_integrated_hscroll": int.from_bytes(
                    committed[0:2], "little"
                ),
                "prepared_pending_basis": prepared.hex(),
                "displayed_map_copied": copied_map == applied_map,
                "pass": (
                    prepared == bytes((0xA5, 0x00, 0xA0, 0xA5))
                    and committed[2] == 0xA0
                    and int.from_bytes(committed[0:2], "little") == 0x03B
                    and committed[4] == 0
                    and committed[7] == 0
                    and copied_map == applied_map
                ),
            }
        )

        # A fixed source column's raw byte can jump -67 at the X1 gap while
        # the common phase moved -3.  The live publisher must retain -3 only.
        m.write_memory("snesWorkRam", 0x72B2, "c3a5c3000000000000")
        run_rtl_helper(m, phase_publish, return_spin, a=0x0080, m8=True)
        phase_state = bytes(m.read_memory("snesWorkRam", 0x72B2, 9))
        rows.append(
            {
                "kind": "phase-publish",
                "name": "fixed-column-gap-jump-unwraps-to-minus-three",
                "raw_previous": 0xC3,
                "raw_current": 0x80,
                "expected_latest": 0xC0,
                "observed_latest": phase_state[0],
                "expected_raw_retained": 0x80,
                "observed_raw_retained": phase_state[8],
                "pass": phase_state[0] == 0xC0 and phase_state[8] == 0x80,
            }
        )

        # Exact maps derive H from the map actually displayed and the current
        # presented camera.  Poison the old integrated coordinate to prove it
        # cannot expose the map's deliberately unused physical columns.
        m.write_memory("snesWorkRam", 0x8994, "477a")
        m.write_memory("snesWorkRam", 0x8996, "003f")
        m.write_memory("snesWorkRam", 0x72B2, "55a555")
        m.write_memory("snesWorkRam", 0x72B7, "60a5")
        poisoned_integrated_hscroll = 0x0CB
        m.write_memory(
            "snesWorkRam",
            0x72B5,
            poisoned_integrated_hscroll.to_bytes(2, "little").hex(),
        )
        run_helper(m, apply_scroll, return_spin)
        layer = m.get_ppu_state()["layers"][0]
        expected_hscroll = (0x40 + 0x60 - 0x55) & 0x3FF
        rows.append(
            {
                "kind": "apply-displayed-map-scroll",
                "name": "exact-map-ignores-poisoned-integrated-coordinate",
                "displayed_map_scrollx": 0x60,
                "presented_scrollx": 0x55,
                "poisoned_integrated_hscroll": poisoned_integrated_hscroll,
                "expected_hscroll": expected_hscroll,
                "observed_hscroll": int(layer["hscroll"]),
                "pass": int(layer["hscroll"]) == expected_hscroll,
            }
        )

        # Reproduce the supplied attract-state layout: source columns 0..13
        # are populated, 14/15 are empty overlaps of physical slots 4/7, and
        # the four visible source groups carry distinct vertical phases.  The
        # empty overlaps must not replace populated slots' Y values.
        source_y = bytes(
            [
                0xF2, 0xF2, 0xF2, 0xF2,
                0x9F, 0x9F, 0x9F, 0x9F,
                0x45, 0x45, 0x45, 0x45,
                0xF9, 0xF9, 0xF2, 0x45,
            ]
        )
        physical_map = bytes(
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 4, 7]
        )
        raw_codes = bytearray(0x400)
        for column in range(14):
            raw_codes[column * 0x40:column * 0x40 + 2] = b"\x01\x00"
        m.write_memory("snesWorkRam", 0x2000, raw_codes.hex())
        m.write_memory("snesWorkRam", 0x72C0, source_y.hex())
        m.write_memory("snesWorkRam", 0x72B2, "00a5004000")
        m.write_memory("snesWorkRam", 0x72B7, "00a5")
        m.write_memory("snesWorkRam", 0x89E0, physical_map.hex())
        m.write_memory("snesWorkRam", 0x8994, "aa00003f")
        m.write_memory("snesWorkRam", 0x89BE, "0000")
        run_helper(m, apply_opt, return_spin)

        expected_physical_y = bytes(
            [
                0xF2, 0xF2, 0xF2, 0xF2,
                0x9F, 0x9F, 0x9F, 0x9F,
                0x45, 0x45, 0x45, 0x45,
                0xF9, 0xF9, 0x9F, 0x9F,
            ]
        )
        hscroll = 0x40
        expected_table = bytearray(0x80)
        for index in range(32):
            pixel = (index * 8 - 24 + hscroll) & 0x1FF
            slot = (pixel >> 5) & 0x0F
            word = 0x2000 | ((expected_physical_y[slot] + 7) & 0xFF)
            expected_table[0x40 + index * 2:0x42 + index * 2] = (
                word.to_bytes(2, "little")
            )
        observed_physical_y = bytes(
            m.read_memory("snesWorkRam", 0x72A0, 0x10)
        )
        observed_opt_control = bytes(
            m.read_memory("snesWorkRam", 0x72B0, 2)
        )
        observed_table = bytes(
            m.read_memory("snesWorkRam", 0x7300, 0x80)
        )
        observed_vram = bytes(
            m.read_memory("snesVideoRam", 0xF000, 0x80)
        )
        ppu = m.get_ppu_state()
        layer = ppu["layers"][0]
        opt_pass = (
            int(ppu.get("bgMode", -1)) == 2
            and int(layer["hscroll"]) == hscroll
            and int(layer["vscroll"]) == 0xF9
            and observed_physical_y == expected_physical_y
            and observed_opt_control == bytes((0xF9, 0x01))
            and observed_table == expected_table
            and observed_vram == expected_table
        )
        rows.append(
            {
                "kind": "mode2-offset-table",
                "name": "attract-populated-overlap",
                "expected_mode": 2,
                "observed_mode": int(ppu.get("bgMode", -1)),
                "expected_hscroll": hscroll,
                "observed_hscroll": int(layer["hscroll"]),
                "expected_vscroll": 0xF9,
                "observed_vscroll": int(layer["vscroll"]),
                "expected_physical_y": expected_physical_y.hex(),
                "observed_physical_y": observed_physical_y.hex(),
                "expected_opt_control": "f901",
                "observed_opt_control": observed_opt_control.hex(),
                "wram_table_sha256": hashlib.sha256(observed_table).hexdigest(),
                "vram_table_sha256": hashlib.sha256(observed_vram).hexdigest(),
                "expected_table_sha256": hashlib.sha256(expected_table).hexdigest(),
                "pass": opt_pass,
            }
        )

        # An exact-looking column map must still respect the explicit title
        # composition bit: Mode-2 offsets would override the zero VOFS guard.
        m.write_memory("snesWorkRam", 0x8996, "003f")
        m.write_memory("snesWorkRam", 0x89BE, "0080")
        run_helper(m, apply_opt, return_spin)
        ppu = m.get_ppu_state()
        layer = ppu["layers"][0]
        observed_opt_control = bytes(
            m.read_memory("snesWorkRam", 0x72B0, 2)
        )
        rows.append(
            {
                "kind": "mode2-title-fallback",
                "name": "exact-map-title-guard",
                "expected_mode": 1,
                "observed_mode": int(ppu.get("bgMode", -1)),
                "expected_vscroll": 0,
                "observed_vscroll": int(layer["vscroll"]),
                "expected_opt_enabled": 0,
                "observed_opt_enabled": observed_opt_control[1],
                "pass": (
                    int(ppu.get("bgMode", -1)) == 1
                    and int(layer["vscroll"]) == 0
                    and observed_opt_control[1] == 0
                ),
            }
        )

    report = {
        "scope": (
            "isolated real-65816/PPU vertical-scroll bridge lab; synthetic "
            "X1-001 shadow; not gameplay, cold boot, stability, or performance"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator.resolve()),
        "symbols": str(args.symbols.resolve()),
        "symbols_sha256": sha256(args.symbols.resolve()),
        "helpers": {
            "capture": f"{capture:06X}",
            "capture_end": f"{capture_end:06X}",
            "apply": f"{apply_scroll:06X}",
            "apply_end": f"{apply_end:06X}",
            "apply_opt": f"{apply_opt:06X}",
            "apply_opt_end": f"{apply_opt_end:06X}",
            "map_prepare": f"{map_prepare:06X}",
            "map_commit": f"{map_commit:06X}",
            "phase_publish": f"{phase_publish:06X}",
            "return_spin": f"{return_spin:06X}",
        },
        "rows": rows,
        "passed": sum(1 for row in rows if row["pass"]),
        "total": len(rows),
    }
    report_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_text, encoding="utf-8")
    print(report_text, end="")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
