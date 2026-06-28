#!/usr/bin/env python3
# Full-FRAME validation: capture at the $0708 IRQ jsr site, run ONE complete frame (GAME_TICK + the
# $75C coroutine scheduler + all resumed task bodies) escapes ON vs OFF, trap at the NEXT IRQ entry,
# and diff work RAM ($40) + video shadow ($41). val_0708_diff only covers GAME_TICK (traps $070E);
# this covers the whole per-frame tick incl. the coroutine task-body escapes (entry_c2f8). a7-aware
# ($40 diffs below a7 are transient stack). Cooperative yields bound the frame, so ON (faster native)
# and OFF reach the same state at the next IRQ -> bit-exact if the escapes are correct.
import sys, os, subprocess
if os.environ.get('_W') != '1':
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=620, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.startswith('>>>') or 'Error' in l or 'Trace' in l))
    sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S = '/tmp/svframe.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7534, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def rd(a, n, mt): return bytes(m.read_memory(mt, a, n))
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    w16(0x0700, 0); w16(0x071A, 0); w16(0x0716, 0); w16(0x0712, 0); w16(0x0714, 0); w16(0x0710, 0x0708)
    w16(0x0704, 1)
    cap = False
    for _ in range(240):
        runf(5)
        if r16(0x0712): cap = True; break
    assert cap, "never reached $0708"
    m.save_state(S)
    def one_frame(gate):
        m.load_state(S)
        a7 = r16(0x3C) | (r16(0x3E) << 16)
        w16(0x071A, gate); w16(0x0700, 0); w16(0x0712, 0); w16(0x0710, 0)
        w16(0x0714, 1); runf(1); w16(0x0714, 0)             # release past this $0708
        ok = False
        for _ in range(400):
            w16(0x0710, 0x0708); w16(0x0716, 0)             # trap at the NEXT IRQ entry
            runf(4)
            if r16(0x0712): ok = True; break
        return ok, rd(0x400000, 0x10000, 'snesMemory'), rd(0x410000, 0x8000, 'snesMemory'), a7 & 0xFFFF
    ok0, o40, o41, a7 = one_frame(0)
    ok1, n40, n41, _ = one_frame(1)
    # Coroutine task bodies run on their OWN stacks (NOT the main a7), so their arg-push frames are
    # transient there -- a7-aware must cover each task stack too. Each entry_X stashes its a7: $0774
    # ($00C300), $0778 ($02658E). 0 if that body didn't run this frame.
    ta7 = [r16(0x0774), r16(0x0778)]
    print(">>> full frame OFF trapped=%s  ON trapped=%s  (main a7=$%04X  task a7s=%s)"
          % (ok0, ok1, a7, ['$%04X' % t for t in ta7]))
    def is_stack(i):           # transient if within 0x400 below the main a7 OR 0x40 below any task a7
        return ((a7 - 0x400) & 0xFFFF) <= i < a7 or any(t and (t - 0x40) <= i < t for t in ta7)
    ds = [i for i in range(0x10000) if o40[i] != n40[i]]
    live = [i for i in ds if not is_stack(i)]; stack = [i for i in ds if is_stack(i)]
    d41 = sum(1 for i in range(0x8000) if o41[i] != n41[i])
    print(">>> $40 diff: %d live + %d transient-stack(<a7) ; $41 diff=%d" % (len(live), len(stack), d41))
    if live: print(">>> first LIVE $40: %s" % ["$40%04X(off=%02X on=%02X)" % (i, o40[i], n40[i]) for i in live[:12]])
    if d41:
        d41s = [i for i in range(0x8000) if o41[i] != n41[i]]
        print(">>> first $41: %s" % ["$41%04X(off=%02X on=%02X)" % (i, o41[i], n41[i]) for i in d41s[:12]])
    print(">>>", "GREEN -- full-frame escapes bit-exact vs interp%s" % (" (%d benign stack)" % len(stack) if stack else "")
          if (ok0 and ok1 and not live and not d41) else "RED -- live$40=%d $41=%d (off=%s on=%s)" % (len(live), d41, ok0, ok1))
