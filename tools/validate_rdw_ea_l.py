#!/usr/bin/env python3
"""Exact regression for the guarded long-call ``rdw_ea`` wrapper.

The production wrapper at $00:E5B2 redirects to a bank-$9F fast path for the
dominant non-wrapping $F0 work-RAM case.  This harness executes that wrapper
and the retained generic ``rdw_ea`` implementation from identical Nexen
states.  It compares the returned value, native transient flags, X/Y, stack
balance, pointer/scratch state, and the complete relevant direct-page window.

The cases cover positive/zero/negative work-RAM words, the final non-wrapping
word, $F0:$FFFF rollover, ROM and ROM-bank rollover, C-Chip/DIP/sound I/O, and
an unmapped address.  This is an internal-helper equivalence regression, not
MAME gameplay or performance evidence; the real Stage-3 parents are separately
validated three-way against MAME.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NAT = Path("/tmp/b0_native.mss")
DEFAULT_SYMBOLS = ROOT / "src/interp.sym"
WRAPPER_ENTRY = 0x00E5B2
# A native BRA-to-self seam.  The older $00:E2CF diagnostic loop starts with
# LDA $0714, so Nexen's post-instruction hook timing obscures the helper's
# returned A/N/Z.  This seam leaves every returned register and flag intact.
RETURN_HOOK = 0x00D15A
FINAL_SP = 0x06E0
DP_FIRST = 0x0050
DP_LENGTH = 0x0060
FULL_WORK_SIZE = 0x10000


@dataclass(frozen=True)
class Case:
    name: str
    high: int
    low: int
    ps_seed: int = 0
    work_writes: tuple[tuple[int, bytes], ...] = ()


CASES = (
    Case("work-positive", 0x00F0, 0x1234, 0x00, ((0x1234, b"\x12\x34"),)),
    Case("work-zero", 0x00F0, 0x2000, 0xC1, ((0x2000, b"\x00\x00"),)),
    Case("work-negative", 0x00F0, 0x3000, 0x40, ((0x3000, b"\x80\x01"),)),
    Case("work-last-word", 0x00F0, 0xFFFE, 0x81, ((0xFFFE, b"\xAB\xCD"),)),
    Case("work-bank-rollover", 0x00F0, 0xFFFF, 0x40, ((0xFFFF, b"\x5A"),)),
    Case("rom-reset-vector", 0x0000, 0x3EF0, 0x81),
    Case("rom-bank-rollover", 0x0007, 0xFFFF, 0x40),
    Case("dip-space", 0x0050, 0x0000, 0x80),
    Case("cchip-status", 0x0090, 0x0803, 0x41),
    Case("sound-status", 0x0080, 0x0002, 0x00),
    Case("unmapped", 0x0008, 0x0000, 0xC1),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol(path: Path, name: str) -> int:
    pattern = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match and match.group(3) == name:
            return (int(match.group(1), 16) << 16) | int(match.group(2), 16)
    raise RuntimeError(f"missing symbol {name!r} in {path}")


def deterministic_work() -> bytearray:
    return bytearray(((offset * 37 + 0x5D) ^ (offset >> 8)) & 0xFF for offset in range(FULL_WORK_SIZE))


def write_bytes(
    session: base.McpSession, space: str, address: int, data: bytes
) -> None:
    session.write_memory(space, address, data.hex())


def set_cpu(
    session: base.McpSession,
    *,
    entry: int,
    sp: int,
    ps_seed: int,
) -> None:
    # Keep M/X clear and mask physical IRQs.  Preserve controlled incoming
    # N/V/Z/C; the generic helper defines its own outgoing N/Z/C and preserves
    # V, so all four are meaningful comparison inputs.
    ps = 0x04 | (ps_seed & 0xC3)
    session.tool(
        "set_cpu_state",
        {
            "cpuType": "Sa1",
            "pc": entry & 0xFFFF,
            "k": (entry >> 16) & 0xFF,
            "a": 0xA55A,
            "x": 0x1357,
            "y": 0x2468,
            "sp": sp,
            "d": 0,
            "dbr": 0,
            "ps": ps,
            "emulationMode": False,
        },
    )


def run_one(
    session: base.McpSession,
    nat: Path,
    case: Case,
    *,
    entry: int,
    long_return: bool,
    work: bytes,
) -> dict[str, object]:
    session.load_state(str(nat))
    session.pause()

    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        write_bytes(
            session,
            base.SNES_SPACE,
            0x400000 + offset,
            work[offset : offset + 0x4000],
        )

    # Seed the whole helper-visible scratch window so unintended omissions are
    # observable, then install the requested effective address.
    scratch = bytes((index * 29 + 7) & 0xFF for index in range(DP_LENGTH))
    write_bytes(session, base.DP_SPACE, DP_FIRST, scratch)
    session.write_u16(0x52, case.high, base.DP_SPACE)
    session.write_u16(0x54, case.low, base.DP_SPACE)
    session.write_u16(0x0714, 0, base.DP_SPACE)

    return_size = 3 if long_return else 2
    entry_sp = FINAL_SP - return_size
    return_value = (RETURN_HOOK - 1) & (0xFFFFFF if long_return else 0xFFFF)
    write_bytes(
        session,
        base.DP_SPACE,
        entry_sp + 1,
        return_value.to_bytes(return_size, "little"),
    )

    hook = session.add_exec_hook(RETURN_HOOK, cpu_type="Sa1")
    session.drain_notifications(timeout=0.02)
    set_cpu(
        session,
        entry=entry,
        sp=entry_sp,
        ps_seed=case.ps_seed,
    )
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=1, hook_handle=hook)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"{case.name}: ${entry:06X} did not return to "
                f"${RETURN_HOOK:06X}: {hit!r}"
            )
        cpu = session.get_cpu_state("Sa1")
        cycles = int(cpu["cycleCount"]) - start_cycles
        direct_page = bytes(
            session.read_memory(base.DP_SPACE, DP_FIRST, DP_LENGTH)
        )
    finally:
        session.remove_hook(hook)

    return {
        "a": int(cpu["a"]) & 0xFFFF,
        "x": int(cpu["x"]) & 0xFFFF,
        "y": int(cpu["y"]) & 0xFFFF,
        "sp": int(cpu["sp"]) & 0xFFFF,
        "ps": int(cpu["ps"]) & 0xFF,
        "d": int(cpu["d"]) & 0xFFFF,
        "dbr": int(cpu["dbr"]) & 0xFF,
        "pointer_high": session.read_u16(0x52, base.DP_SPACE),
        "pointer_low": session.read_u16(0x54, base.DP_SPACE),
        "scratch_90": session.read_u16(0x90, base.DP_SPACE),
        "direct_page_sha256": hashlib.sha256(direct_page).hexdigest(),
        "direct_page": direct_page.hex(),
        "cycles": cycles,
    }


def comparable(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key != "cycles"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9189)
    args = parser.parse_args()

    for label, path in (
        ("ROM", args.rom),
        ("native state", args.nat),
        ("symbols", args.symbols),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    generic_entry = symbol(args.symbols, "rdw_ea")
    wrapper_entry = symbol(args.symbols, "rdw_ea_l")
    if wrapper_entry != WRAPPER_ENTRY:
        raise RuntimeError(
            f"rdw_ea_l moved: expected ${WRAPPER_ENTRY:06X}, "
            f"got ${wrapper_entry:06X}"
        )
    rom = args.rom.read_bytes()
    wrapper_offset = wrapper_entry - 0x8000
    if rom[wrapper_offset : wrapper_offset + 4] != bytes.fromhex("5c00eb9f"):
        raise RuntimeError("production rdw_ea_l wrapper is not JML $9F:EB00")

    work = deterministic_work()
    records: list[dict[str, object]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = args.output.with_suffix(".nexen.stderr.log")
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as session:
        for case in CASES:
            case_work = bytearray(work)
            for offset, data in case.work_writes:
                case_work[offset : offset + len(data)] = data
            reference = run_one(
                session,
                args.nat,
                case,
                entry=generic_entry,
                long_return=False,
                work=bytes(case_work),
            )
            candidate = run_one(
                session,
                args.nat,
                case,
                entry=wrapper_entry,
                long_return=True,
                work=bytes(case_work),
            )
            keys = sorted(
                key
                for key in comparable(reference)
                if reference[key] != candidate[key]
            )
            record = {
                "event": "case",
                "name": case.name,
                "address": f"{case.high:04X}:{case.low:04X}",
                "ps_seed": case.ps_seed,
                "reference": {
                    key: value
                    for key, value in reference.items()
                    if key != "direct_page"
                },
                "candidate": {
                    key: value
                    for key, value in candidate.items()
                    if key != "direct_page"
                },
                "mismatch_keys": keys,
                "result": "green" if not keys else "red",
            }
            records.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)

    green = sum(record["result"] == "green" for record in records)
    summary = {
        "event": "summary",
        "result": "green" if green == len(records) else "red",
        "green": green,
        "red": len(records) - green,
        "total": len(records),
        "scope": (
            "same-state Nexen equivalence of production rdw_ea_l redirect "
            "against retained generic rdw_ea; internal helper, not MAME or fps"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "wrapper_entry": f"{wrapper_entry:06X}",
        "generic_entry": f"{generic_entry:06X}",
        "time": time.time(),
    }
    with args.output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
