#!/usr/bin/env python3
"""68000 -> SA-1 (65816) transpiler. Emits a native escape (entry_<addr>) for a 68K function,
operating on the interpreter's DP reg file (D2) so it is call-bridge compatible. Codegen rules:
TRANSPILER_DESIGN.md (D1 flags/branches, D2 reg file, D3 endian, D4 map), CALL_BRIDGE_DESIGN.md.
Reference oracles: the hand-written, MAME-validated entry_ce4 ($000CE4) / entry_111a ($00111A).

Model (reg-file-faithful): the jsr hook enters with the return-push SKIPPED and PC already =
the caller's return. We re-simulate that 4-byte push at entry so the frame (link/movem/a6-rel
args) matches the real 68K exactly, transpile every instruction onto the REAL reg file $00-$3C
(incl. link/movem/unlk and the terminal rts), and `jmp inext`. movem.w sign-extension, the final
d7, and a7 all fall out of faithful transpilation -> bit-exact with MAME, leaf or (later) non-leaf.

Signed compares use `sec;sbc` (sets V correctly) -> the signed-branch idiom (N==V / N!=V) is
fully general (the hand oracle's `cmp`-based idiom relied on no-overflow). Memory reads route via
rdw40 for frame pointers (a6/a7, always work RAM) and rdw_ea (ROM/IO/work-RAM-aware) otherwise.

Usage: tools/transpile.py <hex-entry>          # e.g. tools/transpile.py 000CE4
Fail-loud: any unhandled op/mode/out-of-fn branch/indirect/IO -> raise (never emit wrong code).
"""
import sys, re
import capstone

ROM = open('build/interp.sfc', 'rb').read()
IMG = 0x10000                                  # 68K ROM at file offset $10000
MD = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)

# per-function lockstep hit counter (TRANSPILER_TOOL_SCOPE) ; add a slot per new target
COUNTERS = {0x000CE4: 0x0724, 0x00111A: 0x0726, 0x0013BE: 0x0730, 0x025110: 0x072A, 0x0020E8: 0x072C}

class Unsupported(Exception): pass

# ---- D2 reg file (direct page): Dn @ $00+4n, An @ $20+4n. lo16@+0, hi16@+2 ----
def reg_dp(name):
    m = re.fullmatch(r'd([0-7])', name)
    if m: return 0x00 + 4*int(m.group(1))
    m = re.fullmatch(r'a([0-7])', name)
    if m: return 0x20 + 4*int(m.group(1))
    if name == 'sp': return 0x3C                # a7 alias
    raise Unsupported('reg %r' % name)
TMP = 0x9E                                      # transpiler compare/store scratch (avoids rdw_ea $90)
VIDEO = False                                   # --video: route non-frame stores via writeword/writebyte
                                                # (IO-aware: video $B0/$D0/$E0 -> $41 shadow). For $002xxx.
BANK2 = False                                   # --bank2: body lives in the 2nd escape bank ($94:8000,
                                                # file $2A0000). ibridge ($92) is unreachable + its $00FE
                                                # resume lands in $92, so INLINE the interpret-bridge with
                                                # a $00FD sentinel (ors_pre -> ors_94chk -> bank $94).
ESCAPED = set()                                 # --escapes=hex,..: callee addrs with an ESCBANK escape;
                                                # gen_call dispatches a bridge-TO-escape (run native) to them

# ---- EA parse: capstone op_str token -> structured operand ----
def parse_ea(tok, pc=None):
    t = tok.strip()
    if re.fullmatch(r'd[0-7]', t): return ('Dn', t)
    if re.fullmatch(r'a[0-7]|sp', t): return ('An', 'a7' if t == 'sp' else t)
    m = re.fullmatch(r'\(a([0-7])\)\+', t)
    if m: return ('(An)+', 'a'+m.group(1))
    m = re.fullmatch(r'-\(a([0-7])\)', t)
    if m: return ('-(An)', 'a'+m.group(1))
    m = re.fullmatch(r'\(a([0-7])\)', t)
    if m: return ('(An)', 'a'+m.group(1))
    m = re.fullmatch(r'-\$([0-9a-f]+)\(a([0-7])\)', t)        # capstone neg disp: -$60(a3)
    if m: return ('(d16,An)', -int(m.group(1), 16), 'a'+m.group(2))
    m = re.fullmatch(r'\$(-?[0-9a-f]+)\(a([0-7])\)', t)
    if m: return ('(d16,An)', s16(int(m.group(1), 16)), 'a'+m.group(2))
    m = re.fullmatch(r'\$([0-9a-f]+)\(pc\)', t)
    if m: return ('abs', int(m.group(1), 16))   # capstone already RESOLVED pc+disp -> absolute address
    m = re.fullmatch(r'#\$?(-?[0-9a-f]+)', t)
    if m: return ('imm', int(t[1:].replace('$', '0x'), 0) & 0xFFFFFFFF)
    m = re.fullmatch(r'\$([0-9a-f]+)\.[lw]', t)             # absolute long/short ($XXXXXX.l)
    if m: return ('abs', int(m.group(1), 16))
    m = re.fullmatch(r'\$([0-9a-f]+)', t)
    if m: return ('abs', int(m.group(1), 16))
    raise Unsupported('EA %r' % tok)

def s16(v): return v - 0x10000 if v & 0x8000 else v
def imm16(v): return '#$%04X' % (v & 0xFFFF)
def hx(v): return '$%04X' % (v & 0xFFFF)

# ---- decode the function: entry -> rts, collect intra-fn branch targets as labels ----
def _dis1(a):
    ins = next(MD.disasm(ROM[IMG+a:IMG+a+8], a), None)
    if ins is None: raise Unsupported('decode stalled @ $%06X' % a)
    return ins

def decode(entry):
    # Phase 1: linear decode to the FIRST rts.
    insns, addr, targets = [], entry, set()
    while True:
        ins = _dis1(addr); insns.append(ins); addr = ins.address + ins.size
        base = ins.mnemonic.split('.')[0]
        btgt = None
        if base in BCC or base in ('bra', 'dbra', 'dbf'):
            m = re.search(r'\$([0-9a-f]+)$', ins.op_str)
            if m:
                btgt = int(m.group(1), 16)
                if entry <= btgt < entry + 0x2000: targets.add(btgt)
        if ins.mnemonic == 'rts': break
        # a coroutine yield is `trap #5` (inline, e.g. $4542's at $455C) OR an unconditional `bra` BACK
        # to a trap #5 (target < entry, e.g. $C2F8's bra $c2f6). Both end the body (multi-exit guard).
        # gen emits the trap as a tail-jump to itself and the bra as a tail-jump -> interp runs the trap.
        if base == 'trap' and addr not in targets: break
        if base == 'bra' and btgt is not None and btgt < entry and addr not in targets: break
        if base == 'jmp' and addr not in targets: break  # jmp(An) state-dispatch / jmp abs tail-jump: ends the body
        if addr - entry > 0x2000: raise Unsupported('no rts within 0x2000 from $%06X' % entry)
    end = addr
    # Phase 2: absorb MULTI-EXIT fragments -- a STRAIGHT-LINE block (data ops only, ending in rts)
    # sitting right after `end` that the body branches to (e.g. $3e88's clr.b+rts exit at $3ea6,
    # $3c36's bclr C-Chip exit at $3e20). A fragment containing ANY control flow is a separate
    # function (a distant tail-jump like beq $3ed0 that happens to be contiguous) -> left a stub.
    while end in targets:
        frag, a = [], end
        while True:
            f = _dis1(a); a += f.size; fb = f.mnemonic.split('.')[0]
            if f.mnemonic == 'rts': frag.append(f); break
            if fb in CTRLFLOW or a - end > 0x40: frag = None; break   # not a simple exit fragment
            frag.append(f)
        if frag is None: break
        insns.extend(frag); end = a
    labels = set()
    for ins in insns:
        base = ins.mnemonic.split('.')[0]
        if base in BCC or base in ('bra', 'dbra', 'dbf'):
            m = re.search(r'\$([0-9a-f]+)$', ins.op_str)
            if m:
                t = int(m.group(1), 16)
                if not (entry <= t < end):
                    # out-of-function target -> a TAIL-JUMP (set PC=t, jmp inext, interpreter takes
                    # over there; our re-pushed return brings control back to OUR caller on its rts).
                    # Works for an unconditional bra (e.g. GAME_TICK's `bra $2e6a`) AND a conditional
                    # branch out (e.g. $3C36's `bhi $3c34` to a spin) -> gen/emit_branch routes the
                    # taken path through a per-target tail-jump stub (emitted after the body). Don't
                    # add to intra-fn labels.
                    continue
                labels.add(t)
    return insns, (labels, entry, end)

# ---- emit buffer + fresh local labels ----
class Emit:
    def __init__(self, pfx=''): self.lines = []; self.n = 0; self.brn = 0; self.pfx = pfx
    def __call__(self, s): self.lines.append('    ' + s)
    def lbl(self, s): self.lines.append(s + ':')
    def cmt(self, s): self.lines.append('    ; ' + s)
    def fresh(self): self.n += 1; return 'Lf%s_%d' % (self.pfx, self.n)  # NB: no leading '_' —
    # Poppy treats leading-underscore labels as local/anonymous and MIS-RESOLVES their forward
    # short branches (bvs/bpl/bra) to a backward address -> infinite loops. Global-style names
    # (like the working hand-written entry_ce4 'ce_*' labels) resolve correctly.
    def L(self, addr): return 'L%s_%x' % (self.pfx, addr)         # per-function branch label

BCC = {'beq', 'bne', 'bmi', 'bpl', 'bge', 'blt', 'ble', 'bgt', 'bcc', 'bcs',
       'bhi', 'bls', 'bvs', 'bvc'}
CTRLFLOW = BCC | {'bra', 'dbra', 'dbf', 'bsr', 'jsr', 'jmp', 'rte', 'rtr'}  # not straight-line (exit-frag reject)

# ===================== memory address helpers =====================
def is_frame(an): return an in ('a6', 'a7')

# EA-SPECIALIZATION (cycle lever, ~14-100x/access vs the generic rdw_ea/readbyte helpers): registers
# that PROVABLY point at work RAM use the fast rdw40/wrw40 ($40-direct) path instead of the ROM/IO/
# bank-aware helpers. a5 = the global state base ($F00000, set at boot, never ROM/video) -> the whole
# a5-relative game-state/scheduler/coroutine access pattern goes fast. a6/a7 = frame pointers (already
# fast). WORKRAM adds escape-specific registers the caller asserts are work RAM (--workram=a0,a1, from
# the captured entry regs). NOTE: only ever WIDEN this when the register cannot be ROM (reads) -- stores
# already assume work-RAM-or-video, and RMW already assumes work RAM (writable). Validate bit-exact.
WORKRAM = set()                                  # --workram=<csv>: extra provably-work-RAM An regs
def is_workram(an): return an in ('a5', 'a6', 'a7') or an in WORKRAM

def hi_ext(disp): return '#$FFFF' if disp < 0 else '#$0000'   # sign-extend a 16-bit disp into hi16

def ea_setup_romaware(e, an, disp):
    """set $52(hi16)/$54(lo16) = An + disp (signed)."""
    dp = reg_dp(an)
    e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('sta $54')
    e('lda $%02X' % (dp+2)); e('adc %s' % hi_ext(disp)); e('sta $52')

