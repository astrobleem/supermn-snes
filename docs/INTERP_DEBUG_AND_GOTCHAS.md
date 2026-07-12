# Interp debug plumbing + toolchain gotchas (the "tribal knowledge" reference)

Everything here was learned the hard way on Superman and applies as-is to the next port
(Gigandes) because the interpreter core, the Poppy toolchain, and the two emulator oracles
all carry over. If you are a fresh agent bringing up or debugging the 68K interpreter,
READ THIS FIRST — each item below cost hours-to-days to discover.

## 1. The interpreter's built-in debug interface (SA-1 IRAM)

The interp has an always-on flight recorder and a poke-driven freeze/trace facility.
No MAME lockstep needed for most "where/why did it derail" questions. All addresses are
SA-1 IRAM (Mesen memtype `Sa1Memory`), little-endian unless noted.

### 68K register file (direct page)
| Cell | Meaning |
|---|---|
| `$00-$1F` | D0-D7, 4 bytes each, little-endian 32-bit |
| `$20-$3F` | A0-A7 (A7 = `$3C/$3E` lo/hi) |
| `$40/$42` | current 68K PC lo16 / bank |
| `$44` | current (last-decoded) 68K opcode |
| `$48` | PC-ring write pointer (see flight recorder) |
| `$4E` | halt code: `$DEAD` = unimplemented op, `$CAFE` = step cap |
| `$56` | peek-ahead / operand fetch pointer |
| `$60/$6E/$70/$72/$A2` | CCR cells Z/C/N/V/X — nonzero = set (NOT bit-packed) |
| `$7C` | SR interrupt mask (mask ≥ 6 blocks level-6 delivery) |
| `$AA` | IRQ pending |
| `$AC` | vblank countdown, instruction-paced; reload `$7000` = 28672 instr/frame |

### Flight recorder (always on)
Last 128 interpreted 68K PCs in a ring at IRAM `$0400-$05FF`, 4 bytes/entry
(lo16, bank16), write pointer at `$48`. Read it after ANY derail/halt — it shows the
final instruction cascade. Decode: entries at `(ptr - 4(i+1)) & $1FF` walking backwards.

**Reading the wedge signature:** if the ring stops updating AND `$AC` freezes AND
`$4E`=0, the SA-1 left the interp core and never came back (a native escape hung or
jumped into a garbage stream). If `$4E`=`$DEAD`, the interp itself fetched an
unimplementable opcode — ring shows how it got there.

### PC-freeze (poke-driven breakpoint, works from Mesen MCP)
- Arm: `$0710` = target 68K PC lo16, `$0716` = target bank. On hit the interp parks
  in a poll loop with `$0712` = 1 (frozen marker). All IRAM/BW-RAM readable at leisure.
- Release: write `$0714` = 1.
- Re-firing mode: `$0730` = `$5A5A` re-arms after release. **CAVEAT: re-fire checks at
  the same PC before the instruction advances — a re-firing freeze on a PC inside a
  tight revisit loop re-catches the SAME frozen instant forever (tick never advances).**
  For per-visit sampling, disarm + release + run ≥1 frame + re-arm instead.
- PC streaming: `$0718` = 0 streams the per-frame PC stream (see `stream_profile.py`).

### Counters: the ONE rule
**NEVER trust `$07xx` in-IRAM counters for anything the game can reach** — work-RAM/IRAM
overlap means the game overwrites them (the "ce4t fires 63451×" artifact). Measure firing
with SA-1 exec-hooks (HOOKTEST) or Mesen-side sampling. Purpose-placed counters in the
`$0760+` range are fine ONLY if you verified nothing else writes there.

## 2. Poppy assembler gotchas (65816, `.pasm`)

1. **`.org` overlap is SILENT — last org wins per byte, no error.** A section that grows
   past the next `.org` gets truncated/overwritten without warning. This produced our
   worst bug (a handler chain grew past `$F601`; the `.org $F602` section assembled over
   its tail — a lost `sec/rts` corrupted the boot RAM-test). **Defense:** after every
   layout change, assert slack seams in the ROM-pack script (see `build_interp_rom.py`
   guards) — assert the bytes just before each `.org` boundary are the expected
   terminator/padding.
2. **Mode inference resets at labels after `rtl`/`rts`.** Code after a label following a
   return is assembled as if `.a16` even when every caller arrives in A8 — 8-bit
   immediates then swallow the next opcode byte (BRK storms). **Explicit `.a8`/`.i16`
   directives at such labels are load-bearing.** Byte-audit any A8 code with 16-bit-
   looking immediates after assembling.
