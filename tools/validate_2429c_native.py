#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native task root $02429C.

Capture organic sustained-gameplay inputs at the bank-$99 coroutine entry,
execute the original MC68000 root in MAME through its real trap #5 boundary,
and compare that committed state with Nexen.  The gate is exact across every
D/A register, CCR/mask, and the mapped 16 KiB work-RAM window.  The only
accepted differences are exact, value-checked popped private-continuation
residues; the interruptible $025110 call must retain its original logical
$0242BE return exactly.

This is bounded function-semantic and local-cycle evidence, not FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


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
RETURN_CONTINUATIONS = (
    # Exact original return PC -> native bank-$99 continuation mappings.
    # The active object path can leave any of these popped four-byte returns
    # below A7.  Treating two quiet-fixture locations as universal made the
    # validator reject the organic tick-12067 fixture even though its only
    # differences were the exact $2436E/$243DA call-path residues.
    ("root_jsr_23342", 0x0242AC, "br2429c_1"),
    ("root_jsr_23e34", 0x0242B2, "br2429c_2"),
    ("root_jsr_235e0", 0x0242B8, "br2429c_3"),
    ("root_jsr_25110", 0x0242BE, "br2429c_4"),
    ("root_jsr_259ca", 0x0242C4, "br2429c_5"),
    ("root_bsr_243e8_first", 0x024306, "br2429c_6"),
    ("root_bsr_243e8_second", 0x024334, "br2429c_7"),
    ("root_indirect_jsr", 0x02436E, "br2429c_8"),
    ("root_bsr_2443a", 0x024378, "br2429c_9"),
    ("root_bsr_243e8_third", 0x0243B4, "br2429c_10"),
    ("root_bsr_244d4", 0x0243DA, "br2429c_11"),
    # $0259CA's active record dispatches one indirect callback.  Its return
    # stays below the parent entry SP after the final root yield, exactly like
    # the other private continuation sentinels above.
    ("scan_indirect_jsr", 0x0259FC, "br259ca_1"),
    ("helper_bsr_23e42", 0x023E3C, "br23e34_1"),
    ("helper_indirect_jsr_first", 0x023F14, "br23e42_1"),
    ("helper_indirect_jsr_second", 0x023F86, "br23e42_2"),
    ("helper_jsr_5c5e_first", 0x023FEC, "br23e42_3"),
    ("helper_jsr_5c5e_second", 0x024002, "br23e42_4"),
    ("helper_bsr_24046", 0x02400A, "br23e42_5"),
    ("helper_bsr_24026", 0x02401A, "br23e42_6"),
)

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


def mame_result(
    session: base.MameSession,
    case: common.LiveCase,
    *,
    prestate_name: str | None = None,
) -> base.Result:
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
    if prestate_name is not None:
        # Saving after forcing PC to the cached `$02429C` page can make MAME
        # 0.287 skip the following capture on this lower root path.  This is
        # still the complete injected input state (D/A, SR, USP/SP, and work
        # RAM); the deterministic resume action is the immediately following
        # PC assignment, recorded by the validator itself.
        session.save_state(prestate_name)
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


def nexen_result_irq_isolated(
    session: base.McpSession,
    nat: Path,
    case: common.LiveCase,
    *,
    xlat_gate: int,
    choke_gate: int,
    pre_state: Path | None = None,
    max_frames: int = 24,
) -> base.Result:
    """Run the bounded root with unrelated IRQ6 held, then restore its mask.

    MAME already runs masked at seven to exclude an unrelated held hardware
    interrupt.  Make Nexen's isolation symmetric and report the fixture's
    original mask because $02429C contains no SR-mask instruction.
    """

    isolated = replace(case, sr=case.sr | 0x0700)
    result = common.nexen_result(
        session,
        nat,
        isolated,
        xlat_gate=xlat_gate,
        choke_gate=choke_gate,
        irq_countdown=0xFFFF,
        enable_debug_fetch=True,
        pre_state=pre_state,
        max_frames=max_frames,
    )
    return base.Result(
        result.regs,
        (result.sr & ~0x0700) | (case.sr & 0x0700),
        result.work,
        result.cycles,
    )