def ea_load_A(e, ea, size):
    """value (size .w/.b -> 16/8 in A) -> A. .b returns byte in A.lo (hi indeterminate)."""
    kind = ea[0]
    if kind == 'Dn':
        e('lda $%02X' % reg_dp(ea[1])); return
    if kind == 'An':
        e('lda $%02X' % reg_dp(ea[1])); return
    if kind == 'imm':
        if ea[1] is None: raise Unsupported('PC-relative immediate')
        e('lda %s' % imm16(ea[1])); return
    if kind in ('(An)', '(An)+', '(d16,An)'):
        an = ea[-1]; disp = ea[1] if kind == '(d16,An)' else 0
        if is_workram(an):                                       # provably work RAM -> fast $40-direct
            dp = reg_dp(an)
            e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('tax')
            e('jsr rdb40' if size == 'b' else 'jsr rdw40')
        else:
            ea_setup_romaware(e, an, disp)
            e('jsr readbyte' if size == 'b' else 'jsr rdw_ea')   # readbyte = ROM-aware byte
        if kind == '(An)+':                 # bump clobbers A -> preserve the loaded value
            e('pha'); bump_an(e, an, 1 if size == 'b' else 2); e('pla')
        return
    if kind == 'abs':
        e('lda #%s' % hx(ea[1] & 0xFFFF)); e('sta $54')
        e('lda #%s' % hx((ea[1] >> 16) & 0xFFFF)); e('sta $52')
        e('jsr readbyte' if size == 'b' else 'jsr rdw_ea'); return
    raise Unsupported('load EA %r' % (ea,))

def bump_an(e, an, n):
    dp = reg_dp(an)
    e('lda $%02X' % dp); e('clc'); e('adc #$%04X' % n); e('sta $%02X' % dp)
    e('lda $%02X' % (dp+2)); e('adc #$0000'); e('sta $%02X' % (dp+2))

def predec_an(e, an, n):
    dp = reg_dp(an)
    e('lda $%02X' % dp); e('sec'); e('sbc #$%04X' % n); e('sta $%02X' % dp)
    e('lda $%02X' % (dp+2)); e('sbc #$0000'); e('sta $%02X' % (dp+2))

def ea_rmw(e, ea, size, modify):
    """read-modify-write: address evaluated ONCE. modify(e) takes A=cur, leaves A=new and MUST
    NOT clobber X (no memory src). (An)+ increments once, after the write. dst is writable ->
    work RAM (rdw40/wrw40, same location for read+write); video-bank RMW is v1 out-of-scope."""
    kind = ea[0]
    rd, wr, step = ('rdb40', 'wrb40', 1) if size == 'b' else ('rdw40', 'wrw40', 2)
    if kind == 'Dn':
        dp = reg_dp(ea[1]); e('lda $%02X' % dp); modify(e); e('sta $%02X' % dp); return
    if kind in ('(An)', '(An)+', '(d16,An)'):
        # ea_rmw is WORD-ONLY for memory: a .l caller must split into two word RMWs itself (the logic
        # ops do; add.l/not.l to memory would need inter-word carry / two words and are not handled).
        if size == 'l': raise Unsupported('.l RMW to memory (caller must split into two words)')
        an = ea[-1]; disp = ea[1] if kind == '(d16,An)' else 0; dp = reg_dp(an)
        e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('tax')   # X = work-RAM offset
        e('jsr %s' % rd); modify(e); e('jsr %s' % wr)                        # X preserved across both
        if kind == '(An)+': bump_an(e, an, step)
        return
    raise Unsupported('RMW EA %r' % (ea,))

def ea_addr_to_X(e, ea):
    """set X = the work-RAM offset of a memory EA (no read). For sub-to-memory writeback."""
    kind = ea[0]
    if kind in ('(An)', '(An)+', '(d16,An)'):
        an = ea[-1]; disp = ea[1] if kind == '(d16,An)' else 0
        e('lda $%02X' % reg_dp(an)); e('clc'); e('adc %s' % imm16(disp)); e('tax'); return
    raise Unsupported('addr_to_X EA %r' % (ea,))

def ea_store_A_from(e, ea, size, load_value):
    """store: load_value(e) must leave the store value in A; dest given by ea (.w/.b)."""
    kind = ea[0]
    if kind == 'Dn':
        load_value(e)
        if size == 'b':
            e('sep #$20'); e('sta $%02X' % reg_dp(ea[1])); e('rep #$20')   # .b touches lo8 only
        else:
            e('sta $%02X' % reg_dp(ea[1]))                                 # .w touches lo16 only
        return
    if kind == '-(An)':                                      # predecrement store (push / buffer write)
        an = ea[-1]; dp = reg_dp(an)
        if size == 'b':                                      # byte: predec 1, write low8 via wrb40
            load_value(e); e('pha'); predec_an(e, an, 1)
            e('lda $%02X' % dp); e('tax'); e('pla'); e('jsr wrb40')
            return
        if size != 'w': raise Unsupported('-(An) store size %s' % size)
        load_value(e); e('pha'); predec_an(e, an, 2)
        e('lda $%02X' % dp); e('tax'); e('pla'); e('jsr wrw40')
        return
    if kind in ('(An)', '(An)+', '(d16,An)'):
        an = ea[-1]; disp = ea[1] if kind == '(d16,An)' else 0; dp = reg_dp(an)
        if VIDEO and not is_workram(an):                         # work-RAM regs (a5/a6/a7/--workram) -> fast wrw40, skip video routing
            # IO-aware store: writeword/writebyte route video $B0/$D0/$E0 -> $41 shadow, $F0 -> $40.
            # in: $52=An.hi16, $54=An.lo16+disp, $80=value (lo/$80, hi/$81). value MUST be in $80 first.
            load_value(e)
            if size == 'b': e('sep #$20'); e('sta $80'); e('rep #$20')
            else: e('sta $80')
            e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('sta $54')
            e('lda $%02X' % (dp+2)); e('adc %s' % hi_ext(disp)); e('sta $52')
            e('jsr writebyte' if size == 'b' else 'jsr writeword')
        else:
            load_value(e); e('pha')                          # value first (may clobber X via mem read)
            e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('tax')   # X = dest offset
            e('pla'); e('jsr wrb40' if size == 'b' else 'jsr wrw40')             # work-RAM byte/word
        if kind == '(An)+': bump_an(e, an, 1 if size == 'b' else 2)
        return
    if kind == 'abs':                                    # absolute store -> I/O-aware writebyte/writeword
        load_value(e)                                    # ($F0->$40, $80/$90 I/O, $B0/$D0/$E0->$41)
        if size == 'b': e('sep #$20'); e('sta $80'); e('rep #$20')
        else: e('sta $80')
        e('lda #%s' % hx(ea[1] & 0xFFFF)); e('sta $54')
        e('lda #%s' % hx((ea[1] >> 16) & 0xFFFF)); e('sta $52')
        e('jsr writebyte' if size == 'b' else 'jsr writeword')
        return
    raise Unsupported('store EA %r' % (ea,))

# ===================== branch idiom =====================
def branch_label(e, tgt):
    """Resolve a conditional-branch target to a local jmp label. In-function -> the normal per-fn
    label (placed in the main loop). Out-of-function -> register a TAIL-JUMP stub (emitted after the
    body by emit_tailjump_stubs) and return its label; the stub sets PC=tgt and jmp inext so the
    interpreter takes over there (matches the real 68K, e.g. $3C36's bhi -> $3c34 spin)."""
    if getattr(e, 'entry', None) is None or (e.entry <= tgt < e.end):
        return e.L(tgt)
    e.tailjumps.add(tgt)
    return 'Ltj%s_%x' % (e.pfx, tgt)

def emit_tailjump_stubs(e):
    """Emit the out-of-function tail-jump stubs collected by branch_label. Placed after the body
    (only reached via jmp): set 68K PC=tgt and jmp inext. bank1_transform -> jml.l inext."""
    for tgt in sorted(getattr(e, 'tailjumps', ())):
        e.lbl('Ltj%s_%x' % (e.pfx, tgt))
        e('lda %s' % imm16(tgt & 0xFFFF)); e('sta $40')
        e('lda %s' % imm16((tgt >> 16) & 0xFFFF)); e('sta $42')
        e('jmp inext')

def emit_ccr_native(e, fsrc):
    """Materialize the 68K CCR MEMORY ($60=Z $6E=C $70=N $72=V $A2=X) that the interp-CALLER's
    op_bcc/op_beq read after this escape's rts, from the LIVE native 65816 flags. The transpiler
    otherwise only lowers branches to native flags -> the CCR memory is stale at a function boundary
    (D1 gap; trip1000 $104F). Called at a branch-to-EXIT edge (native flags = the fused op's, live).
    fsrc='signed' (sec;sbc = sub/cmp): Z/N/V native, C=!nativeC (68K borrow), X=C. (cmp X-untouched
    is a KNOWN GAP -- rare; X only matters to a following ADDX/SUBX/NEGX/ROXx.)
    fsrc='tst' (move/logic/tst = N,Z; V=0,C=0): Z/N native, V=0, C=0, X untouched. (add-reloaded-as-
    tst loses the add's real C -> also a known gap; the transpiler already can't feed C from an add.)
    Scratch $50 (dead at every escape exit; the epilogue reloads regs, never reads $50)."""
    e('php'); e('sep #$20'); e('pla'); e('rep #$30'); e('and #$00FF'); e('sta $50')
    e('and #$0002'); e('sta $60')                  # Z <- P.b1
    e('lda $50'); e('and #$0080'); e('sta $70')    # N <- P.b7
    if fsrc == 'signed':
        e('lda $50'); e('and #$0040'); e('sta $72')                 # V <- P.b6
        e('lda $50'); e('and #$0001'); e('eor #$0001')              # C <- !P.b0 (68K sub borrow)
        e('sta $6E'); e('sta $A2')                                  # X = C
    else:                                          # 'tst': move/logic/tst -> V=0, C=0, X untouched
        e('stz $72'); e('stz $6E')

def emit_ccr_from_value(e, val):
    """Materialize the 68K CCR (N,Z; V=0,C=0; X untouched) from a MOVE's result VALUE (not the native
    flags). Used at a dbra-loop fall-through to a function exit: 68K `dbra`/`dbf` PRESERVE the CCR, so
    the caller reads N/Z of the loop body's last moved value -- but (a) the transpiler's dbra emits
    `cmp #$FFFF` (corrupting the native flags) and (b) for move.l (An)+ the native flags are the
    pointer-bump's, not the moved value's. So compute N/Z from the value directly. `val` is
    (dp,size) [word@dp / long@dp,dp+2] or ('imm',const,size). Byte layout matches the pre-fix
    hand-materialization in entry_8fat/entry_fd2t. Scratch: A only."""
    kind = val[0]
    if kind == 'imm':
        _, c, sz = val
        n = (c >> (31 if sz == 'l' else 15)) & 1
        z = 1 if (c & (0xFFFFFFFF if sz == 'l' else 0xFFFF)) == 0 else 0
        e('lda #$%04X' % (0x8000 if n else 0)); e('sta $70')   # N
        e('stz $72'); e('stz $6E')                             # V=0, C=0
        e('lda #$%04X' % (1 if z else 0)); e('sta $60')        # Z (const)
        return
    dp, sz = val
    hi = dp + 2 if sz == 'l' else dp
    e('lda $%02X' % hi); e('and #$8000'); e('sta $70')         # N = bit(msb) of the moved value
    e('stz $72')                                                # V = 0
    e('stz $6E')                                                # C = 0
    e('stz $60')                                                # Z = 0 (assume nonzero)
    if sz == 'l': e('lda $%02X' % dp); e('ora $%02X' % (dp + 2))
    else: e('lda $%02X' % dp)
    s = e.fresh(); e('bne %s' % s); e('inc $60'); e.lbl(s)      # Z = 1 iff value == 0

def dbra_exit_ccr_val(prev):
    """The (dp,size)/('imm',..) whose N/Z the caller reads after a dbra loop whose body's last op is
    `prev` (a move). None if not determinable -> leave the CCR unmaterialized (the pre-existing
    behaviour; only matters if the caller branches on it, which is exactly the case this closes)."""
    if prev is None: return None
    b, sz = split_mn(prev)
    if b != 'move' or sz not in ('w', 'l'): return None
    ops = operands(prev)
    if len(ops) != 2: return None
    src, dst = ops
    if sz == 'l' and src[0] == '(An)+' and dst[0] == '(An)+': return (0x9A, 'l')  # gen_movel scratch
    if src[0] == 'Dn': return (reg_dp(src[1]), sz)                                 # move Dn,<mem>: value = Dn
    if src[0] == 'imm': return ('imm', src[1], sz)                                 # move #imm,<mem>
    return None

