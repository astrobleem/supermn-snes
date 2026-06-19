#!/usr/bin/env python3
"""
Trace-driven CDL (Code/Data Log) builder for the Superman 68K ROM — the G1 tool.

The MAME execution trace IS a dynamic disassembler: every line is a confirmed
code address, and consecutive executed PCs within a basic block reveal the exact
instruction length (no error-prone static 68K length decoder needed). This marks
ONLY confirmed-executed code, and naturally includes jump-table targets (we trace
where indirect jumps actually went), which is what blocks static coverage (H6).

Usage:
  build_cdl.py <trace1.log> [trace2.log ...]
     -> accumulates, prints coverage vs the 512KB ROM, writes data/traced.cdl
        and data/traced_lengths.json (per-instruction lengths, reusable).
"""
import json
import os
import re
import sys
from pathlib import Path

# Game-agnostic: point CDL_ROM at any 68K program ROM (default = Superman).
ROM = Path(os.environ.get("CDL_ROM", "data/superman_m68k.bin")).read_bytes()
ROM_SIZE = len(ROM)
LINE = re.compile(r'^([0-9A-Fa-f]{4,6}):\s+(\S+)\s*(.*)$')
CDL = Path("data/traced.cdl")
LENJSON = Path("data/traced_lengths.json")


def term_len(pc):
    """Structural length for flow-terminators (which may never fall through, so
    a sequential successor is never observed). Returns None if not a terminator."""
    if pc + 2 > ROM_SIZE:
        return None
    op = (ROM[pc] << 8) | ROM[pc + 1]
    if op in (0x4E75, 0x4E73, 0x4E77):       # rts, rte, rtr
        return 2
    if (op & 0xF000) == 0x6000:               # bra/bsr/bcc
        lo = op & 0xFF
        return 4 if lo == 0 else (6 if lo == 0xFF else 2)
    if (op & 0xFFC0) in (0x4EF9, 0x4EB9):     # jmp/jsr abs.l
        return 6
    if (op & 0xFFC0) in (0x4EF8, 0x4EB8):     # jmp/jsr abs.w
        return 4
    if (op & 0xFFB8) == 0x4ED0 or (op & 0xFFB8) == 0x4E90:  # jmp/jsr (An)/(d,An)
        return 2
    return None


def main(paths):
    lengths = {}            # pc -> instruction length (bytes)
    indirect = {}           # site pc -> set of observed targets
    prev = None             # previous (pc, mnem)
    INDIR = re.compile(r'(jmp|jsr)', re.I)

    # load prior accumulation if present
    if LENJSON.exists():
        for k, v in json.loads(LENJSON.read_text()).items():
            lengths[int(k)] = v

    for path in paths:
        prev = None
        with open(path, errors="replace") as fh:
            for raw in fh:
                m = LINE.match(raw)
                if not m:
                    prev = None          # blank / "(loops...)" breaks adjacency
                    continue
                pc = int(m.group(1), 16)
                mn = m.group(2).lower()
                if pc >= ROM_SIZE:
                    prev = None
                    continue
                # derive length from sequential successor
                if prev is not None:
                    ppc, pmn = prev
                    d = pc - ppc
                    if 2 <= d <= 10:
                        lengths[ppc] = d
                    elif INDIR.match(pmn):
                        # previous was an indirect jmp/jsr and we jumped: record target
                        indirect.setdefault(ppc, set()).add(pc)
                lengths.setdefault(pc, None)   # ensure pc is known as code
                prev = (pc, mn)

    # fill unknown lengths: terminators structurally, else 2 (minimal)
    unknown = 0
    for pc in list(lengths):
        if lengths[pc] is None:
            t = term_len(pc)
            if t is None:
                t = 2
                unknown += 1
            lengths[pc] = t

    # byte coverage = union of [pc, pc+len)
    covered = bytearray(ROM_SIZE)
    for pc, ln in lengths.items():
        for b in range(pc, min(pc + ln, ROM_SIZE)):
            covered[b] = 1
    nbytes = sum(covered)

    LENJSON.write_text(json.dumps({str(k): v for k, v in lengths.items()}))
    with open(CDL, "w") as f:
        for pc in sorted(lengths):
            f.write(f"C 0x{pc:06X}\n")

    print(f"traces: {len(paths)}")
    print(f"distinct code instructions: {len(lengths)}")
    print(f"code bytes covered:         {nbytes} ({nbytes/1024:.1f} KB)")
    print(f"coverage of 512KB ROM:      {100*nbytes/ROM_SIZE:.1f}%   (baseline 14%)")
    print(f"  (lengths w/o observed successor, assumed 2B: {unknown})")
    print(f"indirect jmp/jsr sites with resolved targets: {len(indirect)}")
    tot_t = sum(len(v) for v in indirect.values())
    print(f"  total distinct resolved targets: {tot_t}")
    print(f"wrote {CDL} and {LENJSON}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
