#!/usr/bin/env python3
# $0708 validation harness: validate a $3A92 (GAME_TICK) escape by running the REAL `jsr $3A92` from
# the IRQ handler's call site ($0708), escapes ON vs OFF, trapping at the return $070E, diffing $40+$41.
# The normal tick-diff sets PC=$3A92 directly, which BYPASSES the jsr-dispatched $3A92 escape; this
# goes through the real dispatch (jsrabs_hook2 -> jah2_ext) so a $3A92 escape actually fires.
# Capture: from the NAT (jh_spin), run forward (lockstep off, escapes off) to the next $0708 via the
# debug-freeze, save S0708. Then per gate: release past the one-shot $0708 freeze, re-arm $070E, run.
import sys, os, subprocess
if os.environ.get('_W') != '1':                         # 2 python levels (Nexen-under-Bash signal-16)
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=620, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.startswith('>>>') or 'Error' in l or 'Trace' in l or 'assert' in l.lower()))
    sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S0708 = '/tmp/s0708.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7526, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def rd(a, n, mt='snesMemory'): return bytes(m.read_memory(mt, a, n))
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    # --- capture S0708: from the NAT, run to the next IRQ `jsr $3A92` site ($0708) ---
    w16(0x0700, 0); w16(0x071A, 0); w16(0x0716, 0); w16(0x0712, 0); w16(0x0714, 0); w16(0x0710, 0x0708)
    w16(0x0704, 1)                                       # release jh_spin -> runs GAME_TICK, IRQ flow...
    cap = False
    for _ in range(240):
        runf(5)
        if r16(0x0712): cap = True; break
    assert cap, "never reached $0708 from the NAT"
    m.save_state(S0708)
    print(">>> captured S0708 (PC=$%04X:%04X)" % (r16(0x42), r16(0x40)))
    TRAP = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x070E   # default: GAME_TICK return
    def one_tick(gate):
        m.load_state(S0708)                             # frozen in df_spin at $0708
        a7 = r16(0x3C) | (r16(0x3E) << 16)
        w16(0x071A, gate); w16(0x0700, 0); w16(0x0712, 0); w16(0x0710, 0)
        w16(0x0714, 1); runf(1)                         # release: exits df_spin, stz $0710 (one-shot), runs jsr $3A92
        w16(0x0714, 0)                                  # clear so the trap freeze HOLDS
        ok = False
        for _ in range(160):
            w16(0x0710, TRAP & 0xFFFF); w16(0x0716, (TRAP >> 16) & 0xFFFF)
            runf(4)
            if r16(0x0712): ok = True; break
        regs = rd(0x000000, 0x40, 'Sa1Memory')          # 68K reg file D0-D7/A0-A7 ($00-$3F)
        return ok, rd(0x400000, 0x10000), rd(0x410000, 0x8000), a7 & 0xFFFF, regs
    ok0, o40, o41, a7, oreg = one_tick(0)
    ok1, n40, n41, _, nreg = one_tick(1)
    print(">>> via real jsr $3A92 (trap=$%06X): OFF trapped=%s ON trapped=%s" % (TRAP, ok0, ok1))
    rnames = ['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    rdiff = [rnames[i] + '(off=%08X on=%08X)' % (int.from_bytes(oreg[i*4:i*4+4],'little'), int.from_bytes(nreg[i*4:i*4+4],'little'))
             for i in range(16) if oreg[i*4:i*4+4] != nreg[i*4:i*4+4]]
    if rdiff: print(">>> REG diffs @ trap: %s" % rdiff)
    stk_lo = (a7 - 0x400) & 0xFFFF                       # a7-aware (bridge sentinels live below a7)
    ds = [i for i in range(0x10000) if o40[i] != n40[i]]
    live = [i for i in ds if not (stk_lo <= i < a7)]; stack = [i for i in ds if stk_lo <= i < a7]
    d41 = sum(1 for i in range(0x8000) if o41[i] != n41[i])
    print(">>> $40 diff: %d live + %d transient-stack(<a7=$%04X) ; $41 diff=%d" % (len(live), len(stack), a7, d41))
    if live: print(">>> first LIVE: %s" % ["$F0%04X(off=%02X on=%02X)" % (i, o40[i], n40[i]) for i in live[:10]])
    if d41:
        d41s = [i for i in range(0x8000) if o41[i] != n41[i]]
        print(">>> first $41 diffs: %s" % ["$41%04X(off=%02X on=%02X)" % (i, o41[i], n41[i]) for i in d41s[:14]])
    print(">>>", "GREEN -- $3A92-path escapes bit-exact vs interp%s" % (" (%d benign stack)" % len(stack) if stack else "")
          if (ok0 and ok1 and len(live) == 0 and d41 == 0) else "RED -- live$40=%d $41=%d (off=%s on=%s)" % (len(live), d41, ok0, ok1))