def _branch32(e, base, jmp, fsrc, low):
    """Emit a branch off a FULL 32-bit compare/tst. State on entry: processor N,V,C valid for the
    whole 32 bits, processor Z = (HIGH word == 0); `low` = DP ref of the LOW-word diff/value (for the
    full Z). `jmp()` emits the taken-branch; falls through when not taken. Every flag-branch precedes
    any `lda low` (which clobbers flags), so the processor flags stay live until they've been read."""
    tst = (fsrc == 'tst32')                        # tst32: V=0, C=0, N=bit31, Z=full
    if base == 'bra': jmp(); return
    if base == 'beq':                              # Z_full: hi==0 AND low==0
        s = e.fresh(); e('bne %s' % s); e('lda %s' % low); e('bne %s' % s); jmp(); e.lbl(s); return
    if base == 'bne':                              # !Z_full
        tk, s = e.fresh(), e.fresh()
        e('bne %s' % tk); e('lda %s' % low); e('beq %s' % s); e.lbl(tk); jmp(); e.lbl(s); return
    if base == 'bmi':                              # N = bit31 (valid in both)
        s = e.fresh(); e('bpl %s' % s); jmp(); e.lbl(s); return
    if base == 'bpl':
        s = e.fresh(); e('bmi %s' % s); jmp(); e.lbl(s); return
    if tst:
        if base == 'blt':                          # V=0 -> N!=V == N
            s = e.fresh(); e('bpl %s' % s); jmp(); e.lbl(s); return
        if base == 'bge':                          # V=0 -> N==V == !N
            s = e.fresh(); e('bmi %s' % s); jmp(); e.lbl(s); return
        if base == 'ble':                          # N OR Z_full
            tk, s = e.fresh(), e.fresh()
            e('bmi %s' % tk); e('bne %s' % s); e('lda %s' % low); e('bne %s' % s)
            e.lbl(tk); jmp(); e.lbl(s); return
        if base == 'bgt':                          # !N AND !Z_full
            tk, s = e.fresh(), e.fresh()
            e('bmi %s' % s); e('bne %s' % tk); e('lda %s' % low); e('bne %s' % tk); e('bra %s' % s)
            e.lbl(tk); jmp(); e.lbl(s); return
        raise Unsupported('tst32-fed branch %s' % base)
    # signed32: N,V,C valid (32-bit); Z_full via `low`.
    if base in ('bcc', 'bcs'):                     # 68K carry inverted vs sec;sbc -> same-name skip
        s = e.fresh(); e('%s %s' % (base, s)); jmp(); e.lbl(s); return
    if base == 'bhi':                              # C set (65816) AND !Z_full
        s, tk = e.fresh(), e.fresh()
        e('bcc %s' % s); e('bne %s' % tk); e('lda %s' % low); e('beq %s' % s)
        e.lbl(tk); jmp(); e.lbl(s); return
    if base == 'bls':                              # C clear OR Z_full
        tk, s = e.fresh(), e.fresh()
        e('bcc %s' % tk); e('bne %s' % s); e('lda %s' % low); e('bne %s' % s)
        e.lbl(tk); jmp(); e.lbl(s); return
    if base in ('blt', 'bge'):                     # N vs V only (no Z)
        v1, tk, s = e.fresh(), e.fresh(), e.fresh()
        if base == 'blt':                          # N!=V
            e('bvs %s' % v1); e('bmi %s' % tk); e('bra %s' % s)
            e.lbl(v1); e('bpl %s' % tk); e('bra %s' % s)
        else:                                      # bge: N==V
            e('bvs %s' % v1); e('bpl %s' % tk); e('bra %s' % s)
            e.lbl(v1); e('bmi %s' % tk); e('bra %s' % s)
        e.lbl(tk); jmp(); e.lbl(s); return
    if base == 'ble':                              # Z_full OR N!=V
        v1, tk, s = e.fresh(), e.fresh(), e.fresh()
        e('bvs %s' % v1); e('bmi %s' % tk); e('bne %s' % s)
        e('lda %s' % low); e('bne %s' % s); e('bra %s' % tk)
        e.lbl(v1); e('bpl %s' % tk); e('bra %s' % s)
        e.lbl(tk); jmp(); e.lbl(s); return
    if base == 'bgt':                              # !Z_full AND N==V
        v1, tk, s = e.fresh(), e.fresh(), e.fresh()
        e('bvs %s' % v1); e('bmi %s' % s); e('bne %s' % tk)
        e('lda %s' % low); e('bne %s' % tk); e('bra %s' % s)
        e.lbl(v1); e('bmi %s' % tk); e('bra %s' % s)
        e.lbl(tk); jmp(); e.lbl(s); return
    raise Unsupported('signed32-fed branch %s' % base)

def emit_branch(e, base, tgt, fsrc):
    """fsrc: 'signed'/'signed32' (N,V,Z,C from sec;sbc) | 'tst'/'tst32' (N,Z; V=0). The *32 variants
    come from a FULL 32-bit cmp/tst -> _branch32 (Z reconstructed). end: falls through if not taken."""
    L = branch_label(e, tgt)
    def jmp():
        if tgt in getattr(e, 'exit_addrs', ()):    # branch to the epilogue/rts: sync CCR for the caller
            emit_ccr_native(e, fsrc)
        e('jmp %s' % L)
    def over(short_skip_cc):                       # `cc _s ; jmp L ; _s:`  (cc skips the jmp)
        s = e.fresh(); e('%s %s' % (short_skip_cc, s)); jmp(); e.lbl(s)
    if fsrc in ('signed32', 'tst32'):
        if tgt in getattr(e, 'exit_addrs', ()):    # CCR-materialization for a .l cmp at a fn-exit edge
            raise Unsupported('.l cmp/tst branching to a function-exit epilogue (32-bit CCR-at-exit not modeled)')
        _branch32(e, base, jmp, fsrc, e._cmp32_low); return
    if base == 'bra': jmp(); return
    if base == 'beq': over('bne'); return
    if base == 'bne': over('beq'); return
    if base == 'bmi': over('bpl'); return
    if base == 'bpl': over('bmi'); return
    if base in ('bcs', 'bcc'):
        # 68K carry is INVERTED vs the 65816 sec;sbc carry (68K bcs = unsigned-below = dst<src =
        # 65816 C clear). over() takes the 68K branch when skip_cc is FALSE, so skip_cc must be the
        # COMPLEMENT of the 68K condition in 65816 flags -> that complement is the SAME mnemonic as
        # base (the carry-inversion and the skip-inversion cancel). e.g. 68K bcs: jmp when 65816 C
        # clear -> skip_cc='bcs' (skip when C set). Cross-checked vs op_bcc's $6E (true 68K carry).
        over(base); return
    # unsigned compares (only meaningful after a cmp's sec;sbc): 65816 C=1 => dst>=src, Z=1 => equal.
    if base == 'bhi':                              # dst>src unsigned: C set AND Z clear
        sk = e.fresh(); e('bcc %s' % sk); e('beq %s' % sk); jmp(); e.lbl(sk); return
    if base == 'bls':                              # dst<=src unsigned: C clear OR Z set
        tk, sk = e.fresh(), e.fresh()
        e('bcc %s' % tk); e('beq %s' % tk); e('bra %s' % sk); e.lbl(tk); jmp(); e.lbl(sk); return
    if fsrc == 'tst':                              # V==0: lt->mi, ge->pl
        if base == 'blt': over('bpl'); return
        if base == 'bge': over('bmi'); return
        if base == 'ble':                          # Z or N
            ov, sk = e.fresh(), e.fresh()
            e('beq %s' % ov); e('bmi %s' % ov); e('bra %s' % sk)
            e.lbl(ov); jmp(); e.lbl(sk); return
        if base == 'bgt':                          # !Z and !N
            sk = e.fresh(); e('beq %s' % sk); e('bmi %s' % sk); jmp(); e.lbl(sk); return
        raise Unsupported('tst-fed branch %s' % base)
    # fsrc == 'signed'
    ov, tk, sk = e.fresh(), e.fresh(), e.fresh()
    if base == 'blt':    # N!=V
        e('bvs %s' % ov); e('bmi %s' % tk); e('bra %s' % sk)
        e.lbl(ov); e('bpl %s' % tk); e('bra %s' % sk)
    elif base == 'bge':  # N==V
        e('bvs %s' % ov); e('bpl %s' % tk); e('bra %s' % sk)
        e.lbl(ov); e('bmi %s' % tk); e('bra %s' % sk)
    elif base == 'ble':  # Z or N!=V
        e('beq %s' % tk); e('bvs %s' % ov); e('bmi %s' % tk); e('bra %s' % sk)
        e.lbl(ov); e('bpl %s' % tk); e('bra %s' % sk)
    elif base == 'bgt':  # !Z and N==V
        e('beq %s' % sk); e('bvs %s' % ov); e('bpl %s' % tk); e('bra %s' % sk)
        e.lbl(ov); e('bmi %s' % tk); e('bra %s' % sk)
    else:
        raise Unsupported('signed-fed branch %s' % base)
    e.lbl(tk); jmp(); e.lbl(sk)

# ===================== per-instruction codegen =====================
def split_mn(ins):
    p = ins.mnemonic.split('.')
    return p[0], (p[1] if len(p) > 1 else None)

def operands(ins):
    return [parse_ea(x) for x in ins.op_str.split(',')] if ins.op_str else []

CMP32_LO = 0x8A     # scratch: low-word diff of a 32-bit compare (emit_branch 'signed32'/'tst32'
                    # reads it to reconstruct the FULL 32-bit Z; dead across the fused cmp->branch).
CMP32_PAIR = 0x9A   # scratch DP pair for a MEMORY .l operand (same slot gen_movel uses; transient).

def _ref32(e, ea, pair):
    """Materialize a 32-bit operand as (lo_ref, hi_ref) usable directly by `sbc`/`lda`.
    imm -> two #immediates; Dn/An -> its DP pair; memory -> load_long_to `pair`, return that pair.
    (pc-rel/abs .l operands are rejected -- add via load_long_to if they ever appear.)"""
    k = ea[0]
    if k == 'imm':
        if ea[1] is None: raise Unsupported('.l PC-relative immediate compare')
        return ('#'+hx(ea[1] & 0xFFFF), '#'+hx((ea[1] >> 16) & 0xFFFF))
    if k in ('Dn', 'An'):
        s = reg_dp(ea[1]); return ('$%02X' % s, '$%02X' % (s+2))
    if k in ('(An)', '(An)+', '(d16,An)'):
        load_long_to(e, ea, pair); return ('$%02X' % pair, '$%02X' % (pair+2))
    raise Unsupported('.l compare operand %r' % (ea,))

def emit_signed_cmp(e, dest_ea, src_ea, size, store_dp=None):
    """lda dest; sec; sbc src  (sets N,V,Z,C). if store_dp: sta dest (sub-family).
    size 'l': FULL 32-bit subtract -- two chained sbc's leave N,V,C valid for the whole 32 bits
    and processor Z = (HIGH word == 0); the low-word diff is saved (store_dp for sub.l, else CMP32_LO)
    so emit_branch('signed32') can rebuild the full Z. (ea_load_A is .w-only -- the historical bug was
    a single 16-bit sbc, so cmp/cmpi/cmpa/sub.l compared only the low word.)"""
    if size == 'l':
        # At most ONE operand is memory here (cmp/cmpa/sub.l dst is a reg; cmpi src is imm) -> one
        # scratch pair suffices. Load it (side effects like (An)+ happen once, in operand order).
        MEM = ('(An)', '(An)+', '(d16,An)')
        if src_ea[0] in MEM and dest_ea[0] in MEM:
            raise Unsupported('.l compare with two memory operands')
        slo, shi = _ref32(e, src_ea, CMP32_PAIR)
        dlo, dhi = _ref32(e, dest_ea, CMP32_PAIR)
        low = store_dp if store_dp is not None else CMP32_LO
        e('lda %s' % dlo); e('sec'); e('sbc %s' % slo); e('sta $%02X' % low)   # low diff (sta: no flag change)
        e('lda %s' % dhi); e('sbc %s' % shi)                                   # high diff: N,V,C 32-bit-valid; Z=(hi==0)
        if store_dp is not None: e('sta $%02X' % (store_dp+2))                 # sub.l: store the high result too
        e._cmp32_low = '$%02X' % low
        return
    k = src_ea[0]
    if k == 'imm':
        ea_load_A(e, dest_ea, size); e('sec'); e('sbc %s' % imm16(src_ea[1]))
    elif k in ('Dn', 'An'):
        ea_load_A(e, dest_ea, size); e('sec'); e('sbc $%02X' % reg_dp(src_ea[1]))
    else:                                   # memory src -> scratch first (clobbers A), then dest
        ea_load_A_to_tmp(e, src_ea, size)
        ea_load_A(e, dest_ea, size); e('sec'); e('sbc $%02X' % TMP)
    if store_dp is not None: e('sta $%02X' % store_dp)

