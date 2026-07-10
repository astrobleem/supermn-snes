#!/usr/bin/env python3
"""prep_drums.py — turn decoded ADPCM-A drum WAVs into ARAM-budget one-shot WAVs.

Input: the unique decoded drum windows in soundwork/samples/decoded_wav/ (18.5 kHz
mono s16, one per ADPCM-A ROM window, produced by vgm_extract_adpcm.py).
Output: one trimmed/faded/resampled WAV per window in the TAD instruments dir,
plus a JSON report of sizes (samples, estimated BRR bytes).

The arcade drums ring out for 0.7-1.7 s each (~154 KB of BRR at native rate —
several times the whole ARAM sample budget), so each drum gets a per-window
length cap + fade-out, and an optional rate reduction. In-game the MML retriggers
drums gate-style (next hit cuts the tail), so shortened tails are rarely audible.

BRR cost = 9 bytes per 16 samples; output lengths are rounded to a multiple of 16.
"""
from __future__ import annotations
import argparse
import array
import json
import math
import wave
from pathlib import Path

# Per-window overrides: (max_seconds, out_rate). Defaults chosen to spend budget
# on the frequently-hit drums; rare/long crashes get trimmed+downsampled harder.
DEFAULT_MAX_S = 0.38
DEFAULT_RATE = 10500
OVERRIDES = {
    # window        (max_s, rate)
    "07b500_07f1ff": (0.50, 9000),    # longest crash — keep some tail, cheaper rate
    "06c500_06f8ff": (0.42, 9000),    # long, rarely hit
    "06f900_0727ff": (0.42, 9000),    # long, rarely hit
}


def load_wav(p: Path):
    w = wave.open(str(p))
    fr = w.getframerate()
    a = array.array("h")
    a.frombytes(w.readframes(w.getnframes()))
    w.close()
    return fr, a


def resample_linear(a, src_rate: int, dst_rate: int):
    if dst_rate == src_rate:
        return array.array("h", a)
    n_out = int(len(a) * dst_rate / src_rate)
    out = array.array("h", bytes(2 * n_out))
    ratio = src_rate / dst_rate
    for i in range(n_out):
        x = i * ratio
        j = int(x)
        f = x - j
        s0 = a[j]
        s1 = a[j + 1] if j + 1 < len(a) else s0
        out[i] = int(s0 + (s1 - s0) * f)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decoded", default="soundwork/samples/decoded_wav")
    ap.add_argument("--out", default="soundwork/tad/mml_drafts/instruments")
    ap.add_argument("--fade-ms", type=float, default=60.0)
    ap.add_argument("--gain", type=float, default=1.0,
                    help="linear gain applied to all drums (they decode quiet)")
    args = ap.parse_args()

    import re
    import glob
    wins = {}
    for f in sorted(glob.glob(f"{args.decoded}/*.wav")):
        m = re.search(r"_a_([0-9a-f]{6})_([0-9a-f]{6})\.wav$", f)
        if m:
            wins.setdefault(f"{m.group(1)}_{m.group(2)}", Path(f))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    report = {}
    total_brr = 0
    for win, path in sorted(wins.items()):
        max_s, rate = OVERRIDES.get(win, (DEFAULT_MAX_S, DEFAULT_RATE))
        fr, a = load_wav(path)
        a = resample_linear(a, fr, rate)
        n = min(len(a), int(max_s * rate))
        n -= n % 16
        a = a[:n]
        nf = min(int(args.fade_ms / 1000 * rate), n)
        for i in range(nf):                       # linear fade-out tail
            k = n - nf + i
            a[k] = int(a[k] * (nf - i) / nf)
        if args.gain != 1.0:
            for i in range(n):
                v = int(a[i] * args.gain)
                a[i] = max(-32768, min(32767, v))
        name = f"sm_drum_{win[:6]}"
        op = outdir / f"{name}.wav"
        w = wave.open(str(op), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())
        w.close()
        brr = (n // 16) * 9
        total_brr += brr
        report[name] = {"window": win, "rate": rate, "samples": n,
                        "seconds": round(n / rate, 3), "brr_bytes": brr}
        print(f"{name}: {n} smp @ {rate} Hz = {n/rate:.2f}s -> {brr} BRR bytes")
    print(f"TOTAL drum BRR ~= {total_brr} bytes")
    (outdir / "drums_report.json").write_text(json.dumps(
        {"total_brr": total_brr, "drums": report}, indent=1))


if __name__ == "__main__":
    main()
