#!/usr/bin/env python3
# Free-running gameplay profiler: from the NAT (jh_spin), release with escapes ON + PC streaming ON,
# let the game run MANY real IRQ ticks (not just one $0708 capture), then histogram all interpreted
# PCs by 64-byte region. Unlike profile_0708 (one captured tick), this sweeps whatever code paths the
# free-running gameplay actually exercises across N frames -- surfacing interpreted work the single
# tick misses (input handling, other dispatcher cases). Argv: nframes (default 90).
import sys, os, collections, subprocess
if os.environ.get('_W') != '1':
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=620, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.startswith('>>>') or l.startswith('  $') or 'Error' in l or 'Trace' in l))
    sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'
NFR = int(sys.argv[1]) if len(sys.argv) > 1 else 90
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7529, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    # release jh_spin: escapes ON, no debug-freeze, PC streaming ON. Then free-run NFR frames.
    w16(0x0710, 0); w16(0x0712, 0); w16(0x0714, 0); w16(0x0716, 0)
    w16(0x071A, 1)                                       # escapes ON
    w16(0x0718, 0)                                       # PC streaming ON (count at $0718)
    w16(0x0700, 0); w16(0x0704, 1)                       # release jh_spin -> free-running gameplay
    runf(NFR)
    nb = r16(0x0718); stream = m.read_memory('snesMemory', 0x408000, min(nb, 0xFFF8))
    pcs = [((stream[i+2] | (stream[i+3] << 8)) << 16) | (stream[i] | (stream[i+1] << 8)) for i in range(0, len(stream) - 3, 4)]
    irq = {0x06F0, 0x06F2, 0x06FA, 0x0700, 0x0704, 0x0708, 0x070E, 0x0710, 0x0712, 0x0716, 0x0818,
           0x06C4, 0x06C8, 0x06CE, 0x06FE, 0x0704}
    work = [p for p in pcs if 0x800 <= p < 0x40000 and p not in irq]
    print(">>> free-run %d frames: %d streamed PCs, %d interpreted game-code PCs (buffer %s)"
          % (NFR, len(pcs), len(work), "FULL/capped" if nb >= 0xFFF8 else "ok"))
    for region, c in collections.Counter(p & ~0x3F for p in work).most_common(24):
        print("  $%06X  %5d  (%4.1f%%)" % (region, c, 100 * c / max(len(work), 1)))
