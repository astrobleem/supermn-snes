#!/usr/bin/env python3
"""Three-way ordinary-enemy damage regression.

The retained fixtures enter the original damage-dispatch code at $01E9DA.
Each exact register/work-RAM state is replayed in:

* MAME 0.287 running the original 68000 code;
* Nexen with every native gate disabled; and
* Nexen with the production native gates enabled.

The bounded span ends immediately before $01EAE0.  That point is after the
health write and damage-specific response setup but before a common flag-dead
tail.  Every D/A register, A7/stack residue, mapped 16 KiB of work RAM, and
the relevant CCR/X state are compared.  Nexen also checks upper-backing
conservation, AC-charge equality, and a clear halt word.
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
import validate_stage3_hot_handlers as stage3
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT / "build/playtest-investigation-20260725"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = base.DEFAULT_NEXEN
DEFAULT_NAT = base.DEFAULT_NAT
ENTRY_PC = 0x01E9DA
TERMINAL_PC = 0x01EAE0
INEXT = 0x00D128
OP_ILLEGAL = 0x00CDED
CCR_MASK = 0x1F
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000


@dataclass(frozen=True)
class Fixture:
    name: str
    label: str
    source: str
    source_state: Path
    source_state_sha256: str
    regs: dict[str, int]
    sr: int
    work: bytes
    target: int
    hp_before: int
    damage: int
    collision_type: int
    buttons: int | None
    player_action: int | None


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    upper: bytes | None
    ac: int | None
    cycles: int | None
    halt: int
    observed_pc: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_address(path: Path, bank: int, label: str) -> int:
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == label:
            return (bank << 16) | (int(fields[0].split(":")[-1], 16) & 0xFFFF)
    raise RuntimeError(f"{path}: missing symbol {label}")


def program_file_offset(address: int) -> int:
    bank = (address >> 16) & 0xFF
    offset = address & 0xFFFF
    if not 0x94 <= bank <= 0x9F or offset < 0x8000:
        raise ValueError(f"unsupported packed program address ${address:06X}")
    return 0x2A0000 + (bank - 0x94) * 0x8000 + (offset & 0x7FFF)


def patterned_upper(index: int) -> bytes:
    return bytes(
        ((offset * 37 + index * 53 + 0xA5) & 0xFF)
        for offset in range(FULL_WORK_SIZE - MAPPED_WORK_SIZE)
    )


def load_fixtures(evidence: Path) -> list[Fixture]:
    selected_dir = evidence / "ordinary-enemy-selected-fixtures-v1"
    selected_manifest = json.loads(
        (selected_dir / "manifest.json").read_text(encoding="utf-8")
    )
    fixtures: list[Fixture] = []
    for raw in selected_manifest["fixtures"]:
        fixture_name = str(raw["name"])
        work_path = evidence / raw["work_file"]
        source_state = evidence / raw["mame_state_file"]
        work = work_path.read_bytes()
        if len(work) != MAPPED_WORK_SIZE:
            raise RuntimeError(f"{work_path}: expected 16 KiB")
        if sha256(work_path) != raw["work_sha256"]:
            raise RuntimeError(f"{work_path}: hash mismatch")
        if sha256(source_state) != raw["mame_state_sha256"]:
            raise RuntimeError(f"{source_state}: hash mismatch")
        target = int(raw["target_pointer"], 16)
        hp_offset = (target & 0xFFFF) + 3
        if work[hp_offset] != int(raw["target_hp_before"]):
            raise RuntimeError(f"{raw['name']}: retained HP does not match")
        fixtures.append(
            Fixture(
                # The retained fixture predates the corrected control vocabulary
                # and is immutably named ``jump-stage3``.  Button 2 is a kick;
                # keep the source name for provenance but never present it as a
                # gameplay action.
                name=fixture_name,
                label=(
                    "kick attack (Button 2)"
                    if fixture_name == "jump-stage3"
                    else str(raw["label"])
                ),
                source="controller-driven MAME input playback",
                source_state=source_state,
                source_state_sha256=str(raw["mame_state_sha256"]),
                regs={
                    name: int(raw["regs"][name]) & 0xFFFFFFFF
                    for name in base.REG_NAMES
                },
                sr=int(raw["sr"]) & 0xFFFF,
                work=work,
                target=target,
                hp_before=int(raw["target_hp_before"]),
                damage=int(raw["damage"]),
                collision_type=int(raw["collision_type"]),
                buttons=int(raw["buttons"]),
                player_action=int(raw["player_action"]),
            )
        )

    charged_dir = evidence / "charged-projectile-enemy-oracle-v1"
    charged_manifest = json.loads(
        (charged_dir / "manifest.json").read_text(encoding="utf-8")
    )
    damage = charged_manifest["damage_dispatch"]
    work_path = charged_dir / damage["work"]["path"]
    source_state = charged_dir / charged_manifest["pre_hit_state"]["path"]
    work = work_path.read_bytes()
    if len(work) != MAPPED_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected 16 KiB")
    if sha256(work_path) != damage["work"]["sha256"]:
        raise RuntimeError(f"{work_path}: hash mismatch")
    if sha256(source_state) != charged_manifest["pre_hit_state"]["sha256"]:
        raise RuntimeError(f"{source_state}: hash mismatch")
    target = int(damage["target"]["address"], 16)
    hp_before = int(damage["target"]["hp_byte"])
    hp_offset = (target & 0xFFFF) + 3
    if work[hp_offset] != hp_before:
        raise RuntimeError("charged-projectile retained HP does not match")
    fixtures.append(
        Fixture(
            name="charged-projectile",
            label="charged projectile",
            source=charged_manifest["scope"],
            source_state=source_state,
            source_state_sha256=charged_manifest["pre_hit_state"]["sha256"],
            regs={
                name: int(damage["registers"][name]) & 0xFFFFFFFF
                for name in base.REG_NAMES
            },
            sr=int(damage["sr"]) & 0xFFFF,
            work=work,
            target=target,
            hp_before=hp_before,
            damage=int(damage["a3_charged_collision"]["damage_byte"]),
            collision_type=int(damage["registers"]["D7"]) & 0xFF,
            buttons=None,
            player_action=int(damage["player"]["action"]),
        )
    )
    return fixtures


def install_mame_spin(session: base.MameSession) -> None:
    session.exec_lua(
        "if MCP_DAMAGE_TERMINAL_SPIN then "
        "MCP_DAMAGE_TERMINAL_SPIN:remove() end "
        "MCP_DAMAGE_TERMINAL_SPIN = "
        "machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{TERMINAL_PC:06X}, "
        f"0x{TERMINAL_PC + 1:06X}, 'mcp_damage_terminal_spin', "
        "function(offset, data, mask) return 0x60FE end); return true"
    )


def remove_mame_spin(session: base.MameSession) -> None:
    session.exec_lua(
        "if MCP_DAMAGE_TERMINAL_SPIN then "
        "MCP_DAMAGE_TERMINAL_SPIN:remove(); "
        "MCP_DAMAGE_TERMINAL_SPIN=nil end; return true"
    )


def mame_result(session: base.MameSession, fixture: Fixture) -> Result:
    session.pause()
    session.write_block(0xF00000, fixture.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, fixture.regs[name])
    entry_sp = fixture.regs["A7"] & 0xFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", fixture.sr | 0x0700)
    session.set_reg("PC", ENTRY_PC)
    install_mame_spin(session)
    try:
        captured = session.cmd(
            "capture_at_pc",
            pc=TERMINAL_PC,
            addr=0xF00000,
            len=MAPPED_WORK_SIZE,
            nth=2,
            exp_sp=entry_sp,
            maxFrames=180,
            timeout=180,
        )
    finally:
        remove_mame_spin(session)
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach terminal for {fixture.name}: {captured!r}"
        )
    raw = captured["registers"]
    regs = {
        name: int(raw[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = int(raw["SP"]) & 0xFFFFFFFF
    physical_sr = int(raw["SR"]) & 0xFFFF
    return Result(
        regs=regs,
        sr=(
            (fixture.sr & ~(CCR_MASK | 0x0700))
            | 0x0700
            | (physical_sr & CCR_MASK)
        ),
        work=bytes.fromhex(captured["hex"]),
        upper=None,
        ac=None,
        cycles=None,
        halt=0,
        observed_pc=int(raw["CURPC"]) & 0xFFFFFF,
    )


def console_result(
    session: base.McpSession,
    nat: Path,
    fixture: Fixture,
    fixture_index: int,
    native_gate: int,
    native_entry: int,
    native_terminal: int,
) -> Result:
    upper = patterned_upper(fixture_index)
    stage_fixture = stage3.Fixture(
        name=fixture.name,
        target=ENTRY_PC,
        return_pc=TERMINAL_PC,
        regs=fixture.regs,
        sr=fixture.sr,
        work=fixture.work + upper,
        tick=0,
        frame=0,
        state=0,
        substate=0,
        metadata_path=fixture.source_state,
        pre_entry_state=fixture.source_state,
        prestate_kind="mame_save_state_fixture",
    )
    stage3.prepare_console(session, nat, stage_fixture, native_gate)
    start_pc: int
    hook_pc: int
    patches: list[tuple[int, bytes]] = []
    if native_gate:
        start_pc = native_entry
        hook_pc = native_terminal
        terminal_offset = program_file_offset(native_terminal)
        original = bytes(
            session.read_memory("snesPrgRom", terminal_offset, 2)
        )
        patches.append((terminal_offset, original))
        session.write_memory("snesPrgRom", terminal_offset, "80fe")
    else:
        start_pc = INEXT
        hook_pc = OP_ILLEGAL
        terminal_offset = 0x10000 + TERMINAL_PC
        illegal_offset = OP_ILLEGAL - 0x8000
        terminal_original = bytes(
            session.read_memory("snesPrgRom", terminal_offset, 2)
        )
        illegal_original = bytes(
            session.read_memory("snesPrgRom", illegal_offset, 2)
        )
        patches.extend(
            (
                (terminal_offset, terminal_original),
                (illegal_offset, illegal_original),
            )
        )
        session.write_memory("snesPrgRom", terminal_offset, "4afc")
        session.write_memory("snesPrgRom", illegal_offset, "80fe")

    hook = session.add_exec_hook(hook_pc, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, start_pc)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, _frames = live.run_to_hook(session, hook, attempts=24)
        session.pause()
    finally:
        session.remove_hook(hook)
        for offset, original in patches:
            session.write_memory("snesPrgRom", offset, original.hex())
    if (hit or {}).get("reason") != "hookFired":
        sa1 = session.get_cpu_state("Sa1")
        logical_pc = live.read_u16(session, 0x40) | (
            (live.read_u16(session, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"{fixture.name} gate={native_gate} missed terminal; "
            f"logical=${logical_pc:06X}, "
            f"SA-1=${int(sa1.get('k', 0)) & 0xFF:02X}:"
            f"{int(sa1.get('pc', 0)) & 0xFFFF:04X}"
        )
    observed_pc = (
        native_terminal
        if native_gate
        else live.read_u16(session, 0x40)
        | ((live.read_u16(session, 0x42) & 0xFF) << 16)
    )
    if observed_pc != (native_terminal if native_gate else TERMINAL_PC):
        raise RuntimeError(
            f"{fixture.name} gate={native_gate} stopped at "
            f"${observed_pc:06X}"
        )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    full_work = bytes(
        session.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
    )
    return Result(
        regs=live.captured_regs(session),
        sr=(
            (fixture.sr & ~(CCR_MASK | 0x0700))
            | ((live.read_u16(session, 0x7C) & 7) << 8)
            | live.captured_ccr(session)
        ),
        work=full_work[:MAPPED_WORK_SIZE],
        upper=full_work[MAPPED_WORK_SIZE:],
        ac=live.read_u16(session, 0xAC),
        cycles=end_cycles - start_cycles,
        halt=live.read_u16(session, 0x4E),
        observed_pc=observed_pc,
    )


def mismatch_offsets(left: bytes, right: bytes) -> list[int]:
    return [
        offset
        for offset, (lhs, rhs) in enumerate(zip(left, right))
        if lhs != rhs
    ]


def hp(fixture: Fixture, work: bytes) -> int:
    return work[(fixture.target & 0xFFFF) + 3]


def compare_case(
    fixture: Fixture,
    fixture_index: int,
    arcade: Result,
    native_off: Result,
    native_on: Result,
) -> dict:
    def reg_mismatches(result: Result) -> dict[str, dict[str, int]]:
        return {
            name: {
                "mame": arcade.regs[name],
                "nexen": result.regs[name],
            }
            for name in base.REG_NAMES
            if arcade.regs[name] != result.regs[name]
        }

    off_regs = reg_mismatches(native_off)
    on_regs = reg_mismatches(native_on)
    off_work = mismatch_offsets(arcade.work, native_off.work)
    on_work = mismatch_offsets(arcade.work, native_on.work)
    upper = patterned_upper(fixture_index)
    off_upper = mismatch_offsets(upper, native_off.upper or b"")
    on_upper = mismatch_offsets(upper, native_on.upper or b"")
    expected_hp = (fixture.hp_before - fixture.damage) & 0xFF
    hp_values = {
        "expected": expected_hp,
        "mame": hp(fixture, arcade.work),
        "native_off": hp(fixture, native_off.work),
        "native_on": hp(fixture, native_on.work),
    }
    off_ccr_mismatch = (
        arcade.sr & CCR_MASK
    ) != (native_off.sr & CCR_MASK)
    # At this interior join, N/Z/V/C from SUB.B and X are dead: $01EAE0
    # overwrites N/Z/V/C before a consumer and $01EAEC overwrites X.  The
    # native body therefore does not materialize those slots.  They are
    # reported, while exact CCR/X is required on the interpreted path.
    failures = (
        bool(off_regs)
        or bool(on_regs)
        or bool(off_work)
        or bool(on_work)
        or bool(off_upper)
        or bool(on_upper)
        or off_ccr_mismatch
        or any(value != expected_hp for value in hp_values.values())
        or native_off.halt != 0
        or native_on.halt != 0
    )
    return {
        "event": "case",
        "case": fixture.name,
        "label": fixture.label,
        "source": fixture.source,
        "source_state": str(fixture.source_state.resolve()),
        "source_state_sha256": fixture.source_state_sha256,
        "entry_pc": f"{ENTRY_PC:06X}",
        "terminal_pc": f"{TERMINAL_PC:06X}",
        "collision_type": fixture.collision_type,
        "damage": fixture.damage,
        "buttons": fixture.buttons,
        "player_action": fixture.player_action,
        "target": f"{fixture.target:06X}",
        "hp_before": fixture.hp_before,
        "hp_after": hp_values,
        "native_off": {
            "cycles_local": native_off.cycles,
            "ac_after": native_off.ac,
            "register_mismatches": off_regs,
            "ccr_x_mismatch": off_ccr_mismatch,
            "mame_ccr_x": arcade.sr & CCR_MASK,
            "nexen_ccr_x": native_off.sr & CCR_MASK,
            "mapped_work_mismatch_count": len(off_work),
            "mapped_work_mismatch_first": [
                f"F0{offset:04X}" for offset in off_work[:32]
            ],
            "upper_backing_mutation_count": len(off_upper),
            "upper_backing_mutation_first": [
                f"F0{MAPPED_WORK_SIZE + offset:04X}"
                for offset in off_upper[:32]
            ],
            "halt": native_off.halt,
        },
        "native_on": {
            "cycles_local": native_on.cycles,
            "ac_after": native_on.ac,
            "register_mismatches": on_regs,
            "ccr_x_observed": native_on.sr & CCR_MASK,
            "ccr_x_comparison": (
                "reported, not compared at the dead-flag interior join: "
                "$01EAE0 overwrites N/Z/V/C before any consumer and "
                "$01EAEC overwrites X before any X-reader"
            ),
            "mapped_work_mismatch_count": len(on_work),
            "mapped_work_mismatch_first": [
                f"F0{offset:04X}" for offset in on_work[:32]
            ],
            "upper_backing_mutation_count": len(on_upper),
            "upper_backing_mutation_first": [
                f"F0{MAPPED_WORK_SIZE + offset:04X}"
                for offset in on_upper[:32]
            ],
            "halt": native_on.halt,
        },
        "ac_comparison": {
            "native_off_after": native_off.ac,
            "native_on_after": native_on.ac,
            "equal": native_off.ac == native_on.ac,
            "scope": (
                "reported, not a semantic gate for this direct interior "
                "join: the legacy whole-task native body does not own "
                "per-block AC equivalence; sustained task/IRQ cadence is "
                "validated separately"
            ),
        },
        "exact_stack_and_a7": (
            not any(
                offset >= (fixture.regs["A7"] & 0xFFFF)
                for offset in off_work + on_work
            )
            and not off_regs.get("A7")
            and not on_regs.get("A7")
        ),
        "interrupt_mask_isolated": {
            "mame_physical": 7,
            "native_off": (native_off.sr >> 8) & 7,
            "native_on": (native_on.sr >> 8) & 7,
        },
        "result": "red" if failures else "green",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9370)
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    for label, path in (
        ("evidence directory", args.evidence),
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    fixtures = load_fixtures(args.evidence.resolve())
    native_entry = symbol_address(
        ROOT / "src/escbank4.sym", 0x98, "L1e7c0_1e9da"
    )
    native_terminal = symbol_address(
        ROOT / "src/escbank4.sym", 0x98, "L1e7c0_1eae0"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mame_workdir = (
        args.output.parent / f"{args.output.stem}.mame-session"
    ).resolve()
    if mame_workdir.exists():
        raise RuntimeError(
            f"refusing to reuse MAME IPC directory: {mame_workdir}"
        )
    mame_workdir.mkdir(parents=True)
    mame_states = mame_workdir / "states"
    mame_states.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "time": time.time(),
        "scope": (
            "same-state MAME original / exact-Nexen native-off / "
            "exact-Nexen native-on ordinary-enemy damage differential; "
            "punch, kick, body/contact, and charged-projectile classes; "
            "all D/A, relevant CCR/X, exact stack and mapped 16 KiB RAM, "
            "upper-backing conservation, local AC reporting, and health write; "
            "bounded regression, not fresh-boot or full-combat proof"
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
        "native_entry": f"{native_entry:06X}",
        "native_terminal": f"{native_terminal:06X}",
        "fixture_count": len(fixtures),
        "terminal_capture": (
            "MAME substitutes a BRA-to-self only at the fetched $01EAE0 "
            "word and samples its second fetch. Native-off substitutes "
            "ILLEGAL at the same 68000 word and spins pre-op_illegal. "
            "Native-on spins at the corresponding translated interior "
            "label. Every patch is restored after each case."
        ),
        "irq_isolation": "all bounded spans physically mask level 7",
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
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
                "entry_pc": f"{ENTRY_PC:06X}",
                "terminal_pc": f"{TERMINAL_PC:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    stderr_log = (
        args.output.parent / f"{args.output.stem}.nexen.stderr.log"
    )
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as nexen:
        for index, fixture in enumerate(fixtures):
            native_off = console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                index,
                0,
                native_entry,
                native_terminal,
            )
            native_on = console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                index,
                1,
                native_entry,
                native_terminal,
            )
            event = compare_case(
                fixture,
                index,
                arcade[fixture.name],
                native_off,
                native_on,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    cases = [event for event in events if event["event"] == "case"]
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
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
