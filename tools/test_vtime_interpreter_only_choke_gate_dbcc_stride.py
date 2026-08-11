#!/usr/bin/env python3
"""Guard the aligned tick-14746 DBcc stride counterfactual."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-"
    "choke-gate-task15-14746-boundary-root-vtwrite-v1"
)
CUMULATIVE = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-"
    "choke-gate-dbcc-stride-task15-14746-to14747-v1"
)


def main() -> int:
    report = json.loads(
        (EVIDENCE / "dbcc-stride-counterfactual.json").read_text(encoding="utf-8")
    )
    assert report["counts"] == {
        "dbcc_equal_pairs": 493,
        "dbcc_pcs": 22,
        "equal_pc_pairs": 10_100,
    }
    charge = report["charge"]
    assert charge == {
        "candidate_aligned_dbcc_units": 2833.0,
        "counterfactual_candidate_endpoint_units": 61031.0,
        "counterfactual_delta_cycles": 664.0,
        "counterfactual_delta_units": 332.0,
        "dbcc_stride_correction_units": -246.0,
        "mame_aligned_dbcc_units": 2587.0,
        "mame_endpoint_units": 60699.0,
        "original_candidate_endpoint_units": 61277.0,
        "original_delta_units": 578.0,
    }

    sites = {row["pc"]: row for row in report["dbcc_sites"]}
    assert sites["000FD4"]["correction_units"] == -108.0
    assert sites["0259C0"]["correction_units"] == -76.0
    assert sites["0008F0"]["correction_units"] == -58.0
    assert sites["000D70"]["correction_units"] == 42.0

    residual = report["residual_breakdown_after_dbcc_fix"]
    assert residual["equal_non_dbcc_delta_units"] == -15.0
    assert residual["unpaired_alignment_delta_units"] == 161.0
    assert residual["non_consume_adjustment_units"] == 186.0
    equal_sites = {
        row["pc"]: row for row in residual["equal_non_dbcc"]["top_sites"]
    }
    assert equal_sites["0259C8"]["delta_units"] == -8.0
    assert equal_sites["025A20"]["delta_units"] == -8.0
    assert equal_sites["00CA3E"]["delta_units"] == 2.0
    assert equal_sites["0008D8"]["delta_units"] == -1.0

    operations = residual["unpaired_alignment"]["operations"]
    assert [row["delta_units"] for row in operations] == [
        -45.0,
        50.0,
        326.0,
        -10.0,
        -160.0,
    ]
    assert operations[2]["candidate_len"] == 61
    assert operations[2]["candidate_range"] == [1400, 1461]
    # Deferred native root charge cancels the two zero-cost RTS rows and the
    # MAME-only native rows.  The honest remainder is path 326 + mask 5 +
    # common-path timing 1 = 332 units.
    assert -8 - 8 - 10 - 160 + 186 == 0
    assert 326 + (-45 + 50) + (2 - 1) == charge["counterfactual_delta_units"]

    cumulative = json.loads(
        (CUMULATIVE / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert cumulative["specific_symptoms"]["charge_comparability"] == (
        "not an aligned oracle comparison"
    )
    assert cumulative["mismatch_ranges"]["charge"]["new_delta_units"] == -19
    assert cumulative["mismatch_ranges"]["work"]["14746"][
        "task15_full_frame_equal"
    ] is False

    for filename in report["artifact_filenames"]:
        assert (EVIDENCE / filename).exists(), filename
    print("VTIME choke-gate DBcc stride counterfactual: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
