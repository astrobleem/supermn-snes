#!/usr/bin/env bash
set -euo pipefail

# Mesen's MCP runner starts with physical input disabled, but its debugger
# controller override still requires an emulated controller on port 1.  The
# user's legacy Mesen profile currently has that port set to None.  Override
# only this process so automated input works without rewriting their settings.
exec /home/chad/Mesen2/bin/linux-x64/Release/Mesen \
  --snes.port1.type=SnesController \
  --doNotSaveSettings \
  "$@"
