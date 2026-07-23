#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native collision root $025110.

Organic inputs are captured at the production bank-$97 entry before its
skipped-JSR adapter pushes a return.  The MAME oracle receives the equivalent
real 68000 stack frame and returns to the original-ROM self-loop at $002B16;
the repeating fetch makes MAME's prefetch-skewed PC tap settle at the correct
post-RTS SP.  Nexen uses the same return and freezes through the interpreter's
debug seam.  Every D/A register, CCR/mask, and mapped 16 KiB work-RAM byte is
compared with nested xlat both disabled and enabled.

This is bounded function-semantic and local-cycle evidence, not FPS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_175a0_native as shared


base = shared.base
ROOT = shared.ROOT
DEFAULT_ROM = shared.DEFAULT_ROM
DEFAULT_STATE = shared.DEFAULT_STATE
ENTRY_PC = 0x025110
ENTRY_NATIVE = 0x978000
RETURN_PC = 0x002B16
DEBUG_SPIN = shared.DEBUG_SPIN
MAPPED_WORK_SIZE = shared.MAPPED_WORK_SIZE
FULL_WORK_SIZE = shared.FULL_WORK_SIZE
COLLISION_TABLE_OFFSET = 0x3A74
COLLISION_RECORD_SIZE = 0x10
COLLISION_RECORD_COUNT = 31
GUARD_ACTIVE_COUNTS = (0, 1, 16, 17)
SEMANTIC_GUARD_SHAPES = (
    "stage2-overlap",
    "stage2-contained-nonzero-response",
    "stage2-second-outer-active",
    "stage2-negative-edge",
    "stage5-positive-outer",
    "stage5-negative-final-slot",
)


def case_work(case: shared.LiveCase) -> bytes:
    """Install the real JSR return at the stack position native will push."""

    pre_push_sp = case.regs["A7"] & 0xFFFFFF
    if (pre_push_sp >> 16) != 0xF0 or (pre_push_sp & 0xFFFF) < 4:
        raise RuntimeError(
            f"{case.name}: unsupported pre-push A7 ${pre_push_sp:06X}"
        )
    work = bytearray(case.work)
    offset = (pre_push_sp - 4) & 0xFFFF
    work[offset : offset + 4] = base.be32(RETURN_PC)
    return bytes(work)


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
    input_buttons: int | None,
) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
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
        if input_buttons is not None:
            m.tool(
                "set_input",
                {"port": 0, "buttons": input_buttons, "hold": True},
            )
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture {index} did not reach native entry: "
                        f"{hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = shared.captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                if (regs["A5"] & 0xFFFFFF) != 0xF00000:
                    raise RuntimeError(
                        f"capture {index}: noncanonical A5 "
                        f"${regs['A5'] & 0xFFFFFF:06X}"
                    )
                tick = shared.be16(work, 0x1C56)
                cases.append(
                    shared.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=shared.captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=RETURN_PC,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def load_cases(fixture_dir: Path, count: int) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
    metadata_paths = sorted(fixture_dir.glob("case-*.json"))
    if len(metadata_paths) < count:
        raise RuntimeError(
            f"fixture directory has {len(metadata_paths)} cases, need {count}: "
            f"{fixture_dir}"
        )
    for metadata_path in metadata_paths[:count]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work = metadata_path.with_suffix(".work.bin").read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"fixture for {metadata_path} is {len(work)} bytes, expected "
                f"{FULL_WORK_SIZE}"
            )
        cases.append(
            shared.LiveCase(
                name=metadata["name"],
                regs={name: int(value) for name, value in metadata["regs"].items()},
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
                exit_pc=RETURN_PC,
            )
        )
    return cases


