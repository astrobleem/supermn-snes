#!/usr/bin/env python3
"""
opsweep.py — GENERATED 68000 op × addressing-mode coverage sweep, differential
against MAME (the CPU-correctness oracle). Built on optest.py's single-step
mechanism, but it enumerates instruction families × every testable EA mode
(including the read-modify-write memory-destination forms: bit ops, CLR/NEG/NOT,
ADDQ/SUBQ-to-memory, MOVE Dn,(ea), shifts-to-memory), and DIFFS THE FULL STATE
per case: D0-D7, A0-A6, PC, CCR, and the touched memory operand.

Output:
  * a coverage matrix (op-family rows × EA-mode columns; cell = pass/FAIL/skip)
  * the explicit list of failing cells with the first per-register mismatch

Both engines run in a SINGLE launch each: every "shot" (op+vector) is baked into
its own ROM slot for the interpreter and re-written at $F03000 per-vector for
MAME, so the whole sweep is one MAME process + one Mesen session.

Excluded by construction (documented limitations, NOT silent gaps):
  * A7/USP: MAME's readback is unreliable -> A7 is not diffed. EA registers use
    A0..A3, never A7, so no tested mode touches A7.
  * (xxx).W: sign-extends a 16-bit address, cannot reach the $F03800 operand.
  * (d16,PC)/(d8,PC,Xn) source: the two engines execute at different PCs.
  * privileged / trap / control-flow ops: covered by optest.py, not here.

Usage:
  python3 tools/opsweep.py                 # full sweep, print matrix + failures
  SWEEP_FILTER=CLR python3 tools/opsweep.py  # only families whose name matches
"""
import os, sys, subprocess, tempfile, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import optest as OT
from optest import (Vec, ccr_bits, REGNAMES, MAME, ROMPATH, NVRAM, CFG,
                    INTERP_SFC, MESEN, MAME_CODE, OPND, STACK)

# ROM op-slot region. MUST be in a bank the SA-1 actually fetches: during play the
# interp only fetches PC-bank 0 -> ROM bank $C1 (proven visible); high banks ($C8 etc.)
# are the untested Phase-A MMC-window risk. Slots live at 68K $1000-$FFFF (-> $C1:1000,
# file $11000), i.e. all of bank $C1 above the vectors: ~1920 slots of 0x20 bytes.
# (Overwrites game image there; harmless in test mode.) If a shot's PC would leave bank
# $C1 the runner chunks the sweep so each pass fits.
SLOT_BASE_68K = 0x001000
SLOT_BASE_ROMOFF = 0x10000 + SLOT_BASE_68K
SLOT_STRIDE = 0x20
MAX_SLOTS = (0x10000 - SLOT_BASE_68K)//SLOT_STRIDE   # stay within bank $C1

# SA-1 memory model (the interp runs on the SA-1 coprocessor, not the 5A22):
#   * interp DP / register file / flags / mailbox ($00-$FF) -> SA-1 IRAM = Sa1Memory $00-$FF
#   * 68K work RAM ($F0xxxx) -> BW-RAM bank $40 = snesMemory $40xxxx (readbyte/writebyte route $F0->$40)
# The old optest.py addressed snesWorkRam ($7E/$7F), correct only for the pre-SA-1 build.
DP_SPACE   = "Sa1Memory"
OPND_ADDR  = 0x400000 | (OPND & 0xFFFF)   # $F03800 work RAM -> BW-RAM $40:3800
OPND_SPACE = "snesMemory"

# Registers diffed every case. A7 excluded (MAME readback unreliable).
DIFF_REGS = ["D0","D1","D2","D3","D4","D5","D6","D7",
             "A0","A1","A2","A3","A4","A5","A6"]

# ---------------------------------------------------------------------------
# A "shot" = one (opwords, oplen, Vec) to execute on both engines.
class Shot:
    def __init__(self, opwords, oplen, vec):
        self.opwords = list(opwords); self.oplen = oplen; self.vec = vec
        self.slot = None   # assigned at bake time

