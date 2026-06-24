#!/usr/bin/env python3
# rank_hot.py — rank 68K functions as native-escape / transpile targets by joining:
#  (1) per-entry trace cost (inv * icount) + leaf/io/indirect classification, from
#      analyze_trace68k on a representative MAME frame trace (the arcade's authoritative
#      per-frame call pattern),
#  (2) live PC-ring hotness (sample_pcring.py -> pcring_hist.txt) confirming the
#      function is actually hot in the running interpreter (idle spin/IRQ excluded),
#  (3) the pure-leaf flag (the safe targets, like $412: no calls/indirect/device I/O).
# Output: a ranked table; the top pure leaves are the next hand-transpile targets, each
# = one escape-table entry validated by the hook-off/on differential (lockstep.py argv3).
import sys, os
sys.path.insert(0, 'tools')
import analyze_trace68k as A

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
TRACE = sys.argv[1] if len(sys.argv) > 1 else S + '/f450n.tr'
HIST = sys.argv[2] if len(sys.argv) > 2 else S + '/pcring_hist.txt'

r = A.analyze(TRACE)
agg = r['agg']

live = {}
if os.path.exists(HIST):
    for ln in open(HIST):
        p = ln.split()
        if len(p) == 2:
            live[int(p[0], 16)] = int(p[1])
SPIN = {0x818, 0x6C4, 0x6C8, 0x6CE, 0x6FE, 0x704, 0x708}   # idle main-loop spin + IRQ entry

def live_hits(lo, hi):
    return sum(c for pc, c in live.items() if lo <= pc <= hi and pc not in SPIN)

rows = []
for entry, a in agg.items():
    if not isinstance(entry, int) or entry >= A.ROM_END or a['inv'] == 0:
        continue
    icount = a['icount_max']
    rows.append({
        'entry': entry, 'inv': a['inv'], 'icount': icount, 'cost': a['inv'] * icount,
        'leaf': (a['calls_ever'] == 0 and a['indirect_ever'] == 0 and not a['io']),
        'io': bool(a['io']), 'indirect': a['indirect_ever'] > 0,
        'live': live_hits(a['lo'], a['hi']),
    })

rows.sort(key=lambda x: -x['cost'])
print('=== HOT 68K FUNCTIONS — transpile-target ranking ===')
print('trace=%s  live-hist=%d PCs' % (os.path.basename(TRACE), len(live)))
print('%-8s %4s %6s %6s %4s %3s %3s %5s  %s' %
      ('entry', 'inv', 'icount', 'cost', 'leaf', 'io', 'ind', 'live', 'class'))
for x in rows[:25]:
    cls = ('LEAF' if x['leaf'] else ('io' if x['io'] else ('indirect' if x['indirect'] else 'calls')))
    print('$%06X %4d %6d %6d %4s %3s %3s %5d  %s' %
          (x['entry'], x['inv'], x['icount'], x['cost'],
           'Y' if x['leaf'] else '.', 'Y' if x['io'] else '.',
           'Y' if x['indirect'] else '.', x['live'], cls))

leaves = sorted((x for x in rows if x['leaf']), key=lambda x: -x['cost'])
print('\n=== top PURE-LEAF native-escape targets (safe, same shape as $412) ===')
for x in leaves[:12]:
    note = '  <- $412 (DONE, proof)' if x['entry'] == 0x412 else ''
    print('  $%06X  cost=%-5d inv=%-3d icount=%-3d live=%d%s' %
          (x['entry'], x['cost'], x['inv'], x['icount'], x['live'], note))
print('\nNext: add the top live-confirmed pure leaf to hook_check, hand-transpile its')
print('entry routine (scratch in $80-$9E), validate via lockstep.py argv3 hook-off/on.')
