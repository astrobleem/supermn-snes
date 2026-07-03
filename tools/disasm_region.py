#!/usr/bin/env python3
# disasm_region.py — annotated 68K listing of a ROM region, anchored by executed-PC streams.
# Linear capstone sweep re-anchored at known instruction starts (executed PCs from STREAMDUMP
# files), so embedded data can't desync the listing. Each line carries per-stream execution
# counts + structural flags (DYN dynamic dispatch, YIELD trap#5, flow breaks).
# Usage: disasm_region.py <lo_hex24> <hi_hex24> [stream1.txt stream2.txt ...]
#   stream files: one hex PC per line (lockstep_trap.py STREAMDUMP output); label = basename.
import sys, collections, os, re
import capstone as cs
LO=int(sys.argv[1],16); HI=int(sys.argv[2],16)
ROM=open(os.path.join(os.path.dirname(__file__),'..','build','interp.sfc'),'rb').read()
MD=cs.Cs(cs.CS_ARCH_M68K, cs.CS_MODE_BIG_ENDIAN)
def rom_off(a): return 0x10000+(a&0x3FFFFF)
streams={}
for f in sys.argv[3:]:
    lbl=re.sub(r'^stream_|\.txt$','',os.path.basename(f))
    pcs=[int(l,16) for l in open(f) if l.strip()]
    streams[lbl]=pcs
counts={lbl:collections.Counter(p for p in pcs if LO<=p<=HI) for lbl,pcs in streams.items()}
anchors=sorted(set(p for c in counts.values() for p in c))   # known instruction starts
# jump targets from within the region also anchor (branch targets are instruction starts)
def disasm_at(a):
    try: return next(MD.disasm(ROM[rom_off(a):rom_off(a)+10], a))
    except StopIteration: return None
pc=LO; lines=[]; ai=0
while pc<=HI:
    while ai<len(anchors) and anchors[ai]<pc: ai+=1
    nxt=anchors[ai] if ai<len(anchors) else None
    ins=disasm_at(pc)
    if ins is None:
        # undecodable word: emit dc.w, advance 2 (re-anchor will catch us)
        w=(ROM[rom_off(pc)]<<8)|ROM[rom_off(pc)+1]
        lines.append((pc,2,'dc.w $%04x'%w,'')); pc+=2; continue
    if nxt is not None and pc<nxt<pc+ins.size:
        # executed PC lands inside this "instruction" -> data mislabeled; dump words to anchor
        w=(ROM[rom_off(pc)]<<8)|ROM[rom_off(pc)+1]
        lines.append((pc,2,'dc.w $%04x'%w,'DATA?')); pc+=2; continue
    d='%s %s'%(ins.mnemonic,ins.op_str)
    flag=''
    m=ins.mnemonic
    if m.startswith(('jsr','jmp')) and '(a' in ins.op_str and 'pc' not in ins.op_str: flag='DYN'
    if m.startswith('trap'): flag='YIELD'
    if m in ('rts','rte','rtr') or m.startswith(('bra','jmp')): flag=(flag+' flow').strip()
    lines.append((pc,ins.size,d,flag)); pc+=ins.size
lbls=sorted(streams)
out=[]
for pc,sz,d,flag in lines:
    cnt=' '.join('%s=%-3d'%(l[:4],counts[l].get(pc,0)) for l in lbls)
    star='*' if any(counts[l].get(pc,0) for l in lbls) else ' '
    out.append('$%06X %s %s  %-44s %s'%(pc,star,cnt,d,flag))
print('\n'.join(out))
print('\n; region $%06X-$%06X: %d lines, %d executed'%(LO,HI,len(lines),
      sum(1 for pc,_,_,_ in lines if any(counts[l].get(pc,0) for l in lbls))), file=sys.stderr)
