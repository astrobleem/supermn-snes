# Risk Mitigation: C-Chip Emulation

> **STATUS: RESOLVED — see `CCHIP_FIRMWARE.md` for the answers.** Every open
> question in this doc has since been settled: MAME runs the chip as LLE; both
> firmware dumps were obtained, hash-verified, and **fully disassembled**
> (`tools/upd7810dasm.py`); the 68K side was traced; and behavior was
> **runtime-verified in MAME across boot + attract + gameplay**
> (`tools/mame-trace/`). Outcome = the best case this doc hoped for: a one-time,
> patchable self-test gate plus a 3-byte input mailbox, **no PRNG gates
> gameplay**. This file is retained for the risk-analysis method and the
> verified MAME-source facts below; for current C-Chip guidance read
> CCHIP_FIRMWARE.md.

Advisor note. Companion to CCHIP_PROTOCOL.md, CCHIP_IMPLEMENTATION.md, and
PORT_PLAN.md "C-Chip". Goal: make sure you emulate the C-Chip's *behavior*, not
a plausible-looking guess at it.

> **UPDATE (verified by reading the MAME source — supersedes the speculation
> below).** I read `taito/taito_x.cpp` and `taito/taitocchip.cpp`/`.h`. The two
> open questions are now answered, and one answer is the opposite of what the
> project docs assumed. Read this box first.

## VERIFIED FROM MAME SOURCE

### V1 — Decision gate 0 is answered: MAME runs the C-Chip as full LLE
`taitox_cchip_state::superman()` (taito_x.cpp:1015–1031) instantiates a real
`TAITO_CCHIP` device clocked at `16_MHz/2` = 8 MHz. That device
(taitocchip.cpp) is an actual **uPD78C11 MCU** executing real firmware. There is
**no high-level command-response simulation anywhere in MAME** — the behavior is
whatever the MCU code does. Therefore **the 16-entry `→$4B` table in
CCHIP_IMPLEMENTATION.md is fabricated** (R1 confirmed). Do not build on it.

### V2 — The firmware IS available (TECHNICAL_REFERENCE.md is wrong)
The project docs say `b61_11.m11 … NOT in our ROM set!`. That premise is false.
MAME ships **both** firmware pieces with verified hashes:
- uPD78C11 **internal 4 KB mask ROM**: `cchip_upd78c11.bin`,
  CRC `43021521`, SHA1 `73bc4b46…` — shared across all Taito C-Chip games,
  optically extracted, internal checksum passes (taitocchip.cpp:137–141).
- Superman's **8 KB external EPROM**: `b61_11.m11`, CRC `3bc5d44b`,
  SHA1 `6ba3ba35…` (taito_x.cpp:1225–1226). **It is 8 KB, not 2 KB.**

This flips the risk profile. You are **not** reverse-engineering a black box —
you can **disassemble the exact MCU code** (MAME has a uPD7810 disassembler).
This is the single biggest de-risk available: the C-Chip's behavior is fully
knowable. Get both dumps, disassemble, and you have the ground truth.

### V3 — Real address map (your docs are off by a digit)
The C-Chip lives at **`$900000`**, not `$090000` (superman_map,
taito_x.cpp:629–642). Fix this everywhere — it also feeds the transpiler address
map (RISK_TRANSPILER.md). Correct mapping:
| 68K address | Device | MAME handler |
|---|---|---|
| `$900000–$9007FF` | C-Chip shared RAM (1 KB window into 8 KB SRAM) | `mem68_r/w`, byte via `umask16(0x00ff)` |
| `$900800–$900FFF` | ASIC registers | `asic_r` / `asic68_w` |
| `$300000`,`$400000`,`$600000` | watchdog/control | **`nopw`** — written each frame, safe to ignore |
| `$500000–$500007` | DIP/input | `dsw_input_r` |
| `$800001`,`$800003` | sound (TC0140SYT) | unchanged |

There is **no** `$700000` C-Chip command port (GAME_LOGIC_ANALYSIS.md is wrong);
it isn't mapped for Superman. Several project addresses appear shifted — re-check
the disassembly's base offset.

### V4 — The C-Chip is wired into the input path (not pure protection)
The MCU's ports are bound directly to the cabinet inputs
(taito_x.cpp:1026–1029): `PA ← IN0` (P1 controls), `PB ← IN1` (P2 controls),
`AD ← IN2` (coins/service), `PC → coin counters/lockout`. The chip takes an
external interrupt every VBlank. So input genuinely flows **through** the C-Chip
and is processed by MCU code before the 68K reads it from shared RAM. That means
the "input read" accesses are a **data-producer** class (see triage below), not
a gate you can simply patch out.

### V5 — ASIC register semantics (from taitocchip.cpp header + code)
- `0x401` = test command/status register: write `0x02` to start self-test; read
  bit0 = ready/OK, bit2 = error. **This matches your observed "ready bit"** — so
  the handshake/poll you found is real; only the surrounding table is invented.
- `0x600` = SRAM bank select (low 3 bits → one of 8× 1 KB banks visible at
  `0x000–0x3FF`). asic_w routes the bank write (taitocchip.cpp:156–165).

---

## Original speculation (kept for context; superseded by V1–V5 above)

### R1 — The 16-entry command table looks invented, not observed
CCHIP_IMPLEMENTATION.md presents a tidy table: `(40,00,00)→4B`, `(40,01,00)→4B`,
`(50,00,00)→4B` … all returning `$4B`. The disassembly in CCHIP_PROTOCOL.md only
actually demonstrates **one** transaction — the init handshake `4A/46/34 → 4B`.
The rest follows a too-neat pattern and every entry returns the same `$4B`.
**Confirmed fabricated by V1** — there is no such table in the real chip.

