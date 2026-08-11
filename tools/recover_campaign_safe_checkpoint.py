#!/usr/bin/env python3
"""Recover an authenticated nested campaign checkpoint into a safe resume.

The ordinary periodic campaign checkpoint is retained at the exact game-update
entry and is intentionally non-resumable.  This tool loads that exact machine
state in a fresh Nexen process, proves the complete public machine/IRAM bundle,
uses the campaign's audited post-entry rendezvous, and emits a new lineage log
that declares the recovery load explicitly.  It does not replay the accepted
prefix or alter game memory/CPU state through debugger writes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import replay_mame_controller_campaign as campaign  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_checkpoint_bundle(
    event_path: Path, state_path: Path, mame_tick: int
) -> dict[str, Any]:
    raw_lines = event_path.read_bytes().splitlines(keepends=True)
    indexed = [
        (index, json.loads(line))
        for index, line in enumerate(raw_lines)
        if line.strip()
    ]
    provenance = [
        (index, row)
        for index, row in indexed
        if row.get("event") == "provenance"
    ]
    if len(provenance) != 1 or provenance[0][0] != 0:
        raise RuntimeError("source requires one first-line provenance event")
    matches = [
        (index, row)
        for index, row in indexed
        if row.get("event") == "checkpoint"
        and int(row.get("mame_tick", -1)) == mame_tick
        and row.get("state", {}).get("sha256")
        == campaign.sha256(state_path)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "source tick/state does not have exactly one checkpoint event"
        )
    checkpoint_index, checkpoint = matches[0]
    state = checkpoint.get("state")
    context = checkpoint.get("resume_context")
    if not isinstance(state, dict) or not isinstance(context, dict):
        raise RuntimeError("source checkpoint bundle is incomplete")
    checks = {
        "exact_entry_bundle": state.get("entry_exact_bundle") is True,
        "nested_nonresumable": (
            state.get("nested_sa1_entry_nonresumable") is True
        ),
        "not_resumable": state.get("resumable_checkpoint") is False,
        "interpreted_route": (
            state.get("observed_game_update_entry_route")
            == "interpreted_iram"
        ),
        "synchronous_save": state.get("synchronous_completed") is True,
        "no_divergence": (
            context.get("first_oracle_divergence") is None
            and int(context.get("oracle_divergence_count", -1)) == 0
        ),
        "tick": int(context.get("mame_tick", -1)) == mame_tick,
    }
    if not all(checks.values()):
        raise RuntimeError(f"source checkpoint is not recoverable: {checks}")
    accepted_prefix = b"".join(raw_lines[: checkpoint_index + 1])
    return {
        "raw_lines": raw_lines,
        "indexed": indexed,
        "provenance": provenance[0][1],
        "checkpoint_index": checkpoint_index,
        "checkpoint": checkpoint,
        "state": state,
        "context": context,
        "accepted_prefix_sha256": digest(accepted_prefix),
        "accepted_prefix_lines": checkpoint_index + 1,
        "source_events_sha256": campaign.sha256(event_path),
        "source_state_sha256": campaign.sha256(state_path),
        "checks": checks,
    }


def recovered_context(
    source: dict[str, Any], safe: dict[str, Any], m: campaign.McpSession
) -> dict[str, Any]:
    context = copy.deepcopy(source["context"])
    context.update(
        {
            "phase": safe["phase"],
            "mame_tick_completed": int(source["checkpoint"]["mame_tick"]),
            "resume_mame_tick": int(safe["resume_mame_tick"]),
            "snes_tick": int(safe["after_snes_tick"]),
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "player": campaign.player_snapshot(m),
        }
    )
    context.pop("mame_tick", None)
    return context


def recovered_provenance(
    source: dict[str, Any], event_path: Path, state_path: Path, tool_hash: str
) -> dict[str, Any]:
    provenance = copy.deepcopy(source["provenance"])
    provenance["scope"] = (
        str(provenance.get("scope", ""))
        + "; one explicitly declared recovery load of the authenticated "
        "nested exact-entry checkpoint; exact-stop removal and post-entry "
        "safe rendezvous only; no accepted-prefix replay or debugger "
        "CPU/memory transplant"
    )
    provenance["mame_end_tick"] = int(source["checkpoint"]["mame_tick"])
    provenance["checkpoint_recovery"] = {
        "source_events": str(event_path.resolve()),
        "source_events_sha256": source["source_events_sha256"],
        "source_accepted_prefix_sha256": source[
            "accepted_prefix_sha256"
        ],
        "source_accepted_prefix_lines": source["accepted_prefix_lines"],
        "source_state": str(state_path.resolve()),
        "source_state_sha256": source["source_state_sha256"],
        "source_boundary_kind": source["state"].get("boundary_kind"),
        "recovery_tool_sha256": tool_hash,
        "architectural_mutations": [],
    }
    return provenance


def write_recovered_events(
    output: Path,
    source: dict[str, Any],
    provenance: dict[str, Any],
    safe: dict[str, Any],
    context: dict[str, Any],
    recovery: dict[str, Any],
) -> None:
    rows = [
        row
        for index, row in source["indexed"]
        if index <= source["checkpoint_index"]
    ]
    rows[0] = provenance
    rows.extend(
        [
            {"event": "checkpoint_recovery", **recovery},
            {
                "event": "safe_checkpoint",
                "mame_tick": int(source["checkpoint"]["mame_tick"]),
                "resume_mame_tick": int(safe["resume_mame_tick"]),
                "safe": safe,
                "state": safe["state"],
                "resume_context": context,
            },
        ]
    )
    with output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, required=True)
    parser.add_argument("--source-events", type=Path, required=True)
    parser.add_argument("--source-state", type=Path, required=True)
    parser.add_argument("--mame-tick", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    for name in ("rom", "mesen", "source_events", "source_state"):
        value = getattr(args, name).resolve()
        if not value.is_file():
            parser.error(f"missing --{name.replace('_', '-')}: {value}")
        setattr(args, name, value)
    if args.output.exists():
        parser.error(f"refusing existing output: {args.output}")

    source = source_checkpoint_bundle(
        args.source_events, args.source_state, args.mame_tick
    )
    if source["provenance"].get("rom_sha256") != campaign.sha256(args.rom):
        raise RuntimeError("source lineage ROM does not match selected ROM")

    args.output.mkdir(parents=True)
    states = args.output / "states"
    states.mkdir()
    config = args.output / "xdg-config"
    config.mkdir()
    os.environ["XDG_CONFIG_HOME"] = str(config.resolve())
    campaign.configure_dotnet(args.mesen)
    tool_hash = campaign.sha256(Path(__file__).resolve())
    recovery: dict[str, Any] = {
        "source_events": str(args.source_events),
        "source_events_sha256": source["source_events_sha256"],
        "source_accepted_prefix_sha256": source[
            "accepted_prefix_sha256"
        ],
        "source_accepted_prefix_lines": source["accepted_prefix_lines"],
        "source_state": str(args.source_state),
        "source_state_sha256": source["source_state_sha256"],
        "source_checks": source["checks"],
        "recovery_tool_sha256": tool_hash,
        "time_unix": time.time(),
    }

    with campaign.AuditedMcpSession(
        rom=args.rom,
        mesen=args.mesen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        mutation_start = len(m.architectural_mutations)
        load_response = m.load_state(args.source_state)
        campaign.require_paused(m, "recovery checkpoint load")
        loaded_public, loaded_raw = campaign.checkpoint_machine_snapshot(m)
        expected_public = source["state"].get("resume_validation")
        iram_info = source["state"].get("resume_sa1_iram")
        if not isinstance(expected_public, dict) or not isinstance(
            iram_info, dict
        ):
            raise RuntimeError("source checkpoint lacks machine/IRAM bundle")
        iram_path = Path(str(iram_info.get("path", "")))
        if not iram_path.is_file():
            raise RuntimeError(f"missing source IRAM sidecar: {iram_path}")
        expected_iram = iram_path.read_bytes()
        load_checks = {
            "public_state_exact": loaded_public == expected_public,
            "sa1_iram_exact": (
                loaded_raw[0] == expected_iram
                and campaign.sha256(iram_path) == iram_info.get("sha256")
            ),
            "no_architectural_mutations": (
                len(m.architectural_mutations) == mutation_start
            ),
        }
        if not all(load_checks.values()):
            raise RuntimeError(f"recovery load mismatch: {load_checks}")
        buttons = int(source["context"]["current_buttons"])
        campaign.set_held_input(m, buttons)
        safe = campaign.safe_checkpoint_rendezvous(
            m,
            states / f"safe-checkpoint-{args.mame_tick:05d}.mss",
            mame_tick=args.mame_tick,
            current_buttons=buttons,
        )
        context = recovered_context(source, safe, m)
        recovery.update(
            {
                "load_response": load_response,
                "load_checks": load_checks,
                "safe_checkpoint_sha256": safe["state"]["sha256"],
                "resume_mame_tick": safe["resume_mame_tick"],
                "architectural_mutations": m.architectural_mutations[
                    mutation_start:
                ],
            }
        )

    provenance = recovered_provenance(
        source, args.source_events, args.source_state, tool_hash
    )
    events = args.output / "events.jsonl"
    write_recovered_events(
        events, source, provenance, safe, context, recovery
    )
    root_identity = provenance["resume_lineage"]["root_identity"]
    expected_identity = {
        key: provenance.get(key) for key in root_identity
    }
    validated = campaign.validate_resume_lineage(
        events,
        Path(safe["state"]["path"]),
        int(safe["resume_mame_tick"]),
        str(provenance["rom_sha256"]),
        expected_identity,
    )
    summary = {
        "result": "green",
        "classification": "authenticated_checkpoint_recovery",
        "source": recovery,
        "safe": safe,
        "resume_context": context,
        "validated_lineage": validated,
        "events": str(events),
        "events_sha256": campaign.sha256(events),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "resume_mame_tick": safe["resume_mame_tick"],
                "state": safe["state"]["path"],
                "state_sha256": safe["state"]["sha256"],
                "events": str(events),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
