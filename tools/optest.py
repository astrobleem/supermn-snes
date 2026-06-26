#!/usr/bin/env python3
"""
optest.py — single-instruction differential micro-test harness for the 68000
interpreter (src/interp.pasm), validated against MAME as the oracle.

For each test vector it sets 68K registers / CCR / a memory operand, executes
EXACTLY ONE opcode on both MAME and the interpreter, and diffs the resulting
registers, CCR (X,N,Z,V,C) and the touched memory word.

MAME side : launch MAME headless with a generated Lua autoboot script that
            redirects PC into work RAM, runs the op followed by `bra *`, masks
            IRQs (SR=$27xx), and reads the frozen post-op state. All vectors are
            batched into one MAME launch.
Interp side: drive build/interp.sfc via the Mesen Python client. The vector is
            written into the ROM mailbox at CPU $F400 (TESTFLAG + regs + flags +
            operand); reset_emulator() runs the test-mode reset stub which loads
            the mailbox into the (just-cleared) work RAM and single-steps one op
            via the $7E hook; then read back DP regs / flags / operand.

Scratch (68K addresses, shared logical space):
  MAME code   $F03000  (work RAM, executable)
  interp code $07C000  (ROM image; interp fetches $C10000+PC; file off $8C000)
  operand     $F03800  (work RAM, within MAME's 16KB $F00000-$F03FFF)
  stack A7    $F03F00

Limitation: PC-relative source operands ((d16,PC)/(d8,PC,Xn)) are NOT covered
(the two engines run the op at different PCs); validate those in-trajectory.

MAME A7/USP readback is unreliable: do not assert A7; for stack ops set A7 going
in and assert on the memory written.
"""
import os, sys, subprocess, tempfile, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAME = "/snap/bin/mame"
ROMPATH = os.path.join(REPO, "tools/mame-trace/roms")
NVRAM = os.path.join(REPO, ".mame_mcp/nvram")
CFG = os.path.join(REPO, ".mame_mcp/cfg")
INTERP_SFC = os.path.join(REPO, "build/interp.sfc")
MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"

# scratch
MAME_CODE = 0xF03000
INTERP_CODE_68K = 0x07C000           # 68K addr; ROM file offset = 0x10000+addr
INTERP_CODE_ROMOFF = 0x10000 + INTERP_CODE_68K
OPND = 0xF03800
OPND_INTERP_WRAM = 0x10000 + (OPND & 0xFFFF)   # snesWorkRam offset for $7F:3800
STACK = 0xF03F00
MBOX = 0x7600                         # ROM file offset of the TESTFLAG. The interp runs on the SA-1,
                                      # which sees bank-$00 $8000-$FFFF LoROM-style (file = CPU-$8000),
                                      # so CPU $00:F600 -> file $7600. (The old $F400 only "worked"
                                      # because $00:F400 -> file $7400 was escape code, permanently
                                      # nonzero => test mode was always-on by accident; relocating the
                                      # flag to a genuinely-zero byte exposed that.)

REGNAMES = ["D0","D1","D2","D3","D4","D5","D6","D7",
            "A0","A1","A2","A3","A4","A5","A6","A7"]

def ccr_bits(x=0,n=0,z=0,v=0,c=0):
    return (x<<4)|(n<<3)|(z<<2)|(v<<1)|c

# ---------------------------------------------------------------------------
# Vector: dict with
#   regs : {name: u32}   (missing regs default 0; A7 defaults to STACK)
#   ccr  : int 0..31 (XNZVC)
#   opnd : bytes (<=16) written big-endian at $F03800 (default zeros)
class Vec:
    def __init__(self, regs=None, ccr=0, opnd=b""):
        self.regs = dict(regs or {})
        self.regs.setdefault("A7", STACK)
        self.ccr = ccr
        self.opnd = bytes(opnd).ljust(16, b"\0")[:16]

