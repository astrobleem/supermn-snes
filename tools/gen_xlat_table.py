#!/usr/bin/env python3
"""Generate the AOT address-translation table: 68K PC -> native escape entry.

This is the data backing `xlat_dispatch` (escbank2 $94:F900) -- the single indirection that
replaces hand-rolled per-target cmp-chains (ojmp_hook/ojmp_disp ...). PoC scope: bank-$00 PCs,
the jmp-state (no-return-push) convention class only, so routing ojmp_hook through it is
convention-safe. Wider classes (jsr/coroutine) need calling-convention unification first.

Structure (2-level page table, little-endian, placed at SA-1 $96:8000 = file $2B0000):
  offset 0:        page[256]   -- 2 bytes each; pages[PC>>8] = byte-offset of that page's
                                  sub-table within the blob, or 0 = no escapes in the page.
  offset $200..:   sub-table   -- 256 entries x 3 bytes; sub[PC&$FF] = 24-bit native addr
                                  (lo, mid, bank), or 0 = miss (interpret).
Real escape entries are at $92/$94:8000+, so a zero lo/mid never collides with a live entry.
"""
import re, sys
from pathlib import Path

# jmp-state class (convention: NO return-push; reached by `jmp (a0)` -> op_jmp_idx -> ojmp_hook).
# Historical campaign notes said $D386/$D3B0 were excluded after a co-dispatch
# divergence, but the current allowlist already enables both.  The latent cause
# was a Poppy layout overlap: $D3B0 flowed across the later fixed $92:F000
# island.  v127 keeps the $92:EFFB table entry as a trampoline to the complete
# audited body at $94:B400.  Keep the mapping enabled and let the ROM packer
# assert both sides of that seam.
JMP_STATE_PCS = {0xD5C4, 0xD0D0, 0xD6FC, 0xD386, 0xD3B0, 0xD01A, 0xD05E, 0xD0BC, 0xD07A, 0xD718, 0xD3F6}

