#!/usr/bin/env python3
# leaf_check.py — STATIC, all-paths leaf verification for native-escape safety.
# A function is a SAFE escape target only if, across EVERY reachable path from its
# entry to an rts, it makes no subroutine call, no indirect/computed jump, and no
# device I/O. The trace-based classification in analyze_trace68k is UNSOUND for this:
# it only sees the paths a particular trace happened to take (e.g. $24D98 looked like
# a leaf in the attract trace but takes an indirect `jsr (a2)` on its active path).
# This walks the control-flow graph from the entry and is conservative: any call/
# indirect/IO -> NOT a safe leaf.
import sys, re
import capstone

ROM = open('data/superman_m68k.bin', 'rb').read()
MD = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)

BCC = {'bhi', 'bls', 'bcc', 'bcs', 'bne', 'beq', 'bvc', 'bvs', 'bpl', 'bmi',
       'bge', 'blt', 'bgt', 'ble', 'bhs', 'blo', 'bt', 'bf'}
DIRECT = re.compile(r'^\$[0-9a-f]+(\.[wl])?$')      # plain absolute / resolved PC-rel target
HEX = re.compile(r'\$([0-9a-f]+)')


def is_io(addr):
    if addr < 0x080000:          # program ROM
        return False
    if 0xF00000 <= addr <= 0xF0FFFF:   # work RAM
        return False
    return addr >= 0x300000      # palette/sprite/video/cchip/sound/regs


def first_operand(op):
    return op.split(',')[0].strip() if ',' in op else op.strip()


def check(entry, cap=4000):
    seen, work = set(), [entry]
    calls, indirects, ios, branch_targets = [], [], [], set()
    truncated = False
    while work:
        pc = work.pop()
        if pc in seen:
            continue
        if pc < 0 or pc + 16 > len(ROM):
            indirects.append((pc, 'out-of-range PC'))
            continue
        if len(seen) > cap:
            truncated = True
            break
        insns = list(MD.disasm(ROM[pc:pc + 16], pc, count=1))
        if not insns:
            indirects.append((pc, 'undecodable'))
            continue
        i = insns[0]
        seen.add(pc)
        mn = i.mnemonic.lower()
        op = i.op_str
        base = mn.split('.')[0]
        nxt = i.address + i.size

        for h in HEX.findall(op):
            a = int(h, 16)
            if is_io(a):
                ios.append((pc, a))

        if base in ('jsr', 'bsr'):
            tgt = first_operand(op)
            m = DIRECT.match(tgt)
            if m:
                calls.append((pc, int(HEX.search(tgt).group(1), 16)))
            else:
                indirects.append((pc, 'indirect call ' + tgt))
            work.append(nxt)                     # returns here
        elif base == 'jmp':
            tgt = first_operand(op)
            m = DIRECT.match(tgt)
            if m:
                t = int(HEX.search(tgt).group(1), 16)
                branch_targets.add(t)
                work.append(t)                   # tail jump: follow
            else:
                indirects.append((pc, 'indirect jmp ' + tgt))
        elif base in ('rts', 'rte', 'rtr', 'rtd'):
            pass                                 # path end
        elif base in ('trap', 'trapv', 'chk', 'illegal', 'reset', 'stop'):
            calls.append((pc, 'trap/illegal ' + mn))
            work.append(nxt)
        elif base == 'bra':
            m = HEX.search(op)
            if m:
                t = int(m.group(1), 16); branch_targets.add(t); work.append(t)
        elif base.startswith('db'):              # dbcc: loop back + fall through
            m = HEX.search(op)
            if m:
                t = int(m.group(1), 16); branch_targets.add(t); work.append(t)
            work.append(nxt)
        elif base in BCC:                        # conditional: target + fall through
            m = HEX.search(op)
            if m:
                t = int(m.group(1), 16); branch_targets.add(t); work.append(t)
            work.append(nxt)
        else:
            work.append(nxt)                     # ordinary instruction
    safe = not calls and not indirects and not ios and not truncated
    return {'entry': entry, 'safe_leaf': safe, 'icount': len(seen),
            'calls': calls, 'indirects': indirects, 'ios': ios, 'truncated': truncated,
            'lo': min(seen) if seen else entry, 'hi': max(seen) if seen else entry}


def fmt(r):
    s = 'SAFE-LEAF' if r['safe_leaf'] else 'NOT-LEAF'
    out = ['$%06X  %s  (%d instr, $%06X-$%06X)' % (r['entry'], s, r['icount'], r['lo'], r['hi'])]
    for pc, t in r['calls'][:4]:
        out.append('   call @$%06X -> %s' % (pc, ('$%06X' % t) if isinstance(t, int) else t))
    for pc, t in r['indirects'][:4]:
        out.append('   INDIRECT @$%06X: %s' % (pc, t))
    for pc, a in r['ios'][:4]:
        out.append('   IO @$%06X: $%06X' % (pc, a))
    if r['truncated']:
        out.append('   (truncated at cap)')
    return '\n'.join(out)


if __name__ == '__main__':
    for a in sys.argv[1:]:
        print(fmt(check(int(a, 16))))
