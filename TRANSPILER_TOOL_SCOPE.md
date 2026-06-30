# Transpiler tool — scope & plan

> **STATUS: DONE (June 25, 2026).** `tools/transpile.py` is built and validated bit-exact
> (reproduces `entry_ce4`/`entry_111a`). All milestones below are met: skeleton → reproduce the
> oracles → bridge codegen (`$025110` collision, 2 bridged calls) → `--video` shadow stores
> (`$0020e8`). 8 escapes deployed in bank-$00 gaps; the multi-bank fallback (risks below) proved
> unnecessary. Live state of the tool: `transpiler-tool` memory. Forward plan: [ROADMAP.md](ROADMAP.md).


Automate what `entry_ce4`/`entry_111a` were done by hand: emit a native 65816 escape
(`entry_<addr>`) for a 68K function, leaf **or** non-leaf (calls via the call-bridge).
Hand-transpilation tops out around icount ~60; the remaining hot mass is bigger
(`$025140` icount 541, `$002xxx`), so codegen must be a tool.

The codegen rules are already settled in `TRANSPILER_DESIGN.md` (D1 branch/carry lowering,
D2 reg file, D3 endianness, D4 address map) and `CALL_BRIDGE_DESIGN.md` (D5 hook + bridge).
This tool **implements** them. Reference oracles: the hand-written, MAME-validated
`entry_ce4`/`entry_111a` — the tool must reproduce them bit-exact.

## I/O
- **In:** ROM (`build/interp.sfc`, 68K at file `$10000`) + a function entry address.
- **Out:** a `.pasm` fragment — `entry_<addr>:` + the native body + helper labels, plus the
  one-line `jsrabs_hook2` dispatch entry to add. Pasted into `src/interp.pasm` ($F-headroom),
  assembled by `tools/build_interp.sh`.
- **Tool:** `tools/transpile.py` (Python + capstone, already in use).

## Pipeline
1. **Decode** the function linearly (entry → `rts`) with capstone; record byte offsets.
2. **Blocks/labels:** collect intra-function branch targets → `L_<addr>` labels. A branch
   *out* of the function (shared tail, jump table) → **hard error** (don't emit wrong code).
3. **Codegen** each instruction (tables below) onto the **real reg file `$00-$3C`** (D2 — not
   scratch, so bridges see live state). Track which flags each op sets.
4. **Calls** (`jsr`/`bsr`/`jsr(An)`): emit the bridge sequence (push args replicating the
   preceding stack moves + a `$00FF:cont` sentinel; set PC=callee; `jmp inext`; `cont:` resume) —
   the validated `entry_bridgeproof` shape.
5. **Entry/exit:** save the hook's return; replicate `link`/`movem` (incl. the **movem.w
   sign-extension** on `d0-d6` restore); set clobbered `d7`; end `jmp inext` at the saved return.
6. **Emit** + suggest the dispatch line.

## Codegen tables (the implementation surface)
- **EA_LOAD[mode] → value in A** (source operand): `Dn`→`lda $<4n>`; `(An)`/`(d16,An)`→
  `lda $<An>;[clc;adc #d16;]tax;jsr rdw40` (work RAM) or `ce_rdw`/`readbyte` (ROM ptr `a0`);
  `(An)+`→load then bump An; `imm`→`lda #imm`; `abs`→`lda $40<abs>`; `(d16,PC)`→resolved const.
- **EA_STORE[mode]** (dest): address into X, `jsr wrw40`; `Dn`→`sta $<4n>`; `(An)+`→store+bump;
  `-(An)`→predecrement An then store — incl. **`move.l → -(An)` push-long** (added 2026-06-30 in
  `store_long_from`; unblocked `$46DE`); read-modify-write (`andi (a3); or d,(a3)`) →
  load/modify/store (the entry_111a Y-write).
- **OP[mnemonic.size]:** `move/movea` (+NZ, V=C=0); `add/addi/adda/sub/subi/subq/neg/cmp/cmpi/
  tst/clr` (set NZVCX per D1 — **subtract/compare carry is INVERTED vs 68K**, V is the CMP
  trap); `and/or/andi/ori/eor` (NZ, V=C=0); `lea` (no flags). `.b`/`.w`/`.l` size variants.
- **BRANCH[cc]:** `beq/bne` read `$60`(Z); `bmi/bpl` read `$70`(N); **signed `bge/blt/ble/bgt`
  synthesised** with the `bvs`/`bpl`/`bmi` idiom (D1, the H1 hazard — already proven in
  entry_ce4); `bcc/bcs` read `$6E`(C) honouring the inversion; `dbra`=dec+cmp #$FFFF+branch.
  Long branches → `jmp` trampoline (else 65816 ±128 fails).
- **FLAGS:** snippet emitters — `Z`(`$60`), `N`(`$70`=$8000?), `C`(`$6E`), `V`(`$72`), `X`(`$A2`)
  — invoked per op's effect set; CCR only materialised when a later branch consumes it.

## Safety: fail loud, never wrong
Any unhandled op, addressing mode, out-of-function branch, indirect jump, or I/O write (video
bank `$B0/$D0/$E0`) → **raise, don't emit**. The tool grows op coverage on demand; it must never
silently mis-transpile. (I/O writes need the `map_snes` video-shadow path — out of v1 scope;
`$002xxx` waits for that.)

## Verification & milestones
1. **Skeleton:** decode + blocks + entry/exit stub for `$000CE4`; assembles.
2. **Reproduce `entry_ce4`** ($000CE4) and **`entry_111a`** ($00111A) — tool output validated
   **bit-exact** via the fresh-adjacent-tick pipeline (frame-900 + flying-stage). This is the
   gate: same behaviour as the hand oracles ⇒ codegen is correct.
3. **Bridge codegen:** transpile a small non-leaf, validate (bridge plumbing already proven).
4. **`$025140`** (~12.6%, 2 calls: `$0184E8` leaf, `$025A40` indirect-callee → both bridged) —
   validate vs MAME.
5. **`$002xxx`** (~10%) — after adding video-shadow store support.

## Risks
- **D1 carry/V/signed-branch** lowering — the subtlest; oracle-checked against entry_ce4's
  validated clamps.
- **movem.w sign-extension** and other epilogue side effects (the entry_111a lesson) —
  reproduce every register effect the caller/callee observes.
- **Reg-file sync at bridges** — non-leaf codegen writes live regs (D2), so it's automatic.
- **Op-coverage creep** — keep the fail-loud guard; grow tables only as targets demand.