# AOT-TABLE / rts-class entries (transpiled with transpile.py --table; faithful link/unlk/rts,
# entered via xlat_dispatch with the real return already on the 68K stack). $0CE4 = the hottest
# cluster (~12.5%), its rts reach (from $0047FE) was uncatchable by any hook -> entry_ce4t.
TABLE_PCS = {0xCE4, 0x111A, 0x295A, 0x29B6, 0x13BE,
             # Bounded one-shot round-transition initializer.  It exits at
             # the original $D9A8 allocator seam before any yielding call.
             0x00D7BE,
             # $D8AC task's yield-bounded hot path.  These callees are entered
             # with a real return already on the 68K stack; $DA44 retains that
             # real $D8B4 return across its $DA70 trap #5 yield.
             0x00D9CC, 0x00DC44, 0x00DA44, 0x00DA9E,
             0x00DAF4, 0x00DC2E,
             # $111A already has a validated hand-native implementation for
             # jsr (An).  Indexed indirect JSR reaches xlat_dispatch after its
             # real return has been pushed, so bank $95 provides the tiny
             # table-convention adapter that pops that return and reuses the
             # same body.  Missing this route left the full $114E-$11A2 loops
             # interpreted during active gameplay.
             # Production round-start pool allocators.  These are leaf/rts
             # routines reached with a real caller return on the 68K stack.
             0x024A60, 0x024A84, 0x024920, 0x024956,
             # Round-start overflow bank ($95): call/rts-class routines.  Some
             # bounded prefixes yield before their eventual rts; their real
             # caller return remains on the 68K stack across that yield.
             # Both the generated and compact $C8E0 deployments are rejected:
             # the former regressed the live transition and the latter corrupted
             # the organic task mask to $D0FF. $C9A6 remains a direct internal
             # callee, not a general table target.
             0x00C722, 0x00BBA4,
             0x00C60E, 0x00C6BC, 0x008D56,
             0x002D8A,
             # Organic gameplay-entry one-shot roots. The two bank-$02 roots
             # use the compact bank-$9D dispatcher so the dense xlat blob
             # does not grow another 768-byte page. $091E is reached by an
             # absolute-long JSR and is handled in the relocated JAH2 bank-0
             # scan, so it needs no dense table slot.
             0x024AA8, 0x028F92,
             # Stage-3 record handlers selected by the original $02E42C
             # state dispatcher.  They retain table/rts convention and use
             # the already-admitted sparse bank-$02 path.
             0x0278E8, 0x027912, 0x02F2E0,
             0x027952, 0x0279D2, 0x02F3BA,
             # Leaf record-output helpers called by those Stage-3 handlers.
             # Their native callers use faithful call bridges, so the
             # genuine return is already on the 68000 stack.
             0x027AEA, 0x027B44, 0x027B7C, 0x02F56A, 0x02F5A2,
             # Pure renderer table-pointer lookup.  Organic interpreted BSR
             # reach has a dedicated bank-$02 arm; sparse xlat covers native
             # callers that already pushed the genuine return.
             0x02E49C,
             # Residual Stage-3 counter leaf; exact CMP-X/ADDQ-CCR hand body.
             0x0296C6,
             # Stage-3 selector/address leaf with live LSL.W CCR/X at return.
             0x02E40E,
             # Stage-3 draw wrappers reached with a genuine table/rts caller
             # return.  Their nested lookup and renderer callback preserve
             # real return residue through guarded bank-$9D bridges.
             0x02E4B8, 0x02E524,
             # Full Stage-3 record selector.  Its BSR and dynamic callback
             # resume through pinned bank-$9D-to-$9F trampolines.
             0x02E42C,
             # Five-per-tick object-status routine selected indirectly by the
             # second Stage-3 record list.
             0x02E676,
             # Shared Stage-3 object bounds leaf, reached by both interpreted
             # BSR callers and the native $02F3BA parent.
             0x02F542,
             # Guarded coordinate/projectile-record update leaf.
             0x0135E0,
             # Guarded player coordinate clamp.  It is a no-call table/rts
             # leaf with exact D2 flag-bit and CCR/X preservation.
             0x013314,
             # Stage-3 player/render record update, including its exact
             # sound-queue and sprite-helper call bridges.
             0x013282,
             # Dominant Stage-3 player-state loops.  Their direct A6/A7
             # accesses are guarded, and every nested call resumes through a
             # pinned bank-$9D-to-$9F trampoline.
             0x01337E, 0x0133EA, 0x013468, 0x013538,
             # The $007734 fan-out caller pushes a genuine $007786 return and
             # enters this trap-bearing table body directly in bank $9E.
             # Keeping it in the table also covers any faithful indirect reach.
             0x008B46,
             0x8FA,   # CAMPAIGN 2 (2026-07-01): $0008FA long block-copy, jsr-reached, 446 interp-instr/heavy-tick -> entry_8fat (chokepoint allowlist)
             0xFD2,   # CAMPAIGN 2: $000FD2 = MID-LOOP RESUME of the $0FB8 fill (IRQ slices the fill; ISR-exit rte resumes at $0FD2 -- unreachable by jsr/jmp/rte tables), 595 interp-instr/heavy-tick -> entry_fd2t
             0x01F1C0} # object leaf already reached through ojmp_hook; entry_1f1c0t
             # $13BE (2026-07-01): rts-class LEAF handler added to the fetch-chokepoint allowlist (see interp choke_tramp). [$1400 dropped: it is an INTERNAL label of $13BE, covered by entry_13bet.] $0CE4 (ce4t) -- SHIPPED 2026-06-29, the first --table (rts-class) escape. Catches the
                      # rts/jmp reaches of $CE4 (~12.5% of frame) that the inline jah2 entry_ce4 (jsr-only)
                      # MISSES: an instrumented run showed entry_ce4t fires 63451x via the table.
                      # VALIDATION (full-tick lockstep_trap on a fresh 64KB $CE4-active wramB triple, ce4trip64):
                      #   ESC=0 (pure interp)         -> GREEN (1 stack byte), deterministic: tool+triple sound.
                      #   ESC=1 with ce4t (ce4=1)     -> diff set is BYTE-IDENTICAL to ESC=1 WITHOUT ce4t across
                      #     all 64KB (diff -q IDENTICAL; comm both-ways empty). ce4t adds ZERO divergence, and
                      #     its sprite-output region ($1cf6-$2600) is bit-exact vs MAME. Its body is identical to
                      #     the already-bit-exact inline entry_ce4 (only the convention differs).
                      # => ce4t is as-correct as the shipped escape set; it cannot reduce correctness below the
                      # current escapes-ON state. (single-call val_jmpstate is the wrong gate for rts-class: its
                      # jmp(a0) dispatch corrupts a0; this full-tick zero-added-divergence test is the right one.)
                      # The residual ~48-byte escapes-ON baseline ($0049 + $01B6-$01D6) is PRE-EXISTING (present
                      # in the 9-set WITHOUT ce4t, AC-invariant) -- a B1 $0708-trap boundary/timing artifact, NOT
                      # ce4t and NOT this table; tracked separately as task #73. Recipe to add more rts-class
                      # escapes: transpile <pc> --bank2 --table | sed <pc>-><pc>t, splice into escbank2, build,
                      # re-run this zero-added-divergence lockstep gate.