def ea_load_A_to_tmp(e, ea, size):
    ea_load_A(e, ea, size); e('sta $%02X' % TMP)

def gen(e, ins, nxt):
    """emit one instruction; returns #instrs consumed (2 if it fuses the following branch)."""
    base, size = split_mn(ins)
    nb = split_mn(nxt)[0] if nxt is not None else None
    fuses = nb in BCC
    if base == 'movem':                              # reglist token isn't a normal EA
        return gen_movem(e, ins, size, None)
    if base in ('jsr', 'bsr'):                       # call operand ('$x.l'/'(an)') isn't a data EA
        return gen_call(e, ins)
    ops = operands(ins)

    # ---- frame / structural ----
    if base == 'link':
        an, disp = ops[0][1], ops[1][1]
        dp = reg_dp(an)
        e('lda $%02X' % dp); e('sta $54'); e('lda $%02X' % (dp+2)); e('sta $56'); e('jsr push32')
        e('lda $3C'); e('sta $%02X' % dp); e('lda $3E'); e('sta $%02X' % (dp+2))   # An = a7
        if disp:                                                                    # a7 += disp (signed)
            e('lda $3C'); e('clc'); e('adc %s' % imm16(disp)); e('sta $3C')
            e('lda $3E'); e('adc #$0000'); e('sta $3E')
        return 1
    if base == 'unlk':
        an = ops[0][1]; dp = reg_dp(an)
        e('lda $%02X' % dp); e('sta $3C'); e('lda $%02X' % (dp+2)); e('sta $3E')    # a7 = An
        e('ldx $3C'); e('jsr rdw40'); e('sta $%02X' % (dp+2))                       # An = [a7] hi
        e('inx'); e('inx'); e('jsr rdw40'); e('sta $%02X' % dp)                     # An = [a7] lo
        e('lda $3C'); e('clc'); e('adc #$0004'); e('sta $3C')                       # a7 += 4
        return 1
    if base == 'rts':
        # PC bank = [a7] bits 16-23, MASKED to a byte. 68K addresses are 24-bit; the stacked return's
        # top byte (bits 24-31) is undefined garbage. op_rts masks it (lda $400001,x; and #$00FF); we
        # MUST too, else a dirty top byte leaves $42 nonzero and xlat_dispatch's `bne xd_miss` rejects
        # a real bank-0 return -> the rts-class table dispatch silently misses (e.g. ce4t's rts to the
        # $13BE leaf never fired). See [[rts-dispatch-dirty-bank]] / task #78.
        e('ldx $3C'); e('jsr rdw40'); e('and #$00FF'); e('sta $42')   # PC bank = [a7] bits 16-23 (masked)
        e('inx'); e('inx'); e('jsr rdw40'); e('sta $40')# PC.lo16
        e('lda $3C'); e('clc'); e('adc #$0004'); e('sta $3C')
        # route the return through ors_pre (not inext): if the popped return bank is a CALL-BRIDGE
        # sentinel ($00FE bank-$92 / $00FF bank-$00) -> resume the bridging escape's continuation;
        # else ors_pre falls through to inext (normal 68K return). Enables bridge-TO-escape: a parent
        # escape can call this escape with a $00FE:cont sentinel return and be resumed natively.
        e('jmp ors_pre')
        return 1

    # ---- moves / address calc ----
    if base == 'move':
        src, dst = ops
        if size == 'l':                                  # full 32-bit move (ea_load/store are .w-only)
            gen_movel(e, src, dst)
            if fuses: raise Unsupported('move.l feeding branch')
            return 1
        ea_store_A_from(e, dst, size, lambda e: ea_load_A(e, src, size))
        if fuses:                                        # move sets N,Z (V cleared) -> reload + branch
            if dst[0] == 'Dn': e('lda $%02X' % reg_dp(dst[1]))
            elif dst[0] in ('(An)', '(d16,An)', 'abs'):  # re-readable w/o side effects: reload stored val
                ea_load_A(e, dst, size)                  # the just-stored value carries the move's N,Z
            else: raise Unsupported('move-to-mem feeding branch (non-reloadable dst %s)' % dst[0])
            emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'movea':
        src, dst = ops; dp = reg_dp(dst[1])
        if size == 'l':
            load_long_to(e, src, dp)
        else:                                            # movea.w sign-extends into 32-bit An
            ea_load_A(e, src, size); e('sta $%02X' % dp); sext_hi(e, dp)
        return 1
    if base == 'lea':
        src, dst = ops; dp = reg_dp(dst[1])
        if src[0] == '(d16,An)':
            s = reg_dp(src[2])
            e('lda $%02X' % s); e('clc'); e('adc %s' % imm16(src[1])); e('sta $%02X' % dp)
            e('lda $%02X' % (s+2)); e('adc #$0000'); e('sta $%02X' % (dp+2))
        elif src[0] == 'abs':
            e('lda #%s' % hx(src[1] & 0xFFFF)); e('sta $%02X' % dp)
            e('lda #%s' % hx((src[1] >> 16) & 0xFFFF)); e('sta $%02X' % (dp+2))
        elif src[0] == '(An)':                       # lea (An),Am = copy An (disp 0)
            s = reg_dp(src[1])
            e('lda $%02X' % s); e('sta $%02X' % dp)
            e('lda $%02X' % (s+2)); e('sta $%02X' % (dp+2))
        else:
            raise Unsupported('lea src %r' % (src,))
        return 1

    # ---- arithmetic / logic (.w) ----
    if base in ('add', 'addi', 'addq', 'adda', 'sub', 'subi', 'subq', 'suba'):
        return gen_addsub(e, base, size, ops, nxt, fuses, nb)
    if base in ('and', 'andi', 'or', 'ori', 'eor', 'eori'):
        src, dst = ops; opn = {'and': 'and', 'andi': 'and', 'or': 'ora', 'ori': 'ora',
                               'eor': 'eor', 'eori': 'eor'}[base]
        memsrc = src[0] in ('(An)', '(An)+', '(d16,An)', 'abs')
        # .l RMW to MEMORY = two independent word ops (ea_rmw is word-only). High word @ EA uses the
        # source's hi16, low word @ EA+2 uses its lo16 (68K big-endian). Was silently truncated to a
        # single word OR'd with the wrong half -> e.g. `or.l d0,$1b12(a5)` corrupted the dirty-palette
        # mask in entry_3a92 (caught by val_0708_diff). Logic ops have no inter-word carry, so safe.
        if size == 'l' and dst[0] in ('(An)', '(d16,An)'):
            if memsrc: raise Unsupported('logic.l mem-dst with memory src')
            an = dst[-1]; disp = dst[1] if dst[0] == '(d16,An)' else 0
            for woff, shalf in ((0, 2), (2, 0)):     # (word offset, src DP/imm half: 2=hi16, 0=lo16)
                if src[0] in ('Dn', 'An'): mk = (opn, '$%02X' % (reg_dp(src[1]) + shalf))
                elif src[0] == 'imm': mk = (opn, imm16((src[1] >> 16) if shalf else src[1]))
                else: raise Unsupported('logic.l mem-dst src %r' % (src,))
                ea_rmw(e, ('(d16,An)', disp + woff, an), 'w', (lambda o, a: lambda e: e('%s %s' % (o, a)))(*mk))
            if fuses: raise Unsupported('logic.l mem-dst feeding branch')
            return 1
        if memsrc: ea_load_A_to_tmp(e, src, size)    # memory src -> $TMP BEFORE the RMW (X is set
        def modify(e):                               # only inside ea_rmw, so loading src here is safe)
            if memsrc: e('%s $%02X' % (opn, TMP))
            elif src[0] == 'imm': e('%s %s' % (opn, imm16(src[1])))
            elif src[0] in ('Dn', 'An'): e('%s $%02X' % (opn, reg_dp(src[1])))
            else: raise Unsupported('logic src %r' % (src,))
        ea_rmw(e, dst, size, modify)                 # handles Dn and memory RMW (incl. (An)+ once)
        if fuses:
            # and/or/eor set N,Z (C=V=0) -> only Z/N-testable branches; reload the result (RMW
            # write clobbered A/flags for the memory case; cheap+safe for Dn too).
            if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('logic feeding %s (needs C/V)' % nb)
            if dst[0] == 'Dn': e('lda $%02X' % reg_dp(dst[1]))
            else: ea_load_A(e, dst, size)
            emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'clr':
        dst = ops[0]
        if size == 'l':                                  # clear BOTH 16-bit words (ea_store is .w-only)
            if dst[0] == 'Dn':
                dp = reg_dp(dst[1]); e('lda #$0000'); e('sta $%02X' % dp); e('sta $%02X' % (dp+2))
            elif dst[0] in ('(An)', '(d16,An)'):
                an = dst[-1]; disp = dst[1] if dst[0] == '(d16,An)' else 0
                for d2 in (disp, disp+2):                # big-endian: both words zero, order moot
                    ea_store_A_from(e, ('(d16,An)', d2, an), 'w', lambda e: e('lda #$0000'))
            elif dst[0] == '-(An)':                      # push a long zero (predec 4, write 0 both words)
                an = dst[-1]; predec_an(e, an, 4); dp = reg_dp(an)
                e('lda $%02X' % dp); e('tax'); e('lda #$0000')
                e('jsr wrw40'); e('inx'); e('inx'); e('jsr wrw40')
            else: raise Unsupported('clr.l %r' % (dst,))
            return 1
        ea_store_A_from(e, dst, size, lambda e: e('lda #$0000')); return 1
    if base == 'moveq':                                  # Dn = sign-extend8(imm) (32-bit), NZ V=C=0
        n = ops[0][1] & 0xFF; dp = reg_dp(ops[1][1])
        lo = (0xFF00 | n) if n & 0x80 else n
        e('lda #$%04X' % lo); e('sta $%02X' % dp)
        e('lda #$%04X' % (0xFFFF if n & 0x80 else 0)); e('sta $%02X' % (dp+2))
        if fuses: e('lda $%02X' % dp); emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base in ('lsl', 'lsr', 'asl', 'asr'):             # shift Dn by #imm OR by Dm (.w)
        cnt, dst = ops
        if dst[0] != 'Dn': raise Unsupported('%s non-Dn dst' % base)
        if base == 'asr' and size != 'w': raise Unsupported('asr.%s — only .w' % size)
        def one(e):                                      # one shift step on A (M=16)
            if base == 'asr':                            # arithmetic >>1: C=bit15, ror folds sign back in
                e('cmp #$8000'); e('ror a')
            else:
                e({'lsl': 'asl a', 'asl': 'asl a', 'lsr': 'lsr a'}[base])
        if cnt[0] == 'Dn':                               # DYNAMIC count: shift Dn.w (Dm.b & $3F) times via a loop
            if size != 'w': raise Unsupported('dynamic %s.%s — only .w' % (base, size))
            dp = reg_dp(dst[1]); dm = reg_dp(cnt[1]); loop = e.fresh(); done = e.fresh()
            e('lda $%02X' % dm); e('and #$003F'); e('tax')   # X = count (low 6 bits, 0-63)
            e('lda $%02X' % dp)                              # A = Dn.w
            e.lbl(loop); e('cpx #$0000'); e('beq %s' % done)
            one(e); e('dex'); e('bra %s' % loop)
            e.lbl(done); e('sta $%02X' % dp)
            if fuses: raise Unsupported('dynamic shift feeding branch — add if needed')
            return 1
        if cnt[0] != 'imm': raise Unsupported('%s count mode %s' % (base, cnt[0]))
        def lv(e):
            ea_load_A(e, dst, size)
            for _ in range(cnt[1] & 0xFFFF): one(e)
        ea_store_A_from(e, dst, size, lv)
        if fuses:                                        # result Z/N is live; only Z/N-testable branches
            if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('shift feeding %s (needs C/V)' % nb)
            e('lda $%02X' % reg_dp(dst[1]))              # reload result for clean Z/N (dst is Dn)
            emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base in ('rol', 'ror'):                           # rotate Dn by #imm (.w lo16 / .l full 32-bit)
        cnt, dst = ops
        if dst[0] != 'Dn' or cnt[0] != 'imm': raise Unsupported('%s non-imm/non-Dn' % base)
        if fuses: raise Unsupported('%s feeding branch' % base)
        dp = reg_dp(dst[1]); n = cnt[1] & 0xFFFF
        for _ in range(n):
            s = e.fresh()
            if base == 'rol':                            # left: top bit (lo15 for .w / bit31 for .l) -> bit0
                e('asl $%02X' % dp)                      # lo <<= 1, C = lo.bit15
                if size == 'l': e('rol $%02X' % (dp + 2))# hi = (hi<<1)|C, C = bit31
                e('bcc %s' % s); e('inc $%02X' % dp); e.lbl(s)
            else:                                        # ror: bit0 -> top bit
                if size == 'l': e('lsr $%02X' % (dp + 2)); e('ror $%02X' % dp)  # C = bit0
                else: e('lsr $%02X' % dp)                # C = lo.bit0
                e('bcc %s' % s)
                w = dp + 2 if size == 'l' else dp        # set the top bit (bit31 / bit15)
                e('lda $%02X' % w); e('ora #$8000'); e('sta $%02X' % w); e.lbl(s)
        return 1
    if base == 'not':                                    # bitwise complement <ea> (~ea), in place
        dst = ops[0]
        if size == 'l': raise Unsupported('not.l — add if needed')
        m = 0x00FF if size == 'b' else 0xFFFF
        ea_rmw(e, dst, size, lambda e: e('eor #$%04X' % m))
        if fuses:
            if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('not feeding %s' % nb)
            if dst[0] == 'Dn': e('lda $%02X' % reg_dp(dst[1]))
            else: ea_load_A(e, dst, size)
            emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'ext':                                    # sign-extend in place; V=C=0, NZ from result
        dp = reg_dp(ops[0][1])
        if size == 'w':                                  # byte -> word: Dn.w = sext8(Dn.b), hi16 unchanged
            e('lda $%02X' % dp); e('and #$00FF'); e('eor #$0080'); e('sec'); e('sbc #$0080'); e('sta $%02X' % dp)
        elif size == 'l':                                # word -> long: Dn.hi16 = sext16(Dn.w)
            e('lda $%02X' % dp); e('asl a')              # C = bit15 of Dn.w
            e('lda #$0000'); e('sbc #$0000'); e('eor #$FFFF'); e('sta $%02X' % (dp+2))  # C? $FFFF : $0000
        else: raise Unsupported('ext.%s' % size)
        if fuses:
            if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('ext feeding %s' % nb)
            e('lda $%02X' % dp); emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'swap':                                   # swap Dn.hi16 <-> Dn.lo16 (32-bit; NZ from result, V=C=0)
        dp = reg_dp(ops[0][1])
        e('lda $%02X' % dp); e('tax'); e('lda $%02X' % (dp+2)); e('sta $%02X' % dp); e('txa'); e('sta $%02X' % (dp+2))
        if fuses:
            if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('swap feeding %s' % nb)
            e('lda $%02X' % dp); emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'pea':                                    # push effective address (32-bit) to -(a7)
        ea = ops[0]
        if ea[0] == 'abs':                               # pea $XXXX(pc) [capstone-resolved] / $XXXX.l
            e('lda #%s' % hx(ea[1] & 0xFFFF)); e('sta $54'); e('lda #%s' % hx((ea[1] >> 16) & 0xFFFF)); e('sta $56')
        elif ea[0] in ('(An)', '(d16,An)'):              # pea (An) / pea (d16,An) = An (+disp)
            an = ea[-1]; disp = ea[1] if ea[0] == '(d16,An)' else 0; dp = reg_dp(an)
            e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('sta $54')
            e('lda $%02X' % (dp+2)); e('adc %s' % hi_ext(disp)); e('sta $56')
        else: raise Unsupported('pea %r' % (ea,))
        e('jsr push32'); return 1
    if base == 'neg':
        dst = ops[0]
        if size == 'l': raise Unsupported('neg.l — add if needed')
        def modify(e):
            e('eor #$FFFF'); e('inc a')                 # two's complement: 0 - A (X preserved)
        ea_rmw(e, dst, size, modify)                    # works for Dn and memory EAs
        if fuses: raise Unsupported('neg feeding branch')
        return 1
    if base == 'mulu':                                   # MULU.W <ea>,Dn : Dn = Dn.w * ea.w (unsigned 32)
        src, dst = ops
        if dst[0] != 'Dn': raise Unsupported('mulu dst not Dn')
        if size not in (None, 'w'): raise Unsupported('mulu.%s' % size)
        ea_load_A(e, src, 'w'); e('sta $52')             # b = src.w  (usmul reads $50*$52)
        e('lda $%02X' % reg_dp(dst[1])); e('sta $50')    # a = Dn.w
        e('jsr usmul')                                   # product -> $94(lo):$96(hi); helper auto -> usmul_l
        e('lda $94'); e('sta $%02X' % reg_dp(dst[1]))
        e('lda $96'); e('sta $%02X' % (reg_dp(dst[1]) + 2))
        if fuses: raise Unsupported('mulu feeding branch')
        return 1
    if base == 'divu':                                   # DIVU.W <ea>,Dn : Dn.lo=Dn(32)/ea.w, Dn.hi=rem
        src, dst = ops
        if dst[0] != 'Dn': raise Unsupported('divu dst not Dn')
        if size not in (None, 'w'): raise Unsupported('divu.%s' % size)
        dp = reg_dp(dst[1])
        e('lda $%02X' % dp); e('sta $50')                # dividend lo16 = Dn.lo
        e('lda $%02X' % (dp + 2)); e('sta $52')          # dividend hi16 = Dn.hi
        ea_load_A(e, src, 'w'); e('sta $54')             # divisor = src.w
        e('jsr esc_udiv')                                # -> quot $50:$52, rem $94 (bank-$92 local; NOT
                                                         # the bank-$00 `udiv` $00:A483 -- name collision)
        e.brn += 1; ov = 'dvov%s_%d' % (e.pfx, e.brn)
        e('lda $52'); e('bne %s' % ov)                   # quotient >16b => 68K overflow: Dn UNCHANGED (V=1)
        e('lda $50'); e('sta $%02X' % dp)                # Dn.lo = quotient
        e('lda $94'); e('sta $%02X' % (dp + 2))          # Dn.hi = remainder
        e.lbl(ov)
        if fuses: raise Unsupported('divu feeding branch')
        return 1
    if base == 'ext':
        dp = reg_dp(ops[0][1])
        if size == 'l': sext_hi(e, dp)                   # word -> long: hi16 = sign(lo16)
        else: raise Unsupported('ext.w (byte->word)')
        return 1
    if base == 'tst':
        if size == 'l':                                  # FULL 32-bit test (ea_load_A is .w-only):
            lo, hi = _ref32(e, ops[0], CMP32_PAIR)       # N = bit31, Z_full = (hi==0 && lo==0)
            e('lda %s' % hi)                             # sets N (bit31) + Z=(hi==0); lo saved for Z_full
            e._cmp32_low = lo
            if fuses: emit_branch(e, nb, branch_target(nxt), 'tst32'); return 2
            return 1
        ea_load_A(e, ops[0], size)
        if fuses: emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        return 1
    if base == 'nop':
        return 1
    if base in ('bset', 'bclr', 'bchg'):                 # bit set/clear/change <bit>,<ea> (in place)
        bitop, dst = ops
        if bitop[0] != 'imm': raise Unsupported('%s dynamic bit operand' % base)
        if fuses: raise Unsupported('%s feeding branch (Z = original bit, not modeled)' % base)
        op = {'bset': 'ora', 'bclr': 'and', 'bchg': 'eor'}[base]
        if dst[0] == 'Dn':                               # 32-bit register bit (mod 32)
            nbit = bitop[1] & 31; dp = reg_dp(dst[1])
            w = dp if nbit < 16 else dp + 2; m = (1 << nbit) >> (0 if nbit < 16 else 16)
            mm = ((~m) & 0xFFFF) if base == 'bclr' else (m & 0xFFFF)
            e('lda $%02X' % w); e('%s #$%04X' % (op, mm)); e('sta $%02X' % w); return 1
        # memory/abs byte (mod 8): IO-aware RMW via readbyte/writebyte so the C-Chip register $900007
        # routes to $41:F000 shared RAM EXACTLY as the interpreter does ($90xxxx; $00F0xxxx -> $40).
        nbit = bitop[1] & 7; m = 1 << nbit
        mm = ((~m) & 0xFFFF) if base == 'bclr' else m
        def setup_addr(e):
            if dst[0] == 'abs':
                e('lda #%s' % hx(dst[1] & 0xFFFF)); e('sta $54')
                e('lda #%s' % hx((dst[1] >> 16) & 0xFFFF)); e('sta $52')
            elif dst[0] in ('(An)', '(d16,An)'):
                an = dst[-1]; disp = dst[1] if dst[0] == '(d16,An)' else 0
                ea_setup_romaware(e, an, disp)
            else: raise Unsupported('%s dst %r' % (base, dst))
        setup_addr(e); e('jsr readbyte')                # A.lo = current byte (IO-aware)
        e('%s #$%04X' % (op, mm)); e('sta $80')         # modify; writebyte takes the value in $80
        setup_addr(e); e('jsr writebyte')               # re-setup ($54 advanced by readbyte), write back
        return 1
    if base == 'btst':                                   # btst <bit>,<ea> : Z = !(bit of ea)
        bitop, dst = ops
        if bitop[0] == 'imm':                            # static bit number -> single mask
            nbit = bitop[1] & (7 if size == 'b' else 31)
            ea_load_A(e, dst, size or 'b'); e('and #$%04X' % (1 << nbit))
        elif bitop[0] == 'Dn':                           # dynamic bit number in a data reg
            # btst Dn,Dm = long (bit mod 32); btst Dn,<mem> = byte (bit mod 8). Extract that bit
            # of the dst into A bit0 (so `and #$0001` leaves Z = bit-clear, as btst requires), via a
            # runtime right-shift loop. Reg-dst .l: pick lo/hi word by bit>=16. Clobbers A,X (scratch).
            bdp = reg_dp(bitop[1])
            if dst[0] == 'Dn':                           # 32-bit register dst (mod 32)
                ddp = reg_dp(dst[1])
                lo, sh = e.fresh(), e.fresh()
                e('lda $%02X' % bdp); e('and #$001F')
                e('cmp #$0010'); e('bcc %s' % lo)
                e('sec'); e('sbc #$0010'); e('tax'); e('lda $%02X' % (ddp+2)); e('bra %s' % sh)
                e.lbl(lo); e('tax'); e('lda $%02X' % ddp)
                e.lbl(sh)
            else:                                        # memory dst (mod 8, single byte)
                ea_load_A(e, dst, 'b'); e('pha')
                e('lda $%02X' % bdp); e('and #$0007'); e('tax'); e('pla')
            lp, dn = e.fresh(), e.fresh()
            e.lbl(lp); e('cpx #$0000'); e('beq %s' % dn); e('lsr a'); e('dex'); e('bra %s' % lp); e.lbl(dn)
            e('and #$0001')
        else:
            raise Unsupported('btst bit operand %s' % bitop[0])
        if fuses:
            if nb not in ('beq', 'bne'): raise Unsupported('btst feeding %s' % nb)
            emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
        raise Unsupported('btst not feeding beq/bne')
    if base in ('cmp', 'cmpi', 'cmpa'):
        src, dst = ops
        emit_signed_cmp(e, dst, src, size)
        if fuses: emit_branch(e, nb, branch_target(nxt), 'signed32' if size == 'l' else 'signed'); return 2
        raise Unsupported('%s not feeding a branch' % base)

    if base == 'trap':
        # coroutine yield: tail-jump to the trap itself so the interpreter executes it ($0532 saves
        # the context with resume-PC = the instr after the trap, and the scheduler runs the next task).
        a = ins.address
        e('lda %s' % imm16(a & 0xFFFF)); e('sta $40')
        e('lda %s' % imm16((a >> 16) & 0xFFFF)); e('sta $42')
        e('jmp inext'); return 1
    if base == 'jmp':
        ea = ops[0]
        if ea[0] == '(An)':                              # jmp (An): jump-table state dispatch -> route
            dp = reg_dp(ea[1])                           # through ojmp_hook (dispatch the state escape, else
            e('lda $%02X' % dp); e('sta $40')            # interpret) exactly like the interp's op_jmp_idx hook.
            e('lda $%02X' % (dp+2)); e('sta $42')
            e('jmp ojmp_hook'); return 1
        if ea[0] == 'abs':                               # jmp $XXXX: tail-jump (interpret the target)
            e('lda %s' % imm16(ea[1] & 0xFFFF)); e('sta $40')
            e('lda %s' % imm16((ea[1] >> 16) & 0xFFFF)); e('sta $42')
            e('jmp inext'); return 1
        raise Unsupported('jmp %r' % (ea,))
    # ---- branches ----
    if base == 'bra':
        t = branch_target(ins)
        if getattr(e, 'entry', None) is not None and not (e.entry <= t < e.end):
            # TAIL-JUMP: bra to another function (e.g. GAME_TICK -> $2e6a). Set PC=t and jmp inext;
            # the target runs interpreted and rts's to OUR caller (the return we re-pushed in the
            # prologue). No sentinel (it's a tail, not a call). bank1_transform -> jml.l inext.
            e('lda %s' % imm16(t & 0xFFFF)); e('sta $40')
            e('lda %s' % imm16((t >> 16) & 0xFFFF)); e('sta $42')
            e('jmp inext'); return 1
        emit_branch(e, 'bra', t, None); return 1
    if base in ('dbra', 'dbf'):
        dp = reg_dp(ops[0][1]); tgt = branch_target(ins)
        e('lda $%02X' % dp); e('dec a'); e('sta $%02X' % dp); e('cmp #$FFFF')
        s = e.fresh(); e('beq %s' % s); e('jmp ' + branch_label(e, tgt)); e.lbl(s); return 1
    if base in BCC:
        raise Unsupported('stray conditional %s (flags not from preceding op)' % base)

    raise Unsupported('opcode %s' % ins.mnemonic)

