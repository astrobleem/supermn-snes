#!/usr/bin/env python3
"""Pin the current-hash `$02429C` MAME/native route differential evidence.

This validates the retained artifact's scope and comparison rows; it does not
rerun emulators and must never be represented as fresh-boot or IRQ-phase proof.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build/validate-2429c-distinct-arm-isolated-a976-pinned-v2.jsonl"
ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def main() -> int:
    rows = [json.loads(line) for line in REPORT.read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["event"] == "provenance"
    provenance = rows[0]
    assert provenance["rom_sha256"] == ROM_SHA256
    assert provenance["capture_rom_sha256"] == ROM_SHA256
    assert provenance["mame"]["version"] == "0.287 (mame0287)"
    assert provenance["fixtures"] == 4 and provenance["variants_per_fixture"] == 3
    cases = [row for row in rows if row.get("event") == "case"]
    assert len(cases) == 12
    expected_routes = {(0, 0), (1, 0), (1, 1)}
    by_case: dict[str, set[tuple[int, int]]] = {}
    for row in cases:
        assert row["result"] == "green"
        assert not row["reg_mismatches"]
        assert row["work_mismatch_count"] == 0
        assert row["mame_ccr"] == row["nexen_ccr"]
        assert row["mame_mask"] == row["nexen_mask"]
        assert row["allowed_native_return_residue"]["all_valid"] is True
        by_case.setdefault(row["case"], set()).add(
            (row["nested_xlat_gate"], row["fetch_choke_gate"])
        )
    assert len(by_case) == 4 and all(routes == expected_routes for routes in by_case.values())
    summary = rows[-1]
    assert summary == {"event": "summary", "green": 12, "red": 0, "result": "green", "time": summary["time"], "total": 12}
    print("active $02429C MAME/native route evidence regression: green (IRQ-masked fixture-local)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
