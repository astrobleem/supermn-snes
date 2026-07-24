# Call-Bridge: transpiling non-leaf 68K functions

## Problem

The native-escape mechanism (`jsrabs_hook2` → `entry_XXX` → `jmp inext`) only handles
**leaf** functions: self-contained code with no `jsr`/`bsr`, no indirect jumps, no I/O.
The remaining gameplay-hot mass is **non-leaf**:

| target | %frame | shape |
|---|---|---|
| `$025140` (collision detect) | ~12.6% | icount 541, **2 calls**: `$0184E8` (leaf, icount 19), `$025A40` (icount 23, 1 indirect) |
| `$002xxx` | ~10% | non-leaf + video-bank I/O |

A non-leaf escape, mid-execution, reaches a `jsr callee`. We need the native code to run
the 68K callee and resume. Two options:

- **Inline (escape-with-callees):** transpile the whole call tree into one native blob.
  Rejected as the general mechanism — call trees explode, callees are shared / have
  indirects / I/O / recursion (e.g. `$025A40`'s indirect jump). Doesn't scale.
- **Bridge (hybrid):** transpile only the hot function; at each call site, hand control
  **back to the interpreter** to run the callee, then resume native via a continuation.
  This is the project thesis (transpile-hot / interpret-cold) applied to the call graph.
  **Chosen.**

## Core mechanism: sentinel returns + `op_rts` dispatch

The interpreter already runs 68K `rts` (`op_rts`: pop 4-byte return → PC). We exploit that
as the resume point.

- **Sentinel bank `$FF`.** Reserve 68K bank `$FF` (no real ROM/RAM there) for continuation
  return addresses. A sentinel return = the 32-bit value `$00FFcccc`, where `cccc` is the
  **65816 address** of the native continuation (continuations live in the interp's code bank
  `$00`, in the `$F000`–`$F6FF` escape headroom). So the sentinel *is* the continuation
  address — **no continuation table needed.**

- **`op_rts` check (the only interp-core edit).** After popping the return into PC
  (`$40`=lo16, `$42`=hi16):
  ```
  op_rts:
      jsr pull32_to_pc            ; existing: $40/$42 = return
      lda $42
      cmp #$00FF                  ; sentinel?  (real banks are $00-$07 ROM / $00F0 work RAM)
      bne op_rts_done             ; no -> normal return
      jmp ($0040)                 ; yes -> jmp to [the value in $40] = the native continuation
  op_rts_done:
      jmp inext
  ```
  Cost: ~3 instructions, and only on `rts` (far colder than `inext`; we never touch the
  hot per-instruction path). Mirror the same 4 lines into `op_rtr` (rts+CCR restore) since a
  callee could return via `rtr`; `rte` is interrupt-only and out of scope.

## The bridge sequence (native side, at a call site)

The native function reaches a 68K `jsr callee`. It replicates exactly what the 68K caller's
`jsr` + preceding arg pushes do, but substitutes a sentinel return:

```
; 1. push the callee's args onto the 68K stack (A7 @ $3C), big-endian, exactly as the 68K
;    `move.w/.l <arg>,-(a7)` instructions before the jsr would. (Use push16/push32 helpers.)
; 2. push the SENTINEL return:  push32  $00FF:<cont_label>
;        cont_label = the 65816 address of the resume point below.
; 3. set PC:  $40 = <callee lo16> ; $42 = <callee hi16>
; 4. jmp inext                    ; the interpreter now runs the callee
cont_label:                       ; <-- op_rts jmps here when the callee returns
; 5. (caller-cleanup if any: addq #n to A7) ; read callee results from the reg file (D0/D7...)
; 6. continue the transpiled function
```

## State model — the key difference from leaf escapes

Leaf escapes keep working registers in **DP scratch** (`$80–$9E`) and never touch the reg
file, for speed. **Non-leaf escapes must operate directly on the reg file** (`D0-D7`@`$00`,
`A0-A7`@`$20`), because at every bridge the interpreted callee reads the live 68K registers
and the 68K stack. Practical rules:

- **Registers:** mutate `$00–$3C` in place, exactly as the function does. (Same DP cost as
  scratch; no penalty — the native code is essentially a compiled, branch-flattened version
  of the function's instruction stream over the same state.)
- **Stack (A7 @ `$3C`):** the native code performs the function's `link`/`unlk`, arg pushes,
  and local-frame moves against the real 68K stack in work RAM, so A7 and the frame are
  exactly what the callee expects. After a bridged call, A7 is back to its pre-call value
  (callee popped its frame; its `rts` popped our sentinel).
- **Flags (`$60`=Z `$6E`=C `$70`=N `$72`=V, X@`$A2`):** only sync if a callee or post-call
  branch reads them; collision-style callees take args in regs/stack, so usually moot. Set
  them when the transpiled instruction stream's CCR is observably consumed.
- **Entry/exit:** the hook enters `entry_XXX` with PC already = the **function's** return
  (caller's next instr). Save that return at entry (a scratch slot); restore it before the
  final `jmp inext`, because the bridges overwrite PC. The native function never executes a
  68K `rts` itself — it ends with `jmp inext` at the saved return, like a leaf escape.

## Nesting & recursion — free, via the 68K stack

Sentinels live on the 68K stack (LIFO). If a callee is itself a bridged native function, it
pushes its own sentinel on top; each `rts` pops exactly one and `op_rts` routes it to the
right continuation. Recursion and arbitrary call depth work with no extra bookkeeping —
the 68K stack *is* the continuation stack.

## Worked example: `entry_25140` (`$025140`, ~12.6%)

1. Hook `$025140` into `jsrabs_hook2` like the leaf escapes (confirm its call form first).
2. Transpile the bounding-box collision logic straight onto the reg file (it's mostly
   `cmp`/`move`/branch over `(a0)`/`(a1)` fields — mechanical).
3. **Call site 1** `$025986` → `$0184E8` (leaf): bridge. (Could alternatively inline this one
   since it's a clean leaf — but bridge first for uniformity, optimize later.)
4. **Call site 2** `$0259A6` → `$025A40` (has an indirect): **must** bridge — don't try to
   inline an indirect-jump callee.
5. Each bridge pushes that call's args + a sentinel; `op_rts` resumes the right continuation.

## Validation & rollout

- **Same fresh-adjacent-tick pipeline** (`extract_flytick`/`flyval`, NOT sparse capture):
  inject MAME frame A, run one tick hook-ON vs OFF, both vs MAME `wramB`; require
  `ON-vs-OFF = 0` and `ON-vs-MAME = sound baseline`. Callees run interpreted (correct by
  construction), so this validates only the native glue + bridge plumbing.
- **Incremental bring-up:**
  1. Land the `op_rts`/`op_rtr` sentinel check; verify transparent (no sentinel in flight →
     opsweep 782/782, existing escapes unchanged).
  2. First bridge target: a non-leaf with ONE call to a LEAF (simplest). Validate.
  3. Then `entry_25140` (2 calls). Then the `$002xxx` I/O subsystem (adds video-shadow
     handling on top of the bridge).

## Risks / open questions

- **`op_rts` cost** — measured-negligible (3 instrs, returns only), but confirm no
  hot-loop tail-call pattern abuses it.
- **Reg-file sync correctness** — the `movem.w` sign-extension lesson (entry_111a) applies:
  faithfully replicate every register side effect the callee or post-call code observes.
- **Sentinel collision** — bank `$FF` must never be a real address the game uses; verify
  superman's map (ROM `$00-$07`, work RAM `$F0`; `$FF` is free). If not, pick another
  unused bank.
- **Callee with I/O / its own indirects** — fine: it runs interpreted, which already handles
  those. The bridge is agnostic to what the callee does.
- **Non-rts returns** (`jmp (a7)+`, `rtd`) — rare; audit the callees. `$025140`'s callees use
  normal `rts`.
