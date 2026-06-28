#!/usr/bin/env python3
# jsr-path profiler: measure the REMAINING interpreted instructions during a REAL GAME_TICK, i.e.
# through the actual `jsr $3A92` dispatch (escapes ON), where the $3A92 escape + its native callees
# run on the SA-1 and DON'T stream -- only interpret-bridged callees / un-escaped code go through
# inext and stream. profile_nat sets PC=$3A92, which BYPASSES the escape and measures the fully-
# INTERPRETED GAME_TICK (~127 PCs); this measures what's actually left interpreted in gameplay.
# Capture at the IRQ jsr site ($0708, escapes off), then run the real jsr with PC-streaming on.
import sys, os, collections, subprocess
if os.environ.get('_W') != '1':                         # 2 python levels (Nexen-under-Bash signal-16)
    os.environ['_W'] = '1'
    r = subprocess.run([sys.executable] + sys.argv, capture_output=True, text=True, timeout=620, env=os.environ)
    print('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.startswith('>>>') or l.startswith('  $') or 'Error' in l or 'Trace' in l or 'assert' in l.lower()))
    sys.exit(r.returncode)
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT'] = '/home/chad/.dotnet10'; os.environ['PATH'] = '/home/chad/.dotnet10:' + os.environ.get('PATH', '')
import mesen_mcp.session as _sess; _sess.validate_mesen_build = lambda *a, **k: None
from mesen_mcp import McpSession
NEXEN = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT = '/tmp/b0_native.mss'; S0708 = '/tmp/s0708.mss'
GATE = int(sys.argv[1]) if len(sys.argv) > 1 else 1     # 1 = escapes ON (jsr-path); 0 = OFF (fully interp, ~127)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen=NEXEN, port=7528, boot_wait=6.0, socket_timeout=300.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def runf(n, c=300):
        d = 0
        while d < n: x = min(c, n - d); m.run_frames(x); d += x
    runf(150); m.load_state(NAT)
    # capture S0708 (escapes off so the lockstep/flow is clean and deterministic)
    w16(0x0700, 0); w16(0x071A, 0); w16(0x0716, 0); w16(0x0712, 0); w16(0x0714, 0); w16(0x0710, 0x0708)
    w16(0x0704, 1)
    cap = False
    for _ in range(240):
        runf(5)
        if r16(0x0712): cap = True; break
    assert cap, "never reached $0708"
    m.save_state(S0708)
    # run the real jsr $3A92 with PC-streaming on; trap at the return $070E
    m.load_state(S0708)
    w16(0x071A, GATE); w16(0x0700, 0); w16(0x0712, 0); w16(0x0710, 0)
    w16(0x0718, 0)                                       # ENABLE PC streaming ($40:8000+, count $0718)
    w16(0x0714, 1); runf(1); w16(0x0714, 0)              # release past the one-shot $0708 freeze
    ok = False
    for _ in range(200):
        w16(0x0710, 0x070E); w16(0x0716, 0)
        runf(4)
        if r16(0x0712): ok = True; break
    nb = r16(0x0718); stream = m.read_memory('snesMemory', 0x408000, min(nb, 0xFFF8))
    pcs = [((stream[i + 2] | (stream[i + 3] << 8)) << 16) | (stream[i] | (stream[i + 1] << 8)) for i in range(0, len(stream) - 3, 4)]
    # exclude the IRQ-handler glue around the call site (not GAME_TICK work)
    irq = {0x06F0, 0x06F2, 0x06FA, 0x0700, 0x0704, 0x0708, 0x070E, 0x0710, 0x0712, 0x0716, 0x0818}
    work = [p for p in pcs if 0x800 <= p < 0x40000 and p not in irq]
    # gate=0 (escapes OFF) is the fully-interpreted baseline for THIS state; gate=1 (ON) is what's
    # actually left interpreted in real gameplay (escaped glue + native callees don't stream).
    print(">>> jsr-path (gate=%d=%s) trapped=%s: %d streamed PCs, %d interpreted GAME_TICK instrs"
          % (GATE, 'escapes ON' if GATE else 'OFF', ok, len(pcs), len(work)))
    buckets = collections.Counter(p & ~0x3F for p in work)
    print(">>> top interpreted regions remaining in the real jsr path:")
    for region, c in buckets.most_common(16):
        print("  $%06X  %5d  (%4.1f%%)" % (region, c, 100 * c / max(len(work), 1)))
