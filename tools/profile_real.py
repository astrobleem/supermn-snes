#!/usr/bin/env python3
# LOOP-HOOK-AWARE profiler. The normal profiler (profile_frame) reads the dbg_fetch PC stream
# ($40:8000), which logs a PC BEFORE loop_hook runs -- so a loop_hook-COLLAPSED loop contributes its
# entry PC once per entry even though loop_hook handles the whole loop natively (~free). That INFLATES
# collapsed clusters. The interp now ALSO logs GENUINELY-interpreted PCs (those that reach lh_off,
# i.e. loop_hook returned C=0 / was off) to $40:C000 (count $0762, gated; see ilog in interp.pasm).
#
# This tool enables BOTH streams for one frame and reports, per 64-byte region: REAL = genuinely-
# interpreted count (the true per-frame interpreted cost), ALL = fetched count. REAL is the thing to
# optimize; (ALL-REAL) is what loop_hook already collapses (don't bother escaping it). Argv: gate=1.
import sys, os, collections, subprocess
if os.environ.get('_W') != '1':
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=320, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines() if l.startswith('>>>') or 'Error' in l or 'Trace' in l)); sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
from capstone import *
md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
IMG = open('build/interp.sfc', 'rb').read()[0x10000:0x10000 + 0x40000]
def desc(pc):
    try: ins = next(md.disasm(IMG[pc:pc+8], pc)); return "%s %s" % (ins.mnemonic, ins.op_str)
    except StopIteration: return "?"
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S = '/tmp/sframe.mss'
GATE = int(sys.argv[1]) if len(sys.argv) > 1 else 1
NFRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 8
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7530, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    def decode(buf, nb):
        return [((buf[i+2]|(buf[i+3]<<8))<<16)|(buf[i]|(buf[i+1]<<8)) for i in range(0, min(nb, len(buf))-3, 4)]
    runf(150); m.load_state(NAT)
    w16(0x0700,0); w16(0x071A,0); w16(0x0716,0); w16(0x0712,0); w16(0x0714,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
    m.save_state(S); m.load_state(S)
    w16(0x071A,GATE); w16(0x0700,0); w16(0x0712,0); w16(0x0710,0)
    w16(0x0714,1); runf(1); w16(0x0714,0)
    allc, realc, nf = collections.Counter(), collections.Counter(), 0
    for fr in range(NFRAMES):
        w16(0x0718, 0); w16(0x0762, 0)                     # enable BOTH streams
        ok = False
        for _ in range(400):
            w16(0x0710, 0x0708); w16(0x0716, 0); runf(4)
            if r16(0x0712): ok = True; break
        if not ok: break
        na, nr = r16(0x0718), r16(0x0762)
        allp  = decode(m.read_memory('snesMemory', 0x408000, min(na, 0xFFF8)), na)
        realp = decode(m.read_memory('snesMemory', 0x40C000, min(nr, 0x3FF8)), nr)
        irq = set(range(0x06F0,0x0762)) | {0x0818}
        for p in allp:
            if 0x800 <= p < 0x40000 and p not in irq: allc[p & ~0x3F] += 1
        for p in realp:
            if 0x800 <= p < 0x40000 and p not in irq: realc[p & ~0x3F] += 1
        nf += 1
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    tot_all = sum(allc.values()); tot_real = sum(realc.values())
    print(">>> over %d frames (gate=%d): ALL fetched=%d (%.0f/fr)  REAL interpreted=%d (%.0f/fr)  -> loop_hook collapses %d (%.0f%%)"
          % (nf, GATE, tot_all, tot_all/max(nf,1), tot_real, tot_real/max(nf,1), tot_all-tot_real, 100*(tot_all-tot_real)/max(tot_all,1)))
    print(">>> top GENUINELY-INTERPRETED regions (REAL/fr | ALL/fr | %collapsed | first PC):")
    for reg, rc in realc.most_common(20):
        ac = allc.get(reg, 0)
        coll = 100*(ac-rc)/max(ac,1)
        first = min((p for p in [reg]), default=reg)
        print(">>> $%06X  REAL %5.1f  ALL %5.1f  coll %3.0f%%  [%s]" % (reg, rc/max(nf,1), ac/max(nf,1), coll, desc(reg)))
    # regions that are mostly collapsed (in ALL but not REAL) -- already optimized, do NOT escape
    coll_only = [(reg, ac) for reg, ac in allc.most_common(30) if realc.get(reg,0) < ac*0.2 and ac >= nf]
    if coll_only:
        print(">>> mostly-COLLAPSED regions (high ALL, low REAL -> already loop_hook-optimized, skip):")
        for reg, ac in coll_only[:8]:
            print(">>> $%06X  ALL %5.1f  REAL %5.1f  [%s]" % (reg, ac/max(nf,1), realc.get(reg,0)/max(nf,1), desc(reg)))
