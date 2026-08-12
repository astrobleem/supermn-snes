# Controls and playtesting

## SNES controls

| SNES input | Arcade meaning |
|---|---|
| D-pad | Move Superman |
| Select | Insert coin |
| Start | Start the game after a credit |
| B or Y | Arcade Button 1: punch/fire; hold and release to charge an energy shot |
| A or X | Arcade Button 2: kick |

The arcade game has two action buttons: punch and kick. Pressing Up makes Superman
fly; there is no jump action.

Only the player-1/port-0 path has current evidence. Do not infer two-player support
from the arcade input map.

## Starting a playtest

1. Verify the ROM before reporting a result:

   ```sh
   sha256sum build/interp-2429c-tstb-ccr-isolated-current-5c7e.sfc
   ```

   The evidence-backed ordinary playtest candidate is
   `a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60`,
   preserved at `build/interp-2429c-tstb-ccr-isolated-current-5c7e.sfc`.

2. Load that hash-verified preserved ROM in Mesen 2.1.1 or the project Nexen build
   with a standard SNES controller on port 0.
3. Wait through the Mode 7 SA-1 activity screen and original game initialization.
   The moving activity diamond means the 5A22 display is alive; it is not a completion
   percentage or proof of a specific RAM/ROM test.
4. At the title, press Select for a credit and Start to begin.

The old v135 playtest copy remains at
`build/playtest/superman-snes-v135-5aac64b6.sfc`. The evidence-backed ordinary
candidate is the preserved `a976…` file named above. A normal current-source build
writes a different, unpromoted `build/interp.sfc` at exact SHA `4eb9a408…`; do
not silently substitute it or any VTIME diagnostic for the preserved candidate.
See [STATUS.md](STATUS.md) and the
[August 11 checkpoint](ENGINEERING_CHECKPOINT_20260811.md) for their distinct
evidence scopes.

## Useful playtest route

For a high-value regression pass:

1. Leave the no-credit title/attract sequence running past the old freeze point.
2. Insert a coin and start.
3. Test normal punch/fire, kick, and Up-to-fly movement.
4. Hold Button 1, release a charged shot, and hit a silver enemy if possible.
5. Pick up and throw the crate.
6. Break the first wall.
7. Defeat the first boss and confirm that the following vertical section scrolls.
8. Watch Superman's attack frames for incorrect tiles.
9. Listen for wrong instruments, excessive pitch shifting, missing effects, or music
   replacement/cutout.

Record the emulator version, exact ROM SHA-256, what happened immediately before a
failure, and a save state if one is available. A human observation is accepted as
project evidence; automation should reproduce and narrow it rather than dismiss it.
