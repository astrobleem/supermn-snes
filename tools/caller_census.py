#!/usr/bin/env python3
# Caller census: capture the full interpreted-PC STREAM for one frame (like profile_frame, buffer at
# work-RAM $40:8000, count $0718), then for each hot interpreted entry PC report the distribution of
# its PREDECESSOR PC (the dispatching instruction) + a disasm classification (rts/jsr/jmp). Identifies
# HOW the hot calls reach already-deployed-but-interpreting escapes. Argv: gate (default 1).
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
    try:
        ins = next(md.disasm(IMG[pc:pc+8], pc)); return "%s %s" % (ins.mnemonic, ins.op_str)
    except StopIteration: return "?"
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S = '/tmp/sframe.mss'
GATE = int(sys.argv[1]) if len(sys.argv) > 1 else 1
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7530, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    w16(0x0700,0); w16(0x071A,0); w16(0x0716,0); w16(0x0712,0); w16(0x0714,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
    m.save_state(S); m.load_state(S)
    w16(0x071A,GATE); w16(0x0700,0); w16(0x0712,0); w16(0x0710,0); w16(0x0718,0)
    w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(400):
        w16(0x0710,0x0708); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    nb = r16(0x0718); stream = m.read_memory('snesMemory', 0x408000, min(nb, 0xFFF8))
    pcs = [((stream[i+2]|(stream[i+3]<<8))<<16)|(stream[i]|(stream[i+1]<<8)) for i in range(0, len(stream)-3, 4)]
    print(">>> %d PCs streamed (gate=%d, buf=%s)" % (len(pcs), GATE, "CAP" if nb>=0xFFF8 else "ok"))
    # hot interpreted entries to census (function start PCs). Auto-augment: top regions' min-PC.
    irq = set(range(0x06F0,0x0762)) | {0x0818}
    work = [p for p in pcs if 0x800 <= p < 0x40000 and p not in irq]
    # find the entry PC of each hot 64-byte region = the region PC most often preceded by an out-of-fn PC
    region_ct = collections.Counter(p & ~0x3F for p in work)
    targets = [0x0CE4, 0x13BE]   # known deployed-but-interpreting
    for reg, _ in region_ct.most_common(10):
        # entry candidate: lowest PC seen in [reg, reg+0x40) -- crude but ok
        cand = min((p for p in work if reg <= p < reg+0x40), default=None)
        if cand and cand not in targets: targets.append(cand)
    for T in targets:
        idxs = [i for i, p in enumerate(pcs) if p == T]
        if not idxs: continue
        pred = collections.Counter(pcs[i-1] for i in idxs if i > 0)
        print(">>> $%06X  x%d  callers:" % (T, len(idxs)))
        for cp, c in pred.most_common(4):
            print(">>>      from $%06X x%d   [%s]" % (cp, c, desc(cp)))
