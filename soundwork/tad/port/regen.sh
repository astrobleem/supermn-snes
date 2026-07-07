#!/usr/bin/env bash
# Regenerate the Poppy port of TAD's host API from the ca65 source.
# 1) poppy convert tad-audio.s -> tad-audio.converted.pasm (checked in)
# 2) port_tad.py applies the ~12 ca65->Poppy fixups (see soundwork/tad/vendor/VERSION.md / memory).
# Integration config: state at $00:1F00 (WRAM mirror), sfx-queue DP $EE, internal jsl forced to bank $E9.
set -euo pipefail; cd "$(dirname "$0")"
TAD_BSS_BASE=0x1F00 TAD_ZP_BASE=0xEE TAD_CODE_BANK=0xE9 python3 port_tad.py
echo "regenerated tad_audio.pasm (integration config)"
