#!/usr/bin/env python3
"""convert_pack — drive the whole Superman VGM -> TAD pipeline in one command.

Steps (each is also runnable standalone):
  1. unpack the VGMRips .zip / .vgz -> .vgm
  2. header report
  3. (optional) per-track register profile
  4. VGM -> MML draft + notes.md + compile-checkable .terrificaudio
  5. (optional) tad-compiler check on every generated project
  6. (optional) extract + decode ADPCM-A drum samples

Usage:
  python3 tools/sound/convert_pack.py --zip VGM_SOUND_SUPERMAN.zip \
      --out soundwork [--tad ../snes-outrun-sa1/tools/tad/tad-compiler.exe] \
      [--check] [--samples] [--bpm-overrides 03=125,08=120]
"""
from __future__ import annotations
import argparse
import gzip
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vgmlib
import vgm2mml
import vgm_extract_adpcm as adpcm


def unpack(zip_path, out_vgm):
    out_vgm.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.filename.lower().endswith(".vgz"):
                raw = z.read(info.filename)
                try:
                    data = gzip.decompress(raw)
                except OSError:
                    data = raw
                name = Path(info.filename).stem + ".vgm"
                (out_vgm / name).write_bytes(data)
                n += 1
            elif info.filename.lower().endswith(".vgm"):
                (out_vgm / Path(info.filename).name).write_bytes(z.read(info.filename))
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="VGMRips zip; if omitted, --vgm-dir is used as-is")
    ap.add_argument("--vgm-dir", default=None, help="dir of already-unpacked .vgm")
    ap.add_argument("--out", default="soundwork")
    ap.add_argument("--tad", default=None, help="tad-compiler.exe for --check")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--samples", action="store_true", help="extract+decode ADPCM-A")
    ap.add_argument("--bpm-overrides", default="",
                    help="comma list like 03=125,08=120 (match by filename prefix)")
    args = ap.parse_args()

    out = Path(args.out)
    vgm_dir = Path(args.vgm_dir) if args.vgm_dir else out / "source" / "vgm_unpacked"
    if args.zip:
        n = unpack(args.zip, vgm_dir)
        print(f"[1] unpacked {n} VGMs -> {vgm_dir}")

    vgms = sorted(vgm_dir.glob("*.vgm"))
    if not vgms:
        print(f"no .vgm files in {vgm_dir}")
        return

    overrides = {}
    for kv in filter(None, args.bpm_overrides.split(",")):
        k, v = kv.split("=")
        overrides[k.strip()] = float(v)

    # header report
    hdr = out / "traces" / "headers" / "header_report.txt"
    hdr.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in vgms:
        h = vgmlib.parse_header(vgmlib.read_vgm(p))
        lines.append(f"{p.name}: {'YM2610B' if h.ym2610b else 'YM2610'} "
                     f"{h.ym2610_clock}Hz {h.total_seconds:.1f}s "
                     f"loop={h.loop_seconds:.1f}s")
    hdr.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[2] header report -> {hdr}")

    # convert
    mml_dir = out / "tad" / "mml_drafts"
    print(f"[4] converting {len(vgms)} tracks -> {mml_dir}")
    for p in vgms:
        prefix = p.stem.split()[0]
        bpm = overrides.get(prefix)
        vgm2mml.convert(str(p), str(mml_dir), bpm=bpm)

    # check
    if args.check:
        tad = args.tad or "tad-compiler"
        ok = bad = 0
        for proj in sorted(mml_dir.glob("*.terrificaudio")):
            r = subprocess.run([tad, "check", str(proj)],
                               capture_output=True, text=True)
            if "valid and will fit" in (r.stdout + r.stderr):
                ok += 1
            else:
                bad += 1
                print(f"  FAIL {proj.name}: {(r.stdout + r.stderr).strip()[:120]}")
        print(f"[5] tad check: {ok} passed, {bad} failed")

    # samples
    if args.samples:
        sdir = out / "samples"
        print(f"[6] extracting ADPCM-A drums -> {sdir}")
        for p in vgms:
            sys.argv = ["", str(p), "-o", str(sdir)]
            try:
                adpcm.main()
            except SystemExit:
                pass

    print("\ndone.")


if __name__ == "__main__":
    main()
