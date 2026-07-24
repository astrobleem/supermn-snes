# C-Chip Firmware — First-Pass Disassembly Notes

Advisor / reverse-engineering pass. Date: June 16, 2026.
Inputs (both hash-verified genuine against MAME; see the
[historical C-Chip risk study](../history/risks/CCHIP.md)):
- `cchip_upd78c11.bin` — 4 KB uPD78C11 **internal mask ROM**, maps to MCU `$0000–$0FFF`
- `b61_11.m11` — 8 KB **external EPROM**, maps to MCU `$2000–$3FFF`

CPU: NEC uPD78C11 (uPD7810 family, 8-bit). Reset enters at `$0000`; hardware
interrupts vector to fixed low addresses spaced 4 bytes apart.

> **Status: DISASSEMBLED.** A faithful disassembler now exists
> (`tools/upd7810dasm.py`) — it parses MAME's own uPD7810 opcode tables
> (`tools/upd7810_dasm_mame.cpp`, copied from the MAME git object db) and
> replicates MAME's dispatch/operand formatter exactly, so the output equals
> what `unidasm -arch upd7810` would produce. It was validated against the
> hand-decoded vector table (every `JMP` target matches). Full output is in
> `data/cchip_eprom.dasm` and `data/cchip_internal.dasm`. The behavior below is
> decoded from that, not guessed.

---

## VERIFIED — control-flow skeleton

### `$54` = `JMP addr16` (LE), confirmed empirically
The internal ROM's first 0x28 bytes are interrupt vectors on a regular 4-byte
grid, each `54 lo hi`. That regularity pins the opcode beyond doubt.

### Interrupt vector table (internal mask ROM)
| MCU addr | uPD7810 interrupt | Bytes | Target |
|---|---|---|---|
| `$0000` | RESET | `54 E5 01` | `JMP $01E5` (internal init) |
| `$0004` | NMI | `54 09 20` | `JMP $2009` → EPROM trampoline |
| `$0008` | INTT0 (timer0) | `54 15 20` | `JMP $2015` (→ `JMP $0000`, i.e. unused) |
| `$000C` | INTT1 (timer1) | `00 00 00 00` | unused |
| `$0010` | **INTF1** (ext /INT1) | `54 00 20` | `JMP $2000` → EPROM trampoline |
| `$0014` | INTF2 | `00 00 00 00` | unused |
| `$0018` | INTFE0 | `54 03 20` | `JMP $2003` |
| `$0020` | INTFEIN | `54 06 20` | `JMP $2006` |
| `$0024` | INTFAD (A/D done) | `54 0F 20` | `JMP $200F` (→ `JMP $0000`, unused) |

**INTF1 is the important one** — it's the external interrupt line the Taito-X
board pulses every VBlank (taito_x.cpp `ext_interrupt`). So the per-frame C-Chip
work hangs off `$0010 → $2000`.

### EPROM trampoline table at `$2000` and resolved handlers
The EPROM opens with a second jump table (so the game ROM can place handlers
freely). Resolving the two hops:

| Interrupt | internal → | EPROM trampoline → | **Handler** |
|---|---|---|---|
| INTF1 (per-frame) | `$2000` | `JMP $2093` | **`$2093`** |
| NMI | `$2009` | `JMP $201E` | `$201E` |
| INTFE0 | `$2003` | `JMP $2126` | `$2126` |
| INTFEIN | `$2006` | `JMP $2092` | `$2092` |
| (via `$200C`) | `$200C` | `JMP $2133` | `$2133` |
| INTT0 / INTFAD | `$2015` / `$200F` | `JMP $0000` | unused (reset) |

Real EPROM code begins ~`$201C`. Entry points to disassemble first:
**`$2093` (per-frame), `$201E`, `$2092`, `$2126`, `$2133`**, and the internal
reset init at **`$01E5`**.

---

## VERIFIED — code/data map (tiny, fully tractable)

### EPROM `b61_11.m11`
- `$2000–$22C4` — **all the real code (~709 bytes)**.
- `$22C5–$3FFF` — `0xFF` blank (7483 bytes unused).
- A small data/pointer block sits around `$2280–$22C4` (mixed `00`/address-like
  bytes, e.g. `1e28`, `2270`, `4883` — looks like a table the handlers index).

So the Superman-specific C-Chip logic is **~0.7 KB**. This is a weekend
disassembly, not a research project.

