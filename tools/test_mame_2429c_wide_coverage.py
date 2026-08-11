#!/usr/bin/env python3
"""Guard the widened exact-MAME `$02429C` coverage gap.

The controller movie revisits the same root arm 141 times through and beyond
the known IRQ failure window.  That is valuable negative coverage: it must
not be silently described as a complete root/child timing ledger merely
because the observed subset is large.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "build/mame-2429c-irq-phase-current-f369-wide-v1/summary.json"
CHILD = ROOT / "build/validate-mame-2429c-native-child-timing-current-f369-wide-v1.json"
BRANCH = ROOT / "build/validate-mame-2429c-branch-timing-current-f369-wide-v1.json"
POST_CAPTURE = ROOT / "build/mame-2429c-irq-phase-current-f369-postdivergence-v1/summary.json"
POST_CHILD = ROOT / "build/validate-mame-2429c-native-child-timing-current-f369-postdivergence-v1.json"
POST_BRANCH = ROOT / "build/validate-mame-2429c-branch-timing-current-f369-postdivergence-v1.json"
MAME_SHA256 = "297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f"
CHILD_GAPS = ["02360C", "023618", "023660", "025A0E"]
ROOT_GAPS = [
    "0242EE", "0242FE", "024310", "02432C", "02433E", "02437E",
    "024388", "02439A", "0243AC", "0243D2",
]


def main() -> int:
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    child = json.loads(CHILD.read_text(encoding="utf-8"))
    branch = json.loads(BRANCH.read_text(encoding="utf-8"))
    post_capture = json.loads(POST_CAPTURE.read_text(encoding="utf-8"))
    post_child = json.loads(POST_CHILD.read_text(encoding="utf-8"))
    post_branch = json.loads(POST_BRANCH.read_text(encoding="utf-8"))
    assert capture["mame"] == {
        "gnome_content_revision": "263",
        "path": "/tmp/mame-4339-recovery/root/mame",
        "sha256": MAME_SHA256,
        "snap_revision": "4339",
        "version": "0.287 (mame0287)",
    }
    assert capture["capture"]["tick_min"] == 14720
    assert capture["capture"]["tick_max"] == 14860
    assert capture["capture"]["events"] == 70436
    assert child["result"] == branch["result"] == "green"
    assert sum(child["observed_counts"].values()) == 4371
    assert child["observed_counts"]["023342"] == 141
    assert child["unobserved_dynamic_child_pcs"] == CHILD_GAPS
    assert branch["observed_counts"] == {
        "0242A2": 141,
        "0242C8": 141,
        "0242E6": 705,
        "0243E0": 705,
    }
    assert branch["unobserved_root_dynamic_pcs"] == ROOT_GAPS
    assert not child["failures"] and not branch["failures"]
    assert post_capture["mame"] == capture["mame"]
    assert post_capture["capture"]["tick_min"] == 14861
    assert post_capture["capture"]["tick_max"] == 15000
    assert post_capture["capture"]["events"] == 56179
    assert post_child["result"] == post_branch["result"] == "green"
    assert sum(post_child["observed_counts"].values()) == 4340
    assert post_child["observed_counts"]["023342"] == 140
    assert post_child["unobserved_dynamic_child_pcs"] == CHILD_GAPS
    assert post_branch["observed_counts"] == {
        "0242A2": 140,
        "0242C8": 140,
        "0242E6": 700,
        "0243E0": 700,
    }
    assert post_branch["unobserved_root_dynamic_pcs"] == ROOT_GAPS
    assert not post_child["failures"] and not post_branch["failures"]
    print("$02429C widened exact-MAME coverage guard: green (gaps retained through tick 15000)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