def branch_target(ins):
    return int(re.search(r'\$([0-9a-f]+)$', ins.op_str).group(1), 16)

def sext_hi(e, dp):
    """hi16 of reg at dp = (lo16 & $8000) ? $FFFF : $0000. Branchless: replicate bit15.
    (Avoids a Poppy assembler bug where repeated forward short bpl/bra blocks — three
    consecutive adda.w sext_hi in entry_d96 — get a wrong, backward displacement -> infinite
    loop. 16-bit A; clobbers A and carry, which both callers reload/reset right after.)"""
    e('lda $%02X' % dp)              # lo16
    e('asl a')                       # C = bit15
    e('lda #$0000'); e('sbc #$0000') # A = C ? $0000 : $FFFF
    e('eor #$FFFF')                  # A = C ? $FFFF : $0000  (= sign-extended hi16)
    e('sta $%02X' % (dp+2))

def load_long_to(e, src, dp):
    """32-bit load src -> reg at dp (no flags)."""
    if src[0] in ('(d16,An)', '(An)', '(An)+'):
        an = src[-1]; disp = src[1] if src[0] == '(d16,An)' else 0
        if is_workram(an):                                       # provably work RAM -> fast (X-held EA = aliasing-safe)
            s = reg_dp(an)
            e('lda $%02X' % s); e('clc'); e('adc %s' % imm16(disp)); e('tax')
            e('jsr rdw40'); e('sta $%02X' % (dp+2)); e('inx'); e('inx'); e('jsr rdw40'); e('sta $%02X' % dp)
        else:
            # Both reads re-derive the EA from An's reg slots ($s/$s+2), so we must NOT write any
            # part of dp until BOTH reads are done: `movea.l (a1),a1` (dp aliases An's slots) would
            # otherwise clobber the base hi word before the lo16 read -> a corrupted-bank lo read
            # (the c172 coroutine bug: bad a1 -> wrong sprite-draw bridge arg). Stash hi16 in TMP.
            ea_setup_romaware(e, an, disp); e('jsr rdw_ea'); e('sta $%02X' % TMP)      # hi16 @ addr -> scratch
            ea_setup_romaware(e, an, disp+2); e('jsr rdw_ea'); e('sta $%02X' % dp)     # lo16 @ addr+2 -> dp
            e('lda $%02X' % TMP); e('sta $%02X' % (dp+2))                              # hi16 -> dp+2 (after both reads)
            # NB: re-setup the address; rdw_ea leaves $54 = addr+1 (it inc's between byte reads),
            # so the old `inc $54 / inc $54` read addr+3 (off by one). Recompute = robust.
        if src[0] == '(An)+': bump_an(e, an, 4)
        return
    if src[0] in ('Dn', 'An'):
        s = reg_dp(src[1]); e('lda $%02X' % s); e('sta $%02X' % dp)
        e('lda $%02X' % (s+2)); e('sta $%02X' % (dp+2)); return
    raise Unsupported('load_long src %r' % (src,))

