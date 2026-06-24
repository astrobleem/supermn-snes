#!/usr/bin/env python3
# save_live_state.py — boot the interpreter to its live per-frame loop (task mask
# $F00002 == $0003) and save a Mesen save-state slot, so speed tests can skip the
# ~thousands-of-frames boot. Verifies the slot round-trips SA-1 CPU state + BW-RAM
# (load it back, confirm still live). Falls back to an existing live slot if the
# unattended boot doesn't reach the loop. (SA-1 build: PC/steps in Sa1Memory; the
# 68K task mask is in BW-RAM $40:0002, big-endian.)
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

SLOT = int(sys.argv[1]) if len(sys.argv) > 1 else 7
FALLBACK = int(sys.argv[2]) if len(sys.argv) > 2 else 6   # existing live slot if boot stalls

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def tmask(): b = m.read_memory('snesMemory', 0x400002, 2); return (b[0] << 8) | b[1]
    def pc(): b = m.read_memory('Sa1Memory', 0x40, 2); return b[0] | (b[1] << 8)
    def steps(): b = m.read_memory('Sa1Memory', 0x4A, 4); return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

    live = False
    for i in range(45):
        m.run_frames(100)
        tm = tmask()
        if (i + 1) % 5 == 0:
            print('  @%df tmask=%04X PC=%04X steps=%d' % ((i + 1) * 100, tm, pc(), steps()), flush=True)
        if tm == 0x0003 and steps() > 1000:
            live = True; break

    if not live:
        print('unattended boot did not reach the live loop; using existing slot %d' % FALLBACK)
        m.load_state_slot(FALLBACK)
        if steps() < 100 and tmask() != 0x0003:
            print('FAIL: fallback slot %d is not a live state' % FALLBACK); sys.exit(1)

    m.save_state_slot(SLOT)
    print('saved LIVE state -> slot %d (tmask=%04X PC=%04X)' % (SLOT, tmask(), pc()))
    # round-trip verification
    m.run_frames(60)
    m.load_state_slot(SLOT)
    tm, p, st = tmask(), pc(), steps()
    m.run_frames(30)
    ok = (tmask() == 0x0003) or (pc() in (0x818, 0x532, 0x708)) or (steps() != st)
    print('round-trip reload slot %d: tmask=%04X PC=%04X steps=%d -> live-after-reload=%s'
          % (SLOT, tm, p, st, ok))
    print('RESULT:', 'OK' if ok else 'ROUND-TRIP FAILED')
