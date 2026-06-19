#!/usr/bin/env python3
"""
uPD7810 / uPD78C11 disassembler for the Superman C-Chip firmware.

This is a faithful Python port of MAME's authoritative disassembler
(src/devices/cpu/upd7810/upd7810_dasm.cpp, copied to upd7810_dasm_mame.cpp).
It PARSES MAME's opcode tables directly rather than re-typing them, so the
opcode->mnemonic mapping is exactly MAME's. The dispatch + operand formatter
replicate upd7810_base_disassembler::disassemble() byte-for-byte.

Variant: uPD78C11 == 7810 family -> uses XX_7810 + its prefix tables.

Usage:
  python3 upd7810dasm.py <rom> <base_hex> [start_hex] [end_hex]
Examples:
  python3 upd7810dasm.py ../../superman-arcade/cchip_upd78c11.bin 0x0000
  python3 upd7810dasm.py ../../superman-arcade/b61_11.m11 0x2000 0x2000 0x22c5
"""
import re, sys, os

MAME_SRC = os.path.join(os.path.dirname(__file__), "upd7810_dasm_mame.cpp")

# regname[32] for the 'i' (bit-manipulation) operand, verbatim from MAME.
REGNAME = [
    "illegal","illegal","illegal","illegal","illegal","illegal","illegal","illegal",
    "illegal","illegal","illegal","illegal","illegal","illegal","illegal","illegal",
    "PA","PB","PC","PD","illegal","PF","MKH","MKL",
    "illegal","SMH","illegal","EOM","illegal","TMM","PT","illegal",
]

def _strip_comments(s):
    return re.sub(r"//[^\n]*", "", s)

def _extract_block(src, name):
    """Return the brace-balanced body of `const ... NAME[256] = { ... };`."""
    m = re.search(r"\b" + re.escape(name) + r"\[256\]\s*=\s*", src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        c = src[j]
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i+1:j]
        j += 1
    raise ValueError("unbalanced braces for " + name)

def _split_entries(body):
    """Split a table body into its depth-1 {...} entry strings, in order."""
    body = _strip_comments(body)
    entries, depth, cur = [], 0, []
    for c in body:
        if c == "{":
            depth += 1
            if depth == 1:
                cur = []
                continue
        elif c == "}":
            depth -= 1
            if depth == 0:
                entries.append("".join(cur).strip())
                continue
        if depth >= 1:
            cur.append(c)
    return entries

def parse_tables(src, table_names):
    """tables[name] = list of 256 entries; each entry is one of:
       ('illegal',), ('insn', MNEMONIC, ARGS|None), ('prefix', SUBTABLE_NAME)."""
    tables = {}
    for name in table_names:
        body = _extract_block(src, name)
        if body is None:
            raise ValueError("table not found: " + name)
        out = []
        for e in _split_entries(body):
            if e == "":
                out.append(("illegal",))
            elif re.fullmatch(r"[a-z]\w*", e):           # lone lowercase id => prefix table
                out.append(("prefix", e))
            else:
                tok = re.match(r"[A-Za-z_]\w*", e).group(0)
                rest = e[len(tok):]
                mq = re.search(r'"((?:[^"\\]|\\.)*)"', rest)  # the quoted args, if any
                if mq:
                    args = mq.group(1)
                else:
                    args = None  # nullptr / no operand
                out.append(("insn", tok, args))
        if len(out) != 256:
            raise ValueError(f"{name}: expected 256 entries, got {len(out)}")
        tables[name] = out
    return tables

# 7810 needs the main table and every prefix table it references.
TABLE_NAMES = ["XX_7810","d48_7810","d4C_7810","d4D_7810","d60","d64_7810","d70","d74"]

class Dasm:
    def __init__(self):
        src = open(MAME_SRC).read()
        self.t = parse_tables(src, TABLE_NAMES)
    def _entry(self, op, table="XX_7810"):
        return self.t[table][op]

    def decode(self, rom, base, addr):
        """Return (length, mnemonic, operand_text). addr/idx are CPU addresses."""
        def r8(a): return rom[a - base]
        idx = addr
        op = r8(idx); idx += 1
        desc = self._entry(op)
        if desc[0] == "prefix":
            op = r8(idx); idx += 1
            desc = self._entry(op, desc[1])
        if desc[0] == "illegal":
            return 1, "illegal", f"${op:02X}"
        _, mnem, args = desc
        out = []
        if args:
            a = 0
            while a < len(args):
                c = args[a]
                if c == "%":
                    a += 1; code = args[a]
                    if code == "a":      # working-reg addr: V*256 + offset
                        op2 = r8(idx); idx += 1; out.append(f"VV:{op2:02X}")
                    elif code == "A":    # I/O address (7801 only) — uses op
                        out.append(f"${op:02X}")
                    elif code == "b":    # immediate byte
                        out.append(f"${r8(idx):02X}"); idx += 1
                    elif code == "w":    # immediate word (LE)
                        ea = r8(idx) + (r8(idx+1) << 8); idx += 2
                        out.append(f"${ea:04X}")
                    elif code == "d":    # JRE
                        op2 = r8(idx); idx += 1
                        offset = -(256 - op2) if (op & 1) else op2
                        out.append(f"${(idx + offset) & 0xFFFF:04X}")
                    elif code == "t":    # CALT
                        ea = 0x80 + 2 * (op & 0x1f)
                        out.append(f"(${ea:04X})")
                    elif code == "f":    # CALF
                        op2 = r8(idx); idx += 1
                        ea = 0x800 + 0x100 * (op & 0x07) + op2
                        out.append(f"${ea:04X}")
                    elif code == "o":    # JR
                        offset = (-0x20 if (op & 0x20) else 0) + (op & 0x1F)
                        out.append(f"${(idx + offset) & 0xFFFF:04X}")
                    elif code == "i":    # bit manipulation
                        op2 = r8(idx); idx += 1
                        out.append(f"{REGNAME[op2 & 0x1f]},{op2 >> 5}")
                    else:
                        out.append(code)
                else:
                    out.append(c)
                a += 1
        return idx - addr, mnem, "".join(out)

def disasm_range(path, base, start=None, end=None):
    rom = open(path, "rb").read()
    base = int(base, 16) if isinstance(base, str) else base
    start = base if start is None else (int(start,16) if isinstance(start,str) else start)
    end = base + len(rom) if end is None else (int(end,16) if isinstance(end,str) else end)
    d = Dasm()
    addr = start
    lines = []
    while addr < end:
        n, mnem, ops = d.decode(rom, base, addr)
        raw = " ".join(f"{rom[addr-base+i]:02X}" for i in range(n))
        lines.append(f"{addr:04X}:  {raw:<14} {mnem:<8}{(' ' + ops) if ops else ''}")
        addr += n
    return lines

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    path, base = sys.argv[1], sys.argv[2]
    start = sys.argv[3] if len(sys.argv) > 3 else None
    end   = sys.argv[4] if len(sys.argv) > 4 else None
    for ln in disasm_range(path, base, start, end):
        print(ln)