def derive_guard_cases(seed: shared.LiveCase) -> list[shared.LiveCase]:
    """Create boundary shapes for the guarded collision shortcuts.

    The count cases exercise stage-1 compact-list limits.  Additional cases
    force stage-2 overlap/shape/sign misses and stage-5 active/final-negative
    behavior so both fast exits and pre-write fallbacks are compared to MAME.
    """

    if (seed.regs["A5"] & 0xFFFFFF) != 0xF00000:
        raise RuntimeError(
            f"{seed.name}: guard fixture requires canonical A5=$F00000"
        )
    derived: list[shared.LiveCase] = []
    for active_count in GUARD_ACTIVE_COUNTS:
        work = bytearray(seed.work)
        for slot in range(COLLISION_RECORD_COUNT):
            offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
            work[offset : offset + 2] = b"\x00\x00"
        for slot in range(active_count):
            offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
            work[offset : offset + 2] = b"\x00\x01"
            work[offset + 0x0A : offset + 0x0C] = b"\x00\x00"
        derived.append(
            shared.LiveCase(
                name=f"guard-active-{active_count:02d}-from-{seed.name}",
                regs=dict(seed.regs),
                sr=seed.sr,
                work=bytes(work),
                tick=seed.tick,
                exit_pc=RETURN_PC,
            )
        )

    def add_shape(name: str, work: bytearray) -> None:
        derived.append(
            shared.LiveCase(
                name=f"guard-{name}-from-{seed.name}",
                regs=dict(seed.regs),
                sr=seed.sr,
                work=bytes(work),
                tick=seed.tick,
                exit_pc=RETURN_PC,
            )
        )

    # Isolate one stage-1 record so that stage 1 itself cannot write it, then
    # force a stage-2 rectangle overlap.  The new stage-2 shortcut must detect
    # the overlap and delegate before the first game-state write.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    inner = COLLISION_TABLE_OFFSET
    outer = 0x3A54
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x00"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x00"
    work[inner + 2 : inner + 10] = work[outer + 2 : outer + 10]
    add_shape("stage2-overlap", work)

    # A rectangle strictly contained by the outer takes both response-clear
    # branches.  Seed nonzero C/D bytes and a nonzero inner E word: the arcade
    # routine conditions the *outer* clear on outer.E, but always clears the
    # inner response.  This catches both a mistaken inner-E guard and the
    # 65816's lack of a long-addressing STZ instruction.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    work[outer : outer + 2] = b"\x00\x01"
    work[outer + 2 : outer + 10] = bytes.fromhex("006400c8006400c8")
    work[outer + 0x0A : outer + 0x0C] = b"\x00\x23"
    work[outer + 0x0C : outer + 0x0E] = b"\x33\x44"
    work[outer + 0x0E : outer + 0x10] = b"\x00\x60"
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 2 : inner + 10] = bytes.fromhex("007800b4007800b4")
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x60"
    work[inner + 0x0C : inner + 0x0E] = b"\x55\xAA"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x01"
    add_shape("stage2-contained-nonzero-response", work)

    # A positive second stage-2 outer is outside the specialized one-outer
    # shape and must run the complete generated pass.
    work = bytearray(seed.work)
    work[0x3A64 : 0x3A66] = b"\x00\x01"
    add_shape("stage2-second-outer-active", work)

    # Signed coordinate domains are retained by the generated path.
    work = bytearray(seed.work)
    for slot in range(32):
        offset = COLLISION_TABLE_OFFSET + slot * COLLISION_RECORD_SIZE
        work[offset : offset + 2] = b"\x00\x00"
    work[inner : inner + 2] = b"\x00\x01"
    work[inner + 2 : inner + 4] = b"\xFF\xFF"
    work[inner + 0x0A : inner + 0x0C] = b"\x00\x00"
    work[inner + 0x0E : inner + 0x10] = b"\x00\x00"
    add_shape("stage2-negative-edge", work)

    # Any positive stage-5 outer must reject the all-inactive proof and retain
    # the original inner-loop/call behavior.
    work = bytearray(seed.work)
    work[0x37F4 : 0x37F6] = b"\x00\x01"
    add_shape("stage5-positive-outer", work)

    # The inactive shortcut still has to publish the final TST.W negative CCR
    # when the last narrow slot is negative rather than zero.
    work = bytearray(seed.work)
    work[0x37E4 : 0x37E6] = b"\xFF\xFF"
    add_shape("stage5-negative-final-slot", work)
    return derived


def derive_x_variants(cases: list[shared.LiveCase]) -> list[shared.LiveCase]:
    """Replay every semantic shape with incoming MC68000 X clear and set."""

    variants: list[shared.LiveCase] = []
    for case in cases:
        for x in (0, 1):
            variants.append(
                shared.LiveCase(
                    name=f"{case.name}-x{x}",
                    regs=dict(case.regs),
                    sr=(case.sr & ~0x10) | (x << 4),
                    work=case.work,
                    tick=case.tick,
                    exit_pc=case.exit_pc,
                )
            )
    return variants


