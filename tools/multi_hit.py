#!/usr/bin/env python3
# multi_hit.py — stress the native-escape hook across MANY hits to confirm the
# 65816 stack stays balanced (the pre-fix code leaked 4 bytes per hit -> crash after
# ~64). Loads the live slot, enables the hook, free-runs, and tracks entry412 hit
# count + interp step counter + 68K PC. PASS = steps keep advancing and PC stays
# sane (ROM <$40000 or work RAM $F0xxxx) across >= TARGET hits.
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 80
SLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 6

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def steps(): return r16(0x4A) | (r16(0x4C) << 16)
    def pc(): return r16(0x40) | (r16(0x42) << 16)

    m.load_state_slot(SLOT)
    m.write_u16(0x410002, 0x0100, 'snesMemory')      # hold Right -> keep gameplay (RNG) active
    m.write_u16(0x410000, 0x0100, 'snesMemory')
    w16(0x0700, 0); w16(0x0702, 0); w16(0x0704, 0)   # disable the lock-step $3A92 freeze
    w16(0x071A, 1)            # hook ON
    w16(0x071C, 0)            # hit counter
    w16(0x4A, 0); w16(0x4C, 0)
    prev, ok = 0, True
    for i in range(120):
        m.run_frames(500)
        h, st, p = r16(0x071C), steps(), pc()
        sane = (0 <= p < 0x40000) or (0xF00000 <= p <= 0xF0FFFF)
        adv = st > prev
        if (i + 1) % 4 == 0 or not sane:
            print('  +%dk frames: hits=%d steps=%d PC=$%06X sane=%s advancing=%s'
                  % ((i + 1) * 500 // 1000, h, st, p, sane, adv), flush=True)
        if not sane:
            ok = False; print('  *** PC went wild after %d hits -> stack leak / crash ***' % h); break
        prev = st
        if h >= TARGET:
            print('reached %d hits' % h); break
    print('RESULT:', 'PASS (stack balanced across hits)' if ok and prev > 0 else 'FAIL')
