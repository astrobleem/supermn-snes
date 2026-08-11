#!/usr/bin/env python3
"""Replay the organic Stage 1-3 boss health sequence in three configurations.

The fixture capture follows ``inp/superman_play.inp`` once in exact MAME
0.287.  It retains every main-boss initialization and damage-handler entry,
including full 68000 registers, SR, and 64 KiB work RAM.  Subsequent runs can
reuse those immutable fixtures without replaying the movie.

Each entry executes to the real routine terminal in:

* MAME running the original 68000 code;
* Nexen with all native/HLE gates disabled;
* Nexen with the production native/HLE gates enabled.

The focused gate is exact for all D/A registers, CCR/X and interrupt mask, and
the complete mapped 16 KiB work-RAM window.  It also reports the boss object,
collision record, task word, game tick, and stack window.  IRQ delivery is
deliberately masked in these bounded spans; cadence belongs to the later
organic replay and is not inferred here.

This validates arcade initialization and every health subtraction actually
seen in the retained movie.  It is not by itself proof that an organic SNES
battle generated the same attacks or completed the same number of hits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
MAME_MCP = Path("/home/chad/mame-mcp")
MESEN_PY = Path("/home/chad/Mesen2/python")
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_DIAGNOSTIC_ROM = (
    EVIDENCE
    / "24bc2-final-source-pcring-v2"
    / "interp.sfc"
)
DEFAULT_BASE_STATE = Path("/tmp/b0_native.mss")
DEFAULT_SUMMARY = EVIDENCE / "boss-allstage-summary.json"
DEFAULT_MOVIE = ROOT / "inp" / "superman_play.inp"
DEFAULT_FIXTURES = EVIDENCE / "boss-health-stage123-fixtures-v3"
MAME_ROMPATH = ROOT / "tools" / "mame-trace" / "roms"
MAME_WORKDIR = ROOT / "tools" / "mame-trace"

EXPECTED_PRODUCTION_SHA256 = (
    "9dccb3c732669f6879cf828f14b27785af35bdd17a347bb4a75193a835cbe8f7"
)
EXPECTED_DIAGNOSTIC_SHA256 = (
    "16b8b164628e727375c6d8196bea15449a8c9966856ecb1f1217566b058b230d"
)

sys.path.insert(0, str(MAME_MCP))
sys.path.insert(0, str(MESEN_PY))
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

from mame_mcp.session import MameSession  # noqa: E402
import mesen_mcp.session as _mesen_session  # noqa: E402

_mesen_session.validate_mesen_build = lambda *args, **kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import validate_175a0_native as shared  # noqa: E402

base = shared.base

MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
INEXT = 0x00D128
DEBUG_SPIN = 0x00E2CF
OP_ILLEGAL = 0x00CDED
INIT_TERMINAL = 0x014E1C
DAMAGE_ENTRY = 0x014CEA
DAMAGE_TERMINAL = 0x014CEE


@dataclass(frozen=True)
class StageOracle:
    stage: int
    record: int
    initial_health: int
    damage_values: tuple[int, ...]
    health_before: tuple[int, ...]
    damage_frames: tuple[int, ...]
    init_entry: int
    init_frame: int


@dataclass(frozen=True)
class CaseSpec:
    name: str
    stage: int
    kind: str
    ordinal: int
    entry: int
    terminal: int
    record: int
    expected_before: int
    expected_after: int
    expected_damage: int | None
    expected_frame: int | None
    retain_pre_state: bool


@dataclass
class Case:
    spec: CaseSpec
    frame: int
    regs: dict[str, int]
    sr: int
    work: bytes
    mame_state: str | None = None


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    cycles: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument(
        "--diagnostic-rom", type=Path, default=DEFAULT_DIAGNOSTIC_ROM
    )
    parser.add_argument("--base-state", type=Path, default=DEFAULT_BASE_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--movie", type=Path, default=DEFAULT_MOVIE)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--capture-movie",
        action="store_true",
        help="replace/create retained fixtures from one exact-MAME movie replay",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--port", type=int, default=7960)
    parser.add_argument(
        "--terminal-trap",
        action="store_true",
        help=(
            "temporarily replace the bounded virtual-68000 terminal with "
            "ILLEGAL and stop at op_illegal; use for an ordinary ROM that "
            "does not contain the PC-ring diagnostic terminal hook"
        ),
    )
    parser.add_argument(
        "--allow-rom-hash",
        action="store_true",
        help="allow non-campaign ROM hashes (provenance is still recorded)",
    )
    args = parser.parse_args()
    for path in (
        args.rom,
        args.diagnostic_rom,
        args.base_state,
        args.nexen,
        args.movie,
        args.summary,
        MAME,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.artifact_dir is None:
        args.artifact_dir = args.output.with_suffix("")
    if args.artifact_dir.resolve() == args.output.resolve():
        parser.error(
            "--output must name the JSON summary, not the artifact directory; "
            "use --artifact-dir for retained states/logs"
        )
    if args.artifact_dir.exists():
        parser.error(f"artifact directory already exists: {args.artifact_dir}")
    manifest = args.fixture_dir / "fixtures.json"
    if not args.capture_movie and not manifest.is_file():
        parser.error(
            f"missing {manifest}; run once with --capture-movie"
        )
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wait_for_nonempty_file(path: Path, timeout: float = 20.0) -> None:
    """Wait for Nexen's asynchronous save-state write before hashing it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for nonempty save state: {path}")


