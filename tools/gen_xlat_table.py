#!/usr/bin/env python3
"""Generate the AOT address-translation table: 68K PC -> native escape entry.

This is the data backing `xlat_dispatch` (escbank2 $94:F900) -- the single indirection that
replaces hand-rolled per-target cmp-chains (ojmp_hook/ojmp_disp ...). PoC scope: bank-$00 PCs,
the jmp-state (no-return-push) convention class only, so routing ojmp_hook through it is
convention-safe. Wider classes (jsr/coroutine) need calling-convention unification first.

Structure (2-level page table, little-endian, placed at SA-1 $96:8000 = file $2B0000):
  offset 0:        page[256]   -- 2 bytes each; pages[PC>>8] = byte-offset of that page's
                                  sub-table within the blob, or 0 = no escapes in the page.
  offset $200..:   sub-table   -- 256 entries x 3 bytes; sub[PC&$FF] = 24-bit native addr
                                  (lo, mid, bank), or 0 = miss (interpret).
Real escape entries are at $92/$94:8000+, so a zero lo/mid never collides with a live entry.
"""
import re, sys
from pathlib import Path

# jmp-state class (convention: NO return-push; reached by `jmp (a0)` -> op_jmp_idx -> ojmp_hook).
# These three are proven bit-exact through xlat_dispatch (val_frame_diff GREEN; 3 escapes, 3 pages).
# d386/d3b0 ($D3 handlers) are EXCLUDED: each dispatches fine alone, but co-dispatching either with
# d0d0 diverges -- a real escape INTERACTION (shared $D0-$D3 state) that routing real dispatch through
# the table exposed (the old ojmp cmp-chain never co-dispatched them). They fall through to the
# interpreter (bit-exact) until that interaction is debugged. See task #70 / memory.
JMP_STATE_PCS = {0xD5C4, 0xD0D0, 0xD6FC}

# AOT-TABLE / rts-class entries (transpiled with transpile.py --table; faithful link/unlk/rts,
# entered via xlat_dispatch with the real return already on the 68K stack). $0CE4 = the hottest
# cluster (~12.5%), its rts reach (from $0047FE) was uncatchable by any hook -> entry_ce4t.
TABLE_PCS = set()   # (empty) -- entry_xce4 ($0CE4) is bit-exact ALONE; {+d0d0} RED looks like a val_frame_diff trap-alignment artifact (needs frame-aligned validation)

ALLOWED_PCS = JMP_STATE_PCS | TABLE_PCS
BANK_OF_SYM = {"src/escbank.sym": 0x92, "src/escbank2.sym": 0x94}  # assembled @ .org $8000

def load_native_addrs():
    """entry_X -> 24-bit native address (bank forced per source bank)."""
    out = {}
    for sym, bank in BANK_OF_SYM.items():
        p = Path(sym)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"\s*[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(entry_[0-9a-z]+)", line)
            if m:
                out[m.group(2)] = (bank << 16) | int(m.group(1), 16)
    return out

def load_entry_pcs():
    """entry_X -> 68K PC, from the `transpiled from $XXXXXX` comment preceding each label."""
    out = {}
    for f in ("src/escbank.pasm", "src/escbank2.pasm"):
        last = None
        for ln in Path(f).read_text().splitlines():
            m = re.search(r"transpiled from \$([0-9A-Fa-f]+)", ln)
            if m:
                last = int(m.group(1), 16)
            m2 = re.match(r"(entry_[0-9a-z]+):", ln)
            if m2:
                out[m2.group(1)] = last
                last = None
    return out

def main():
    native = load_native_addrs()
    pcs = load_entry_pcs()
    # select the jmp-state class entries that are present + resolved
    pairs = []   # (pc, native_addr)
    for name, pc in pcs.items():
        if pc in ALLOWED_PCS and name in native:
            pairs.append((pc, native[name], name))
    pairs.sort()
    if len(pairs) != len(ALLOWED_PCS):
        got = {p for p, _, _ in pairs}
        print("gen_xlat_table: WARNING missing jmp-state entries: %s"
              % [hex(x) for x in ALLOWED_PCS - got], file=sys.stderr)

    # build the page table
    PAGE_BYTES = 256 * 2
    page_off = {}                       # hibyte -> sub-table offset in blob
    for pc, _, _ in pairs:
        hib = (pc >> 8) & 0xFF
        page_off.setdefault(hib, None)
    # allocate sub-tables after the page array
    cur = PAGE_BYTES
    subtab = {}                          # hibyte -> bytearray(256*3)
    for hib in sorted(page_off):
        page_off[hib] = cur
        subtab[hib] = bytearray(256 * 3)
        cur += 256 * 3
    # fill sub-table entries
    for pc, addr, name in pairs:
        hib, lob = (pc >> 8) & 0xFF, pc & 0xFF
        st = subtab[hib]
        st[lob*3+0] = addr & 0xFF
        st[lob*3+1] = (addr >> 8) & 0xFF
        st[lob*3+2] = (addr >> 16) & 0xFF
    # assemble blob
    blob = bytearray(cur)
    for hib, off in page_off.items():
        blob[hib*2+0] = off & 0xFF
        blob[hib*2+1] = (off >> 8) & 0xFF
    for hib in subtab:
        off = page_off[hib]
        blob[off:off+256*3] = subtab[hib]
    assert len(blob) <= 0x8000, "xlat table %d bytes overflows $96:8000 bank" % len(blob)

    Path("src/xlat_table.bin").write_bytes(blob)
    print("gen_xlat_table: %d entries, %d pages, %d bytes -> src/xlat_table.bin (@ $96:8000)"
          % (len(pairs), len(page_off), len(blob)))
    for pc, addr, name in pairs:
        print("    $%06X -> $%06X  [%s]  page $%02X off $%04X" % (pc, addr, name, (pc>>8)&0xFF, page_off[(pc>>8)&0xFF]))

if __name__ == "__main__":
    main()