# COROUTINE class (transpile.py --coroutine; NO return-push; reached by op_rte resume -> ors_rte ->
# ors_rte_x -> ojmp_hook -> xlat_dispatch). c172 = first coroutine escape (TASK #73 / STEP A).
# 2026-07-03: BANK-$01 pages (object-processor A2): the table is now 512 pages, index =
# ((PC>>8) & 0x1FF) so bank-$01 resume PCs dispatch through the SAME ors_rte_x->ojmp_hook route
# with ZERO bank-$00 changes (xlat_dispatch accepts $42 in {0,1}). $01E7C0 is
# the retained objproc render visit.  The $01D5F0 physics visit remains
# assembled as forensic material, but is deliberately absent from CORO_PCS:
# its generated body did not export the final CCR/X before TRAP #5.  Organic
# MAME/native-off/native-on replay first exposed this as $F002D5 $04/$10/$00.
# Until the complete body can be regenerated flag-safely in a larger bank,
# production must interpret that resume rather than dispatch the unsafe HLE.
# (docs/history/designs/OBJECT_PROCESSOR_CAMPAIGN_20260703.md).
CORO_PCS = {0xC172, 0x01D51A, 0x01E7C0,
            # $DA44 resumes at $DA72 and immediately RTSes to the genuine
            # $D8B4 continuation.  Both are no-push coroutine continuations.
            0x00DA72, 0x00D8B4,
            0x024BC2, 0x02429C,   # trap#5 SHELL resume PCs (escbank5; bank-$02 pages)
            # Signed record path around TRAP #1.  These two exact PCs use the
            # compact bank-$9D dispatcher so bank $96 does not gain another
            # 768-byte page; their bodies live in bank $9E.
            0x024D28, 0x024D64,
            0xC604, 0xC78E, 0xCD1A,   # CP1 2.2 light-tick task resumes (escbank5)
            0xC846,                   # CP1 2.2 gameplay-tick per-slot loop resume (escbank5)
            0xC7DC,                   # post-$C7DA trap continuation; bank-$98 entry_c7dc
            0xC892,                   # post-$C890 yield continuation; bank-$98 entry_c892
            0x011752,                 # $011752 contiguous-tree spine, first half (escbank5)
            0x46DE,                   # $0046DE light-tick task resume (escbank5; first --fnfrag body)
            # Stage-3 scroll task.  The body begins immediately after an RTE
            # resume and ends by tail-entering the original TRAP #5, so it is
            # a no-return-push coroutine target.
            0x00BD1C,
            # Round-1 Stage-3 background-index task. $007AC6 is the genuine
            # post-TRAP scheduler resume; $0079FE also covers an exact IRQ
            # resume at the first loop instruction.
            0x0079FE, 0x007AC6,
            # One-shot gameplay-entry task.  Its otherwise-new $C0 page is
            # routed by the compact bank-$9D dispatcher.
            0x00C0BC,
            # Production round-start initial roots: all are op_rte/coroutine convention
            # (no synthetic return push).  $CE48 is a bounded prefix that tail-enters the
            # already deployed $CE58 continuation after clearing its frame.
            0xC262, 0xC3F6, 0xCE48, 0x8D72, 0x7C22,
            # Consecutive round-start task-creation continuations.
            0x74B8, 0x74D4, 0x74EC,
            # Sustained gameplay object-update root.  Its state dispatch is
            # guarded in bank $95 and falls back for every nonzero state.
            0x02A190,
            # Eight-slot object callback/update coroutine resumed organically
            # at $0175A0 after its setup yield.
            0x0175A0,
            # Nested callback/yield loop and its genuine return continuation.
            # Both labels live in one body so the hot backward edge remains
            # native while a callback that yields retains return $01770E.
            0x0176F6, 0x01770E,
            # Object-state coroutine resumed after the $01C118 trap #5.
            0x01C11A,
            # Fetch-choked first iteration of the guarded inactive-record pass.
            0x01C9AE,
            # Organic gameplay-entry fan-out.  The bank-$00 $76/$77 entries
            # use the compact bank-$9E dispatcher; bank-$01/$02 entries reuse
            # already-allocated dense pages.  Every TRAP remains interpreted
            # so scheduler ordering and IRQ density are unchanged.
            0x0076B6, 0x0076D4, 0x0076EC, 0x007704, 0x00771C, 0x007734,
            0x01E71E, 0x024B5A, 0x02427C,
            # Post-TRAP #5 inner-loop continuation in the bounded $8B46 task.
            0x008B9C}

