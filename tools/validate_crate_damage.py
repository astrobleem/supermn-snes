#!/usr/bin/env python3
"""Replay retained organic crate contacts in MAME and current Nexen semantics.

The MAME side is immutable original-code evidence captured from an organic
held-crate state.  The SNES side loads one retained pre-contact state twice,
with both native gates disabled and enabled, and stops on the exact collision
and health writes.  This is focused semantic evidence, not fresh-boot proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_EMULATOR = ROOT / "tools/mesen211_mcp_controller.sh"
MESEN_BINARY = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
EVIDENCE = ROOT / "build/playtest-investigation-20260725"
DEFAULT_THROWN = EVIDENCE / "crate-thrown-hit-prewrite.mss"
DEFAULT_HELD = EVIDENCE / "crate-held-8039-contact-prewrite.mss"
MAME_DIR = EVIDENCE / "crate-damage-oracle-v1"
MAME_STATE_DIR = EVIDENCE / "mame-crate-playback-states/superman"

SNES_SPACE = base.SNES_SPACE
DP_SPACE = base.DP_SPACE
CRATE = 0x403744
THROWN_TARGET = 0x403A94
THROWN_DAMAGE = 0x403AA1
THROWN_OWNER = 0x40041A
THROWN_HEALTH = 0x40041D
HELD_TARGET = 0x403AB4
HELD_RESPONSE_HI = 0x403AC0
HELD_PEER_HI = 0x403AC2
HELD_OWNER = 0x402BB4
HELD_HEALTH = 0x402BB7


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--thrown-state", type=Path, default=DEFAULT_THROWN)
    parser.add_argument("--held-state", type=Path, default=DEFAULT_HELD)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=7950)
    args = parser.parse_args()
    for path in (
        args.rom,
        args.emulator,
        args.nexen,
        args.thrown_state,
        args.held_state,
        MESEN_BINARY,
        MAME_DIR / "mame-held-oracle.log",
        MAME_DIR / "mame-thrown-oracle.log",
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(m: base.McpSession, address: int, length: int) -> bytes:
    return bytes(m.read_memory(SNES_SPACE, address, length))


def read_dp(m: base.McpSession, address: int, length: int = 2) -> bytes:
    return bytes(m.read_memory(DP_SPACE, address, length))


def dp16(m: base.McpSession, address: int) -> int:
    return int.from_bytes(read_dp(m, address), "little")


def be16(m: base.McpSession, address: int) -> int:
    return int.from_bytes(read(m, address, 2), "big")


def write_dp16(m: base.McpSession, address: int, value: int) -> None:
    m.write_memory(
        DP_SPACE,
        address,
        (value & 0xFFFF).to_bytes(2, "little").hex(),
    )


def collision_record(m: base.McpSession, address: int) -> dict[str, Any]:
    raw = read(m, address, 16)
    words = [
        int.from_bytes(raw[offset : offset + 2], "big")
        for offset in range(0, 16, 2)
    ]
    return {
        "address": f"{address:06X}",
        "hex": raw.hex().upper(),
        "active": words[0],
        "x1": words[1],
        "x2": words[2],
        "y1": words[3],
        "y2": words[4],
        "type": words[5],
        "response": words[6],
        "damage": raw[13],
        "peer_type": words[7],
    }


def register_state(m: base.McpSession) -> dict[str, Any]:
    raw = read_dp(m, 0x00, 0x40)
    regs = {
        name: int.from_bytes(
            raw[index * 4 : index * 4 + 4], "little"
        )
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        ((dp16(m, 0xA2) & 1) << 4)
        | ((dp16(m, 0x70) & 1) << 3)
        | ((dp16(m, 0x60) & 1) << 2)
        | ((dp16(m, 0x72) & 1) << 1)
        | (dp16(m, 0x6E) & 1)
    )
    stack = 0x400000 | ((regs["A7"] - 32) & 0xFFFF)
    return {
        "registers": {
            name: f"{value & 0xFFFFFFFF:08X}" for name, value in regs.items()
        },
        "ccr_nzvc": ccr & 0x0F,
        "x": (ccr >> 4) & 1,
        "interrupt_mask": dp16(m, 0x7C) & 7,
        "stack_window_address": f"{stack:06X}",
        "stack_window_hex": read(m, stack, 64).hex().upper(),
    }


def snapshot(
    m: base.McpSession,
    *,
    target: int,
    owner: int,
    health: int,
) -> dict[str, Any]:
    state = m.get_state()
    sa1 = m.get_cpu_state("Sa1")
    mapped_work = read(m, 0x400000, 0x4000)
    return {
        "crate": collision_record(m, CRATE),
        "target": collision_record(m, target),
        "owner_address": f"{owner:06X}",
        "owner_hex": read(m, owner, 0x70).hex().upper(),
        "health_address": f"{health:06X}",
        "health": read(m, health, 1)[0],
        "mapped_work_sha256": hashlib.sha256(mapped_work).hexdigest(),
        "object_collision_f03000_f03fff_sha256": hashlib.sha256(
            mapped_work[0x3000:0x4000]
        ).hexdigest(),
        "m68k": register_state(m),
        "scheduler_irq": {
            "task_mask_f00002": be16(m, 0x400002),
            "game_tick_f01c56": be16(m, 0x401C56),
            "virtual_irq_pending_aa": dp16(m, 0xAA),
            "virtual_irq_countdown_ac": dp16(m, 0xAC),
            "interpreter_steps": dp16(m, 0x4A) | (dp16(m, 0x4C) << 16),
            "halt_4e": dp16(m, 0x4E),
            "video_frame": int(state.get("frameCount", 0)),
            "sa1_cycles": int(sa1.get("cycleCount", 0)),
        },
        "gates": {
            "xlat_071a": dp16(m, 0x071A),
            "fetch_choke_073a": dp16(m, 0x073A),
        },
    }


def clear_hooks(m: base.McpSession) -> None:
    for row in m.list_hooks():
        handle = int(row.get("handle", row.get("id", 0)))
        if handle:
            m.remove_hook(handle)
    m.drain_notifications(timeout=0.05)


def configure(
    m: base.McpSession, state: Path, gate: int
) -> dict[str, Any]:
    m.load_state(str(state))
    m.pause()
    clear_hooks(m)
    write_dp16(m, 0x071A, gate)
    write_dp16(m, 0x073A, gate)
    observed = (dp16(m, 0x071A), dp16(m, 0x073A))
    if observed != (gate, gate):
        raise RuntimeError(f"native gates did not verify: {observed}")
    return {
        "state": str(state.resolve()),
        "state_sha256": sha256(state),
        "requested_gate": gate,
        "observed_071a": observed[0],
        "observed_073a": observed[1],
    }


def run_to_write(
    m: base.McpSession,
    address: int,
    value: int,
    *,
    max_frames: int,
) -> dict[str, Any]:
    hook = m.add_write_hook(
        address,
        cpu_type="Sa1",
        match_value=value,
        match_value_mask=0xFF,
    )
    m.drain_notifications(timeout=0.05)
    before = m.get_cpu_state("Sa1")
    before_frame = int(m.get_state().get("frameCount", 0))
    try:
        result = m.run_until(max_frames=max_frames, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.02)
    after = m.get_cpu_state("Sa1")
    after_frame = int(m.get_state().get("frameCount", 0))
    return {
        "address": f"{address:06X}",
        "value": value,
        "result": result,
        "video_frames": after_frame - before_frame,
        "sa1_cycles": (
            int(after.get("cycleCount", 0))
            - int(before.get("cycleCount", 0))
        ),
    }


def require_hook(event: dict[str, Any], label: str) -> None:
    if (event["result"] or {}).get("reason") != "hookFired":
        raise RuntimeError(f"{label} did not reach its write: {event}")


def run_thrown(
    m: base.McpSession, state: Path, gate: int
) -> dict[str, Any]:
    result: dict[str, Any] = {"configure": configure(m, state, gate)}
    result["pre"] = snapshot(
        m, target=THROWN_TARGET, owner=THROWN_OWNER, health=THROWN_HEALTH
    )
    result["contact_run"] = run_to_write(
        m, THROWN_DAMAGE, 1, max_frames=300
    )
    require_hook(result["contact_run"], "thrown response")
    result["contact"] = snapshot(
        m, target=THROWN_TARGET, owner=THROWN_OWNER, health=THROWN_HEALTH
    )
    result["damage_run"] = run_to_write(
        m, THROWN_HEALTH, 0, max_frames=300
    )
    require_hook(result["damage_run"], "thrown health")
    result["post"] = snapshot(
        m, target=THROWN_TARGET, owner=THROWN_OWNER, health=THROWN_HEALTH
    )
    if (
        result["contact"]["target"]["response"] != 0x2001
        or result["contact"]["target"]["damage"] != 1
        or result["contact"]["target"]["peer_type"] != 0x8039
        or result["contact"]["health"] != 1
        or result["post"]["health"] != 0
    ):
        raise AssertionError("thrown crate semantics diverged")
    return result


def run_held(
    m: base.McpSession, state: Path, gate: int
) -> dict[str, Any]:
    result: dict[str, Any] = {"configure": configure(m, state, gate)}
    result["pre"] = snapshot(
        m, target=HELD_TARGET, owner=HELD_OWNER, health=HELD_HEALTH
    )
    result["contact_run"] = run_to_write(
        m, HELD_RESPONSE_HI, 0x20, max_frames=300
    )
    require_hook(result["contact_run"], "held response")
    result["contact"] = snapshot(
        m, target=HELD_TARGET, owner=HELD_OWNER, health=HELD_HEALTH
    )
    result["consume_run"] = run_to_write(
        m, HELD_PEER_HI, 0, max_frames=180
    )
    require_hook(result["consume_run"], "held consume")
    result["consumed"] = snapshot(
        m, target=HELD_TARGET, owner=HELD_OWNER, health=HELD_HEALTH
    )

    configure(m, state, gate)
    replay = run_to_write(m, HELD_RESPONSE_HI, 0x20, max_frames=300)
    require_hook(replay, "held replay response")
    no_damage = run_to_write(m, HELD_HEALTH, 0, max_frames=60)
    result["zero_health_watch"] = no_damage
    result["post_watch"] = snapshot(
        m, target=HELD_TARGET, owner=HELD_OWNER, health=HELD_HEALTH
    )
    if (
        result["contact"]["target"]["response"] != 0x2000
        or result["contact"]["target"]["damage"] != 0
        or result["contact"]["target"]["peer_type"] != 0x8039
        or result["contact"]["health"] != 1
        or result["consumed"]["health"] != 1
        or (no_damage["result"] or {}).get("reason") == "hookFired"
        or result["post_watch"]["health"] != 1
    ):
        raise AssertionError("held crate damaged the target")
    return result


def retained_mame_oracle() -> dict[str, Any]:
    held_path = MAME_DIR / "mame-held-oracle.log"
    thrown_path = MAME_DIR / "mame-thrown-oracle.log"
    held = held_path.read_text(encoding="utf-8")
    thrown = thrown_path.read_text(encoding="utf-8")
    checks = {
        "held_contact_2000": bool(
            re.search(r"^CONTACT .* data=2000 ", held, re.MULTILINE)
        ),
        "held_health_1_to_1": bool(
            re.search(
                r"^FINAL_OWNER .* health=01 zero_write=false$",
                held,
                re.MULTILINE,
            )
        ),
        "held_30_frame_watch": (
            "reason=held_contact_30_frame_watch_no_damage" in held
        ),
        "thrown_contact_2001": bool(
            re.search(r"^CONTACT .* data=2001 ", thrown, re.MULTILINE)
        ),
        "thrown_health_write_at_01ea4e": bool(
            re.search(r"^HEALTH_WRITE .* pc=01EA4E$", thrown, re.MULTILINE)
        ),
        "thrown_health_1_to_0": bool(
            re.search(
                r"^OWNER_CANDIDATE .* health=01$", thrown, re.MULTILINE
            )
            and re.search(r"^FINAL_OWNER .* health=00$", thrown, re.MULTILINE)
        ),
    }
    if not all(checks.values()):
        raise AssertionError(f"retained MAME crate oracle failed: {checks}")
    state_names = (
        "mame-crate-thrown-aligned-held.sta",
        "mame-crate-held-positive-pre-event.sta",
        "mame-crate-held-positive-contact-health1.sta",
        "mame-crate-held-positive-postwatch-health1.sta",
        "mame-crate-thrown-positive-pre-event.sta",
        "mame-crate-thrown-positive-contact-health1.sta",
        "mame-crate-thrown-positive-postdamage-health0.sta",
    )
    states = {}
    for name in state_names:
        path = MAME_STATE_DIR / name
        if not path.is_file():
            raise FileNotFoundError(path)
        states[name] = {
            "path": str(path.resolve()),
            "sha256": sha256(path),
        }
    return {
        "classification": "original_arcade_oracle",
        "mame": "/snap/bin/mame 0.287",
        "logs": {
            "held": {"path": str(held_path), "sha256": sha256(held_path)},
            "thrown": {
                "path": str(thrown_path),
                "sha256": sha256(thrown_path),
            },
        },
        "states": states,
        "checks": checks,
        "held_contact_registers": next(
            line for line in held.splitlines() if line.startswith("CONTACT_REGS ")
        ),
        "thrown_contact_registers": next(
            line
            for line in thrown.splitlines()
            if line.startswith("CONTACT_REGS ")
        ),
    }


def nexen_checkpoint_probe(
    rom: Path,
    nexen: Path,
    states: dict[str, tuple[Path, int, int, int]],
    *,
    port: int,
) -> dict[str, Any]:
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    observations: dict[str, Any] = {}
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
    ) as m:
        for name, (state, target, owner, health) in states.items():
            m.load_state(str(state))
            m.pause()
            observations[name] = {
                "state": str(state.resolve()),
                "state_sha256": sha256(state),
                "m68k_pc": (
                    dp16(m, 0x40) | ((dp16(m, 0x42) & 0xFF) << 16)
                ),
                "halt": dp16(m, 0x4E),
                "sa1": m.get_cpu_state("Sa1"),
                "snapshot": snapshot(
                    m, target=target, owner=owner, health=health
                ),
            }
    return {
        "nexen": str(nexen.resolve()),
        "nexen_sha256": sha256(nexen),
        "observations": observations,
    }


def semantic_summary(case: dict[str, Any], held: bool) -> dict[str, Any]:
    contact = case["contact"]
    return {
        "response": contact["target"]["response"],
        "damage": contact["target"]["damage"],
        "peer_type": contact["target"]["peer_type"],
        "health_before": case["pre"]["health"],
        "health_at_contact": contact["health"],
        "health_after": (
            case["post_watch"]["health"] if held else case["post"]["health"]
        ),
        "task_mask_at_contact": contact["scheduler_irq"][
            "task_mask_f00002"
        ],
        "halt_at_contact": contact["scheduler_irq"]["halt_4e"],
    }


def main() -> int:
    args = parse_args()
    # The retained checkpoints are exact Mesen 2.1.1 states.  Nexen correctly
    # loads their shared work RAM but cannot restore their legacy SA-1
    # CPU/IRAM state; using it would classify the fixture as stale before any
    # crate code runs.  Run the semantic replay in the owning emulator.
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
    os.environ["PATH"] = "/home/chad/.dotnet8:" + os.environ.get("PATH", "")
    events: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "scope": (
                "retained organic crate contact; original MAME oracle plus "
                "current Nexen native-off/native-on replay; not fresh boot"
            ),
            "time": time.time(),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "emulator": str(args.emulator.resolve()),
            "emulator_sha256": sha256(args.emulator),
            "mesen_2_1_1_binary": str(MESEN_BINARY),
            "mesen_2_1_1_binary_sha256": sha256(MESEN_BINARY),
            "emulator_ownership": (
                "retained checkpoints are Mesen 2.1.1-owned; separate Nexen "
                "load probe classifies their CPU/IRAM as stale"
            ),
            "fixtures": {
                "thrown": {
                    "path": str(args.thrown_state.resolve()),
                    "sha256": sha256(args.thrown_state),
                },
                "held": {
                    "path": str(args.held_state.resolve()),
                    "sha256": sha256(args.held_state),
                },
            },
        },
        {"event": "mame_oracle", **retained_mame_oracle()},
    ]
    try:
        with base.McpSession(
            rom=str(args.rom),
            mesen=str(args.emulator),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=args.output.with_suffix(".emulator.stderr.log"),
        ) as m:
            cases = {
                "held_native_off": run_held(m, args.held_state, 0),
                "held_native_on": run_held(m, args.held_state, 1),
                "thrown_native_off": run_thrown(m, args.thrown_state, 0),
                "thrown_native_on": run_thrown(m, args.thrown_state, 1),
            }
    except RuntimeError as error:
        # A retained pre-write checkpoint that cannot reach its own response
        # write under the selected current ROM is stale evidence, not a crate
        # damage result.  Emit a durable classification instead of converting
        # that fixture incompatibility into an unexplained traceback.
        if "did not reach its write" not in str(error):
            raise
        stale = {
            "event": "summary",
            "result": "red",
            "classification": "stale_save_state_data",
            "green": 0,
            "red": 1,
            "reason": str(error),
            "scope": (
                "retained Mesen-owned crate checkpoint does not reach the "
                "expected response write under the current ROM; no gameplay "
                "conclusion is drawn"
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
            + json.dumps(stale, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps(stale, indent=2, sort_keys=True))
        return 1
    nexen_probe = nexen_checkpoint_probe(
        args.rom,
        args.nexen,
        {
            "held": (
                args.held_state,
                HELD_TARGET,
                HELD_OWNER,
                HELD_HEALTH,
            ),
            "thrown": (
                args.thrown_state,
                THROWN_TARGET,
                THROWN_OWNER,
                THROWN_HEALTH,
            ),
        },
        port=args.port + 1,
    )
    stale_checks = {}
    for fixture, case_name in (
        ("held", "held_native_on"),
        ("thrown", "thrown_native_on"),
    ):
        mesen_pre = cases[case_name]["pre"]
        nexen_pre = nexen_probe["observations"][fixture]["snapshot"]
        stale_checks[fixture] = {
            "work_ram_preserved": (
                mesen_pre["mapped_work_sha256"]
                == nexen_pre["mapped_work_sha256"]
            ),
            "m68k_register_file_differs": (
                mesen_pre["m68k"]["registers"]
                != nexen_pre["m68k"]["registers"]
            ),
            "mesen_m68k": mesen_pre["m68k"],
            "nexen_m68k": nexen_pre["m68k"],
            "nexen_m68k_pc": nexen_probe["observations"][fixture][
                "m68k_pc"
            ],
            "nexen_sa1": nexen_probe["observations"][fixture]["sa1"],
        }
    if not all(
        check["work_ram_preserved"] and check["m68k_register_file_differs"]
        for check in stale_checks.values()
    ):
        raise AssertionError(
            f"unexpected Mesen-state/Nexen compatibility result: {stale_checks}"
        )
    events.append(
        {
            "event": "nexen_checkpoint_classification",
            "result": "stale_save_state_data",
            "reason": (
                "legacy Mesen state transfers gameplay work RAM but not its "
                "owning SA-1 CPU/IRAM state into Nexen; no Nexen gameplay "
                "conclusion may be drawn from these checkpoint files"
            ),
            "probe": nexen_probe,
            "checks": stale_checks,
        }
    )
    for name, case in cases.items():
        events.append(
            {
                "event": "case",
                "name": name,
                "result": "green",
                "summary": semantic_summary(case, name.startswith("held_")),
                "detail": case,
            }
        )
    summaries = {
        name: semantic_summary(case, name.startswith("held_"))
        for name, case in cases.items()
    }
    if summaries["held_native_off"] != summaries["held_native_on"]:
        raise AssertionError("held native-off/on semantic summary differs")
    if summaries["thrown_native_off"] != summaries["thrown_native_on"]:
        raise AssertionError("thrown native-off/on semantic summary differs")
    summary = {
        "event": "summary",
        "result": "green",
        "green": 4,
        "red": 0,
        "held": summaries["held_native_on"],
        "thrown": summaries["thrown_native_on"],
        "classification": (
            "no crate-damage discrepancy: held response $2000 carries zero "
            "damage; thrown response $2001 carries one"
        ),
    }
    events.append(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