def store_long_from(e, dst, dp):
    """store the 32-bit value at $dp(lo)/$dp+2(hi) to dst (no flags)."""
    if dst[0] in ('Dn', 'An'):
        d = reg_dp(dst[1]); e('lda $%02X' % dp); e('sta $%02X' % d)
        e('lda $%02X' % (dp+2)); e('sta $%02X' % (d+2)); return
    if dst[0] in ('(d16,An)', '(An)', '(An)+'):
        an = dst[-1]; disp = dst[1] if dst[0] == '(d16,An)' else 0
        ea_store_A_from(e, ('(d16,An)', disp, an),   'w', lambda e: e('lda $%02X' % (dp+2)))  # hi16 @ addr
        ea_store_A_from(e, ('(d16,An)', disp+2, an), 'w', lambda e: e('lda $%02X' % dp))      # lo16 @ addr+2
        if dst[0] == '(An)+': bump_an(e, an, 4)
        return
    if dst[0] == '-(An)':                                     # push long: predec 4, write big-endian
        an = dst[-1]; predec_an(e, an, 4)                     # An -= 4 (now points at the push slot)
        ea_store_A_from(e, ('(d16,An)', 0, an), 'w', lambda e: e('lda $%02X' % (dp+2)))  # hi16 @ An
        ea_store_A_from(e, ('(d16,An)', 2, an), 'w', lambda e: e('lda $%02X' % dp))      # lo16 @ An+2
        return
    raise Unsupported('store_long dst %r' % (dst,))

def gen_movel(e, src, dst):
    """move.l src -> dst (full 32-bit). scratch $9A(lo)/$9C(hi). (ea_load/store are .w-only.)"""
    if src[0] == 'imm':
        e('lda #%s' % hx(src[1] & 0xFFFF)); e('sta $9A')
        e('lda #%s' % hx((src[1] >> 16) & 0xFFFF)); e('sta $9C')
    else:
        load_long_to(e, src, 0x9A)
    store_long_from(e, dst, 0x9A)

RUN_MIN = 4                                          # collapse runs of >=4 identical move.l (An)+,(An)+

def is_movel_anp(ins):
    """move.l (An)+,(Am)+ -- the postincrement long-copy primitive that forms memcpy runs."""
    b, sz = split_mn(ins)
    if b != 'move' or sz != 'l': return False
    ops = operands(ins)
    return len(ops) == 2 and ops[0][0] == '(An)+' and ops[1][0] == '(An)+'

def movel_run_len(insns, i, labels):
    """length of the run of IDENTICAL `move.l (An)+,(Am)+` starting at i (same An,Am). Stops at a
    branch target (a label inside the run would be unreachable after collapsing)."""
    if not is_movel_anp(insns[i]): return 0
    s0 = operands(insns[i]); k = 1
    while i + k < len(insns):
        nx = insns[i + k]
        if nx.address in labels or not is_movel_anp(nx) or operands(nx) != s0: break
        k += 1
    return k

def gen_movel_run(e, src, dst, k):
    """collapse k copies of `move.l (a0)+,(a1)+` into a loop (mirrors the interpreter's mvc_check;
    avoids unrolling a 255-long memcpy like $15b4 into 255x native code). Counter in scratch $98
    (free; gen_movel uses $9A/$9C + X + $80, none touch $98). a0/a1 advance via the (An)+ bumps."""
    lp = e.fresh()
    e.cmt('run-collapse: %d x move.l (a0)+,(a1)+' % k)
    e('lda #$%04X' % k); e('sta $98')
    e.lbl(lp)
    gen_movel(e, src, dst)                            # one long: load (a0)+ -> store (a1)+, bumps both
    e('dec $98'); e('bne %s' % lp)

