#!/usr/bin/env python3
# audit_banks.py — post-build .org-overlap audit (campaign risk #7: Poppy assembles overlapping
# .org blocks SILENTLY, later bytes win, both bodies corrupt — the entry_25110/$AC00 lessons).
# For each escbank pasm: map every label to its file-order .org block, then check each block's
# HIGHEST label address (a lower bound on its end) stays below the next block's .org base.
# Exit 1 on any violation. Run after tools/build_interp.sh.
import re, sys
from pathlib import Path

BANKS = [
    ("src/escbank.pasm", "src/escbank.sym"),
    *[
        (f"src/escbank{index}.pasm", f"src/escbank{index}.sym")
        for index in range(2, 10)
    ],
]
bad = 0
for pasm, sym in BANKS:
    if not Path(pasm).exists() or not Path(sym).exists():
        continue
    addr = {}
    for line in Path(sym).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*00:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            addr[m.group(2)] = int(m.group(1), 16)
    # File-order blocks: labels defined between this .org and the next.  Keep
    # the last significant source item as well.  A terminal *_end label may
    # legitimately equal the next .org: it marks the first byte not owned by
    # the preceding block and emits no data.  Any code/directive after such a
    # label, any non-end label at the seam, or any label beyond it remains an
    # overlap failure.
    blocks, cur = [], None
    for raw_line in Path(pasm).read_text().splitlines():
        line = raw_line.split(";", 1)[0].rstrip()
        m = re.match(r"\s*\.org\s+\$([0-9A-Fa-f]+)", line)
        if m:
            cur = {
                "org": int(m.group(1), 16),
                "labels": [],
                "tail": None,
            }
            blocks.append(cur)
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*):", line)
        if m and cur is not None:
            label = m.group(1)
            cur["labels"].append(label)
            cur["tail"] = ("label", label)
        elif line.strip() and cur is not None:
            cur["tail"] = ("source", line.strip())
    seq = sorted(blocks, key=lambda block: block["org"])
    fbad = 0
    for i, block in enumerate(seq):
        org = block["org"]
        labels = block["labels"]
        hi = max((addr[l] for l in labels if l in addr), default=org)
        nxt = seq[i + 1]["org"] if i + 1 < len(seq) else 0x10000
        seam_labels = [
            label for label in labels
            if addr.get(label) == nxt
        ]
        terminal_end_seam = (
            hi == nxt
            and seam_labels
            and all(label.endswith("_end") for label in seam_labels)
            and block["tail"] is not None
            and block["tail"][0] == "label"
            and block["tail"][1] in seam_labels
        )
        if hi > nxt or (hi == nxt and not terminal_end_seam):
            first = next((l for l in labels if l in addr), "?")
            print(
                "OVERLAP %s: block .org $%04X (%s..) has nonterminal "
                "label/source at $%04X >= next block .org $%04X"
                % (pasm, org, first, hi, nxt)
            )
            fbad += 1
    bad += fbad
    print("%s: %d blocks, max label $%04X — %s" % (pasm, len(seq),
          max((
              addr[label]
              for block in seq
              for label in block["labels"]
              if label in addr
          ), default=0),
          "OK" if not fbad else "OVERLAP"))
sys.exit(1 if bad else 0)