# These bank-$00 entries occupy four otherwise-empty high-byte pages.  A dense
# xlat sub-table costs 768 bytes per page, so representing them in the generic
# blob would overflow bank $96 even though only eight slots are live.  The
# range arm at $94:F900 routes pages $D8/$D9/$DA/$DC to the compact dispatcher
# at $9D:DA00 instead.  Keep them in TABLE_PCS/CORO_PCS above so convention
# selection and missing-entry checks still cover them; omit only their dense
# data pages below.
DIRECT_PCS = {
    # Free the otherwise-single-entry $002D page for the Stage-3 $00BD page.
    # $2D8A is a table/rts leaf and already has an exact compact-bank target.
    0x002D8A,
    0x0079FE, 0x007AC6,
    0x00C0BC,
    0x00D7BE,
    0x00D8B4, 0x00D9CC,
    0x00DA44, 0x00DA72, 0x00DA9E, 0x00DAF4,
    0x00DC2E, 0x00DC44,
    0x024AA8, 0x028F92,
    0x0278E8, 0x027912, 0x02F2E0,
    0x027952, 0x0279D2, 0x02F3BA,
    0x027AEA, 0x027B44, 0x027B7C, 0x02F56A, 0x02F5A2, 0x02E676, 0x02F542,
    0x02E49C, 0x0296C6, 0x02E40E, 0x02E42C, 0x02E4B8, 0x02E524,
    0x013282, 0x013314, 0x01337E, 0x0133EA, 0x013468, 0x013538, 0x0135E0,
    0x024D28, 0x024D64,
    # The $0076B6 one-shot task and genuine-return continuations occupy two
    # otherwise-empty bank-$00 pages.  $94:F900 routes those pages through
    # $9D:DA00 to the exact bank-$9E dispatcher at $9E:A700.
    0x0076B6, 0x0076BC, 0x0076C2, 0x0076D4, 0x0076EC,
    0x007704, 0x00771C, 0x007734, 0x007748, 0x00776A,
    0x00777A, 0x007782, 0x007786,
    # Free one dense page for the $008Bxx continuation cluster.  Bank-$02 is
    # already admitted to $9D:DA00, so these two exact production allocators
    # are cheaper as sparse comparisons than as a 768-byte page.
    0x024920, 0x024956,
    # Bank $02 already routes through the sparse dispatcher.  Move this lone
    # page-$2A1 entry out of the dense blob to make room for $01C9xx without
    # increasing the fixed forty-page bank-$96 footprint.
    0x02A190,
    # Correct bank-$01 landing/combat returns would each consume a new
    # 768-byte dense page.  Route both exact PCs through the sparse dispatcher.
    0x011BDC, 0x011C9A,
}

