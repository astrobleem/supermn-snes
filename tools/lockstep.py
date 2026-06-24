#!/usr/bin/env python3
# Lock-step differential validation: inject MAME's frame-N 68K state into the
# interpreter, run exactly one game-frame (freeze at the next $3A92 via the
# jsrabs_hook), and diff the interp's resulting work RAM vs MAME's frame N+1.
import sys, os, time
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
wramA = open(S + '/wramA.bin', 'rb').read()
wramB = open(S + '/wramB.bin', 'rb').read()
regs = open(S + '/regsA.bin', 'rb').read()
def be32(d, o): return (d[o] << 24) | (d[o+1] << 16) | (d[o+2] << 8) | d[o+3]
# regsA layout: D0-D7(8), A0-A6(7), SP(A7), USP, SR
D = [be32(regs, i*4) for i in range(8)]
A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]  # A0-A6, A7=SP
USP = be32(regs, 16*4); SR = be32(regs, 17*4)
print('Injecting D=%s' % [hex(x) for x in D])
print('          A=%s  USP=%X SR=%04X' % ([hex(x) for x in A], USP, SR))

def le16(v): return '%02x%02x' % (v & 0xFF, (v >> 8) & 0xFF)
def le32(v): return '%02x%02x%02x%02x' % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF)

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(mt, a): b = m.read_memory(mt, a, 2); return b[0] | (b[1] << 8)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)

    m.load_state_slot(6)
    # arm the hook, clear markers
    w16(0x0700, 1); w16(0x0702, 0); w16(0x0704, 0)
    # run until frozen at B0 (interp's own next $3A92)
    for _ in range(20):
        m.run_frames(60)
        if r16('Sa1Memory', 0x0702): break
    print('B0 frozen: $0702=%X  68K PC before inject=%04X' % (r16('Sa1Memory', 0x0702), r16('Sa1Memory', 0x40)))

    # ---- inject MAME frame-300 state ----
    # D0-D7 @ $00-$1F, A0-A7 @ $20-$3F  (each 32-bit little-endian: lo16@+0 hi16@+2)
    regblk = ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8))
    wh(0x00, regblk)                 # $00-$3F
    wh(0x40, le32(0x00003A92))       # PC = $3A92 (low16@$40, high16@$42)
    # flags from SR=$2704: Z set, N=V=C=X=0 ; SR int-mask=7
    w16(0x60, 1)                     # Z (nonzero = set)
    w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)   # C N V X
    w16(0x7C, 7)                     # SR interrupt mask
    w16(0xA4, USP & 0xFFFF); w16(0xA6, (USP >> 16) & 0xFFFF)  # USP
    w16(0xA8, 1)                     # C-Chip phase = input mailbox
    w16(0xAA, 0)                     # IRQ pending clear
    AC = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x7000
    w16(0xAC, AC)                    # frame countdown fresh
    print('  (injected $AC = %04X)' % AC)
    w16(0x4A, 0); w16(0x4C, 0)       # step counter reset (avoid cap)
    w16(0x0718, 0xFFF8)              # disable PC streaming (speed) -- already captured
    # work RAM 16KB -> BW-RAM $40:0000
    wh(0x400000, wramA.hex(), 'snesMemory')
    # input (argv[2] = JOY1 active-high bits, e.g. 0x0100=Right); matches MAME's held input
    INP = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    w16(0x410000, INP, 'snesMemory'); w16(0x410002, INP, 'snesMemory')
    print('  (injected input $410000 = %04X)' % INP)

    print('  $AC right after inject (pre-release) = %04X' % r16('Sa1Memory', 0xAC))
    # release -> run exactly one game-frame -> freeze at B1
    w16(0x0702, 0)
    w16(0x0704, 1)
    for _ in range(150):
        m.run_frames(60)
        if r16('Sa1Memory', 0x0702): break
    print('B1 frozen: $0702=%X' % r16('Sa1Memory', 0x0702))

    # dump the interp's 68K PC ring ($0400, 64 entries x4: lo16,hi16; write idx @ $48) at B1
    ring = m.read_memory('Sa1Memory', 0x0400, 0x200)
    idx = m.read_memory('Sa1Memory', 0x48, 2)[0] | (m.read_memory('Sa1Memory', 0x49, 1)[0]<<8)
    def pc_at(o): return ((ring[o+2]|(ring[o+3]<<8))<<16)|(ring[o]|(ring[o+1]<<8))
    pcs = [pc_at((idx+4*k) & 0x1FF) for k in range(128)]   # oldest -> newest
    print('interp last 90 68K PCs @B1:', ' '.join('%05X' % p for p in pcs[-90:]))

    instr = r16('Sa1Memory', 0x4A) | (r16('Sa1Memory', 0x4C) << 16)
    print('interp 68K instr count B0->B1 = %d  (MAME noloop frame-450 = 12209)' % instr)
    print('  $AC at B1 = %04X (reload const $7000=28672); $AA=%X' % (r16('Sa1Memory', 0xAC), r16('Sa1Memory', 0xAA)))
    # dump the streamed full-frame PC list ($40:8000+, $0718 = byte count)
    nbytes = r16('Sa1Memory', 0x0718)
    stream = m.read_memory('snesMemory', 0x408000, min(nbytes, 0xFFF8))
    spcs = [((stream[i+2] | (stream[i+3] << 8)) << 16) | (stream[i] | (stream[i+1] << 8))
            for i in range(0, len(stream) - 3, 4)]
    open(S + '/interp_pcs.txt', 'w').write('\n'.join('%06X' % p for p in spcs))
    print('streamed %d interp PCs -> interp_pcs.txt' % len(spcs))
    out = m.read_memory('snesMemory', 0x400000, 0x4000)   # interp frame-301 work RAM
    open(S + '/interp_out.bin', 'wb').write(bytes(out))
    # exclude $3F00-$3F47: MAME's extraction clobbered that region to stash regs, so
    # wramB is dirty there (not a real interp/MAME divergence).
    diff = [i for i in range(0x4000) if out[i] != wramB[i] and not (0x3F00 <= i < 0x3F48)]
    print('=== RESULT: interp frame-N+1 vs MAME wramB: %d / 16384 bytes differ ===' % len(diff))
    if diff:
        print('first 48 diff offsets:', ['%04X' % x for x in diff[:48]])
        for o in diff[:12]:
            print('  $%04X: interp=%02X mame=%02X' % (o, out[o], wramB[o]))
    else:
        print('  *** BIT-EXACT MATCH — interpreter reproduced MAME frame exactly ***')
