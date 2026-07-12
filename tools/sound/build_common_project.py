#!/usr/bin/env python3
"""build_common_project.py — consolidate the 21 per-track TAD drafts into ONE project.

TAD wants ONE common-audio-data pool (samples + instruments + SFX, resident in
ARAM for every song) + N song blobs. This tool:
  1. Emits soundwork/tad/mml_drafts/superman_all.terrificaudio containing
     - the rendered FM patch instruments (fm_pNN, from render_fm_patches.py)
     - the 12 shared drum instruments (sm_drum_XXXXXX, from prep_drums.py)
     - all 21 songs in track order (song id N = track N, id 0 = TAD built-in
       silence, which maps to the arcade $00 stop command)
     - a merged SFX file (punch/kick reuse drum samples — zero extra ARAM)
  2. Rewrites each NN_*.mml's instrument-binding header lines (@0..@3 sm_fmN ->
     the track's dominant FM patch instrument, from the capture's binding map).
     Drum bindings already use the global window names and are left alone.

Drum freq math: a drum WAV recorded at rate R must play back at R when the MML
hits c4, so freq = 261.63 * 32000 / R (TAD: playback_rate = 32000 * note/freq).
"""
from __future__ import annotations
import json
import re
from pathlib import Path

DRAFTS = Path("soundwork/tad/mml_drafts")
INSTR = DRAFTS / "instruments"
C4 = 261.6255653005986

SFX_FILE = "superman_all.sfx.txt"
# arcade $07 = punch, $62 = kick/jump (docs/SOUND_COMMAND_MAP.md); drum choice
# is a first-pass guess — tune by ear.
SFX_TEXT = """\
=== punch ===
    set_instrument sm_drum_067800
    play_note c4 8

=== kick ===
    set_instrument sm_drum_069f00
    play_note c4 8
"""


def main():
    fm = json.loads((INSTR / "fm_instruments.json").read_text())
    drums = json.loads((INSTR / "drums_report.json").read_text())

    instruments = []
    for i in fm["instruments"]:
        instruments.append({
            "name": i["name"],
            "source": i["wav"],
            "freq": i["freq"],
            "loop": "loop_reset_filter",
            "evaluator": "default",
            "ignore_gaussian_overflow": False,
            "first_octave": i["first_octave"],
            "last_octave": i["last_octave"],
            "envelope": i["envelope"],
            "comment": f"YM2610 FM patch {i['pid']} (ymfm render, modal {i['modal_note']})",
            "loop_setting": i["loop_offset"],
        })
    for name, d in sorted(drums["drums"].items()):
        instruments.append({
            "name": name,
            "source": f"instruments/{name}.wav",
            "freq": round(C4 * 32000.0 / d["rate"], 3),
            "loop": "none",
            "evaluator": "default",
            "ignore_gaussian_overflow": False,
            "first_octave": 4,
            "last_octave": 4,
            "envelope": "gain F127",
            "comment": f"ADPCM-A window 0x{d['window'][:6]} @{d['rate']}Hz "
                       f"{d['seconds']}s (trimmed+faded)",
        })

    mmls = sorted(DRAFTS.glob("[0-9][0-9]_*.mml"))
    assert len(mmls) == 21, f"expected 21 track MMLs, got {len(mmls)}"
    songs = [{"name": f"s{m.stem}", "source": m.name} for m in mmls]

    project = {
        "_about": {"file_type": "Terrific Audio Driver project file",
                   "version": "0.2.0-beta.2"},
        "instruments": instruments,
        "samples": [],
        "default_sfx_flags": {"one_channel": True, "interruptible": True},
        "high_priority_sound_effects": [],
        "sound_effects": ["punch", "kick"],
        "low_priority_sound_effects": [],
        "sound_effect_file": SFX_FILE,
        "songs": songs,
    }
    (DRAFTS / "superman_all.terrificaudio").write_text(json.dumps(project, indent=1))
    (DRAFTS / SFX_FILE).write_text(SFX_TEXT)

    # rewrite @0..@3 binding lines per track
    bind = {}   # (trackstem, fmvoice) -> instrument name
    for b in fm["bindings"]:
        # capture track stems look like "03 Main BGM 1"; MML stems like 03_main_bgm_1
        num = b["track"].split()[0]
        bind[(num, b["fm_voice"])] = b["instrument"]
    for m in mmls:
        num = m.stem[:2]
        text = m.read_text()
        if re.search(r"(?m)^@\d+ fm_p\d\d$", text):
            # regenerated with vgm2mml --fm-map: bindings + per-note @ switches are
            # already real patch instruments — nothing to rewrite
            print(f"{m.name}: fm-mapped (per-note switches), bindings left as-is")
            continue
        for v in range(4):
            name = bind.get((num, v))
            if not name:
                continue
            text, n = re.subn(rf"(?m)^@{v} \S+$", f"@{v} {name}", text)
            if n != 1:
                raise SystemExit(f"{m.name}: expected one '@{v} <name>' line, got {n}")
        m.write_text(text)
        print(f"{m.name}: bound @0-@3 -> "
              + ", ".join(bind.get((num, v), "-") for v in range(4)))
    print(f"\nwrote {DRAFTS/'superman_all.terrificaudio'} "
          f"({len(instruments)} instruments, {len(songs)} songs)")


if __name__ == "__main__":
    main()
