#!/usr/bin/env python3
"""Exact live-fixture A/B differential for the native collision spine.

Capture organic production inputs at the guarded $0122A4 collision spine.
Re-run each fixture from identical registers, IRAM, and all 64 KiB of mapped
68K work RAM:

* the retained v115 ROM starts at the logical 68000 PC through ``iloop``;
* the candidate starts at the corresponding native bank-$9D entry.

Stop at the first terminal PC before it executes.  Every D/A register, CCR and
interrupt-mask bit, terminal PC, and work-RAM byte must match.  The test loop
reports $AC but does not compare it: TESTFLAG deliberately interprets nested
production-only escapes, so its inner instruction count differs while their
architectural result remains the reference.  This is bounded semantic/local-
cycle evidence, not fps evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = (
    ROOT
    / "build/user-playtest-v105-investigation/rom-history/"
    "interp-v115-23xx-8c09b396.sfc"
)
DEFAULT_CANDIDATE = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/user-playtest-v105-investigation/"
    "production-v110-combat-caf6-111a-safe-coldboot-uninterrupted-3600f-v1/"
    "final.mss"
)
ILOOP = 0x0080A5
INEXT = 0x00D128
TEST_IDLE = 0x00D15F
IRAM_SIZE = 0x0800
WORK_SIZE = 0x10000
POPPED_STACK_WINDOW = 0x0200
CAPTURE_CHUNK_FRAMES = 360
CAPTURE_FRAME_BUDGET = 3600


@dataclass(frozen=True)
class Spine:
    name: str
    entry_pc: int
    entry_native: int
    terminals: frozenset[int]


def current_symbol(path: Path, bank: int, symbol: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == symbol:
            return (bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"{path}: missing {symbol}")


SPINES = {
    "4542": Spine(
        "4542",
        0x00455E,
        current_symbol(
            ROOT / "src" / "escbank.sym",
            0x92,
            "entry_4542",
        ),
        frozenset((0x00455C, 0x004560)),
    ),
    "122a4": Spine(
        "122a4",
        0x0122A4,
        0x9D8D00,
        frozenset((0x0122A2, 0x012392, 0x012344)),
    ),
    # Second half of the player/object task spine.  $0118DE is the ordinary
    # no-animation/down-input branch; $011750 is its normal task-yield tail.
    "1177c": Spine(
        "1177c",
        0x01177C,
        current_symbol(
            ROOT / "src" / "escbank5.sym",
            0x99,
            "entry_1177c",
        ),
        frozenset((0x0118DE, 0x011750)),
    ),
    # Per-slot coroutine continuation.  The campaign task-frame audit exposed
    # saved-SR differences at its $00C844 yield, so keep all four bounded exits
    # available for exact same-ROM native-off/native-on comparisons.
    "c846": Spine(
        "c846",
        0x00C846,
        current_symbol(
            ROOT / "src" / "escbank5.sym",
            0x99,
            "entry_c846",
        ),
        frozenset((0x00C844, 0x00C890, 0x00C8BA, 0x00C8DA)),
    ),
}


@dataclass
class Fixture:
    name: str
    spine: Spine
    tick: int
    regs: dict[str, int]
    sr: int
    iram: bytes
    work: bytes


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    ac: int
    aa: int
    terminal_pc: int
    work: bytes
    cycles: int
    inext_hits: int
    trace: list[tuple[int, int]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_u16(m: base.McpSession, address: int) -> int:
    return int(m.read_u16(address, base.DP_SPACE))


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def logical_pc(m: base.McpSession) -> int:
    return read_u16(m, 0x40) | ((read_u16(m, 0x42) & 0xFF) << 16)


def capture_fixtures(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    cases_per_spine: int,
    spines: list[Spine],
    buttons: int,
    capture_a6: int | None,
    output: Path,
) -> list[Fixture]:
    fixtures: list[Fixture] = []
    for spine_index, spine in enumerate(spines):
        with base.McpSession(
            rom=str(rom),
            mesen=str(nexen),
            cwd=ROOT,
            port=port + spine_index,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=output / f"capture-{spine.name}.stderr.log",
        ) as m:
            m.pause()
            m.load_state(str(state))
            m.pause()
            m.tool(
                "set_input",
                {"port": 0, "buttons": buttons & 0x0FFF, "hold": True},
            )
            hook = m.add_exec_hook(spine.entry_native, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            previous_cycles = -1
            try:
                for index in range(cases_per_spine):
                    for attempt in range(64):
                        start_frame = int(
                            m.get_state().get("frameCount", 0)
                        )
                        hit = None
                        while True:
                            current_frame = int(
                                m.get_state().get("frameCount", 0)
                            )
                            remaining_frames = (
                                CAPTURE_FRAME_BUDGET
                                - (current_frame - start_frame)
                            )
                            if remaining_frames <= 0:
                                break
                            hit = m.run_until(
                                max_frames=min(
                                    CAPTURE_CHUNK_FRAMES,
                                    remaining_frames,
                                ),
                                hook_handle=hook,
                            )
                            m.pause()
                            if (hit or {}).get("reason") == "hookFired":
                                break
                            if (
                                (hit or {}).get("reason") != "maxFrames"
                                or int(
                                    (hit or {}).get("framesAdvanced", 0)
                                )
                                <= 0
                            ):
                                break
                        if (hit or {}).get("reason") != "hookFired":
                            raise RuntimeError(
                                f"{spine.name} capture {index} did not reach "
                                f"${spine.entry_native:06X} within "
                                f"{CAPTURE_FRAME_BUDGET} emulated frames: "
                                f"{hit!r}"
                            )
                        cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                        if cycles <= previous_cycles:
                            raise RuntimeError(
                                f"{spine.name} capture did not advance"
                            )
                        previous_cycles = cycles
                        regs = common.captured_regs(m)
                        if (
                            capture_a6 is None
                            or regs["A6"] == capture_a6
                        ):
                            break
                    else:
                        raise RuntimeError(
                            f"{spine.name} did not capture requested "
                            f"A6=${capture_a6:08X} after 64 entry hits"
                        )
                    if (regs["A6"] >> 16) != 0xF0 or (regs["A7"] >> 16) != 0xF0:
                        raise RuntimeError(
                            f"{spine.name} captured non-work-RAM A6/A7: "
                            f"${regs['A6'] & 0xFFFFFF:06X}/"
                            f"${regs['A7'] & 0xFFFFFF:06X}"
                        )
                    iram = bytes(m.read_memory(base.DP_SPACE, 0, IRAM_SIZE))
                    work = bytes(
                        m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)
                    )
                    tick = common.be16(work, 0x1C56)
                    fixtures.append(
                        Fixture(
                            name=f"{spine.name}-live-{index:02d}-tick-{tick}",
                            spine=spine,
                            tick=tick,
                            regs=regs,
                            sr=common.captured_sr(m),
                            iram=iram,
                            work=work,
                        )
                    )
            finally:
                m.remove_hook(hook)
    return fixtures


def load_fixtures(
    source: Path,
    spines: list[Spine],
    cases_per_spine: int,
) -> list[Fixture]:
    """Load retained byte-exact pre-failure fixtures without recapturing."""
    requested = {spine.name: spine for spine in spines}
    loaded: dict[str, list[Fixture]] = {name: [] for name in requested}
    for metadata_path in sorted(source.glob("fixture-*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        spine_name = metadata.get("spine")
        if spine_name not in requested:
            continue
        stem = metadata_path.with_suffix("")
        iram_path = stem.with_suffix(".iram.bin")
        work_path = stem.with_suffix(".work.bin")
        for path in (iram_path, work_path):
            if not path.is_file():
                raise RuntimeError(
                    f"{metadata_path}: missing retained fixture component {path}"
                )
        iram = iram_path.read_bytes()
        work = work_path.read_bytes()
        if len(iram) != IRAM_SIZE or len(work) != WORK_SIZE:
            raise RuntimeError(
                f"{metadata_path}: invalid retained fixture sizes "
                f"{len(iram)}/{len(work)}"
            )
        for payload, key, path in (
            (iram, "iram_sha256", iram_path),
            (work, "work_sha256", work_path),
        ):
            actual = hashlib.sha256(payload).hexdigest()
            if actual != metadata.get(key):
                raise RuntimeError(
                    f"{metadata_path}: {path.name} hash mismatch: {actual}"
                )
        regs = metadata.get("regs")
        if not isinstance(regs, dict):
            raise RuntimeError(f"{metadata_path}: missing register snapshot")
        loaded[spine_name].append(
            Fixture(
                name=str(metadata["name"]),
                spine=requested[spine_name],
                tick=int(metadata["tick"]),
                regs={name: int(value) for name, value in regs.items()},
                sr=int(metadata["sr"]),
                iram=iram,
                work=work,
            )
        )

    fixtures: list[Fixture] = []
    for spine in spines:
        available = loaded[spine.name]
        if len(available) < cases_per_spine:
            raise RuntimeError(
                f"{source}: requested {cases_per_spine} retained "
                f"{spine.name} fixtures but found {len(available)}"
            )
        fixtures.extend(available[:cases_per_spine])
    return fixtures


def prepare_fixture(
    m: base.McpSession,
    nat: Path,
    fixture: Fixture,
    *,
    isolate_budget: bool,
) -> None:
    m.load_state(str(nat))
    m.pause()
    m.write_memory(base.DP_SPACE, 0, fixture.iram.hex())
    for offset in range(0, WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            fixture.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

    # The historical semantic mode isolates asynchronous delivery and reports
    # the virtual-instruction delta.  The production-cadence mode retains the
    # organic mask/pending/countdown cells so unsafe native boundary movement
    # is observable instead of normalized away.
    if isolate_budget:
        write_u16(m, 0x7C, 7)
        write_u16(m, 0x7E, 1)
        write_u16(m, 0xAA, 0)
        write_u16(m, 0xAC, 0x6000)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0x4E, 0)
    write_u16(m, 0x40, fixture.spine.entry_pc & 0xFFFF)
    write_u16(m, 0x42, fixture.spine.entry_pc >> 16)


def run_fixture(
    m: base.McpSession,
    nat: Path,
    fixture: Fixture,
    *,
    candidate: bool,
    force_reference_gates_off: bool,
    isolate_budget: bool,
) -> Result:
    prepare_fixture(
        m,
        nat,
        fixture,
        isolate_budget=isolate_budget,
    )
    if not candidate and force_reference_gates_off:
        # A same-ROM interpreted reference must disable both gameplay-native
        # gates together.  Disabling only one is not a supported continuation
        # convention once execution has entered a native body.
        write_u16(m, 0x071A, 0)
        write_u16(m, 0x073A, 0)
    hook = m.add_exec_hook(TEST_IDLE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, fixture.spine.entry_native if candidate else ILOOP)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    terminal_pc = -1
    hits = 0
    observed_pcs: list[int] = []
    trace: list[tuple[int, int]] = []
    try:
        for _ in range(512):
            hit = m.run_until(max_frames=5, hook_handle=hook)
            if (hit or {}).get("reason") != "hookFired":
                cpu = m.get_cpu_state("Sa1")
                observed = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
                raise RuntimeError(
                    f"{fixture.name} did not reach test_idle; "
                    f"SA-1=${observed:06X}: "
                    f"{hit!r}"
                )
            m.pause()
            hits += 1
            terminal_pc = logical_pc(m)
            observed_pcs.append(terminal_pc)
            trace.append((terminal_pc, read_u16(m, 0xAC)))
            if terminal_pc in fixture.spine.terminals:
                break
            # TESTFLAG=1 makes inext stop here after exactly one interpreted
            # instruction (or one complete native spine).  Resume at iloop
            # after observing the committed next PC so Nexen cannot report the
            # same not-yet-executed hook twice.  iloop still performs the real
            # per-instruction AC/IRQ work.
            base.set_sa1_pc(m, ILOOP)
        else:
            raise RuntimeError(
                f"{fixture.name} exceeded 512 test-loop boundaries; "
                f"last PC=${terminal_pc:06X}; "
                f"tail={[f'{pc:06X}' for pc in observed_pcs[-32:]]}"
            )
    finally:
        m.remove_hook(hook)
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    return Result(
        regs=common.captured_regs(m),
        sr=common.captured_sr(m),
        ac=read_u16(m, 0xAC),
        aa=read_u16(m, 0xAA),
        terminal_pc=terminal_pc,
        work=bytes(m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)),
        cycles=end_cycles - start_cycles,
        inext_hits=hits,
        trace=trace,
    )


def run_rom(
    rom: Path,
    nexen: Path,
    nat: Path,
    fixtures: list[Fixture],
    port: int,
    stderr_log: Path,
    *,
    candidate: bool,
    force_reference_gates_off: bool,
    isolate_budget: bool,
) -> dict[str, Result]:
    results: dict[str, Result] = {}
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        for fixture in fixtures:
            results[fixture.name] = run_fixture(
                m,
                nat,
                fixture,
                candidate=candidate,
                force_reference_gates_off=force_reference_gates_off,
                isolate_budget=isolate_budget,
            )
    return results


def compare(fixture: Fixture, reference: Result, candidate: Result) -> dict:
    reg_mismatches = {
        name: {
            "reference": reference.regs[name],
            "candidate": candidate.regs[name],
        }
        for name in base.REG_NAMES
        if reference.regs[name] != candidate.regs[name]
    }
    all_work_mismatches = [
        offset
        for offset, values in enumerate(zip(reference.work, candidate.work))
        if values[0] != values[1]
    ]
    terminal_sp = reference.regs["A7"] & 0xFFFF
    residue_start = max(0, terminal_sp - POPPED_STACK_WINDOW)
    popped_stack_residue = [
        offset
        for offset in all_work_mismatches
        if residue_start <= offset < terminal_sp
    ]
    live_work_mismatches = [
        offset
        for offset in all_work_mismatches
        if offset not in set(popped_stack_residue)
    ]
    scalar_mismatches = {}
    for name in ("sr", "aa", "terminal_pc"):
        reference_value = getattr(reference, name)
        candidate_value = getattr(candidate, name)
        if reference_value != candidate_value:
            scalar_mismatches[name] = {
                "reference": reference_value,
                "candidate": candidate_value,
            }
    green = (
        not reg_mismatches
        and not live_work_mismatches
        and not scalar_mismatches
    )
    return {
        "event": "case",
        "case": fixture.name,
        "spine": fixture.spine.name,
        "tick": fixture.tick,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "scalar_mismatches": scalar_mismatches,
        "work_mismatch_count": len(all_work_mismatches),
        "live_work_mismatch_count": len(live_work_mismatches),
        "live_work_mismatch_first": [
            f"F0{offset:04X}" for offset in live_work_mismatches[:32]
        ],
        "popped_native_stack_residue": {
            "accepted": True,
            "range": f"F0{residue_start:04X}-F0{terminal_sp - 1:04X}",
            "terminal_a7": f"F0{terminal_sp:04X}",
            "different_bytes": len(popped_stack_residue),
            "first_offsets": [
                f"F0{offset:04X}" for offset in popped_stack_residue[:32]
            ],
        },
        "reference_cycles": reference.cycles,
        "candidate_cycles": candidate.cycles,
        "local_cycle_delta": reference.cycles - candidate.cycles,
        "reference_inext_hits": reference.inext_hits,
        "candidate_inext_hits": candidate.inext_hits,
        "reference_trace_tail": [
            {
                "pc": f"{pc:06X}",
                "irq_countdown": countdown,
            }
            for pc, countdown in reference.trace[-64:]
        ],
        "candidate_trace_tail": [
            {
                "pc": f"{pc:06X}",
                "irq_countdown": countdown,
            }
            for pc, countdown in candidate.trace[-64:]
        ],
        "reference_ac": reference.ac,
        "candidate_ac": candidate.ac,
        "ac_delta_testflag_noncomparable": candidate.ac - reference.ac,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7810)
    parser.add_argument("--cases-per-spine", type=int, default=4)
    parser.add_argument(
        "--spine",
        action="append",
        choices=tuple(SPINES),
        default=None,
        help="spine to validate; repeat for more than one (default: 122a4)",
    )
    parser.add_argument(
        "--buttons",
        type=lambda value: int(value, 0),
        default=0x82,
    )
    parser.add_argument(
        "--capture-a6",
        type=lambda value: int(value, 0),
        help="accept only an organic entry whose complete A6 equals this value",
    )
    parser.add_argument(
        "--force-reference-gates-off",
        action="store_true",
        help=(
            "disable both gameplay-native gates only in the interpreted "
            "reference run; required for same-ROM A/B checks"
        ),
    )
    parser.add_argument(
        "--preserve-budget",
        action="store_true",
        help=(
            "retain the organic interrupt mask, pending flag, and $AC "
            "countdown instead of using the isolated $6000 semantic budget"
        ),
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help=(
            "reuse retained fixture-*.json/.iram.bin/.work.bin snapshots "
            "instead of recapturing them from --state"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.reference_rom,
        args.candidate_rom,
        args.nexen,
        args.nat,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.fixture_dir is None:
        if not args.state.is_file():
            parser.error(f"missing required input: {args.state}")
    elif not args.fixture_dir.is_dir():
        parser.error(f"missing fixture directory: {args.fixture_dir}")
    if args.cases_per_spine < 1:
        parser.error("--cases-per-spine must be positive")
    if not 0 <= args.buttons <= 0x0FFF:
        parser.error("--buttons must be in 0..0xfff")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    selected_spines = [
        SPINES[name] for name in (args.spine or ["122a4"])
    ]

    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture bounded combat-spine Nexen reference/candidate "
            "differential; all D/A registers, CCR/mask, terminal PC, and full "
            "64 KiB work RAM, with only explicitly reported native continuation "
            "bytes below restored A7 accepted as dead stack residue; TESTFLAG "
            "$AC is reported but non-comparable because nested production-only "
            "escapes are interpreted; not fps"
        ),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256(args.candidate_rom),
        "state": (
            str(args.state.resolve()) if args.fixture_dir is None else None
        ),
        "state_sha256": (
            sha256(args.state) if args.fixture_dir is None else None
        ),
        "fixture_source": (
            str(args.fixture_dir.resolve())
            if args.fixture_dir is not None
            else None
        ),
        "cases_per_spine": args.cases_per_spine,
        "buttons": args.buttons,
        "capture_a6": (
            f"{args.capture_a6:08X}"
            if args.capture_a6 is not None
            else None
        ),
        "force_reference_gates_off": args.force_reference_gates_off,
        "isolate_budget": not args.preserve_budget,
        "spines": [
            {
                "name": spine.name,
                "entry_pc": f"{spine.entry_pc:06X}",
                "entry_native": f"{spine.entry_native:06X}",
                "terminals": [f"{pc:06X}" for pc in sorted(spine.terminals)],
            }
            for spine in selected_spines
        ],
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)
    if args.fixture_dir is None:
        fixtures = capture_fixtures(
            args.candidate_rom,
            args.state,
            args.nexen,
            args.port,
            args.cases_per_spine,
            selected_spines,
            args.buttons,
            args.capture_a6,
            args.output,
        )
    else:
        fixtures = load_fixtures(
            args.fixture_dir,
            selected_spines,
            args.cases_per_spine,
        )
    for index, fixture in enumerate(fixtures):
        fixture_event = {
            "event": "fixture",
            "name": fixture.name,
            "spine": fixture.spine.name,
            "tick": fixture.tick,
            "sr": fixture.sr,
            "regs": fixture.regs,
            "iram_sha256": hashlib.sha256(fixture.iram).hexdigest(),
            "work_sha256": hashlib.sha256(fixture.work).hexdigest(),
            "interrupt_mask": int.from_bytes(
                fixture.iram[0x7C:0x7E],
                "little",
            )
            & 7,
            "virtual_irq_pending": int.from_bytes(
                fixture.iram[0xAA:0xAC],
                "little",
            ),
            "virtual_irq_countdown": int.from_bytes(
                fixture.iram[0xAC:0xAE],
                "little",
            ),
        }
        events.append(fixture_event)
        print(json.dumps(fixture_event, sort_keys=True), flush=True)
        (args.output / f"fixture-{index:02d}.json").write_text(
            json.dumps(fixture_event, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (args.output / f"fixture-{index:02d}.iram.bin").write_bytes(
            fixture.iram
        )
        (args.output / f"fixture-{index:02d}.work.bin").write_bytes(
            fixture.work
        )

    reference = run_rom(
        args.reference_rom,
        args.nexen,
        args.nat,
        fixtures,
        args.port + 2,
        args.output / "reference.stderr.log",
        candidate=False,
        force_reference_gates_off=args.force_reference_gates_off,
        isolate_budget=not args.preserve_budget,
    )
    candidate = run_rom(
        args.candidate_rom,
        args.nexen,
        args.nat,
        fixtures,
        args.port + 3,
        args.output / "candidate.stderr.log",
        candidate=True,
        force_reference_gates_off=args.force_reference_gates_off,
        isolate_budget=not args.preserve_budget,
    )
    for fixture in fixtures:
        event = compare(
            fixture, reference[fixture.name], candidate[fixture.name]
        )
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    cases = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in cases)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (args.output / "results.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
