#!/usr/bin/env python3
# sample_pcring.py — histogram the LIVE interpreter's 68K PC ring buffer to find
# the hot code in the actual running game (signal 2 for rank_hot.py). The ring is
# the interp's last 128 fetched 68K PCs at Sa1Memory $0400 (4 bytes each: lo16,hi16).
# Loads slot6 (live gameplay), runs N sample windows (run_frames(STEP) between
# samples so the ring refreshes), and counts each 68K PC. Writes pcring_hist.txt.
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession
from collections import Counter

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 150       # sample windows
STEP = int(sys.argv[2]) if len(sys.argv) > 2 else 8      # Mesen frames between samples
SLOT = int(sys.argv[3]) if len(sys.argv) > 3 else 6

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    m.load_state_slot(SLOT)
    hist = Counter()
    for _ in range(N):
        m.run_frames(STEP)
        ring = m.read_memory('Sa1Memory', 0x0400, 0x200)
        for k in range(128):
            o = k * 4
            pc = ((ring[o+2] | (ring[o+3] << 8)) << 16) | (ring[o] | (ring[o+1] << 8))
            hist[pc] += 1
    lines = ['%06X %d' % (pc, c) for pc, c in hist.most_common()]
    open(S + '/pcring_hist.txt', 'w').write('\n'.join(lines))
    print('live PC-ring histogram: %d distinct PCs over %d windows (slot %d)' % (len(hist), N, SLOT))
    print('top 25 hottest 68K PCs:')
    for pc, c in hist.most_common(25):
        print('  $%06X  %d' % (pc, c))
