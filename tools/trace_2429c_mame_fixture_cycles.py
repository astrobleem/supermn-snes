#!/usr/bin/env python3
"""Record original-MAME instruction timing for controlled `$02429C` arms.

The cold controller movie is the only authority for organic gameplay timing,
but it repeatedly exercises the empty `$02429C` route.  This companion starts
from the retained, explicitly mutated pre-entry fixtures used by the exact
function differential and records the original M68000 instruction stream to
the coroutine's terminal Trap #5.  It masks an unrelated held IRQ6 and changes
only that terminal Trap fetch to NOP so the fixture has a finite observation
boundary.

The result is a bounded original-code cycle oracle for otherwise unvisited
root/child branches.  It is not fresh boot, organic play, a SNES comparison,
or rate evidence.  It must be combined with the real controller trace and
separate MAME/native-off/native-on state differentials before any repair can
be accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import validate_2429c_native as root
import validate_mame_25110_branch_timing as trace_common
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "build/gen-2429c-distinct-arm-fixtures-current-5c7e-v1"
ENTRY_PC = root.ENTRY_PC
TERMINAL_PC = root.EXIT_PC
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_CFG = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
CAPTURE_LUA = MAME_TRACE / "capture_2429c_fixture_cycles.lua"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_metadata(fixture_dir: Path, case: Any) -> Path:
    """Locate and authenticate the exact retained metadata for one work image."""

    work_hash = hashlib.sha256(case.work).hexdigest()
    for path in sorted(fixture_dir.glob("case-*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("name") != case.name:
            continue
        if row.get("work_sha256") != work_hash:
            raise RuntimeError(f"{case.name}: metadata work hash does not match loaded fixture")
        return path
    raise RuntimeError(f"missing retained metadata for fixture {case.name}")


def trace_case(
    oracle: dict[str, str],
    fixture_dir: Path,
    case: Any,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    case_dir = output / case.name
    trace = case_dir / "m68k.log"
    meta = case_dir / "meta.json"
    work = fixture_metadata(fixture_dir, case).with_suffix(".work.bin")
    metadata = fixture_metadata(fixture_dir, case)
    cfg = case_dir / "cfg"
    nvram = case_dir / "nvram"
    states = case_dir / "states"
    for directory in (case_dir, cfg, nvram, states):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MAME_CFG, cfg / MAME_CFG.name)
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        FIXTURE_M68K_WORK=str(work.resolve()),
        FIXTURE_TRACE_OUT=str(trace.resolve()),
        FIXTURE_META_OUT=str(meta.resolve()),
        FIXTURE_MAX_FRAMES="120",
        FIXTURE_SR=f"{(case.sr | 0x0700) & 0xFFFF:X}",
        **{
            f"FIXTURE_D{index}": f"{case.regs[f'D{index}'] & 0xFFFFFFFF:X}"
            for index in range(8)
        },
        **{
            f"FIXTURE_A{index}": f"{case.regs[f'A{index}'] & 0xFFFFFFFF:X}"
            for index in range(7)
        },
        FIXTURE_A7=f"{case.regs['A7'] & 0xFFFFFFFF:X}",
    )
    command = [
        str(MAME), "superman", "-rompath", str(MAME_TRACE / "roms"),
        "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo",
        "-debug", "-debugger", "none", "-autoboot_script", str(CAPTURE_LUA),
        "-autoboot_delay", "0", "-state_directory", str(states),
        "-nvram_directory", str(nvram), "-cfg_directory", str(cfg),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        check=False,
    )
    (case_dir / "mame.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (case_dir / "mame.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"{case.name}: MAME exited {completed.returncode}; see {case_dir / 'mame.stderr.log'}")
    if not meta.is_file():
        raise RuntimeError(f"{case.name}: MAME did not write a finite-capture result")
    terminal = json.loads(meta.read_text(encoding="utf-8"))
    terminal_hits = int(terminal.get("terminal_hits", 0))
    if terminal.get("reason") != "terminal":
        raise RuntimeError(f"{case.name}: terminal was not reached: {terminal}")
    if terminal_hits != 1:
        raise RuntimeError(f"{case.name}: expected one terminal hit, got {terminal_hits}")
    if not trace.is_file() or not trace.stat().st_size:
        raise RuntimeError(f"{case.name}: debugger trace was not created")
    records = trace_common.parse_trace(trace)
    if records[0]["pc"] != ENTRY_PC:
        raise RuntimeError(
            f"{case.name}: trace begins at ${records[0]['pc']:06X}, not root ${ENTRY_PC:06X}"
        )
    if sum(item["pc"] == ENTRY_PC for item in records) != 1:
        raise RuntimeError(f"{case.name}: terminal boundary allowed multiple root entries")
    root_dynamic = {
        f"{pc:06X}": sum(item["pc"] == pc for item in records)
        for pc in sorted(trace_common_root_dynamic_pcs())
        if any(item["pc"] == pc for item in records)
    }
    child_dynamic = {
        f"{pc:06X}": sum(item["pc"] == pc for item in records)
        for pc in sorted(trace_common_child_dynamic_pcs())
        if any(item["pc"] == pc for item in records)
    }
    summary = {
        "scope": (
            "IRQ-masked controlled original-MAME `$02429C` fixture trace; "
            "explicit pre-entry work-RAM mutations and a terminal Trap-fetch NOP; "
            "not organic gameplay, SNES comparison, rate, or acceptance"
        ),
        "runtime_architectural_mutations": [
            {
                "kind": "fixture_work_ram",
                "source": str(metadata.resolve()),
                "meaning": "only documented synthetic pre-entry work-RAM fields",
            },
            {
                "kind": "MAME_read_tap",
                "address": f"{TERMINAL_PC:06X}",
                "value": "4E71",
                "meaning": "replace only terminal Trap #5 fetch to make one bounded observation",
            },
            {
                "kind": "entry_SR_mask",
                "value": "0700",
                "meaning": "mask unrelated held IRQ6; do not infer cadence from this span",
            },
        ],
        "mame": oracle,
        "fixture": {
            "name": case.name,
            "tick": case.tick,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
            "metadata": str(metadata.resolve()),
            "metadata_sha256": sha256(metadata),
        },
        "entry_pc": f"{ENTRY_PC:06X}",
        "terminal_pc": f"{TERMINAL_PC:06X}",
        "capture": {
            "debugger_trace": {"path": str(trace.resolve()), "sha256": sha256(trace)},
            "meta": {"path": str(meta.resolve()), "sha256": sha256(meta)},
            "terminal_hits": terminal_hits,
            "register_trace_records": len(records),
            "first_pc": f"{records[0]['pc']:06X}",
            "last_pc": f"{records[-1]['pc']:06X}",
            "cycle_span": records[-1]["cycle"] - records[0]["cycle"],
            "observed_root_dynamic_pcs": root_dynamic,
            "observed_native_child_dynamic_pcs": child_dynamic,
        },
    }
    summary_path = case_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "case": case.name,
        "summary": str(summary_path.resolve()),
        "summary_sha256": sha256(summary_path),
        "records": len(records),
        "root_dynamic": root_dynamic,
        "child_dynamic": child_dynamic,
    }


def trace_common_root_dynamic_pcs() -> frozenset[int]:
    # Keep the fixture record directly consumable by the same branch reducer
    # used for the original controller trace.
    import validate_mame_2429c_branch_timing as branch

    return branch.ROOT_DYNAMIC_PCS


def trace_common_child_dynamic_pcs() -> frozenset[int]:
    import validate_mame_2429c_native_child_timing as child

    return frozenset(child.child_dynamic_pcs())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--cases", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if args.timeout <= 0 or args.cases < 1:
        parser.error("--timeout and --cases must be positive")
    if any(char.isspace() for char in str(args.output.resolve())):
        parser.error("--output cannot contain whitespace because MAME debugger trace paths are unquoted")
    if not args.fixtures.is_dir():
        parser.error(f"missing fixtures: {args.fixtures}")
    for path in (MAME_CFG, CAPTURE_LUA):
        if not path.is_file():
            parser.error(f"missing MAME fixture-capture input: {path}")
    return args


def main() -> int:
    args = parse_args()
    oracle = mame_identity()
    os.environ.update(mame_environment())
    cases = root.load_cases(args.fixtures, args.cases)
    args.output.mkdir(parents=True)
    rows = [trace_case(oracle, args.fixtures, case, args.output, args.timeout) for case in cases]
    manifest = {
        "scope": (
            "bounded original-MAME cycle traces for retained controlled `$02429C` "
            "fixtures; not organic gameplay, a SNES differential, rate, or acceptance"
        ),
        "mame": oracle,
        "fixtures": str(args.fixtures.resolve()),
        "cases": rows,
        "result": "green",
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "green", "cases": len(rows), "manifest": str(manifest_path.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
