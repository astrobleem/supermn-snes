# C-Chip boot handshake — correction to the "patch, no emulation" resolution

Date: June 17, 2026. Found while driving the full-ROM interpreter through boot and
verified against MAME ground truth (`tools/mame-trace/cchip_boot_handshake.log`,
via `trace_cchip_superman`). **This corrects `CCHIP_FIRMWARE.md` "PORT RESOLUTION"
point 3** ("nothing gameplay-critical consumes a C-Chip value") — boot *does*
consume C-Chip values, in a deterministic command/response handshake.

## The handshake (real boot path, MAME-confirmed)
After the status gate at `$2AE2` (`$900803`→`$01`, already known) the reset path
runs a command/response protocol with the C-Chip data ports:

```
$2AE2  gate: cmpi.b #5/#1,$900803   -> status must read $01 (known)
$2AF6  bsr $2B18  : send commands 7,6,5,4,3,2,1,0 to $900C01, interleaved with
                    the $2BAA clear-loop (writes 0 to $900001,3,..,$3FF). setup.
$2AFA  send command 0; move.b #2,$900803; bsr $2BF0 (the handshake):
$2BF0  send command 2 ($900C01=2); then:
         move.b #$4A,$900001 ; #$46,$900003 ; #$34,$900005   (the "request")
$2C16  GATE (busy-wait): cmpi.b #$47,$900001 ; bne
$2C20         cmpi.b #$57,$900003 ; bne $2C16
$2C2A         cmpi.b #$4B,$900005 ; bne $2C16     -> chip must answer 47 57 4B ("GWK")
$2C34  send command 1 ($900C01=1)
$2C42  copy 256 bytes from $900001,$900003,..,$9001FF (step 2) into ($1B20,A5)
         = work RAM $F01B20.  <-- this block is 68K EXECUTABLE CODE served by the chip
```

## Key facts
- **The data port is address-indexed and command-selected, NOT a flat byte.**
  The same `$900001` returns `$47` during the gate (after command 2 + request
  bytes) but `$4E` during the command-1 block copy. Read value = `buffer[(addr&0x1FF)/2]`
  where `buffer` is selected by the last command written to `$900C01`.
- **Responses are deterministic** (a fixed signature + fixed downloaded code) →
  **replayable from captured MAME data; still NO uPD78C11 emulation, no PRNG.**
- The 256-byte command-1 block is **68K code** (`LINK A6/MOVEM/...lea $900001,A0.../
  TRAP #5/.../RTS`) — two small subroutines + `$FF`/`$00` padding. Saved verbatim
  to `data/cchip_boot_response.bin`. It is copied to `$F01B20` and these are almost
  certainly the **runtime C-Chip access routines** (they read the `$900001` block =
  the input mailbox). So the resolution's "input mailbox" insight stands; the
  mechanism is that the chip *downloads the input-reading code* at boot.

## Captured response buffers (command → response, MAME ground truth)
- **command 2 + request `4A 46 34`** → data port answers `47 57 4B` ("GWK") at
  index 0/1/2 (rest not read by boot).
- **command 1** → the 256-byte block in `data/cchip_boot_response.bin`
  (index i = read at `$900001 + 2i`).

## Port-handling plan (interpreter + transpiler)
Keep "patch, not emulate" but extend the `$900xxx` I/O layer to a **replay table**:
- track the last byte written to `$900C01` (`cmd`);
- on a read of an odd data port `$9000xx`, return `RESP[cmd][(addr&0x1FF)/2]`;
- `RESP[2] = {0:$47,1:$57,2:$4B}`; `RESP[1] = cchip_boot_response.bin`;
- `$900803` (aliased `$900802`) still returns `$01`;
- inputs: the downloaded routines read the `$900001` block → feed the 3-byte
  P1/P2/coin mailbox there at runtime (unchanged from the resolution).

This is captured-deterministic-replay, not MCU emulation. Open question to confirm
as the interpreter advances: whether any *later* command produces a non-constant
(input-dependent) response — if so, capture that command's buffer too. So far
(boot) every response is constant. See `cchip-resolution` memory.
