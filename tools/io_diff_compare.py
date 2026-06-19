#!/usr/bin/env python3
"""Compare MAME's per-frame I/O read values (io_diff.log from trace_io_diff.lua)
against what src/interp.pasm's readbyte returns, to rank the divergences that gate
the boot frame-sync. 'MAME varies across frames but interp returns a constant'
ranks first — that's a hardware-state poll the interpreter stubs.
"""
import re, sys, os
REPO = "/home/chad/supermn-snes"
LOG  = os.path.join(REPO, "tools/mame-trace/io_diff.log")
ROM  = open(os.path.join(REPO, "data/superman_m68k.bin"), "rb").read()
RESP1 = open(os.path.join(REPO, "data/cchip_boot_response.bin"), "rb").read()

def interp_readbyte(addr):
    """Model readbyte (src/interp.pasm:5728-5809). Returns a value, or a tuple of
    plausible values for cmd-dependent C-Chip reads, or None for work RAM."""
    hi = (addr >> 16) & 0xFF
    if hi == 0xF0: return None                      # work RAM — not stubbed
    if addr in (0x900802, 0x900803): return 0x01    # self-test OK
    if hi == 0x50: return 0x0F                       # DIP/input
    if hi == 0x80: return 0x04                       # sound-latch
    if addr < 0x80000: return ROM[addr]              # 68K ROM
    if hi == 0x90:                                   # C-Chip data port (cmd-dependent)
        idx = (addr >> 1) & 0xFF
        cmd1 = RESP1[idx] if idx < len(RESP1) else 0
        cmd2 = {0:0x47,1:0x57,2:0x4B}.get(idx, 0)
        return ("cchip", cmd1, cmd2, 0)              # cmd1 / cmd2 / no-cmd
    return 0x00                                       # rb_zero

def parse(path):
    recs=[]
    for line in open(path):
        m=re.match(r'^(VARY|const)\s+PC=([0-9A-F]+) ADDR=([0-9A-F]+) count=(\d+) nvals=(\d+)\s+\[(.*)\]', line)
        if not m: continue
        kind,pc,addr,count,nvals,changes=m.groups()
        vals=[]
        for c in re.findall(r'=\$([0-9A-F]{2})', changes):
            vals.append(int(c,16))
        recs.append(dict(pc=int(pc,16),addr=int(addr,16),count=int(count),
                         nvals=int(nvals),vals=vals,kind=kind))
    return recs

def main():
    recs=parse(LOG)
    divergences=[]
    for r in recs:
        iv=interp_readbyte(r['addr'])
        if iv is None: continue
        mame_set=set(r['vals'])
        if isinstance(iv,tuple):  # C-Chip cmd-dependent
            interp_set={iv[1],iv[2],iv[3]}
            interp_desc=f"cchip cmd1=${iv[1]:02X} cmd2=${iv[2]:02X}"
            # divergent if MAME ever returns a value the interp can't produce
            missing = mame_set - interp_set
            diverge = bool(missing)
        else:
            interp_set={iv}
            interp_desc=f"${iv:02X} (const)"
            missing = mame_set - interp_set
            diverge = bool(missing)
        if diverge:
            # severity: MAME varies AND interp constant (not cchip) -> top gate
            varies = r['nvals']>1
            const_interp = not isinstance(iv,tuple)
            rank = (varies and const_interp, r['count'], r['nvals'])
            divergences.append((rank, r, interp_desc, sorted(mame_set), sorted(missing)))
    divergences.sort(key=lambda x:(x[0][0], x[0][1]), reverse=True)
    print(f"{'PC':>7} {'ADDR':>7} {'cnt':>5} {'nval':>4}  interp_returns        MAME_values  missing")
    print("-"*88)
    for rank,r,idesc,mvals,missing in divergences[:25]:
        flag = "GATE" if rank[0] else "    "
        print(f"{flag} {r['pc']:06X} {r['addr']:06X} {r['count']:5d} {r['nvals']:4d}  "
              f"{idesc:20s}  {[f'{v:02X}' for v in mvals]}  miss={[f'{v:02X}' for v in missing]}")
    print()
    gates=[d for d in divergences if d[0][0]]
    if gates:
        _,r,idesc,mvals,missing=gates[0]
        print(f"FIRST GATE: PC=${r['pc']:06X} reads ${r['addr']:06X} {r['count']}x; "
              f"interp returns {idesc} but MAME returns {[f'${v:02X}' for v in mvals]}")
if __name__=="__main__": main()
