#!/usr/bin/env bash
# Record a Superman playthrough in the EXACT boot config the bridge plays back with, so it replays
# deterministically (the original .inp desyncs because it was made in a different MAME env).
# Backs up the pre-record cfg/nvram to tools/mame-trace/record_env so playback restores the same
# boot state. Goal: capture a VERTICAL sprite moment to exercise entry_ce4's off-screen clamp.
#
# Run this in a terminal WITH A DISPLAY:   bash tools/record_playthrough.sh

MT=/home/chad/supermn-snes/tools/mame-trace
INPDIR=/home/chad/supermn-snes/inp
OUT=vplay.inp
MAME=/snap/bin/mame

# 0) force Service Mode dip OFF (DSWA mask 4: On=0, Off=4) so it boots to the game, not the
#    test pattern -- defensive against a stale "On" override in the cfg
[ -f "$MT/cfg/superman.cfg" ] && sed -i '/:DSWA/ s/value="0"/value="4"/' "$MT/cfg/superman.cfg"

# 1) snapshot the pre-record boot env (cfg + nvram) so playback matches this recording's boot
rm -rf "$MT/record_env"; mkdir -p "$MT/record_env/nvram"
cp -r "$MT/cfg" "$MT/record_env/cfg" 2>/dev/null
[ -d "$MT/nvram" ] && cp -r "$MT/nvram/." "$MT/record_env/nvram/" 2>/dev/null
mkdir -p "$INPDIR"

cat <<'EOF'
=================== RECORDING SUPERMAN -> inp/vplay.inp ===================
  1) wait for the ATTRACT screen, press  5  (insert coin), hold ~1 second
  2) press  1  (1-Player Start)
  3) reach VERTICAL sprite action -- the off-screen clamp fires when a sprite
     runs off the TOP or BOTTOM of the screen. Easiest: FLY Superman UP HIGH
     so he hugs the top edge, or reach a flying stage / a tall boss. Linger ~2s.
  4) quit with  Esc  (this finalizes the .inp -- do NOT just close the window)
  Do NOT open the dipswitch / config menus (keeps boot deterministic).
  It can be SHORT -- a few seconds of vertical action is enough.
==========================================================================
EOF
echo "Launching MAME..."; echo

"$MAME" superman \
  -rompath         "$MT/roms" \
  -cfg_directory   "$MT/cfg" \
  -nvram_directory "$MT/nvram" \
  -state_directory "$MT/sta" \
  -input_directory "$INPDIR" \
  -record "$OUT" -skip_gameinfo

echo
if [ -f "$INPDIR/$OUT" ]; then
  echo "OK: recorded $INPDIR/$OUT ($(stat -c%s "$INPDIR/$OUT") bytes)."
  echo "Boot env snapshot saved to $MT/record_env."
  echo ">> Tell Claude 'vplay.inp is ready' and it will play it back + find the off-screen frame."
else
  echo "ERROR: $INPDIR/$OUT was not created."
  echo "       Make sure MAME launched and you quit with Esc (not by closing the window)."
fi
