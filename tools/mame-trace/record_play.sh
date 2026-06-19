#!/usr/bin/env bash
# Record YOUR Superman playthrough so it can be traced. Opens the game in a
# window; play as far as you can (ideally to the ending). Input is saved to
# inp/superman_play.inp. MUST be MAME 0.287 (matches the tracer) so playback is
# faithful — no desync.
#
# Run it from your desktop (needs a display). In this Claude session you can
# launch it by typing:   ! tools/mame-trace/record_play.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p /home/chad/supermn-snes/inp
NAME="${1:-superman_play.inp}"
echo "Recording to inp/$NAME — play, then close the window when done."
echo
echo "Default keyboard controls:"
echo "  5 = insert coin     1 = 1-player start"
echo "  arrow keys = move    Left-Ctrl = punch/fire   Left-Alt = jump"
echo "  Tab = MAME menu (remap controls under 'Input (this Machine)')"
echo "  Esc = quit (stops the recording)"
echo
# NOTE: no -video none here — you need to see the game. Real MAME 0.287.
mame superman \
  -rompath ./roms \
  -input_directory /home/chad/supermn-snes/inp \
  -record "$NAME" \
  -skip_gameinfo
echo
echo "Saved: /home/chad/supermn-snes/inp/$NAME"
echo "Tell Claude that filename and it will play it back + trace it."