def gen_call(e, ins):
    """CALL-BRIDGE (CALL_BRIDGE_DESIGN.md): push a $00FF:cont sentinel return, set PC=callee,
    jmp inext (interpreter runs the callee). The callee's rts pops the sentinel -> op_rts_sentinel
    -> jmp ($0040) -> cont. Args/cleanup are the normal move.w/-(a7) + addq.l #n,a7 instructions
    around the call (transpiled separately). Reg-file-faithful => no native state crosses the bridge."""
    e.brn += 1; cont = 'br%s_%d' % (e.pfx, e.brn); t = ins.op_str.strip()
    # $XXXX.l (jsr.l) / $XXXX (bsr, capstone-resolved) / $XXXX(pc) (jsr (d16,PC) -- capstone already
    # resolved the target to absolute $XXXX). All give the absolute callee address in group(1).
    m = (re.fullmatch(r'\$([0-9a-f]+)\.l', t) or re.fullmatch(r'\$([0-9a-f]+)', t)
         or re.fullmatch(r'\$([0-9a-f]+)\(pc\)', t))
    # BRIDGE-TO-ESCAPE: callee has an escbank escape -> run it NATIVELY (no interpret) and resume the
    # parent. Set $40=cont/$42=$00FE (sentinel), jmp entry_C: entry_C's prologue pushes $00FE:cont, its
    # body runs native, its terminal rts pops $00FE:cont -> ors_pre -> resume here ($92:cont). The
    # callee escape MUST route its rts through ors_pre (transpiled with the current rts codegen).
    if m and (int(m.group(1), 16) & 0xFFFFFF) in ESCAPED:
        a = int(m.group(1), 16) & 0xFFFFFF
        e.cmt('CALL-BRIDGE %s %s -> entry_%x (NATIVE escape), resume %s' % (ins.mnemonic, t, a, cont))
        e('lda #%s' % cont); e('sta $40'); e('lda #$00FE'); e('sta $42')
        e('jmp entry_%x' % a)
        e.lbl(cont)
        return 1
    if not m:
        # INDIRECT-BRIDGE-TO-ESCAPE: jsr (An) with a RUNTIME target -> ibridge (escbank) scans An at
        # runtime; if it's a bridge-to-escape-able escape (a draw routine) it dispatches it NATIVELY,
        # else it interpret-bridges. Set up the bridge-to-escape state ($40=cont/$42=$00FE) + An ->
        # $52(lo)/$50(hi), then jmp ibridge. (escbank-only; ibridge is a $92 label.)
        ea = parse_ea(t)
        if ea[0] != '(An)': raise Unsupported('call form %r' % t)
        dp = reg_dp(ea[1])
        if BANK2:
            # ibridge is a $92 label (unreachable from $94) and its ib_miss resumes in bank $92. INLINE
            # the interpret-bridge: push the $00FD sentinel:cont, set PC=An, jml inext. The callee's rts
            # pops $00FD:cont -> ors_pre -> ors_94chk -> bank-$94 resume at cont. (No native draw dispatch
            # in $94 -- the callee always interprets; the per-jsr(An) native-draw win is forgone here.)
            # push the $00FD:cont sentinel, set PC=An, then route through ojmp_hook (reachable from $94
            # via jml.l): xlat HIT -> dispatch the callee's --table native escape (the per-jsr(An) native-
            # draw win, e.g. c172's $295A/$29B6 renderers); MISS/gate-off -> jml inext (interpret, as before).
            # Either way the callee's rts pops $00FD:cont -> ors_pre -> ors_94chk -> bank-$94 resume at cont.
            e.cmt('INDIRECT-BRIDGE %s %s -> ojmp_hook (a0 --table escape, else interpret); $00FD sentinel, resume %s' % (ins.mnemonic, t, cont))
            e('lda #%s' % cont); e('sta $54'); e('lda #$00FD'); e('sta $56'); e('jsr push32')
            e('lda $%02X' % dp); e('sta $40'); e('lda $%02X' % (dp+2)); e('sta $42')
            e('jmp ojmp_hook')
            e.lbl(cont)
            return 1
        e.cmt('INDIRECT-BRIDGE %s %s -> ibridge (a0 escape or interpret), resume %s' % (ins.mnemonic, t, cont))
        e('lda #%s' % cont); e('sta $40'); e('lda #$00FE'); e('sta $42')
        e('lda $%02X' % dp); e('sta $52'); e('lda $%02X' % (dp+2)); e('sta $50')
        e('jmp ibridge')
        e.lbl(cont)
        return 1
    # route the (static-target) callee through ojmp_hook (xlat): a --table escape of the callee
    # dispatches NATIVELY (cross-bank-safe; e.g. entry_25110's $184E8/$25A40), a MISS falls back to
    # jml inext (interpret, as before). Same size as `jmp inext` -> safe in-place swap for bank-$00
    # escapes. The pushed $00FF/$00FD sentinel + faithful-rts callee resume cont either way.
    e.cmt('CALL-BRIDGE %s %s -> ojmp_hook (callee --table escape, else interpret), resume %s' % (ins.mnemonic, t, cont))
    sentinel = '$00FD' if BANK2 else '$00FF'         # bank2: $00FD resumes in $94 (not $00 via $00FF)
    e('lda #%s' % cont); e('sta $54'); e('lda #%s' % sentinel); e('sta $56'); e('jsr push32')
    a = int(m.group(1), 16)                              # jsr.l absolute / bsr (capstone resolves PC-rel)
    e('lda #%s' % hx(a & 0xFFFF)); e('sta $40'); e('lda #%s' % hx((a >> 16) & 0xFFFF)); e('sta $42')
    e('jmp ojmp_hook')
    e.lbl(cont)
    return 1

def gen_movem(e, ins, size, ops):
    # capstone gives "<reglist>, -(a7)" (save) or "(a7)+, <reglist>" (restore).
    # the reglist is the operand WITHOUT parens (the other is the -(a7)/(a7)+ memory operand).
    txt = ins.op_str
    parts = [p.strip() for p in txt.split(',')]
    reglist = [p for p in parts if '(' not in p]
    if len(reglist) != 1: raise Unsupported('movem operands %r (only (a7) frame supported)' % txt)
    regs = expand_reglist(reglist[0])
    if '-(a7)' in txt or '-(sp)' in txt:                 # SAVE (predecrement): high reg first
        for r in reversed(regs):
            dp = reg_dp(r)
            if size == 'l':
                e('lda $%02X' % dp); e('sta $54'); e('lda $%02X' % (dp+2)); e('sta $56'); e('jsr push32')
            else:
                e('lda $3C'); e('sec'); e('sbc #$0002'); e('sta $3C')
                e('ldx $3C'); e('lda $%02X' % dp); e('jsr wrw40')
        return 1
    else:                                                # RESTORE (postincrement): low reg first
        for r in regs:
            dp = reg_dp(r)
            if size == 'l':
                e('ldx $3C'); e('jsr rdw40'); e('sta $%02X' % (dp+2))
                e('inx'); e('inx'); e('jsr rdw40'); e('sta $%02X' % dp)
                e('lda $3C'); e('clc'); e('adc #$0004'); e('sta $3C')
            else:                                        # movem.w restore SIGN-EXTENDS each word
                e('ldx $3C'); e('jsr rdw40'); e('sta $%02X' % dp); sext_hi(e, dp)
                e('lda $3C'); e('clc'); e('adc #$0002'); e('sta $3C')
        return 1

def expand_reglist(s):
    out = []
    for part in s.split('/'):
        if '-' in part:
            a, b = part.split('-'); t = a[0]
            for i in range(int(a[1]), int(b[1]) + 1): out.append('%s%d' % (t, i))
        else:
            out.append(part)
    return out

def gen_addsub(e, base, size, ops, nxt, fuses, nb):
    is_sub = base.startswith('sub')
    src, dst = ops
    if base in ('adda', 'suba') or dst[0] == 'An':       # address-register arithmetic: no flags
        dp = reg_dp(dst[1])
        if size == 'l':
            if src[0] in ('Dn', 'An'):
                s = reg_dp(src[1]); lo, hi = '$%02X' % s, '$%02X' % (s+2)
            elif src[0] == 'imm':
                lo, hi = '#'+hx(src[1] & 0xFFFF), '#'+hx((src[1] >> 16) & 0xFFFF)
            else: raise Unsupported('adda/suba mem src')
        else:                                            # .w: sign-extend src to 32-bit in $9A/$9C
            ea_load_A(e, src, size); e('sta $9A'); sext_hi(e, 0x9A); lo, hi = '$9A', '$9C'
        op = 'sbc' if is_sub else 'adc'
        e('lda $%02X' % dp); e('clc' if not is_sub else 'sec'); e('%s %s' % (op, lo)); e('sta $%02X' % dp)
        e('lda $%02X' % (dp+2)); e('%s %s' % (op, hi)); e('sta $%02X' % (dp+2))
        return 1
    # add/sub on Dn (or mem) .w
    src, dst = ops
    store_dp = reg_dp(dst[1]) if dst[0] == 'Dn' else None
    # .l RMW to MEMORY for add/sub: ea_rmw is word-only, and unlike the logic family these need
    # inter-word CARRY/BORROW. 68K big-endian -> HIGH word @ disp+0, LOW word @ disp+2. Do the LOW
    # word first (clc/sec then adc/sbc -> sets C), preserve C across the high-word ADDRESS calc (its
    # `clc` would clobber C) via php/plp, then the HIGH word adc/sbc consumes it. The interp reg file
    # stores a Dn as lo16@dp / hi16@dp+2 (see the adda .l case above). Unblocks the $00C1xx sprite
    # segments (addi.l #4,$2a38(a5) / addi.l #2,$2a44(a5)). (impl 2026-06-29; validated by optest.)
    if size == 'l' and dst[0] in ('(An)', '(An)+', '(d16,An)'):
        if fuses: raise Unsupported('.l add/sub mem-dst feeding branch')
        an = dst[-1]; disp = dst[1] if dst[0] == '(d16,An)' else 0; dp = reg_dp(an)
        if src[0] == 'imm':
            slo, shi = imm16(src[1] & 0xFFFF), imm16((src[1] >> 16) & 0xFFFF)
        elif src[0] in ('Dn', 'An'):
            s = reg_dp(src[1]); slo, shi = '$%02X' % s, '$%02X' % (s + 2)
        else:
            raise Unsupported('.l add/sub mem-dst src %r' % (src,))
        op = 'sbc' if is_sub else 'adc'; init = 'sec' if is_sub else 'clc'
        e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp + 2)); e('tax')   # X = LOW word offset
        e('jsr rdw40'); e(init); e('%s %s' % (op, slo)); e('php'); e('jsr wrw40')
        e('lda $%02X' % dp); e('clc'); e('adc %s' % imm16(disp)); e('tax')       # X = HIGH word offset
        e('jsr rdw40'); e('plp'); e('%s %s' % (op, shi)); e('jsr wrw40')          # plp restores LOW's C
        if dst[0] == '(An)+': bump_an(e, an, 4)
        return 1
    if is_sub:
        if dst[0] == 'Dn':                                      # register dest: sbc + sta $dp (flags live)
            emit_signed_cmp(e, dst, src, size, store_dp=store_dp)
            if fuses: emit_branch(e, nb, branch_target(nxt), 'signed32' if size == 'l' else 'signed'); return 2
            return 1
        # MEMORY dest: sub is read-modify-WRITE (not a flagless cmp). emit the sub into A with flags,
        # then write A back to the EA preserving the sub's N,V,Z,C across the (flag-clobbering) store.
        wr = 'wrb40' if size == 'b' else 'wrw40'
        if fuses:
            emit_signed_cmp(e, dst, src, size, store_dp=None)  # A=result; N,V,Z,C live
            e('php'); e('pha')                                 # save sub flags, then result value
            ea_addr_to_X(e, dst)                               # X = dest work-RAM offset (clobbers A)
            e('pla'); e('jsr %s' % wr)                         # A=result; write back (clobbers flags)
            e('plp')                                           # restore the sub's flags for the branch
            emit_branch(e, nb, branch_target(nxt), 'signed'); return 2
        def modify(e2):                                        # non-fused: plain RMW writeback
            e2('sec')
            if src[0] == 'imm': e2('sbc %s' % imm16(src[1]))
            elif src[0] in ('Dn', 'An'): e2('sbc $%02X' % reg_dp(src[1]))
            else: raise Unsupported('sub mem,mem')
        ea_rmw(e, dst, size, modify); return 1
    # add family (RMW; (An)+ increments once). A MEMORY src is pre-loaded to TMP BEFORE ea_rmw sets X
    # for the dst (so the src load can't clobber the RMW address); modify then `adc $TMP`.
    if src[0] not in ('imm', 'Dn', 'An'):
        ea_load_A_to_tmp(e, src, size)
    def modify(e):
        e('clc')
        if src[0] == 'imm': e('adc %s' % imm16(src[1]))
        elif src[0] in ('Dn', 'An'): e('adc $%02X' % reg_dp(src[1]))
        else: e('adc $%02X' % TMP)
    ea_rmw(e, dst, size, modify)
    if fuses:
        # bne/beq/bmi/bpl need only Z/N -> reload the result (RMW write clobbered A/flags).
        # bcs/bcc/signed branches need C/V from the add -> not modeled here.
        if nb not in ('beq', 'bne', 'bmi', 'bpl'): raise Unsupported('add feeding %s (needs C/V)' % nb)
        if dst[0] == 'Dn': e('lda $%02X' % reg_dp(dst[1]))
        else: ea_load_A(e, dst, size)                    # re-read stored memory result for Z/N
        emit_branch(e, nb, branch_target(nxt), 'tst'); return 2
    return 1

# ===================== driver =====================
# helpers an escape may jsr; in --bank1 these run in bank $00 reached via `jsl <name>_l` rtl-wrappers
HELPERS = ('rdw40', 'wrw40', 'rdb40', 'wrb40', 'push32', 'rdw_ea', 'readbyte', 'usmul', 'writeword', 'writebyte')