def mame_result(session: base.MameSession, case: shared.LiveCase) -> base.Result:
    work = case_work(case)
    pre_push_sp = case.regs["A7"] & 0xFFFFFF
    entry_sp = (pre_push_sp - 4) & 0xFFFFFF

    session.pause()
    session.write_block(0xF00000, work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # $025110 contains no SR-mask writer.  Mask unrelated real IRQ6 delivery
    # during the injected span, then restore the organic mask on readback.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=pre_push_sp,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach settled return loop ${RETURN_PC:06X} "
            f"for {case.name}: {captured!r}"
        )
    raw = captured["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    sr = ((raw["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(regs, sr, bytes.fromhex(captured["hex"]))


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: shared.LiveCase,
    *,
    xlat_gate: int,
) -> base.Result:
    work = case_work(case)
    m.load_state(str(nat))
    m.pause()

    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    shared.write_u16(m, 0x6E, flags & 1)
    shared.write_u16(m, 0x72, (flags >> 1) & 1)
    shared.write_u16(m, 0x60, (flags >> 2) & 1)
    shared.write_u16(m, 0x70, (flags >> 3) & 1)
    shared.write_u16(m, 0xA2, (flags >> 4) & 1)
    shared.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    shared.write_u16(m, 0x40, RETURN_PC & 0xFFFF)
    shared.write_u16(m, 0x42, (RETURN_PC >> 16) & 0xFF)
    shared.write_u16(m, 0x4A, 0)
    shared.write_u16(m, 0x4C, 0)
    shared.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    shared.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    shared.write_u16(m, 0xA8, 1)
    shared.write_u16(m, 0xAA, 0)
    shared.write_u16(m, 0xAC, 0x7000)
    shared.write_u16(m, 0x0702, 0)
    shared.write_u16(m, 0x0704, 1)
    shared.write_u16(m, 0x0710, RETURN_PC & 0xFFFF)
    shared.write_u16(m, 0x0712, 0)
    shared.write_u16(m, 0x0714, 0)
    shared.write_u16(m, 0x0716, (RETURN_PC >> 16) & 0xFF)
    shared.write_u16(m, 0x0718, 0xFFF8)
    shared.write_u16(m, 0x071A, xlat_gate)
    shared.write_u16(m, 0x072E, 0)
    shared.write_u16(m, 0x0730, 0)
    shared.write_u16(m, 0x0734, 0)
    shared.write_u16(m, 0x0736, 0)
    shared.write_u16(m, 0x0738, 0)
    shared.write_u16(m, 0x073A, 0)
    shared.write_u16(m, 0x073C, 0)

    seam_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=24, hook_handle=seam_hook)
    m.pause()
    m.remove_hook(seam_hook)
    if (hit or {}).get("reason") != "hookFired":
        sa1_state = m.get_cpu_state("Sa1")
        observed_pc = shared.read_u16(m, 0x40) | (
            (shared.read_u16(m, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen did not freeze at return ${RETURN_PC:06X} "
            f"for {case.name}, xlat={xlat_gate}: {hit!r}; "
            f"SA1={sa1_state!r}, 68K_PC=${observed_pc:06X}, "
            f"halt=${shared.read_u16(m, 0x4E):04X}, "
            f"compact_count=${shared.read_u16(m, 0x50):04X}, "
            f"outer=${shared.read_u16(m, 0x52):04X}, "
            f"inner=${shared.read_u16(m, 0x56):04X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = shared.read_u16(m, 0x40) | (
        (shared.read_u16(m, 0x42) & 0xFF) << 16
    )
    if not shared.read_u16(m, 0x0712) or observed_pc != RETURN_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${RETURN_PC:06X}"
        )
    sr = 0x2000 | ((shared.read_u16(m, 0x7C) & 7) << 8) | shared.captured_ccr(m)
    return base.Result(
        shared.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7720)
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        help="hold this Nexen port-0 button mask while capturing fresh fixtures",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="replay retained case-*.json/.work.bin fixtures instead of recapturing",
    )
    parser.add_argument(
        "--guard-shapes",
        action="store_true",
        help=(
            "derive 0/1/16/17-active boundary cases from the first fixture "
            "to exercise both compact and fallback paths"
        ),
    )
    parser.add_argument(
        "--both-x",
        action="store_true",
        help="replay every organic/guard shape with incoming X clear and set",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0xFFF:
        parser.error("--input-buttons must be a 12-bit mask")

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
            "live-fixture function-local $025110 MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "mame_return_seam": {
            "pc": f"{RETURN_PC:06X}",
            "instruction": "BRA.B self",
            "reason": "repeat fetch until post-RTS SP is settled",
            "rom_file_modified": False,
        },
        "mame_irq_isolation": {
            "reason": "prevent unrelated held VBLANK IRQ6 during local injection",
            "entry_mask": 7,
            "reported_mask": "organic entry mask; function has no SR-mask writer",
            "rom_file_modified": False,
        },
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": shared.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": shared.sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": shared.sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": shared.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "fixtures": args.cases,
        "input_buttons": args.input_buttons,
        "synthetic_guard_active_counts": (
            list(GUARD_ACTIVE_COUNTS) if args.guard_shapes else []
        ),
        "synthetic_guard_shapes": (
            list(SEMANTIC_GUARD_SHAPES) if args.guard_shapes else []
        ),
        "incoming_x_variants": [0, 1] if args.both_x else "organic",
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh production capture"
        ),
        "variants_per_fixture": 2,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = (
        load_cases(fixture_dir, args.cases)
        if args.fixture_dir is not None
        else capture_live_cases(
            args.rom,
            args.state,
            args.nexen,
            args.port,
            args.cases,
            fixture_dir / "capture.nexen.stderr.log",
            args.input_buttons,
        )
    )
    if args.guard_shapes:
        cases.extend(derive_guard_cases(cases[0]))
    if args.both_x:
        cases = derive_x_variants(cases)
    for index, case in enumerate(cases):
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "terminal_pc": f"{RETURN_PC:06X}",
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
        for case in cases:
            arcade[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{RETURN_PC:06X}",
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
        # A retained fixture directory is immutable evidence.  Keep replay
        # process logs beside the new result instead of overwriting the log
        # that accompanied the original capture.
        stderr_log=args.output.parent / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for xlat_gate in (0, 1):
                console = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                )
                event = shared.compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                    0,
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
