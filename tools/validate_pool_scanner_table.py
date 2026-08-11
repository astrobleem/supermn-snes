#!/usr/bin/env python3
"""Three-way MAME/Nexen proof for the table-convention pool scanners.

Fixtures are captured at the genuine interpreted $02498C/$0249C2 fetches in
the retained Stage-3 checkpoint.  Those entries already have their 68000 JSR
return on the work-RAM stack.  The same captured register file, CCR/X, stack,
and mapped work RAM are then executed by original MAME, SNES with native
escapes disabled, and the new table-convention native body.  This is bounded
function semantics and local-cycle evidence; it is not an FPS measurement or
a fresh-boot claim.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import mame_0287
import profile_stage3_tick as profile
import validate_175a0_native as shared


base = shared.base
ENTRY_PCS = (0x02498C, 0x0249C2)
NATIVE_ENTRIES = {0x02498C: 0x9DB400, 0x0249C2: 0x9DB940}
INEXT = 0x00D128
OJMP_HOOK = 0x00D1B3
DEBUG_SPIN = 0x00E2CF
MAPPED_WORK_SIZE = 0x4000


@dataclass
class Case:
    name: str
    entry_pc: int
    return_pc: int
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_symbol(symbol: str) -> int:
    path = ROOT / "src/escbank7.sym"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == symbol:
            return 0x9D0000 | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"{path}: missing {symbol}")


def r16(m: base.McpSession, address: int) -> int:
    return shared.read_u16(m, address)


def virtual_pc(m: base.McpSession) -> int:
    return r16(m, 0x40) | ((r16(m, 0x42) & 0xFF) << 16)


def captured_case(m: base.McpSession, entry_pc: int, ordinal: int) -> Case:
    regs = shared.captured_regs(m)
    work = bytes(m.read_memory(base.SNES_SPACE, 0x400000, 0x10000))
    sp = regs["A7"] & 0xFFFF
    if sp > 0x3FFC:
        raise RuntimeError(f"${entry_pc:06X}: A7 outside mapped work RAM: ${regs['A7']:08X}")
    return_pc = int.from_bytes(work[sp:sp + 4], "big") & 0xFFFFFF
    if not return_pc:
        raise RuntimeError(f"${entry_pc:06X}: zero return PC at F0{sp:04X}")
    return Case(
        name=f"pc-{entry_pc:06x}-tick-{r16(m, 0x0760)}-{ordinal:02d}",
        entry_pc=entry_pc,
        return_pc=return_pc,
        regs=regs,
        sr=shared.captured_sr(m),
        work=work,
        tick=r16(m, 0x0760),
    )


def capture_cases(
    rom: Path, state: Path, nexen: Path, port: int, per_entry: int, out: Path
) -> list[Case]:
    cases: list[Case] = []
    seen = {entry: 0 for entry in ENTRY_PCS}
    profile.configure_dotnet(nexen)
    with profile.trace.McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=out / "capture.nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        profile.stage3.migrate_checkpoint_video(m, rom.read_bytes())
        # The candidate may already route these PCs natively.  Capture the
        # genuine 68000 entry frame under the explicit native-off control so
        # the saved fixture remains an arcade/interpreter state, not a view of
        # a native body after it has consumed the caller return.
        shared.write_u16(m, 0x071A, 0)
        hook = m.add_exec_hook(profile.LH_OFF, cpu_type="Sa1")
        try:
            for _ in range(4000):
                response = m.run_until(max_frames=240, hook_handle=hook)
                m.pause()
                if response.get("reason") != "hookFired":
                    raise RuntimeError(f"lost interpreted-fetch hook: {response}")
                entry = virtual_pc(m)
                if entry in seen and seen[entry] < per_entry:
                    cases.append(captured_case(m, entry, seen[entry]))
                    seen[entry] += 1
                    if all(count == per_entry for count in seen.values()):
                        break
        finally:
            m.remove_hook(hook)
    if not all(count == per_entry for count in seen.values()):
        raise RuntimeError(f"did not capture all pool entries: {seen}")
    return cases


def load_cases(directory: Path) -> list[Case]:
    """Reuse retained exact-entry states without mutating the source checkpoint.

    The fixture is a pre-body register/work-RAM snapshot captured at a genuine
    $02498C/$0249C2 fetch with its caller's JSR return still on the 68000
    stack. It is therefore portable across candidate ROMs, while each run
    still executes that state independently in MAME, native-off, and native-on.
    """

    cases: list[Case] = []
    for metadata_path in sorted(directory.glob("case-*.json")):
        metadata = json.loads(metadata_path.read_text())
        work_path = metadata_path.with_suffix(".work.bin")
        if not work_path.is_file():
            raise RuntimeError(f"missing retained work image: {work_path}")
        work = work_path.read_bytes()
        if len(work) != 0x10000:
            raise RuntimeError(f"{work_path}: expected 64 KiB, got {len(work)}")
        if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
            raise RuntimeError(f"{work_path}: work SHA-256 does not match metadata")
        cases.append(
            Case(
                name=str(metadata["case"]),
                entry_pc=int(str(metadata["entry_pc"]), 16),
                return_pc=int(str(metadata["return_pc"]), 16),
                regs={name: int(value) for name, value in metadata["regs"].items()},
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
            )
        )
    expected = set(ENTRY_PCS)
    found = {case.entry_pc for case in cases}
    if not cases or found != expected:
        raise RuntimeError(
            f"{directory}: expected fixtures for {sorted(expected)}, found {sorted(found)}"
        )
    return cases


def mame_result(session: base.MameSession, case: Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # The local oracle must not take an unrelated held VBLANK IRQ6 while it
    # runs this leaf. The scanner does not write the interrupt mask, so restore
    # the organically captured mask in the compared result.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", case.entry_pc)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.return_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    sr = ((regs["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(result_regs, sr, bytes.fromhex(captured["hex"]))


def configure_fixture(m: base.McpSession, case: Case, *, xlat_gate: int) -> None:
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    m.write_memory(base.SNES_SPACE, 0x400000, case.work[:MAPPED_WORK_SIZE].hex())
    shared.park_snes_cpu(m)
    flags = case.sr & base.CCR_MASK
    shared.write_u16(m, 0x6E, flags & 1)
    shared.write_u16(m, 0x72, (flags >> 1) & 1)
    shared.write_u16(m, 0x60, (flags >> 2) & 1)
    shared.write_u16(m, 0x70, (flags >> 3) & 1)
    shared.write_u16(m, 0xA2, (flags >> 4) & 1)
    shared.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    shared.write_u16(m, 0x40, case.entry_pc & 0xFFFF)
    shared.write_u16(m, 0x42, (case.entry_pc >> 16) & 0xFF)
    shared.write_u16(m, 0x4A, 0)
    shared.write_u16(m, 0x4C, 0)
    shared.write_u16(m, 0xAC, 0x7000)
    shared.write_u16(m, 0x0710, case.return_pc & 0xFFFF)
    shared.write_u16(m, 0x0712, 0)
    shared.write_u16(m, 0x0714, 0)
    shared.write_u16(m, 0x0716, (case.return_pc >> 16) & 0xFF)
    shared.write_u16(m, 0x0718, 0xFFF8)
    shared.write_u16(m, 0x071A, xlat_gate)
    shared.write_u16(m, 0x072E, 0)
    shared.write_u16(m, 0x0730, 0)
    shared.write_u16(m, 0x0734, 0)
    shared.write_u16(m, 0x0736, 0)
    shared.write_u16(m, 0x0738, 0)
    shared.write_u16(m, 0x073A, 0)
    shared.write_u16(m, 0x073C, 0)


def enable_debug_fetch(m: base.McpSession) -> None:
    for offset in (0x0000EB, 0x0080EB):
        actual = bytes(m.read_memory("snesPrgRom", offset, 3))
        if actual not in (bytes.fromhex("8001ea"), bytes.fromhex("2081e2")):
            raise RuntimeError(f"unexpected dbg_fetch bytes at ${offset:06X}: {actual.hex()}")
        m.write_memory("snesPrgRom", offset, "2081e2")


def nexen_result(
    m: base.McpSession, state: Path, case: Case, *, mode: str
) -> tuple[base.Result, dict[str, Any]]:
    m.load_state(str(state))
    m.pause()
    enable_debug_fetch(m)
    configure_fixture(m, case, xlat_gate=0 if mode == "native-off" else 1)
    m.drain_notifications(timeout=0.05)
    start = int(m.get_cpu_state("Sa1")["cycleCount"])
    base.set_sa1_pc(
        # A real $0249xx scan follows an MC68000 RTS: op_rts_norm tail-calls
        # ojmp_hook with the genuine return already on the emulated stack.
        # Starting there exercises xlat, the bank-$9D sparse dispatcher, and
        # the table/rts clone, rather than directly calling the clone.
        m, INEXT if mode == "native-off" else OJMP_HOOK
    )
    # Do not add an entry breakpoint here: Nexen's SA-1 execution hook is a
    # stopping debugger primitive and changes the body timing/observable
    # state. The native-on comparison starts at the real table dispatcher;
    # xlat and its pack-audited branch chain are therefore part of the tested
    # execution, while a separately collected profiler trace proves live hits.
    hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    hit = m.run_until(max_frames=60, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if hit.get("reason") != "hookFired":
        raise RuntimeError(f"Nexen {mode} did not return for {case.name}: {hit!r}")
    # $0712 is a debugger/inext breadcrumb, not architectural state. The
    # real rts→xlat route reaches the same virtual return through ors_pre
    # without necessarily setting it, so require the architectural return PC.
    if virtual_pc(m) != case.return_pc:
        raise RuntimeError(
            f"Nexen {mode} terminal ${virtual_pc(m):06X}, expected ${case.return_pc:06X}; "
            f"SA-1 ${int(m.get_cpu_state('Sa1')['pc']):06X}"
        )
    sr = 0x2000 | ((shared.read_u16(m, 0x7C) & 7) << 8) | shared.captured_ccr(m)
    route = {
        "start": "ojmp_hook/xlat" if mode == "native-on" else "inext",
        "native_entry": (
            f"{NATIVE_ENTRIES[case.entry_pc]:06X}" if mode == "native-on" else None
        ),
    }
    return (
        base.Result(
            shared.captured_regs(m),
            sr,
            bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
            int(m.get_cpu_state("Sa1")["cycleCount"]) - start,
        ),
        route,
    )


def compare(
    case: Case,
    oracle: base.Result,
    result: base.Result,
    mode: str,
    route: dict[str, Any],
) -> dict[str, Any]:
    reg_mismatches = {
        name: {"mame": oracle.regs[name], "snes": result.regs[name]}
        for name in base.REG_NAMES
        if oracle.regs[name] != result.regs[name]
    }
    work = [
        offset
        for offset, (left, right) in enumerate(zip(oracle.work, result.work))
        if left != right
    ]
    return {
        "event": "case",
        "case": case.name,
        "entry_pc": f"{case.entry_pc:06X}",
        "return_pc": f"{case.return_pc:06X}",
        "tick": case.tick,
        "mode": mode,
        "route": route,
        "result": "green" if not reg_mismatches and not work and oracle.sr == result.sr else "red",
        "reg_mismatches": reg_mismatches,
        "mame_sr": oracle.sr,
        "snes_sr": result.sr,
        "work_mismatch_count": len(work),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work[:24]],
        "snes_cycles": result.cycles,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fixtures-from",
        type=Path,
        help=(
            "reuse retained case-*.json/.work.bin exact-entry snapshots instead "
            "of running the source checkpoint to acquire them"
        ),
    )
    parser.add_argument("--cases-per-entry", type=int, default=2)
    parser.add_argument("--port", type=int, default=9190)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.cases_per_entry < 1:
        raise SystemExit("--cases-per-entry must be positive")
    for pc, symbol in ((0x02498C, "entry_2498ct"), (0x0249C2, "entry_249c2t")):
        if NATIVE_ENTRIES[pc] != resolve_symbol(symbol):
            raise SystemExit(f"{symbol} did not assemble at its audited address")
    os.environ.update(mame_0287.environment())
    mame_identity = mame_0287.identity()
    args.output.mkdir(parents=True)
    events: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "scope": (
                "Stage-3 pool-scanner table/rts MAME/native-off/native-on "
                "differential; registers, CCR/X, stack return, and mapped work RAM; not fps"
            ),
            "mame": mame_identity,
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "state": str(args.state.resolve()),
            "state_sha256": sha256(args.state),
            "fixture_source": (
                str(args.fixtures_from.resolve()) if args.fixtures_from else "captured-this-run"
            ),
            "native_entries": {f"{pc:06X}": f"{entry:06X}" for pc, entry in NATIVE_ENTRIES.items()},
            "time": time.time(),
        }
    ]
    if args.fixtures_from:
        if not args.fixtures_from.is_dir():
            raise SystemExit(f"missing fixture directory: {args.fixtures_from}")
        cases = load_cases(args.fixtures_from)
    else:
        cases = capture_cases(
            args.rom,
            args.state,
            args.nexen,
            args.port,
            args.cases_per_entry,
            args.output,
        )
    for index, case in enumerate(cases):
        metadata = {
            "event": "fixture",
            "case": case.name,
            "entry_pc": f"{case.entry_pc:06X}",
            "return_pc": f"{case.return_pc:06X}",
            "tick": case.tick,
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        events.append(metadata)
        (args.output / f"case-{index:02d}.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        (args.output / f"case-{index:02d}.work.bin").write_bytes(case.work)

    arcade: dict[str, base.Result] = {}
    for case in cases:
        mame = base.MameSession(
            mame=str(mame_0287.MAME),
            system="superman",
            rompath=str(base.MAME_TRACE / "roms"),
            workdir=str(base.MAME_TRACE),
            state_directory=str(base.MAME_TRACE / "sta"),
            extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
        )
        try:
            mame.launch(boot_wait=25)
            arcade[case.name] = mame_result(mame, case)
        finally:
            mame.stop()

    with base.McpSession(
        rom=str(args.rom), mesen=str(args.nexen), cwd=ROOT, port=args.port + 1,
        boot_wait=8.0, socket_timeout=180.0,
        stderr_log=args.output / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for mode in ("native-off", "native-on"):
                result, route = nexen_result(nexen, args.state, case, mode=mode)
                events.append(compare(case, arcade[case.name], result, mode, route))

    rows = [event for event in events if event.get("event") == "case"]
    summary = {
        "event": "summary",
        "green": sum(row["result"] == "green" for row in rows),
        "red": sum(row["result"] != "green" for row in rows),
        "total": len(rows),
        "result": "green" if rows and all(row["result"] == "green" for row in rows) else "red",
        "time": time.time(),
    }
    events.append(summary)
    (args.output / "results.jsonl").write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