# ---------------------------------------------------------------------------
# MAME oracle
def mame_run(opwords, oplen, vecs):
    """opwords: list of u16 (the instruction + extension words).
       oplen: bytes consumed by the instruction.
       returns list of dicts {reg:u32..., 'CCR':int, 'OPND':bytes}"""
    # build Lua vector table
    mame_name = lambda n: "SP" if n=="A7" else n   # MAME exposes A7 as SP
    lua_vecs = []
    for v in vecs:
        regset = " ".join(f'st["{mame_name(n)}"].value={v.regs.get(n,0)&0xFFFFFFFF}'
                          for n in REGNAMES)
        opnd_writes = " ".join(
            f"prog:write_u8(0x{OPND+i:X},0x{v.opnd[i]:02X})" for i in range(16))
        lua_vecs.append(f"{{sr=0x{0x2700|v.ccr:04X}, regs=function() {regset} end, "
                        f"opnd=function() {opnd_writes} end}}")
    op_writes = " ".join(
        f"prog:write_u16(0x{MAME_CODE+2*i:X},0x{w:04X})" for i,w in enumerate(opwords))
    brasel_addr = MAME_CODE + oplen
    vec_tbl = ",\n".join(lua_vecs)
    lua = f"""
KEEP={{}}
local cpu=manager.machine.devices[":maincpu"]
local prog=cpu.spaces["program"]
local st=cpu.state
local out=io.open("optest_mame.txt","w")
local vecs={{
{vec_tbl}
}}
local i=1
local sub=0
local fc=0
KEEP[1]=emu.register_frame_done(function()
  fc=fc+1
  if fc<60 then return end
  if i>#vecs then out:close(); io.stderr:write("DONE\\n"); os.exit(0) end
  sub=sub+1
  if sub==1 then
    vecs[i].regs()
    st["SR"].value=vecs[i].sr
    for a=0,0x80,2 do prog:write_u16(0x{MAME_CODE-0x40:X}+a,0x60FE) end  -- bra* fill (branch targets spin)
    {op_writes}
    prog:write_u16(0x{brasel_addr:X},0x60FE)   -- bra * (spin)
    vecs[i].opnd()
    st["PC"].value=0x{MAME_CODE:X}
  elseif sub==4 then
    local s=string.format("VEC %d", i)
    local rd={{ {{"D0","D0"}},{{"D1","D1"}},{{"D2","D2"}},{{"D3","D3"}},{{"D4","D4"}},{{"D5","D5"}},{{"D6","D6"}},{{"D7","D7"}},{{"A0","A0"}},{{"A1","A1"}},{{"A2","A2"}},{{"A3","A3"}},{{"A4","A4"}},{{"A5","A5"}},{{"A6","A6"}},{{"A7","SP"}} }}
    for _,p in ipairs(rd) do
      s=s..string.format(" %s=%08X", p[1], st[p[2]].value)
    end
    s=s..string.format(" CCR=%02X", st["SR"].value & 0x1F)
    s=s..string.format(" PC=%08X", st["PC"].value)
    s=s.." OPND="
    for k=0,15 do s=s..string.format("%02X", prog:read_u8(0x{OPND:X}+k)) end
    out:write(s.."\\n"); out:flush()
    i=i+1; sub=0
  end
end)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, dir=REPO) as f:
        f.write(lua); script=f.name
    outpath = os.path.join(REPO, "optest_mame.txt")
    if os.path.exists(outpath): os.remove(outpath)
    nframes = 60 + 5*len(vecs) + 20
    secs = max(8, nframes//60 + 4)
    cmd=[MAME,"superman","-rompath",ROMPATH,"-video","none","-sound","none",
         "-nothrottle","-skip_gameinfo","-seconds_to_run",str(secs),
         "-autoboot_script",script,"-autoboot_delay","0",
         "-nvram_directory",NVRAM,"-cfg_directory",CFG]
    env=os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER","dummy"); env.setdefault("SDL_AUDIODRIVER","dummy")
    subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=secs+30, env=env)
    os.remove(script)
    res={}
    if os.path.exists(outpath):
        for line in open(outpath):
            m=re.match(r"VEC (\d+) (.*)", line.strip())
            if not m: continue
            idx=int(m.group(1))-1
            d={}
            for tok in m.group(2).split():
                k,_,vv=tok.partition("=")
                if k=="OPND": d["OPND"]=bytes.fromhex(vv)
                elif k=="CCR": d["CCR"]=int(vv,16)
                else: d[k]=int(vv,16)
            res[idx]=d
    return [res.get(i) for i in range(len(vecs))]

# ---------------------------------------------------------------------------
# Interpreter (Mesen)
def _regblk(v):
    """64-byte DP image $00-$3F: D0lo,D0hi,..,A7lo,A7hi (each 16-bit little-endian)."""
    b=bytearray(0x40)
    for i,n in enumerate(REGNAMES):
        val=v.regs.get(n,0)&0xFFFFFFFF
        off=i*4
        b[off]=val&0xFF; b[off+1]=(val>>8)&0xFF
        b[off+2]=(val>>16)&0xFF; b[off+3]=(val>>24)&0xFF
    return bytes(b)

def _make_test_sfc(opwords):
    """Copy build/interp.sfc to a temp .sfc with TESTFLAG=1 baked in and the op
       baked into the ROM image at file $8C000 (= 68K $7C000)."""
    data=bytearray(open(INTERP_SFC,"rb").read())
    data[MBOX]=0x01; data[MBOX+1]=0x00            # TESTFLAG word = 1
    opbytes=b"".join(int(w).to_bytes(2,"big") for w in opwords)
    data[INTERP_CODE_ROMOFF:INTERP_CODE_ROMOFF+len(opbytes)]=opbytes
    f=tempfile.NamedTemporaryFile(suffix=".sfc", delete=False, dir="/tmp")
    f.write(data); f.close()
    return f.name

def interp_run(opwords, oplen, vecs):
    sys.path.insert(0,"/home/chad/Mesen2/python")
    os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
    os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
    from mesen_mcp import McpSession
    sfc=_make_test_sfc(opwords)
    out=[]
    try:
        with McpSession(rom=sfc, mesen=MESEN, port=7339, boot_wait=3.0) as m:
            for v in vecs:
                # poke vector state directly into the (running, idle) interpreter
                m.write_memory("snesWorkRam", 0x00, _regblk(v).hex())
                pc=INTERP_CODE_68K
                m.write_memory("snesWorkRam", 0x40,
                               bytes([pc&0xFF,(pc>>8)&0xFF,(pc>>16)&0xFF,(pc>>24)&0xFF]).hex())
                Z=(v.ccr>>2)&1; C=v.ccr&1; N=(v.ccr>>3)&1; V=(v.ccr>>1)&1; X=(v.ccr>>4)&1
                for addr,val in ((0x60,Z),(0x6E,C),(0x70,N),(0x72,V),(0xA2,X)):
                    m.write_memory("snesWorkRam", addr, bytes([val,0]).hex())
                m.write_memory("snesWorkRam", 0x7C, bytes([0x07,0]).hex())   # SR mask
                m.write_memory("snesWorkRam", OPND_INTERP_WRAM, v.opnd.hex())
                m.write_memory("snesWorkRam", 0xA0, bytes([0x01,0]).hex())   # go-flag
                m.run_frames(1)
                regblk=m.read_memory("snesWorkRam", 0x00, 0x40)
                flagblk=m.read_memory("snesWorkRam", 0x60, 0x20)   # $60..$7F
                xbyte=m.read_memory("snesWorkRam", 0xA2, 1)        # X flag
                opnd=m.read_memory("snesWorkRam", OPND_INTERP_WRAM, 16)
                stopf=m.read_memory("snesWorkRam", 0x4E, 2)
                pcblk=m.read_memory("snesWorkRam", 0x40, 4)
                uspblk=m.read_memory("snesWorkRam", 0xA4, 4)       # USP slot ($A4/$A6)
                d={}
                d["USP"]=uspblk[0]|(uspblk[1]<<8)|(uspblk[2]<<16)|(uspblk[3]<<24)
                d["PC"]=pcblk[0]|(pcblk[1]<<8)|(pcblk[2]<<16)|(pcblk[3]<<24)
                for i,n in enumerate(REGNAMES):
                    off=i*4
                    lo=regblk[off]|(regblk[off+1]<<8)
                    hi=regblk[off+2]|(regblk[off+3]<<8)
                    d[n]=lo|(hi<<16)
                Z=1 if flagblk[0x60-0x60] else 0
                C=1 if flagblk[0x6E-0x60] else 0
                N=1 if flagblk[0x70-0x60] else 0
                V=1 if flagblk[0x72-0x60] else 0
                X=1 if xbyte[0] else 0
                d["CCR"]=ccr_bits(X,N,Z,V,C)
                d["OPND"]=bytes(opnd)
                d["_stopped"]=(stopf[0]|(stopf[1]<<8))
                out.append(d)
    finally:
        os.remove(sfc)
    return out

# ---------------------------------------------------------------------------
def compare(mame, interp, check_regs, check_ccr=True, check_opnd=False, ccr_mask=0x1F):
    """returns (passed, list_of_failure_strings)"""
    fails=[]
    for i,(mr,ir) in enumerate(zip(mame,interp)):
        if mr is None:
            fails.append(f"vec{i}: MAME produced no result"); continue
        if ir.get("_stopped")!=1:
            fails.append(f"vec{i}: interp did not single-step (stop={ir.get('_stopped'):#06x})")
            continue
        for n in check_regs:
            if n=="PC":
                # PC bases differ between emulators; compare offset from each base.
                # MAME exposes the 68000 prefetch PC (one word ahead) while spinning
                # on the bra* landing pad, so subtract 2 to get the true next-PC.
                mo=(mr["PC"]-MAME_CODE-2)&0xFFFFFFFF
                io=(ir["PC"]-INTERP_CODE_68K)&0xFFFFFFFF
                if mo!=io:
                    fails.append(f"vec{i}: PC off mame=+{mo:X} interp=+{io:X}")
                continue
            if mr[n]!=ir[n]:
                fails.append(f"vec{i}: {n} mame={mr[n]:08X} interp={ir[n]:08X}")
        if check_ccr:
            if (mr["CCR"]&ccr_mask)!=(ir["CCR"]&ccr_mask):
                fails.append(f"vec{i}: CCR mame={mr['CCR']:02X} interp={ir['CCR']:02X} (mask {ccr_mask:02X})")
        if check_opnd and mr["OPND"]!=ir["OPND"]:
            fails.append(f"vec{i}: OPND mame={mr['OPND'].hex()} interp={ir['OPND'].hex()}")
    return (len(fails)==0, fails)

_FILTER=os.environ.get("OPTEST_FILTER")   # substring; when set, run only matching ops
def run_test(name, opwords, oplen, vecs, check_regs, check_ccr=True,
             check_opnd=False, ccr_mask=0x1F):
    if _FILTER and _FILTER.lower() not in name.lower():
        return True
    print(f"=== {name}  ({len(vecs)} vectors) ===")
    mame=mame_run(opwords, oplen, vecs)
    interp=interp_run(opwords, oplen, vecs)
    ok,fails=compare(mame,interp,check_regs,check_ccr,check_opnd,ccr_mask)
    if ok:
        print(f"  PASS  ({len(vecs)}/{len(vecs)})")
    else:
        print(f"  FAIL  ({len(vecs)-len(fails)} ok, {len(fails)} bad)")
        for f in fails[:20]: print("   ", f)
    return ok

# ---------------------------------------------------------------------------
if __name__=="__main__":
    r=[]
    # Harness sanity: CMPI.W #$0003,D0 (uses verified subflags_w).
    r.append(run_test("CMPI.W #3,D0", [0x0C40,0x0003], 4,
        [Vec({"D0":3}),Vec({"D0":5}),Vec({"D0":2}),Vec({"D0":0x8000}),Vec({"D0":0})],
        check_regs=["D0"], ccr_mask=0x0F))

    # Batch 1: CCR/SR immediates (no reg change; full XNZVC). Vary CCR-in.
    ccrs=[0x00,0x01,0x04,0x0A,0x1F,0x10,0x15]
    r.append(run_test("ORI #$0F,CCR",  [0x003C,0x000F], 4,
        [Vec(ccr=c) for c in ccrs], check_regs=[], ccr_mask=0x1F))
    r.append(run_test("ANDI #$F0,CCR", [0x023C,0x00F0], 4,
        [Vec(ccr=c) for c in ccrs], check_regs=[], ccr_mask=0x1F))
    r.append(run_test("EORI #$0F,CCR", [0x0A3C,0x000F], 4,
        [Vec(ccr=c) for c in ccrs], check_regs=[], ccr_mask=0x1F))
    r.append(run_test("EORI #$1F,SR",  [0x0A7C,0x001F], 4,
        [Vec(ccr=c) for c in ccrs], check_regs=[], ccr_mask=0x1F))
    # Batch 2: NOT <ea> — first EA-engine workout (read-modify-write, all sizes/modes).
    #   X must be preserved (set X=1 in to confirm).
    XIN = ccr_bits(x=1)
    # NOT.L Dn (register direct)
    r.append(run_test("NOT.L D0", [0x4680], 2,
        [Vec({"D0":0},ccr=XIN), Vec({"D0":0xFFFFFFFF},ccr=XIN),
         Vec({"D0":0x80000000},ccr=XIN), Vec({"D0":0x12345678}),
         Vec({"D0":0x00000001})],
        check_regs=["D0"], ccr_mask=0x1F))
    # NOT.W Dn (high word must be preserved)
    r.append(run_test("NOT.W D0", [0x4640], 2,
        [Vec({"D0":0xAAAA0000},ccr=XIN), Vec({"D0":0x1111FFFF}),
         Vec({"D0":0x22228000}), Vec({"D0":0x33337FFF})],
        check_regs=["D0"], ccr_mask=0x1F))
    # NOT.B Dn (only low byte changes)
    r.append(run_test("NOT.B D0", [0x4600], 2,
        [Vec({"D0":0xAAAAAA00},ccr=XIN), Vec({"D0":0x111111FF}),
         Vec({"D0":0x22222280}), Vec({"D0":0x3333337F})],
        check_regs=["D0"], ccr_mask=0x1F))
    # NOT.L (xxx).L  (memory operand at $F03800)
    def opL(v): return v.to_bytes(4,"big")
    r.append(run_test("NOT.L (xxx).L", [0x46B9,0x00F0,0x3800], 6,
        [Vec(opnd=opL(0x00000000),ccr=XIN), Vec(opnd=opL(0xFFFFFFFF)),
         Vec(opnd=opL(0x80000000)), Vec(opnd=opL(0x12345678))],
        check_regs=[], check_opnd=True, ccr_mask=0x1F))
    # NOT.W (xxx).L
    r.append(run_test("NOT.W (xxx).L", [0x4679,0x00F0,0x3800], 6,
        [Vec(opnd=(0x0000).to_bytes(2,"big")), Vec(opnd=(0xFFFF).to_bytes(2,"big")),
         Vec(opnd=(0x8000).to_bytes(2,"big")), Vec(opnd=(0x1234).to_bytes(2,"big"))],
        check_regs=[], check_opnd=True, ccr_mask=0x1F))
    # NOT.B (An)  (An -> $F03800)
    r.append(run_test("NOT.B (A0)", [0x4610], 2,
        [Vec({"A0":OPND},opnd=bytes([0x00])), Vec({"A0":OPND},opnd=bytes([0xFF])),
         Vec({"A0":OPND},opnd=bytes([0x80])), Vec({"A0":OPND},opnd=bytes([0x7F]))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    # NOT.L (A0)+  (address post-increment; A0 must advance by 4)
    r.append(run_test("NOT.L (A0)+", [0x4698], 2,
        [Vec({"A0":OPND},opnd=opL(0x12345678)), Vec({"A0":OPND},opnd=opL(0x00000000))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    # NOT.W -(A0)  (pre-decrement; operand sits at OPND, so A0 starts at OPND+2)
    r.append(run_test("NOT.W -(A0)", [0x4660], 2,
        [Vec({"A0":OPND+2},opnd=(0x1234).to_bytes(2,"big")),
         Vec({"A0":OPND+2},opnd=(0xFFFF).to_bytes(2,"big"))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    # NOT.L (d16,A0)  d16=0, A0 -> $F03800
    r.append(run_test("NOT.L (0,A0)", [0x46A8,0x0000], 4,
        [Vec({"A0":OPND},opnd=opL(0x0F0F0F0F)), Vec({"A0":OPND},opnd=opL(0xFFFFFFFF))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))

    # --- AND <ea>,Dn (dir0).  AND.L D1,D0 = $C081 ; AND.W D1,D0 = $C041 ; AND.B = $C001
    r.append(run_test("AND.L D1,D0", [0xC081], 2,
        [Vec({"D0":0xFFFFFFFF,"D1":0x12345678},ccr=XIN),
         Vec({"D0":0x0F0F0F0F,"D1":0xF0F0F0F0}),
         Vec({"D0":0x80000000,"D1":0xFFFFFFFF}),
         Vec({"D0":0xAAAAAAAA,"D1":0x55555555})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("AND.W D1,D0", [0xC041], 2,
        [Vec({"D0":0x1111FFFF,"D1":0x22220F0F}),
         Vec({"D0":0xAAAA8000,"D1":0xBBBBFFFF}),
         Vec({"D0":0xCCCC1234,"D1":0xDDDD0000})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("AND.B D1,D0", [0xC001], 2,
        [Vec({"D0":0x111111FF,"D1":0x2222220F}),
         Vec({"D0":0xAAAAAA80,"D1":0xBBBBBBFF})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # AND.W (xxx).L,D0 (dir0, memory source)  $C079
    r.append(run_test("AND.W (xxx).L,D0", [0xC079,0x00F0,0x3800], 6,
        [Vec({"D0":0x0000FFFF},opnd=(0x0F0F).to_bytes(2,"big")),
         Vec({"D0":0x00008000},opnd=(0xFFFF).to_bytes(2,"big"))],
        check_regs=["D0"], ccr_mask=0x1F))
    # --- AND Dn,<ea> (dir1).  AND.L D1,(A0) = $C190 ; AND.W D1,(xxx).L = $C179
    r.append(run_test("AND.L D1,(A0)", [0xC190], 2,
        [Vec({"A0":OPND,"D1":0x0F0F0F0F},opnd=opL(0xFFFFFFFF)),
         Vec({"A0":OPND,"D1":0x00000000},opnd=opL(0x12345678))],
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("AND.W D1,(xxx).L", [0xC179,0x00F0,0x3800], 6,
        [Vec({"D1":0x0000F0F0},opnd=(0xFFFF).to_bytes(2,"big")),
         Vec({"D1":0x00008000},opnd=(0x8000).to_bytes(2,"big"))],
        check_regs=["D1"], check_opnd=True, ccr_mask=0x1F))
    # --- EOR Dn,<ea>.  EOR.L D1,D0 = $B181 ; EOR.W D1,(A0) = $B150 ; EOR.B D1,D0=$B101
    r.append(run_test("EOR.L D1,D0", [0xB181], 2,
        [Vec({"D0":0xFFFFFFFF,"D1":0x12345678},ccr=XIN),
         Vec({"D0":0xAAAAAAAA,"D1":0xAAAAAAAA}),
         Vec({"D0":0x00000000,"D1":0x80000000})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("EOR.W D1,(A0)", [0xB150], 2,
        [Vec({"A0":OPND,"D1":0x0000FFFF},opnd=(0x1234).to_bytes(2,"big")),
         Vec({"A0":OPND,"D1":0x00008000},opnd=(0x0000).to_bytes(2,"big"))],
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("EOR.B D1,D0", [0xB101], 2,
        [Vec({"D0":0x111111FF,"D1":0x2222220F}),
         Vec({"D0":0xAAAAAA00,"D1":0xBBBBBB80})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # --- EORI #imm,<ea>.  EORI.L #imm,D0=$0A80 ; EORI.W #imm,(A0)=$0A50 ; EORI.B=$0A00
    r.append(run_test("EORI.L #imm,D0", [0x0A80,0x1234,0x5678], 6,
        [Vec({"D0":0xFFFFFFFF},ccr=XIN), Vec({"D0":0x12345678}),
         Vec({"D0":0x00000000})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("EORI.W #$8000,(A0)", [0x0A50,0x8000], 4,
        [Vec({"A0":OPND},opnd=(0x0000).to_bytes(2,"big")),
         Vec({"A0":OPND},opnd=(0x8000).to_bytes(2,"big"))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("EORI.B #$FF,D0", [0x0A00,0x00FF], 4,
        [Vec({"D0":0x000000AA}), Vec({"D0":0x000000FF})],
        check_regs=["D0"], ccr_mask=0x1F))

    # --- Batch 3: ADD/SUB/CMP (full XNZVC; ADD/SUB set X=C, CMP leaves X).
    # ADD.L D1,D0 (dir0) = $D081 — carry, signed overflow, zero, sign edges.
    addL=[Vec({"D0":0x00000001,"D1":0x00000001}),
          Vec({"D0":0xFFFFFFFF,"D1":0x00000001}),          # carry out, result 0 -> C,X,Z
          Vec({"D0":0x7FFFFFFF,"D1":0x00000001}),          # signed overflow
          Vec({"D0":0x80000000,"D1":0x80000000}),          # carry + overflow
          Vec({"D0":0x12345678,"D1":0xEDCBA988},ccr=XIN)]  # X-in must be overwritten by C
    r.append(run_test("ADD.L D1,D0", [0xD081], 2, addL, check_regs=["D0","D1"], ccr_mask=0x1F))
    # ADD.W D1,D0 = $D041 (high word preserved)
    r.append(run_test("ADD.W D1,D0", [0xD041], 2,
        [Vec({"D0":0xAAAA7FFF,"D1":0xBBBB0001}),           # word overflow, high kept
         Vec({"D0":0x1111FFFF,"D1":0x22220001}),           # word carry -> 0
         Vec({"D0":0x33330000,"D1":0x44440000})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # ADD.B D1,D0 = $D001
    r.append(run_test("ADD.B D1,D0", [0xD001], 2,
        [Vec({"D0":0x111111FF,"D1":0x22222201}),           # byte carry -> 0
         Vec({"D0":0x3333337F,"D1":0x44444401})],          # byte overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # ADD.L D1,(A0) dir1 = $D190
    r.append(run_test("ADD.L D1,(A0)", [0xD190], 2,
        [Vec({"A0":OPND,"D1":0x00000001},opnd=opL(0xFFFFFFFF)),
         Vec({"A0":OPND,"D1":0x7FFFFFFF},opnd=opL(0x00000001))],
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))
    # ADD.W (xxx).L,D0 dir0 memory source = $D079
    r.append(run_test("ADD.W (xxx).L,D0", [0xD079,0x00F0,0x3800], 6,
        [Vec({"D0":0x00007FFF},opnd=(0x0001).to_bytes(2,"big")),
         Vec({"D0":0x0000FFFF},opnd=(0x0001).to_bytes(2,"big"))],
        check_regs=["D0"], check_opnd=True, ccr_mask=0x1F))
    # SUB.L D1,D0 (dir0) = $9081  (Dn - ea)
    r.append(run_test("SUB.L D1,D0", [0x9081], 2,
        [Vec({"D0":0x00000005,"D1":0x00000003}),
         Vec({"D0":0x00000003,"D1":0x00000005}),           # borrow -> C,X
         Vec({"D0":0x00000005,"D1":0x00000005}),           # zero
         Vec({"D0":0x80000000,"D1":0x00000001}),           # signed overflow
         Vec({"D0":0x00000000,"D1":0x00000001},ccr=XIN)],  # 0-1 -> FFFFFFFF, C,X,N
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # SUB.W / SUB.B
    r.append(run_test("SUB.W D1,D0", [0x9041], 2,
        [Vec({"D0":0x11110000,"D1":0x22220001}),           # word borrow
         Vec({"D0":0x33338000,"D1":0x44440001})],          # word overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("SUB.B D1,D0", [0x9001], 2,
        [Vec({"D0":0x11111100,"D1":0x22222201}),           # byte borrow
         Vec({"D0":0x33333380,"D1":0x44444401})],          # byte overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # SUB.L D1,(A0) dir1 = $9190  (ea - Dn)
    r.append(run_test("SUB.L D1,(A0)", [0x9190], 2,
        [Vec({"A0":OPND,"D1":0x00000003},opnd=opL(0x00000005)),
         Vec({"A0":OPND,"D1":0x00000005},opnd=opL(0x00000003))],
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))
    # CMP.L D1,D0 = $B081  (D0 - D1, no writeback, X preserved)
    r.append(run_test("CMP.L D1,D0", [0xB081], 2,
        [Vec({"D0":0x00000005,"D1":0x00000003},ccr=XIN),   # X must survive
         Vec({"D0":0x00000003,"D1":0x00000005}),           # borrow
         Vec({"D0":0x00000005,"D1":0x00000005}),           # equal -> Z
         Vec({"D0":0x80000000,"D1":0x00000001})],          # overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("CMP.W D1,D0", [0xB041], 2,
        [Vec({"D0":0x11110005,"D1":0x22220005}),           # equal low word -> Z
         Vec({"D0":0x33338000,"D1":0x44440001})],          # word overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("CMP.B (xxx).L,D0", [0xB039,0x00F0,0x3800], 6,
        [Vec({"D0":0x00000005},opnd=bytes([0x05])),        # equal -> Z
         Vec({"D0":0x00000003},opnd=bytes([0x05]))],       # borrow
        check_regs=["D0"], check_opnd=True, ccr_mask=0x1F))

    # --- Batch 3 cont.: NEG / EXT.l / CMPA / CMPM
    r.append(run_test("NEG.L D0", [0x4480], 2,
        [Vec({"D0":0x00000000}), Vec({"D0":0x00000001}),
         Vec({"D0":0x80000000}), Vec({"D0":0x12345678},ccr=XIN)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("NEG.W D0", [0x4440], 2,
        [Vec({"D0":0xAAAA0001}), Vec({"D0":0xBBBB8000}), Vec({"D0":0xCCCC0000})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("NEG.B D0", [0x4400], 2,
        [Vec({"D0":0x11111101}), Vec({"D0":0x22222280}), Vec({"D0":0x33333300})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("NEG.L (A0)", [0x4490], 2,
        [Vec({"A0":OPND},opnd=opL(0x00000001)), Vec({"A0":OPND},opnd=opL(0x80000000))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("EXT.L D0", [0x48C0], 2,
        [Vec({"D0":0x11110001}), Vec({"D0":0x1111FFFF}), Vec({"D0":0x11110000},ccr=XIN)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("CMPA.W D1,A0", [0xB0C1], 2,
        [Vec({"A0":0x00010000,"D1":0x00000000},ccr=XIN),
         Vec({"A0":0x00000005,"D1":0x00000005}),
         Vec({"A0":0x00000000,"D1":0x0000FFFF})],
        check_regs=["A0","D1"], ccr_mask=0x1F))
    r.append(run_test("CMPA.L D1,A0", [0xB1C1], 2,
        [Vec({"A0":0x00000005,"D1":0x00000005}),
         Vec({"A0":0x00000003,"D1":0x00000005})],
        check_regs=["A0","D1"], ccr_mask=0x1F))
    r.append(run_test("CMPM.L (A1)+,(A0)+", [0xB189], 2,
        [Vec({"A0":OPND,"A1":OPND+4}, opnd=opL(0x00000005)+opL(0x00000005)),
         Vec({"A0":OPND,"A1":OPND+4}, opnd=opL(0x00000003)+opL(0x00000005))],
        check_regs=["A0","A1"], check_opnd=True, ccr_mask=0x1F))

    # --- Batch 3 final: ADDX / SUBX / NEGX (X carry-in, sticky Z).
    r.append(run_test("ADDX.L D1,D0", [0xD181], 2,
        [Vec({"D0":1,"D1":2}, ccr=0),
         Vec({"D0":1,"D1":2}, ccr=ccr_bits(x=1)),                  # +X
         Vec({"D0":0xFFFFFFFF,"D1":0}, ccr=ccr_bits(x=1,z=1)),     # ->0, Z stays 1
         Vec({"D0":0xFFFFFFFF,"D1":0}, ccr=ccr_bits(x=1,z=0)),     # ->0, Z stays 0
         Vec({"D0":0x7FFFFFFF,"D1":1}, ccr=0),                     # overflow
         Vec({"D0":0x12345678,"D1":1}, ccr=ccr_bits(x=1))],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("ADDX.W D1,D0", [0xD141], 2,
        [Vec({"D0":0xAAAAFFFF,"D1":0xBBBB0000}, ccr=ccr_bits(x=1)),  # word carry ->0
         Vec({"D0":0x11117FFF,"D1":0x22220001}, ccr=0)],            # word overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("ADDX.B D1,D0", [0xD101], 2,
        [Vec({"D0":0x111111FF,"D1":0x22222200}, ccr=ccr_bits(x=1)),  # byte carry ->0
         Vec({"D0":0x3333337F,"D1":0x44444401}, ccr=0)],            # byte overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("ADDX.L -(A1),-(A0)", [0xD189], 2,
        [Vec({"A0":OPND+4,"A1":OPND+8}, opnd=opL(0x10)+opL(0x20), ccr=ccr_bits(x=1)),
         Vec({"A0":OPND+4,"A1":OPND+8}, opnd=opL(0)+opL(0), ccr=ccr_bits(z=1))],
        check_regs=["A0","A1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("SUBX.L D1,D0", [0x9181], 2,
        [Vec({"D0":5,"D1":3}, ccr=0),
         Vec({"D0":5,"D1":3}, ccr=ccr_bits(x=1)),                  # -X
         Vec({"D0":5,"D1":5}, ccr=ccr_bits(z=1)),                  # ->0, Z stays 1
         Vec({"D0":5,"D1":5}, ccr=ccr_bits(x=1,z=1)),              # 5-5-1=-1, Z cleared
         Vec({"D0":0x80000000,"D1":1}, ccr=0)],                    # overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("SUBX.B D1,D0", [0x9101], 2,
        [Vec({"D0":0x11111100,"D1":0x22222201}, ccr=0),            # byte borrow
         Vec({"D0":0x33333380,"D1":0x44444401}, ccr=0)],           # byte overflow
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("SUBX.L -(A1),-(A0)", [0x9189], 2,
        [Vec({"A0":OPND+4,"A1":OPND+8}, opnd=opL(0x20)+opL(0x10), ccr=ccr_bits(x=1)),
         Vec({"A0":OPND+4,"A1":OPND+8}, opnd=opL(5)+opL(5), ccr=ccr_bits(z=1))],
        check_regs=["A0","A1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("NEGX.L D0", [0x4080], 2,
        [Vec({"D0":0}, ccr=ccr_bits(z=1)),                         # 0-0-0=0, Z stays 1
         Vec({"D0":0}, ccr=ccr_bits(x=1,z=1)),                     # 0-0-1=-1, Z cleared
         Vec({"D0":1}, ccr=0),                                     # -1
         Vec({"D0":1}, ccr=ccr_bits(x=1)),                         # -2
         Vec({"D0":0x80000000}, ccr=0)],                           # overflow
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("NEGX.B D0", [0x4000], 2,
        [Vec({"D0":0x11111100}, ccr=ccr_bits(z=1)),
         Vec({"D0":0x11111101}, ccr=ccr_bits(x=1))],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("NEGX.L (A0)", [0x4090], 2,
        [Vec({"A0":OPND}, opnd=opL(0x00000001), ccr=ccr_bits(x=1)),
         Vec({"A0":OPND}, opnd=opL(0x00000000), ccr=ccr_bits(z=1))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))

    # --- Batch 4: BCD (ABCD/SBCD/NBCD). Match MAME bit-for-bit incl undefined N/V.
    #   High byte of the Dn must be preserved; sticky Z; X carry-in; invalid nibbles.
    DH=0x77777700   # dest high bits (must survive)
    SH=0x88888800   # src high bits (ignored by BCD)
    r.append(run_test("ABCD.B D1,D0", [0xC101], 2,
        [Vec({"D0":DH|0x25,"D1":SH|0x37}, ccr=ccr_bits(z=1)),   # 62
         Vec({"D0":DH|0x55,"D1":SH|0x55}, ccr=0),               # 0x10, C
         Vec({"D0":DH|0x99,"D1":SH|0x01}, ccr=ccr_bits(z=1)),   # 00, C, Z stays 1
         Vec({"D0":DH|0x25,"D1":SH|0x37}, ccr=ccr_bits(x=1)),   # 63
         Vec({"D0":DH|0x00,"D1":SH|0x00}, ccr=ccr_bits(x=1,z=1)),# 01
         Vec({"D0":DH|0x90,"D1":SH|0x90}, ccr=0),               # 0x80, C
         Vec({"D0":DH|0x0A,"D1":SH|0x06}, ccr=0),               # invalid nibble
         Vec({"D0":DH|0x1F,"D1":SH|0x0B}, ccr=ccr_bits(x=1))],  # invalid nibbles + X
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("SBCD.B D1,D0", [0x8101], 2,
        [Vec({"D0":DH|0x62,"D1":SH|0x37}, ccr=ccr_bits(z=1)),   # 25
         Vec({"D0":DH|0x25,"D1":SH|0x37}, ccr=0),               # -12 -> 0x88, borrow
         Vec({"D0":DH|0x55,"D1":SH|0x55}, ccr=ccr_bits(z=1)),   # 0, Z stays 1
         Vec({"D0":DH|0x62,"D1":SH|0x37}, ccr=ccr_bits(x=1)),   # 24
         Vec({"D0":DH|0x00,"D1":SH|0x01}, ccr=0),               # 0x99, borrow
         Vec({"D0":DH|0x0A,"D1":SH|0x01}, ccr=0)],              # invalid nibble
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # NBCD: V is officially UNDEFINED on the 68000 and MAME's internal value can't be
    # reproduced by the ~init&res rule (e.g. result 0x50 -> MAME V=1 with bit7=0).
    # Validate the four DEFINED flags X/N/Z/C (mask out V = bit1 -> 0x1D).
    r.append(run_test("NBCD.B D0", [0x4800], 2,
        [Vec({"D0":DH|0x00}, ccr=ccr_bits(z=1)),                # 0, Z stays
         Vec({"D0":DH|0x01}, ccr=0),                            # 0x99, borrow
         Vec({"D0":DH|0x99}, ccr=0),                            # 0x01, borrow
         Vec({"D0":DH|0x00}, ccr=ccr_bits(x=1)),                # 0x99, borrow
         Vec({"D0":DH|0x50}, ccr=0),                            # 0x50, borrow
         Vec({"D0":DH|0x0A}, ccr=0)],                           # invalid nibble
        check_regs=["D0"], ccr_mask=0x1D))
    r.append(run_test("ABCD.B -(A1),-(A0)", [0xC109], 2,
        [Vec({"A0":OPND+1,"A1":OPND+2}, opnd=bytes([0x25,0x37]), ccr=0),         # 62
         Vec({"A0":OPND+1,"A1":OPND+2}, opnd=bytes([0x99,0x01]), ccr=ccr_bits(z=1))],  # 00, C
        check_regs=["A0","A1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("NBCD.B (A0)", [0x4810], 2,
        [Vec({"A0":OPND}, opnd=bytes([0x01]), ccr=0),           # 0x99
         Vec({"A0":OPND}, opnd=bytes([0x00]), ccr=ccr_bits(z=1))],  # 0, Z stays
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1D))

    # --- Batch 5: shift/rotate.  reg form 1110 ccc d ss i tt rrr
    def shft(cv,dr,sz,ireg,typ,dn): return 0xE000|(cv<<9)|(dr<<8)|(sz<<6)|(ireg<<5)|(typ<<3)|dn
    HB=0xAAAA0000
    r.append(run_test("ASL.W #1,D0", [shft(1,1,1,0,0,0)], 2,
        [Vec({"D0":HB|0x4000}), Vec({"D0":HB|0x2000}), Vec({"D0":HB|0xC000}),
         Vec({"D0":HB|0x8000}), Vec({"D0":HB|0x0000},ccr=ccr_bits(x=1))],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ASR.W #1,D0", [shft(1,0,1,0,0,0)], 2,
        [Vec({"D0":HB|0x8001}), Vec({"D0":HB|0x0002}), Vec({"D0":HB|0x0001})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ASL.L #8,D0", [shft(0,1,2,0,0,0)], 2,   # cnt 0 -> 8
        [Vec({"D0":0x00FF00FF}), Vec({"D0":0x01020304}), Vec({"D0":0x80000000})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("LSL.B #1,D0", [shft(1,1,0,0,1,0)], 2,
        [Vec({"D0":0x111111FF}), Vec({"D0":0x11111180}), Vec({"D0":0x11111140})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("LSR.B #1,D0", [shft(1,0,0,0,1,0)], 2,
        [Vec({"D0":0x11111101}), Vec({"D0":0x11111180})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("LSR.L #4,D0", [shft(4,0,2,0,1,0)], 2,
        [Vec({"D0":0x1234567F}), Vec({"D0":0xF0000000})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ROL.B #1,D0", [shft(1,1,0,0,3,0)], 2,
        [Vec({"D0":0x11111181}), Vec({"D0":0x11111100})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ROR.B #1,D0", [shft(1,0,0,0,3,0)], 2,
        [Vec({"D0":0x11111101}), Vec({"D0":0x11111180})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ROL.L #1,D0", [shft(1,1,2,0,3,0)], 2,
        [Vec({"D0":0x80000001}), Vec({"D0":0x40000000})],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ROXL.L #1,D0", [shft(1,1,2,0,2,0)], 2,
        [Vec({"D0":0x80000000},ccr=ccr_bits(x=1)), Vec({"D0":0x00000001},ccr=0),
         Vec({"D0":0x80000000},ccr=0)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("ROXR.L #1,D0", [shft(1,0,2,0,2,0)], 2,
        [Vec({"D0":0x00000001},ccr=ccr_bits(x=1)), Vec({"D0":0x00000001},ccr=0)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("LSL.L D1,D0", [shft(1,1,2,1,1,0)], 2,
        [Vec({"D0":0x12345678,"D1":40}),                          # >32 -> 0
         Vec({"D0":0x12345678,"D1":0},ccr=ccr_bits(x=1)),         # count 0: C=0, X kept
         Vec({"D0":0x00000001,"D1":4}),
         Vec({"D0":0x80000000,"D1":1})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("ASR.W D1,D0", [shft(1,0,1,1,0,0)], 2,
        [Vec({"D0":HB|0x8000,"D1":0},ccr=ccr_bits(x=1)),          # count 0: unchanged, C=0
         Vec({"D0":HB|0x8000,"D1":4})],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("ASL.W (A0)", [0xE1D0], 2,
        [Vec({"A0":OPND},opnd=(0x4000).to_bytes(2,"big")),
         Vec({"A0":OPND},opnd=(0xC000).to_bytes(2,"big"))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("LSR.W (A0)", [0xE2D0], 2,
        [Vec({"A0":OPND},opnd=(0x0001).to_bytes(2,"big")),
         Vec({"A0":OPND},opnd=(0x8000).to_bytes(2,"big"))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("ROXL.W (A0)", [0xE5D0], 2,
        [Vec({"A0":OPND},opnd=(0x8000).to_bytes(2,"big"),ccr=ccr_bits(x=1)),
         Vec({"A0":OPND},opnd=(0x0001).to_bytes(2,"big"),ccr=0)],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))

    # Batch 6: Scc <ea> — byte = FF/00 per condition; no flags affected.
    def scc(cc,mode,reg): return 0x50C0|(cc<<8)|(mode<<3)|reg
    SCC_NAMES=["T","F","HI","LS","CC","CS","NE","EQ","VC","VS","PL","MI","GE","LT","GT","LE"]
    scc_ccrs=[0x00,0x01,0x02,0x04,0x08,0x05,0x0A,0x0F,0x0C,0x03]
    for cc in range(16):
        r.append(run_test(f"Scc[S{SCC_NAMES[cc]}].B D0", [scc(cc,0,0)], 2,
            [Vec({"D0":0x11223344},ccr=c) for c in scc_ccrs],
            check_regs=["D0"], ccr_mask=0x1F))
    # Scc memory form (An) — exercises EA byte writeback for true/false/conditional
    for cc in (0,1,6,7,13):
        r.append(run_test(f"Scc[S{SCC_NAMES[cc]}].B (A0)", [scc(cc,2,0)], 2,
            [Vec({"A0":OPND},opnd=bytes([0x55]),ccr=c) for c in scc_ccrs],
            check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))

    # Batch 6: DBcc Dn,disp16 — decrement-and-branch. PC checked via base offset.
    #   cc TRUE -> terminate (PC+4, no dec) ; cc FALSE -> Dn.w-=1, branch unless expired.
    def dbcc(cc,reg): return 0x50C8|(cc<<8)|reg
    Zset=ccr_bits(z=1); Zclr=ccr_bits(z=0)
    # DBT (cc=0): always true -> terminate, no decrement.
    r.append(run_test("DBT D0 (+4)", [dbcc(0,0),0x0004], 4,
        [Vec({"D0":0x00070005},ccr=Zset), Vec({"D0":0x00000000},ccr=0)],
        check_regs=["D0","PC"]))
    # DBNE (cc=6): terminate when Z=0; else dec Dn.w & branch (high word preserved).
    r.append(run_test("DBNE D0 (+4)", [dbcc(6,0),0x0004], 4,
        [Vec({"D0":0x00070005},ccr=Zset),    # Z=1 false -> 5->4, branch +6
         Vec({"D0":0x00070000},ccr=Zset),    # expired -> ->FFFF, +4
         Vec({"D0":0x00070005},ccr=Zclr)],   # Z=0 true -> terminate, +4
        check_regs=["D0","PC"]))
    # DBNE backward branch (disp16 = -4 -> target offset -2).
    r.append(run_test("DBNE D0 (-4)", [dbcc(6,0),0xFFFC], 4,
        [Vec({"D0":0x00070003},ccr=Zset)],
        check_regs=["D0","PC"]))
    # DBEQ (cc=7) on D3.
    r.append(run_test("DBEQ D3 (+4)", [dbcc(7,3),0x0004], 4,
        [Vec({"D3":0x00070005},ccr=Zclr),    # EQ false (Z=0) -> dec/branch
         Vec({"D3":0x00070000},ccr=Zclr),    # expired
         Vec({"D3":0x00070005},ccr=Zset)],   # EQ true -> terminate
        check_regs=["D3","PC"]))

    # Batch 6: BTST/BCHG/BCLR/BSET — static (#n) & dynamic (Dn); Dn=long/mod32,
    #   mem=byte/mod8. Z=!(old bit); X/N/V/C preserved (input CFULL = X,N,V,C set).
    def bstat(typ,mode,reg): return 0x0800|(typ<<6)|(mode<<3)|reg
    def bdyn(typ,dn,mode,reg): return 0x0100|(dn<<9)|(typ<<6)|(mode<<3)|reg
    CFULL=ccr_bits(x=1,n=1,v=1,c=1)
    r.append(run_test("Bit:BTST D1,D0", [bdyn(0,1,0,0)], 2,
        [Vec({"D0":0x00000001,"D1":0},ccr=CFULL), Vec({"D0":0x00000001,"D1":1},ccr=CFULL),
         Vec({"D0":0x80000000,"D1":31},ccr=CFULL), Vec({"D0":0x80000000,"D1":32},ccr=CFULL),
         Vec({"D0":0x00000000,"D1":5},ccr=CFULL), Vec({"D0":0xFFFFFFFF,"D1":15},ccr=CFULL)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("Bit:BCHG D1,D0", [bdyn(1,1,0,0)], 2,
        [Vec({"D0":0,"D1":3},ccr=CFULL), Vec({"D0":0x08,"D1":3},ccr=CFULL),
         Vec({"D0":0x80000000,"D1":31},ccr=CFULL), Vec({"D0":0,"D1":31},ccr=CFULL)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("Bit:BCLR D1,D0", [bdyn(2,1,0,0)], 2,
        [Vec({"D0":0xFFFFFFFF,"D1":0},ccr=CFULL), Vec({"D0":0,"D1":5},ccr=CFULL),
         Vec({"D0":0xFFFFFFFF,"D1":31},ccr=CFULL)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("Bit:BSET D1,D0", [bdyn(3,1,0,0)], 2,
        [Vec({"D0":0,"D1":0},ccr=CFULL), Vec({"D0":0xFFFFFFFF,"D1":4},ccr=CFULL),
         Vec({"D0":0,"D1":31},ccr=CFULL)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("Bit:BTST #4,D0", [bstat(0,0,0),0x0004], 4,
        [Vec({"D0":0x10},ccr=CFULL), Vec({"D0":0},ccr=CFULL)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("Bit:BSET #31,D0", [bstat(3,0,0),0x001F], 4,
        [Vec({"D0":0},ccr=CFULL), Vec({"D0":0x80000000},ccr=CFULL)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("Bit:BTST #7,(A0)", [bstat(0,2,0),0x0007], 4,
        [Vec({"A0":OPND},opnd=bytes([0x80]),ccr=CFULL), Vec({"A0":OPND},opnd=bytes([0x00]),ccr=CFULL)],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("Bit:BSET #3,(A0)", [bstat(3,2,0),0x0003], 4,
        [Vec({"A0":OPND},opnd=bytes([0x00]),ccr=CFULL), Vec({"A0":OPND},opnd=bytes([0xFF]),ccr=CFULL)],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("Bit:BSET D1,(A0)", [bdyn(3,1,2,0)], 2,
        [Vec({"A0":OPND,"D1":2},opnd=bytes([0x00]),ccr=CFULL),
         Vec({"A0":OPND,"D1":10},opnd=bytes([0x04]),ccr=CFULL)],   # mod8=2
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))
    r.append(run_test("Bit:BCLR D1,(A0)", [bdyn(2,1,2,0)], 2,
        [Vec({"A0":OPND,"D1":1},opnd=bytes([0xFF]),ccr=CFULL),
         Vec({"A0":OPND,"D1":1},opnd=bytes([0x00]),ccr=CFULL)],
        check_regs=["A0","D1"], check_opnd=True, ccr_mask=0x1F))

    # Batch 7: MULU/MULS/DIVU/DIVS/CHK (generic EA, word source). X preserved.
    def mulu(dn,mode,reg): return 0xC0C0|(dn<<9)|(mode<<3)|reg
    def muls(dn,mode,reg): return 0xC1C0|(dn<<9)|(mode<<3)|reg
    def divu(dn,mode,reg): return 0x80C0|(dn<<9)|(mode<<3)|reg
    def divs(dn,mode,reg): return 0x81C0|(dn<<9)|(mode<<3)|reg
    def chk(dn,mode,reg):  return 0x4180|(dn<<9)|(mode<<3)|reg
    X1=ccr_bits(x=1)
    # MULU.W D1,D0 (reg src). N=bit31, Z, V=C=0, X kept. (high word of D0 ignored)
    r.append(run_test("B7:MULU.W D1,D0", [mulu(0,0,1)], 2,
        [Vec({"D0":0x12340003,"D1":0x00000004},ccr=X1),
         Vec({"D0":0x0000FFFF,"D1":0x0000FFFF},ccr=X1),
         Vec({"D0":0x00000000,"D1":0x00001234},ccr=X1),
         Vec({"D0":0x00008000,"D1":0x00000002},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # MULU.W #imm,D0 (immediate-source EA -> my op_mulu, no fast-path exists)
    r.append(run_test("B7:MULU.W #7,D0", [mulu(0,7,4),0x0007], 4,
        [Vec({"D0":0x00000003},ccr=X1), Vec({"D0":0x0000FFFF},ccr=X1)],
        check_regs=["D0"], ccr_mask=0x1F))
    # MULU.W (A0),D0 (memory-source word)
    r.append(run_test("B7:MULU.W (A0),D0", [mulu(0,2,0)], 2,
        [Vec({"D0":0x00000005,"A0":OPND},opnd=(0x0003).to_bytes(2,"big"),ccr=X1),
         Vec({"D0":0x0000FFFF,"A0":OPND},opnd=(0x0002).to_bytes(2,"big"),ccr=X1)],
        check_regs=["D0","A0"], ccr_mask=0x1F))
    # MULS.W D1,D0 (signed)
    r.append(run_test("B7:MULS.W D1,D0", [muls(0,0,1)], 2,
        [Vec({"D0":0x0000FFFF,"D1":0x00000002},ccr=X1),
         Vec({"D0":0x0000FFFF,"D1":0x0000FFFF},ccr=X1),
         Vec({"D0":0x00008000,"D1":0x00008000},ccr=X1),
         Vec({"D0":0x00000000,"D1":0x0000FFFF},ccr=X1),
         Vec({"D0":0x00007FFF,"D1":0x00007FFF},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # DIVU.W D1,D0 (no overflow): quot lo16, rem hi16; N=quot bit15
    r.append(run_test("B7:DIVU.W D1,D0", [divu(0,0,1)], 2,
        [Vec({"D0":0x00000064,"D1":0x00000007},ccr=X1),
         Vec({"D0":0x00010000,"D1":0x00000002},ccr=X1),
         Vec({"D0":0x00000000,"D1":0x00000005},ccr=X1),
         Vec({"D0":0x0001FFFF,"D1":0x00000002},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # DIVU.W overflow: V=1, C=0, no write (N/Z undefined -> mask V,C only)
    r.append(run_test("B7:DIVU.W ovf", [divu(0,0,1)], 2,
        [Vec({"D0":0xFFFFFFFE,"D1":0x00000001},ccr=X1),
         Vec({"D0":0x00020000,"D1":0x00000001},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x03))
    # DIVS.W D1,D0 (signed, no overflow). rem sign = dividend sign.
    r.append(run_test("B7:DIVS.W D1,D0", [divs(0,0,1)], 2,
        [Vec({"D0":0x00000064,"D1":0x00000007},ccr=X1),
         Vec({"D0":0xFFFFFF9C,"D1":0x00000007},ccr=X1),
         Vec({"D0":0x00000064,"D1":0x0000FFF9},ccr=X1),
         Vec({"D0":0xFFFFFF9C,"D1":0x0000FFF9},ccr=X1),
         Vec({"D0":0x00000000,"D1":0x00000005},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    # DIVS.W overflow: V=1, no write
    r.append(run_test("B7:DIVS.W ovf", [divs(0,0,1)], 2,
        [Vec({"D0":0x00010000,"D1":0x00000001},ccr=X1),
         Vec({"D0":0x80000000,"D1":0x0000FFFF},ccr=X1)],
        check_regs=["D0","D1"], ccr_mask=0x03))
    # CHK.W D1,D0 in-range (no trap): PC += 2, regs unchanged, flags undefined.
    r.append(run_test("B7:CHK.W D1,D0 ok", [chk(0,0,1)], 2,
        [Vec({"D0":0x00000005,"D1":0x0000000A}),
         Vec({"D0":0x0000000A,"D1":0x0000000A}),
         Vec({"D0":0x00000000,"D1":0x0000000A})],
        check_regs=["D0","D1","PC"], check_ccr=False))
    # #imm MULS/DIVS (formerly op_muls_w/op_divs_w fast path; now generic). The
    # game uses these immediate forms, so confirm parity through the new path.
    r.append(run_test("B7:MULS.W #-2,D0", [muls(0,7,4),0xFFFE], 4,
        [Vec({"D0":0x00000003},ccr=X1), Vec({"D0":0x0000FFFF},ccr=X1),
         Vec({"D0":0x00008000},ccr=X1), Vec({"D0":0x00000000},ccr=X1)],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("B7:DIVS.W #7,D0", [divs(0,7,4),0x0007], 4,
        [Vec({"D0":0x00000064},ccr=X1), Vec({"D0":0xFFFFFF9C},ccr=X1),
         Vec({"D0":0x00000000},ccr=X1)],
        check_regs=["D0"], ccr_mask=0x1F))

    # Batch 7 trap paths: DIVU/DIVS by zero -> vector 5 ($00100142); CHK
    # out-of-range -> vector 6 ($00100162). The free-run+spin MAME model can't
    # observe these (the real handler runs), so these are validated against MAME
    # ground truth captured via a stack write-tap (see notes below). We set
    # A7=OPND+6 so the pushed exception frame ([SP]=SR word, [SP+2]=return PC
    # long) lands in the 16-byte OPND readback window. X is preserved.
    #   MAME-captured stacked CCR (low5 of SR), SR-in=271F (all CCR+X set):
    #     DIVU #0  -> 10 (X; N=Z=V=C=0)
    #     DIVS #0  -> 14 (X,Z; N=V=C=0)
    #     CHK>bound-> 10 (X; N=0)        CHK<0 -> 18 (X,N)
    #   return PC offset = oplen (4); SR high byte = 27 (supervisor+mask).
    V5=0x00100142; V6=0x00100162
    def trap_check(name, opwords, oplen, dn_d0, vec_target, want_ccr,
                   want_retoff=None, in_ccr=None):
        if _FILTER and _FILTER.lower() not in name.lower(): return True
        if want_retoff is None: want_retoff=oplen
        if in_ccr is None: in_ccr=ccr_bits(x=1,n=1,z=1,v=1,c=1)
        print(f"=== {name} (trap) ===")
        v=Vec({"D0":dn_d0,"A7":OPND+6}, ccr=in_ccr)
        res=interp_run(opwords, oplen, [v])[0]
        frame=res["OPND"][:6]
        sr=(frame[0]<<8)|frame[1]
        retpc=(frame[2]<<24)|(frame[3]<<16)|(frame[4]<<8)|frame[5]
        retoff=(retpc-INTERP_CODE_68K)&0xFFFFFFFF
        ok=(res["PC"]==vec_target and res["A7"]==OPND and retoff==want_retoff
            and (sr>>8)==0x27 and (sr&0x1F)==want_ccr)
        if ok: print(f"  PASS  PC={res['PC']:08X} A7={res['A7']:08X} SR={sr:04X} retoff={retoff}")
        else:  print(f"  FAIL  PC={res['PC']:08X}(want {vec_target:08X}) A7={res['A7']:08X}"
                     f"(want {OPND:08X}) SR={sr:04X}(hi want 27, ccr want {want_ccr:02X}) retoff={retoff}(want {want_retoff})")
        return ok
    r.append(trap_check("B7:DIVU #0 ->vec5", [0x80FC,0x0000], 4, 0x00010000, V5, 0x10))
    r.append(trap_check("B7:DIVS #0 ->vec5", [0x81FC,0x0000], 4, 0x00010000, V5, 0x14))
    r.append(trap_check("B7:DIVU D1=0 ->vec5", [divu(0,0,1)], 2, 0x00010000, V5, 0x10))  # reg divisor 0 (D1=0)
    r.append(trap_check("B7:CHK >bound ->vec6", [0x41BC,0x0005], 4, 0x0000000A, V6, 0x10))
    r.append(trap_check("B7:CHK <0 ->vec6", [0x41BC,0x0005], 4, 0x0000FFFF, V6, 0x18))

    # ---- Batch 8: control/system ----
    # interp-only self-consistency for ops not observable via free-run+spin
    # (privileged / stack-relative). want keys: PCoff(off from base), PCabs,
    # A7, CCR, USP, reg names, or 'opnd'(bytes prefix).
    def interp_only(name, opwords, oplen, vec, want):
        if _FILTER and _FILTER.lower() not in name.lower(): return True
        print(f"=== {name} (interp) ===")
        res=interp_run(opwords, oplen, [vec])[0]
        fails=[]
        for k,exp in want.items():
            if k=="PCoff":   got=(res["PC"]-INTERP_CODE_68K)&0xFFFFFFFF
            elif k=="PCabs": got=res["PC"]
            elif k=="opnd":
                got=res["OPND"][:len(exp)]
                if got!=exp: fails.append(f"{k}={got.hex()} want {exp.hex()}")
                continue
            else: got=res[k]
            if got!=exp: fails.append(f"{k}={got:X} want {exp:X}")
        print("  PASS" if not fails else "  FAIL  "+"; ".join(fails))
        return not fails
    FULL=ccr_bits(x=1,n=1,z=1,v=1,c=1)
    # EXG (32-bit swap; no flags)
    r.append(run_test("B8:EXG D0,D1", [0xC141], 2,
        [Vec({"D0":0x11112222,"D1":0x3333AAAA},ccr=FULL)],
        check_regs=["D0","D1"], ccr_mask=0x1F))
    r.append(run_test("B8:EXG A0,A1", [0xC149], 2,
        [Vec({"A0":0x12345678,"A1":0x9ABCDEF0})], check_regs=["A0","A1"], ccr_mask=0x1F))
    r.append(run_test("B8:EXG D0,A1", [0xC189], 2,
        [Vec({"D0":0xCAFEBABE,"A1":0x0BADF00D})], check_regs=["D0","A1"], ccr_mask=0x1F))
    # TAS: byte; N/Z from value; V=C=0; X kept; set bit7
    r.append(run_test("B8:TAS D0", [0x4AC0], 2,
        [Vec({"D0":0x11223300},ccr=ccr_bits(x=1)), Vec({"D0":0x11223380},ccr=ccr_bits(x=1)),
         Vec({"D0":0x1122337F},ccr=ccr_bits(x=1))],
        check_regs=["D0"], ccr_mask=0x1F))
    r.append(run_test("B8:TAS (A0)", [0x4AD0], 2,
        [Vec({"A0":OPND},opnd=bytes([0x00]),ccr=ccr_bits(x=1)),
         Vec({"A0":OPND},opnd=bytes([0x80]),ccr=ccr_bits(x=1)),
         Vec({"A0":OPND},opnd=bytes([0x7F]),ccr=ccr_bits(x=1))],
        check_regs=["A0"], check_opnd=True, ccr_mask=0x1F))
    # MOVE SR,Dn : Dn.w = SR (= 0x2700|CCR); high16 kept; flags unchanged
    r.append(run_test("B8:MOVE SR,D0", [0x40C0], 2,
        [Vec({"D0":0xFFFF0000},ccr=ccr_bits(c=1)),
         Vec({"D0":0xFFFF0000},ccr=FULL),
         Vec({"D0":0xFFFF0000},ccr=0)],
        check_regs=["D0"], ccr_mask=0x1F))
    # MOVE #imm,CCR : CCR = imm low byte
    for imm in [0x0000,0x001F,0x0010,0x000A,0x0015]:
        r.append(run_test(f"B8:MOVE #{imm:02X},CCR", [0x44FC,imm], 4,
            [Vec(ccr=FULL)], check_regs=[], ccr_mask=0x1F))
    # MOVE #imm,SR : SR = imm (keep supervisor 0x27xx to avoid mode switch)
    for imm in [0x2700,0x271F,0x2710,0x270A]:
        r.append(run_test(f"B8:MOVE #{imm:04X},SR", [0x46FC,imm], 4,
            [Vec(ccr=FULL)], check_regs=[], ccr_mask=0x1F))
    # MOVEP (alternate-byte transfers; no flags). A0=OPND, d16=0.
    r.append(run_test("B8:MOVEP.L D0,(0,A0)", [0x01C8,0x0000], 4,
        [Vec({"D0":0x12345678,"A0":OPND})], check_regs=[], check_opnd=True))
    r.append(run_test("B8:MOVEP.W D0,(0,A0)", [0x0188,0x0000], 4,
        [Vec({"D0":0x12345678,"A0":OPND})], check_regs=[], check_opnd=True))
    r.append(run_test("B8:MOVEP.L (0,A0),D0", [0x0148,0x0000], 4,
        [Vec({"D0":0x00000000,"A0":OPND},opnd=bytes([0x12,0,0x34,0,0x56,0,0x78]))],
        check_regs=["D0"], check_opnd=True))
    r.append(run_test("B8:MOVEP.W (0,A0),D0", [0x0108,0x0000], 4,
        [Vec({"D0":0xAAAA0000,"A0":OPND},opnd=bytes([0x12,0,0x34]))],
        check_regs=["D0"], check_opnd=True))
    # Trap ops (interp single-steps cleanly; compared to MAME-captured truth).
    #   ILLEGAL -> vec4 ($0010011A), retPC=instr addr (offset 0), CCR kept.
    #   TRAPV(V=1) -> vec7 ($00100186), retPC=next (offset 2), CCR kept.
    r.append(trap_check("B8:ILLEGAL ->vec4", [0x4AFC], 2, 0, 0x0010011A, 0x1F, want_retoff=0))
    r.append(trap_check("B8:TRAPV(V) ->vec7", [0x4E76], 2, 0, 0x00100186, 0x1F, want_retoff=2))
    # interp-only: RESET noop, TRAPV no-trap, STOP, RTR, MOVE An,USP
    r.append(interp_only("B8:RESET noop", [0x4E70], 2, Vec({"D0":0x12345678},ccr=FULL),
        {"PCoff":2, "D0":0x12345678, "CCR":FULL}))
    r.append(interp_only("B8:TRAPV(noV)", [0x4E76], 2, Vec({"A7":OPND+6},ccr=0),
        {"PCoff":2, "A7":OPND+6}))
    r.append(interp_only("B8:STOP #271F", [0x4E72,0x271F], 4, Vec(ccr=0),
        {"PCoff":4, "CCR":0x1F}))
    r.append(interp_only("B8:RTR", [0x4E77], 2,
        Vec({"A7":OPND},opnd=bytes([0x00,0x1F, 0x00,0x07,0xC0,0x40]),ccr=0),
        {"PCabs":0x0007C040, "A7":OPND+6, "CCR":0x1F}))
    r.append(interp_only("B8:MOVE A0,USP", [0x4E60], 2, Vec({"A0":0x0BADCAFE}),
        {"USP":0x0BADCAFE, "PCoff":2}))

    print(f"\n{sum(r)}/{len(r)} ops green")
    sys.exit(0 if all(r) else 1)
