# MAME C-Chip Access Trace (validation harness)

Runtime validation for the static C-Chip findings in
[`docs/current/CCHIP_FIRMWARE.md`](../../docs/current/CCHIP_FIRMWARE.md)
("68K-SIDE TRACE"). It runs Superman in MAME headlessly and logs every 68K
access to the C-Chip window `$900000–$900FFF`, then prints a verdict on the
self-test protection gate.

## What it confirms
- **`$900803` status** only ever reads `$01` (OK) and **never `$05`** (error →
  boot hang at `$2b16`). If `$05` ever appears, the protection path is reachable.
- **`$900001 / $900003 / $900005`** are the P1 / P2 / coins input mailbox.
- No access reads a PRNG-derived value the game compares (no hidden gate) — you
  can eyeball the deduped access list for any unexpected `$900xxx` reads feeding
  a compare.

## Files
- `roms/superman.zip` — complete, CRC-verified romset (incl. `b61_11.m11` EPROM
  and `cchip_upd78c11.bin` internal MCU ROM). Built from `~/superman-arcade/`.
- `trace_cchip.lua` — MAME autoboot script: installs read/write taps, dedupes by
  `(PC, addr, R/W)`, tracks `$900803` values, exits after `CCHIP_FRAMES` frames.
- `run_trace.sh` — headless runner.

## You need a MAME binary
The local `/home/chad/mame` is a **source-only sparse checkout** (taito drivers,
no build). Get a binary with the Lua memory-tap API (**MAME ≥ ~0.236**):
- Distro/package, a prebuilt release, or build from a full MAME checkout
  (`make -j$(nproc)` — large). The driver here matches upstream `taito_x.cpp`.
- Then: `MAME=/path/to/mame ./run_trace.sh`  (or put `mame` on PATH).

## Usage
```bash
# default ~30s (1800 frames) boot + attract trace
./run_trace.sh

# longer, or to reach gameplay
CCHIP_FRAMES=5400 ./run_trace.sh        # ~90s
```
Output: `cchip_trace.log` — a deduped access table plus a VERDICT block.

### Reaching gameplay (optional)
The default trace covers boot + attract, which already exercises the self-test
handshake and per-frame input polling. To drive into a level you must inject a
coin + start. Two options:
1. Add input injection to `trace_cchip.lua` (set the `:IN2` coin field and
   `:IN0` start field for a few frames around a chosen frame number via
   `manager.machine.ioport.ports`).
2. Run MAME interactively (drop `-video none`, remove `-seconds_to_run`), insert
   coin/start by hand; the Lua tap still logs. Exit when done.

## If MAME can't find the C-Chip internal ROM
Some MAME versions audit the device ROM `cchip_upd78c11.bin` under a separate
`cchip` set. If `superman.zip` alone errors on that file, also create
`roms/cchip.zip` containing just `cchip_upd78c11.bin`.

## Fallback: debugger watchpoints (no Lua taps)
On an older MAME, use the debugger instead of `trace_cchip.lua`:
```
mame superman -rompath ./roms -debug
# in the debugger console:
wpset 900000,1000,r,1,{ printf "R %06X = %02X  pc=%06X\n",wpaddr,wpdata,pc; g }
wpset 900000,1000,w,1,{ printf "W %06X = %02X  pc=%06X\n",wpaddr,wpdata,pc; g }
g
```
Pipe the console log to a file and grep for `900803`.
