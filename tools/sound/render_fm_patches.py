#!/usr/bin/env python3
"""render_fm_patches.py — turn captured YM2610 FM patches into looped TAD instrument WAVs.

Pipeline (per patch that is the DOMINANT patch of at least one (track, FM-voice)):
  1. Render a held note at the patch's modal pitch with the ymfm YM2610B core
     (tools/sound/patch_render.cpp compiled binary; real chip emulation, not an
     approximation) — 500 kHz native chip rate, mono.
  2. Resample so ONE fundamental period == exactly 64 output samples. 64 is a
     multiple of the BRR block (16), so every whole-period boundary is a legal
     BRR loop point, and the TAD instrument freq becomes exactly 32000/64 = 500 Hz.
  3. Keep a short attack (up to ATTACK_PERIODS periods), then an 8-period loop:
     amplitude-flattened across the loop window (so a decaying render still loops
     cleanly) and crossfaded end->start (kills detune/LFO beating clicks).
  4. Normalize ALL patches by one global factor (preserves the arcade FM mix).

Outputs: instruments/<name>.wav + fm_instruments.json (name, freq, loop offset,
octave range, per-(track,voice) binding map for the consolidation step).
"""
from __future__ import annotations
import argparse
import array
import json
import math
import subprocess
import wave
from pathlib import Path

ATTACK_PERIODS = 16          # max attack kept before the loop (in periods)
LOOP_PERIODS = 8             # loop window length in periods
HOLD_S, TAIL_S = 1.2, 0.3    # render length (tail unused by the loop cut)

NOTE_SEMIS = {"c": 0, "c+": 1, "d": 2, "d+": 3, "e": 4, "f": 5, "f+": 6,
              "g": 7, "g+": 8, "a": 9, "a+": 10, "b": 11}


def fnum_to_freq(block, fnum, clock):
    return fnum * clock / (144.0 * (1 << (21 - block)))


def note_octave(notestr):
    # "c6" / "a+4" -> 6 / 4
    return int(notestr.lstrip("abcdefg+").lstrip("+") or 0)


def note_freq(name: str, octave: int) -> float:
    n = NOTE_SEMIS[name] + 12 * (octave + 1)
    return 440.0 * 2 ** ((n - 69) / 12.0)


def pick_period(last_octave: int) -> int:
    """Samples per fundamental period. The S-DSP pitch register caps at 4x, so a
    freq=32000/64=500 Hz instrument tops out at 2 kHz (~b6). Instruments that
    must reach o7 use 32 samples/period (freq 1000 -> 4 kHz ceiling)."""
    return 32 if note_freq("b", last_octave) > 2000.0 else 64


def resample_to_period(a, src_rate, f0, period):
    """Linear resample so one f0 period == period samples (dst rate = period*f0).
    Exact float ratio -> the achieved fundamental is exactly 32000/period at
    32 kHz playback (no integer-rate rounding detune)."""
    dst_rate = period * f0
    n_out = int(len(a) * dst_rate / src_rate)
    out = array.array("d", bytes(8 * n_out))
    ratio = src_rate / dst_rate
    for i in range(n_out):
        x = i * ratio
        j = int(x)
        f = x - j
        s0 = a[j]
        s1 = a[j + 1] if j + 1 < len(a) else s0
        out[i] = s0 + (s1 - s0) * f
    return out


def period_env(a, period):
    """Per-period peak envelope."""
    return [max(abs(x) for x in a[i:i + period]) or 1e-9
            for i in range(0, len(a) - period, period)]


def classify_envelope(a16, src_rate, hold_s):
    """Classify the raw ymfm render into a TAD envelope string.
    sustained -> flat gain; decaying -> ADSR approximating the FM decay."""
    win = src_rate // 100                       # 10 ms windows
    env = [max(abs(x) for x in a16[i:i + win]) or 1
           for i in range(0, int(hold_s * src_rate), win)]
    peak = max(env)
    ipk = env.index(peak)
    end = env[-1]
    if end > 0.5 * peak:
        return "gain F127", "sustained"
    # decay time: peak -> half amplitude (in seconds)
    t_half = None
    for i in range(ipk, len(env)):
        if env[i] <= peak * 0.5:
            t_half = (i - ipk) * win / src_rate
            break
    # SNES ADSR decay-rate ladder, ~time from full to sustain level (coarse)
    ladder = [(0.04, 7), (0.11, 6), (0.22, 5), (0.29, 4),
              (0.40, 3), (0.74, 2), (0.88, 1), (9.99, 0)]
    d = next(dv for t, dv in ladder if (t_half or 9.99) <= t)
    if end <= 0.1 * peak:
        return f"adsr 15 {d} 0 0", "percussive"
    sl = max(0, min(7, round(end / peak * 8) - 1))
    return f"adsr 15 {d} {sl} 10", "decaying"


