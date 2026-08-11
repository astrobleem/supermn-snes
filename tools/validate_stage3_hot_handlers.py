#!/usr/bin/env python3
"""Three-way differential for the Stage-3 table-dispatched hot handlers.

Each retained fixture is an exact architectural entry state captured by
``PC_RING=1`` in Mesen 2.1.1 before the original handler executes.  This tool
injects that same state into:

* MAME 0.287 running the original 68000 routine;
* Nexen with the production native gate disabled;
* Nexen with the production native gate enabled.

The comparison includes every D/A register, CCR including X, the real stacked
return and all other bytes of mapped 16 KiB work RAM.  Nexen additionally
checks that the upper 48 KiB backing allocation is untouched, that the
interpreter/native AC charge agrees, and that the ordinary table-dispatch route
reaches each native entry.  No stack bytes are masked.  The Stage-3 player
leaves are BSR-dispatched, so their real-route differential lives in
``validate_stage3_player_bsr.py`` rather than this direct-table harness.

This is bounded function-local semantic and local-cycle evidence, not fps or a
fresh-boot playthrough result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import validate_1f2e4_native as live
import validate_render_helpers as base
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-perf-diagnostic-v1/target-fixtures"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = base.DEFAULT_NEXEN
DEFAULT_NAT = base.DEFAULT_NAT
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
OJMP_HOOK = 0x00D1B3
INEXT = 0x00D128
OP_ILLEGAL = 0x00CDED
CCR_MASK = 0x1F
AC_START = 0x7000


def esc6_native(symbol: str) -> int:
    """Resolve a movable bank-$95 entry from the assembled symbol file."""

    path = ROOT / "src/escbank6.sym"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return 0x950000 | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing assembled bank-$95 symbol: {symbol}")


NATIVE_ENTRIES = {
    0x013282: 0x9FE000,
    0x013314: 0x9FD800,
    0x01337E: 0x9FBA00,
    0x0133EA: 0x9FEC00,
    0x013468: 0x9FF100,
    0x013538: 0x9FF700,
    0x0278E8: 0x9FD000,
    0x027912: 0x9FA500,
    0x027952: 0x94B600,
    0x0279D2: 0x94BC00,
    0x027AEA: 0x9FC000,
    0x027B44: 0x94CB40,
    0x027B7C: 0x94CEC0,
    0x02E49C: 0x94D340,
    0x0296C6: 0x94D480,
    0x02E40E: 0x94D540,
    0x0135E0: 0x94DB20,
    0x02F3BA: 0x94C200,
    0x02F2E0: 0x9FA680,
    0x02F56A: 0x94CD00,
    0x02F5A2: 0x94D100,
    0x02E4B8: 0x9DDC00,
    0x02E524: 0x9DE190,
    0x02E42C: 0x9FA140,
    0x02E676: 0x9FE400,
    0x02F542: 0x9FFE00,
    # Work-RAM code reached through the guarded $002D8A gateway.  Its body is
    # deliberately movable inside bank $95, so consume the assembled symbol
    # instead of baking another stale hook address into the validator.
    0xF01B20: esc6_native("entry_f01b20t"),
}
BSR_PLAYER_TARGETS = frozenset(
    {
        0x013282,
        0x013314,
        0x01337E,
        0x0133EA,
        0x013468,
        0x013538,
    }
)


def bsr_player_targets(targets: object) -> list[int]:
    """Return logical targets that require the BSR-route validator.

    Keeping this small classification separate makes the generic harness's
    refusal directly regression-testable; a direct OJMP fixture would execute
    the interpreter fallback and falsely label the result native-on.
    """

    return sorted({int(target) for target in targets} & BSR_PLAYER_TARGETS)
PRODUCTION_ROUTE_TARGETS = {
    # logical target, native destination, dispatcher seam, gate-off seam
    0xF01B20: (
        0x002D8A,
        esc6_native("entry_2d8at"),
        0x94F980,
        0x008102,
    ),
}
EXPECTED_RETURNS = {
    0x013282: {0x0126EE},
    0x013314: {0x012702},
    0x01337E: {0x01337C},
    # The player collision reducer is reached both from the regular player
    # update spine and from the organic $012914 collision-response callsite.
    # The latter is the tick-14866 campaign boundary-phase fixture.
    0x0133EA: {0x0126E0, 0x012918},
    0x013468: {0x0126DC},
    0x013538: {0x01272E},
    0x0278E8: {0x02E44C},
    0x027912: {0x0278F2, 0x0278FC},
    0x027952: {0x0278F2, 0x0278FC},
    0x0279D2: {0x0278F2, 0x0278FC},
    0x027AEA: {0x027956},
    0x027B44: {0x027950, 0x0279CC},
    0x027B7C: {0x0279D0},
    0x02E49C: {0x02E4BA, 0x02E4FA, 0x02E528},
    0x0296C6: {0x027B8E, 0x02F5B4},
    0x02E40E: {0x02E3E6, 0x02E44A},
    0x0135E0: {0x0135AC, 0x0135D4},
    0x02F3BA: {0x02E44C},
    0x02F2E0: {0x02E44C},
    0x02F56A: {0x02F490},
    0x02F5A2: {0x02F494},
    0x02E4B8: {0x02F48C},
    0x02E524: {0x0279C8, 0x027A60},
    0x02E42C: {0x0278E6, 0x02F2DE},
    0x02E676: {0x02F3BE},
    0x02F542: {0x02F478, 0x02F50A},
    # Organic tick 14866 reaches both the player-death sound call and a
    # second gameplay task through the copied C-Chip queue routine.
    0xF01B20: {0x012974, 0x0296DA},
}


@dataclass(frozen=True)
class Fixture:
    name: str
    target: int
    return_pc: int
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    state: int
    substate: int
    metadata_path: Path
    pre_entry_state: Path
    prestate_kind: str


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    usp: int
    ac: int | None
    cycles: int | None
    halt: int
    observed_pc: int
    entry_hits: int | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_hex(value: str | int) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def load_fixtures(
    directory: Path,
    targets: set[int] | None,
    max_cases: int | None,
) -> list[Fixture]:
    fixtures: list[Fixture] = []
    for metadata_path in sorted(directory.glob("*/entry.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = parse_hex(metadata["target"])
        if target not in NATIVE_ENTRIES:
            continue
        if targets is not None and target not in targets:
            continue
        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"{work_path} is {len(work)} bytes; expected {FULL_WORK_SIZE}"
            )
        if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
            raise RuntimeError(f"fixture work hash mismatch: {work_path}")
        return_pc = parse_hex(metadata["return_pc"])
        if return_pc not in EXPECTED_RETURNS[target]:
            raise RuntimeError(
                f"{metadata_path} has unexpected return ${return_pc:06X}"
            )
        regs = {
            name: int(metadata["regs"][name]) & 0xFFFFFFFF
            for name in base.REG_NAMES
        }
        sp = regs["A7"] & 0xFFFFFF
        if (sp >> 16) != 0xF0 or (sp & 0xFFFF) > MAPPED_WORK_SIZE - 4:
            raise RuntimeError(f"{metadata_path} has invalid SP ${sp:06X}")
        stacked = int.from_bytes(
            work[sp & 0xFFFF : (sp & 0xFFFF) + 4], "big"
        ) & 0xFFFFFF
        if stacked != return_pc:
            raise RuntimeError(
                f"{metadata_path} stack return ${stacked:06X} != "
                f"metadata ${return_pc:06X}"
            )
        prestate_key = (
            "pre_entry_state"
            if "pre_entry_state" in metadata
            else "pre_failure_state"
        )
        pre_entry = Path(metadata[prestate_key])
        if not pre_entry.is_file():
            raise RuntimeError(f"missing retained fixture state: {pre_entry}")
        fixtures.append(
            Fixture(
                name=metadata_path.parent.name,
                target=target,
                return_pc=return_pc,
                regs=regs,
                sr=int(metadata["sr"]) & 0xFFFF,
                work=work,
                tick=int(metadata["tick"]),
                frame=int(metadata["frame"]),
                state=int(metadata["state"]),
                substate=int(metadata["substate"]),
                metadata_path=metadata_path,
                pre_entry_state=pre_entry,
                prestate_kind=prestate_key,
            )
        )
    if max_cases is not None:
        fixtures = fixtures[:max_cases]
    if not fixtures:
        raise RuntimeError(f"no matching fixtures found in {directory}")
    return fixtures


def mame_result(
    session: base.MameSession,
    fixture: Fixture,
    *,
    return_sp_delta: int = 4,
) -> Result:
    session.pause()
    # MAME's capture_at_pc primitive is an opcode-prefetch tap.  Sampling the
    # stacked return once can therefore see the preceding RTS before its A7
    # update retires.  Replace only that fetched return word with a
    # validation-only BRA-to-self and capture the second qualified fetch.  The
    # branch changes no D/A/CCR/work state; by its second fetch the RTS and A7
    # update are necessarily committed.  Direct target-entry fixtures already
    # have the callee return stacked, so their post-RTS SP is entry+4.  A
    # pre-BSR fixture pushes and pops that return within the bounded span and
    # therefore passes return_sp_delta=0.
    session.exec_lua(
        "if MCP_STAGE3_RETURN_NOP then "
        "MCP_STAGE3_RETURN_NOP:remove() end "
        "MCP_STAGE3_RETURN_NOP = "
        "machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{fixture.return_pc:06X}, "
        f"0x{fixture.return_pc + 1:06X}, 'mcp_stage3_return_spin', "
        "function(offset, data, mask) return 0x60FE end); return true"
    )
    session.write_block(0xF00000, fixture.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, fixture.regs[name])
    entry_sp = fixture.regs["A7"] & 0xFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    # Isolate the bounded call from VBLANK.  The handler does not change the
    # interrupt mask; its architectural input mask is retained in the result.
    session.set_reg("SR", fixture.sr | 0x0700)
    session.set_reg("PC", fixture.target)
    captured = session.cmd(
        "capture_at_pc",
        pc=fixture.return_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=2,
        exp_sp=(entry_sp + return_sp_delta) & 0xFFFFFF,
        maxFrames=180,
        timeout=180,
    )
    session.exec_lua(
        "if MCP_STAGE3_RETURN_NOP then "
        "MCP_STAGE3_RETURN_NOP:remove(); "
        "MCP_STAGE3_RETURN_NOP=nil end; return true"
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not return from {fixture.name}: {captured!r}"
        )
    registers = captured["registers"]
    result_regs = {
        name: int(registers[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = int(registers["SP"]) & 0xFFFFFFFF
    physical_sr = int(registers["SR"]) & 0xFFFF
    architectural_sr = (
        (fixture.sr & ~CCR_MASK) | (physical_sr & CCR_MASK)
    )
    return Result(
        regs=result_regs,
        sr=architectural_sr,
        work=bytes.fromhex(captured["hex"]),
        usp=int(registers.get("USP", entry_sp)) & 0xFFFFFFFF,
        ac=None,
        cycles=None,
        halt=0,
        observed_pc=fixture.return_pc,
    )


def write_u16(session: base.McpSession, address: int, value: int) -> None:
    session.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def sa1_rom_file_offset(address: int) -> int:
    """Resolve an SA-1 `$92-$9F:8000-$FFFF` escape address in the packed ROM."""

    bank = (address >> 16) & 0xFF
    offset = address & 0xFFFF
    if not 0x92 <= bank <= 0x9F or offset < 0x8000:
        raise ValueError(f"not a packed SA-1 escape address: ${address:06X}")
    # build_interp_rom.py packs $92:8000 at file $290000 and each subsequent
    # escape bank 32 KiB later.  The bank-$9F Stage-3 bodies are therefore
    # $2F:8000 plus their local address, not part of the older $94/$95-only
    # arithmetic that this validator used before the player routes moved.
    return 0x290000 + (bank - 0x92) * 0x8000 + (offset - 0x8000)


def prepare_console(
    session: base.McpSession,
    nat: Path,
    fixture: Fixture,
    native_gate: int,
) -> None:
    session.load_state(str(nat))
    session.pause()
    register_blob = b"".join(
        base.le32(fixture.regs[name]) for name in base.REG_NAMES
    )
    session.write_memory(base.DP_SPACE, 0x00, register_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            fixture.work[offset : offset + 0x4000].hex(),
        )
    live.park_snes_cpu(session)

    flags = fixture.sr & CCR_MASK
    write_u16(session, 0x6E, flags & 1)
    write_u16(session, 0x72, (flags >> 1) & 1)
    write_u16(session, 0x60, (flags >> 2) & 1)
    write_u16(session, 0x70, (flags >> 3) & 1)
    write_u16(session, 0xA2, (flags >> 4) & 1)
    write_u16(session, 0x7C, 7)
    write_u16(session, 0x7E, 0)
    # The fixture is in supervisor mode, so USP is not architecturally used by
    # these handlers.  Seed it identically in all isolated configurations.
    entry_sp = fixture.regs["A7"] & 0xFFFFFF
    write_u16(session, 0xA4, entry_sp & 0xFFFF)
    write_u16(session, 0xA6, (entry_sp >> 16) & 0xFFFF)
    write_u16(session, 0xA8, 1)
    write_u16(session, 0xAA, 0)
    write_u16(session, 0xAC, AC_START)
    write_u16(session, 0x40, fixture.target & 0xFFFF)
    write_u16(session, 0x42, (fixture.target >> 16) & 0xFF)
    write_u16(session, 0x48, 0)
    write_u16(session, 0x4A, 0)
    write_u16(session, 0x4C, 0)
    write_u16(session, 0x4E, 0)
    write_u16(session, 0x0702, 0)
    write_u16(session, 0x0704, 1)
    write_u16(session, 0x0710, fixture.return_pc & 0xFFFF)
    write_u16(session, 0x0712, 0)
    write_u16(session, 0x0714, 0)
    write_u16(session, 0x0716, (fixture.return_pc >> 16) & 0xFF)
    write_u16(session, 0x0718, 0xFFF8)
    write_u16(session, 0x071A, native_gate)
    write_u16(session, 0x072E, 0)
    write_u16(session, 0x0730, 0x5A5A)
    write_u16(session, 0x0734, 0)
    write_u16(session, 0x0736, 0)
    write_u16(session, 0x0738, 0)
    # Gate-off is the genuine cold interpreter configuration: disable both
    # the jsr/rts xlat gate and the independent per-fetch choke.  Production
    # native-on enables both.
    write_u16(session, 0x073A, native_gate)
    write_u16(session, 0x073C, 0)


def console_result(
    session: base.McpSession,
    nat: Path,
    fixture: Fixture,
    native_gate: int,
    *,
    start_pc: int = OJMP_HOOK,
    direct_native_entry: bool = False,
) -> Result:
    prepare_console(session, nat, fixture, native_gate)
    if direct_native_entry:
        if not native_gate:
            raise ValueError("direct native entry requires native_gate=1")
        # A parent-only bridge experiment may not be represented in the
        # generic dispatcher (by design the dispatcher lacks a stage
        # discriminator).  Entering the assembled body here validates its
        # exact bounded semantics; the caller must retain a separate organic
        # execution-hook proof before treating it as a production route.
        start_pc = NATIVE_ENTRIES[fixture.target]
    if fixture.target == 0xF01B20:
        # $F01B20 is copied executable work RAM, not an xlat-table key.
        # Compare its original interpreted body directly with the native body;
        # route_probe separately proves the production $002D8A gateway.
        start_pc = NATIVE_ENTRIES[fixture.target] if native_gate else INEXT
    # Production ROMs deliberately NOP the per-fetch PC_RING call.  Patch only
    # the first 68000 word at the already-stacked return to ILLEGAL, then hook
    # the interpreter immediately before op_illegal mutates architectural
    # state.  Reaching this hook proves that RTS popped the exact real return;
    # all D/A/CCR/work/stack residue is still the post-handler state.  Restore
    # the original program word before leaving the case.
    return_file_offset = 0x10000 + fixture.return_pc
    original_return_word = bytes(
        session.read_memory("snesPrgRom", return_file_offset, 2)
    )
    # Bank-$00 executes from the LoROM mirror at file
    # ``symbol-$8000``.  Turn op_illegal itself into a stable BRA spin so the
    # debugger cannot run ahead into trap-vector mutation before pausing.
    illegal_file_offset = OP_ILLEGAL - 0x8000
    original_illegal_word = bytes(
        session.read_memory("snesPrgRom", illegal_file_offset, 2)
    )
    session.write_memory("snesPrgRom", return_file_offset, "4afc")
    session.write_memory("snesPrgRom", illegal_file_offset, "80fe")
    live.set_sa1_pc(session, start_pc)
    hook = session.add_exec_hook(OP_ILLEGAL, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, _frames = live.run_to_hook(session, hook, attempts=16)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", return_file_offset, original_return_word.hex()
        )
        session.write_memory(
            "snesPrgRom", illegal_file_offset, original_illegal_word.hex()
        )
    if (hit or {}).get("reason") != "hookFired":
        sa1 = session.get_cpu_state("Sa1")
        virtual_pc = live.read_u16(session, 0x40) | (
            (live.read_u16(session, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen gate={native_gate} did not return from "
            f"{fixture.name}: {hit!r}; virtual_pc=${virtual_pc:06X}, "
            f"sa1_pc=${(int(sa1.get('k', 0)) & 0xFF):02X}:"
            f"{int(sa1.get('pc', 0)) & 0xFFFF:04X}, "
            f"halt=${live.read_u16(session, 0x4E):04X}, "
            f"AC=${live.read_u16(session, 0xAC):04X}, "
            f"stack=${live.captured_regs(session)['A7'] & 0xFFFFFF:06X}"
        )
    observed_pc = live.read_u16(session, 0x40) | (
        (live.read_u16(session, 0x42) & 0xFF) << 16
    )
    if observed_pc != fixture.return_pc:
        raise RuntimeError(
            f"Nexen gate={native_gate} froze at ${observed_pc:06X}, "
            f"expected ${fixture.return_pc:06X}"
        )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    usp = live.read_u16(session, 0xA4) | (
        live.read_u16(session, 0xA6) << 16
    )
    return Result(
        regs=live.captured_regs(session),
        sr=(
            (fixture.sr & ~(CCR_MASK | 0x0700))
            | ((live.read_u16(session, 0x7C) & 7) << 8)
            | live.captured_ccr(session)
        ),
        work=bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, FULL_WORK_SIZE
            )
        ),
        usp=usp,
        ac=live.read_u16(session, 0xAC),
        cycles=end_cycles - start_cycles,
        halt=live.read_u16(session, 0x4E),
        observed_pc=observed_pc,
    )


def route_probe(
    session: base.McpSession,
    nat: Path,
    fixture: Fixture,
    native_gate: int,
) -> dict:
    prepare_console(session, nat, fixture, native_gate)
    route_target, native_expected, route_start, off_expected = (
        PRODUCTION_ROUTE_TARGETS.get(
            fixture.target,
            (
                fixture.target,
                NATIVE_ENTRIES[fixture.target],
                OJMP_HOOK,
                INEXT,
            ),
        )
    )
    write_u16(session, 0x40, route_target & 0xFFFF)
    write_u16(session, 0x42, (route_target >> 16) & 0xFF)
    expected = native_expected if native_gate else off_expected
    if expected >> 16 == 0:
        # Bank $00 is the first LoROM half-bank in the file.
        expected_file_offset = (expected & 0xFFFF) - 0x8000
    else:
        expected_file_offset = sa1_rom_file_offset(expected)
    original_word = bytes(
        session.read_memory("snesPrgRom", expected_file_offset, 2)
    )
    # Execution-hook notifications are asynchronous.  Make the destination a
    # temporary two-byte BRA-to-self so the sampled PC remains the routed
    # address after the hook fires.  This changes no dispatcher byte and is
    # restored before the next probe.
    session.write_memory("snesPrgRom", expected_file_offset, "80fe")
    hook = session.add_exec_hook(expected, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, route_start)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=8, hook_handle=hook)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", expected_file_offset, original_word.hex()
        )
    actual_state = session.get_cpu_state("Sa1")
    actual_pc = (
        (int(actual_state.get("k", 0)) & 0xFF) << 16
    ) | (int(actual_state["pc"]) & 0xFFFF)
    fired = (hit or {}).get("reason") == "hookFired" and actual_pc == expected
    return {
        "event": "route_probe",
        "target": f"{fixture.target:06X}",
        "production_logical_target": f"{route_target:06X}",
        "route_start_sa1_pc": f"{route_start:06X}",
        "native_gate": native_gate,
        "expected_sa1_pc": f"{expected:06X}",
        "actual_sa1_pc": f"{actual_pc:06X}",
        "hook_fired": fired,
        "cycles": int(session.get_cpu_state("Sa1")["cycleCount"])
        - start_cycles,
        "result": "green" if fired else "red",
    }


def mismatch_map(
    expected: Result,
    actual: Result,
) -> tuple[dict[str, dict[str, int]], list[int], bool]:
    register_mismatches = {
        name: {"mame": expected.regs[name], "nexen": actual.regs[name]}
        for name in base.REG_NAMES
        if expected.regs[name] != actual.regs[name]
    }
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(
            zip(expected.work[:MAPPED_WORK_SIZE], actual.work[:MAPPED_WORK_SIZE])
        )
        if left != right
    ]
    ccr_mismatch = (expected.sr & CCR_MASK) != (actual.sr & CCR_MASK)
    return register_mismatches, work_mismatches, ccr_mismatch


def compare_case(
    fixture: Fixture,
    arcade: Result,
    native_off: Result,
    native_on: Result,
) -> dict:
    off_regs, off_work, off_ccr = mismatch_map(arcade, native_off)
    on_regs, on_work, on_ccr = mismatch_map(arcade, native_on)
    off_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                fixture.work[MAPPED_WORK_SIZE:],
                native_off.work[MAPPED_WORK_SIZE:],
            ),
            start=MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    on_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                fixture.work[MAPPED_WORK_SIZE:],
                native_on.work[MAPPED_WORK_SIZE:],
            ),
            start=MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    ac_mismatch = native_off.ac != native_on.ac
    mask_mismatch = (
        ((native_off.sr >> 8) & 7) != 7
        or ((native_on.sr >> 8) & 7) != 7
    )
    usp_mismatch = native_off.usp != native_on.usp
    halt_mismatch = native_off.halt != 0 or native_on.halt != 0
    green = not any(
        (
            off_regs,
            off_work,
            off_ccr,
            on_regs,
            on_work,
            on_ccr,
            off_high,
            on_high,
            ac_mismatch,
            mask_mismatch,
            usp_mismatch,
            halt_mismatch,
        )
    )
    stack = fixture.regs["A7"] & 0xFFFF
    a4 = fixture.regs["A4"] & 0xFFFF
    return {
        "event": "case",
        "case": fixture.name,
        "target": f"{fixture.target:06X}",
        "native_entry": f"{NATIVE_ENTRIES[fixture.target]:06X}",
        "return_pc": f"{fixture.return_pc:06X}",
        "tick": fixture.tick,
        "frame": fixture.frame,
        "state": fixture.state,
        "substate": fixture.substate,
        "pre_entry_state": str(fixture.pre_entry_state.resolve()),
        "pre_entry_state_sha256": sha256(fixture.pre_entry_state),
        "prestate_kind": fixture.prestate_kind,
        "input_work_sha256": hashlib.sha256(fixture.work).hexdigest(),
        "input_stack_hex": fixture.work[
            max(0, stack - 16) : min(FULL_WORK_SIZE, stack + 32)
        ].hex(),
        "input_object_hex": fixture.work[
            max(0, a4 - 32) : min(FULL_WORK_SIZE, a4 + 64)
        ].hex(),
        "native_off": {
            "cycles_local": native_off.cycles,
            "ac_after": native_off.ac,
            "register_mismatches": off_regs,
            "ccr_mismatch": off_ccr,
            "mame_ccr": arcade.sr & CCR_MASK,
            "nexen_ccr": native_off.sr & CCR_MASK,
            "mapped_work_mismatch_count": len(off_work),
            "mapped_work_mismatch_first": [
                {
                    "address": f"F0{offset:04X}",
                    "mame": arcade.work[offset],
                    "nexen": native_off.work[offset],
                }
                for offset in off_work[:24]
            ],
            "upper_backing_mutation_count": len(off_high),
            "upper_backing_mutation_first": [
                f"F0{offset:04X}" for offset in off_high[:24]
            ],
        },
        "native_on": {
            "cycles_local": native_on.cycles,
            "ac_after": native_on.ac,
            "register_mismatches": on_regs,
            "ccr_mismatch": on_ccr,
            "mame_ccr": arcade.sr & CCR_MASK,
            "nexen_ccr": native_on.sr & CCR_MASK,
            "mapped_work_mismatch_count": len(on_work),
            "mapped_work_mismatch_first": [
                {
                    "address": f"F0{offset:04X}",
                    "mame": arcade.work[offset],
                    "nexen": native_on.work[offset],
                }
                for offset in on_work[:24]
            ],
            "upper_backing_mutation_count": len(on_high),
            "upper_backing_mutation_first": [
                f"F0{offset:04X}" for offset in on_high[:24]
            ],
        },
        "ac_match_off_on": not ac_mismatch,
        "interrupt_mask_isolated": {
            "mame_physical": 7,
            "native_off": (native_off.sr >> 8) & 7,
            "native_on": (native_on.sr >> 8) & 7,
        },
        "usp_match_off_on": not usp_mismatch,
        "halt_clear": not halt_mismatch,
        "result": "green" if green else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9050)
    parser.add_argument(
        "--targets",
        nargs="*",
        help="optional hex target filter, e.g. 027952 02F3BA",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="debug-only cap after sorting fixtures",
    )
    parser.add_argument(
        "--direct-native-targets",
        nargs="*",
        help=(
            "optional hexadecimal targets whose native-on semantic run "
            "begins at the assembled native entry; this is an isolated "
            "body check, not a production-dispatch claim"
        ),
    )
    parser.add_argument(
        "--skip-route-probes",
        action="store_true",
        help=(
            "retain only bounded semantic comparisons; requires an explicit "
            "direct-native target and cannot prove organic routing"
        ),
    )
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    target_filter = (
        {int(value, 16) for value in args.targets}
        if args.targets
        else None
    )
    direct_native_targets = {
        int(value, 16) for value in (args.direct_native_targets or [])
    }
    for label, path in (
        ("fixture directory", args.fixtures),
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    fixtures = load_fixtures(
        args.fixtures.resolve(), target_filter, args.max_cases
    )
    bsr_targets = bsr_player_targets(fixture.target for fixture in fixtures)
    if bsr_targets:
        parser.error(
            "Stage-3 player BSR target(s) require "
            "validate_stage3_player_bsr.py: "
            + ", ".join(f"${target:06X}" for target in bsr_targets)
        )
    fixture_targets = {fixture.target for fixture in fixtures}
    unknown_direct = direct_native_targets - fixture_targets
    if unknown_direct:
        parser.error(
            "--direct-native-targets not present in selected fixtures: "
            + ", ".join(f"${target:06X}" for target in sorted(unknown_direct))
        )
    if args.skip_route_probes and not direct_native_targets:
        parser.error("--skip-route-probes requires --direct-native-targets")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mame_workdir = (
        args.output.parent / f"{args.output.stem}.mame-session"
    ).resolve()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "same-state MAME original / Nexen native-off / Nexen "
            "native-on hot-handler differential; all D/A, CCR/X, exact "
            "stack and mapped 16 KiB work RAM; upper backing conservation, "
            "AC-charge equality, and production route probes; not fps or "
            "fresh-boot evidence"
        ),
        "configurations": {
            "native_off": {
                "xlat_gate_071a": 0,
                "fetch_chokepoint_gate_073a": 0,
            },
            "native_on": {
                "xlat_gate_071a": 1,
                "fetch_chokepoint_gate_073a": 1,
            },
        },
        "direct_native_targets": [
            f"{target:06X}" for target in sorted(direct_native_targets)
        ],
        "route_probes": (
            "skipped for explicitly direct-injected semantic targets; "
            "separate organic hooks are required"
            if args.skip_route_probes
            else "production dispatcher route probes retained"
        ),
        "post_return_capture": (
            "MAME replaces only the fetched return word with BRA-to-self and "
            "captures its second qualified fetch, after RTS commits A7. "
            "Nexen replaces the same first 68000 return word with ILLEGAL and "
            "temporarily makes the pre-op_illegal SA-1 hook a stable "
            "BRA-to-self; both patches are restored after every case."
        ),
        "mame": str(MAME.resolve()),
        "mame_version": mame_oracle["version"],
        "mame_sha256": mame_oracle["sha256"],
        "mame_snap_revision": mame_oracle["snap_revision"],
        "mame_gnome_content_revision": (
            mame_oracle["gnome_content_revision"]
        ),
        "mame_ipc_workdir": str(mame_workdir),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "fixture_directory": str(args.fixtures.resolve()),
        "fixture_count": len(fixtures),
        "targets": sorted(f"{fixture.target:06X}" for fixture in fixtures),
        "irq_isolation": (
            "all bounded calls physically mask level 7; fixture "
            "architectural CCR/X is compared and handler mask changes are "
            "not expected"
        ),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
    if mame_workdir.exists():
        raise RuntimeError(
            f"refusing to reuse MAME IPC directory: {mame_workdir}"
        )
    mame_workdir.mkdir(parents=True)
    mame_states = mame_workdir / "states"
    mame_states.mkdir()
    mame = base.MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(mame_workdir),
        state_directory=str(mame_states),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for fixture in fixtures:
            arcade[fixture.name] = mame_result(mame, fixture)
            event = {
                "event": "mame_case",
                "case": fixture.name,
                "target": f"{fixture.target:06X}",
                "return_pc": f"{fixture.return_pc:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    off: dict[str, Result] = {}
    on: dict[str, Result] = {}
    stderr_log = args.output.parent / f"{args.output.stem}.nexen.stderr.log"
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as nexen:
        for fixture in fixtures:
            off[fixture.name] = console_result(
                nexen, args.nat.resolve(), fixture, 0
            )
            on[fixture.name] = console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                1,
                direct_native_entry=(
                    fixture.target in direct_native_targets
                ),
            )
            event = compare_case(
                fixture,
                arcade[fixture.name],
                off[fixture.name],
                on[fixture.name],
            )
            if fixture.target in direct_native_targets:
                event["native_on_execution"] = "direct_native_entry"
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        if not args.skip_route_probes:
            seen: set[int] = set()
            for fixture in fixtures:
                if fixture.target in seen:
                    continue
                seen.add(fixture.target)
                for native_gate in (0, 1):
                    event = route_probe(
                        nexen,
                        args.nat.resolve(),
                        fixture,
                        native_gate,
                    )
                    events.append(event)
                    print(json.dumps(event, sort_keys=True), flush=True)

    checks = [
        event
        for event in events
        if event.get("event") in ("case", "route_probe")
    ]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "semantic_cases": sum(
            event.get("event") == "case" for event in checks
        ),
        "route_probes": sum(
            event.get("event") == "route_probe" for event in checks
        ),
        "green": green,
        "red": len(checks) - green,
        "total": len(checks),
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