### Internal mask ROM `cchip_upd78c11.bin`
- `$0000–$0027` — interrupt vectors (above).
- `$0028–~$00C0` — init/runtime code.
- `$00C0–~$01E0` — **ASCII data block** (see protection finding).
- `$01E5+` — reset init routine (sets up the chip, then presumably hands off).
- Scattered code/tables to `$0FFF` (≈251 distinct byte values — densely used).

---

## VERIFIED — this C-Chip does anti-piracy protection

The internal ROM contains a plaintext block at `$00C0`:

```
$00C0: "Kill the copy !!"
$00D0: "VER 0.015" "DEC,1986" "JW6X COMMAND"
       "---- staff ---- software I.Fujisue hardware K.Fujimoto hardware T.Kushiro"
$0148: "© TAITO CORPORATION 1987 / ALL RIGHTS RESERVED"
       "© 1987 TAITO AMERICA CORP. / LICENSED TO ROMSTAR FOR U.S.A."
       "© TAITO CORP. 1987 LICENSED TO PHOENIX ELECTRONICS CO."
```

`"Kill the copy !!"` is the giveaway: the C-Chip participates in copy
protection. The string is **data**, not necessarily displayed — but its
presence means at least one code path treats a check failure as "this is a
copy." For the port this matters in one specific way:

- Our SA-1 emulation must satisfy whatever the 68K verifies, OR we patch the
  68K's check. (RISK_CCHIP "triage": this is the **protection-gate** class —
  patchable once we see the 68K-side compare.)
- The version string `0.015` and date `DEC,1986` are good anchors for matching
  this dump against any other Superman C-Chip references.

---

## DECODED — what the firmware actually does

MCU address-space recap (from `cchip_map`): internal mask ROM `$0000–$0FFF`,
**shared SRAM bank window `$1000–$13FF`** (this is the 1 KB the 68K sees at
`$900000–$9003FF`), **ASIC regs `$1400–$17FF`**, EPROM `$2000–$3FFF`. On-chip
RAM is `$FF00–$FFFF` (MCU scratch, not visible to the 68K).

### Reset init — internal `$01E5`
Mask all interrupts (`MKL/MKH=$FF`), set memory-map mode `MM=$0E` (exposes the
external EPROM/SRAM windows), configure port-F and A/D (`ANM`), write `$F0` to
ASIC bank reg `$1600`, set port directions, clear ASIC scratch
`$1401–$1403`, then read A/D `CR0` and set **Port F = $C0 or $40** by threshold
— a power-on configuration/region sense. Falls through into the main loop.

### Main loop — EPROM `$2133`
Sets port directions `MA=MB=$FF` (Port A,B = inputs), `MC=$00` (Port C =
output), writes `$40` to ASIC `$1400`, raises the command flag `$FF9B=1`,
unmasks interrupts (`MKL=$D7`), then `EI; JR self` — idle, fully interrupt
driven.

### Per-frame ISR — EPROM `$2093` (vector INTF1, pulsed every VBlank by the 68K)
`DI` → push all regs → read command flag `$FF9B`; **if non-zero, `CALL $20CF`**
(process a command) and clear the flag → pop regs → `EI`/`RETI`. So the 68K
drives the chip one transaction per frame via the flag + shared SRAM.

### Input sampling — EPROM `$215F`  ← the key data-producer
```
MOV A,PA          ; Port A = IN0 (Player 1 buttons/stick)
MOV ($1000),A     ;   -> shared SRAM $000   (68K reads $900000)
MOV A,PB          ; Port B = IN1 (Player 2)
MOV ($1001),A     ;   -> shared SRAM $001   (68K reads $900002)
MOV A,($1003) ; MOV PC,A      ; drive Port C (coin counters/strobe)
CALL $2028        ; pack 8 A/D channels (AN0-7 = IN2 coin/service), threshold $80
MOV ($1002),A     ;   -> shared SRAM $002   (68K reads $900004)
```
The A/D packer (`$201E`/`$2028`) scans two channel groups via `ANM`, reads
`CR0..CR3`, thresholds each at `$80`, and OR-packs 8 bits. This is exactly the
input wiring MAME declares (`pa=IN0, pb=IN1, an=IN2, pc=counters`).

