#!/usr/bin/env python3
"""Prove non-mutating campaign checkpoint restoration across Nexen processes.

At native pre-body $003A92, this regression requires repeated synchronous
saves to leave all MCP-visible CPU, timing, RAM, VRAM, CGRAM, OAM, and SPC
state unchanged.  It then loads the file in a fresh process with a
mutation-denying audit, compares the immediate state, and compares a direct
continuation against the fresh-process continuation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-exact-checkpoint-publish/Nexen"
)
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "fresh-campaign-entrysync-3ea4faf-to01100-v1/states/failure.mss"
)

sys.path.insert(0, str(ROOT / "tools"))
import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(
    m: campaign.McpSession,
) -> tuple[dict[str, Any], tuple[bytes, ...]]:
    public, raw = campaign.checkpoint_machine_snapshot(m)
    iram, work = raw[:2]
    public["scheduler"] = {
        "halt_004e": int.from_bytes(iram[0x4E:0x50], "little"),
        "irq_mask_007c": int.from_bytes(iram[0x7C:0x7E], "little"),
        "task_index_00aa": int.from_bytes(iram[0xAA:0xAC], "little"),
        "irq_budget_00ac": int.from_bytes(iram[0xAC:0xAE], "little"),
        "task_mask_f00002": int.from_bytes(work[2:4], "big"),
        "game_tick_f01c56": int.from_bytes(work[0x1C56:0x1C58], "big"),
    }
    return public, raw


def exact_address(cpu: dict[str, Any]) -> int:
    return (
        ((int(cpu.get("k", 0)) & 0xFF) << 16)
        | (int(cpu.get("pc", 0)) & 0xFFFF)
    )


def raw_hashes(raw: tuple[bytes, ...]) -> dict[str, str]:
    names = (
        "sa1_iram",
        "game_work",
        "snes_wram",
        "vram",
        "cgram",
        "oam",
        "spc_ram",
    )
    if len(raw) != len(names):
        raise RuntimeError(
            f"unexpected checkpoint raw component count: {len(raw)}"
        )
    return {
        name: sha256_bytes(data)
        for name, data in zip(names, raw, strict=True)
    }


def require_exact_stop(stop: dict[str, Any], occurrences: int) -> None:
    response_pc = (
        ((int(stop.get("k", 0)) & 0xFF) << 16)
        | (int(stop.get("pc", 0)) & 0xFFFF)
    )
    checks = {
        "reason": stop.get("reason") == "breakpoint",
        "hit": stop.get("hit") is True,
        "paused": stop.get("isPaused") is True,
        "pc": response_pc == campaign.ENTRY_3A92_NATIVE,
        "requested": int(stop.get("requestedOccurrences", -1))
        == occurrences,
        "occurrences": int(stop.get("observedOccurrences", -1))
        == occurrences,
        "removed": stop.get("exactStopRemoved") is True,
        "handle": int(stop.get("exactStopHandle", 0)) > 0,
        "triggered": stop.get("exactStopTriggered") is True,
        "delivered": stop.get("exactStopBreakDelivered") is True,
        "trigger_cycle": int(stop.get("triggerCycleCount", -1))
        == int(stop.get("cycleCount", -2)),
        "trigger_frame": int(stop.get("triggerFrame", -1))
        == int(stop.get("endFrame", -2)),
    }
    if not all(checks.values()):
        raise RuntimeError(f"exact entry stop failed: {checks}; {stop}")


def restore_bundle(
    m: campaign.AuditedMcpSession,
    state_path: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    cpu_state = bundle.get("resume_sa1_state")
    iram_info = bundle.get("resume_sa1_iram")
    if not isinstance(cpu_state, dict) or not isinstance(iram_info, dict):
        raise RuntimeError("checkpoint lacks exact SA-1 restore metadata")
    response = bundle.get("response")
    if (
        not isinstance(response, dict)
        or bundle.get("synchronous_completed") is not True
        or bundle.get("atomic_rename") is not True
        or response.get("completed") is not True
        or response.get("atomicRename") is not True
        or not state_path.is_file()
        or sha256_file(state_path) != bundle.get("sha256")
        or state_path.stat().st_size != int(response.get("size", -1))
    ):
        raise RuntimeError("checkpoint .mss failed pre-load authentication")
    iram_path = Path(str(iram_info.get("path", "")))
    if (
        not iram_path.is_file()
        or iram_path.stat().st_size != 0x800
        or sha256_file(iram_path) != iram_info.get("sha256")
    ):
        raise RuntimeError("checkpoint SA-1 IRAM sidecar failed authentication")
    mutation_start = len(m.architectural_mutations)
    load_response = m.load_state(str(state_path.resolve()))
    campaign.require_paused(m, "checkpoint validator load")
    mutations = m.architectural_mutations[mutation_start:]
    if mutations:
        raise RuntimeError(
            f"checkpoint restore used an architectural transplant: {mutations}"
        )
    loaded_cpu = dict(m.get_cpu_state("Sa1"))
    mismatches = {
        key: {
            "expected": cpu_state.get(key),
            "observed": loaded_cpu.get(key),
        }
        for key in cpu_state
        if key != "cpuType"
        and loaded_cpu.get(key) != cpu_state.get(key)
    }
    if mismatches:
        raise RuntimeError(f"atomic SA-1 load mismatch: {mismatches}")
    return {
        "load_response": load_response,
        "architectural_mutations": mutations,
        "no_cpu_or_memory_transplant": not mutations,
        "loaded_sa1": loaded_cpu,
        "loaded_pc": f"{exact_address(loaded_cpu):06X}",
    }


def session(
    *,
    rom: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> campaign.AuditedMcpSession:
    return campaign.AuditedMcpSession(
        rom=str(rom.resolve()),
        mesen=str(nexen.resolve()),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=600.0,
        stderr_log=stderr_log,
    )


def run_entry_sequence(
    m: campaign.McpSession,
    entries: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[tuple[bytes, ...]],
]:
    runs: list[dict[str, Any]] = []
    public_states: list[dict[str, Any]] = []
    raw_states: list[tuple[bytes, ...]] = []
    for index in range(1, entries + 1):
        run = campaign.run_game_update_entries(m, 1)[0]
        public, raw = snapshot(m)
        runs.append(
            {
                "entry": index,
                "run": run,
                "public": public,
                "raw_sha256": raw_hashes(raw),
            }
        )
        public_states.append(public)
        raw_states.append(raw)
    return runs, public_states, raw_states


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--source-state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--entries", type=int, default=100)
    parser.add_argument("--repeat-saves", type=int, default=3)
    parser.add_argument("--port", type=int, default=9570)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.source_state):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.entries < 1:
        parser.error("--entries must be positive")
    if args.repeat_saves < 2:
        parser.error("--repeat-saves must be at least 2")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    campaign.configure_dotnet(args.nexen)
    args.output.mkdir(parents=True)
    states_dir = args.output / "states"
    states_dir.mkdir()
    events: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "focused durable checkpoint-bundle regression; direct versus "
            "fresh-Nexen-process continuation at the exact native $003A92 "
            "pre-body seam; not fresh-boot gameplay or fps"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256_file(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256_file(args.nexen),
        "nexen_identity": campaign.nexen_identity(args.nexen),
        "source_state": str(args.source_state.resolve()),
        "source_state_sha256": sha256_file(args.source_state),
        "entries": args.entries,
        "repeat_saves": args.repeat_saves,
        "validator_sha256": sha256_file(Path(__file__).resolve()),
        "campaign_harness_sha256": sha256_file(
            ROOT / "tools" / "replay_mame_controller_campaign.py"
        ),
        "time_unix": time.time(),
    }
    events.append(provenance)
    result = "red"
    failure: dict[str, Any] | None = None
    bundle: dict[str, Any] | None = None
    repeated_bundles: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    direct_run: list[dict[str, Any]] | None = None
    resumed_run: list[dict[str, Any]] | None = None
    restore_info: dict[str, Any] | None = None
    pre_save_public: dict[str, Any] | None = None
    post_save_public: dict[str, Any] | None = None
    restored_public: dict[str, Any] | None = None
    pre_save_raw: tuple[bytes, ...] | None = None
    post_save_raw: tuple[bytes, ...] | None = None
    restored_raw: tuple[bytes, ...] | None = None
    first_continuation_divergence: dict[str, Any] | None = None
    try:
        checkpoint_path = states_dir / "exact-entry-checkpoint.mss"
        with session(
            rom=args.rom,
            nexen=args.nexen,
            port=args.port,
            stderr_log=args.output / "direct.stderr.log",
        ) as m:
            campaign.pause_for_startup(m)
            m.load_state(str(args.source_state.resolve()))
            campaign.require_paused(m, "validator source-state load")
            entry_stop = dict(
                m.tool(
                    "run_to_exact_exec_stop",
                    {
                        "address": campaign.ENTRY_3A92_NATIVE,
                        "cpuType": "Sa1",
                        "maxFrames": 1000,
                        "occurrences": 1,
                    },
                )
            )
            require_exact_stop(entry_stop, 1)
            pre_save_public, pre_save_raw = snapshot(m)
            bundle = campaign.save_state(m, checkpoint_path)
            if bundle.get("entry_exact_bundle") is not True:
                raise RuntimeError("campaign did not create an exact-entry bundle")
            repeated_bundles.append(bundle)
            post_save_public, post_save_raw = snapshot(m)
            for index in range(1, args.repeat_saves):
                repeated_bundles.append(
                    campaign.save_state(
                        m,
                        states_dir
                        / f"exact-entry-checkpoint-repeat-{index}.mss",
                    )
                )
            final_save_public, final_save_raw = snapshot(m)
            initial_public, initial_raw = (
                final_save_public,
                final_save_raw,
            )
            (
                direct_run,
                direct_public_states,
                direct_raw_states,
            ) = run_entry_sequence(m, args.entries)
            direct_public = direct_public_states[-1]
            direct_raw = direct_raw_states[-1]

        with session(
            rom=args.rom,
            nexen=args.nexen,
            port=args.port + 1,
            stderr_log=args.output / "resumed.stderr.log",
        ) as m:
            campaign.pause_for_startup(m)
            restore_info = restore_bundle(m, checkpoint_path, bundle)
            restored_public, restored_raw = snapshot(m)
            (
                resumed_run,
                resumed_public_states,
                resumed_raw_states,
            ) = run_entry_sequence(m, args.entries)
            resumed_public = resumed_public_states[-1]
            resumed_raw = resumed_raw_states[-1]

        for index, (
            direct_entry_public,
            direct_entry_raw,
            resumed_entry_public,
            resumed_entry_raw,
        ) in enumerate(
            zip(
                direct_public_states,
                direct_raw_states,
                resumed_public_states,
                resumed_raw_states,
                strict=True,
            ),
            start=1,
        ):
            if (
                direct_entry_public != resumed_entry_public
                or direct_entry_raw != resumed_entry_raw
            ):
                first_continuation_divergence = {
                    "entry": index,
                    "public_equal": (
                        direct_entry_public == resumed_entry_public
                    ),
                    "memory_equal": direct_entry_raw == resumed_entry_raw,
                    "direct": direct_run[index - 1],
                    "resumed": resumed_run[index - 1],
                }
                break

        checks = {
            "synchronous_save_completed": (
                bundle.get("synchronous_completed") is True
                and bundle.get("atomic_rename") is True
            ),
            "live_save_state_unchanged": (
                bundle.get("live_state_unchanged") is True
                and bundle.get("active_run_reloaded") is False
                and bundle.get("active_run_memory_restored") is False
                and pre_save_public == post_save_public
                and pre_save_raw == post_save_raw
                and pre_save_public == final_save_public
                and pre_save_raw == final_save_raw
                and all(
                    item.get("live_state_unchanged") is True
                    for item in repeated_bundles
                )
            ),
            "bundle_state_authenticated": (
                sha256_file(checkpoint_path) == bundle.get("sha256")
            ),
            "bundle_iram_authenticated": (
                sha256_file(
                    Path(str(bundle["resume_sa1_iram"]["path"]))
                )
                == bundle["resume_sa1_iram"]["sha256"]
            ),
            "initial_public_exact": initial_public == restored_public,
            "initial_memory_exact": initial_raw == restored_raw,
            "direct_and_resumed_public_exact": (
                direct_public == resumed_public
            ),
            "direct_and_resumed_memory_exact": direct_raw == resumed_raw,
            "direct_final_exact_entry": (
                exact_address(direct_public["sa1"])
                == campaign.ENTRY_3A92_NATIVE
            ),
            "resumed_final_exact_entry": (
                exact_address(resumed_public["sa1"])
                == campaign.ENTRY_3A92_NATIVE
            ),
            "entry_count_exact": (
                len(direct_run) == args.entries
                and len(resumed_run) == args.entries
                and all(
                    int(item["run"]["observed_entries"]) == 1
                    for item in [*direct_run, *resumed_run]
                )
            ),
            "load_required_no_transplant": (
                restore_info.get("no_cpu_or_memory_transplant") is True
                and not restore_info.get("architectural_mutations")
            ),
        }
        result = "green" if all(checks.values()) else "red"
        if result != "green":
            raise RuntimeError(f"checkpoint branch mismatch: {checks}")
    except Exception as exc:
        failure = {"reason": repr(exc)}

    comparison = {
        "event": "checkpoint_bundle_comparison",
        "checks": checks,
        "bundle": bundle,
        "repeated_bundles": repeated_bundles,
        "restore": restore_info,
        "pre_save_public": pre_save_public,
        "post_save_public": post_save_public,
        "fresh_load_public": restored_public,
        "pre_save_raw_sha256": (
            raw_hashes(pre_save_raw)
            if pre_save_raw is not None
            else None
        ),
        "post_save_raw_sha256": (
            raw_hashes(post_save_raw)
            if post_save_raw is not None
            else None
        ),
        "fresh_load_raw_sha256": (
            raw_hashes(restored_raw)
            if restored_raw is not None
            else None
        ),
        "direct_run": direct_run,
        "resumed_run": resumed_run,
        "first_continuation_divergence": (
            first_continuation_divergence
        ),
        "result": result,
    }
    events.append(comparison)
    event_path = args.output / "events.jsonl"
    with event_path.open("x", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
    summary = {
        **provenance,
        "result": result,
        "failure": failure,
        "checks": checks,
        "bundle": bundle,
        "repeated_bundles": repeated_bundles,
        "restore": restore_info,
        "events": str(event_path.resolve()),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
