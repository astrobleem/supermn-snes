#!/usr/bin/env python3
"""make_check_project — build a compile-checkable TAD project from MML draft(s).

vgm2mml emits MML that references instrument names (@0 sm_fm0, @10 sm_drum_...).
Those need real BRR/WAV samples to sound right, but to *prove the MML is
structurally valid* (syntax, note ranges, voice count, ARAM fit) we only need a
placeholder sample bound to every name. This script:

  1. scans the MML draft(s) for @N name bindings,
  2. synthesizes a tiny placeholder WAV (mono 16-bit, loopable),
  3. writes a <name>.terrificaudio binding every instrument to the placeholder,
  4. optionally runs `tad-compiler check` / `song2spc` to validate.

Usage:
  python3 tools/sound/make_check_project.py soundwork/tad/mml_drafts/03_main_bgm_1.mml \
      --project soundwork/tad/check.terrificaudio \
      --tad ../snes-outrun-sa1/tools/tad/tad-compiler.exe --run
"""
from __future__ import annotations
import argparse
import json
import math
import re
import struct
import subprocess
import sys
from pathlib import Path

ABOUT = {"file_type": "Terrific Audio Driver project file", "version": "0.2.0-beta.2"}


def make_placeholder_wav(path: Path, rate=32000, freq=500.0, n=512):
    """A short sine (length multiple of 16) usable as a stand-in instrument."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for i in range(n):
        v = int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / rate))
        samples.append(max(-32768, min(32767, v)))
    pcm = struct.pack("<%dh" % n, *samples)
    block = b"WAVE"
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16)
    data = struct.pack("<4sI", b"data", len(pcm)) + pcm
    riff = b"RIFF" + struct.pack("<I", 4 + len(fmt) + len(data)) + block + fmt + data
    path.write_bytes(riff)


def parse_instruments(mml_text):
    names = []
    seen = set()
    for m in re.finditer(r"^@(\d+)\s+(\S+)", mml_text, re.M):
        name = m.group(2)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mml", nargs="+")
    ap.add_argument("--project", default="soundwork/tad/check.terrificaudio")
    ap.add_argument("--placeholder", default="soundwork/tad/instruments/placeholder.wav")
    ap.add_argument("--tad", default=None, help="path to tad-compiler.exe")
    ap.add_argument("--run", action="store_true", help="run check + song2spc")
    args = ap.parse_args()

    proj = Path(args.project)
    proj.parent.mkdir(parents=True, exist_ok=True)
    ph = Path(args.placeholder)
    make_placeholder_wav(ph)

    instruments = {}
    songs = []
    for mp in args.mml:
        mml = Path(mp)
        text = mml.read_text(encoding="utf-8")
        for name in parse_instruments(text):
            instruments.setdefault(name, True)
        rel = Path(mp).resolve().relative_to(proj.resolve().parent) \
            if proj.resolve().parent in Path(mp).resolve().parents else Path(mp).name
        sn = mml.stem
        if sn and sn[0].isdigit():       # TAD identifiers must not start with a digit
            sn = "s" + sn
        songs.append({"name": sn, "source": str(rel).replace("\\", "/")})

    ph_rel = ph.resolve()
    try:
        ph_rel = ph_rel.relative_to(proj.resolve().parent)
    except ValueError:
        pass
    ph_src = str(ph_rel).replace("\\", "/")

    inst_list = []
    for name in instruments:
        inst_list.append({
            "name": name,
            "source": ph_src,
            "freq": 500.0,
            "loop": "none",
            "evaluator": "default",
            "ignore_gaussian_overflow": False,
            "first_octave": 1,
            "last_octave": 7,
            "envelope": "adsr 12 2 6 8",
            "comment": "PLACEHOLDER — replace with real sample",
        })

    project = {
        "_about": ABOUT,
        "instruments": inst_list,
        "samples": [],
        "default_sfx_flags": {"one_channel": True, "interruptible": True},
        "high_priority_sound_effects": [],
        "sound_effects": [],
        "low_priority_sound_effects": [],
        "sound_effect_file": "",
        "songs": songs,
    }
    proj.write_text(json.dumps(project, indent=2), encoding="utf-8")
    print(f"wrote {proj}  ({len(inst_list)} instruments, {len(songs)} songs)")

    if args.run:
        tad = args.tad or "tad-compiler"
        print("\n=== tad-compiler check ===")
        r = subprocess.run([tad, "check", str(proj)], capture_output=True, text=True)
        print(r.stdout + r.stderr)
        for s in songs:
            out = proj.parent / f"{s['name']}.spc"
            print(f"=== song2spc {s['name']} ===")
            r = subprocess.run([tad, "song2spc", "-o", str(out), str(proj), s["name"]],
                               capture_output=True, text=True)
            print((r.stdout + r.stderr).strip() or f"  ok -> {out}")


if __name__ == "__main__":
    main()