def be16(blob: bytes, offset: int) -> int:
    offset &= 0xFFFF
    return int.from_bytes(blob[offset : offset + 2], "big")


def json_regs(raw: dict[str, Any]) -> dict[str, int]:
    regs = {
        name: int(raw[name]) & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = int(raw["SP"]) & 0xFFFFFFFF
    return regs


def ranges(values: list[int]) -> list[str]:
    if not values:
        return []
    answer: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        answer.append(
            f"{start:06X}" if start == previous else f"{start:06X}-{previous:06X}"
        )
        start = previous = value
    answer.append(
        f"{start:06X}" if start == previous else f"{start:06X}-{previous:06X}"
    )
    return answer


def load_oracles(path: Path) -> list[StageOracle]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    lifetimes = raw.get("lifetimes", [])
    if len(lifetimes) < 3:
        raise RuntimeError(f"{path}: fewer than three boss lifetimes")
    expected_records = (0xF00A74, 0xF00A70, 0xF00A58)
    expected_health = (40, 40, 20)
    expected_hits = (13, 37, 6)
    log_path = Path(raw["source"])
    if not log_path.is_file():
        raise RuntimeError(f"{path}: missing source log {log_path}")
    damage_log: list[dict[str, int]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("DAMAGE "):
            continue
        fields = {
            key: value
            for key, value in (
                word.split("=", 1) for word in line.split()[1:]
            )
        }
        damage_log.append(
            {
                "frame": int(fields["frame"]),
                "record": int(fields["A0"], 16),
                "health": int(fields["health"], 16),
                "damage": int(fields["damage"], 16),
            }
        )
    answer: list[StageOracle] = []
    for index, item in enumerate(lifetimes[:3]):
        stage = index + 1
        record = int(item["record"], 16)
        initial = int(item["initial_health"])
        damages = tuple(int(value) for value in item["damage_values"])
        before = tuple(
            int(value) for value in item["health_before_each_damage"]
        )
        if (
            record != expected_records[index]
            or initial != expected_health[index]
            or len(damages) != expected_hits[index]
            or len(before) != len(damages)
            or not item.get("continuous_subtractions")
            or not item.get("terminal_nonpositive")
        ):
            raise RuntimeError(
                f"{path}: unexpected Stage {stage} boss oracle {item!r}"
            )
        running = initial
        for hit, (health, damage) in enumerate(
            zip(before, damages), 1
        ):
            if health != running:
                raise RuntimeError(
                    f"Stage {stage} hit {hit}: discontinuous health "
                    f"{health}, expected {running}"
                )
            running = (health - damage) & 0xFFFF
        matching_events = [
            event
            for event in damage_log
            if event["record"] == record
            and event["frame"] > int(item["init_frame"])
        ][: len(damages)]
        if [
            (event["health"], event["damage"]) for event in matching_events
        ] != list(zip(before, damages)):
            raise RuntimeError(
                f"Stage {stage}: source-log damage sequence does not match "
                "the summary"
            )
        answer.append(
            StageOracle(
                stage=stage,
                record=record,
                initial_health=initial,
                damage_values=damages,
                health_before=before,
                damage_frames=tuple(
                    event["frame"] for event in matching_events
                ),
                init_entry=0x014EB8 if stage == 1 else 0x014EBA,
                init_frame=int(item["init_frame"]),
            )
        )
    return answer


def make_specs(oracles: list[StageOracle]) -> list[CaseSpec]:
    specs: list[CaseSpec] = []
    for oracle in oracles:
        specs.append(
            CaseSpec(
                name=f"stage{oracle.stage}-init",
                stage=oracle.stage,
                kind="init",
                ordinal=0,
                entry=oracle.init_entry,
                terminal=INIT_TERMINAL,
                record=oracle.record,
                expected_before=-1,
                expected_after=oracle.initial_health,
                expected_damage=None,
                expected_frame=oracle.init_frame,
                retain_pre_state=True,
            )
        )
        last = len(oracle.damage_values)
        for ordinal, (before, damage) in enumerate(
            zip(oracle.health_before, oracle.damage_values), 1
        ):
            specs.append(
                CaseSpec(
                    name=f"stage{oracle.stage}-hit-{ordinal:02d}",
                    stage=oracle.stage,
                    kind="damage",
                    ordinal=ordinal,
                    entry=DAMAGE_ENTRY,
                    terminal=DAMAGE_TERMINAL,
                    record=oracle.record,
                    expected_before=before,
                    expected_after=(before - damage) & 0xFFFF,
                    expected_damage=damage,
                    expected_frame=oracle.damage_frames[ordinal - 1],
                    retain_pre_state=ordinal in (1, last),
                )
            )
    return specs


def case_to_json(case: Case, work_name: str) -> dict[str, Any]:
    return {
        "name": case.spec.name,
        "stage": case.spec.stage,
        "kind": case.spec.kind,
        "ordinal": case.spec.ordinal,
        "entry_pc": f"{case.spec.entry:06X}",
        "terminal_pc": f"{case.spec.terminal:06X}",
        "record": f"{case.spec.record:06X}",
        "expected_before": case.spec.expected_before,
        "expected_after": case.spec.expected_after,
        "expected_damage": case.spec.expected_damage,
        "frame": case.frame,
        "sr": case.sr,
        "regs": case.regs,
        "work_file": work_name,
        "work_sha256": hashlib.sha256(case.work).hexdigest(),
        "mame_state": case.mame_state,
    }


def validate_entry(case: Case) -> None:
    offset = case.spec.record & 0xFFFF
    before = be16(case.work, offset + 2)
    if case.spec.kind == "damage":
        if before != case.spec.expected_before:
            raise RuntimeError(
                f"{case.spec.name}: entry health {before}, "
                f"expected {case.spec.expected_before}"
            )
        damage = case.regs["D3"] & 0xFFFF
        if damage != case.spec.expected_damage:
            raise RuntimeError(
                f"{case.spec.name}: D3 damage {damage}, "
                f"expected {case.spec.expected_damage}"
            )


def capture_movie_fixtures(
    args: argparse.Namespace, specs: list[CaseSpec]
) -> list[Case]:
    args.fixture_dir.mkdir(parents=True, exist_ok=False)
    state_dir = args.fixture_dir / "mame-pre"
    state_dir.mkdir(parents=True)
    lua = ROOT / "tools/mame-trace/capture_boss_health_entries.lua"
    command = [
        str(MAME),
        "superman",
        "-rompath",
        str(MAME_ROMPATH),
        "-input_directory",
        str(args.movie.parent),
        "-playback",
        args.movie.name,
        "-video",
        "none",
        "-sound",
        "none",
        "-nothrottle",
        "-skip_gameinfo",
        "-autoboot_script",
        str(lua),
        "-autoboot_delay",
        "0",
        "-state_directory",
        str(state_dir),
        "-nvram_directory",
        str(args.fixture_dir / "nvram"),
        "-cfg_directory",
        str(args.fixture_dir / "cfg"),
    ]
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        BOSS_HEALTH_FIXTURE_DIR=str(args.fixture_dir.resolve()),
        BOSS_HEALTH_MAXF="60000",
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
        check=False,
    )
    (args.fixture_dir / "mame.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    (args.fixture_dir / "mame.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"MAME capture exited {completed.returncode}; see "
            f"{args.fixture_dir / 'mame.stderr.log'}"
        )

    capture_path = args.fixture_dir / "capture.jsonl"
    captured_events = [
        json.loads(line)
        for line in capture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summaries = [
        event for event in captured_events if event.get("event") == "summary"
    ]
    if len(summaries) != 3 or any(
        not event["initialized"]
        or event["hits"] != event["expected_hits"]
        for event in summaries
    ):
        raise RuntimeError(
            f"incomplete MAME boss capture: {summaries!r}"
        )
    by_name = {
        event["name"]: event
        for event in captured_events
        if "name" in event
    }

    retained_init = {
        1: EVIDENCE / "boss-first-boss-init-entry",
        2: EVIDENCE / "boss-stage2-boss-init-entry",
        3: EVIDENCE / "boss-stage3-boss-init-entry",
    }
    cases: list[Case] = []
    for spec in specs:
        event = by_name.get(spec.name)
        if event is None:
            raise RuntimeError(f"MAME capture omitted {spec.name}")
        if spec.kind == "init":
            stem = retained_init[spec.stage]
            metadata = json.loads(
                stem.with_suffix(".json").read_text(encoding="utf-8")
            )
            work = stem.with_suffix(".work.bin").read_bytes()
            if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
                raise RuntimeError(f"{stem}: retained init hash mismatch")
            regs = {
                name: int(metadata["regs"][name])
                for name in base.REG_NAMES
            }
            sr = int(metadata["sr"])
            frame = int(metadata["frame"])
        else:
            work = (args.fixture_dir / f"{spec.name}.work.bin").read_bytes()
            regs = {
                name: int(event[name]) for name in base.REG_NAMES
            }
            sr = int(event["SR"])
            frame = int(event["frame"])
            if int(event["old"]) != spec.expected_before:
                raise RuntimeError(
                    f"{spec.name}: write-tap old={event['old']}, "
                    f"expected {spec.expected_before}"
                )
            if int(event["new"]) != spec.expected_after:
                raise RuntimeError(
                    f"{spec.name}: write-tap new={event['new']}, "
                    f"expected {spec.expected_after}"
                )
            if int(event["PC"]) != 0x014CF0:
                raise RuntimeError(
                    f"{spec.name}: write callback PC=${event['PC']:06X}, "
                    "expected $014CF0"
                )
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(f"{spec.name}: short work-RAM fixture")
        case = Case(
            spec=spec,
            frame=frame,
            regs=regs,
            sr=sr,
            work=work,
            mame_state=(
                f"mame-pre/superman/{spec.name}-write-boundary.sta"
                if spec.retain_pre_state
                else None
            ),
        )
        validate_entry(case)
        cases.append(case)
        print(
            f"captured {spec.name}: frame={case.frame} "
            f"health={be16(case.work, (spec.record & 0xFFFF) + 2)}",
            flush=True,
        )

    manifest_cases: list[dict[str, Any]] = []
    for case in cases:
        work_name = f"{case.spec.name}.work.bin"
        (args.fixture_dir / work_name).write_bytes(case.work)
        manifest_cases.append(case_to_json(case, work_name))
    manifest = {
        "schema": 1,
        "created_unix": time.time(),
        "mame": mame_identity(),
        "mame_binary": str(MAME.resolve()),
        "movie": str(args.movie),
        "movie_sha256": sha256(args.movie),
        "source_summary": str(args.summary),
        "source_summary_sha256": sha256(args.summary),
        "capture_boundary": (
            "damage fixtures are synchronous pre-write work-RAM snapshots "
            "from the real main-boss health write tap; registers are sampled "
            "with PC=$014CF0 after the SUB write bus access and replayed from "
            "$014CEA; init fixtures are retained exact opcode-entry captures"
        ),
        "cases": manifest_cases,
    }
    (args.fixture_dir / "fixtures.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cases


def load_fixtures(
    directory: Path, specs: list[CaseSpec], movie: Path
) -> list[Case]:
    manifest_path = directory / "fixtures.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise RuntimeError(f"{manifest_path}: unsupported schema")
    if manifest.get("movie_sha256") != sha256(movie):
        raise RuntimeError(f"{manifest_path}: movie hash mismatch")
    raw_cases = manifest.get("cases", [])
    if len(raw_cases) != len(specs):
        raise RuntimeError(
            f"{manifest_path}: {len(raw_cases)} cases, expected {len(specs)}"
        )
    cases: list[Case] = []
    for spec, raw in zip(specs, raw_cases):
        if raw.get("name") != spec.name:
            raise RuntimeError(
                f"{manifest_path}: case order mismatch at {spec.name}"
            )
        work_path = directory / raw["work_file"]
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(f"{work_path}: expected 65536 bytes")
        if hashlib.sha256(work).hexdigest() != raw["work_sha256"]:
            raise RuntimeError(f"{work_path}: hash mismatch")
        regs = {name: int(raw["regs"][name]) for name in base.REG_NAMES}
        case = Case(
            spec=spec,
            frame=int(raw["frame"]),
            regs=regs,
            sr=int(raw["sr"]),
            work=work,
            mame_state=raw.get("mame_state"),
        )
        validate_entry(case)
        cases.append(case)
    return cases


def mame_span(session: MameSession, case: Case) -> Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", case.spec.entry)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.spec.terminal,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${case.spec.terminal:06X} for "
            f"{case.spec.name}: {captured!r}"
        )
    raw = captured["registers"]
    result = Result(
        regs=json_regs(raw),
        sr=int(raw["SR"]) & 0xFFFF,
        work=bytes.fromhex(captured["hex"]),
    )
    observed = be16(
        result.work, (case.spec.record & 0xFFFF) + 2
    )
    if observed != case.spec.expected_after:
        raise RuntimeError(
            f"{case.spec.name}: MAME health {observed}, "
            f"expected {case.spec.expected_after}"
        )
    return result


def organic_damage_result(case: Case) -> Result:
    """Materialize MAME's exact architectural state after the health write.

    The fixture work dump is synchronous and precedes the real SUB.W bus
    write.  MAME's registers and SR in that callback are already the
    architectural post-SUB state at PC $014CF0.  Applying only the tapped
    health word therefore gives a non-speculative result at the next 68000 PC,
    $014CEE.
    """

    if case.spec.kind != "damage":
        raise ValueError(case.spec.name)
    work = bytearray(case.work[:MAPPED_WORK_SIZE])
    offset = (case.spec.record & 0xFFFF) + 2
    work[offset : offset + 2] = case.spec.expected_after.to_bytes(2, "big")
    return Result(
        regs=dict(case.regs),
        sr=(case.sr & ~0x0700) | 0x0700,
        work=bytes(work),
    )


def write_dp16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def read_dp16(m: McpSession, address: int) -> int:
    return int(m.read_u16(address, base.DP_SPACE))


def prepare_flags(m: McpSession, sr: int) -> None:
    flags = sr & base.CCR_MASK
    write_dp16(m, 0x6E, flags & 1)
    write_dp16(m, 0x72, (flags >> 1) & 1)
    write_dp16(m, 0x60, (flags >> 2) & 1)
    write_dp16(m, 0x70, (flags >> 3) & 1)
    write_dp16(m, 0xA2, (flags >> 4) & 1)
    write_dp16(m, 0x7C, 7)


def write_mode(m: McpSession, mode: str) -> dict[str, int]:
    if mode == "all-native-off":
        values = {
            "071A": 0,
            "0734": 0,
            "0736": 0,
            "073A": 0,
            "073C": 0,
        }
    elif mode == "production-on":
        values = {
            "071A": 1,
            "0734": 1,
            "0736": 0x5EEC,
            "073A": 1,
            "073C": 0xA55A,
        }
    else:
        raise ValueError(mode)
    for address, value in values.items():
        write_dp16(m, int(address, 16), value)
    return values


def captured_regs(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    return {
        name: int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }


def captured_ccr(m: McpSession) -> int:
    return (
        (1 if read_dp16(m, 0x6E) else 0)
        | ((1 if read_dp16(m, 0x72) else 0) << 1)
        | ((1 if read_dp16(m, 0x60) else 0) << 2)
        | ((1 if read_dp16(m, 0x70) else 0) << 3)
        | ((1 if read_dp16(m, 0xA2) else 0) << 4)
    )


def nexen_span(
    m: McpSession,
    args: argparse.Namespace,
    case: Case,
    mode: str,
) -> tuple[Result, dict[str, int], dict[str, Any] | None]:
    m.load_state(str(args.base_state))
    m.pause()
    reg_blob = b"".join(
        base.le32(case.regs[name]) for name in base.REG_NAMES
    )
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(m)
    prepare_flags(m, case.sr)
    write_dp16(m, 0x40, case.spec.entry & 0xFFFF)
    write_dp16(m, 0x42, (case.spec.entry >> 16) & 0xFF)
    write_dp16(m, 0x4A, 0)
    write_dp16(m, 0x4C, 0)
    write_dp16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    write_dp16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_dp16(m, 0xA8, 1)
    write_dp16(m, 0xAA, 0)
    write_dp16(m, 0xAC, 0x7000)
    write_dp16(m, 0x0702, 0)
    write_dp16(m, 0x0704, 1)
    write_dp16(m, 0x0710, case.spec.terminal & 0xFFFF)
    write_dp16(m, 0x0712, 0)
    write_dp16(m, 0x0714, 0)
    write_dp16(m, 0x0716, (case.spec.terminal >> 16) & 0xFF)
    write_dp16(m, 0x0718, 0xFFF8)
    write_dp16(m, 0x072E, 0)
    write_dp16(m, 0x0730, 0)
    write_dp16(m, 0x0738, 0)
    gates = write_mode(m, mode)

    pre_state: dict[str, Any] | None = None
    if case.spec.retain_pre_state:
        target = (
            args.artifact_dir
            / "nexen-pre"
            / mode
            / f"{case.spec.name}.mss"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        response = m.save_state(target.resolve())
        wait_for_nonempty_file(target)
        pre_state = {
            "path": str(target),
            "response": response,
            "size": target.stat().st_size,
            "sha256": sha256(target),
        }

    patches: list[tuple[int, bytes]] = []
    hook_pc = DEBUG_SPIN
    if args.terminal_trap:
        # The ordinary pack deliberately omits the PC-ring diagnostic gateway
        # at DEBUG_SPIN.  Make the immutable source word at this bounded
        # terminal ILLEGAL instead, then park its SA-1 handler.  This is the
        # same reversible terminal technique used by the ordinary-enemy
        # three-way validator; it changes neither the start state nor any
        # completed 68000 instruction in the span.
        terminal_offset = 0x10000 + case.spec.terminal
        illegal_offset = OP_ILLEGAL - 0x8000
        terminal_original = bytes(
            m.read_memory("snesPrgRom", terminal_offset, 2)
        )
        illegal_original = bytes(
            m.read_memory("snesPrgRom", illegal_offset, 2)
        )
        patches.extend(
            ((terminal_offset, terminal_original), (illegal_offset, illegal_original))
        )
        m.write_memory("snesPrgRom", terminal_offset, "4afc")
        m.write_memory("snesPrgRom", illegal_offset, "80fe")
        hook_pc = OP_ILLEGAL

    hook = m.add_exec_hook(hook_pc, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, INEXT)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=24, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
        for offset, original in patches:
            m.write_memory("snesPrgRom", offset, original.hex())
    if (hit or {}).get("reason") != "hookFired":
        observed = read_dp16(m, 0x40) | (
            (read_dp16(m, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen did not freeze for {case.spec.name}, {mode}: "
            f"{hit!r}; 68K PC=${observed:06X}"
        )
    observed = read_dp16(m, 0x40) | (
        (read_dp16(m, 0x42) & 0xFF) << 16
    )
    terminal_seen = (
        observed == case.spec.terminal
        if args.terminal_trap
        else bool(read_dp16(m, 0x0712)) and observed == case.spec.terminal
    )
    if not terminal_seen:
        raise RuntimeError(
            f"Nexen froze at ${observed:06X}, expected "
            f"${case.spec.terminal:06X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    return (
        Result(
            regs=captured_regs(m),
            sr=0x2000 | (7 << 8) | captured_ccr(m),
            work=bytes(
                m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)
            ),
            cycles=end_cycles - start_cycles,
        ),
        gates,
        pre_state,
    )


def work_slice(blob: bytes, address: int, radius: int) -> dict[str, Any]:
    offset = address & 0xFFFF
    start = max(0, offset - radius)
    end = min(len(blob), offset + radius)
    raw = blob[start:end]
    return {
        "address": f"F0{start:04X}",
        "length": len(raw),
        "hex": raw.hex().upper(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def context(result: Result, case: Case) -> dict[str, Any]:
    a7 = result.regs["A7"] & 0xFFFF
    return {
        "boss_object": work_slice(result.work, case.spec.record, 0x40),
        "collision_record": work_slice(
            result.work, result.regs["A2"] & 0xFFFF, 0x20
        ),
        "stack": work_slice(result.work, a7, 0x20),
        "task_mask_f00002": be16(result.work, 0x0002),
        "game_tick_f01c56": be16(result.work, 0x1C56),
    }


def compare(
    case: Case,
    arcade: Result,
    console: Result,
    mode: str,
    gates: dict[str, int],
    pre_state: dict[str, Any] | None,
) -> dict[str, Any]:
    reg_mismatches = {
        name: {
            "mame": f"{arcade.regs[name]:08X}",
            "nexen": f"{console.regs[name]:08X}",
        }
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mask_mismatch = (arcade.sr & 0x071F) != (console.sr & 0x071F)
    health_offset = (case.spec.record & 0xFFFF) + 2
    green = not reg_mismatches and not ccr_mask_mismatch and not work_mismatches
    return {
        "event": "case",
        "case": case.spec.name,
        "stage": case.spec.stage,
        "kind": case.spec.kind,
        "hit_ordinal": case.spec.ordinal,
        "movie_frame": case.frame,
        "entry_pc": f"{case.spec.entry:06X}",
        "terminal_pc": f"{case.spec.terminal:06X}",
        "boss_record": f"{case.spec.record:06X}",
        "mode": mode,
        "gates": gates,
        "result": "green" if green else "red",
        "classification": (
            "arcade_exact"
            if green
            else (
                "native_hle"
                if mode == "production-on"
                else "interpreter_or_hardware_boundary"
            )
        ),
        "health_before": be16(case.work, health_offset),
        "expected_damage": case.spec.expected_damage,
        "expected_health_after": case.spec.expected_after,
        "mame_health_after": be16(arcade.work, health_offset),
        "nexen_health_after": be16(console.work, health_offset),
        "reg_mismatches": reg_mismatches,
        "mame_ccr_xnzvc_and_mask": arcade.sr & 0x071F,
        "nexen_ccr_xnzvc_and_mask": console.sr & 0x071F,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:32]
        ],
        "mame_context": context(arcade, case),
        "nexen_context": context(console, case),
        "nexen_cycles": console.cycles,
        "pre_state": pre_state,
        "irq_scope": (
            "68000 interrupt mask forced to 7 in both bounded spans; no IRQ "
            "cadence claim; task/tick words remain within the exact RAM gate"
        ),
    }


def main() -> int:
    args = parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    production_hash = sha256(args.rom)
    diagnostic_hash = sha256(args.diagnostic_rom)
    # A terminal-trap run deliberately uses the current ordinary ROM.  The
    # trap replaces only the fetched terminal opcode during the bounded span,
    # so requiring an older PC-ring diagnostic image would test the wrong
    # production candidate.
    nexen_rom = args.rom if args.terminal_trap else args.diagnostic_rom
    nexen_hash = sha256(nexen_rom)
    if not args.allow_rom_hash:
        if production_hash != EXPECTED_PRODUCTION_SHA256:
            raise RuntimeError(
                f"production ROM is {production_hash}, expected "
                f"{EXPECTED_PRODUCTION_SHA256}"
            )
        if (
            not args.terminal_trap
            and diagnostic_hash != EXPECTED_DIAGNOSTIC_SHA256
        ):
            raise RuntimeError(
                f"diagnostic ROM is {diagnostic_hash}, expected "
                f"{EXPECTED_DIAGNOSTIC_SHA256}"
            )
    production = args.rom.read_bytes()
    diagnostic = args.diagnostic_rom.read_bytes()
    if len(production) != len(diagnostic):
        raise RuntimeError("production and diagnostic ROM sizes differ")
    diff_offsets = [
        offset
        for offset, (left, right) in enumerate(zip(production, diagnostic))
        if left != right
    ]

    oracles = load_oracles(args.summary)
    specs = make_specs(oracles)
    if args.capture_movie:
        cases = capture_movie_fixtures(args, specs)
    else:
        cases = load_fixtures(args.fixture_dir, specs, args.movie)

    args.artifact_dir.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "time_unix": time.time(),
            "mame": str(MAME.resolve()),
            "mame_version": mame_oracle["version"],
            "mame_sha256": mame_oracle["sha256"],
            "mame_snap_revision": mame_oracle["snap_revision"],
            "mame_gnome_content_revision": (
                mame_oracle["gnome_content_revision"]
            ),
            "nexen": str(args.nexen),
            "production_rom": str(args.rom),
            "production_rom_sha256": production_hash,
            "diagnostic_rom": str(args.diagnostic_rom),
            "diagnostic_rom_sha256": diagnostic_hash,
            "nexen_test_rom": str(nexen_rom),
            "nexen_test_rom_sha256": nexen_hash,
            "diagnostic_difference_byte_count": len(diff_offsets),
            "diagnostic_difference_ranges": ranges(diff_offsets),
            "base_state": str(args.base_state),
            "base_state_sha256": sha256(args.base_state),
            "movie": str(args.movie),
            "movie_sha256": sha256(args.movie),
            "fixture_dir": str(args.fixture_dir),
            "fixture_manifest_sha256": sha256(
                args.fixture_dir / "fixtures.json"
            ),
            "summary": str(args.summary),
            "summary_sha256": sha256(args.summary),
            "case_count": len(cases),
            "damage_terminal": (
                "synchronous MAME post-SUB health-write state compared with "
                "Nexen frozen at the next 68000 PC $014CEE"
            ),
            "nexen_terminal_capture": (
                "reversible virtual-terminal ILLEGAL/op_illegal trap"
                if args.terminal_trap
                else "PC-ring diagnostic DEBUG_SPIN hook"
            ),
            "isolation": (
                "interrupt mask forced to 7 in MAME and Nexen bounded spans"
            ),
        }
    ]
    for oracle in oracles:
        events.append(
            {
                "event": "arcade_sequence",
                "stage": oracle.stage,
                "record": f"{oracle.record:06X}",
                "initial_health": oracle.initial_health,
                "hit_count": len(oracle.damage_values),
                "damage_values": list(oracle.damage_values),
                "health_before_each_damage": list(oracle.health_before),
                "terminal_nonpositive": (
                    oracle.health_before[-1] <= oracle.damage_values[-1]
                ),
            }
        )

    arcade: dict[str, Result] = {}
    for index, case in enumerate(cases, 1):
        if case.spec.kind == "damage":
            arcade[case.spec.name] = organic_damage_result(case)
            print(
                f"MAME {index:02d}/{len(cases)} {case.spec.name} "
                "(organic health-write tap)",
                flush=True,
            )
            continue
        # The bridge's opcode-prefetch terminal tap can remain satisfied by
        # MAME's prefetch/cache state after several synthetic PC injections.
        # A fresh process per retained case makes the terminal trap independent.
        oracle = MameSession(
            mame=str(MAME),
            system="superman",
            rompath=str(MAME_ROMPATH),
            workdir=str(MAME_WORKDIR),
            state_directory=str(args.artifact_dir / "mame-oracle"),
            extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
        )
        try:
            oracle.launch(boot_wait=25)
            arcade[case.spec.name] = mame_span(oracle, case)
        finally:
            oracle.stop()
        print(
            f"MAME {index:02d}/{len(cases)} {case.spec.name}",
            flush=True,
        )

    with McpSession(
        rom=str(nexen_rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.artifact_dir / "nexen.stderr.log",
    ) as nexen:
        total = len(cases) * 2
        completed = 0
        for case in cases:
            for mode in ("all-native-off", "production-on"):
                result, gates, pre_state = nexen_span(
                    nexen, args, case, mode
                )
                events.append(
                    compare(
                        case,
                        arcade[case.spec.name],
                        result,
                        mode,
                        gates,
                        pre_state,
                    )
                )
                completed += 1
                print(
                    f"Nexen {completed:03d}/{total} "
                    f"{case.spec.name} {mode}",
                    flush=True,
                )

    case_events = [event for event in events if event["event"] == "case"]
    stage_summaries: list[dict[str, Any]] = []
    for oracle_data in oracles:
        selected = [
            event
            for event in case_events
            if event["stage"] == oracle_data.stage
        ]
        stage_summaries.append(
            {
                "event": "stage_summary",
                "stage": oracle_data.stage,
                "result": (
                    "green"
                    if selected
                    and all(event["result"] == "green" for event in selected)
                    else "red"
                ),
                "initial_health": oracle_data.initial_health,
                "arcade_hit_count": len(oracle_data.damage_values),
                "damage_values": list(oracle_data.damage_values),
                "differential_case_count": len(selected),
                "modes": ["all-native-off", "production-on"],
                "scope": (
                    "exact bounded replay of organic MAME init and every "
                    "damage-handler entry; not continuous organic SNES battle"
                ),
            }
        )
    events.extend(stage_summaries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    green = all(event["result"] == "green" for event in case_events)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cases": len(case_events),
                "green": sum(
                    event["result"] == "green" for event in case_events
                ),
                "red": sum(
                    event["result"] != "green" for event in case_events
                ),
                "stage_summaries": stage_summaries,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if green and all(
        item["result"] == "green" for item in stage_summaries
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