JMP_STATE_PCS |= {0x01177C}   # $011752 spine second half: reached by the hle_12b6c rts POP (op_rts_norm -> xlat)
# These are genuine BSR returns from hle_12b6c.  The old hard-coded $01177C
# shortcut hid them; the corrected HLE now materializes the actual caller.
JMP_STATE_PCS |= {0x011BDC, 0x011C9A}
JMP_STATE_PCS |= {0x3B48, 0x3B58, 0x3B70}   # $3B48 GAME_TICK prologue fragments (3B48 = choke ct_ext arm; 3B58/3B70 = header-callee rts pops)
JMP_STATE_PCS |= {0x075C, 0x077A}   # sched plumbing: first task-SELECT + the trap-handler DEFER entry (choke ct_ext arms)
# Genuine-return continuations inside the native $0175A0 coroutine.  The
# callees see/preserve real $0175E8/$017612 stack values; their RTS reaches
# these bare no-push labels through op_rts_norm -> xlat_dispatch.
JMP_STATE_PCS |= {0x0175E8, 0x017612}
# Genuine RTS return from the already-native $01F2E4 allocator into the
# one-shot object initializer.  The caller return is gone, so this is a bare
# no-push continuation rather than a table/rts-class entry.
JMP_STATE_PCS |= {0x01D53A}
# Genuine returns inside the one-shot fan-out bodies.  The real return has
# already been consumed, so each continuation is a bare no-push entry.
JMP_STATE_PCS |= {
    0x0076BC, 0x0076C2,
    0x007748, 0x00776A, 0x00777A, 0x007782, 0x007786,
    0x01E772, 0x01E7B0,
    0x024BAA,
    0x0242BE,
    0x024282, 0x024288, 0x02428E, 0x024294,
    0x008B72,
}

ALLOWED_PCS = JMP_STATE_PCS | TABLE_PCS | CORO_PCS
assert 0x01D5F0 not in ALLOWED_PCS, (
    "$01D5F0 native physics coroutine is parked until its trap CCR/X "
    "contract is regenerated and organically revalidated"
)
BANK_OF_SYM = {"src/escbank.sym": 0x92, "src/escbank2.sym": 0x94,
               "src/escbank3.sym": 0x97, "src/escbank4.sym": 0x98,
               "src/escbank5.sym": 0x99, "src/escbank6.sym": 0x95,
               "src/escbank7.sym": 0x9D, "src/escbank8.sym": 0x9E,
               "src/escbank9.sym": 0x9F}

def load_native_addrs():
    """entry_X -> 24-bit native address (bank forced per source bank)."""
    out = {}
    for sym, bank in BANK_OF_SYM.items():
        p = Path(sym)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            # Require the complete symbol token.  Prefix-matching
            # ``entry_c262_generated_resume`` as ``entry_c262`` silently
            # replaced the guarded $C900 wrapper with its $C906 fallback seam.
            m = re.match(
                r"\s*[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+"
                r"(entry_[0-9a-z]+)(?:\s|$)",
                line,
            )
            if m:
                out[m.group(2)] = (bank << 16) | int(m.group(1), 16)
    return out

def load_entry_pcs():
    """entry_X -> 68K PC, from the `transpiled from $XXXXXX` comment preceding each label."""
    out = {}
    for f in ("src/escbank.pasm", "src/escbank2.pasm", "src/escbank3.pasm",
              "src/escbank4.pasm", "src/escbank5.pasm", "src/escbank6.pasm",
              "src/escbank7.pasm", "src/escbank8.pasm",
              "src/escbank9.pasm"):
        last = None
        for ln in Path(f).read_text().splitlines():
            m = re.search(r"transpiled from \$([0-9A-Fa-f]+)", ln)
            if m:
                last = int(m.group(1), 16)
            m2 = re.match(r"(entry_[0-9a-z]+):", ln)
            if m2:
                out[m2.group(1)] = last
                last = None
    return out