def build_looped(a, period):
    """Choose attack + loop windows, flatten + crossfade the loop.
    Returns (float samples, loop_offset_samples)."""
    env = period_env(a, period)
    peak = max(env)
    xfade = period * 2
    # loop starts once the envelope settles: first period after which the
    # envelope changes < 10% per period for 4 consecutive periods, else at
    # ATTACK_PERIODS; never before period 2.
    start = ATTACK_PERIODS
    for p in range(2, min(ATTACK_PERIODS, len(env) - LOOP_PERIODS - 4)):
        window = env[p:p + 4]
        if all(abs(window[i + 1] - window[i]) < 0.10 * window[i] for i in range(3)):
            start = p
            break
    start = min(start, max(2, len(env) - LOOP_PERIODS - 2))
    ls = start * period
    ll = LOOP_PERIODS * period
    out = array.array("d", a[:ls + ll])
    # flatten: scale each loop sample so the per-period envelope stays at env[start]
    base = env[start]
    for p in range(LOOP_PERIODS):
        e = env[start + p] if start + p < len(env) else base
        g = base / e
        for i in range(period):
            out[ls + p * period + i] *= g
    # crossfade the seam: blend the loop's last xfade samples toward the signal
    # just before the loop start (which is what the loop wraps back into)
    for i in range(xfade):
        w = i / xfade
        k = ls + ll - xfade + i
        out[k] = out[k] * (1 - w) + out[ls - xfade + i] * w
    return out, ls


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--patches", default="soundwork/samples/fm_patches.json")
    ap.add_argument("--renderer", required=True, help="compiled patch_render binary")
    ap.add_argument("--out", default="soundwork/tad/mml_drafts/instruments")
    ap.add_argument("--tmp", default="/tmp/fm_render")
    ap.add_argument("--target-peak", type=int, default=24000)
    args = ap.parse_args()

    j = json.loads(Path(args.patches).read_text())
    clock = j["ym2610_clock"]

    # dominant patch per (track, voice) + union note stats per dominant patch
    bindings = []                 # {track, fm_voice, instrument}
    per_patch_notes = {}          # pid -> {notekey: count} (all keyons on voices it dominates)
    per_patch_octaves = {}        # pid -> (lo, hi) across the WHOLE voice range it must cover
    for u in j["usage"]:
        ph = {int(k): v for k, v in u["patch_hist"].items()}
        dom = max(ph, key=ph.get)
        bindings.append({"track": u["track"], "fm_voice": u["fm_voice"], "pid": dom})
        lo, hi = 9, 0
        for pid, nh in u["note_hist"].items():
            for nk, cnt in nh.items():
                o = note_octave(nk.split("|")[0])
                lo, hi = min(lo, o), max(hi, o)
                if int(pid) == dom:
                    d = per_patch_notes.setdefault(dom, {})
                    d[nk] = d.get(nk, 0) + cnt
        plo, phi = per_patch_octaves.get(dom, (9, 0))
        per_patch_octaves[dom] = (min(plo, lo), max(phi, hi))

    need = sorted(per_patch_notes)
    print(f"{len(need)} dominant patches to render: {need}")
    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    rendered = {}                 # pid -> (float samples, loop_offset, period, note, env)
    gpeak = 0.0
    for pid in need:
        p = j["patches"][pid]
        assert p["id"] == pid
        mode = max(per_patch_notes[pid], key=per_patch_notes[pid].get)
        note, block, fnum = mode.split("|")
        f0 = fnum_to_freq(int(block), int(fnum), clock)
        period = pick_period(per_patch_octaves[pid][1])
        wf = tmp / f"p{pid}.wav"
        r = subprocess.run([args.renderer, p["raw"], block, fnum,
                            str(HOLD_S), str(TAIL_S), str(wf)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"render failed for patch {pid}: {r.stderr}")
        src_rate = int(r.stdout.split("rate=")[1].split()[0])
        w = wave.open(str(wf))
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
        w.close()
        envstr, envclass = classify_envelope(a, src_rate, HOLD_S)
        rs = resample_to_period(a, src_rate, f0, period)
        looped, ls = build_looped(rs, period)
        rendered[pid] = (looped, ls, period, note, envstr, envclass)
        gpeak = max(gpeak, max(abs(x) for x in looped))
        print(f"  p{pid}: modal {note} f0={f0:.1f}Hz period={period} attack={ls} "
              f"loop={LOOP_PERIODS*period} total={len(looped)} smp "
              f"(~{len(looped)//16*9}B BRR) env={envclass} [{envstr}]")

    scale = args.target_peak / gpeak
    instruments = []
    total_brr = 0
    for pid, (samples, ls, period, note, envstr, envclass) in rendered.items():
        name = f"fm_p{pid:02d}"
        out = array.array("h", (max(-32768, min(32767, int(x * scale))) for x in samples))
        wpath = outdir / f"{name}.wav"
        w = wave.open(str(wpath), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)     # nominal; TAD pitch comes from freq + note
        w.writeframes(out.tobytes())
        w.close()
        lo, hi = per_patch_octaves[pid]
        total_brr += len(out) // 16 * 9
        instruments.append({
            "name": name, "pid": pid, "wav": f"instruments/{name}.wav",
            "freq": 32000.0 / period, "loop_offset": ls,
            "first_octave": lo, "last_octave": hi,
            "envelope": envstr, "env_class": envclass,
            "modal_note": note, "samples": len(out),
        })
    for b in bindings:
        b["instrument"] = f"fm_p{b['pid']:02d}"
    Path(outdir / "fm_instruments.json").write_text(json.dumps(
        {"instruments": instruments, "bindings": bindings,
         "total_brr_estimate": total_brr}, indent=1))
    print(f"TOTAL FM BRR ~= {total_brr} bytes across {len(instruments)} instruments")


if __name__ == "__main__":
    main()
