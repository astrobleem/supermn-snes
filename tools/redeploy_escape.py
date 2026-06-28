#!/usr/bin/env python3
"""Re-deploy an already-deployed escbank escape: remove its body + scan block(s), then run
deploy_escape (which re-transpiles, re-appends, builds, smoke-tests, auto-reverts). Needed when a
NEW escape changes how an OLD one should be transpiled -- chiefly bridge-to-escape: once a callee
becomes a deployed escape, the parent must be re-deployed so its interpret-bridge to that callee
turns into a NATIVE bridge (jmp entry_callee). Usage: tools/redeploy_escape.py <hex-addr> [tag].

Removal is anchored precisely: the body runs from `; --- $ADDR ...` to the next body header or the
BODIES_END marker; each scan block from `cmp #$ADDR` to its own `(b)jx_ADDR:` label (backref-matched
so it can't over-eat). Snapshots escbank.pasm first and restores it (+rebuild) on ANY failure."""
import sys, re, subprocess, os
addr = int(sys.argv[1], 16); tag = sys.argv[2] if len(sys.argv) > 2 else ''
hx = '%06X' % addr; lab = 'entry_%x' % (addr & 0xFFFFFF)
PATH = 'src/escbank.pasm'
orig = open(PATH).read()
assert ('%s:' % lab) in orig, "%s not currently deployed in escbank -- use deploy_escape" % lab

# 1) remove the body block: header line .. next body header (opt. leading ws) or BODIES_END.
body_re = re.compile(r'\n;\s*--- \$%s [^\n]*\n.*?(?=\n;\s*--- \$[0-9A-Fa-f]{6}|\n; >>> ESCBANK_BODIES_END)'
                     % hx, re.S)
esc, nb = body_re.subn('', orig)
assert nb == 1, "expected exactly 1 body block for $%s, removed %d" % (hx, nb)

# 2) remove each scan block: `cmp #$XXXX .. (b)jx_XXXX:` (backref ties the closing label to bne tgt).
scan_re = re.compile(r'\n    cmp #\$%04X\n    bne (b?jx_%x)\n.*?\n\1:' % (addr & 0xFFFF, addr & 0xFFFFFF), re.S)
esc, ns = scan_re.subn('', esc)
assert ns >= 1, "expected >=1 scan block for $%s, removed %d" % (hx, ns)
assert ('%s:' % lab) not in esc, "body label still present after removal"
open(PATH, 'w').write(esc)
print("REMOVED %s (%d body, %d scan) -- now re-deploying via deploy_escape" % (hx, nb, ns))

r = subprocess.run([sys.executable, 'tools/deploy_escape.py', hx] + ([tag] if tag else []), text=True)
if r.returncode != 0:
    open(PATH, 'w').write(orig)
    print("REDEPLOY FAILED -- restored original escbank.pasm, rebuilding")
    subprocess.run(['bash', 'tools/build_interp.sh'], capture_output=True, text=True)
    sys.exit(1)
print("REDEPLOYED %s OK" % hx)
