# 68000 Interpreter Spike — Result: GREEN

> **UPDATE (June 19, 2026): IT'S ALIVE — boots to the live per-frame game loop.**
> The interpreter now boots Superman all the way into its **live cooperative
> scheduler + per-frame game loop** on real SNES hardware. Past `$0818`: it creates
> both scheduler tasks (`tmask=$0003`, matches MAME), downloads and executes the
> C-Chip **GWK RAM-resident routine** (`$F01B20`), runs init, and cycles through
> 26+ game PCs/sec with the per-frame counter (`$F01C56`) incrementing and work RAM
> evolving every frame.
>
> The multi-session `$0818` freeze root cause was a chain: (1) VBLANK cadence too
> fast (`$8A $1800→$7000`) interrupted trap#1 task creation; (2) a reset-time
> `($F00006)` bootstrap hack corrupted A5; (3) **the keystone: `op_movb_d16_d16`
> never set the Z flag** — the VBLANK ISR's `move.b ($0,A5),($1,A5); bne` relied on
> it, so a stale Z drove the ISR into a context-save that splattered the task mask
> (`$0001→$16CC`) and the scheduler could never find slot0. Setting Z unblocked the
> switch. Then ~20 boot-exercised addressing modes were added one at a time (jmp
> (d16,An) + work-RAM-PC fetch, cmpi.b/.l, several move.l/.w/.b modes, movem.w, clr
> variants, an addq/subq `(d16,An)` dispatch-mask fix, a sprite-copy `$B00000`
> bank-gate, and move.w (An)+,(An) which was the final freeze). The cooperative
> scheduler / `$F0xxxx` task model and the video-write findings are in
> **`VIDEO_PLUMBING.md`**; debugging memory in `phase-a-blocker.md`. Next phase is
> video plumbing (the game runs blind — hardware-bank writes are no-op'd).

> **UPDATE (June 18, 2026): the spike graduated into a complete interpreter.**
> What began as a 5-opcode reset-handler spike is now the **full legal MC68000
> instruction set** — 47/47 operation groups, implemented and validated one at a
> time against MAME via `tools/optest.py` (**154/154 single-instruction
> differential vectors green**), with a full-boot regression after each batch.
> Batches: B1 CCR/SR-imm · B2 logical-EA · B3 add/sub/cmp + extended · B4 BCD ·
> B5 shifts/rotates · B6 bit-ops + Scc + DBcc · B7 MULU/MULS/DIVU/DIVS/CHK +
> exception traps · B8 control/system (ILLEGAL/TRAPV/RESET/STOP/RTR/EXG/TAS/
> MOVE-from-SR/to-CCR/to-SR/MOVE-USP/MOVEP) · B9 decode-chain audit. New ops route
> through a shared effective-address engine; the original game-path handlers are
> untouched. Boot is healthy (steady-state PC `$0818`). One documented limitation:
> illegal EA encodings are executed rather than illegal-trapped (see
> [ROADMAP.md](ROADMAP.md) → Known limitations). The notes below are the original
> spike record.

Date: June 17, 2026
Outcome: **a 65816 interpreter executes the real Superman 68K code on a real SNES
PPU/CPU (Mesen) and matches MAME's reset-handler trajectory exactly.** This proves
the "interpret-cold" half of the interpret-cold / transpile-hot **hybrid** is
viable — the fastest path to an end-to-end boot (a ramp, not a cliff).

## What runs
`src/interp.pasm` is a 65816 (SA-1-class) interpreter that:
1. **Fetches** real Superman 68K opcodes (big-endian) from the program ROM
   (a slice embedded at SNES ROM offset $2000 / CPU $A000),
2. **Decodes** five opcode forms used by the reset handler — `lea (xxx).L,An`,
   `move.w #imm,(xxx).L`, `move.w #imm,Dn`, `clr.l (An)+`, `dbra Dn,disp`,
3. **Executes** them (68K regs in direct page per `TRANSPILER_DESIGN.md` D2;
   I/O / memory writes are no-ops — the PC trajectory is what we validate),
4. **Logs** each executed PC to WRAM for differential checking.

## Validation (vs MAME, the independent oracle)
Run on real SNES, the interpreter reproduced MAME's reset trajectory from
`probe_trace.log`:
- First 32 logged PCs **exact match**: `3EF0 3EF6 3EFE 3F06 3F0E 3F16 3F1E 3F26
  2F2E… 3F46 3F4A 3F50 3F52 3F50 3F52 …` (init + the work-RAM clear loop iterating
  — `dbra` branch-taken).
- **Both 4096- and 256-iteration clear loops terminated correctly** and execution
  reached **PC=$3F6A** (the first opcode outside the subset, `move.l`) after
  **exactly 8,720 interpreted instructions** = 13 init + 8,192 (loop 1) + 2 + 512
  (loop 2) + 1. Stop code `$DEAD` (clean unknown-opcode halt).

Exact instruction count + trajectory match = fetch, decode, execute, **and control
flow** (branch-taken and loop-exit) all correct.

## Why it matters
The project's central unknown was "will the 68K game logic run on the SA-1 at all?"
This answers yes for the interpret path: real game code, real hardware, exact match.
It also gives a second oracle for the transpiler and de-risks the hybrid strategy.

## Increment 3 — real memory + the RAM test (GREEN)
Extended the interpreter to a **real memory model** (68K work RAM `$F0xxxx` → SNES
bank `$7F`) plus ~17 opcodes / 5 addressing modes (`(An)`, `(An)+`, `(d16,An)`,
`Dn`, `#imm`), software Z-flags, and conditional branches (`bne`/`bra`). It then
executed the reset handler's **work-RAM test** — four sub-tests (`$00`/`$FF`/`$AA`
fill+verify and the walking-bit test) that write patterns and **read them back** —
and reached **PC=$4008** (the first unimplemented opcode, `move.w #imm,(d16,A5)`)
after **~1.09M interpreted instructions**, stop code `$DEAD`. Crucially it reached
`$4008` via the *success* branch (`bra $4008`), not any error target, so every
`cmp.b` readback matched: the memory model, opcodes, addressing modes, flags, and
branches are all correct. The interpreter now runs real, data-dependent game code.

