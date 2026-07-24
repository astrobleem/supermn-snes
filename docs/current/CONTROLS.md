# Controls and playtesting

## SNES controls

| SNES input | Arcade meaning |
|---|---|
| D-pad | Move Superman |
| Select | Insert coin |
| Start | Start the game after a credit |
| B or Y | Arcade Button 1: punch/fire; hold and release to charge an energy shot |
| A or X | Arcade Button 2: jump |

The arcade game has two action buttons. There is no independent kick button, so a
missing “third attack” is not a controller-mapping problem.

Only the player-1/port-0 path has current evidence. Do not infer two-player support
from the arcade input map.

## Starting a playtest

1. Verify the ROM before reporting a result:

   ```sh
   sha256sum build/interp.sfc
   ```

   The current v135 candidate is
   `5aac64b67cfc04caf88b44198b762ddbf283ac38dfc831956290db7a99dd025a`.

2. Load the ROM in Mesen 2.1.1 or the project Nexen build with a standard SNES
   controller on port 0.
3. Wait through the Mode 7 SA-1 activity screen and original game initialization.
   The moving activity diamond means the 5A22 display is alive; it is not a completion
   percentage or proof of a specific RAM/ROM test.
4. At the title, press Select for a credit and Start to begin.

On the current host, the preserved playtest copy is
`build/playtest/superman-snes-v135-5aac64b6.sfc`; a fresh build writes
`build/interp.sfc`. Both are private build artifacts and are ignored by Git.

## Useful playtest route

For a high-value regression pass:

1. Leave the no-credit title/attract sequence running past the old freeze point.
2. Insert a coin and start.
3. Test normal punch/fire and jump.
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
