#!/usr/bin/env python3
# measure_render_wram.py — pt.21 validation: does relocating the 5A22 render to WRAM ($7F) reduce
# SA-1 bus contention? Toggles the $8004 VF_TICK wrapper between ROM-render ($E9, 4c1889ea) and
# WRAM-render ($7F, 5c18897f) on the SAME state and compares Sa1 cyc/frame.
#
# CRITICAL — measure on a FRESH boot, NOT the NAT: dump_b0_native's jh_spin transplant does
# setcpu(cpu['snes']) and the 5A22 ends up stranded at $00:D161 (interp ispin/test_idle ROM
# region), OUT of its $7E:F000 supervisor poll loop -> the render NEVER fires under NAT/injected
# harnesses (FRAME_ACK frozen). set_cpu_state('Snes') does NOT let you force it back. A fresh boot
# (cpu5a22_boot) puts the 5A22 in the supervisor naturally. We then inject the combat shadow, force
# the game "alive" so vid_frame takes the HEAVY path (vid_bg/vid_obj/decode_tile), and drive
# FRAME_REQ every frame so the render fires continuously (~100% duty = pt.20's combat condition).
#
# RESULT (2026-07-04, this ROM): render provably relocates (ROM->5A22 bank $E9, WRAM->bank $7F;
# vid_frame$7F/vid_bg$7F exec-hooks fire). Sa1 cyc/frame ROM 92464 vs WRAM 89341 = 3123 (3.4%,
# ~68K/combat-tick). Plan expected ~27% (550K). Render is DMA/$7E-write-heavy -> its code-fetch
# (the only WRAM-recoverable share) is a MINOR conflict source. Lever largely mis-premised.
#
# Usage: measure_render_wram.py   env: PORT   (run via a 2-level python wrapper to dodge exit-144)
import sys, os, collections
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ROM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc')
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
WRAMA='/tmp/supermn-scratch/ce4trip64/wramA.bin'
F_WRAP=0x298004     # snesPrgRom file offset of $E9:8004 (VF_TICK wrapper)
with McpSession(rom=ROM,mesen=NEXEN,port=int(os.environ.get('PORT','7650')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def sacyc(): return m.get_cpu_state('Sa1').get('cycleCount',0)
    m.run_frames(300)                                   # FRESH boot -> 5A22 in the $7E:F000 supervisor
    wramA=open(WRAMA,'rb').read()
    for o in range(0,len(wramA),0x2000): m.write_memory('snesMemory',0x400000+o, wramA[o:o+0x2000].hex())
    m.write_memory('snesPrgRom',F_WRAP,'5c18897f')
    for nm,a in [('vid_frame$7F',0x7F80AE),('vid_bg$7F',0x7F846C),('vid_obj$7F',0x7F817D)]:
        h=m.add_exec_hook(a,cpu_type='Snes')
        w16(0x400002,0x0300,'snesMemory'); w16(0x3300,(r16(0x3300)+4)&0xFFFF)
        r=m.run_until(max_frames=8,hook_handle=h); m.remove_hook(h)
        print("  heavy-path %-14s %s"%(nm, r.get('reason')), flush=True)
    def measure(patch,label,N=150,bump=4):
        m.write_memory('snesPrgRom',F_WRAP,patch)
        for _ in range(10):
            w16(0x400002,0x0300,'snesMemory'); m.write_memory('snesMemory',0x7EA000,'ff'*512)
            w16(0x3300,(r16(0x3300)+bump)&0xFFFF); m.run_frames(1)
        kb=collections.Counter(); c0=sacyc(); ack0=r16(0x3302)
        for _ in range(N):
            w16(0x400002,0x0300,'snesMemory')                       # game "alive" -> heavy render
            m.write_memory('snesMemory',0x7EA000,'ff'*512)          # invalidate BG cache -> max decode
            w16(0x3300,(r16(0x3300)+bump)&0xFFFF); m.run_frames(1)  # keep REQ ahead -> render/frame
            kb[m.get_cpu_state('Snes').get('k',0)]+=1
        cpf=(sacyc()-c0)//N
        print("[%s] Sa1 cyc/frame=%d | ACK moved %d | 5A22 Kbank=%s"%(label,cpf,r16(0x3302)-ack0,dict(kb)),flush=True)
        return cpf
    rom=(measure('4c1889ea','ROM  #1')+measure('4c1889ea','ROM  #2'))//2
    wram=(measure('5c18897f','WRAM #1')+measure('5c18897f','WRAM #2'))//2
    print(">>> ROM render %d vs WRAM render %d cyc/frame | delta %d (%.1f%%)  [WRAM<ROM => win]"%(
        rom,wram,rom-wram,100*(rom-wram)/rom if rom else 0),flush=True)
