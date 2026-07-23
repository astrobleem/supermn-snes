#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native task root $02429C.

Capture organic sustained-gameplay inputs at the bank-$99 coroutine entry,
execute the original MC68000 root in MAME through its real trap #5 boundary,
and compare that committed state with Nexen.  The gate is exact across every
D/A register, CCR/mask, and the mapped 16 KiB work-RAM window.  The only
accepted differences are two exact, value-checked popped native-return
sentinels; their original MAME values and locations are recorded per case.

This is bounded function-semantic and local-cycle evidence, not FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
ENTRY_PC = 0x02429C
ENTRY_NATIVE = 0x9985D3
EXIT_PC = 0x02429A
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000

# Reuse the already-audited local Nexen injection/freeze machinery with this
# coroutine's entry.  Its terminal comes from LiveCase.exit_pc.
common.ENTRY_PC = ENTRY_PC
common.ENTRY_NATIVE = ENTRY_NATIVE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_offset(path: Path, name: str) -> int:
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) != 2 or fields[1] != name:
            continue
        bank, offset = fields[0].split(":", 1)
        if bank != "00":
            raise RuntimeError(f"unexpected symbol bank for {name}: {fields[0]}")
        return int(offset, 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[common.LiveCase]:
    cases: list[common.LiveCase] = []
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(state))
        m.pause()
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture {index} did not reach native entry: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = common.captured_regs(m)
                if regs["A5"] != 0x00F00000:
                    raise RuntimeError(
                        f"capture A5 is not canonical work RAM: {regs['A5']:#010x}"
                    )
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                tick = common.be16(work, 0x1C56)
                cases.append(
                    common.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=common.captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=EXIT_PC,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def load_cases(fixture_dir: Path, count: int) -> list[common.LiveCase]:
    """Load retained organic fixtures for an exact post-fix replay."""

    cases: list[common.LiveCase] = []
    metadata_paths = sorted(fixture_dir.glob("case-*.json"))
    if len(metadata_paths) < count:
        raise RuntimeError(
            f"fixture directory has {len(metadata_paths)} cases, need {count}: "
            f"{fixture_dir}"
        )
    for metadata_path in metadata_paths[:count]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work_path = metadata_path.with_suffix(".work.bin")
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"fixture {work_path} is {len(work)} bytes, expected "
                f"{FULL_WORK_SIZE}"
            )
        cases.append(
            common.LiveCase(
                name=metadata["name"],
                regs={name: int(value) for name, value in metadata["regs"].items()},
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
                exit_pc=EXIT_PC,
            )
        )
    return cases


