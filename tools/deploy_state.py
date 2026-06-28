#!/usr/bin/env python3
"""Deploy ONE jmp-table state handler as a coroutine escape dispatched by the ojmp_hook/ojmp_disp
chain (see [[main-loop-coroutine-arch]]). Usage: tools/deploy_state.py <hex-addr>. Adds a cmp/beq to
ojmp_hook (interp.pasm, bank $00) + ojmp_disp (escbank), transpiles the --coroutine --video body
(with --escapes so bsr/jsr callees bridge-to-escape), inserts it, builds. Validate separately with
tools/val_frame_diff.py before committing. Snapshots + restores both files on build failure."""
import sys, re, subprocess
a = sys.argv[1].lower().lstrip('$')
A = a.upper()
IP = 'src/interp.pasm'; ES = 'src/escbank.pasm'
ip0 = open(IP).read(); es0 = open(ES).read()
assert ('entry_%s:' % a) not in es0, "entry_%s already deployed" % a
# bridge-able escapes (end in ors_pre) -> --escapes so this state's bsr/jsr bridge-to-escape
parts = re.split(r'^(entry_[0-9a-f]+):', es0, flags=re.M); able = []
for i in range(1, len(parts), 2):
    addr = parts[i].split('_')[1]; body = parts[i+1]; nxt = body.find('\nentry_')
    if 'jml.l ors_pre' in (body[:nxt] if nxt > 0 else body): able.append(addr)
ESC = ','.join(able)
# 1) ojmp_hook: add `cmp #ADDR / beq ojmp_hit` before `    bra ojmp_x`
ip = ip0
assert ip.count('\n    bra ojmp_x\n') == 1, "ojmp_hook bra ojmp_x marker"
ip = ip.replace('\n    bra ojmp_x\n',
                '\n    cmp #$%s\n    beq ojmp_hit         ; $00%s\n    bra ojmp_x\n' % (A, A), 1)
open(IP, 'w').write(ip)
# 2) ojmp_disp: add `cmp #ADDR / bne ojn_X / jmp entry_X / ojn_X:` before `ojd_x:`
es = es0
assert es.count('\nojd_x:\n') == 1, "ojmp_disp ojd_x marker"
es = es.replace('\nojd_x:\n',
                '\n    cmp #$%s\n    bne ojn_%s\n    jmp entry_%s\nojn_%s:\nojd_x:\n' % (A, a, a, a), 1)
# 3) transpile + insert the body
out = subprocess.run(['python3', 'tools/transpile.py', a, '--bank1', '--coroutine', '--video',
                      '--escapes=' + ESC], capture_output=True, text=True).stdout
assert 'UNIMPLEMENTED' not in out, "transpile has UNIMPLEMENTED ops"
def w(ln):
    t = ln.strip()
    if t == 'jsr writeword': return '    jsl.l writeword_l'
    if t == 'jsr writebyte': return '    jsl.l writebyte_l'
    return ln
body = '\n'.join(w(l) for l in out.splitlines()).rstrip()
blk = '; --- $00%s jmp-table state handler ---\n%s\n\n' % (A, body)
es = es.replace('; >>> ESCBANK_BODIES_END', blk + '; >>> ESCBANK_BODIES_END', 1)
open(ES, 'w').write(es)
b = subprocess.run(['bash', 'tools/build_interp.sh'], capture_output=True, text=True)
if b.returncode != 0 or 'wrote build/interp.sfc' not in b.stdout:
    open(IP, 'w').write(ip0); open(ES, 'w').write(es0)
    subprocess.run(['bash', 'tools/build_interp.sh'], capture_output=True, text=True)
    print("BUILD FAILED -- reverted.\n" + b.stdout[-500:] + b.stderr[-500:]); sys.exit(1)
print("DEPLOYED state $00%s (%d-line body). Now run tools/val_frame_diff.py to validate." % (A, len(body.splitlines())))
