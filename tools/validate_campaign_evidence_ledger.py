#!/usr/bin/env python3
"""Audit and query reusable gameplay-campaign checkpoint lineages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "docs/current/CAMPAIGN_EVIDENCE_LEDGER.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rooted(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def require_equal(
    errors: list[str], label: str, observed: Any, expected: Any
) -> None:
    if observed != expected:
        errors.append(f"{label}: {observed!r} != {expected!r}")


def audit_lineage(name: str, lineage: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    dependencies = lineage["dependencies"]
    runtime = lineage["expected_runtime"]
    previous_end: int | None = None
    previous_checkpoint: str | None = None
    accepted_segments: list[dict[str, Any]] = []

    rom_path = rooted(lineage["rom"])
    if not rom_path.is_file():
        errors.append(f"missing ROM: {rom_path}")
    else:
        require_equal(
            errors,
            "ROM SHA-256",
            sha256(rom_path),
            lineage["rom_sha256"],
        )

    for index, segment in enumerate(lineage["segments"]):
        prefix = f"segment[{index}]"
        summary_path = rooted(segment["summary"])
        report_path = rooted(segment["report"])
        checkpoint_path = rooted(segment["checkpoint"])
        for label, path in (
            ("summary", summary_path),
            ("report", report_path),
            ("checkpoint", checkpoint_path),
        ):
            if not path.is_file():
                errors.append(f"{prefix}: missing {label}: {path}")
        if not summary_path.is_file():
            continue

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        require_equal(errors, f"{prefix}.result", summary.get("result"), runtime["result"])
        require_equal(errors, f"{prefix}.failure", summary.get("failure"), None)
        require_equal(
            errors,
            f"{prefix}.first_oracle_divergence",
            summary.get("first_oracle_divergence"),
            None,
        )
        require_equal(
            errors,
            f"{prefix}.oracle_divergence_count",
            summary.get("oracle_divergence_count"),
            0,
        )
        require_equal(
            errors,
            f"{prefix}.rom_sha256",
            summary.get("rom_sha256"),
            lineage["rom_sha256"],
        )
        for field, expected in dependencies.items():
            require_equal(errors, f"{prefix}.{field}", summary.get(field), expected)
        require_equal(
            errors,
            f"{prefix}.lineage_kind",
            summary.get("lineage_kind"),
            segment["kind"],
        )
        require_equal(
            errors,
            f"{prefix}.segment_origin_tick",
            summary.get("segment_origin_tick"),
            segment["segment_origin_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.mame_end_tick",
            summary.get("mame_end_tick"),
            segment["end_tick"],
        )
        end = summary.get("end") or {}
        gates = end.get("gates") or {}
        require_equal(errors, f"{prefix}.end.mame_tick", end.get("mame_tick"), segment["end_tick"])
        require_equal(errors, f"{prefix}.end.halt", end.get("halt"), runtime["halt"])
        require_equal(
            errors,
            f"{prefix}.end.gates.xlat_071a",
            gates.get("xlat_071a"),
            runtime["xlat_gate_071a"],
        )
        require_equal(
            errors,
            f"{prefix}.end.gates.choke_073a",
            gates.get("choke_073a"),
            runtime["choke_gate_073a"],
        )

        if previous_end is not None:
            require_equal(
                errors,
                f"{prefix}.contiguous_origin",
                segment["segment_origin_tick"],
                previous_end + 1,
            )
            require_equal(
                errors,
                f"{prefix}.parent_checkpoint_sha256",
                segment.get("parent_checkpoint_sha256"),
                previous_checkpoint,
            )
            require_equal(
                errors,
                f"{prefix}.resume.state_sha256",
                (summary.get("resume") or {}).get("state_sha256"),
                previous_checkpoint,
            )

        checkpoint_hash = segment["checkpoint_sha256"]
        if checkpoint_path.is_file():
            require_equal(
                errors,
                f"{prefix}.checkpoint file SHA-256",
                sha256(checkpoint_path),
                checkpoint_hash,
            )
        matching_states = [
            state
            for state in summary.get("states", [])
            if state.get("resumable_checkpoint") is True
            and state.get("sha256") == checkpoint_hash
        ]
        require_equal(
            errors,
            f"{prefix}.identical resumable checkpoint copies",
            len(matching_states),
            segment["identical_checkpoint_copies"],
        )
        event_log = rooted(summary.get("event_log", ""))
        if not event_log.is_file():
            errors.append(f"{prefix}: missing event log: {event_log}")
        else:
            require_equal(
                errors,
                f"{prefix}.event_log_sha256",
                sha256(event_log),
                summary.get("event_log_sha256"),
            )

        accepted_segments.append(
            {
                "origin_tick": segment["segment_origin_tick"],
                "end_tick": segment["end_tick"],
                "checkpoint": segment["checkpoint"],
                "checkpoint_sha256": checkpoint_hash,
                "resume_tick": segment["resume_tick"],
            }
        )
        previous_end = segment["end_tick"]
        previous_checkpoint = checkpoint_hash

    for index, recovery in enumerate(lineage.get("recovered_checkpoints", [])):
        prefix = f"recovered_checkpoint[{index}]"
        source_summary_path = rooted(recovery["source_summary"])
        source_events_path = rooted(recovery["source_events"])
        source_state_path = rooted(recovery["source_state"])
        recovery_summary_path = rooted(recovery["recovery_summary"])
        recovery_events_path = rooted(recovery["recovery_events"])
        checkpoint_path = rooted(recovery["checkpoint"])
        paths = (
            ("source summary", source_summary_path),
            ("source events", source_events_path),
            ("source state", source_state_path),
            ("recovery summary", recovery_summary_path),
            ("recovery events", recovery_events_path),
            ("checkpoint", checkpoint_path),
        )
        for label, path in paths:
            if not path.is_file():
                errors.append(f"{prefix}: missing {label}: {path}")
        if not all(path.is_file() for _label, path in paths):
            continue

        source_summary = json.loads(
            source_summary_path.read_text(encoding="utf-8")
        )
        recovered = json.loads(
            recovery_summary_path.read_text(encoding="utf-8")
        )
        require_equal(
            errors,
            f"{prefix}.source.result",
            source_summary.get("result"),
            "red",
        )
        require_equal(
            errors,
            f"{prefix}.source.first_oracle_divergence",
            source_summary.get("first_oracle_divergence"),
            None,
        )
        require_equal(
            errors,
            f"{prefix}.source.oracle_divergence_count",
            source_summary.get("oracle_divergence_count"),
            0,
        )
        require_equal(
            errors,
            f"{prefix}.source.segment_origin_tick",
            source_summary.get("segment_origin_tick"),
            recovery["source_segment_origin_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.source.rom_sha256",
            source_summary.get("rom_sha256"),
            lineage["rom_sha256"],
        )
        for field, expected in dependencies.items():
            require_equal(
                errors,
                f"{prefix}.source.{field}",
                source_summary.get(field),
                expected,
            )
        require_equal(
            errors,
            f"{prefix}.source events SHA-256",
            sha256(source_events_path),
            source_summary.get("event_log_sha256"),
        )
        require_equal(
            errors,
            f"{prefix}.source state SHA-256",
            sha256(source_state_path),
            recovery["source_state_sha256"],
        )

        safe = recovered.get("safe") or {}
        state = safe.get("state") or {}
        context = recovered.get("resume_context") or {}
        source = recovered.get("source") or {}
        checkpoint_hash = recovery["checkpoint_sha256"]
        require_equal(errors, f"{prefix}.result", recovered.get("result"), "green")
        require_equal(
            errors,
            f"{prefix}.classification",
            recovered.get("classification"),
            "authenticated_checkpoint_recovery",
        )
        require_equal(
            errors,
            f"{prefix}.accepted through tick",
            context.get("mame_tick_completed"),
            recovery["accepted_through_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.resume tick",
            context.get("resume_mame_tick"),
            recovery["resume_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.oracle divergence count",
            context.get("oracle_divergence_count"),
            0,
        )
        require_equal(
            errors,
            f"{prefix}.first oracle divergence",
            context.get("first_oracle_divergence"),
            None,
        )
        require_equal(
            errors,
            f"{prefix}.source state provenance",
            source.get("source_state_sha256"),
            recovery["source_state_sha256"],
        )
        require_equal(
            errors,
            f"{prefix}.safe state SHA-256",
            state.get("sha256"),
            checkpoint_hash,
        )
        require_equal(
            errors,
            f"{prefix}.safe boundary kind",
            state.get("boundary_kind"),
            "post_entry_safe_snes_boundary",
        )
        require_equal(
            errors,
            f"{prefix}.safe resumable",
            state.get("resumable_checkpoint"),
            True,
        )
        require_equal(
            errors,
            f"{prefix}.checkpoint file SHA-256",
            sha256(checkpoint_path),
            checkpoint_hash,
        )
        require_equal(
            errors,
            f"{prefix}.recovery events SHA-256",
            sha256(recovery_events_path),
            recovered.get("events_sha256"),
        )
        repeat_hashes = safe.get("repeat_save_hashes") or []
        require_equal(
            errors,
            f"{prefix}.identical resumable checkpoint copies",
            len(repeat_hashes),
            recovery["identical_checkpoint_copies"],
        )
        if any(value != checkpoint_hash for value in repeat_hashes):
            errors.append(f"{prefix}: repeated safe checkpoint hashes differ")
        if previous_end is not None and recovery["accepted_through_tick"] <= previous_end:
            errors.append(
                f"{prefix}: recovery does not extend accepted coverage"
            )

        accepted_segments.append(
            {
                "kind": "authenticated_checkpoint_recovery",
                "origin_tick": recovery["source_segment_origin_tick"],
                "end_tick": recovery["accepted_through_tick"],
                "checkpoint": recovery["checkpoint"],
                "checkpoint_sha256": checkpoint_hash,
                "resume_tick": recovery["resume_tick"],
            }
        )
        previous_end = recovery["accepted_through_tick"]
        previous_checkpoint = checkpoint_hash

    for index, segment in enumerate(lineage.get("post_recovery_segments", [])):
        prefix = f"post_recovery_segment[{index}]"
        summary_path = rooted(segment["summary"])
        report_path = rooted(segment["report"])
        checkpoint_path = rooted(segment["checkpoint"])
        for label, path in (
            ("summary", summary_path),
            ("report", report_path),
            ("checkpoint", checkpoint_path),
        ):
            if not path.is_file():
                errors.append(f"{prefix}: missing {label}: {path}")
        if not summary_path.is_file():
            continue

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        require_equal(errors, f"{prefix}.result", summary.get("result"), runtime["result"])
        require_equal(errors, f"{prefix}.failure", summary.get("failure"), None)
        require_equal(
            errors,
            f"{prefix}.first_oracle_divergence",
            summary.get("first_oracle_divergence"),
            None,
        )
        require_equal(
            errors,
            f"{prefix}.oracle_divergence_count",
            summary.get("oracle_divergence_count"),
            0,
        )
        require_equal(
            errors,
            f"{prefix}.rom_sha256",
            summary.get("rom_sha256"),
            lineage["rom_sha256"],
        )
        for field, expected in dependencies.items():
            require_equal(errors, f"{prefix}.{field}", summary.get(field), expected)
        require_equal(
            errors,
            f"{prefix}.lineage_kind",
            summary.get("lineage_kind"),
            segment["kind"],
        )
        require_equal(
            errors,
            f"{prefix}.segment_origin_tick",
            summary.get("segment_origin_tick"),
            segment["segment_origin_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.mame_end_tick",
            summary.get("mame_end_tick"),
            segment["end_tick"],
        )
        end = summary.get("end") or {}
        gates = end.get("gates") or {}
        require_equal(errors, f"{prefix}.end.mame_tick", end.get("mame_tick"), segment["end_tick"])
        require_equal(errors, f"{prefix}.end.halt", end.get("halt"), runtime["halt"])
        require_equal(
            errors,
            f"{prefix}.end.gates.xlat_071a",
            gates.get("xlat_071a"),
            runtime["xlat_gate_071a"],
        )
        require_equal(
            errors,
            f"{prefix}.end.gates.choke_073a",
            gates.get("choke_073a"),
            runtime["choke_gate_073a"],
        )
        require_equal(
            errors,
            f"{prefix}.contiguous_origin",
            segment["segment_origin_tick"],
            (previous_end + 1) if previous_end is not None else None,
        )
        require_equal(
            errors,
            f"{prefix}.parent_checkpoint_sha256",
            segment.get("parent_checkpoint_sha256"),
            previous_checkpoint,
        )
        require_equal(
            errors,
            f"{prefix}.resume.state_sha256",
            (summary.get("resume") or {}).get("state_sha256"),
            previous_checkpoint,
        )

        checkpoint_hash = segment["checkpoint_sha256"]
        if checkpoint_path.is_file():
            require_equal(
                errors,
                f"{prefix}.checkpoint file SHA-256",
                sha256(checkpoint_path),
                checkpoint_hash,
            )
        matching_states = [
            state
            for state in summary.get("states", [])
            if state.get("resumable_checkpoint") is True
            and state.get("sha256") == checkpoint_hash
        ]
        require_equal(
            errors,
            f"{prefix}.identical resumable checkpoint copies",
            len(matching_states),
            segment["identical_checkpoint_copies"],
        )
        event_log = rooted(summary.get("event_log", ""))
        if not event_log.is_file():
            errors.append(f"{prefix}: missing event log: {event_log}")
        else:
            require_equal(
                errors,
                f"{prefix}.event_log_sha256",
                sha256(event_log),
                summary.get("event_log_sha256"),
            )

        accepted_segments.append(
            {
                "kind": "checkpoint_continuation",
                "origin_tick": segment["segment_origin_tick"],
                "end_tick": segment["end_tick"],
                "checkpoint": segment["checkpoint"],
                "checkpoint_sha256": checkpoint_hash,
                "resume_tick": segment["resume_tick"],
            }
        )
        previous_end = segment["end_tick"]
        previous_checkpoint = checkpoint_hash

    for index, prefix_checkpoint in enumerate(
        lineage.get("red_prefix_checkpoints", [])
    ):
        prefix = f"red_prefix_checkpoint[{index}]"
        summary_path = rooted(prefix_checkpoint["source_summary"])
        report_path = rooted(prefix_checkpoint["source_report"])
        event_log_path = rooted(prefix_checkpoint["source_events"])
        checkpoint_path = rooted(prefix_checkpoint["checkpoint"])
        for label, path in (
            ("source summary", summary_path),
            ("source report", report_path),
            ("source events", event_log_path),
            ("checkpoint", checkpoint_path),
        ):
            if not path.is_file():
                errors.append(f"{prefix}: missing {label}: {path}")
        if not all(
            path.is_file()
            for path in (summary_path, report_path, event_log_path, checkpoint_path)
        ):
            continue

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        first_divergence = summary.get("first_oracle_divergence") or {}
        divergence_tick = first_divergence.get("mame_tick")
        checkpoint_hash = prefix_checkpoint["checkpoint_sha256"]
        require_equal(errors, f"{prefix}.result", summary.get("result"), "red")
        require_equal(
            errors,
            f"{prefix}.oracle_divergence_count",
            summary.get("oracle_divergence_count"),
            1,
        )
        require_equal(
            errors,
            f"{prefix}.first divergence tick",
            divergence_tick,
            prefix_checkpoint["first_divergence_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.rom_sha256",
            summary.get("rom_sha256"),
            lineage["rom_sha256"],
        )
        for field, expected in dependencies.items():
            require_equal(errors, f"{prefix}.{field}", summary.get(field), expected)
        require_equal(
            errors,
            f"{prefix}.lineage_kind",
            summary.get("lineage_kind"),
            "checkpoint_continuation",
        )
        require_equal(
            errors,
            f"{prefix}.segment_origin_tick",
            summary.get("segment_origin_tick"),
            prefix_checkpoint["segment_origin_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.requested end tick",
            summary.get("mame_end_tick"),
            prefix_checkpoint["requested_end_tick"],
        )
        require_equal(
            errors,
            f"{prefix}.contiguous_origin",
            prefix_checkpoint["segment_origin_tick"],
            (previous_end + 1) if previous_end is not None else None,
        )
        require_equal(
            errors,
            f"{prefix}.parent_checkpoint_sha256",
            prefix_checkpoint.get("parent_checkpoint_sha256"),
            previous_checkpoint,
        )
        require_equal(
            errors,
            f"{prefix}.resume.state_sha256",
            (summary.get("resume") or {}).get("state_sha256"),
            previous_checkpoint,
        )
        if not (
            isinstance(divergence_tick, int)
            and prefix_checkpoint["accepted_through_tick"] < divergence_tick
        ):
            errors.append(
                f"{prefix}: checkpoint is not strictly before first divergence"
            )
        require_equal(
            errors,
            f"{prefix}.checkpoint file SHA-256",
            sha256(checkpoint_path),
            checkpoint_hash,
        )
        matching_states = [
            state
            for state in summary.get("states", [])
            if state.get("resumable_checkpoint") is True
            and state.get("sha256") == checkpoint_hash
        ]
        require_equal(
            errors,
            f"{prefix}.identical resumable checkpoint copies",
            len(matching_states),
            prefix_checkpoint["identical_checkpoint_copies"],
        )
        require_equal(
            errors,
            f"{prefix}.event log path",
            summary.get("event_log"),
            prefix_checkpoint["source_events"],
        )
        require_equal(
            errors,
            f"{prefix}.event log SHA-256",
            sha256(event_log_path),
            summary.get("event_log_sha256"),
        )

        accepted_segments.append(
            {
                "kind": "red_run_green_prefix_checkpoint",
                "origin_tick": prefix_checkpoint["segment_origin_tick"],
                "end_tick": prefix_checkpoint["accepted_through_tick"],
                "checkpoint": prefix_checkpoint["checkpoint"],
                "checkpoint_sha256": checkpoint_hash,
                "resume_tick": prefix_checkpoint["resume_tick"],
            }
        )
        previous_end = prefix_checkpoint["accepted_through_tick"]
        previous_checkpoint = checkpoint_hash

    return {
        "lineage": name,
        "valid": not errors,
        "errors": errors,
        "rom": lineage["rom"],
        "rom_sha256": lineage["rom_sha256"],
        "accepted_through_tick": previous_end,
        "newest_checkpoint": accepted_segments[-1] if accepted_segments else None,
        "segments": accepted_segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--lineage")
    parser.add_argument("--candidate-rom", type=Path)
    parser.add_argument("--target-tick", type=int)
    args = parser.parse_args()

    ledger_path = args.ledger if args.ledger.is_absolute() else ROOT / args.ledger
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    lineages = ledger["lineages"]
    if args.lineage:
        if args.lineage not in lineages:
            parser.error(f"unknown lineage: {args.lineage}")
        selected = {args.lineage: lineages[args.lineage]}
    else:
        selected = lineages

    audits = [audit_lineage(name, value) for name, value in selected.items()]
    output: dict[str, Any] = {
        "ledger": str(ledger_path),
        "valid": all(audit["valid"] for audit in audits),
        "lineages": audits,
    }

    if args.candidate_rom:
        if len(audits) != 1:
            parser.error("--candidate-rom requires exactly one selected lineage")
        candidate = args.candidate_rom
        candidate = candidate if candidate.is_absolute() else ROOT / candidate
        candidate_hash = sha256(candidate)
        audit = audits[0]
        latest = audit["newest_checkpoint"]
        if candidate_hash != audit["rom_sha256"]:
            decision = "incompatible_candidate"
        elif not audit["valid"]:
            decision = "ledger_invalid"
        elif args.target_tick is not None and args.target_tick <= audit["accepted_through_tick"]:
            decision = "already_covered"
        else:
            decision = "resume_from_newest_checkpoint"
        output["query"] = {
            "candidate_rom": str(candidate),
            "candidate_rom_sha256": candidate_hash,
            "target_tick": args.target_tick,
            "decision": decision,
            "accepted_through_tick": audit["accepted_through_tick"],
            "checkpoint": latest,
        }

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