### Command processor — EPROM `$20CF`
Reads on-chip `$FFBE`, splits it into nibbles, writes results into the shared
SRAM, and calls several routines **in the internal mask ROM** (`$09D0`,
`$0FD5`, `$0F29`, `$0F23`) plus a timer setup (`$2109`). The mask-ROM `$09xx`/
`$0Fxx` routines are the **generic Taito C-Chip command/handshake engine**
(shared across all C-Chip games); the EPROM is the Superman-specific glue.

### Code/data boundary
EPROM real code ≈ `$2000–$2260`. From ~`$2260` onward the bytes are a
**data/pointer table** (mis-decodes as instructions in the linear dump —
ignore those lines; `$22C5+` is blank `$FF`).

---

## The shared-SRAM contract (what the SNES port must reproduce)

This is the payoff. The 68K reads these bytes at `$900000+` each frame; the SA-1
emulation must populate the same mailbox:

| Shared SRAM | 68K address | Produced from | SNES port action |
|---|---|---|---|
| `$000` | `$900000` | Port A = P1 input | write mapped SNES pad 1 |
| `$001` | `$900002` | Port B = P2 input | write mapped SNES pad 2 |
| `$002` | `$900004` | packed A/D = coins/service | write coin/service bits |
| ASIC `$401`+ | `$900800+` | self-test/handshake regs | ready/OK status (RISK_CCHIP V5) |

Plus the per-frame command transaction: 68K writes a command + sets the flag;
ISR runs `$20CF`; 68K reads the response from shared SRAM. **The input half is
now fully known and trivially portable.** The remaining unknown is exactly what
`$20CF` + the mask-ROM `$09xx/$0Fxx` helpers compute for the
command/protection responses — that's the next drill-down.

---

## The tool (reproducible)

- `tools/upd7810dasm.py` — the disassembler. Parses MAME's tables, no guessing.
- `tools/upd7810_dasm_mame.cpp` — MAME's source the tables come from (BSD-3).
- Regenerate (ROMs live in the sibling `~/superman-arcade/`, hence `../`):
  ```
  python3 tools/upd7810dasm.py ../superman-arcade/cchip_upd78c11.bin 0x0000 > data/cchip_internal.dasm
  python3 tools/upd7810dasm.py ../superman-arcade/b61_11.m11 0x2000 0x2000 0x22C5 > data/cchip_eprom.dasm
  ```
  (`VV:xx` in output = the uPD7810 working-register/V-address operand, exactly as
  MAME prints it.)

## DECODED — command & protection engine (internal mask ROM)

The EPROM dispatches commands through a **`CALT` pointer table at `$0080`**
(32 LE words; `CALT($0080+2n)`), 27 active entries. Decoded structure:

### On-chip RAM state map (`$FF00–$FFFF`, MCU-private)
| Addr | Role (from decoded refs) |
|---|---|
| `$FF99` | pointer used by buffer handlers (`LHLD $FF99`) |
| `$FFB6` | saved SP (handlers swap to a private stack) |
| `$FFBC` | **16-bit protection seed** (see `$09D0`) |
| `$FFBE` | **command/response byte** — low nibble = result code |
| `$FFBF–$FFC2` | **timer**: 4 counters with wrap limits `$3B,$3B,$3B,$17` (59/59/59/23 — a clock the game can read) |

### Response mechanism — `$0F23` family (CALT idx 6–13)
```
MOV A,($FFBE); ANI A,$F0; ORI A,$0n; MOV ($FFBE),A; MOV ($1600),A
```
Each sets the low nibble of `$FFBE` to a fixed code `0..n` and mirrors it to
**ASIC reg `$1600`**. This is the literal command-acknowledge/response the 68K
reads back. (Ties to the `$401`/status observation in RISK_CCHIP V5.)

### Protection generator — `$09D0` (a 16-bit LFSR/PRNG)
```
LXI HL,$FFBC ; LDEAX (HL)      ; load 16-bit seed
DADD EA,HL ; RLL A ; ANI $01   ; \
RLR A ×4 ; ANI $01 ; XRA C     ;  > compute feedback bit from shifted/xored taps
... INX HL ; SHLD $FFBC        ; write evolved seed back
```
This shuffles a seed at `$FFBC` and stores it back — a classic protection PRNG.
The game seeds it and reads back evolved values; a mismatch is what trips the
**`"Kill the copy"`** path in the mask ROM. (Interpretation is well-supported by
the decode; confirm against the 68K-side compare before relying on it.)

