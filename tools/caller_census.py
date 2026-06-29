#!/usr/bin/env python3
# Caller census: capture the interpreter's full ordered interpreted-PC STREAM (work-RAM $40:8000,
# count $0718) and, for each interpreted-function ENTRY, report the distribution of its PREDECESSOR
# PC (the dispatching instruction) + a capstone disasm. Identifies HOW each hot already-deployed-but-
# interpreting escape is reached (jsr/jmp/rts/bsr...). The hot handlers' dispatch path VARIES BY FRAME
# (different $0708/game state), so accumulate over N CONSECUTIVE frames (game advances) to map ALL
# paths -- a single frame is not enough (see [[hot-cluster-rts-dispatch]]).
#
# Usage: tools/caller_census.py [gate=1] [frames=30]
import sys, os, collections, subprocess
if os.environ.get('_W') != '1':
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=600, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines() if l.startswith('>>>') or 'Error' in l or 'Trace' in l)); sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
from capstone import *
md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
IMG = open('build/interp.sfc', 'rb').read()[0x10000:0x10000 + 0x40000]
_dc = {}
def desc(pc):
    if pc not in _dc:
        try: ins = next(md.disasm(IMG[pc:pc+8], pc)); _dc[pc] = "%s %s" % (ins.mnemonic, ins.op_str)
        except StopIteration: _dc[pc] = "?"
    return _dc[pc]
def mnem(pc):
    try: return next(md.disasm(IMG[pc:pc+8], pc)).mnemonic
    except StopIteration: return "?"
# a predecessor whose op is a control TRANSFER means pcs[i] is a dispatch entry (not straight-line).
DISPATCH = {'rts', 'rtr', 'rte', 'jsr', 'jmp', 'bsr', 'bra'}
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S = '/tmp/sframe.mss'
GATE = int(sys.argv[1]) if len(sys.argv) > 1 else 1
NFRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 30
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7530, boot_wait=6.0, socket_timeout=540.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    # capture at the $0708 IRQ jsr site (escapes off for a clean deterministic start)
    w16(0x0700,0); w16(0x071A,0); w16(0x0716,0); w16(0x0712,0); w16(0x0714,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
    m.save_state(S); m.load_state(S)
    w16(0x071A,GATE); w16(0x0700,0); w16(0x0712,0); w16(0x0710,0)
    w16(0x0714,1); runf(1); w16(0x0714,0)                 # release past the captured $0708
    entry_pred = collections.defaultdict(collections.Counter)   # entry PC -> Counter(predecessor PC)
    entry_total = collections.Counter()                          # entry PC -> total dispatch count
    frames_done = 0; capped = 0
    for fr in range(NFRAMES):
        w16(0x0718, 0)                                    # reset stream write-count
        ok = False
        for _ in range(400):
            w16(0x0710, 0x0708); w16(0x0716, 0); runf(4)
            if r16(0x0712): ok = True; break
        if not ok: break
        nb = r16(0x0718)
        if nb >= 0xFFF8: capped += 1
        stream = m.read_memory('snesMemory', 0x408000, min(nb, 0xFFF8))
        pcs = [((stream[i+2]|(stream[i+3]<<8))<<16)|(stream[i]|(stream[i+1]<<8)) for i in range(0, len(stream)-3, 4)]
        for i in range(1, len(pcs)):
            p, q = pcs[i-1], pcs[i]
            if not (0x800 <= q < 0x40000): continue
            if q == p or (p < q and q - p <= 6): continue      # straight-line fall-through, not a dispatch
            if mnem(p) in DISPATCH:
                entry_pred[q][p] += 1; entry_total[q] += 1
        frames_done += 1
        w16(0x0712, 0); w16(0x0710, 0); w16(0x0714, 1); runf(1); w16(0x0714, 0)   # advance to next frame
    print(">>> caller census over %d frames (gate=%d%s): %d distinct dispatch entries"
          % (frames_done, GATE, ", %d CAPPED" % capped if capped else "", len(entry_total)))
    # report the top entries by total incoming dispatches, with the predecessor (dispatch) breakdown
    for T, tot in entry_total.most_common(20):
        kinds = collections.Counter()
        for cp, c in entry_pred[T].items(): kinds[mnem(cp)] += c
        kind_s = " ".join("%s:%d" % (k, v) for k, v in kinds.most_common())
        print(">>> $%06X  x%-4d  via %s   [%s]" % (T, tot, kind_s, desc(T)))
        for cp, c in entry_pred[T].most_common(4):
            print(">>>      from $%06X x%-4d [%s]" % (cp, c, desc(cp)))
