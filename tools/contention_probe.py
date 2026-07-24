#!/usr/bin/env python3
# contention_probe.py — the 5A22<->SA-1 bus-contention probe (the decisive unattributed-1.08M
# measurement, docs/history/performance/PROFILE_CAMPAIGN.md
# "ISR verification round" suspect (a)).
#
# Mechanism (Nexen Sa1Cpu::ProcessCpuCycle): the SA-1 pays wait cycles whenever its access's
# memory TYPE equals the 5A22's latched Bus-A type (SnesMemoryManager::_memTypeBusA):
#   BW-RAM access: 2 cyc -> 4 on conflict; ROM/IRAM access: 1 cyc -> 2 (IRAM+FastROM -> 3).
# The 5A22 video supervisor (cv_loop, $E9:8835) BUSY-POLLS at 100%% duty: ROM code fetches +
# IRAM $3300/$3302 polls + BW-RAM $410000/02 (joy5a22) every iteration -> a constant tax on
# every SA-1 ROM/IRAM/BW-RAM cycle. This probe frees-run the NAT state and measures SA-1
# cyc/tick under graded 5A22 stubs (in-session snesPrgRom pokes, no rebuild):
#   A  live baseline
#   B  jsr joy5a22 nop'd            (kills the per-spin BW-RAM mailbox hammer)
#   C  B + jsr vid_frame nop'd      (pure spin: IRAM poll + ROM fetch only)
#   D  5A22 parked in a WRAM bra-$  (zero bus presence: WRAM fetches never conflict.
#      NOT stp: _memTypeBusA is a LATCH -> a stopped 5A22 whose last fetch was ROM would
#      fake permanent PrgRom contention)
#   A2 all pokes restored + 5A22 un-parked (drift check)
# SA-1 side is safe under all stubs: VID_FRAME is fire-and-forget (inc $3300, no ack wait).
#
# Usage: contention_probe.py [ticks_per_cond=10]   env: NAT, PORT
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession

K=int(sys.argv[1]) if len(sys.argv)>1 else 10
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
NAT=os.environ.get('NAT','/tmp/b0_native.mss')
ROM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc')

# cv_loop poke sites (file offsets into the $E9 video bank @ $298000; verified against
# build/interp.sfc bytes: c230 204a88 ad0033 cd0233 f0f3 8d0233 20ae80 80eb)
F_CVLOOP =0x298835   # C2 30 20 4A 88 ...  (rep #$30 ; jsr joy5a22)
F_JOY    =0x298837   # 20 4A 88            jsr joy5a22
F_VIDFRM =0x298845   # 20 AE 80            jsr vid_frame
PARK     =0x7EF800   # WRAM park: 80 FE (bra $)  -- 5A22 fetches = SnesWorkRam, no conflict
ORIG={F_CVLOOP:'c230204a88', F_JOY:'204a88', F_VIDFRM:'20ae80'}

print("contention probe: NAT=%s K=%d ticks/cond"%(NAT,K),flush=True)
with McpSession(rom=ROM,mesen=NEXEN,port=int(os.environ.get('PORT','7551')),boot_wait=6.0,socket_timeout=300.0) as m:
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def tickctr(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    def rom_poke(fo,hx):
        m.write_memory('snesPrgRom',fo,hx)
        rb=m.read_memory('snesPrgRom',fo,len(hx)//2).hex()
        assert rb==hx, "poke @%06X: wrote %s read %s"%(fo,hx,rb)
    def snes_pc():
        st=m.get_cpu_state('Snes'); return (st.get('k',st.get('K',0)), st.get('pc',st.get('PC',0)))

    m.load_state(NAT)
    # release the NAT freeze -> production free-run with escapes armed (the smoke sequence)
    w16(0x0700,0); w16(0x0702,0); w16(0x0710,0); w16(0x0712,0)
    w16(0x072E,1); w16(0x0704,1)
    w16(0x071A,1); w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    m.run_frames(60)                                    # settle

    def measure(tag):
        t0=tickctr(); c0=cyc(); fr=0
        # skip a partial tick: run to the next tick edge first
        while tickctr()==t0 and fr<600: m.run_frames(2); fr+=2
        t0=tickctr(); c0=cyc(); fr=0
        while tickctr()<t0+K and fr<3000: m.run_frames(2); fr+=2
        t1=tickctr(); c1=cyc()
        n=t1-t0
        if n<=0: print("  %s: NO TICKS in window (fr=%d) -- SA-1 stalled?"%(tag,fr),flush=True); return None
        cpt=(c1-c0)//n
        print("  %s: %d ticks, %d cyc -> %d cyc/tick  (~%.1f frames/tick)"%(tag,n,c1-c0,cpt,fr/n),flush=True)
        return cpt

    res={}
    res['A']=measure('A  live         ')

    rom_poke(F_JOY,'eaeaea')
    m.run_frames(10)
    res['B']=measure('B  -joy         ')

    rom_poke(F_VIDFRM,'eaeaea')
    m.run_frames(10)
    res['C']=measure('C  -joy -vidfrm ')

    m.write_memory('snesMemory',PARK,'80fe')            # WRAM bra-$
    rom_poke(F_CVLOOP,'5c00f87e'+'ea')                  # jml $7EF800 (+nop pad over the 5-byte site)
    m.run_frames(10)
    k,pc=snes_pc()
    print("  [D] 5A22 at $%02X:%04X (expect $7E:F800..F801)"%(k,pc),flush=True)
    res['D']=measure('D  5A22 parked  ')

    # restore: un-poke ROM, then re-aim the park jml back at cv_loop
    for fo,hx in ORIG.items(): rom_poke(fo,hx)
    m.write_memory('snesMemory',PARK,'5c3588e9')        # jml $E98835 -> resume cv_loop
    m.run_frames(10)
    res['A2']=measure('A2 restored     ')

    a,d=res.get('A'),res.get('D')
    if a and d:
        print(">>> contention share of the live tick: A-D = %d cyc/tick = %.1f%% of A"%(a-d,100*(a-d)/a),flush=True)
        if res.get('B'): print(">>>   joy BW-RAM hammer (A-B): %d (%.1f%%)"%(a-res['B'],100*(a-res['B'])/a),flush=True)
        if res.get('B') and res.get('C'): print(">>>   vid_frame render  (B-C): %d (%.1f%%)"%(res['B']-res['C'],100*(res['B']-res['C'])/a),flush=True)
        if res.get('C'): print(">>>   spin fetch/IRAM   (C-D): %d (%.1f%%)"%(res['C']-d,100*(res['C']-d)/a),flush=True)
        print(">>> quiet-5A22 floor D = %d cyc/tick vs the 358K/tick 30fps budget = %.2fx"%(d,d/358000.0),flush=True)
    if a and res.get('A2'): print(">>> drift check: A=%d A2=%d (%.1f%%)"%(a,res['A2'],100*abs(a-res['A2'])/a),flush=True)
