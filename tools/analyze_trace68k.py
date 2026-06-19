#!/usr/bin/env python3
"""
Analyze a MAME 68K execution trace (PC + disasm per line, loops compacted) to
produce, for the transpiler spike:
  1. Coverage: distinct executed instruction addresses.
  2. Call graph: caller-function -> callee targets (from jsr/bsr).
  3. PURE LEAF candidates: functions that (across every observed invocation)
     make no call, contain no indirect/computed jump, and touch no device I/O
     (only ROM reads + work-RAM $F00000-$F0FFFF). These are the safe spike
     targets for the differential harness.
  4. Indirect control-flow sites (jump tables / computed jmp/jsr) — the H6
     blockers to resolve for coverage.

Usage: analyze_trace68k.py tools/mame-trace/probe_trace.log
"""
import re
import sys
from collections import defaultdict

LINE = re.compile(r'^([0-9A-Fa-f]{4,6}):\s+(\S+)\s*(.*)$')
HEXOP = re.compile(r'\$([0-9a-fA-F]+)')

IRQ_VECTORS = {0x6C4, 0x82C}          # GAME_LOGIC: IRQ2/6 and IRQ4 handlers
ROM_END = 0x080000                    # 512KB program ROM
WORKRAM_LO, WORKRAM_HI = 0xF00000, 0xF0FFFF


def is_io_abs(addr):
    """True if an absolute address is a device (side-effecting), not ROM/work-RAM."""
    if addr < ROM_END:
        return False                  # ROM: code/constants, safe to read
    if WORKRAM_LO <= addr <= WORKRAM_HI:
        return False                  # work RAM: plain memory
    return addr >= 0x300000           # palette/sprite/video/cchip/sound/frame regs


class Frame:
    __slots__ = ("entry", "calls", "io", "indirect", "icount", "lo", "hi")
    def __init__(self, entry):
        self.entry = entry
        self.calls = 0
        self.io = set()
        self.indirect = 0
        self.icount = 0
        self.lo = entry if isinstance(entry, int) else None
        self.hi = entry if isinstance(entry, int) else None


def main(path):
    # per-entry aggregate
    agg = defaultdict(lambda: {"inv": 0, "calls_ever": 0, "indirect_ever": 0,
                               "io": set(), "icount_min": 1 << 30, "icount_max": 0,
                               "lo": 1 << 30, "hi": 0, "callees": set()})
    callgraph = defaultdict(set)      # caller entry -> set(callee target)
    indirect_sites = defaultdict(int)  # pc of jmp/jsr (An,...) -> count
    pcs = set()
    n = 0

    stack = [Frame("root")]

    def pop():
        f = stack.pop() if len(stack) > 1 else None
        if f and isinstance(f.entry, int):
            a = agg[f.entry]
            a["inv"] += 1
            a["calls_ever"] = max(a["calls_ever"], f.calls)
            a["indirect_ever"] = max(a["indirect_ever"], f.indirect)
            a["io"] |= f.io
            a["icount_min"] = min(a["icount_min"], f.icount)
            a["icount_max"] = max(a["icount_max"], f.icount)
            if f.lo is not None:
                a["lo"] = min(a["lo"], f.lo)
                a["hi"] = max(a["hi"], f.hi)
        return f

    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            m = LINE.match(raw)
            if not m:
                continue              # blank / "(loops for N instructions)"
            pc = int(m.group(1), 16)
            mn = m.group(2).lower()
            op = m.group(3)
            pcs.add(pc)
            n += 1

            # interrupt entry bracketing
            if pc in IRQ_VECTORS and stack[-1].entry != pc:
                stack.append(Frame(pc))

            top = stack[-1]
            top.icount += 1
            if top.lo is None or pc < top.lo:
                top.lo = pc
            if top.hi is None or pc > top.hi:
                top.hi = pc

            # I/O detection on absolute operands
            for h in HEXOP.findall(op):
                a = int(h, 16)
                if is_io_abs(a):
                    top.io.add(a & 0xFFFFFF)

            if mn in ("jsr", "bsr"):
                top.calls += 1
                tgt = None
                hm = HEXOP.search(op)
                # register-indirect jsr "(A0)" has no $ → indirect
                if hm and "(" not in op.split(",")[0]:
                    tgt = int(hm.group(1), 16)
                if tgt is None:
                    top.indirect += 1
                    indirect_sites[pc] += 1
                    stack.append(Frame("ind@%06x" % pc))
                else:
                    if isinstance(top.entry, int):
                        callgraph[top.entry].add(tgt)
                        agg[top.entry]  # touch
                    stack.append(Frame(tgt))
            elif mn == "jmp":
                hm = HEXOP.search(op)
                if not (hm and "(" not in op):
                    top.indirect += 1
                    indirect_sites[pc] += 1
            elif mn.split(".")[0] in ("trap", "trapv", "chk", "illegal", "trapcc"):
                # software interrupt / OS dispatch — NOT a leaf
                top.calls += 1
            elif mn == "rts":
                pop()
            elif mn == "rte":
                pop()

    # record callees into agg
    for caller, callees in callgraph.items():
        agg[caller]["callees"] |= callees

    print(f"trace lines parsed: {n}")
    print(f"distinct executed instruction addresses: {len(pcs)}")
    in_rom = sum(1 for p in pcs if p < ROM_END)
    print(f"  of which in program ROM (<$80000): {in_rom}")
    print()

    # pure leaf candidates
    leaves = []
    for entry, a in agg.items():
        if not isinstance(entry, int) or entry >= ROM_END:
            continue
        if a["inv"] == 0:
            continue
        if a["calls_ever"] == 0 and a["indirect_ever"] == 0 and not a["io"]:
            extent = (a["hi"] - a["lo"]) if a["hi"] >= a["lo"] else 0
            leaves.append((entry, a["inv"], a["icount_min"], a["icount_max"], extent))

    leaves.sort(key=lambda t: (-t[1], t[4]))   # most-invoked, then smallest
    print(f"PURE LEAF candidates (no calls, no indirect, no device I/O): {len(leaves)}")
    print(f"{'entry':>8} {'invocs':>7} {'imin':>5} {'imax':>5} {'extent':>7}")
    for entry, inv, imn, imx, ext in leaves[:25]:
        print(f"{entry:08X} {inv:7d} {imn:5d} {imx:5d} {ext:7d}")
    print()

    print(f"indirect/computed control-flow sites (H6 jump tables): {len(indirect_sites)}")
    for pc, c in sorted(indirect_sites.items(), key=lambda t: -t[1])[:15]:
        print(f"  {pc:08X}  x{c}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/mame-trace/probe_trace.log")