Bug caught en route (classic 68K encoding gotcha): for `subq`/`lsr` the count is in
opcode bits 11-9 but the **register is bits 2-0** — using the wrong field left a
loop counter never reaching zero (stuck). Also: a DP-overlap in the 32-bit step
counter; both fixed.

## Increment 4 — calls, stack, the C-Chip gate, and the slice boundary
Added `jsr (xxx).L` / `bsr` / `rts` with a real 68K stack (A7 in work RAM),
`cmpi.b #imm,(xxx).L`, `beq`, `move.w #imm,(d16,An)`, and an I/O-aware byte read
(C-Chip `$900803 → $01`, our patch-not-emulate resolution — in the interpreter).
Fast-started at `$4008` (RAM test already proven) it executed the A5-relative init
and `jsr $2ae2` with an **exact MAME trajectory match** (`$4008,$400E,…,$404E,$2AE2`)
— the call jumped correctly (stack push works).

**Architectural boundary hit:** it then stopped at `$2AE2` because that address is
**outside the loaded ROM slice**. The restart-free harness patches only the 32 KB
cart, which holds the reset handler's *local* code (`$3E00–$41FF`); but the boot
path `jsr`/`jmp`s across the whole 512 KB 68K ROM (`$2ae2`, `$716`, `$8fa`,
`$ae0a`, …). The interpreter is correct — it just can't fetch code it doesn't have.