# ---------------------------------------------------------------------------
# MAME oracle — one launch, per-vector op write + spin.
def mame_run_shots(shots):
    mame_name = lambda n: "SP" if n=="A7" else n
    lua_vecs=[]
    for s in shots:
        v=s.vec
        regset=" ".join(f'st["{mame_name(n)}"].value={v.regs.get(n,0)&0xFFFFFFFF}'
                        for n in REGNAMES)
        opnd_writes=" ".join(f"prog:write_u8(0x{OPND+i:X},0x{v.opnd[i]:02X})" for i in range(16))
        opw=" ".join(f"prog:write_u16(0x{MAME_CODE+2*i:X},0x{w:04X})"
                     for i,w in enumerate(s.opwords))
        spin=f"prog:write_u16(0x{MAME_CODE+s.oplen:X},0x60FE)"
        lua_vecs.append(f"{{sr=0x{0x2700|v.ccr:04X}, "
                        f"setup=function() {regset}; {opw}; {spin}; {opnd_writes} end}}")
    vec_tbl=",\n".join(lua_vecs)
    lua=f"""
KEEP={{}}
local cpu=manager.machine.devices[":maincpu"]
local prog=cpu.spaces["program"]
local st=cpu.state
local out=io.open("opsweep_mame.txt","w")
local vecs={{
{vec_tbl}
}}
local i=1
local sub=0
local fc=0
KEEP[1]=emu.register_frame_done(function()
  fc=fc+1
  if fc<30 then return end
  if i>#vecs then out:close(); io.stderr:write("DONE\\n"); os.exit(0) end
  sub=sub+1
  if sub==1 then
    for a=0,0x80,2 do prog:write_u16(0x{MAME_CODE-0x40:X}+a,0x60FE) end
    vecs[i].setup()
    st["SR"].value=vecs[i].sr
    st["PC"].value=0x{MAME_CODE:X}
  elseif sub==4 then
    local s=string.format("VEC %d", i)
    local rd={{ {{"D0","D0"}},{{"D1","D1"}},{{"D2","D2"}},{{"D3","D3"}},{{"D4","D4"}},{{"D5","D5"}},{{"D6","D6"}},{{"D7","D7"}},{{"A0","A0"}},{{"A1","A1"}},{{"A2","A2"}},{{"A3","A3"}},{{"A4","A4"}},{{"A5","A5"}},{{"A6","A6"}},{{"A7","SP"}} }}
    for _,p in ipairs(rd) do s=s..string.format(" %s=%08X", p[1], st[p[2]].value) end
    s=s..string.format(" CCR=%02X", st["SR"].value & 0x1F)
    s=s..string.format(" PC=%08X", st["PC"].value)
    s=s.." OPND="
    for k=0,15 do s=s..string.format("%02X", prog:read_u8(0x{OPND:X}+k)) end
    out:write(s.."\\n"); out:flush()
    i=i+1; sub=0
  end
end)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, dir=OT.REPO) as f:
        f.write(lua); script=f.name
    outpath=os.path.join(OT.REPO,"opsweep_mame.txt")
    if os.path.exists(outpath): os.remove(outpath)
    nframes=30+4*len(shots)+20
    secs=max(8, nframes//60 + 6)
    cmd=[MAME,"superman","-rompath",ROMPATH,"-video","none","-sound","none",
         "-nothrottle","-skip_gameinfo","-seconds_to_run",str(secs),
         "-autoboot_script",script,"-autoboot_delay","0",
         "-nvram_directory",NVRAM,"-cfg_directory",CFG]
    env=os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER","dummy"); env.setdefault("SDL_AUDIODRIVER","dummy")
    subprocess.run(cmd, cwd=OT.REPO, capture_output=True, timeout=secs+40, env=env)
    os.remove(script)
    res={}
    if os.path.exists(outpath):
        for line in open(outpath):
            m=re.match(r"VEC (\d+) (.*)", line.strip())
            if not m: continue
            idx=int(m.group(1))-1; d={}
            for tok in m.group(2).split():
                k,_,vv=tok.partition("=")
                if k=="OPND": d["OPND"]=bytes.fromhex(vv)
                elif k=="CCR": d["CCR"]=int(vv,16)
                else: d[k]=int(vv,16)
            res[idx]=d
    return [res.get(i) for i in range(len(shots))]

# ---------------------------------------------------------------------------
# Interpreter — bake every distinct shot at its own ROM slot, one Mesen session.
def _regblk(v):
    b=bytearray(0x40)
    for i,n in enumerate(REGNAMES):
        val=v.regs.get(n,0)&0xFFFFFFFF; off=i*4
        b[off]=val&0xFF; b[off+1]=(val>>8)&0xFF; b[off+2]=(val>>16)&0xFF; b[off+3]=(val>>24)&0xFF
    return bytes(b)

def _make_sweep_sfc(shots):
    data=bytearray(open(INTERP_SFC,"rb").read())
    data[OT.MBOX]=0x01; data[OT.MBOX+1]=0x00            # TESTFLAG=1 (5A22 HiROM view $C0:F400)
    # The interp runs on the SA-1, which reads $00:F400 via the LoROM mirror -> file $7400.
    # Without this, the SA-1 never sees TESTFLAG and just free-runs the game (the long-
    # standing reason the optest single-step "broke" after the SA-1 migration).
    data[0x7400]=0x01; data[0x7401]=0x00
    for k,s in enumerate(shots):
        s.slot=k
        off=SLOT_BASE_ROMOFF + k*SLOT_STRIDE
        opb=b"".join(int(w).to_bytes(2,"big") for w in s.opwords)
        data[off:off+len(opb)]=opb
    f=tempfile.NamedTemporaryFile(suffix=".sfc", delete=False, dir="/tmp")
    f.write(data); f.close()
    return f.name

def interp_run_shots(shots):
    sys.path.insert(0,"/home/chad/Mesen2/python")
    os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
    os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
    from mesen_mcp import McpSession
    sfc=_make_sweep_sfc(shots)
    out=[]
    try:
        with McpSession(rom=sfc, mesen=MESEN, port=7341, boot_wait=3.0) as m:
            for s in shots:
                v=s.vec
                pc=SLOT_BASE_68K + s.slot*SLOT_STRIDE
                m.write_memory(DP_SPACE, 0x00, _regblk(v).hex())
                m.write_memory(DP_SPACE, 0x40,
                               bytes([pc&0xFF,(pc>>8)&0xFF,(pc>>16)&0xFF,(pc>>24)&0xFF]).hex())
                Z=(v.ccr>>2)&1; C=v.ccr&1; N=(v.ccr>>3)&1; V=(v.ccr>>1)&1; X=(v.ccr>>4)&1
                for addr,val in ((0x60,Z),(0x6E,C),(0x70,N),(0x72,V),(0xA2,X)):
                    m.write_memory(DP_SPACE, addr, bytes([val,0]).hex())
                m.write_memory(DP_SPACE, 0x7C, bytes([0x07,0]).hex())
                m.write_memory(OPND_SPACE, OPND_ADDR, v.opnd.hex())
                m.write_memory(DP_SPACE, 0xA0, bytes([0x01,0]).hex())
                m.run_frames(1)
                regblk=m.read_memory(DP_SPACE, 0x00, 0x40)
                flagblk=m.read_memory(DP_SPACE, 0x60, 0x20)
                xbyte=m.read_memory(DP_SPACE, 0xA2, 1)
                opnd=m.read_memory(OPND_SPACE, OPND_ADDR, 16)
                stopf=m.read_memory(DP_SPACE, 0x4E, 2)
                pcblk=m.read_memory(DP_SPACE, 0x40, 4)
                d={"PC":pcblk[0]|(pcblk[1]<<8)|(pcblk[2]<<16)|(pcblk[3]<<24)}
                for i,n in enumerate(REGNAMES):
                    off=i*4
                    d[n]=(regblk[off]|(regblk[off+1]<<8))|((regblk[off+2]|(regblk[off+3]<<8))<<16)
                Z=1 if flagblk[0] else 0; C=1 if flagblk[0xE] else 0
                N=1 if flagblk[0x10] else 0; V=1 if flagblk[0x12] else 0; X=1 if xbyte[0] else 0
                d["CCR"]=ccr_bits(X,N,Z,V,C); d["OPND"]=bytes(opnd)
                d["_stopped"]=(stopf[0]|(stopf[1]<<8))
                out.append(d)
    finally:
        os.remove(sfc)
    return out

# ---------------------------------------------------------------------------
# Diff one shot. Returns "" if pass, else first-mismatch string. None=skip(no mame).
def diff_shot(s, mr, ir, ccr_mask=0x1F, check_opnd=True):
    if mr is None: return "MAME:no-result"
    if ir.get("_stopped")!=1: return f"interp-no-step(stop={ir.get('_stopped'):#06x})"
    for n in DIFF_REGS:
        if mr.get(n)!=ir.get(n):
            return f"{n} mame={mr.get(n):08X} interp={ir.get(n):08X}"
    mo=(mr["PC"]-MAME_CODE-2)&0xFFFFFFFF
    io=(ir["PC"]-(SLOT_BASE_68K+s.slot*SLOT_STRIDE))&0xFFFFFFFF
    if mo!=io: return f"PC off mame=+{mo:X} interp=+{io:X}"
    if (mr["CCR"]&ccr_mask)!=(ir["CCR"]&ccr_mask):
        return f"CCR mame={mr['CCR']:02X} interp={ir['CCR']:02X}"
    if check_opnd and mr["OPND"]!=ir["OPND"]:
        return f"OPND mame={mr['OPND'].hex()} interp={ir['OPND'].hex()}"
    return ""

# ===========================================================================
# Addressing-mode catalog. Each entry builds the EA bits + ext words + the Vec
# register/operand setup for a given size (1/2/4 bytes). role:
#   reg  = Dn direct        an = An direct
#   mem  = memory at OPND   imm = immediate (source only; value in ext words)
def ea_bits(mode,reg): return (mode<<3)|reg

# size in bytes -> operand bytes (big-endian) for a test value
def opbytes(val, size): return (val & ((1<<(8*size))-1)).to_bytes(size,"big")

class EAMode:
    def __init__(self, name, mode, reg, role, ext):
        self.name=name; self.mode=mode; self.reg=reg; self.role=role; self.ext=ext
    def bits(self): return ea_bits(self.mode,self.reg)

# ext: callable(size)->list of ext words (the immediate is appended separately for imm)
EA_MODES = [
    EAMode("Dn",        0,2,"reg", lambda sz: []),
    EAMode("An",        1,2,"an",  lambda sz: []),
    EAMode("(An)",      2,0,"mem", lambda sz: []),
    EAMode("(An)+",     3,0,"mem", lambda sz: []),
    EAMode("-(An)",     4,0,"mem", lambda sz: []),
    EAMode("(d16,An)",  5,0,"mem", lambda sz: [0x0000]),
    EAMode("(d8,An,Xn)",6,0,"mem", lambda sz: [0xB000]),     # index = A3 (=0), d8=0
    EAMode("(xxx).L",   7,1,"mem", lambda sz: [0x00F0,0x3800]),
    EAMode("#imm",      7,4,"imm", None),
]
EA_BYNAME = {e.name:e for e in EA_MODES}
COLS = [e.name for e in EA_MODES]

# Apply an EA operand of `size` bytes holding `val` to a Vec's regs/opnd.
# Returns extra ext words for the instruction.
def apply_ea(ea, val, size, regs, opndbuf, opnd_off=0):
    if ea.role=="reg":
        regs["D2"]=val & ((1<<(8*size))-1) if size<4 else val&0xFFFFFFFF
        # for sub-long, keep upper bits noise to confirm they're preserved
        if size<4: regs["D2"]=0x55550000 | (val & ((1<<(8*size))-1))
        return []
    if ea.role=="an":
        regs["A2"]=val & 0xFFFFFFFF
        return []
    if ea.role=="imm":
        if size==4: return [(val>>16)&0xFFFF, val&0xFFFF]
        return [val & 0xFFFF if size==2 else val & 0xFF]
    # memory
    b=opbytes(val,size)
    opndbuf[opnd_off:opnd_off+len(b)]=b
    if ea.mode==7 and ea.reg==1:    # (xxx).L: absolute addr = OPND+opnd_off (honor the slot,
        addr=OPND+opnd_off          # else src/dst both alias $F03800 in MOVE mem->mem cases)
        return [(addr>>16)&0xFFFF, addr&0xFFFF]
    if ea.mode==4:    regs["A0"]=OPND+opnd_off+size   # -(An): starts past operand
    else:             regs["A0"]=OPND+opnd_off
    if ea.mode==6:    regs.setdefault("A3",0)
    return ea.ext(size)

SIZE_CODE={1:0,2:1,4:2}   # standard size field for most ops (00=B,01=W,10=L)
SIZE_NAME={1:"B",2:"W",4:"L"}

# ---------------------------------------------------------------------------
# Cell = (family, size, mode_name) -> list of Shots (vectors) + ccr_mask + check_opnd
class Cell:
    def __init__(self, fam, size, modename, shots, ccr_mask=0x1F, check_opnd=True, note=""):
        self.fam=fam; self.size=size; self.modename=modename
        self.shots=shots; self.ccr_mask=ccr_mask; self.check_opnd=check_opnd; self.note=note
    @property
    def key(self): return f"{self.fam}.{SIZE_NAME[self.size]}"

def mkvec(regs, ccr, opndbuf):
    return Vec(dict(regs), ccr, bytes(opndbuf))

# Representative operand value pairs per size (normal, sign/edge).
def vals(size):
    if size==1: return [(0x3C,0x0F),(0x80,0xFF)]
    if size==2: return [(0x1234,0x0F0F),(0x8000,0xFFFF)]
    return [(0x12345678,0x0F0F0F0F),(0x80000000,0xFFFFFFFF)]

# Build shots for a binary op with EA as one operand and D0 as the other.
def binop_cells(cells, fam, base, sizes, dir, ea_modes,
                d_field=0, ccr_mask=0x1F, an_ok=False, dn_ok=True):
    """dir 0: <ea>,D0  (D0 = base|(d_field<<9)|(dir<<8)|(size<<6)|ea ; EA source)
       dir 1: D0,<ea>  (EA dest, RMW for memory)"""
    for size in sizes:
        for mn in ea_modes:
            ea=EA_BYNAME[mn]
            if ea.role=="an" and (size==1 or not an_ok): continue
            if ea.role=="reg" and not dn_ok: continue
            if ea.role=="imm" and dir==1: continue           # imm can't be dest
            shots=[]
            for eav,d0 in vals(size):
                regs={}; opnd=bytearray(16)
                ext=apply_ea(ea, eav, size, regs, opnd)
                regs["D0"]= d0 if size==4 else (0x77770000|(d0 & ((1<<(8*size))-1)))
                opw=[base|(d_field<<9)|(dir<<8)|(SIZE_CODE[size]<<6)|ea.bits()]+ext
                shots.append(Shot(opw, 2+2*len(ext), mkvec(regs, ccr_bits(x=1), opnd)))
            cells.append(Cell(fam, size, mn, shots, ccr_mask,
                              check_opnd=(ea.role=="mem")))

# Unary RMW op: op <ea> (CLR/NEG/NEGX/NOT/TST).
def unop_cells(cells, fam, base, sizes, ea_modes, ccr_mask=0x1F, dn_ok=True):
    for size in sizes:
        for mn in ea_modes:
            ea=EA_BYNAME[mn]
            if ea.role in ("an","imm"): continue
            if ea.role=="reg" and not dn_ok: continue
            shots=[]
            for eav,_ in vals(size):
                regs={}; opnd=bytearray(16)
                ext=apply_ea(ea, eav, size, regs, opnd)
                opw=[base|(SIZE_CODE[size]<<6)|ea.bits()]+ext
                shots.append(Shot(opw, 2+2*len(ext), mkvec(regs, ccr_bits(x=1), opnd)))
            cells.append(Cell(fam, size, mn, shots, ccr_mask,
                              check_opnd=(ea.role=="mem")))

def all_modes(): return COLS
def mem_modes(): return ["(An)","(An)+","-(An)","(d16,An)","(d8,An,Xn)","(xxx).L"]
def src_modes(): return COLS                      # incl #imm
def dst_modes(): return ["Dn","(An)","(An)+","-(An)","(d16,An)","(d8,An,Xn)","(xxx).L"]

# ===========================================================================
def generate():
    cells=[]
    # ---- ALU <ea>,Dn (dir0): ADD/SUB/AND/OR/CMP ; and Dn,<ea> (dir1): ADD/SUB/AND/OR/EOR
    binop_cells(cells,"ADD",0xD000,[1,2,4],0,src_modes(), an_ok=True)
    binop_cells(cells,"ADD",0xD000,[1,2,4],1,dst_modes(), dn_ok=False)   # dir1: ea-dst only mem/Dn (Dn dir1 invalid->skip via dn_ok)
    binop_cells(cells,"SUB",0x9000,[1,2,4],0,src_modes(), an_ok=True)
    binop_cells(cells,"SUB",0x9000,[1,2,4],1,dst_modes(), dn_ok=False)
    binop_cells(cells,"AND",0xC000,[1,2,4],0,src_modes())               # AND no An src
    binop_cells(cells,"AND",0xC000,[1,2,4],1,dst_modes(), dn_ok=False)
    binop_cells(cells,"OR", 0x8000,[1,2,4],0,src_modes())
    binop_cells(cells,"OR", 0x8000,[1,2,4],1,dst_modes(), dn_ok=False)
    binop_cells(cells,"CMP",0xB000,[1,2,4],0,src_modes(), an_ok=True)   # CMP is dir0 only
    binop_cells(cells,"EOR",0xB000,[1,2,4],1,dst_modes(), dn_ok=True)   # EOR is dir1 only (Dn dst ok)
    # ---- ADDQ/SUBQ #3,<ea> (incl An for W/L) — RMW memory + register
    for fam,base in (("ADDQ",0x5000),("SUBQ",0x5100)):
        for size in (1,2,4):
            for mn in dst_modes()+["An"]:
                ea=EA_BYNAME[mn]
                if ea.role=="an" and size==1: continue
                shots=[]
                for eav,_ in vals(size):
                    regs={}; opnd=bytearray(16)
                    ext=apply_ea(ea, eav, size, regs, opnd)
                    opw=[base|(3<<9)|(SIZE_CODE[size]<<6)|ea.bits()]+ext
                    # ADDQ/SUBQ to An is always long & sets no flags
                    cm=0x1F if ea.role!="an" else 0x00
                    shots.append(Shot(opw, 2+2*len(ext), mkvec(regs, ccr_bits(x=1), opnd)))
                cells.append(Cell(fam,size,mn,shots,
                    ccr_mask=(0x00 if ea.role=="an" else 0x1F),
                    check_opnd=(ea.role=="mem")))
    # ---- immediate ALU: ADDI/SUBI/ANDI/ORI/EORI/CMPI #imm,<ea>
    for fam,base in (("ADDI",0x0600),("SUBI",0x0400),("ANDI",0x0200),
                     ("ORI",0x0000),("EORI",0x0A00),("CMPI",0x0C00)):
        for size in (1,2,4):
            for mn in dst_modes():
                ea=EA_BYNAME[mn]
                shots=[]
                for eav,imm in vals(size):
                    regs={}; opnd=bytearray(16)
                    ext=apply_ea(ea, eav, size, regs, opnd)
                    immext=[(imm>>16)&0xFFFF, imm&0xFFFF] if size==4 else [imm & (0xFFFF if size==2 else 0xFF)]
                    opw=[base|(SIZE_CODE[size]<<6)|ea.bits()]+immext+ext
                    shots.append(Shot(opw, 2+2*len(immext)+2*len(ext), mkvec(regs, ccr_bits(x=1), opnd)))
                cells.append(Cell(fam,size,mn,shots,check_opnd=(ea.role=="mem")))
    # ---- CLR/NEG/NEGX/NOT/TST <ea>
    unop_cells(cells,"CLR",0x4200,[1,2,4],dst_modes())
    unop_cells(cells,"NEG",0x4400,[1,2,4],dst_modes())
    unop_cells(cells,"NEGX",0x4000,[1,2,4],dst_modes())
    unop_cells(cells,"NOT",0x4600,[1,2,4],dst_modes())
    unop_cells(cells,"TST",0x4A00,[1,2,4],dst_modes())
    # ---- bit ops: static #n and dynamic Dn ; type 0=BTST 1=BCHG 2=BCLR 3=BSET
    for typ,nm in ((0,"BTST"),(1,"BCHG"),(2,"BCLR"),(3,"BSET")):
        # static #n : 0000 1000 tt mmmrrr , ext = bitnum
        for mn in dst_modes():
            ea=EA_BYNAME[mn]
            size = 4 if ea.role=="reg" else 1
            if nm=="BTST" and ea.role!="reg" and mn in ("Dn",): pass
            shots=[]
            for eav,_ in (vals(size)):
                regs={}; opnd=bytearray(16)
                ext=apply_ea(ea, eav, size, regs, opnd)
                bitnum = 31 if ea.role=="reg" else 7
                opw=[0x0800|(typ<<6)|ea.bits(), bitnum]+ext
                shots.append(Shot(opw, 4+2*len(ext), mkvec(regs, ccr_bits(x=1,n=1,v=1,c=1), opnd)))
            cells.append(Cell(f"{nm}#n",size,mn,shots,
                check_opnd=(ea.role=="mem")))
        # dynamic Dn (bit number in D1) : 0000 dn1 tt mmmrrr
        for mn in dst_modes():
            ea=EA_BYNAME[mn]
            size = 4 if ea.role=="reg" else 1
            shots=[]
            for eav,_ in vals(size):
                regs={"D1": (5 if ea.role!="reg" else 20)}; opnd=bytearray(16)
                ext=apply_ea(ea, eav, size, regs, opnd)
                opw=[0x0100|(1<<9)|(typ<<6)|ea.bits()]+ext
                shots.append(Shot(opw, 2+2*len(ext), mkvec(regs, ccr_bits(x=1,n=1,v=1,c=1), opnd)))
            cells.append(Cell(f"{nm}Dn",size,mn,shots,
                check_opnd=(ea.role=="mem")))
    # ---- shifts/rotates, MEMORY form (1-bit, word): 1110 ttt d 11 mmmrrr
    for typ,nm in ((0,"ASx"),(1,"LSx"),(2,"ROXx"),(3,"ROx")):
        for d in (0,1):
            fam=f"{nm}{'L' if d else 'R'}.mem"
            for mn in mem_modes():
                ea=EA_BYNAME[mn]
                shots=[]
                for eav,_ in vals(2):
                    regs={}; opnd=bytearray(16)
                    ext=apply_ea(ea, eav, 2, regs, opnd)
                    opw=[0xE0C0|(typ<<9)|(d<<8)|ea.bits()]+ext
                    shots.append(Shot(opw, 2+2*len(ext), mkvec(regs, ccr_bits(x=1), opnd)))
                cells.append(Cell(fam,2,mn,shots,check_opnd=True))
    # ---- MOVE.B/W/L <src>,<dst>  (the big src×dst matrix). dst as a "mode column".
    for size in (1,2,4):
        szf={1:1,2:3,4:2}[size]   # MOVE size field: 01=B,11=W,10=L
        for smn in src_modes():
            sea=EA_BYNAME[smn]
            if size==1 and sea.role=="an": continue
            for dmn in dst_modes():
                dea=EA_BYNAME[dmn]
                if size==1 and dea.role=="an": continue
                shots=[]
                for sval,_ in vals(size):
                    regs={}; opnd=bytearray(16)
                    sext=apply_ea(sea, sval, size, regs, opnd, opnd_off=0)
                    # dest memory uses a SEPARATE operand slot at OPND+8 to avoid clobber
                    if dea.role=="mem":
                        dummy={}
                        dext=apply_ea(dea, 0, size, dummy, opnd, opnd_off=8)
                        if dea.mode==4: regs["A1"]=OPND+8+size
                        else: regs["A1"]=OPND+8
                        if dea.mode==6: regs["A3"]=0
                        dbits=ea_bits(dea.mode, 1 if dea.mode<7 else dea.reg)  # dest An=A1
                    else:
                        dext=[]
                        dbits=ea_bits(dea.mode, 0 if dea.role=="reg" else dea.reg)  # dest D0
                    # MOVE encoding: 00 ss DDDMMM mmmRRR  (dest mode/reg are bits 8-6/11-9)
                    dst_reg = (1 if dea.role=="mem" and dea.mode<7 else (0 if dea.role=="reg" else dea.reg))
                    opw=[ (szf<<12)|(dst_reg<<9)|(dea.mode<<6)|sea.bits() ] + sext + dext
                    shots.append(Shot(opw, 2+2*len(sext)+2*len(dext),
                                      mkvec(regs, ccr_bits(x=1), opnd)))
                cells.append(Cell(f"MOVE.{SIZE_NAME[size]}:{smn}",size,dmn,shots,
                    check_opnd=(dea.role=="mem")))
    return cells

# ===========================================================================
def main():
    flt=os.environ.get("SWEEP_FILTER")
    cells=generate()
    if flt:
        cells=[c for c in cells if flt.lower() in (c.fam+c.modename).lower()]
    # flatten to shots
    shots=[]; spans=[]
    for c in cells:
        spans.append((len(shots), len(shots)+len(c.shots), c))
        shots.extend(c.shots)
    nchunks=(len(shots)+MAX_SLOTS-1)//MAX_SLOTS
    print(f"sweep: {len(cells)} cells, {len(shots)} shots, {nchunks} chunk(s) "
          f"(<= {MAX_SLOTS} slots each)", flush=True)
    mame=[]; interp=[]
    for ci in range(nchunks):
        chunk=shots[ci*MAX_SLOTS:(ci+1)*MAX_SLOTS]
        if nchunks>1: print(f"  chunk {ci+1}/{nchunks}: {len(chunk)} shots", flush=True)
        mame.extend(mame_run_shots(chunk))
        interp.extend(interp_run_shots(chunk))   # re-bakes chunk into slots 0..
    # evaluate per cell
    results={}   # (fam,size) -> {modename: status}
    fams_order=[]; failing=[]
    for (lo,hi,c) in spans:
        cellfail=None
        for j in range(lo,hi):
            r=diff_shot(shots[j], mame[j], interp[j], c.ccr_mask, c.check_opnd)
            if r:
                cellfail=r; break
        status = "ok" if cellfail is None else "FAIL"
        key=c.fam if c.size is None else f"{c.fam}.{SIZE_NAME[c.size]}"
        if key not in results: results[key]={}; fams_order.append(key)
        results[key][c.modename]=("ok" if cellfail is None else "X")
        if cellfail:
            failing.append((key, c.modename, cellfail))
    # ---- coverage matrix
    print("\n===== COVERAGE MATRIX (op.size × EA-mode)  [.]=ok [X]=FAIL [ ]=n/a =====")
    hdr="%-16s "%"" + " ".join("%-10s"%m for m in COLS)
    print(hdr)
    for key in fams_order:
        row=results[key]
        cells_s=" ".join("%-10s"%({"ok":".","X":"X"}.get(row.get(m),"")) for m in COLS)
        print("%-16s %s"%(key, cells_s))
    # ---- failing cells
    print(f"\n===== FAILING CELLS ({len(failing)}) =====")
    for key,mn,why in failing:
        print(f"  {key:16s} {mn:12s} {why}")
    nok=sum(1 for (lo,hi,c) in spans
            if all(not diff_shot(shots[j],mame[j],interp[j],c.ccr_mask,c.check_opnd)
                   for j in range(lo,hi)))
    print(f"\n{nok}/{len(cells)} cells pass")
    sys.exit(0 if not failing else 1)

if __name__=="__main__":
    main()
