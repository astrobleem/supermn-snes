#!/usr/bin/env python3
# Run the entry_26fa escape differential ON NEXEN by transplanting the Mesen B0 gameplay state onto
# a Nexen interp booted in TEST mode (so CIWP is enabled and the SA-1's IRAM writes work). No Mesen
# save-state load, no broken prod boot. "freezeB0" = re-transplant (write IRAM+BW-RAM, set both CPUs).
import sys, os, json
TGT=int(sys.argv[1],16)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess
_sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
regs = open(S + '/regsA.bin', 'rb').read(); wramA = open(S + '/wramA.bin', 'rb').read()
def be32(d, o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D = [be32(regs, i*4) for i in range(8)]; A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]; USP = be32(regs, 16*4)
def le32(v): return '%02x%02x%02x%02x' % (v&0xFF, (v>>8)&0xFF, (v>>16)&0xFF, (v>>24)&0xFF)
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu = json.load(open('/tmp/b0_cpu.json'))
iram = open('/tmp/b0_iram.bin','rb').read(); bwram = open('/tmp/b0_bwram.bin','rb').read()

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7458, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a, mt='Sa1Memory'): b = m.read_memory(mt, a, 2); return b[0]|(b[1]<<8)
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    def runf(n, c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    def setcpu(st): m.tool("set_cpu_state", {k: st[k] for k in ('cpuType','pc','k','a','x','y','sp','d','dbr','ps','emulationMode') if k in st})
    def transplant():
        for o in range(0, len(iram), 0x400): wh(0x0000+o, iram[o:o+0x400].hex())          # IRAM
        for o in range(0, len(bwram), 0x4000): wh(0x400000+o, bwram[o:o+0x4000].hex(), 'snesMemory')  # BW-RAM
        setcpu(cpu['sa1']); setcpu(cpu['snes'])
    def freezeB0():
        transplant()
        # IRAM dump already has $0702=1 (frozen). re-assert the arm just in case.
        w16(0x0700, 1)
        for _ in range(10):
            if r16(0x0702): break
            runf(60)
    def inject(hook, bp_lo, bp_bank):
        wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8))); wh(0x40, le32(0x00003A92))
        w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
        w16(0x7C, 7); w16(0xA4, USP&0xFFFF); w16(0xA6, (USP>>16)&0xFFFF); w16(0xA8, 1); w16(0xAA, 0); w16(0x4A, 0); w16(0x4C, 0); w16(0xAC, 0x7000)
        w16(0x0718, 0xFFF8); wh(0x400000, wramA.hex(), 'snesMemory'); w16(0x410000, 0x0100, 'snesMemory'); w16(0x410002, 0x0100, 'snesMemory')
        w16(0x071A, hook); w16(0x0712, 0); w16(0x0714, 0); w16(0x0710, bp_lo); w16(0x0716, bp_bank)
        w16(0x0702, 0); w16(0x0704, 1)

    print("[Nexen] booting TEST ROM to enable CIWP (IRAM writes)...", flush=True)
    runf(600)
    print("[Nexen] CIWP check — reset test presets: $7E=%04X $AC=%04X (expect $7E=1 $AC=$7FFF if test-idle)" % (r16(0x7E), r16(0xAC)), flush=True)
    freezeB0()
    print("[Nexen] after transplant: $0702(frozen)=%d SA1.68kPC=$%06X tmask=%04X" % (r16(0x0702), r16(0x40)|(r16(0x42)<<16), r16(0x400002,'snesMemory')), flush=True)
    inject(0, TGT&0xFFFF, (TGT>>16)&0xFFFF)
    fz = 0
    for _ in range(60):
        runf(20)
        if r16(0x0712) or r16(0x0702): fz=1; break
    a7 = r16(0x3C)|(r16(0x3E)<<16); sb = m.read_memory('snesMemory', 0x400000|(a7&0xFFFF), 4)
    hi = sb[0]<<8|sb[1]; lo = sb[2]<<8|sb[3]
    print("[Nexen] frozen at $%06X: $0712=%d a7=$%06X return=$%04X:%04X" % (TGT, r16(0x0712), a7, hi, lo), flush=True)

    def run_to_ret(hook):
        freezeB0(); inject(hook, lo, hi)
        for _ in range(60):
            runf(20)
            if r16(0x0712) or r16(0x0702): break
        return r16(0x0712), bytes(m.read_memory('Sa1Memory',0x00,0x40)), bytes(m.read_memory('snesMemory',0x400000,0x8000)), bytes(m.read_memory('snesMemory',0x410000,0x8000))
    of, orf, o40, o41 = run_to_ret(0); nf, nrf, n40, n41 = run_to_ret(1)
    RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    def rd(b,s): i=s*4; return b[i]|(b[i+1]<<8)|(b[i+2]<<16)|(b[i+3]<<24)
    rdiff=[RN[s] for s in range(16) if rd(orf,s)!=rd(nrf,s)]
    bd40=sum(1 for i in range(len(o40)) if o40[i]!=n40[i]); bd41=sum(1 for i in range(len(o41)) if o41[i]!=n41[i])
    print("[Nexen] OFF froze=%d | ON froze=%d ; reg diffs=%s ; $40 diff=%d ; $41(shadow) diff=%d" % (of, nf, rdiff or "NONE", bd40, bd41), flush=True)
    print(">>>", "GREEN-tick $%06X bit-exact"%TGT if (not rdiff and bd40==0 and bd41==0 and nf) else "RED", flush=True)
