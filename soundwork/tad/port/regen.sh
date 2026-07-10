#!/usr/bin/env bash
# Regenerate the Poppy port of TAD's host API from the ca65 source.
# 1) poppy convert tad-audio.s -> tad-audio.converted.pasm (checked in)
# 2) port_tad.py applies the ~12 ca65->Poppy fixups (see soundwork/tad/vendor/VERSION.md / memory).
# Integration config: state at $00:1F00 (WRAM mirror), sfx-queue DP $68, internal jsl forced to bank $7F (the WRAM mirror; P3 concurrent fix).
# ZP base is $68 (NOT $EE): the 5A22 render (video.pasm vid_obj/obj_palslot/bg_palslot) uses $EE as its
# "arcade palette bank" DP scratch, which aliased TAD's Tad_sfxQueue_sfx=$EE. Between Tad_Process calls the
# render left $EE = a bank id (0-31) != $ff, so the next Tad_Process saw a bogus queued SFX and fired a
# garbage sfx command -> render-interleaving-dependent music dropout. $68/$69 are free in video.pasm.
set -euo pipefail; cd "$(dirname "$0")"
TAD_BSS_BASE=0x1F00 TAD_ZP_BASE=0x68 TAD_CODE_BANK=0x7F python3 port_tad.py
echo "regenerated tad_audio.pasm (integration config)"
