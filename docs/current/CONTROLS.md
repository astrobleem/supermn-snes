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

There is currently no promoted human-test ROM. Do not substitute
`build/interp.sfc`; it is always unverified, and current hash `f25a0e68…` is
visually rejected.

When the fail-closed promotion tool eventually creates a test ROM:

1. Verify its hash against the adjacent promotion record before reporting a result:

   ```sh
   sha256sum build/Superman-Arcade-Edition-<hash>-test.sfc
   ```

2. Load that hash-verified preserved ROM in Mesen 2.1.1 or the project Nexen build
   with a standard SNES controller on port 0.
3. Wait through the Mode 7 SA-1 activity screen and original game initialization.
   The moving activity diamond means the 5A22 display is alive; it is not a completion
   percentage or proof of a specific RAM/ROM test.
4. At the title, press Select for a credit and Start to begin.

Historical playtest copies remain evidence only. A normal current-source build is
not a candidate, even if an older narrow gate passed. See [STATUS.md](STATUS.md)
and the [validation contract](VALIDATION.md) for the exact fail-closed rules.

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
