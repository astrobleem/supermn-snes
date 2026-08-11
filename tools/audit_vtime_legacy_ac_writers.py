#!/usr/bin/env python3
"""Inventory every direct legacy `$AC` writer against the VTIME clock.

`$AC` is the production instruction-countdown.  An enabled VTIME image ignores
that countdown, so every direct writer has to be either an explicitly retained
compatibility write, a VTIME-owned implementation detail, or a migrated native
seam.  This audit intentionally reports the remaining writers as blockers; it
does not claim that the partial diagnostic is a common clock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Final


ROOT = Path(__file__).resolve().parents[1]
SOURCES: Final = (
    ROOT / "src" / "interp.pasm",
    ROOT / "src" / "escbank2.pasm",
    ROOT / "src" / "escbank3.pasm",
    ROOT / "src" / "escbank5.pasm",
    ROOT / "src" / "escbank6.pasm",
    ROOT / "src" / "escbank7.pasm",
    ROOT / "src" / "escbank8.pasm",
    ROOT / "src" / "escbank9.pasm",
    ROOT / "src" / "vtime.pasm",
)
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
WRITER = re.compile(r"^\s*(?:sta|stz|inc|dec)\s+\$AC(?:\s|;|$)", re.IGNORECASE)

# Every direct writer must be classified here.  The selected-bank entries are
# only intercepted at the finite diagnostic pack seams; they must not be
# mistaken for general clock coverage.
CLASSIFICATION: Final = {
    ("interp.pasm", "ccramclr"): "normal-only-setup",
    ("interp.pasm", "rclr"): "normal-only-setup",
    ("escbank2.pasm", "esc_ac_charge"): "unmigrated-native-charge",
    ("escbank2.pasm", "eacc_clamp"): "unmigrated-native-charge",
    ("escbank2.pasm", "hce4_leaf_ac_ready"): "unmigrated-renderer-residue",
    ("escbank3.pasm", "esc3_ac_charge_legacy_sbc"): "selected-25110-vtime-seam",
    ("escbank3.pasm", "esc3_ac_charge_clamp"): "selected-25110-vtime-seam",
    ("escbank5.pasm", "lh_0818_paced"): "unmigrated-idle-scheduler",
    ("escbank5.pasm", "lhp_vtime_release_seam"): "selected-vtime-pacing-seam",
    ("escbank5.pasm", "h11752_charge_12b6c"): "unmigrated-native-charge",
    ("escbank6.pasm", "esc6_ac_charge"): "unmigrated-native-charge",
    ("escbank6.pasm", "esc6_ac_clamp"): "unmigrated-native-charge",
    ("escbank7.pasm", "esc7_ac_charge"): "unmigrated-native-charge",
    ("escbank7.pasm", "esc7_ac_clamp"): "unmigrated-native-charge",
    ("escbank8.pasm", "h1c9ae_empty_hit"): "unmigrated-native-charge",
    ("escbank8.pasm", "Lfd7be_7"): "unmigrated-native-charge",
    ("escbank9.pasm", "esc9_ac_charge"): "selected-player-vtime-seam",
    ("escbank9.pasm", "esc9_ac_clamp"): "selected-player-vtime-seam",
    ("vtime.pasm", "vtime_consume_legacy"): "vtime-disabled-compatibility",
    ("vtime.pasm", "vtime_reload_legacy"): "vtime-disabled-compatibility",
    ("vtime.pasm", "vtime_reload_clear"): "vtime-legacy-quarantine",
    ("vtime.pasm", "vtime_paced_release_legacy"): "vtime-disabled-compatibility",
    # The opt-in choke gateway keeps this value safely out of the old expiry
    # path after virtual state is first constructed. It is not a native/HLE
    # migration and therefore does not reduce the outstanding coverage list.
    ("vtime.pasm", "vtime_choke_prepare_only"): "vtime-legacy-quarantine",
    ("vtime.pasm", "vtime_choke_have_magic"): "vtime-legacy-quarantine",
    # Virtual native and hardware-paced deadlines bridge once through the
    # retained iloop countdown so a self-refetching `$0818` wait cannot strand
    # VT_DUE before the normal IRQ/pending/reload boundary observes it.
    ("vtime.pasm", "vtime_charge_units_due"): "vtime-due-delivery-bridge",
    ("vtime.pasm", "vtime_paced_release"): "vtime-due-delivery-bridge",
}
UNMIGRATED: Final = frozenset(
    {
        "unmigrated-native-charge",
        "unmigrated-renderer-residue",
        "unmigrated-idle-scheduler",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect() -> list[dict[str, object]]:
    writers: list[dict[str, object]] = []
    for source in SOURCES:
        label = "<before-first-label>"
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            match = LABEL.match(line)
            if match:
                label = match.group(1)
            if not WRITER.match(line):
                continue
            key = (source.name, label)
            classification = CLASSIFICATION.get(key)
            if classification is None:
                raise RuntimeError(
                    f"unclassified legacy $AC writer at {source}:{number} ({label})"
                )
            writers.append(
                {
                    "source": str(source.relative_to(ROOT)),
                    "line": number,
                    "label": label,
                    "classification": classification,
                    "instruction": line.strip(),
                }
            )
    observed = {(Path(str(row["source"])).name, str(row["label"])) for row in writers}
    expected = set(CLASSIFICATION)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise RuntimeError(
            "legacy $AC classification drift: "
            f"missing={missing} extra={extra}"
        )
    return writers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    writers = collect()
    counts = Counter(str(row["classification"]) for row in writers)
    unmigrated = [row for row in writers if str(row["classification"]) in UNMIGRATED]
    report = {
        "scope": (
            "current-source direct legacy $AC writer inventory for the opt-in "
            "VTIME diagnostic; static blocker evidence, not a ROM, rate, or "
            "Stage-3 correctness result"
        ),
        "sources": {
            str(source.relative_to(ROOT)): sha256(source) for source in SOURCES
        },
        "writers": writers,
        "counts": dict(sorted(counts.items())),
        "unmigrated_writers": unmigrated,
        "common_clock_ready": not unmigrated,
        "promotion_blocked": bool(unmigrated),
        "required_before_promotion": (
            "migrate every unmigrated writer to common MC68000-cycle accounting "
            "and prove the resulting scheduler/IRQ boundaries in fresh three-way runs"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "writers": len(writers),
                "unmigrated": len(unmigrated),
                "promotion_blocked": report["promotion_blocked"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
