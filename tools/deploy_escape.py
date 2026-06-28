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
assert all(k in esc for k in ('ESCBANK_BODIES_END','JAH2_EXT_SCAN','jx_real:','JAH2_EXT_BSR_SCAN','jxb_real:')), \
    "escbank.pasm missing jah2_ext markers (run the extension-chain migration first)"
assert ('%s:'%lab) not in esc, "%s already deployed (escbank)"%lab
# also reject if already deployed as a bank-$00 gap escape in interp.pasm (e.g. inline bsr/jah2
# chains reference entry_X there) -- else we'd create a DUPLICATE label that never fires
_interp=open('src/interp.pasm').read()
assert ('%s:'%lab) not in _interp, "%s already deployed (interp.pasm gap escape -- inline chain handles it)"%lab

# Detect how $addr is called -> which hook chain(s) dispatch it. jsr.l/jsr.w/jsr(An) -> jah2_ext
# (jsrabs_hook2); bsr / jsr(d16,PC) -> jah2_ext_bsr (bsr_hookpush). Append only to the chain(s)
# that can actually reach it (an indirect jsr(An) shows as neither -> default to jah2_ext).
def call_type(a):
    img=open('build/interp.sfc','rb').read()[0x10000:0x10000+0x40000]; a&=0xFFFFFF
    jsr = (a<0x10000 and bytes([0x4e,0xb8])+a.to_bytes(2,'big') in img) or (bytes([0x4e,0xb9])+a.to_bytes(4,'big') in img)
    bsr=False; i=0
    while i<len(img)-3:
        if img[i]==0x4e and img[i+1]==0xba:                      # jsr (d16,PC)
            if (i+2+int.from_bytes(img[i+2:i+4],'big',signed=True))&0xFFFFFF==a: bsr=True
        elif img[i]==0x61:                                       # bsr.b / bsr.w
            d=int.from_bytes(img[i+2:i+4],'big',signed=True) if img[i+1]==0 else (img[i+1]-256 if img[i+1]>=128 else img[i+1])
            if (i+2+d)&0xFFFFFF==a: bsr=True
        i+=1
    return jsr, bsr
do_jsr, do_bsr = call_type(addr)
if not do_jsr and not do_bsr: do_jsr=True                        # indirect jsr(An) -> jah2_ext path
# BRIDGE-TO-ESCAPE: a callee that's an escbank escape whose terminal rts routes through ors_pre
# (jml.l ors_pre) can be run NATIVELY from this escape (vs interpreted). Collect those addrs and pass
# them via --escapes so gen_call dispatches a native bridge to them. (Escapes deployed before this
# feature end in `jml.l inext` and are NOT bridge-to-escape-able -> excluded.)
_esc_addrs=[]; _cur=None
for ln in esc.splitlines():
    m=re.match(r'^entry_([0-9a-f]+):',ln)
    if m: _cur=m.group(1)
    elif _cur and ln.strip()=='jml.l ors_pre': _esc_addrs.append(_cur); _cur=None  # body ends in ors_pre rts
ESCAPES_ARG='--escapes='+','.join(_esc_addrs) if _esc_addrs else '--noescapes'
if os.environ.get('DEPLOY_NOB2E'): ESCAPES_ARG='--noescapes'   # debug: force all interpret-bridge
# transpile both modes, pick video if they differ (video mode routes stores through the $41 shadow)
def tr(*a): return subprocess.run(['python3','tools/transpile.py',hx,'--bank1',ESCAPES_ARG,*a],capture_output=True,text=True).stdout
vo=tr('--video'); po=tr()
# CALL-BRIDGE is now allowed (bank-aware $00FE sentinel + ors_pre resume in bank $92). Still reject
# UNIMPLEMENTED. A bridged escape interprets its callees (which may themselves be escaped, separately).
assert 'jml.l ors_pre' in vo and 'UNIMPLEMENTED' not in vo, "transpile has UNIMPLEMENTED ops (or no terminal rts)"
if 'CALL-BRIDGE' in vo: print("note: %s is a BRIDGED escape (interprets its callees via $00FE sentinel)"%hx)
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
# 2) append a scan block before the matching chain's miss label (dispatch jmps within bank $92).
#    jah2_ext (jsr): plp/pla then PC=return.  jah2_ext_bsr (bsr): PC=return then pla (no php).
chains=[]
if do_jsr: chains.append(('jx_real:', jx, "    plp\n    pla\n    lda $54\n    sta $40\n"))
if do_bsr: chains.append(('jxb_real:', 'b'+jx, "    lda $54\n    sta $40\n    pla\n"))
for miss_lbl, jlab, prologue in chains:
    scan="    cmp #$%04X\n    bne %s\n    inc $0764\n%s    jmp %s          ; <- $%s %s\n%s:\n"%(
        addr&0xFFFF, jlab, prologue, lab, hx, tag, jlab)
    assert esc.count(miss_lbl)==1
    esc=esc.replace(miss_lbl, scan+miss_lbl, 1)
open('src/escbank.pasm','w').write(esc)
cn='+'.join(([ 'jah2_ext'] if do_jsr else [])+(['jah2_ext_bsr'] if do_bsr else []))
print("DEPLOYED %s -> %s (%s) mode=%s"%(hx, cn, lab, 'video' if video else 'work'))

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
