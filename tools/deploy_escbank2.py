#!/usr/bin/env python3
"""Deploy a big native escape into the SECOND escape bank (escbank2.pasm, SA-1 $94:8000) and wire a
cross-bank jah2_ext dispatch entry in escbank.pasm ($92). For jsr.l/bsr/jsr(An)-reached escapes (the
jah2 chain, via jsrabs_hook2). Usage: tools/deploy_escbank2.py <hex-addr> [tag].

Why: the $92 bodies region is full ($F000 ceiling); $94 has 384KB free (see
[[escbank-overflow-second-bank]]). The body is --bank2 transpiled (jsl.l/jml.l bank-$00 helpers,
$00FD ibridge sentinel). The $92 jah2_ext scan entry dispatches with `jml entry_X` ($94, fed by
gen_escbank_syms). Builds + smoke-tests; auto-reverts on failure.
"""
import sys, re, subprocess, os
addr = int(sys.argv[1], 16); tag = sys.argv[2] if len(sys.argv) > 2 else ''
hx = '%06X' % addr; lab = 'entry_%x' % (addr & 0xFFFFFF); jx = 'jx_%x' % (addr & 0xFFFFFF)
E2 = 'src/escbank2.pasm'; E1 = 'src/escbank.pasm'
e2 = open(E2).read(); e1 = open(E1).read()
e2_orig, e1_orig = e2, e1
assert ('%s:' % lab) not in e2, "%s already in escbank2" % lab
assert ('%s:' % lab) not in e1, "%s already in escbank ($92) -- $94 deploy would duplicate" % lab
assert '; >>> ESCBANK2_BODIES_END' in e2, "escbank2 BODIES_END marker missing"
assert '; >>> JAH2_EXT_SCAN' in e1, "escbank jah2_ext scan marker missing"

# 1) transpile --bank2 (video if it differs from work mode); reject UNIMPLEMENTED
def tr(*a): return subprocess.run(['python3', 'tools/transpile.py', hx, '--bank2', '--escapes=', *a],
                                  capture_output=True, text=True).stdout
vo = tr('--video'); po = tr()
assert 'jml.l ors_pre' in vo or 'jml.l inext' in vo, "no terminal rts"
assert 'UNIMPLEMENTED' not in vo, "transpile has UNIMPLEMENTED ops"
video = (vo != po); body = vo if video else po
def w(ln):
    t = ln.strip()
    if t == 'jsr writeword': return '    jsl.l writeword_l'
    if t == 'jsr writebyte': return '    jsl.l writebyte_l'
    return ln
body = '\n'.join(w(ln) for ln in body.splitlines()).rstrip()
blk = '; --- $%s %s (escbank2 / $94) ---\n%s\n\n' % (hx, tag, body)
e2 = e2.replace('; >>> ESCBANK2_BODIES_END', blk + '; >>> ESCBANK2_BODIES_END', 1)
open(E2, 'w').write(e2)

# 2) escbank.pasm jah2_ext scan: cmp/bne/prologue/`jml entry_X`($94). Insert at the scan marker.
scan = ("    cmp #$%04X\n    bne %s\n    inc $0764\n    plp\n    pla\n    lda $54\n    sta $40\n"
        "    jml %s          ; <- $%s %s (2nd bank $94)\n%s:\n"
        % (addr & 0xFFFF, jx, lab, hx, tag, jx))
marker = '; >>> JAH2_EXT_SCAN — deploy_escape inserts `cmp/bne/dispatch` blocks before jx_real <<<\n'
assert e1.count(marker) == 1, "scan marker not found uniquely"
e1 = e1.replace(marker, marker + scan, 1)
open(E1, 'w').write(e1)
print("DEPLOYED %s -> escbank2 ($94) %s, jah2_ext scan added (mode=%s)" % (hx, lab, 'video' if video else 'work'))

def revert(why):
    open(E2, 'w').write(e2_orig); open(E1, 'w').write(e1_orig)
    subprocess.run(['bash', 'tools/build_interp.sh'], capture_output=True, text=True)
    print("REVERTED %s -- %s" % (hx, why)); sys.exit(1)

print("building...", flush=True)
b = subprocess.run(['bash', 'tools/build_interp.sh'], capture_output=True, text=True)
if b.returncode != 0 or 'wrote build/interp.sfc' not in b.stdout:
    revert("build failed:\n" + (b.stdout[-700:] + b.stderr[-700:]))
print("smoke-testing...", flush=True)
s = subprocess.run([sys.executable, 'tools/smoke_gameplay.py'], capture_output=True, text=True)
print(s.stdout.strip().splitlines()[-1] if s.stdout.strip() else '(no smoke output)')
if s.returncode != 0 or 'SMOKE: OK' not in s.stdout:
    revert("gameplay smoke-test FAILED")
print("OK %s -- build + smoke PASS. Now run tools/val_frame_diff.py to validate bit-exactness." % hx)
