#!/usr/bin/env python3
"""Gate VTIME promotion on every declared accelerated execution boundary.

The opt-in VTIME image charges decoded interpreter instructions and two bounded
ledger families.  It cannot become a hardware-clock repair while loop collapses,
scheduler shortcuts, renderer/HLE paths, or idle pacing continue in a separate
instruction-countdown domain.  This is deliberately a *blocker* audit: its
green result means the incomplete design was correctly rejected, not that a ROM
or a gameplay rate is green.

It complements ``audit_stage3_vtime_coverage.py``.  That tool reads one active
Stage-3 trace; this one makes the source-declared accelerator boundary set
explicit, including bootstrap loops that do not occur in that trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Final


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE: Final = (
    ROOT
    / "build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/"
    "trace.json"
)
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")

# This is the boundary inventory, not a reachability claim for every generated
# escape.  Every item has an exact source label, an original program boundary,
# and an explicit VTIME ownership state.  ``selected-ledger`` means the current
# diagnostic has a bounded charge table for this entry only; it is not evidence
# that its surrounding call/return, scheduler, or IRQ paths share a clock.
BOUNDARIES: Final = (
    ("move_l_run_collapse", "src/interp.pasm", "mvc_check", "dynamic", "loop-collapse", "uncovered"),
    ("delay_003b84", "src/interp.pasm", "lh_delay", "003B84", "loop-collapse", "uncovered"),
    ("walking_byte_003fea", "src/escbank5.pasm", "lh_3fea_far", "003FEA", "loop-collapse", "uncovered"),
    ("walking_word_00adbe", "src/escbank5.pasm", "lh_adbe_far", "00ADBE", "loop-collapse", "uncovered"),
    ("generic_memclr", "src/interp.pasm", "gm_memclr", "dynamic", "loop-collapse", "uncovered"),
    ("generic_verify", "src/escbank5.pasm", "gm_verify_far", "dynamic", "loop-collapse", "uncovered"),
    ("generic_memset", "src/escbank5.pasm", "gm_memset_far", "dynamic", "loop-collapse", "uncovered"),
    ("scheduler_scan_00074c", "src/interp.pasm", "lh_sched", "00074C", "scheduler-shortcut", "uncovered"),
    ("scheduler_switch_out_000532", "src/escbank.pasm", "entry_swo", "000532", "scheduler-shortcut", "uncovered"),
    ("scheduler_switch_in_000796", "src/escbank.pasm", "entry_swin", "000796", "scheduler-shortcut", "uncovered"),
    ("scheduler_select_00075c", "src/escbank.pasm", "lhs_sel", "00075C", "scheduler-shortcut", "uncovered"),
    ("idle_pacing_000818", "src/escbank5.pasm", "lh_0818_paced", "000818", "idle-pacing", "uncovered"),
    ("collision_025110", "src/escbank7.pasm", "h25110_stage2_try", "025110", "native-hle", "selected-ledger"),
    ("stage3_player_013282", "src/escbank9.pasm", "entry_13282t", "013282", "native-hle", "selected-ledger"),
    ("stage3_player_013314", "src/escbank9.pasm", "entry_13314t", "013314", "native-hle", "selected-ledger"),
    ("stage3_player_01337e", "src/escbank9.pasm", "entry_1337et", "01337E", "native-hle", "selected-ledger"),
    ("stage3_player_0133ea", "src/escbank9.pasm", "entry_133eat", "0133EA", "native-hle", "selected-ledger"),
    ("stage3_player_013468", "src/escbank9.pasm", "entry_13468t", "013468", "native-hle", "selected-ledger"),
    ("stage3_player_013538", "src/escbank9.pasm", "entry_13538t", "013538", "native-hle", "selected-ledger"),
    ("stage3_tick_bridge_02429c", "src/escbank5.pasm", "entry_2429c", "02429C", "native-hle", "selected-ledger"),
    ("ce4_renderer", "src/escbank2.pasm", "entry_ce4t", "00CE4", "renderer-hle", "uncovered"),
)
TRACE_REQUIRED: Final = (
    "entry_25110",
    "entry_13282t",
    "entry_13314t",
    "entry_1337et",
    "entry_133eat",
    "entry_13468t",
    "entry_13538t",
    "entry_2429c",
    "entry_ce4t",
    "entry_swin",
    "entry_swo",
)
SELECTED_LEDGER_ENTRY_LABELS: Final = frozenset(
    {
        "entry_25110",
        "entry_13282t",
        "entry_13314t",
        "entry_1337et",
        "entry_133eat",
        "entry_13468t",
        "entry_13538t",
        "entry_2429c",
    }
)
MIGRATION_STRATEGIES: Final = {
    # A collapsed loop cannot debit its whole cost and then request an IRQ: an
    # original level-6 IRQ may be accepted between iterations.  It must either
    # expose original instruction boundaries or fall back before the first
    # virtual deadline it could cross.
    "loop-collapse": "split-at-deadline-or-fallback-to-interpreter",
    # The shortcut must commit an original basic block, then let the common
    # clock request delivery before beginning the next block/continuation.
    "scheduler-shortcut": "decoded-basic-block-ledger-with-pre-next-block-unwind",
    # The WAI replacement represents elapsed hardware video time, not a
    # fabricated instruction decrement.  Feed the observed epoch into the
    # shared phase/overshoot clock at the wake boundary.
    "idle-pacing": "observed-video-epoch-to-common-phase-boundary",
    "native-hle": "decoded-path-sensitive-basic-block-ledger",
    "renderer-hle": "decoded-path-sensitive-basic-block-ledger",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def labels_for(source: Path) -> set[str]:
    return {
        match.group(1)
        for line in source.read_text(encoding="utf-8").splitlines()
        if (match := LABEL.match(line))
    }


def active_entries(trace: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, count in dict(trace.get("event_counts", {})).items():
        if not int(count) or "@" not in str(label):
            continue
        name = str(label).split("@", 1)[0]
        counts[name] = counts.get(name, 0) + int(count)
    return counts


def audit(trace: dict[str, object], expected_rom_sha256: str | None) -> dict[str, object]:
    sources = sorted({ROOT / relative for _, relative, _, _, _, _ in BOUNDARIES})
    source_labels = {source: labels_for(source) for source in sources}
    boundaries: list[dict[str, object]] = []
    for name, relative, label, m68k_pc, family, state in BOUNDARIES:
        source = ROOT / relative
        if label not in source_labels[source]:
            raise RuntimeError(f"missing accelerator label {label} in {relative}")
        boundaries.append(
            {
                "name": name,
                "source": relative,
                "label": label,
                "m68k_entry": m68k_pc,
                "family": family,
                "vtime_state": state,
                "common_clock_covered": False,
                "required_migration_strategy": MIGRATION_STRATEGIES[family],
            }
        )

    entries = active_entries(trace)
    active_entry_labels = {
        name: count for name, count in entries.items() if name.startswith("entry_")
    }
    # These labels include continuation/end hooks, so they are intentionally
    # not asserted to be uncharged.  They are *unadmitted*: a future migration
    # must prove their route reaches an exact common-clock owner or add an
    # explicit ledger.  This prevents a seven-entry diagnostic allowlist from
    # silently being presented as complete Stage-3 coverage.
    unadmitted_entry_labels = {
        name: count
        for name, count in active_entry_labels.items()
        if name not in SELECTED_LEDGER_ENTRY_LABELS
    }
    missing_trace_entries = [name for name in TRACE_REQUIRED if name not in entries]
    uncovered = [row for row in boundaries if row["vtime_state"] == "uncovered"]
    selected = [row for row in boundaries if row["vtime_state"] == "selected-ledger"]
    expected_ok = expected_rom_sha256 is None or trace.get("rom_sha256") == expected_rom_sha256
    return {
        "scope": (
            "current-source accelerated-boundary inventory plus one authenticated "
            "Stage-3 trace. A green result means promotion is correctly blocked; "
            "it is not a ROM, MAME lockstep, rate, or gameplay acceptance."
        ),
        "trace_rom_sha256": trace.get("rom_sha256"),
        "expected_rom_sha256": expected_rom_sha256,
        "trace_required_entries": list(TRACE_REQUIRED),
        "trace_required_missing": missing_trace_entries,
        "trace_active_entries": entries,
        "trace_active_entry_labels": active_entry_labels,
        "selected_ledger_entry_labels": sorted(SELECTED_LEDGER_ENTRY_LABELS),
        "trace_unadmitted_entry_labels": unadmitted_entry_labels,
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
        "boundaries": boundaries,
        "uncovered_boundaries": uncovered,
        "selected_ledger_boundaries": selected,
        "all_declared_boundaries_share_common_clock": False,
        "all_active_trace_entries_admitted_to_common_clock": False,
        "promotion_blocked": True,
        "required_before_promotion": (
            "replace every uncovered loop, scheduler, idle, renderer, and native/HLE "
            "boundary with its declared exact common-clock strategy; then "
            "repeat fresh MAME/native-off/native-on IRQ and gameplay validation"
        ),
        "result": "green" if expected_ok and not missing_trace_entries and uncovered else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--expected-rom-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.trace.is_file():
        parser.error(f"missing trace: {args.trace}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    report = audit(trace, args.expected_rom_sha256)
    report["trace"] = str(args.trace.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "uncovered": len(report["uncovered_boundaries"]), "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
