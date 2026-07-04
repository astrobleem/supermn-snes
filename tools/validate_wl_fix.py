#!/usr/bin/env python3
# validate_wl_fix.py — post-fix validation of the WRAM supervisor loop (video.pasm wl_setup):
# free-run the light NAT on the NEW ROM, confirm (1) the 5A22 migrates to $7E:F0xx, (2) live
# cyc/tick collapses to ~the old parked floor (~1.02M), (3) the residual vs a parked blob is
# small, (4) FRAME_ACK still tracks FRAME_REQ (render alive) + a screenshot.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
K=int(sys.argv[1]) if len(sys.argv)>1 else 10
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
NAT=os.environ.get('NAT','/tmp/b0_native.mss')
ROM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc')
with McpSession(rom=ROM,mesen=NEXEN,port=int(os.environ.get('PORT','7553')),boot_wait=6.0,socket_timeout=300.0) as m:
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def r16sa(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def tickctr(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    def measure(tag):
        t0=tickctr(); fr=0
        while tickctr()==t0 and fr<600: m.run_frames(2); fr+=2
        t0=tickctr(); c0=cyc(); fr=0
        while tickctr()<t0+K and fr<3000: m.run_frames(2); fr+=2
        t1=tickctr(); c1=cyc(); n=t1-t0
        if n<=0: print("  %s: NO TICKS"%tag,flush=True); return None
        print("  %s: %d ticks -> %d cyc/tick"%(tag,n,(c1-c0)//n),flush=True); return (c1-c0)//n
    m.load_state(NAT)
    w16(0x0700,0); w16(0x0702,0); w16(0x0710,0); w16(0x0712,0)
    w16(0x072E,1); w16(0x0704,1)
    w16(0x071A,1); w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    m.run_frames(60)
    st=m.get_cpu_state('Snes')
    print("5A22 at $%02X:%04X (expect $7E:F0xx)"%(st.get('k',0),st.get('pc',0)),flush=True)
    req,ack=r16sa(0x3300),r16sa(0x3302)
    live=measure('live (WRAM loop)')
    req2,ack2=r16sa(0x3300),r16sa(0x3302)
    print("FRAME req/ack: %d/%d -> %d/%d (render %s)"%(req,ack,req2,ack2,'ALIVE' if ack2>ack else 'DEAD'),flush=True)
    shot=m.take_screenshot(); print("screenshot:",shot,flush=True)
    m.write_memory('snesMemory',0x7EF000,'80fe')     # park the blob: bra $ at wl_poll
    m.run_frames(10)
    st=m.get_cpu_state('Snes')
    print("[parked] 5A22 at $%02X:%04X"%(st.get('k',0),st.get('pc',0)),flush=True)
    parked=measure('parked (residual)')
    m.write_memory('snesMemory',0x7EF000,'a280')     # restore ldx #$0080
    if live and parked:
        print(">>> residual 5A22 tax with the fix: %d cyc/tick (%.1f%%)"%(live-parked,100*(live-parked)/live),flush=True)
