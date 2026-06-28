#!/usr/bin/env python3
"""Deploy a transpiled leaf escape: auto-detect slot, transpile (auto --video), wire escbank jmptab +
interp jah2 chain, build. Usage: tools/deploy_escape.py <hex-addr> [tag]. Prints the slot/mode."""
import sys, re, subprocess
addr=int(sys.argv[1],16); tag=sys.argv[2] if len(sys.argv)>2 else ''
hx='%06X'%addr; lab='entry_%x'%(addr&0xFFFFFF)
esc=open('src/escbank.pasm').read(); interp=open('src/interp.pasm').read()
esc_orig=esc; interp_orig=interp  # for auto-revert if the deploy breaks the gameplay path
# next slot = count of jmptab entries
slot=len(re.findall(r'^    jmp (entry_|gm_memset)', esc, re.M))
tgt=0x928000+slot*3
# transpile both modes, pick video if they differ
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
# escbank: jmptab slot + body. Insert jmptab line after the last `jmp ...; slot` line.
lines=esc.splitlines(); out=[]; ins=False
for i,ln in enumerate(lines):
    out.append(ln)
    if re.match(r'^    jmp (entry_\w+|gm_memset)\s+; slot', ln) and (i+1>=len(lines) or not re.match(r'^    jmp ',lines[i+1])):
        out.append('    jmp %s               ; slot %d ($%06X)  <- $%s %s'%(lab,slot,tgt,hx,tag)); ins=True
assert ins,"jmptab anchor not found"
esc='\n'.join(out).rstrip()+'\n\n'+body.rstrip()+'\n'
open('src/escbank.pasm','w').write(esc)
# interp jah2: add cmp/bne/jmp before jah2_miss, dispatch block before jah2_e412
nN=len(re.findall(r'jah2_n\d+:',interp))
cmp_blk="    cmp #$%04X\n    bne jah2_n%d\n    jmp jah2_e%x\njah2_n%d:\njah2_miss:"%(addr&0xFFFF,nN,addr&0xFFFFFF,nN)
assert interp.count('jah2_miss:')>=1
interp=interp.replace('jah2_miss:',cmp_blk,1)
disp="jah2_e%x:\n    plp\n    pla\n    lda $54\n    sta $40\n    jml $%06X          ; slot %d ($%s)\njah2_e412:"%(addr&0xFFFFFF,tgt,slot,hx)
interp=interp.replace('jah2_e412:',disp,1)
open('src/interp.pasm','w').write(interp)
print("DEPLOYED %s -> slot %d ($%06X) mode=%s"%(hx,slot,tgt,'video' if video else 'work'))

def revert(why):
    open('src/escbank.pasm','w').write(esc_orig); open('src/interp.pasm','w').write(interp_orig)
    print("REVERTED %s -- %s"%(hx,why))
    subprocess.run(['bash','tools/build_interp.sh'],capture_output=True,text=True)  # restore working ROM
    sys.exit(1)

# build the new ROM; a code-shift that wraps a short branch fails to assemble or breaks gameplay
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
