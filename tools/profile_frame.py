#!/usr/bin/env python3
# Deterministic FULL-FRAME profiler: capture at the IRQ jsr site ($0708), then run ONE full frame
# (GAME_TICK + the $75C coroutine scheduler + the resumed task body) and trap at the NEXT IRQ entry,
# histogramming every interpreted PC. profile_0708 traps at $070E (GAME_TICK only); this continues
# through the scheduler/task work that profile_0708 misses -- the main-loop coroutine tail. Single
# frame from a fixed state = deterministic (unlike profile_gameplay's free-run). Argv: gate (1=ON).
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
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S = '/tmp/sframe.mss'
GATE = int(sys.argv[1]) if len(sys.argv) > 1 else 1
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7530, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    # capture at the $0708 IRQ jsr site (escapes off for a clean deterministic capture)
    w16(0x0700, 0); w16(0x071A, 0); w16(0x0716, 0); w16(0x0712, 0); w16(0x0714, 0); w16(0x0710, 0x0708)
    w16(0x0704, 1)
    cap = False
    for _ in range(240):
        runf(5)
        if r16(0x0712): cap = True; break
    assert cap, "never reached $0708"
    m.save_state(S)
    # run ONE full frame with PC streaming on; release past this $0708, then trap at the NEXT $0708.
    m.load_state(S)
    w16(0x071A, GATE); w16(0x0700, 0); w16(0x0712, 0); w16(0x0710, 0); w16(0x0718, 0)
    w16(0x0714, 1); runf(1); w16(0x0714, 0)              # release past the one-shot $0708 freeze
    ok = False
    for _ in range(400):
        w16(0x0710, 0x0708); w16(0x0716, 0)             # re-arm trap at the NEXT IRQ jsr site
        runf(4)
        if r16(0x0712): ok = True; break
    nb = r16(0x0718); stream = m.read_memory('snesMemory', 0x408000, min(nb, 0xFFF8))
    pcs = [((stream[i+2] | (stream[i+3] << 8)) << 16) | (stream[i] | (stream[i+1] << 8)) for i in range(0, len(stream) - 3, 4)]
    irq = {0x06F0, 0x06F2, 0x06FA, 0x0700, 0x0704, 0x0708, 0x070E, 0x0710, 0x0712, 0x0716, 0x0818,
           0x074C, 0x0750, 0x0752, 0x0754, 0x0758, 0x075C, 0x075E, 0x0760}     # IRQ + scheduler glue
    work = [p for p in pcs if 0x800 <= p < 0x40000 and p not in irq]
    gt = [p for p in work if 0x3A00 <= p < 0x3F00 or 0x1500 <= p < 0x1900]      # GAME_TICK subtree
    ml = [p for p in work if p not in set(gt)]                                  # main-loop / task bodies
    print(">>> full frame (gate=%d) trapped=%s: %d streamed, %d interpreted (%d GAME_TICK, %d main-loop) buf=%s"
          % (GATE, ok, len(pcs), len(work), len(gt), len(ml), "CAP" if nb >= 0xFFF8 else "ok"))
    for region, c in collections.Counter(p & ~0x3F for p in ml).most_common(20):
        print("  $%06X  %5d  (%4.1f%%)" % (region, c, 100 * c / max(len(ml), 1)))
