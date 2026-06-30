#!/usr/bin/env python3
# Companion to yield_diff.py: simulate $0532-$0550 (CORRECT) and entry_swo (MY ASM, literally as
# written) on the captured S0 work RAM, diff the two -> any divergence IS the switch-out bug. No MAME
# sync-noise (unlike the recurring-$074C tap). Run yield_diff.py first to produce s0.bin + s0_regs.txt.
import ast
OUT='/tmp/supermn-scratch/yield'; WBASE=0xF00000
s0=bytearray(open(OUT+'/s0.bin','rb').read())
regs={k:int(v,16) for k,v in ast.literal_eval(open(OUT+'/s0_regs.txt').read()).items()}
a5=regs['A5']&0xFFFFFFFF; a7=regs['SP']&0xFFFFFFFF
REGORD=['D0','D1','D2','D3','D4','D5','D6','D7','A0','A1','A2','A3','A4','A5','A6']
def mk():
    W=bytearray(s0)
    def w32(a,v):o=a-WBASE;W[o]=(v>>24)&0xFF;W[o+1]=(v>>16)&0xFF;W[o+2]=(v>>8)&0xFF;W[o+3]=v&0xFF
    def w16(a,v):o=a-WBASE;W[o]=(v>>8)&0xFF;W[o+1]=v&0xFF
    def r32(a):o=a-WBASE;return (W[o]<<24)|(W[o+1]<<16)|(W[o+2]<<8)|W[o+3]
    def r16(a):o=a-WBASE;return (W[o]<<8)|W[o+1]
    return W,w32,w16,r32,r16
def sim_correct():
    W,w32,w16,r32,r16=mk()
    na7=(a7-60)&0xFFFFFFFF                       # 68K movem -(An): full 32-bit An
    for i,r in enumerate(REGORD): w32(na7+i*4, regs[r]&0xFFFFFFFF)
    a6=r32(a5+6); w32(a6&0xFFFFFFFF, na7)
    a4=r32(a5+0x4a); dv=(r16(a4&0xFFFFFFFF)&0xCFFF)|0xC000; w16(a4&0xFFFFFFFF, dv)
    return W
def sim_myasm():
    W,w32,w16,r32,r16=mk()
    na7=(a7&0xFFFF0000)|((a7-60)&0xFFFF)         # entry_swo: lo16-only sbc on $3C ($3E unchanged)
    wp=na7&0xFFFF                                # write ptr = $400000 + (na7 lo16), X is 16-bit
    for i,r in enumerate(REGORD):
        a=WBASE|((wp+i*4)&0xFFFF)                # my asm: $400000,x, x wraps at 64K
        w32(a, regs[r]&0xFFFFFFFF)
    a6=r32((a5+6)&0xFFFFFFFF); w32((a6)&0xFFFFFFFF, na7)   # write na7 ($3C/$3E) to (a6)
    a4=r32((a5+0x4a)&0xFFFFFFFF); dv=(r16(a4&0xFFFFFFFF)&0xCFFF)|0xC000; w16(a4&0xFFFFFFFF, dv)
    return W
C=sim_correct(); M=sim_myasm()
d=[(WBASE+i,C[i],M[i]) for i in range(len(C)) if C[i]!=M[i]]
print(">>> sim: a5=%06X a7=%06X a7-60=%06X  *(a5+6)=%06X *(a5+$4a)=%06X"%(a5&0xFFFFFF,a7&0xFFFFFF,(a7-60)&0xFFFFFF,
      ((s0[6]<<24)|(s0[7]<<16)|(s0[8]<<8)|s0[9])&0xFFFFFF,((s0[0x4a]<<24)|(s0[0x4b]<<16)|(s0[0x4c]<<8)|s0[0x4d])&0xFFFFFF))
print(">>> CORRECT vs MY-ASM: %d divergent bytes"%len(d))
for a,c,m in d[:40]: print("    $%06X: correct=%02X myasm=%02X"%(a,c,m))
if not d: print("    >>> MY ASM MATCHES the correct switch-out on this input (body is bit-exact).")
