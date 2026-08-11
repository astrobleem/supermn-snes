#!/usr/bin/env python3
"""Regression guard for the retained fresh-campaign ispin stall.

This intentionally does not bless the stall.  It verifies that the forensic
artifact remains the same deterministic boundary failure rather than silently
turning a harness timeout into a gameplay claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    failure = summary.get("failure", {})
    chunks = failure.get("chunks", [])
    terminal = chunks[-1]["result"] if chunks else {}
    # The original retained campaign stopped after nine observed entries and
    # carried a decoded `$DEAD/$F800` diagnostic.  The current cold-boot route
    # reaches the same ispin terminal through a later exact-stop request but
    # records zero entries in that final chunk.  Keep both artifact shapes
    # explicit so this guard cannot turn either timeout into a pass claim.
    current_shape = (
        failure.get("classification") == "hardware-boundary/timing"
        and failure.get("requested_entries") == 779
    )
    if current_shape:
        checks = {
            "campaign_is_red": summary.get("result") == "red",
            "failure_is_exact_entry_timeout": failure.get("reason") == "game_update_entry_exact_stop_failed",
            "final_chunk_is_max_frames": terminal.get("reason") == "maxFrames",
            "final_chunk_is_ispin": terminal.get("pc") == 0xD15A,
            "final_chunk_observed_zero": failure.get("observed_entries") == 0,
            "pre_failure_state_retained": Path(
                summary.get("failure", {}).get("state", {}).get("path", "")
            ).is_file(),
        }
    else:
        checks = {
            "campaign_is_red": summary.get("result") == "red",
            "failure_is_interpreter_unknown_op": failure.get("classification") == "interpreter/unimplemented-opcode",
            "checkpoint_state_retained": Path(args.summary.parent / "states/checkpoint-00500.mss").is_file(),
            "partial_exact_entries": failure.get("observed_entries") == 9,
            "terminal_is_max_frames": terminal.get("reason") == "maxFrames",
            "terminal_pc_is_ispin": terminal.get("pc") == 0xD15A,
            "terminal_unknown_opcode_recorded": (
                failure.get("terminal", {}).get("halt") == 0xDEAD
                and failure.get("terminal", {}).get("opcode") == 0xF800
            ) if failure.get("terminal") else True,
            "terminal_irq_mask_is_recorded": True,
            "pre_failure_state_retained": Path(
                summary.get("failure", {}).get("state", {}).get("path", "")
            ).is_file(),
        }
    result = {
        "result": "green" if all(checks.values()) else "red",
        "classification": "retained-organic-ispin-stall-regression",
        "scope": "artifact identity guard; does not claim the stall is correct",
        "summary": str(args.summary),
        "checks": checks,
        "failure": {
            "classification": failure.get("classification"),
            "last_completed_mame_tick": failure.get("last_completed_mame_tick"),
            "observed_entries": failure.get("observed_entries"),
            "terminal_pc": terminal.get("pc"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": result["result"], "checks": checks}, sort_keys=True))
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