def bank1_transform(lines):
    """rewrite a bank-$00 escape body to run from the escape bank ($92:8000): helper jsr->jsl.l _l
    wrapper, jmp inext->jml.l inext (back to bank $00). Internal jmp L../jmp _t.. stay (same bank).
    Counter inc is already emitted long-addressed. op_rts_sentinel trampolines continuations.
    NB: the `.l` suffix is REQUIRED — the bank-$00 helper/inext targets are numerically <=$FFFF,
    so Poppy's analyzer would classify jsl/jml as 16-bit Absolute and SIZE THEM AS 3 (while the
    encoder emits 4) -> label-address drift -> forward short branches resolve backward -> infinite
    loops. `.l` forces the analyzer's operand size to 3 (=> instr size 4), matching the encoder."""
    out = []
    for l in lines:
        s = l.strip()
        # CALL-BRIDGE sentinel: a bank-$92 escape must push $00FE (not $00FF) so op_rts_sentinel/
        # ors_pre resumes the continuation in bank $92 (jml [$40]), not bank $00 (jmp ($40)).
        # gen_call emits `lda #$00FF` immediately before `sta $56` (the sentinel-return high16).
        if s == 'sta $56' and out and out[-1].strip() == 'lda #$00FF':
            out[-1] = '    lda #$00FE'
            out.append(l); continue
        m = re.fullmatch(r'jsr (%s)' % '|'.join(HELPERS), s)
        if m:
            out.append('    jsl.l %s_l' % m.group(1)); continue
        if s == 'jmp inext':
            out.append('    jml.l inext'); continue
        if s == 'jmp ors_pre':                           # terminal rts -> bank-aware sentinel resume
            out.append('    jml.l ors_pre'); continue
        if s == 'jmp ojmp_hook':                         # jmp(An) state-dispatch -> bank-$00 jmp-table hook
            out.append('    jml.l ojmp_hook'); continue
        out.append(l)
    return out

# BW-RAM ($40) word/byte access bodies, inlined in place of the rdw40/wrw40/rdb40/wrb40 leaf calls.
# These mirror the helpers in interp.pasm EXACTLY (minus the rts). `lda $400000,x` is absolute-LONG
# indexed ($BF) -> it addresses bank $40 regardless of the program bank, so the SAME inline works from
# a bank-$00 gap escape AND a bank-$92 escape-bank escape (no `_l` rtl-wrapper, no jsl/jsr/rtl/rts
# overhead). X holds the work-RAM offset (set by the caller's `tax`); 16-bit X is preserved (sep #$20
# touches only M). Work RAM is big-endian: [X]=hi, [X+1]=lo.
# 16-bit BE work-RAM access (M=16 throughout -> no sep/rep). A 16-bit `lda $400000,x` reads the two
# bytes [x],[x+1] LITTLE-endian (A = [x+1]<<8 | [x]); `xba` swaps them to the 68K BIG-endian word
# ([x]<<8 | [x+1]). Symmetric for the store. ~2x fewer ops than the old byte-by-byte 8-bit assembly
# (rdw40 5->2, wrw40 6->3, rdb40 4->2) -> ~2x cheaper on EVERY inline work-RAM word/byte access, which
# dominates every escape body. Pure equivalence (same bytes, same result); the escape is already M=16.
# wrb40 stays 8-bit: a 16-bit `sta` would clobber the adjacent byte [x+1].
INLINE_MEM = {
    'rdw40': ['lda $400000,x', 'xba'],                       # LE word load + swap = BE word
    'wrw40': ['xba', 'sta $400000,x', 'xba'],                # swap -> LE store = BE word; restore A
    'rdb40': ['lda $400000,x', 'and #$00FF'],                # byte at [x] = low byte of the LE load
    'wrb40': ['sep #$20', 'sta $400000,x', 'rep #$20'],      # byte store: MUST stay 8-bit (else [x+1] clobbered)
}
def inline_mem_ops(lines):
    """Replace `jsr <rdw40|wrw40|rdb40|wrb40>` leaf calls with their inline bodies. Run BEFORE
    bank1_transform so it never sees these (they don't become jsl.l _l). Eliminates the per-memory-op
    call overhead (~25 cycles/op in bank1: jsl+wrapper-jsr+rtl+rts) on the hottest path of every
    escape -- escapes are memory-op-dominated (every Dn/An is a DP read, every (An)/(d16,An) a $40 op)."""
    out = []
    for l in lines:
        m = re.fullmatch(r'jsr (rdw40|wrw40|rdb40|wrb40)', l.strip())
        if m: out.extend('    ' + b for b in INLINE_MEM[m.group(1)])
        else: out.append(l)
    return out

def main():
    global VIDEO, ESCAPED, BANK2, WORKRAM
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    BANK2 = '--bank2' in sys.argv
    bank1 = '--bank1' in sys.argv or BANK2            # bank2 reuses all of bank1's jsl.l/jml.l transforms
    VIDEO = '--video' in sys.argv
    for a in sys.argv:                                # --workram=a0,a1: extra provably-work-RAM An regs (EA fast path)
        if a.startswith('--workram='): WORKRAM |= {r.strip() for r in a.split('=',1)[1].split(',') if r.strip()}
    coroutine = '--coroutine' in sys.argv                 # task-BODY escape (see main-loop-coroutine-arch):
    # entered by the $07E4/op_rte resume hook (reg file already restored, a7 already past the trap
    # frame), NOT by a jsr -> NO re-simulate-push prologue. Decode ends at the yield `bra` (target <
    # entry = back to the trap #5); that tail-jump runs the trap interpreted -> the normal yield.
    table = '--table' in sys.argv                         # AOT-TABLE/rts dispatch (aot-dispatch-table):
    # entered via xlat_dispatch (jmp(a0)/rts at a materialized boundary) with PC=fn-entry and the
    # caller's REAL return already on the 68K stack -> like default, decode to the terminal rts and
    # emit the faithful link/unlk/rts body, but SKIP the re-simulate push (the return is already there).
    for a in sys.argv:                                   # --escapes=hex,hex,..: callees with escbank escapes
        if a.startswith('--escapes='):
            ESCAPED = {int(x, 16) & 0xFFFFFF for x in a.split('=', 1)[1].split(',') if x}
    entry = int(args[0], 16)
    insns, (labels, fn_lo, fn_hi) = decode(entry)
    name = 'entry_%x' % entry
    e = Emit(pfx='%x' % entry)                       # per-function label namespace (global Poppy syms)
    e.entry, e.end = fn_lo, fn_hi                    # function bounds (for tail-jump detection in gen)
    e.tailjumps = set()                              # out-of-fn conditional-branch targets -> stubs
    # exit_addrs: the STRAIGHT-LINE flag-preserving epilogue run(s) ending at each rts (movem/unlk/
    # lea/pea/nop/movea/link/adda/suba + the rts). movem/unlk/rts DON'T touch the 68K CCR, so the CCR
    # is constant across the epilogue -> a branch to any of these reaches the caller's rts with NO
    # further flag-setting op. emit_branch materializes the 68K CCR at such a branch edge (D1-gap fix).
    FP = {'movem', 'unlk', 'lea', 'pea', 'nop', 'movea', 'link', 'adda', 'suba', 'rts'}
    e.exit_addrs = set()
    for k in range(len(insns)):
        if insns[k].mnemonic != 'rts': continue
        j = k
        while j >= 0 and insns[j].mnemonic.split('.')[0] in FP:
            e.exit_addrs.add(insns[j].address); j -= 1
    e.lines.append('; --- transpiled from $%06X (%d instrs) by tools/transpile.py%s ---'
                   % (entry, len(insns), ' [bank1]' if bank1 else ''))
    e.lbl(name)
    e('rep #$30')
    if entry in COUNTERS:
        c = COUNTERS[entry]
        if bank1: e('lda $00%04X' % c); e('inc a'); e('sta $00%04X' % c)   # long: DBR-independent
        else: e('inc $%04X' % c)
    if coroutine:
        e.cmt('coroutine task body: NO return-push (entered by the op_rte resume hook, not a jsr)')
    elif table:
        e.cmt('AOT-table/rts dispatch: caller return ALREADY on the 68K stack -> NO re-simulate push')
    else:
        e.cmt('re-simulate the jsr return-push the hook skipped (frame must match the real 68K)')
        e('lda $40'); e('sta $54'); e('lda $42'); e('sta $56'); e('jsr push32')
    unimpl = {}
    # TASK #73 frame-pacing (--accharge): charge $AC by this escape's DYNAMIC 68K-instr count so the
    # vblank-IRQ boundary fires at the same 68K-work point as MAME (the main loop only decrements $AC by
    # 1 per escape-step). Charge PER BASIC BLOCK at the block START -> loop bodies charge per iteration
    # (exact). Each charge is php/rep#$30/.../plp-wrapped so it preserves the caller's flags+mode and can
    # never disturb a fused cmp->conditional-branch. block size = #decoded instrs from the block start to
    # the next label-or-control-flow (cf inclusive). Bridged jsr/bsr count as 1 (callee charges its own).
    accharge = '--accharge' in sys.argv
    def _is_cf(ins):
        b = ins.mnemonic.split('.')[0]
        return b in CTRLFLOW or b in ('rts', 'trap')
    def emit_charge(start):
        if not accharge: return
        n = 0
        for j in range(start, len(insns)):
            if n > 0 and insns[j].address in labels: break      # next block begins at this label
            n += 1
            if _is_cf(insns[j]): break                          # block ends at control flow (inclusive)
        if n:
            e('php'); e('rep #$30'); e('lda #$%04X' % n); e('jsr esc_ac_charge'); e('plp')
    i = 0
    new_block = True
    while i < len(insns):
        ins = insns[i]
        if ins.address in labels: e.lbl(e.L(ins.address)); new_block = True
        if new_block: emit_charge(i); new_block = False
        rk = movel_run_len(insns, i, labels)         # collapse a memcpy run into a loop (vs unroll)
        if rk >= RUN_MIN:
            s, d = operands(ins); gen_movel_run(e, s, d, rk); i += rk; continue
        nxt = insns[i+1] if i+1 < len(insns) else None
        i0 = i
        try:
            i += gen(e, ins, nxt)
            # dbra/dbf whose FALL-THROUGH is a function exit: 68K dbra preserves the CCR, so the caller
            # reads N/Z of the loop body's last moved value. gen() already emitted the fall-through label;
            # materialize the CCR here (right after it) from that value. (emit_ccr_native only fires at
            # Bcc-to-exit edges; the dbra fall-through is neither a branch nor flag-preserving.)
            if ins.mnemonic.split('.')[0] in ('dbra', 'dbf') and i < len(insns) \
               and insns[i].address in e.exit_addrs:
                v = dbra_exit_ccr_val(insns[i0-1] if i0 > 0 else None)
                if v is not None: emit_ccr_from_value(e, v)
        except Unsupported as ex:
            e.cmt('!! UNIMPLEMENTED: %-9s %s   (%s)' % (ins.mnemonic, ins.op_str, ex))
            unimpl['%s %s' % (ins.mnemonic, ins.op_str.split(',')[0] if ins.op_str else '')] = str(ex)
            i += 1
        # block ends if ANY consumed instr was control flow (covers fused cmp+branch where the branch is nxt)
        if any(_is_cf(insns[k]) for k in range(i0, min(i, len(insns)))): new_block = True
    emit_tailjump_stubs(e)                            # out-of-fn conditional tail-jumps (after body)
    noinline = '--noinline' in sys.argv               # keep the leaf calls (baseline / cycle A/B)
    lines = e.lines if noinline else inline_mem_ops(e.lines)
    out = bank1_transform(lines) if bank1 else lines
    print('\n'.join(out))
    if unimpl:
        sys.stderr.write('\n=== %d UNIMPLEMENTED ===\n' % len(unimpl))
        for k, v in sorted(unimpl.items()): sys.stderr.write('  %-28s %s\n' % (k, v))
    else:
        sys.stderr.write('\n=== all %d instrs transpiled ===\n' % len(insns))

if __name__ == '__main__':
    main()
