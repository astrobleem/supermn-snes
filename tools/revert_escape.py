#!/usr/bin/env python3
"""Revert a deployed escape (escbank jmptab+body, interp jah2 cmp+dispatch). Usage: revert_escape.py <hex>."""
import sys, re
addr=int(sys.argv[1],16); lo=addr&0xFFFF; lab='entry_%x'%(addr&0xFFFFFF); el='jah2_e%x'%(addr&0xFFFFFF)
# escbank
esc=open('src/escbank.pasm').read()
esc=re.sub(r'\n    jmp %s\s+; slot \d+[^\n]*'%lab, '', esc)         # jmptab line
# body: from the transpiled-comment (or label) to next transpiled-comment / EOF
m=re.search(r'(\n; --- transpiled from \$0*%X\b.*?|\n%s:)'%(addr&0xFFFFFF,lab), esc, re.S)
if m:
    start=m.start()
    nxt=esc.find('\n; --- transpiled from', start+5)
    esc=esc[:start]+('\n'+esc[nxt+1:] if nxt!=-1 else '\n')
open('src/escbank.pasm','w').write(esc.rstrip()+'\n')
# interp
it=open('src/interp.pasm').read()
it=re.sub(r'\n    cmp #\$%04X\n    bne (jah2_n\d+)\n    jmp %s\n\1:'%(lo,el), '', it)  # cmp block
it=re.sub(r'\n%s:\n    plp\n    pla\n    lda \$54\n    sta \$40\n    jml \$[0-9A-F]+[^\n]*'%el, '', it)  # dispatch
open('src/interp.pasm','w').write(it)
print("reverted",lab)
