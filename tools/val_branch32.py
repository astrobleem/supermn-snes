#!/usr/bin/env python3
# Regression guard for the transpiler 32-bit compare/tst flag codegen (transpile.py _branch32).
# Captures the ACTUAL asm emit_branch32 emits for every signed/unsigned/tst branch, executes it
# symbolically against the 65816 flag state, and checks TAKEN vs the TRUE 68K 32-bit outcome over
# edge-case operands (sign boundaries, overflow, high-word-differs, equal). 0 FAILURES = correct.
# See memory [[transpiler-32bit-flag-bug]]. Run: python3 tools/val_branch32.py
# RIGOROUS validation: capture the ACTUAL asm emit_branch32 emits, then execute it symbolically
# against the 65816 flag state, and compare TAKEN vs the true 68K 32-bit outcome. Executing the
# real emitted code (not a hand-transcription) removes simulator/transpiler disagreement.
import sys; sys.path.insert(0,'tools')
import transpile as T

class Cap(T.Emit):
    def __init__(s): super().__init__(pfx='v'); s.n=0
def capture(base, fsrc, low='$8A'):
    e=Cap()
    def jmp(): e('__TAKE__')          # marker for the taken-branch
    T._branch32(e, base, jmp, fsrc, low)
    return e.lines

def run(lines, N,V,C,Zhi, lowval):
    """execute the emitted lines; flags N,V,C,Z; `lda $8A` loads lowval (sets Z,N; V/C unchanged).
       returns True if __TAKE__ is reached."""
    Z=Zhi
    # build label index
    idx={}
    for i,l in enumerate(lines):
        if l.endswith(':'): idx[l[:-1]]=i
    i=0; steps=0
    while i < len(lines):
        steps+=1
        if steps>1000: raise SystemExit('loop')
        l=lines[i].strip()
        if l=='__TAKE__': return True
        if l.endswith(':'): i+=1; continue
        parts=l.split()
        op=parts[0]; arg=parts[1] if len(parts)>1 else None
        def go(a): return idx[a]
        if op=='lda':
            v=lowval & 0xFFFF
            Z=1 if v==0 else 0; N=(v>>15)&1
            i+=1; continue
        if op=='bra': i=go(arg); continue
        if op=='beq': i=go(arg) if Z==1 else i+1; continue
        if op=='bne': i=go(arg) if Z==0 else i+1; continue
        if op=='bmi': i=go(arg) if N==1 else i+1; continue
        if op=='bpl': i=go(arg) if N==0 else i+1; continue
        if op=='bvs': i=go(arg) if V==1 else i+1; continue
        if op=='bvc': i=go(arg) if V==0 else i+1; continue
        if op=='bcc': i=go(arg) if C==0 else i+1; continue
        if op=='bcs': i=go(arg) if C==1 else i+1; continue
        raise SystemExit('unhandled op %r'%l)
    return False   # fell through = not taken

def sbc16(a,m,cin):
    full=a-m-(1-cin); r=full&0xFFFF
    return r,(1 if full>=0 else 0),(r>>15)&1,(1 if r==0 else 0),(1 if ((a^m)&(a^r)&0x8000) else 0)
def flags_cmp(dest,src):
    dlo,dhi=dest&0xFFFF,(dest>>16)&0xFFFF; slo,shi=src&0xFFFF,(src>>16)&0xFFFF
    low,c1,_,_,_=sbc16(dlo,slo,1); _,C,N,Zhi,V=sbc16(dhi,shi,c1)
    return N,V,C,Zhi,low
def s32(x): return x-0x100000000 if x>=0x80000000 else x
def true68k(base,d,s):
    ds,ss=s32(d),s32(s)
    return {'beq':d==s,'bne':d!=s,'blt':ds<ss,'bge':ds>=ss,'ble':ds<=ss,'bgt':ds>ss,
            'bcc':d>=s,'bcs':d<s,'bhi':d>s,'bls':d<=s,'bmi':(d-s)&0x80000000!=0,'bpl':(d-s)&0x80000000==0}[base]
def true_tst(base,v):
    s=s32(v)
    return {'beq':v==0,'bne':v!=0,'bmi':v&0x80000000!=0,'bpl':v&0x80000000==0,'blt':s<0,'bge':s>=0,'ble':s<=0,'bgt':s>0}[base]

vals=[0,1,2,0xFFFF,0x10000,0x10001,0x7FFF,0x8000,0x7FFFFFFF,0x80000000,0x80000001,0xFFFFFFFF,
      0x1869F,0x1F4,0x12345678,0xFEDCBA98,0x00010000,0x0000FFFF,0x00018000,0xABCD0000,0x00007FFF]
fails=0; tot=0
for base in ['beq','bne','blt','bge','ble','bgt','bcc','bcs','bhi','bls','bmi','bpl']:
    lines=capture(base,'signed32')
    for d in vals:
        for s in vals:
            tot+=1; N,V,C,Zhi,low=flags_cmp(d,s)
            got=run(lines,N,V,C,Zhi,low); exp=true68k(base,d,s)
            if got!=exp:
                fails+=1
                if fails<=15: print("SIGNED %s d=%08X s=%08X got=%s exp=%s"%(base,d,s,got,exp))
for base in ['beq','bne','bmi','bpl','blt','bge','ble','bgt']:
    lines=capture(base,'tst32')
    for v in vals:
        tot+=1; hi=(v>>16)&0xFFFF; lo=v&0xFFFF
        # tst.l setup: `lda hi` -> N=bit15(hi), Z=(hi==0); low ref = lo
        N=(hi>>15)&1; Zhi=1 if hi==0 else 0
        got=run(lines,N,0,0,Zhi,lo); exp=true_tst(base,v)
        if got!=exp:
            fails+=1
            if fails<=15: print("TST %s v=%08X got=%s exp=%s"%(base,v,got,exp))
print("\n%d cases, %d FAILURES -> %s"%(tot,fails,"ALL CORRECT" if fails==0 else "BUGS"))
