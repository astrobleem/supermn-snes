#!/usr/bin/env python3
# speedup_bench.py — measure the REAL speedup of native escapes, since the per-frame
# step counter ($4A) is $AC-gated (the main-loop spin absorbs freed steps) and can't
# show it. Metric = wall-clock + Mesen-frames to advance a FIXED amount of game-work
# (N RNG/$412 calls = N game-frames), hook OFF vs ON. Runs OFF twice first to establish
# the noise floor, so a real win is distinguishable from jitter.
#
# NOTE: $000412 is a COLD target (one ~7-instruction call per game-frame) -- it's a
# CORRECTNESS proof, not a speed target, so expect ~1.0x here (within noise). The point
# is the HARNESS: it will show a real ratio once a hot leaf (e.g. rank_hot's $00CB9E,
# ~10 calls/frame) is transpiled. That is the first bulk-transpile step.
import sys, os, time
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15      # game-frames (=$412 hits) per trial
SLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 6

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')

    def trial(hook):
        m.load_state_slot(SLOT)
        m.write_u16(0x410002, 0x0100, 'snesMemory'); m.write_u16(0x410000, 0x0100, 'snesMemory')
        w16(0x0700, 0); w16(0x0702, 0); w16(0x0704, 0)
        w16(0x071A, hook); w16(0x071C, 0); w16(0x4A, 0); w16(0x4C, 0)
        t0, frames = time.time(), 0
        while r16(0x071C) < N and frames < 40000:
            m.run_frames(200); frames += 200
            m.write_u16(0x410002, 0x0100, 'snesMemory'); m.write_u16(0x410000, 0x0100, 'snesMemory')
        return time.time() - t0, frames, r16(0x071C)

    off1 = trial(0)
    off2 = trial(0)
    on = trial(1)
    print('target = %d game-frames (RNG calls) per trial' % N)
    print('  hook OFF #1: %.1fs  %d mesen-frames  hits=%d' % off1)
    print('  hook OFF #2: %.1fs  %d mesen-frames  hits=%d' % off2)
    print('  hook ON    : %.1fs  %d mesen-frames  hits=%d' % on)
    base = (off1[0] + off2[0]) / 2
    noise = abs(off1[0] - off2[0]) / base * 100
    print('  noise floor (OFF vs OFF): %.1f%%' % noise)
    print('  wall-clock speedup OFF->ON: %.3fx  (frames %.3fx)'
          % (base / on[0] if on[0] else 0, ((off1[1] + off2[1]) / 2) / on[1] if on[1] else 0))
    print('  -> $412 is cold; a number meaningfully > 1 + noise appears once a HOT leaf is hooked.')