### Timer/counter — `$0FD5` family
Increment-with-wrap counters at `$FFBF+` (limits `$3B/$3B/$3B/$17`): a real-time
clock the game can query via a command.

---

# 68K-SIDE TRACE (the game's view of the C-Chip)

ROM: 512 KB 68000 program, reconstructed from the four mask ROMs per MAME's
`ROM_LOAD16_BYTE` interleave (even: `b61_09`,`b61_08`; odd: `b61_07`,`b61_13`).
**Verified** — reset vector decodes to `SP=$00F03FFE, PC=$00003EF0` (matches
TECHNICAL_REFERENCE) and the rebuild is byte-identical to `data/superman_m68k.bin`.
Existing Peony disasm (`data/superman_disasm.pasm`) already uses the correct
`$900000` addresses — only the hand notes had `$090000`.

## C-Chip register map, 68K side (every absolute access, raw-scanned)
| 68K addr | Dir | Meaning |
|---|---|---|
| `$900001` | R | P1 input (SRAM $000 ← Port A) |
| `$900003` | R | P2 input (SRAM $001 ← Port B) |
| `$900005` | R | coins/service (SRAM $002 ← packed A/D) |
| `$900007` | R/W | ASIC control/status (`btst #2/#3`; writes `$0F`) |
| `$900803` | R/W | **ASIC self-test/status reg** (the protection gate) |
| `$900C01` | W | command-byte port |

A raw scan found all 56 `$0090xxxx` 32-bit constants in the ROM; the extras
beyond the list above are **data-table values** (e.g. the `$aad2` loop reads
work-RAM input bytes at `$00F01C50` and tests button bits — `$0090`/`$0030`
there are parameters, not C-Chip addresses). No indirect (`lea/movea`) C-Chip
base loads exist. So the table above is complete for absolute accesses.

## The protection is a self-test gate — and it's trivially satisfiable
`loc_2ae2`:
```
cmpi.b #$5,$00900803     ; $05 = ready|error
beq.s  $002b16           ; -> loc_2b16: "bra.s $2b16"  = DEAD HANG
cmpi.b #$1,$00900803     ; $01 = ready, OK
bne.s  $002ae2           ; spin until ready
... bsr send-command-sequence; move.b #$02,$900803 (restart test); rts
```
`$2b16` (the only hang target — confirmed by xref) is reached **only** from this
check. So the entire boot-time C-Chip protection is: *status must read `$01`
(OK), never `$05` (error).* This is the **protection-gate** class
(RISK_CCHIP triage), not a data-producer the game's logic consumes.

**Key finding:** the `$FFBC` PRNG (`$09D0`) decoded in the firmware is **not**
read back and compared by the 68K anywhere in the disassembled + raw-scanned
code. The game gates boot on the *status byte*, not on a computed PRNG value.
So the SA-1 port does **not** need to replicate the LFSR — it only needs to
report self-test `OK ($01)`.

## Input read — `loc_3ad2`, confirmed both sides
```
move.b $00900001,d0 ; -> $1c4e(a5)   P1   (prev kept in $1c52)
move.b $00900003,d0 ; -> $1c4f(a5)   P2   (prev in $1c53)
move.b $00900005,d0 ; -> $1c50(a5)   coins(prev in $1c54)
```
`a5` = work-RAM base (`$00F00000`), so these land at `$00F01C4E/4F/50`, which the
rest of the game (e.g. the `$aad2` button-dispatch loop) reads. Exactly matches
the firmware's `$1000/$1001/$1002` writes.

## Verdict for the SNES port — the easy case
The C-Chip reduces to:
1. **Self-test:** SA-1 returns `$01` at `$900803`-equiv (or patch `beq $2b16`).
   No PRNG needed.
2. **Inputs:** SA-1 writes 3 mapped-pad bytes to the mailbox each frame.
3. **Command port `$900C01` / status `$900007`:** replay the handshake the init
   expects (the `$2b18` sequence sends bytes 7,6,5,…; pair with the firmware's
   command engine if any response is consumed — none gate gameplay so far).

This is the **best-case outcome** RISK_CCHIP hoped for: a patchable protection
gate plus a trivial input mailbox. No black-box logic blocks the port.

## VALIDATED at runtime (MAME 0.287, G3 done)

