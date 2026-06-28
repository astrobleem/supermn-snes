#!/usr/bin/env python3
"""Deploy a transpiled leaf escape into the escape-bank extension chain (jah2_ext, $92:F000):
transpile (auto --video), append the body + a `cmp/bne/dispatch` scan block in escbank.pasm,
build, smoke-test gameplay, auto-revert on failure. Usage: tools/deploy_escape.py <hex-addr> [tag].

Why the extension chain (not the inline bank-$00 jah2 chain): bank $00's $E200 region is packed
to the point of .org-overlap at $F602 -- ANY byte added there shifts hot code into the overlap
and breaks gameplay silently. jah2_ext lives in the escape bank (32KB free), so appending escapes
never shifts bank-$00 code. The bank-$00 side is a fixed, size-neutral `jml $92F000` at jah2_miss."""
import sys, re, subprocess, os
addr=int(sys.argv[1],16); tag=sys.argv[2] if len(sys.argv)>2 else ''
SKIP_REVERT=os.environ.get('DEPLOY_NOREVERT')=='1'  # leave a broken build in place for diagnosis
hx='%06X'%addr; lab='entry_%x'%(addr&0xFFFFFF); jx='jx_%x'%(addr&0xFFFFFF)
esc=open('src/escbank.pasm').read()
esc_orig=esc  # for auto-revert if the deploy breaks the gameplay path
assert 'ESCBANK_BODIES_END' in esc and 'JAH2_EXT_SCAN' in esc and 'jx_real:' in esc, \
    "escbank.pasm missing jah2_ext markers (run the extension-chain migration first)"
assert ('jmp %s\n'%lab) not in esc and ('%s:'%lab) not in esc, "%s already deployed"%lab
# transpile both modes, pick video if they differ (video mode routes stores through the $41 shadow)
def tr(*a): return subprocess.run(['python3','tools/transpile.py',hx,'--bank1',*a],capture_output=True,text=True).stdout
vo=tr('--video'); po=tr()
assert 'jml.l inext' in vo and 'UNIMPLEMENTED' not in vo and 'CALL-BRIDGE' not in vo, "not a clean leaf"
video = (vo!=po); body=vo if video else po
def _w(ln):
    t=ln.strip()
    if t=='jsr writeword': return '    jsl.l writeword_l'
    if t=='jsr writebyte': return '    jsl.l writebyte_l'
    return ln
body='\n'.join(_w(ln) for ln in body.splitlines())
# 1) append the body just before the BODIES_END marker (stays below .org $F000)
body_blk='; --- $%s %s (jah2_ext) ---\n%s\n\n'%(hx,tag,body.rstrip())
esc=esc.replace('; >>> ESCBANK_BODIES_END', body_blk+'; >>> ESCBANK_BODIES_END',1)
# 2) append a scan block just before jx_real (dispatch jumps within bank $92 to the body label)
scan=("    cmp #$%04X\n    bne %s\n    inc $0764\n    plp\n    pla\n    lda $54\n    sta $40\n"
      "    jmp %s          ; <- $%s %s\n%s:\n"%(addr&0xFFFF,jx,lab,hx,tag,jx))
assert esc.count('jx_real:')==1
esc=esc.replace('jx_real:',scan+'jx_real:',1)
open('src/escbank.pasm','w').write(esc)
print("DEPLOYED %s -> jah2_ext (%s) mode=%s"%(hx,lab,'video' if video else 'work'))

def revert(why):
    if SKIP_REVERT:
        print("NOREVERT set -- leaving broken build in place. %s"%why); sys.exit(2)
    open('src/escbank.pasm','w').write(esc_orig)
    print("REVERTED %s -- %s"%(hx,why))
    subprocess.run(['bash','tools/build_interp.sh'],capture_output=True,text=True)  # restore working ROM
    sys.exit(1)

# build the new ROM; smoke-test catches any runtime break the assembler can't (gameplay path)
print("building...",flush=True)
b=subprocess.run(['bash','tools/build_interp.sh'],capture_output=True,text=True)
if b.returncode!=0:
    revert("build failed:\n"+(b.stdout[-600:]+b.stderr[-600:]))
# gameplay smoke-test: does one real GAME_TICK still run + return? (catches silent branch-wrap)
print("smoke-testing gameplay...",flush=True)
s=subprocess.run([sys.executable,'tools/smoke_gameplay.py'],capture_output=True,text=True)
print(s.stdout.strip())
if s.returncode!=0 or 'SMOKE: OK' not in s.stdout:
    revert("gameplay smoke-test FAILED (deploy broke the execution path)")
print("OK %s -- build + gameplay smoke-test PASS"%hx)
