#!/usr/bin/env python3
"""Reduce the retained Stage-3 VTIME failure to one exact phase diagnosis.

This is an artifact validator, not an emulator runner.  It correlates the
original-MAME cycle trace with authenticated Nexen root-entry, root-terminal,
and route captures.  A green result means the *negative diagnosis* remains
reproducible: the VTIME candidate reaches task 15 with far too much time left,
even though the `$02429C` root's `$025110` child is interpreted rather than
silently re-accelerated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MAME_TICK = 14745
ROOT_ENTRY = "F38000"
ROOT_TERMINAL = "F38945"
FINAL_ROOT_ORDINAL = 35
PRE_ROOT_PHASES = (
    ("control_scheduler", 200997, 200997, 16, 0),
    ("scroll_player_prepass", 200999, 200999, 35, 2),
    ("player_renderer_fanout", 201000, 201000, 48, 4),
    ("selector_resume_tail", 201001, 201003, 8, 0),
    ("task15_pre_root", 201018, 201025, 78, 1),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"expected JSON object at {path}:{line_number}")
        rows.append(value)
    return rows


def unique_cycle(
    rows: list[dict[str, Any]], *, event: str, label: str, tick: int, first: bool = True
) -> int:
    cycles = sorted(
        {
            int(row["cycles"])
            for row in rows
            if row.get("event") == event
            and row.get("label") == label
            and int(row.get("tick", -1)) == tick
        }
    )
    if not cycles:
        raise RuntimeError(f"missing MAME {event}/{label} at tick {tick}")
    return cycles[0] if first else cycles[-1]


def exact_stop(report: dict[str, Any], address: str) -> bool:
    boundary = report.get("intermediate_boundary", {})
    stop = boundary.get("stop", {})
    observed = f"{((int(stop.get('k', 0)) & 0xFF) << 16) | (int(stop.get('pc', 0)) & 0xFFFF):06X}"
    return (
        boundary.get("address") == address
        and stop.get("reason") == "breakpoint"
        and stop.get("hit") is True
        and stop.get("exactStopTriggered") is True
        and stop.get("exactStopBreakDelivered") is True
        and observed == address
    )


def partition_pre_root_hits(
    hits: list[dict[str, Any]],
    selected_labels: set[str],
    unadmitted_labels: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition the retained pre-root window into its observed execution phases."""

    phases = []
    unclassified = []
    for phase, first_frame, last_frame, expected_unadmitted, expected_selected in PRE_ROOT_PHASES:
        phase_hits = [
            hit
            for hit in hits
            if first_frame <= int(hit.get("frame", -1)) <= last_frame
        ]
        selected: dict[str, int] = {}
        unadmitted: dict[str, int] = {}
        unknown: dict[str, int] = {}
        for hit in phase_hits:
            site = str(hit.get("site", ""))
            label = site.split("@", 1)[0]
            target = (
                selected
                if label in selected_labels
                else unadmitted
                if label in unadmitted_labels
                else unknown
            )
            target[site] = target.get(site, 0) + 1
        phases.append(
            {
                "phase": phase,
                "first_frame": first_frame,
                "last_frame": last_frame,
                "observed_hits": len(phase_hits),
                "selected_ledger_hits": sum(selected.values()),
                "unadmitted_hits": sum(unadmitted.values()),
                "unknown_hits": sum(unknown.values()),
                "expected_selected_ledger_hits": expected_selected,
                "expected_unadmitted_hits": expected_unadmitted,
                "top_unadmitted": [
                    {"label": name, "hits": count}
                    for name, count in sorted(
                        unadmitted.items(), key=lambda item: (-item[1], item[0])
                    )[:12]
                ],
            }
        )
    covered_ids = {
        id(hit)
        for phase in PRE_ROOT_PHASES
        for hit in hits
        if phase[1] <= int(hit.get("frame", -1)) <= phase[2]
    }
    unclassified.extend(hit for hit in hits if id(hit) not in covered_ids)
    return phases, unclassified


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-meta", type=Path, required=True)
    parser.add_argument("--root-entry", type=Path, required=True)
    parser.add_argument("--root-terminal", type=Path, required=True)
    parser.add_argument("--route-trace", type=Path, required=True)
    parser.add_argument("--pre-root-trace", type=Path, required=True)
    parser.add_argument("--coverage-audit", type=Path, required=True)
    parser.add_argument("--attribution", type=Path, required=True)
    parser.add_argument("--cost-table", type=Path, default=Path("src/vtime_esc5_charge_cost.bin"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("MAME metadata", args.mame_meta),
        ("root-entry capture", args.root_entry),
        ("root-terminal capture", args.root_terminal),
        ("route trace", args.route_trace),
        ("pre-root entry trace", args.pre_root_trace),
        ("accelerated-boundary audit", args.coverage_audit),
        ("work-RAM attribution", args.attribution),
        ("root cost table", args.cost_table),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    mame_rows = load_jsonl(args.mame_meta)
    root = load_json(args.root_entry)
    terminal = load_json(args.root_terminal)
    route = load_json(args.route_trace)
    pre_root = load_json(args.pre_root_trace)
    coverage = load_json(args.coverage_audit)
    attribution = load_json(args.attribution)
    costs = args.cost_table.read_bytes()
    if len(costs) != FINAL_ROOT_ORDINAL:
        raise RuntimeError(f"expected {FINAL_ROOT_ORDINAL} root costs, got {len(costs)}")

    mame_boundary = unique_cycle(
        mame_rows, event="boundary", label="game_tick", tick=MAME_TICK
    )
    mame_next_boundary = unique_cycle(
        mame_rows, event="boundary", label="game_tick", tick=MAME_TICK + 1
    )
    mame_root = unique_cycle(
        mame_rows, event="seam_fetch", label="task15_2429c", tick=MAME_TICK
    )
    mame_collision = unique_cycle(
        mame_rows, event="seam_fetch", label="collision_25110", tick=MAME_TICK
    )
    mame_irq = unique_cycle(
        mame_rows, event="seam_fetch", label="irq_6c4", tick=MAME_TICK
    )

    root_target = root["target_entry"]["vtime"]
    root_entry = root["intermediate_boundary"]["snapshot"]
    root_vtime = root_entry["vtime"]
    terminal_snapshot = terminal["intermediate_boundary"]["snapshot"]
    terminal_vtime = terminal_snapshot["vtime"]
    trace_counts = route["virtual_irq_entry"]["root_trace_counts"]
    pre_root_counts = {
        name: int(count)
        for name, count in pre_root["pre_intermediate_entry_trace"]["counts"].items()
        if int(count)
    }
    selected_labels = set(coverage["selected_ledger_entry_labels"])
    unadmitted_labels = set(coverage["trace_unadmitted_entry_labels"])
    selected_pre_root = {
        name: count
        for name, count in pre_root_counts.items()
        if name.split("@", 1)[0] in selected_labels
    }
    unadmitted_pre_root = {
        name: count
        for name, count in pre_root_counts.items()
        if name.split("@", 1)[0] in unadmitted_labels
    }
    pre_root_phases, unclassified_pre_root_hits = partition_pre_root_hits(
        pre_root["pre_intermediate_entry_trace"]["hits"],
        selected_labels,
        unadmitted_labels,
    )
    final_cost_units = costs[FINAL_ROOT_ORDINAL - 1]

    target_remaining_units = int(root_target["remaining_two_cycle_units"])
    root_remaining_units = int(root_vtime["remaining_two_cycle_units"])
    terminal_preflush_units = int(terminal_vtime["remaining_two_cycle_units"])
    terminal_postflush_units = terminal_preflush_units - final_cost_units

    mame_boundary_to_root = mame_root - mame_boundary
    mame_root_to_irq = mame_irq - mame_root
    snes_target_to_root_cycles = 2 * (target_remaining_units - root_remaining_units)
    pre_root_undercharge_cycles = mame_boundary_to_root - snes_target_to_root_cycles
    root_phase_lateness_cycles = 2 * root_remaining_units - mame_root_to_irq
    snes_root_charge_to_terminal_cycles = 2 * (
        root_remaining_units - terminal_postflush_units
    )

    checks = {
        "shared_candidate_rom": root["rom"]["sha256"] == terminal["rom"]["sha256"] == route["rom"]["sha256"],
        "shared_checkpoint": root["checkpoint"]["sha256"] == terminal["checkpoint"]["sha256"] == route["checkpoint"]["sha256"],
        "root_entry_exact": exact_stop(root, ROOT_ENTRY),
        "root_terminal_exact": exact_stop(terminal, ROOT_TERMINAL),
        "root_entry_task15": (
            root_entry["logical_pc"] == "02429C"
            and int(root_entry["scheduler"]["current_task_f00004"]) == 15
        ),
        "root_terminal_before_deadline": (
            int(terminal_vtime["due"]) == 0
            and int(terminal_vtime["native_owner"]) == 5
            and int(terminal_vtime["native_pending"]) == FINAL_ROOT_ORDINAL
            and terminal_postflush_units > 0
        ),
        "collision_child_not_reaccelerated": (
            int(trace_counts["collision_native_entry"]) == 0
            and int(trace_counts["esc3_charge_entry"]) == 0
            and int(trace_counts["esc3_reset_entry"]) == 0
            and int(trace_counts["esc3_finish_entry"]) == 0
        ),
        "root_route_observed": (
            int(trace_counts["root_entry"]) == 1
            and int(trace_counts["root_charge_gateway"]) == 20
            and int(trace_counts["root_child_handoff"]) == 5
            and int(trace_counts["root_terminal_handoff"]) == 1
        ),
        "pre_root_inventory_is_broad": (
            len(pre_root_counts) == 59 and sum(pre_root_counts.values()) == 192
        ),
        "pre_root_inventory_is_mostly_unadmitted": (
            len(unadmitted_pre_root) == 52
            and sum(unadmitted_pre_root.values()) == 185
            and sum(selected_pre_root.values()) == 7
        ),
        "pre_root_phase_partition_is_complete": (
            not unclassified_pre_root_hits
            and sum(phase["observed_hits"] for phase in pre_root_phases) == 192
            and sum(phase["unadmitted_hits"] for phase in pre_root_phases) == 185
            and sum(phase["selected_ledger_hits"] for phase in pre_root_phases) == 7
            and all(
                phase["unknown_hits"] == 0
                and phase["unadmitted_hits"] == phase["expected_unadmitted_hits"]
                and phase["selected_ledger_hits"]
                == phase["expected_selected_ledger_hits"]
                for phase in pre_root_phases
            )
        ),
        "mame_irq_inside_collision": mame_root < mame_collision < mame_irq < mame_next_boundary,
        "pre_root_phase_gap_is_large": pre_root_undercharge_cycles > 100_000,
        "root_entry_is_already_late": root_phase_lateness_cycles > 100_000,
        "task_frame_first_diff_tick_14746": int(attribution["seam_comparison"]["first_differing_tick"]) == 14746,
        "downstream_false_hit_chain": (
            int(attribution["false_hit_comparison"]["first_marker_difference_tick"]) == 14839
            and int(attribution["false_hit_comparison"]["first_player_difference_tick"]) == 14840
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "scope": (
            "retained-artifact Stage-3 VTIME phase diagnosis; green means the "
            "negative root cause remains proven, not that gameplay or VTIME is accepted"
        ),
        "inputs": {
            label: {"path": str(path.resolve()), "sha256": sha256(path)}
            for label, path in (
                ("mame_meta", args.mame_meta),
                ("root_entry", args.root_entry),
                ("root_terminal", args.root_terminal),
                ("route_trace", args.route_trace),
                ("pre_root_trace", args.pre_root_trace),
                ("coverage_audit", args.coverage_audit),
                ("attribution", args.attribution),
                ("cost_table", args.cost_table),
            )
        },
        "mame_cycles": {
            "game_tick_14745": mame_boundary,
            "task15_root_02429c": mame_root,
            "collision_025110": mame_collision,
            "irq_handler_0006c4": mame_irq,
            "game_tick_14746": mame_next_boundary,
            "period_14745_to_14746": mame_next_boundary - mame_boundary,
            "boundary_to_root": mame_boundary_to_root,
            "root_to_irq": mame_root_to_irq,
            "collision_to_irq": mame_irq - mame_collision,
        },
        "snes_vtime": {
            "target_remaining_two_cycle_units": target_remaining_units,
            "root_remaining_two_cycle_units": root_remaining_units,
            "target_to_root_charged_cycles": snes_target_to_root_cycles,
            "terminal_preflush_two_cycle_units": terminal_preflush_units,
            "terminal_final_block_two_cycle_units": final_cost_units,
            "terminal_postflush_two_cycle_units": terminal_postflush_units,
            "root_to_terminal_charged_cycles": snes_root_charge_to_terminal_cycles,
            "route_counts": trace_counts,
            "pre_root_inventory": {
                "observed_entry_labels": len(pre_root_counts),
                "observed_hits": sum(pre_root_counts.values()),
                "selected_ledger_labels": selected_pre_root,
                "selected_ledger_hits": sum(selected_pre_root.values()),
                "unadmitted_labels": len(unadmitted_pre_root),
                "unadmitted_hits": sum(unadmitted_pre_root.values()),
                "top_unadmitted": [
                    {"label": name, "hits": count}
                    for name, count in sorted(
                        unadmitted_pre_root.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:16]
                ],
                "phase_partition": pre_root_phases,
                "unclassified_hits": unclassified_pre_root_hits,
            },
        },
        "diagnosis": {
            "pre_root_undercharge_cycles": pre_root_undercharge_cycles,
            "root_entry_phase_lateness_cycles": root_phase_lateness_cycles,
            "mame_irq_location": "inside $025110 at $0259B0/$0242BE",
            "snes_irq_location": "after task 15 returned, at interpreter $000818",
            "classification": (
                "The candidate is already about 115K MC68000 cycles late when "
                "task 15 enters `$02429C`. The root's `$025110` child is genuinely "
                "interpreted, so the retained failure is upstream/global common-clock "
                "coverage, not a hidden collision re-acceleration or final-root flush bug."
            ),
            "safe_narrow_fix_available": False,
        },
        "downstream": {
            "task_frame_first_difference_tick": attribution["seam_comparison"]["first_differing_tick"],
            "false_hit_marker_tick": attribution["false_hit_comparison"]["first_marker_difference_tick"],
            "player_difference_tick": attribution["false_hit_comparison"]["first_player_difference_tick"],
        },
        "checks": checks,
        "failed_checks": failed,
        "result": "green" if not failed else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve()), "diagnosis": report["diagnosis"]}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
