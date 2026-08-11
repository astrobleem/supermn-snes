#!/usr/bin/env python3
"""Pin the rejected fresh one-credit result for the VTIME helper variant.

This deliberately guards a *red* diagnostic result.  It prevents the failure
from being forgotten or misreported as proof that the accepted production ROM
regressed.  The image is a VTIME/interpreter-only experiment and is not the
active ``build/interp.sfc`` ROM.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build/validate-vtime-interpreter-only-native-handoff-fresh-prompt-v1/summary.json"
ROM_SHA256 = "598f0acc255ee703188caab39e44b0475f87f23311fc82a2e0c41128c1af1d91"
PRODUCTION_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    checks = report["checks"]
    assert report["result"] == "red"
    assert report["rom_sha256"] == ROM_SHA256
    assert report["rom_sha256"] != PRODUCTION_SHA256
    assert report["scope"].startswith("fresh-power-on one-credit")
    assert report["runtime_memory_writes"] == []
    assert report["snapshot"]["task_mask_f00002"] == 3
    assert report["snapshot"]["halt_iram_004e"] == 0
    assert report["snapshot"]["credits_f01c62"] == 0
    assert checks["task_mask_nonzero"] and checks["halt_zero"]
    for name in (
        "fresh_credit_count_is_one",
        "right_artwork_wedge_has_no_black_gap",
        "credit_text_preserves_artwork_underlay",
        "lower_right_status_garbage_absent",
    ):
        assert checks[name] is False, f"diagnostic failure unexpectedly changed: {name}"
    assert report["pixels"]["right_wedge_black_count"] == 775
    assert report["pixels"]["credit_box_artwork_gray_pixels"] == 0
    assert report["pixels"]["lower_right_nonblack_pixels"] == 156
    assert report["state"]["path"].endswith("states/one-credit-prompt.mss")
    assert report["state"]["resumable_checkpoint"] is False
    print("VTIME interpreter-only native-handoff fresh prompt: red as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
