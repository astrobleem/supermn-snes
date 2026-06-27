#!/usr/bin/env python3
"""Rank uncovered gf260-reached call-target functions, classified by transpilability.
Deployed set auto-derived from the interp jah2 chain (cmp #$XXXX) + bank-relative entries.
Needs /tmp/gf260_pcs.txt (from stream_profile)."""
import capstone, subprocess, re
f=open('build/interp.sfc','rb').read(); base=0x10000
MD=capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
def w(o): return (f[o]<<8)|f[o+1]
def l(o): return (f[o]<<24)|(f[o+1]<<16)|(f[o+2]<<8)|f[o+3]
def s16(v): return v-0x10000 if v&0x8000 else v
pcs=set(int(x,16) for x in open('/tmp/gf260_pcs.txt').read().split())
it=open('src/interp.pasm').read()
deployed=set(int(x,16) for x in re.findall(r'cmp #\$([0-9A-Fa-f]{4})', it))  # jah2 chain
deployed |= {0x25110}  # bank!=0 path
def fn_end(e):
    a=e
    while a<e+0x900:
        x=next(MD.disasm(f[base+a:base+a+8],a),None)
        if not x: a+=2; continue
        if x.mnemonic=='rts': return a+2
        a=x.address+x.size
    return a
cov=[(e,fn_end(e)) for e in deployed]
def is_cov(pc): return any(e<=pc<end for e,end in cov)
entries=set(l(base+0x4100+i*4)&0xFFFFFF for i in range(16))
for bank in range(len(f)//0x10000):
    b=bank*0x10000
    for o in range(b,b+0x10000-6,2):
        op=w(o)
        if op==0x4EB9:
            t=l(o+2)
            if (t>>16)==0 and (t&0xFFFF)<0xF000: entries.add(t)
        elif bank==1 and op==0x4EB8: entries.add(w(o+2))
        elif bank==1 and op==0x6100: entries.add((o-0x10000)+2+s16(w(o+2)))
cand=[]
for e in entries:
    if e<0x400 or e>=0x10000 or is_cov(e): continue
    end=fn_end(e); heat=sum(1 for pc in pcs if e<=pc<end)
    if heat>0: cand.append((e,heat,end))
cand.sort(key=lambda x:-x[1])
for e,heat,end in cand[:60]:
    out=subprocess.run(['python3','tools/transpile.py','%06X'%e,'--bank1','--video'],capture_output=True,text=True,timeout=40).stdout
    leaf='jml.l inext' in out and 'UNIMPLEMENTED' not in out and 'CALL-BRIDGE' not in out
    nu=out.count('UNIMPLEMENTED'); nc=out.count('CALL-BRIDGE')
    cls='LEAF-CLEAN' if leaf else ('NONLEAF' if nc else ('FEAT(%d)'%nu if nu else 'FAIL'))
    ops=''
    if nu: ops=' | '+'; '.join(sorted(set(re.findall(r'UNIMPLEMENTED: (\S+)', out))))
    print("%06X heat=%-3d %s%s"%(e,heat,cls,ops))
