#!/usr/bin/env python3
"""R4 sound-truth: objective pre-screen of SNES track recordings vs arcade refs.

For each track pair (snes-tracks/NN_*.wav vs arcade-ref/NN_*.wav) computes:

* active duration (first->last audio above threshold) on both sides,
* tempo ratio via onset-envelope autocorrelation (beat period match),
* onset-envelope cross-correlation peak (structure similarity, tempo-aligned),
* silence/dropout segments inside the active window.

This is a FLAGGING pass for the human listening session, not an acceptance
gate: identical-sounding renders on different synths (YM2610 vs S-DSP/TAD)
never match sample-for-sample, but their onset structure and tempo should.
Run with the repo venv: .venv/bin/python tools/r4_compare.py
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
R4 = ROOT / "build/recovery-20260712/r4-sound-truth"

ENV_RATE = 100  # onset-envelope sample rate (Hz)


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    w = wave.open(str(path), "rb")
    rate = w.getframerate()
    n = w.getnframes()
    data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    if w.getnchannels() == 2:
        data = data.reshape(-1, 2).mean(axis=1)
    w.close()
    return data / 32768.0, rate


def envelope(x: np.ndarray, rate: int) -> np.ndarray:
    """RMS envelope at ENV_RATE Hz."""
    hop = rate // ENV_RATE
    usable = len(x) - len(x) % hop
    frames = x[:usable].reshape(-1, hop)
    return np.sqrt((frames ** 2).mean(axis=1))


def onset_strength(env: np.ndarray) -> np.ndarray:
    d = np.diff(env, prepend=env[:1])
    return np.maximum(d, 0.0)


def active_span(env: np.ndarray, thresh_ratio: float = 0.02) -> tuple[int, int]:
    thresh = max(env.max() * thresh_ratio, 1e-4)
    idx = np.where(env > thresh)[0]
    if len(idx) == 0:
        return 0, 0
    return int(idx[0]), int(idx[-1])


def beat_period(onsets: np.ndarray) -> float | None:
    """Dominant inter-onset period in seconds via autocorrelation (0.2-2.0 s)."""
    x = onsets - onsets.mean()
    if len(x) < ENV_RATE * 3 or not x.any():
        return None
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    lo, hi = int(0.2 * ENV_RATE), min(int(2.0 * ENV_RATE), len(ac) - 1)
    if hi <= lo:
        return None
    return (lo + int(np.argmax(ac[lo:hi]))) / ENV_RATE


def dropouts(env: np.ndarray, start: int, end: int) -> list[tuple[float, float]]:
    """Silent gaps > 0.75 s inside the active window."""
    thresh = max(env.max() * 0.02, 1e-4)
    quiet = env[start:end] <= thresh
    gaps = []
    run = 0
    for i, q in enumerate(quiet):
        if q:
            run += 1
        else:
            if run > int(0.75 * ENV_RATE):
                gaps.append(((start + i - run) / ENV_RATE, (start + i) / ENV_RATE))
            run = 0
    if run > int(0.75 * ENV_RATE):
        gaps.append(((end - run) / ENV_RATE, end / ENV_RATE))
    return gaps


def xcorr_peak(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized cross-correlation peak of two onset envelopes."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    ac = np.correlate(a, b, mode="full") / n
    return float(ac.max())


def main() -> int:
    snes_dir = R4 / "snes-tracks"
    ref_dir = R4 / "arcade-ref"
    results = []
    for ref in sorted(ref_dir.glob("*.wav")):
        stem = ref.stem  # e.g. 03_Main_BGM_1_cmd06
        matches = list(snes_dir.glob(stem.rsplit("_cmd", 1)[0] + "_cmd*.wav"))
        if not matches:
            results.append({"track": stem, "status": "MISSING_SNES"})
            continue
        snes = matches[0]
        try:
            xr, rr = load_mono(ref)
            xs, rs = load_mono(snes)
        except Exception as exc:
            results.append({"track": stem, "status": f"LOAD_ERROR: {exc}"})
            continue
        er, es = envelope(xr, rr), envelope(xs, rs)
        onr, ons = onset_strength(er), onset_strength(es)
        ar0, ar1 = active_span(er)
        as0, as1 = active_span(es)
        bpr, bps = beat_period(onr[ar0:ar1]), beat_period(ons[as0:as1])
        tempo_ratio = (bps / bpr) if (bpr and bps) else None
        entry = {
            "track": stem,
            "snes_file": snes.name,
            "ref_active_s": round((ar1 - ar0) / ENV_RATE, 1),
            "snes_active_s": round((as1 - as0) / ENV_RATE, 1),
            "ref_beat_s": round(bpr, 3) if bpr else None,
            "snes_beat_s": round(bps, 3) if bps else None,
            "tempo_ratio": round(tempo_ratio, 3) if tempo_ratio else None,
            "onset_xcorr": round(
                xcorr_peak(onr[ar0:ar1], ons[as0:as1]), 3
            ) if (ar1 > ar0 and as1 > as0) else None,
            "snes_peak": round(float(np.abs(xs).max()), 3),
            "snes_dropouts": dropouts(es, as0, as1),
        }
        flags = []
        if entry["snes_peak"] < 0.02:
            flags.append("SILENT")
        if entry["snes_active_s"] < entry["ref_active_s"] * 0.6:
            flags.append("SHORT")
        if tempo_ratio and not (0.94 <= tempo_ratio <= 1.06) \
           and not (0.47 <= tempo_ratio <= 0.53) and not (1.88 <= tempo_ratio <= 2.12):
            flags.append("TEMPO")
        if entry["snes_dropouts"]:
            flags.append("DROPOUT")
        entry["flags"] = flags
        results.append(entry)

    out = R4 / "compare_report.json"
    out.write_text(json.dumps(results, indent=2))
    for r in results:
        flags = ",".join(r.get("flags", [])) or "ok"
        print(f"{r['track']:34s} ref={r.get('ref_active_s','-'):>6} "
              f"snes={r.get('snes_active_s','-'):>6} "
              f"tempo={r.get('tempo_ratio','-')} "
              f"xcorr={r.get('onset_xcorr','-')} [{flags}]")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
