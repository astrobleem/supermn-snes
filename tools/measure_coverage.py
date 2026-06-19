#!/usr/bin/env python3
"""
Measure code/data coverage of a Peony .pasm disassembly. Each emitted line is
annotated `; $ADDR: <hex bytes>`. We classify a line as CODE (a real decoded
instruction) vs DATA/unknown (`dc.w`, `dc.b`, or `???` placeholder), and sum the
byte span of each so we report *reliable code* coverage, not linear-sweep noise.

Usage: measure_coverage.py <disasm.pasm>
"""
import re
import sys

ANN = re.compile(r';\s*\$?([0-9A-Fa-f]{1,6}):\s*([0-9A-Fa-f ]+)\s*$')
ROM = 512 * 1024


def main(path):
    code_bytes = set()
    data_bytes = set()
    n_code = n_data = 0
    for line in open(path, errors="replace"):
        m = ANN.search(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        nb = len(m.group(2).split())
        body = line.split(";")[0].strip().lower()
        is_data = (not body) or body.startswith((".db", ".dw", "dc.", "dc ")) or "???" in body
        tgt = data_bytes if is_data else code_bytes
        for b in range(addr, addr + nb):
            tgt.add(b)
        if is_data:
            n_data += 1
        else:
            n_code += 1
    # bytes counted as code but also data -> prefer code
    code_only = code_bytes
    print(f"file: {path}")
    print(f"code lines:  {n_code:6d}   code bytes:  {len(code_only):6d}  ({len(code_only)/1024:.1f} KB, {100*len(code_only)/ROM:.1f}% of 512KB)")
    print(f"data lines:  {n_data:6d}   data bytes:  {len(data_bytes):6d}  ({len(data_bytes)/1024:.1f} KB)")
    classified = len(code_only | data_bytes)
    print(f"classified:  {classified} bytes ({100*classified/ROM:.1f}% of ROM); unclassified {ROM-classified} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
