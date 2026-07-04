#!/usr/bin/env python3
# audit_banks.py — post-build .org-overlap audit (campaign risk #7: Poppy assembles overlapping
# .org blocks SILENTLY, later bytes win, both bodies corrupt — the entry_25110/$AC00 lessons).
# For each escbank pasm: map every label to its file-order .org block, then check each block's
# HIGHEST label address (a lower bound on its end) stays below the next block's .org base.
# Exit 1 on any violation. Run after tools/build_interp.sh.
import re, sys
from pathlib import Path

BANKS = [("src/escbank.pasm", "src/escbank.sym"), ("src/escbank2.pasm", "src/escbank2.sym"),
         ("src/escbank3.pasm", "src/escbank3.sym"), ("src/escbank4.pasm", "src/escbank4.sym"),
         ("src/escbank5.pasm", "src/escbank5.sym")]
bad = 0
for pasm, sym in BANKS:
    if not Path(pasm).exists() or not Path(sym).exists():
        continue
    addr = {}
    for line in Path(sym).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*00:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            addr[m.group(2)] = int(m.group(1), 16)
    # file-order blocks: (org, [labels]) — labels defined between this .org and the next
    blocks, cur = [], None
    for line in Path(pasm).read_text().splitlines():
        m = re.match(r"\s*\.org\s+\$([0-9A-Fa-f]+)", line)
        if m:
            cur = [int(m.group(1), 16), []]
            blocks.append(cur)
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*):", line)
        if m and cur is not None:
            cur[1].append(m.group(1))
    seq = sorted(blocks, key=lambda b: b[0])
    fbad = 0
    for i, (org, labels) in enumerate(seq):
        hi = max((addr[l] for l in labels if l in addr), default=org)
        nxt = seq[i + 1][0] if i + 1 < len(seq) else 0x10000
        if hi >= nxt:
            first = next((l for l in labels if l in addr), "?")
            print("OVERLAP %s: block .org $%04X (%s..) has label at $%04X >= next block .org $%04X"
                  % (pasm, org, first, hi, nxt))
            fbad += 1
    bad += fbad
    print("%s: %d blocks, max label $%04X — %s" % (pasm, len(seq),
          max((addr[l] for _, ls in seq for l in ls if l in addr), default=0),
          "OK" if not fbad else "OVERLAP"))
sys.exit(1 if bad else 0)
