#!/usr/bin/env python3
"""Prove a campaign's post-entry safe checkpoint resumes bit-exactly.

The source event log must be an uninterrupted fresh-power-on campaign that
retained a ``post_entry_safe_snes_boundary`` state.  This validator loads that
state in a fresh Nexen process, requires the immediate MCP-visible machine to
match the retained snapshot, re-saves it byte-identically, then replays the
original controller transitions through the campaign end.

The final exact-entry CPU/PPU/memory snapshot and save-state bytes must equal
the uninterrupted branch's retained campaign-end state.  This is checkpoint
serialization/control evidence, not a substitute for the uninterrupted
fresh-boot run that generated the direct branch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_TIMELINE = (
    EVIDENCE / "full-playback-timeline-v1" / "timeline.jsonl"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-safe-checkpoint-publish/Nexen"
)

sys.path.insert(0, str(ROOT / "tools"))
import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolve_recorded_path(value: str, event_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = (ROOT / path, event_path.parent / path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return (ROOT / path).resolve()


def require_single(
    rows: list[dict[str, Any]],
    event: str,
) -> dict[str, Any]:
    matches = [row for row in rows if row.get("event") == event]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {event} event, found {len(matches)}"
        )
    return matches[0]


def public_snapshot(m: campaign.McpSession) -> dict[str, Any]:
    public, _raw = campaign.checkpoint_machine_snapshot(m)
    return public


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--lineage-events", type=Path, required=True)
    parser.add_argument("--safe-tick", type=int, required=True)
    parser.add_argument("--port", type=int, default=9590)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("timeline", args.timeline),
        ("Nexen", args.nexen),
        ("lineage events", args.lineage_events),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    rows = load_events(args.lineage_events)
    provenance = require_single(rows, "provenance")
    if provenance.get("lineage_kind") != "fresh_power_on_root":
        raise RuntimeError("lineage is not a fresh-power-on root")
    if provenance.get("rom_sha256") != sha256(args.rom):
        raise RuntimeError("lineage ROM does not match selected ROM")
    if provenance.get("mame_timeline_sha256") != sha256(args.timeline):
        raise RuntimeError("lineage timeline does not match selected timeline")

    safe_rows = [
        row
        for row in rows
        if row.get("event") == "safe_checkpoint"
        and int(row.get("mame_tick", -1)) == args.safe_tick
    ]
    if len(safe_rows) != 1:
        raise RuntimeError(
            f"expected one safe checkpoint at {args.safe_tick}, "
            f"found {len(safe_rows)}"
        )
    safe_row = safe_rows[0]
    safe_state = dict(safe_row.get("state", {}))
    safe_context = dict(safe_row.get("resume_context", {}))
    safe_checks = {
        "resumable": safe_state.get("resumable_checkpoint") is True,
        "safe_boundary": (
            safe_state.get("boundary_kind")
            == "post_entry_safe_snes_boundary"
        ),
        "not_nested_entry": (
            safe_state.get("entry_exact_bundle") is False
            and safe_state.get("nested_sa1_entry_nonresumable") is False
        ),
        "nonmutating_save": (
            safe_state.get("synchronous_completed") is True
            and safe_state.get("atomic_rename") is True
            and safe_state.get("live_state_unchanged") is True
            and safe_state.get("active_run_reloaded") is False
            and safe_state.get("active_run_memory_restored") is False
        ),
        "safe_phase": (
            safe_context.get("phase")
            == "post_entry_safe_snes_boundary"
        ),
        "completed_tick": (
            int(safe_context.get("mame_tick_completed", -1))
            == args.safe_tick
        ),
        "resume_tick": (
            int(safe_context.get("resume_mame_tick", -1))
            == args.safe_tick + 1
        ),
        "zero_prefix_divergence": (
            int(safe_context.get("oracle_divergence_count", -1)) == 0
        ),
    }
    if not all(safe_checks.values()):
        raise RuntimeError(f"safe checkpoint contract failed: {safe_checks}")

    safe_path = resolve_recorded_path(
        str(safe_state.get("path", "")), args.lineage_events
    )
    if (
        not safe_path.is_file()
        or sha256(safe_path) != safe_state.get("sha256")
    ):
        raise RuntimeError("safe checkpoint file is missing or unauthenticated")

    campaign_end = require_single(rows, "campaign_end")
    direct_end_state = dict(campaign_end.get("state", {}))
    direct_end_path = resolve_recorded_path(
        str(direct_end_state.get("path", "")), args.lineage_events
    )
    if (
        not direct_end_path.is_file()
        or sha256(direct_end_path) != direct_end_state.get("sha256")
    ):
        raise RuntimeError("direct campaign-end state is unauthenticated")
    direct_end_public = direct_end_state.get("resume_validation")
    if not isinstance(direct_end_public, dict):
        raise RuntimeError("direct campaign-end state lacks exact validation")

    end_tick = int(provenance["mame_end_tick"])
    resume_tick = args.safe_tick + 1
    inputs, tick_rows = campaign.load_timeline(
        args.timeline,
        int(provenance["mame_origin_tick"]),
        end_tick,
    )
    if any(event.tick == resume_tick for event in inputs):
        raise RuntimeError(
            "safe resume tick coincides with an input edge; choose a quiet "
            "safe-checkpoint boundary"
        )

    args.output.mkdir(parents=True)
    events: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "scope": (
                "fresh-process safe-checkpoint restoration and exact direct-"
                "versus-resumed continuation; source branch is an "
                "authenticated uninterrupted fresh-power-on campaign"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "nexen": str(args.nexen.resolve()),
            "nexen_identity": campaign.nexen_identity(args.nexen),
            "lineage_events": str(args.lineage_events.resolve()),
            "lineage_events_sha256": sha256(args.lineage_events),
            "safe_tick_completed": args.safe_tick,
            "resume_tick": resume_tick,
            "end_tick": end_tick,
            "safe_state": str(safe_path),
            "safe_state_sha256": sha256(safe_path),
            "direct_end_state": str(direct_end_path),
            "direct_end_state_sha256": sha256(direct_end_path),
            "validator_sha256": sha256(Path(__file__).resolve()),
            "campaign_harness_sha256": sha256(
                ROOT / "tools/replay_mame_controller_campaign.py"
            ),
            "time_unix": time.time(),
        }
    ]

    campaign.configure_dotnet(args.nexen)
    repeated_path = args.output / "fresh-load-immediate-resave.mss"
    resumed_end_path = args.output / "resumed-campaign-end.mss"
    comparisons = 0
    green_comparisons = 0
    first_mismatch: dict[str, Any] | None = None

    with campaign.AuditedMcpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        load_response = dict(m.load_state(str(safe_path)))
        campaign.require_paused(m, "safe-checkpoint load")
        immediate_public = public_snapshot(m)
        expected_immediate = safe_state.get("resume_validation")
        immediate_exact = immediate_public == expected_immediate
        if not immediate_exact:
            raise RuntimeError("fresh-process immediate safe state mismatch")

        repeated = campaign.save_state(
            m,
            repeated_path,
            boundary_kind="post_entry_safe_snes_boundary",
            post_entry_safe_proof=safe_state.get(
                "post_entry_safe_proof"
            ),
        )
        immediate_resave_exact = repeated["sha256"] == safe_state["sha256"]

        current_buttons = int(safe_context["current_buttons"])
        campaign.set_held_input(m, current_buttons)
        restore_mutations = list(m.architectural_mutations)
        if restore_mutations:
            raise RuntimeError(
                f"checkpoint restoration used architectural writes: "
                f"{restore_mutations}"
            )

        campaign.run_active_game_update_entries(m, 1)
        current_tick = resume_tick
        resume_player = campaign.player_snapshot(m)
        resume_compare = campaign.compare_player(
            resume_player, tick_rows[resume_tick]
        )
        comparisons += 1
        green_comparisons += resume_compare["result"] == "green"
        if resume_compare["result"] != "green":
            raise RuntimeError(
                f"resume entry {resume_tick} diverged: {resume_compare}"
            )

        scheduled: dict[int, list[tuple[str, campaign.InputEvent]]] = (
            defaultdict(list)
        )
        for event in inputs:
            if event.tick > resume_tick:
                scheduled[event.tick].append(("compare", event))
                scheduled[event.tick].append(("apply", event))
            response_tick = event.tick + 2
            if resume_tick < response_tick <= end_tick:
                scheduled[response_tick].append(("response", event))
        scheduled[end_tick].append(("end", campaign.InputEvent(
            tick=end_tick,
            buttons=current_buttons,
            reference=tick_rows[end_tick],
        )))

        for target_tick in sorted(scheduled):
            campaign.run_active_game_update_entries(
                m, target_tick - current_tick
            )
            current_tick = target_tick
            player = campaign.player_snapshot(m)
            for kind, event in scheduled[target_tick]:
                if kind == "apply":
                    campaign.set_held_input(m, event.buttons)
                    current_buttons = event.buttons
                    continue
                reference = (
                    event.reference
                    if kind == "compare"
                    else tick_rows[target_tick]
                )
                comparison = campaign.compare_player(player, reference)
                comparisons += 1
                if comparison["result"] == "green":
                    green_comparisons += 1
                elif first_mismatch is None:
                    first_mismatch = {
                        "kind": kind,
                        "tick": target_tick,
                        "comparison": comparison,
                    }

        if first_mismatch is not None:
            raise RuntimeError(
                f"resumed MAME player differential failed: {first_mismatch}"
            )

        resumed_end_public = public_snapshot(m)
        final_public_exact = resumed_end_public == direct_end_public
        resumed_end = campaign.save_state(m, resumed_end_path)
        final_state_bytes_exact = (
            resumed_end["sha256"] == direct_end_state["sha256"]
        )
        final_mutations = list(m.architectural_mutations)

    required_checks = {
        **safe_checks,
        "immediate_public_exact": immediate_exact,
        "resume_entry_player_exact": resume_compare["result"] == "green",
        "all_player_comparisons_green": (
            green_comparisons == comparisons and first_mismatch is None
        ),
        "direct_and_resumed_final_public_exact": final_public_exact,
        "zero_cpu_or_memory_transplants": not final_mutations,
    }
    archive_byte_observations = {
        "immediate_resave_bytes_exact": immediate_resave_exact,
        "direct_and_resumed_final_state_bytes_exact": (
            final_state_bytes_exact
        ),
        "interpretation": (
            "opaque serializer bytes canonicalize across a fresh load even "
            "when all exposed state is exact"
            if not immediate_resave_exact
            else "fresh-process archive bytes remained exact"
        ),
        "gameplay_acceptance_gate": False,
    }
    result = "green" if all(required_checks.values()) else "red"
    summary = {
        "event": "summary",
        "result": result,
        "required_checks": required_checks,
        "archive_byte_observations": archive_byte_observations,
        "player_comparisons_green": green_comparisons,
        "player_comparisons_total": comparisons,
        "first_mismatch": first_mismatch,
        "load_response": load_response,
        "immediate_resave": repeated,
        "resumed_end_state": resumed_end,
        "runtime_architectural_mutations": final_mutations,
        "safe_checkpoint_classification": (
            "serializer-safe main-SNES pre-opcode boundary"
        ),
        "nested_sa1_entry_states_remain_nonresumable": True,
    }
    events.append(summary)
    (args.output / "events.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in events),
        encoding="utf-8",
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