def mame_result(session: base.MameSession, case: common.LiveCase) -> base.Result:
    session.pause()
    # MAME's capture observes opcode prefetch.  Replace only the terminal trap
    # fetch with a validation-only NOP and capture the following $02429C fetch,
    # after all body writes and the terminal DBRA have committed.  The injected
    # entry prefetch is already filled before capture_at_pc arms, so this is the
    # first observed entry hit.
    installed = session.exec_lua(
        "if MCP_2429C_EXIT_NOP then MCP_2429C_EXIT_NOP:remove() end "
        "MCP_2429C_EXIT_NOP = machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{EXIT_PC:06X}, 0x{EXIT_PC + 1:06X}, "
        "'mcp_2429c_exit_nop', function(offset, data, mask) return 0x4E71 end); "
        "return true"
    )
    if not installed:
        raise RuntimeError("failed to install MAME terminal NOP read tap")
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # Mask unrelated held VBLANK delivery only for this bounded oracle span.
    # The function has no SR-mask instruction, so report its original entry mask.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=ENTRY_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    session.exec_lua(
        "if MCP_2429C_EXIT_NOP then MCP_2429C_EXIT_NOP:remove(); "
        "MCP_2429C_EXIT_NOP=nil end; return true"
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach committed post-trap seam ${ENTRY_PC:06X} "
            f"for {case.name}: {captured!r}"
        )
    regs = captured["registers"]
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    result_sr = ((regs["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(
        result_regs,
        result_sr,
        bytes.fromhex(captured["hex"]),
    )


def indexed_bytes(data: bytes, start: int, count: int = 4) -> tuple[int, ...]:
    return tuple(data[(start + index) & 0xFFFF] for index in range(count))


def compare(
    case: common.LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
    choke_gate: int,
    br2429c_5: int,
    br23e34_1: int,
) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    all_work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]

    entry_sp = case.regs["A7"] & 0xFFFF
    residue_specs = (
        {
            "name": "popped_23e34_bsr",
            "offset": (entry_sp - 0x38) & 0xFFFF,
            "mame": (0x00, 0x02, 0x3E, 0x3C),
            "nexen": (
                0x00,
                0xFA,
                (br23e34_1 >> 8) & 0xFF,
                br23e34_1 & 0xFF,
            ),
        },
        {
            "name": "popped_259ca_jsr",
            "offset": (entry_sp - 0x04) & 0xFFFF,
            "mame": (0x00, 0x02, 0x42, 0xC4),
            "nexen": (
                0x00,
                0xFA,
                (br2429c_5 >> 8) & 0xFF,
                br2429c_5 & 0xFF,
            ),
        },
    )
    residue_rows = []
    allowed_offsets: set[int] = set()
    residues_valid = True
    for spec in residue_specs:
        offset = int(spec["offset"])
        observed_mame = indexed_bytes(arcade.work, offset)
        observed_nexen = indexed_bytes(console.work, offset)
        valid = observed_mame == spec["mame"] and observed_nexen == spec["nexen"]
        residues_valid &= valid
        if valid:
            allowed_offsets.update((offset + index) & 0xFFFF for index in range(4))
        residue_rows.append(
            {
                "name": spec["name"],
                "address": f"F0{offset:04X}",
                "expected_mame": "".join(f"{byte:02X}" for byte in spec["mame"]),
                "expected_nexen": "".join(f"{byte:02X}" for byte in spec["nexen"]),
                "observed_mame": "".join(f"{byte:02X}" for byte in observed_mame),
                "observed_nexen": "".join(f"{byte:02X}" for byte in observed_nexen),
                "valid": valid,
            }
        )
    work_mismatches = [
        offset for offset in all_work_mismatches if offset not in allowed_offsets
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (
        console.sr & base.CCR_MASK
    )
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    green = (
        not reg_mismatches
        and not work_mismatches
        and not ccr_mismatch
        and not mask_mismatch
        and residues_valid
    )
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "terminal_pc": f"{EXIT_PC:06X}",
        "nested_xlat_gate": xlat_gate,
        "fetch_choke_gate": choke_gate,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:24]
        ],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "allowed_native_return_residue": {
            "reason": "exact popped MAME returns versus native continuation sentinels",
            "all_valid": residues_valid,
            "rows": residue_rows,
            "mismatch_offsets": [
                f"F0{offset:04X}"
                for offset in all_work_mismatches
                if offset in allowed_offsets
            ],
        },
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture-rom", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--candidate-sym", type=Path, default=ROOT / "src/escbank5.sym")
    parser.add_argument("--port", type=int, default=7640)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="replay retained case-*.json/.work.bin fixtures instead of recapturing",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.capture_rom is None:
        args.capture_rom = args.rom
    for path in (
        args.rom,
        args.capture_rom,
        args.state,
        args.nexen,
        args.nat,
        args.candidate_sym,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    br2429c_5 = symbol_offset(args.candidate_sym, "br2429c_5")
    br23e34_1 = symbol_offset(args.candidate_sym, "br23e34_1")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.fixture_dir is not None:
        fixture_dir = args.fixture_dir
        if not fixture_dir.is_dir():
            parser.error(f"fixture directory does not exist: {fixture_dir}")
    else:
        fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
        if fixture_dir.exists():
            parser.error(f"fixture directory already exists: {fixture_dir}")
        fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $02429C MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": sha256(args.capture_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "terminal_pc": f"{EXIT_PC:06X}",
        "mame_boundary": (
            "validation-only NOP read tap at $02429A trap; capture following "
            "$02429C prefetch with entry SP"
        ),
        "mame_irq_isolation": (
            "entry mask forced to seven; reported result restores fixture mask; "
            "the bounded function has no SR-mask instruction"
        ),
        "native_return_residue": {
            "popped_23e34_bsr": f"MAME 00023E3C; Nexen 00FA{br23e34_1:04X}",
            "popped_259ca_jsr": f"MAME 000242C4; Nexen 00FA{br2429c_5:04X}",
            "acceptance": "exact values and entry-SP-relative addresses only",
        },
        "fixtures": args.cases,
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh production capture"
        ),
        "variants_per_fixture": 3,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = (
        load_cases(fixture_dir, args.cases)
        if args.fixture_dir is not None
        else capture_live_cases(
            args.capture_rom,
            args.state,
            args.nexen,
            args.port,
            args.cases,
            fixture_dir / "capture.nexen.stderr.log",
        )
    )
    for index, case in enumerate(cases):
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        if args.fixture_dir is None:
            (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
            (fixture_dir / f"case-{index:02d}.json").write_text(
                json.dumps(fixture, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        event = {"event": "fixture", **fixture}
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
    for case in cases:
        mame = base.MameSession(
            mame="/snap/bin/mame",
            system="superman",
            rompath=str(base.MAME_TRACE / "roms"),
            workdir=str(base.MAME_TRACE),
            state_directory=str(base.MAME_TRACE / "sta"),
            extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
        )
        try:
            mame.launch(boot_wait=25)
            arcade[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{EXIT_PC:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
        finally:
            mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for xlat_gate, choke_gate in ((0, 0), (1, 0), (1, 1)):
                console = common.nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=choke_gate,
                )
                event = compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                    choke_gate,
                    br2429c_5,
                    br23e34_1,
                )
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