The harness in `tools/mame-trace/` was **run** (headless MAME 0.287, taps on the
68K's `$900000–$900FFF`). Results confirm the static trace:

- **Protection gate satisfied:** the self-test status reads **`$01` (OK) twice
  at boot and `$05` (error) never** — automated verdict:
  `status $01(OK) seen=true ; status $05(ERROR/hang) seen=false`.
  The `$02` test-restart write (`$2B10`) appears once. One-time, not per-frame.
- **Inputs confirmed both code paths:** P1/P2/coins read every frame at `$2C1E`
  and `$3ADE` (P1 read 8463×, coins 1724× over ~1700 frames).
- **No PRNG read/compare observed** anywhere in the C-Chip window — consistent
  with "no hidden gate." The per-frame status reg `$900007` just reads `$03`
  (interrupt flags clear); `$900C01` command port is written each frame.
- **Bus-address note:** the C-Chip sits on the low data byte (`umask 0x00ff`),
  so the 68K's odd byte addresses alias to even word addresses in the tap
  (`$900803→$900802`, `$900001→$900000`, etc.). Same registers.

Reproduce: `MAME=/path/to/mame tools/mame-trace/run_trace.sh` (needs MAME
≥~0.236 for Lua taps; the runner sets `SDL_VIDEODRIVER=dummy` for headless).

### Gameplay trace (coin + START injected) — investigation closed
Re-ran with `CCHIP_INJECT=1` (Lua injects COIN1 then START1; `run_trace.sh`
exposes it). The game **entered active gameplay** — proof: the per-frame input
routine at `$3ADE` jumps from **1 read (attract) to thousands in a level**
(3739 over a 4000-frame run; 8739 over 9000), coins `$3AFE` likewise. Under
active play:
- **No new command / data / PRNG reads.** The only new access sites vs boot are
  `$3D80`/`$3DA2` — more read-modify-write toggles of the `$900007` control/IRQ
  register (same class as boot, not data-producers).
- **Self-test status still never `$05`** (2 reads total, both at boot; not
  re-checked during gameplay).
- **No PRNG value is read or compared** anywhere, boot or gameplay.

**Conclusion:** across boot + attract + gameplay, the C-Chip is used only for
(1) a one-time boot self-test handshake (patchable / return `$01`), (2) the
per-frame P1/P2/coins input mailbox, and (3) `$900007` IRQ-flag toggling. **No
game logic depends on a C-Chip-computed value.** The SA-1 emulation plan is
confirmed and the C-Chip investigation is closed.
Run gameplay trace: `MAME=/path/to/mame CCHIP_INJECT=1 tools/mame-trace/run_trace.sh`.

---

# PORT RESOLUTION — C-Chip is PATCHED, not emulated (CLOSED, June 17 2026)

Decision: **no uPD78C11 emulation.** Confirmed by the static trace + MAME runtime
(boot/attract/gameplay): the only protection is a one-time self-test gate, and no
C-Chip-computed value (incl. the `$FFBC` PRNG) is ever read back by the 68K. The
SA-1 port handles the C-Chip entirely in its I/O layer (the interpreter's / 
transpiler's `$900000` handling, address-map D4):

1. **Self-test gate (protection) — satisfy or patch.**
   - I/O-layer (preferred): reads of `$900803` (aliases `$900802`) return **`$01`**
     (ready/OK), never `$05`; reads of `$900007` return a benign value (`$03`).
   - OR ROM patch at `loc_2ae2`: neutralize `beq $2b16` (the hang) and `bne $2ae2`
     (the spin) so boot proceeds. No PRNG/LFSR needed either way.
2. **Input mailbox (data — trivial wiring, not emulation).** Each frame write the
   mapped pad bytes the firmware would have produced:
   - `$900001` ← SNES pad 1 mapped to the arcade IN0 bit layout
   - `$900003` ← SNES pad 2 (IN1 layout)
   - `$900005` ← coins/service bits (IN2 packed)
   (The 68K copies these to work RAM `$F01C4E/4F/50` at `loc_3ad2`; map SNES→IN0/IN1
   active-low bit positions per `get_ioports` / the MAME port masks at impl time.)
3. **Command port `$900C01` / control `$900007`:** writes are no-ops; the boot
   command sequence (`$2b18` sends 7,6,5,…) needs no consumed response.

Acceptance: drop these into the interpreter's `$900xxx` I/O handler when it reaches
the boot self-test; differential-replay vs the MAME C-Chip tap log
(`tools/mame-trace/`) if any doubt. **C-Chip is no longer an open risk.**