## Classify every access — emulate only what matters

Not all C-Chip traffic needs faithful emulation. Triage each access point
(the integration points are already listed in GAME_LOGIC_ANALYSIS.md) by **what
the 68K does with the result**:

| Class | Pattern in 68K | Strategy | Risk |
|---|---|---|---|
| **Protection gate** | read response, `cmp`, branch to error/halt on mismatch | **Patch out the check** (force the taken path) | Low |
| **Pure pass-through** | C-Chip relays input/coins it didn't transform | Feed SNES controller state directly | Low |
| **Data producer** | response is stored / used in later math | Must **replicate the computation** | High |
| **Watchdog/control** | $300000/$400000/$600000 each frame | NOP (no watchdog HW on SNES) | Low |

The plan's instinct ("replace protection checks with a lookup table, patch
protection") is correct **for the gate class**. The danger is mislabeling a
*data-producer* as a *gate* and patching it — then the game runs but computes
garbage. Every access must be classified from the disassembly, not assumed.

## Recommended strategy (revised after reading MAME source)

Because the firmware is fully available (V2), you have a *better* oracle than a
black-box transaction log: **the MCU source itself.** Use both, in this order.

### Primary: disassemble the C-Chip firmware
1. Obtain both dumps (verify hashes against V2): `cchip_upd78c11.bin` (4 KB
   internal) and `b61_11.m11` (8 KB external EPROM).
2. Disassemble with MAME's uPD7810 core/disassembler (e.g. `unidasm` from the
   MAME tools, CPU type `upd7810`/`upd78c11`). Map both ROM windows per
   `cchip_map` (taitocchip.cpp:181–187): internal `0x0000–0x0FFF`, EPROM
   `0x2000–0x3FFF`, SRAM bank window `0x1000–0x13FF`, ASIC `0x1400–0x17FF`.
3. Recover what the MCU actually computes for each shared-RAM field the 68K
   reads. This is the ground truth — not a guess. It's only 12 KB of 8-bit code.

### Secondary (confirmation, not discovery): transaction log from MAME
MAME is still useful as a runtime oracle. Record **every** 68K-side C-Chip read
and write during a playthrough (address, value, direction, issuing PC) and use
it to:
1. Confirm which shared-RAM fields the game actually consumes (so you only port
   the firmware logic that matters).
2. Build differential tests (below).

Disassembly tells you *what it computes*; the log tells you *what the game uses*.
The intersection is exactly what you must port — nothing more.

## Validate by differential replay
Once you have an SA-1 emulation:
1. Take the recorded MAME transaction log as input sequence.
2. Replay the same command sequence into your SA-1 mailbox emulation.
3. Assert each response byte matches MAME's. Any mismatch is a concrete bug
   before it's buried in gameplay.

This is the same golden-reference discipline as the transpiler harness
(RISK_TRANSPILER.md) — reuse the MAME-as-oracle infrastructure.

## The mailbox mechanism is fine
The `$3000–$3005` SA-1 I-RAM mailbox (CCHIP_IMPLEMENTATION.md) is a reasonable
design and matches the SMI mailbox pattern. The mechanism is **not** the risk —
the **table contents** and the **classification** are. Don't over-invest in the
protocol plumbing; invest in knowing what the chip actually returns.

One mechanism note: confirm the original is a polled handshake (the disassembly
shows `cmp`/`bne` busy-wait at $2C2A). If so, the SA-1 must respond fast enough
that the main CPU's poll loop sees `done` — trivial for table lookups (~tens of
cycles), but verify nothing depends on C-Chip *latency/timing* (some protection
schemes do). Flag if any access cares about how long a response takes.

## Acceptance gates
- **G0 — DONE.** Decision gate 0 answered: MAME is LLE; firmware is available
  (V1, V2). No further investigation needed to start.
- **G1 — Firmware disassembled:** both ROMs dumped, hashes verified, and the
  shared-RAM output fields the 68K reads are explained by MCU code.
- **G2 — Every access classified** (gate / pass-through / producer / watchdog)
  with the 68K PC and the branch it feeds. Note V4: input reads are producers.
- **G3 — Differential replay green:** SA-1 emulation matches MAME's C-Chip
  shared-RAM state for a recorded playthrough sequence.
- **G4 — Boot + first level** runs without a protection halt or C-Chip desync.

## Fallbacks
- **Pure protection slices** (handshake/self-test at `0x401`): patch the check
  in the transpiled 68K; no emulation needed for those.
- **Input/data-producer slices** (V4): port the relevant MCU logic from the
  disassembly. Since it's only ~12 KB of 8-bit code, a faithful port — or even
  running a small uPD7810 interpreter on the SA-1 fed by the dumps — is viable
  if hand-porting proves fiddly.
- **Last resort** (no longer expected, since firmware is available): hard-code
  observed shared-RAM responses for the exact sequences the game uses (from the
  transaction log) and accept off-path inputs are undefined.

## One correction to propagate
Fix `$090000 → $900000` and the "2 KB / not in ROM set" firmware note in
TECHNICAL_REFERENCE.md, CCHIP_PROTOCOL.md, CCHIP_IMPLEMENTATION.md, and
GAME_LOGIC_ANALYSIS.md, and drop the bogus `$700000` C-Chip port. These same
addresses feed the transpiler's address map, so the error would otherwise
propagate into ported code.