3. **Never insert code mid-file in `interp.pasm`** — long-range branches wrap silently.
   Append new bodies at the end / in escape banks and reach them with stubs.
4. **`rep #$30` before 16-bit immediates** in any code Poppy might size as 8-bit.
5. **Forward-referenced `jml`/`jml [abs]` is mis-sized** — use a literal 24-bit target
   or the push+RTL pattern (see `xlat_dispatch`).
6. Escape banks: start files with `.snes`(+`.sa1_enabled`); use explicit `jsl.l`/`jml.l`
   for cross-bank; branchless sign-extension beats branchy (see `escape-bank` notes in
   PROFILE_CAMPAIGN).
7. Symbol constants shared between `.pasm` files (e.g. `lh_nofire=$00F5C0` in escbank)
   do NOT track relocations in the other file. **After moving anything in `interp.pasm`,
   grep every other `.pasm` for hardcoded addresses into it** — a stale one is a
   mid-instruction `jml` landmine that presents as a silent SA-1 runaway.

## 3. Emulator-harness operational gotchas

### Mesen MCP (`mesen_mcp` Python)
- Needs `DOTNET_ROOT=/home/chad/.dotnet8` (and `.dotnet8` first in PATH).
- Long-running McpSession scripts die with exit 144 when run FOREGROUND under an agent
  Bash tool — run them in BACKGROUND and poll the output file.
- Use `socket_timeout=120` for sessions that run thousands of frames per call.
- `write_hex(addr, hex, 'Sa1Memory')` works while the SA-1 runs — poke-driven labs
  (runtime-pokeable IRAM handlers) beat rebuild-per-variant sweeps.

### MAME 0.287 (the arcade oracle)
- Lua: taps/subscriptions must be held in GLOBALS (else GC'd); `register_frame_done`;
  headless tracing = `-debug -debugger none`; PC reads back +2 (prefetch).
- **`set_input_line` is NOT exposed to Lua** — you cannot inject IRQs from a script;
  a "did it fire" tick-trace control is mandatory before trusting any injection result.
- Snap-confined MAME **cannot read `~/.claude` paths** — put scripts/artifacts under the
  project tree.
- `capture_at_pc` is prefetch-skewed → unreliable `[SP]` for stack-frame functions; use
  full-tick lockstep (`tools/lockstep.py`) for rts/table-class captures.

## 4. The coroutine-scheduler IRQ contract (why idle-collapse is clamped)

The game's per-frame tail is a cooperative coroutine scheduler (switch-out `$0532`,
switch-in `$0796`, select `$075C`, idle spin `$0818`). Decoding it revealed a hard
design contract, and any speed lever that increases IRQ density must respect it:

- Per-task stacks are TINY (256-512 bytes; floor table in ROM at `$087E`, one entry per
  slot). Every IRQ context save costs 66 bytes (6-byte exception frame + 60-byte
  `movem.l d0-d7/a0-a6`). The game even ships its own switch-in floor check with a
  "---Task Stack Error---" string — whose error handler jumps OFF-ROM (`$1000AE`,
  a dev-board address) and derails.
- **Contract: IRQ6 may only arrive when tasks are shallow** — on hardware, tasks finish
  each activation well within a video frame and the CPU idles at `$0818` (main context,
  roomy stack), so vblank never catches a task deep.
- Breaking the contract (IRQ spacing below a task activation's work window) fails two
  ways, both observed: (a) a deep-caught task's save blows through its floor into the
  neighbor's saved context → corrupt resume PC / off-ROM error path → `$DEAD` derail;
  (b) interleaving reorder makes a consumer poll a flag before its producer ran — if the
  poll loop is a NATIVELY-ESCAPED body, the native loop never returns to the interp
  core, `$AC` never decrements, no further IRQ can ever fire → system-wide livelock.
- Hence the shipped idle-collapse clamps `$AC` DOWN to `$2000` (never raises it — an
  unconditional store refills faster than the loop drains and starves the IRQ), which is
  longer than the longest task activation. Empirical boundary: ≤`$0800` fails at the
  first mass-coroutine-creation event; `$2000` is stable. Full narrative:
  `docs/PROFILE_CAMPAIGN.md` §sound-era addendum.