def main():
    native = load_native_addrs()
    pcs = load_entry_pcs()
    # select the entries that are present + resolved. A PC can have TWO transpiled bodies: a jsr-conv
    # `entry_<hex>` (escbank, jah2-dispatched) AND a table-conv `entry_<hex>t` (escbank2). For TABLE_PCS
    # the table MUST point at the table variant (no-push, return on stack); for JMP_STATE_PCS at the bare
    # name. Pick deterministically by name (don't rely on $94>$92 address ordering).
    bypc = {}    # pc -> list of (name, addr)
    for name, pc in pcs.items():
        if pc in ALLOWED_PCS and name in native:
            bypc.setdefault(pc, []).append((name, native[name]))
    pairs = []   # (pc, native_addr, name)
    for pc, cands in bypc.items():
        want_table = pc in TABLE_PCS
        pick = None
        for name, addr in cands:
            is_table = name.endswith('t')
            if is_table == want_table:
                pick = (pc, addr, name); break
        if pick is None:
            pick = (pc, cands[0][1], cands[0][0])   # fallback: whatever resolved
        pairs.append(pick)
    pairs.sort()
    c262 = [addr for pc, addr, _name in pairs if pc == 0xC262]
    assert c262 == [0x99C900], (
        "$C262 xlat entry must target the guarded $99:C900 wrapper, got %r" % c262
    )
    ret_242be = [
        (addr, name) for pc, addr, name in pairs if pc == 0x0242BE
    ]
    assert ret_242be == [
        (native["entry_242be"], "entry_242be")
    ], (
        "$0242BE must return from interruptible $025110 through its exact "
        "bank-$99 continuation, got %r" % ret_242be
    )
    if len(pairs) != len(ALLOWED_PCS):
        got = {p for p, _, _ in pairs}
        print("gen_xlat_table: WARNING missing jmp-state entries: %s"
              % [hex(x) for x in ALLOWED_PCS - got], file=sys.stderr)

    direct_pairs = [item for item in pairs if item[0] in DIRECT_PCS]
    assert len(direct_pairs) == len(DIRECT_PCS), (
        "direct xlat entries missing: %s" % sorted(DIRECT_PCS - {p for p, _, _ in direct_pairs})
    )
    pairs = [item for item in pairs if item[0] not in DIRECT_PCS]

    # build the page table: 768 pages, index = (bank<<8)|(PC>>8) (bank 0/1/2 —
    # xlat_dispatch accepts $42 in {0,1,2} and merges bank<<8 into the page index)
    for pc, _, _ in pairs:
        assert (pc >> 16) <= 2, "xlat table PC $%06X: only banks 0/1/2 supported" % pc
    PAGE_BYTES = 768 * 2
    page_off = {}                       # page index -> sub-table offset in blob
    for pc, _, _ in pairs:
        hib = (pc >> 8) & 0x3FF
        page_off.setdefault(hib, None)
    # allocate sub-tables after the page array
    cur = PAGE_BYTES
    subtab = {}                          # hibyte -> bytearray(256*3)
    for hib in sorted(page_off):
        page_off[hib] = cur
        subtab[hib] = bytearray(256 * 3)
        cur += 256 * 3
    # fill sub-table entries
    for pc, addr, name in pairs:
        hib, lob = (pc >> 8) & 0x3FF, pc & 0xFF
        st = subtab[hib]
        st[lob*3+0] = addr & 0xFF
        st[lob*3+1] = (addr >> 8) & 0xFF
        st[lob*3+2] = (addr >> 16) & 0xFF
    # assemble blob
    blob = bytearray(cur)
    for hib, off in page_off.items():
        blob[hib*2+0] = off & 0xFF
        blob[hib*2+1] = (off >> 8) & 0xFF
    for hib in subtab:
        off = page_off[hib]
        blob[off:off+256*3] = subtab[hib]
    assert len(blob) <= 0x8000, "xlat table %d bytes overflows $96:8000 bank" % len(blob)

    Path("src/xlat_table.bin").write_bytes(blob)
    print("gen_xlat_table: %d dense entries + %d direct entries, %d pages, %d bytes "
          "-> src/xlat_table.bin (@ $96:8000)"
          % (len(pairs), len(direct_pairs), len(page_off), len(blob)))
    for pc, addr, name in pairs:
        print("    $%06X -> $%06X  [%s]  page $%03X off $%04X" % (pc, addr, name, (pc>>8)&0x3FF, page_off[(pc>>8)&0x3FF]))
    for pc, addr, name in direct_pairs:
        print("    $%06X -> $%06X  [%s]  direct $9D:DA00" % (pc, addr, name))

if __name__ == "__main__":
    main()