**Next phase = full-ROM harness.** To follow cross-ROM control flow toward the main
loop, build a proper SNES/SA-1 ROM that embeds the **entire 512 KB 68K image** +
the interpreter, and load it in Mesen (set `MESEN_ROM` + restart — the 32 KB
patch trick can't hold 512 KB). Map fetch + the byte-read helper to read the full
image. Then the interpreter can run `$2ae2` (C-Chip gate passes via `$900803→$01`),
return, and continue toward `jmp $716` (the main entry). The hard mechanisms
(fetch/decode/execute, control flow, real memory, stack, I/O) are all proven; this
is a harness change, not new interpreter logic.

Bug caught this increment: `move.w #imm,(d16,An)` is 6 bytes (opcode+imm+d16), not 8.

## Full-ROM harness — works, passes the C-Chip gate (GREEN)
`tools/build_interp_rom.py` → `build/interp.sfc`: 1MB **HiROM** = interpreter at
file $8000 + the **entire 512KB 68K image** at file $10000 (CPU $C1:0000, flat — 68K
addr A reads at `$C10000+A`). Fetch reworked to a 24-bit pointer (`$56=$C10000+PC`,
indirect-long `lda [$56],y`; operands via `rdw2/rdw4/rdw6`). Loaded via `MESEN_ROM`
(needs a restart); thereafter the interpreter region (file $8000) is still
patch-iterable via `write_memory(snesPrgRom,$8000)` + reset (image stays).

With the full image fetchable, the interpreter (fast-start $4008) **follows
cross-ROM control flow and passes the C-Chip self-test**: init → `jsr $2ae2` →
gate (`cmpi.b $900803`→`$01`, `beq $2b16` not taken = no hang, `bne $2ae2` not
taken = no spin) → `bsr $2b18` (word form) → `$2B18`. Stops at `$2B18` = `clr.w D0`
($4240), the next opcode to add. This proves the harness + the C-Chip
patch-not-emulate plan end-to-end in the interpreter. Bugs fixed: `cmpi.b (xxx).L`
= `$0C39` (not `$0C38`); `bsr` word form (`$6100`+disp16).

**Next:** add the command-sequence + main-init opcodes (`clr.w`, `move.w #imm,-(An)`
push, `adda.l #imm,An`, `move.b #imm,(xxx).L`, the `$2bc2/$2baa/$2bf0` command-port
writes + polling — watch the poll on `$900007`), then `jmp` (word/abs) toward
`jmp $716` (main entry) and the main loop.

## Through the C-Chip boot handshake (GREEN, June 17)
Added 11 opcodes (`clr.w Dn`, `move.w #imm,-(An)`, `adda.l/.w #imm,An`,
`move.w (d16,An),Dn`, `move.w Dn,(d16,An)`, `move.b (An),(An)+`, `move.b Dn,(xxx).L`
[tracks the `$900C01` command], `move.b #imm,(xxx).L`, `nop`, `jsr (d16,PC)`) +
fixes: `op_lea_abs` now actually stores `An` (the `$2BAA`/`$2C46` loops use `A0`);
`op_movb_dn_an` guards I/O writes (no-op outside `$F0xxxx`); and a **C-Chip
command/response replay** in `readbyte` (`buffer[cmd][(addr&0x1FF)/2]`: cmd 2 →
`$47/$57/$4B`, cmd 1 → the 256-byte `RESP1` block embedded via `.incbin`). Toolchain:
`tools/build_interp.sh` (poppy .NET 10 → `interp.bin` → `interp.sfc`).

Bug caught: `readbyte`'s data path stored the index in `$50`, clobbering the
immediate that `op_cmpib_abs` parks there → the gate `cmpi.b` compared against the
index, looping forever at `$2C16`. Moved the index to `$64`.

Result on real SNES (Mesen): the interpreter **clears the whole C-Chip boot
handshake** — the 3-byte gate (`$47/$57/$4B`) AND the 256-byte block download
(index reached `$FF`) — returns through the `rts` chain, and runs on into the reset
init, executing the real `movea.l A4,A5` at `$416A`, stopping at **`$417C` =
`move.b ($500001).L,D0`** (`$1039`, the next unimplemented opcode — a `$500000`
hardware-port read). Stop code `$DEAD` (clean). ~25.5k interpreted instructions
from `$4008`. The C-Chip "patch + replay, no MCU emulation" plan is now proven
end-to-end through boot.

## Copy dest PINNED + faithfulness PROVEN vs MAME (June 17)
Fixed the fast-start to preset ALL 16 regs to MAME's exact `$4008` state
(`regs_at_4008.log`): D0=`$3FFE`, D6=`$FFFF`, D7=`$4`, A0=`$F00000`, A1=`$F03FFE`,
A5=`$F00000`, A7=`$0` (rest 0). The earlier divergence was entirely a preset bug
(I had A7=`$F03FFE`; that value is actually A1, and A7 starts `0`).

After the fix, MAME register taps (`regs_at_417c.log`) confirm the interpreter
matches MAME **exactly** at `$417C`: A5=`$00F00000`, A0=`$00900201`,
A1=`$00F01C20`, D6=`$FFFF`, rest 0. **Copy dest verified:** at `$2C50` A5=`$F00000`,
so the 256-byte block lands at 68K `$F01B20` (→ `$7F1B20`); a CPU-bus read there
returns the RESP1 bytes exactly. (My earlier "garbage" reads were my own address
arithmetic — `$7F1B20` = snesWorkRam offset `0x11B20`, not `0x11D20`.)

**MAME Lua A7 caveat:** MAME's `cpu.state["A7"]`/`USP` reads return `0` even where a
return is provably on the stack (verified at `$2B14`). So MAME's A7 is unreliable in
Lua; my interpreter's A7 (e.g. `$FFFC` = one pending `bsr`) is the correct value.
Don't diff A7 against MAME's Lua readout.

Then added `move.b (xxx).L,Dn` (`$1039`), `andi.b`, `or.b`, `lsl.b`, and a
`$500000` DIP/input read (`$0F`, MAME ground truth). The interpreter now runs the
**DIP-read routine** at `$4178` (reads `$500001/3/5/7`→`$0F`, packs to D0/D1=`$FF`,
stores `($1C4A/$1C4C,A5)`), returns, and stops at `$405C` = `andi.w #imm,D1`
(`$0241`), ~25.6k instr, all regs still matching MAME.

**Roadmap to the main loop:** the init reaches `$40EA` = `jmp ($716).L` (the main
entry) but first `jsr $8FA / $AE0A / $2D38 / $5BC8`. Reaching `$716` needs the
opcodes in those subroutines too.

## Into the init subroutines — still MAME-exact (June 17)
Added the linear `$405C..$4072` batch + a **`readbyte` ROM path** (addr<`$80000`
reads `$C10000+addr`): `andi.w`(`$0240`), `lsl.w`(`$E148`), `lea (d16,PC),An`
(`$41FA`), `adda.w Dn,An`(`$D0C0`), `move.w (An),(d16,An)`(`$3150`), `pea`(`$4879`),
`move.l #imm,(d16,An)`(`$217C`), `btst #imm,(d16,An)`(`$0828`), `move.l (An)+,(An)+`
(`$20D8`, I/O-aware src), `subq.w`(`$5140`), `clr.w (d16,An)`(`$42A8`). The
interpreter runs the linear init and `jsr $8FA`, stopping at `$08FA` = `link A6,#imm`
(`$4E56`). **Verified vs MAME (`regs_at_8fa.log`): ALL registers match** —
D0=`$FF`, D1=`$06`, D6=`$FFFF`, A0=`$00004176` (the computed `lea`+`adda.w` result),
A1=`$00F01C20`, A5=`$00F00000`; A7=`$FFF8` is correct (`pea`+`jsr` = −8; MAME's `0`
is the Lua artifact). DP map now uses `$66-$68` (ROM read ptr) and `$6A`
(`move.l (An)+,(An)+` dst).

**Next:** the `$8FA` stack-frame subroutine — `link A6,#imm` (`$4E56`), `unlk`
(`$4E5E`), `movem` push/pop, plus its body — then `$AE0A / $2D38 / $5BC8`, then
`jmp $716`. Each subroutine adds opcodes; register fidelity is checked vs MAME taps
at each stop (`tools/mame-trace/regs_at_*.log`).

## Caveats / next increments
- Subset only (5 opcode forms) — enough for the reset init + clear loops. The next
  increments add the opcodes the reset handler needs past $3F6A (`move.l #imm,Dn`,
  the walking-bit RAM test: `move.b`/`cmp.b`/`bne`/`lsr.b`/`subq.l`, `bsr`/`rts`,
  `trap`), then memory reads (work RAM in BW-RAM) and real I/O handling, growing
  toward booting into the main loop.
- Memory/I-O writes are currently no-ops (fine for PC-trajectory validation; real
  semantics needed once data flow matters).
- 65816 gotchas hit: no `STA long,Y` (Poppy silently drops the bank → log to a
  bank-0 WRAM-mirror address); decode/loop branches exceed ±127 → use `bne`-skip +
  `jmp`; fetch via DBR-independent addressing so it's bank-stable.
- Speed: ~280 interpreted instructions/SNES-frame in this naive form — expected;
  the hybrid transpiles hot paths. A real interpreter would use a jump-table
  dispatch and tighter handlers.

Tools: built with Poppy; patched into the loaded ROM via Mesen `write_memory
(snesPrgRom)` (survives `reset_emulator`) — same restart-free harness as the
transpiler spike (`SPIKE_RESULT.md`).