def indexed_bytes(data: bytes, start: int, count: int = 4) -> tuple[int, ...]:
    return tuple(data[(start + index) & 0xFFFF] for index in range(count))


def compare(
    case: common.LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
    choke_gate: int,
    return_pairs: tuple[dict, ...],
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
    residue_rows = []
    allowed_offsets: set[int] = set()
    # Only inspect the bounded below-entry-SP call-residue window.  A row is
    # accepted only when all four original bytes and all four native bytes
    # exactly match one audited return/continuation pair; arbitrary stack
    # differences remain ordinary work-RAM failures.
    for relative in range(-0x100, -3):
        offset = (entry_sp + relative) & 0xFFFF
        observed_mame = indexed_bytes(arcade.work, offset)
        observed_nexen = indexed_bytes(console.work, offset)
        for pair in return_pairs:
            if (
                observed_mame != pair["mame"]
                or observed_nexen != pair["nexen"]
            ):
                continue
            row_offsets = {
                (offset + index) & 0xFFFF for index in range(4)
            }
            if not row_offsets & set(all_work_mismatches):
                break
            allowed_offsets.update(row_offsets)
            residue_rows.append(
                {
                    "name": pair["name"],
                    "address": f"F0{offset:04X}",
                    "expected_mame": "".join(
                        f"{byte:02X}" for byte in pair["mame"]
                    ),
                    "expected_nexen": "".join(
                        f"{byte:02X}" for byte in pair["nexen"]
                    ),
                    "observed_mame": "".join(
                        f"{byte:02X}" for byte in observed_mame
                    ),
                    "observed_nexen": "".join(
                        f"{byte:02X}" for byte in observed_nexen
                    ),
                    "valid": True,
                }
            )
            break
    work_mismatches = [
        offset for offset in all_work_mismatches if offset not in allowed_offsets
    ]
    residues_valid = not work_mismatches
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
    global ENTRY_NATIVE
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture-rom", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--candidate-sym", type=Path, default=ROOT / "src/escbank5.sym")
    parser.add_argument(
        "--entry-native",
        type=lambda value: int(value, 0),
        default=ENTRY_NATIVE,
        help="physical SA-1 entry used for the bounded Nexen execution",
    )
    parser.add_argument(
        "--logical-returns",
        action="store_true",
        help=(
            "require genuine 68000 return residue for every child call; used "
            "by the VTIME-only bank-$F3 diagnostic root"
        ),
    )
    parser.add_argument(
        "--xlat-on-only",
        action="store_true",
        help=(
            "exercise only xlat=1/choke={0,1}; required when a forced native "
            "entry depends on an xlat-gated genuine-return dispatcher"
        ),
    )
    parser.add_argument("--port", type=int, default=7640)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument(
        "--nexen-max-frames",
        type=int,
        default=24,
        help="bounded per-fixture Nexen frame budget (interpreted children need more)",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="replay retained case-*.json/.work.bin fixtures instead of recapturing",
    )
    parser.add_argument(
        "--prestate-dir",
        type=Path,
        help=(
            "retain exact post-injection/pre-execution MAME and Nexen states "
            "for every case/configuration"
        ),
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
    if args.cases < 1 or args.nexen_max_frames < 1:
        parser.error("--cases and --nexen-max-frames must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.prestate_dir is not None and args.prestate_dir.exists():
        parser.error(f"refusing to overwrite prestate directory: {args.prestate_dir}")

    ENTRY_NATIVE = args.entry_native
    common.ENTRY_NATIVE = ENTRY_NATIVE

    # Never silently substitute the mutable snap launcher for the retained
    # MAME 0.287 oracle.  This check also makes a missing recovered payload or
    # its required library path an explicit validation precondition.
    oracle = mame_identity()
    os.environ.update(mame_environment())

    return_pairs = tuple(
        {
            "name": name,
            "mame_pc": mame_pc,
            "native_continuation": symbol,
            "mame": tuple(mame_pc.to_bytes(4, "big")),
            # $025110 is interruptible.  Its bridge therefore publishes the
            # real logical return so a scheduler frame can expose an
            # arcade-identical stack.  The remaining atomic helpers still
            # retain their audited private continuation sentinels after RTS.
            "nexen": (
                tuple(mame_pc.to_bytes(4, "big"))
                if args.logical_returns or mame_pc == 0x0242BE
                else (
                    0x00,
                    0xFA,
                    (symbol_offset(args.candidate_sym, symbol) >> 8) & 0xFF,
                    symbol_offset(args.candidate_sym, symbol) & 0xFF,
                )
            ),
            "contract": (
                "exact logical return"
                if args.logical_returns or mame_pc == 0x0242BE
                else "audited private continuation residue"
            ),
        }
        for name, mame_pc, symbol in RETURN_CONTINUATIONS
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.prestate_dir is not None:
        args.prestate_dir.mkdir(parents=True)
        (args.prestate_dir / "mame").mkdir()
        (args.prestate_dir / "nexen").mkdir()
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
        "mame": oracle,
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
        "all_child_returns_are_logical": args.logical_returns,
        "xlat_on_only": args.xlat_on_only,
        "terminal_pc": f"{EXIT_PC:06X}",
        "mame_boundary": (
            "validation-only NOP read tap at $02429A trap; capture following "
            "$02429C prefetch with entry SP"
        ),
        "mame_irq_isolation": (
            "entry mask forced to seven; reported result restores fixture mask; "
            "the bounded function has no SR-mask instruction"
        ),
        "nexen_irq_isolation": (
            "entry mask forced to seven and virtual countdown set to $FFFF "
            "for the bounded root; reported result restores the fixture mask; "
            "the separate campaign boundary regression retains real preemption"
        ),
        "nexen_terminal_instrumentation": (
            "validation-only runtime restoration of the source JSR dbg_fetch "
            "at both packed bank-$00 ROM mirrors; candidate ROM file unchanged"
        ),
        "native_return_residue": {
            "mappings": [
                {
                    "name": pair["name"],
                    "contract": pair["contract"],
                    "mame": "".join(
                        f"{byte:02X}" for byte in pair["mame"]
                    ),
                    "nexen": "".join(
                        f"{byte:02X}" for byte in pair["nexen"]
                    ),
                    "native_continuation": pair["native_continuation"],
                }
                for pair in return_pairs
            ],
            "acceptance": (
                "exact four-byte audited mapping inside the 256-byte "
                "below-entry-SP call-residue window only"
            ),
        },
        "fixtures": args.cases,
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh production capture"
        ),
        "variants_per_fixture": 2 if args.xlat_on_only else 3,
        "nexen_max_frames_per_variant": args.nexen_max_frames,
        "prestate_directory": (
            str(args.prestate_dir.resolve()) if args.prestate_dir is not None else None
        ),
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
        mame_state_name = f"{case.name}-prestate" if args.prestate_dir is not None else None
        mame = base.MameSession(
            mame=str(MAME),
            system="superman",
            rompath=str(base.MAME_TRACE / "roms"),
            workdir=str(base.MAME_TRACE),
            state_directory=str(
                (args.prestate_dir / "mame")
                if args.prestate_dir is not None
                else (base.MAME_TRACE / "sta")
            ),
            extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
        )
        try:
            mame.launch(boot_wait=25)
            arcade[case.name] = mame_result(mame, case, prestate_name=mame_state_name)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{EXIT_PC:06X}",
                "pre_failure_state_name": mame_state_name,
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
            variants = (
                ((1, 0), (1, 1))
                if args.xlat_on_only
                else ((0, 0), (1, 0), (1, 1))
            )
            for xlat_gate, choke_gate in variants:
                pre_state = (
                    args.prestate_dir / "nexen" / (
                        f"{case.name}-xlat{xlat_gate}-choke{choke_gate}-prestate.mss"
                    )
                    if args.prestate_dir is not None
                    else None
                )
                console = nexen_result_irq_isolated(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=choke_gate,
                    pre_state=pre_state,
                    max_frames=args.nexen_max_frames,
                )
                event = compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                    choke_gate,
                    return_pairs,
                )
                if pre_state is not None:
                    event["pre_failure_state"] = {
                        "path": str(pre_state.resolve()),
                        "sha256": sha256(pre_state),
                        "size": pre_state.stat().st_size,
                    }
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
