#!/usr/bin/env python3
"""Batch escape-vs-MAME ground-truth validator (the scalable AOT validation gate).

Validates a SET of deployed native escapes against MAME ground truth, sidestepping the sub-realtime
interp-vs-interp alignment problem that makes val_frame_diff fragile as escape coverage grows (see
the aot-dispatch-table memory). For each 68K function address it:
  1. CAPTURE (cached): runs extract_frame.py (entry regs+wram) + extract_exit.py (exit at the return)
     to snapshot MAME's deterministic ground truth into /tmp/supermn-scratch/frame_<addr>/. Skipped
     if already captured (so re-validating after a transpiler/codegen change is just phase 2).
  2. VALIDATE: runs val_escape_mame.py <addr> -- injects the MAME entry frame on the deterministic
     native base, runs the escape, diffs regs + $40 work RAM against MAME's exit. GREEN => the escape
     reproduces the arcade bit-exact.
Produces a per-function table (captured? / escape-deployed? / GREEN-vs-MAME / mismatches) + a report.

Usage:
  batch_val_mame.py <hexaddr> [<hexaddr> ...]      validate these functions
  batch_val_mame.py --list <file>                  one hexaddr per line (# comments ok)
  batch_val_mame.py --deployed                      auto-discover all deployed entry_<addr> escapes
  options: --start <frame> (MAME playback fast-forward target, default 1500)
           --recapture (force re-capture even if cached)  --capture-only / --validate-only
Per-function capture is ~2 MAME launches (~slow); validation is one Mesen run each. Captures persist,
so the expensive phase runs once. NB: validates whatever is currently built into build/interp.sfc --
deploy + rebuild the escapes first.
"""
import sys, os, re, subprocess, time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SCRATCH = Path("/tmp/supermn-scratch")
PY = sys.executable

def discover_deployed():
    """All entry_<hex> escapes deployed in the source (escbank/escbank2/interp), with their 68K PC
    from the `transpiled from $XXXXXX` comment (preferred) or the label hex suffix."""
    addrs = {}
    for f in ("src/interp.pasm", "src/escbank.pasm", "src/escbank2.pasm"):
        p = ROOT / f
        if not p.exists():
            continue
        last_pc = None
        for ln in p.read_text(errors="ignore").splitlines():
            mc = re.search(r"transpiled from \$([0-9A-Fa-f]+)", ln)
            if mc:
                last_pc = int(mc.group(1), 16)
            ml = re.match(r"(entry_[0-9a-f]+):", ln)
            if ml:
                hexs = ml.group(1)[len("entry_"):]
                pc = last_pc if last_pc is not None else int(hexs, 16)
                addrs[pc] = ml.group(1)
                last_pc = None
    return dict(sorted(addrs.items()))

def captured(addr):
    d = SCRATCH / ("frame_%x" % addr)
    return all((d / f).exists() for f in ("entry_regs.bin", "entry_wram.bin", "exit_wram.bin", "exit_regs.bin"))

def run(tool, addr, start, timeout=900):
    t0 = time.time()
    r = subprocess.run([PY, str(TOOLS / tool), "%x" % addr, str(start)],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr), time.time() - t0

def main():
    args = sys.argv[1:]
    start = 1500
    recapture = "--recapture" in args
    capture_only = "--capture-only" in args
    validate_only = "--validate-only" in args
    if "--start" in args:
        start = int(args[args.index("--start") + 1])
    if "--deployed" in args:
        targets = discover_deployed()
    elif "--list" in args:
        lf = Path(args[args.index("--list") + 1])
        targets = {int(x, 16): "entry_%s" % x for x in
                   (l.split("#")[0].strip() for l in lf.read_text().splitlines()) if x}
    else:
        hexs = [a for a in args if not a.startswith("--") and a not in (str(start),)]
        targets = {int(a, 16): "entry_%x" % int(a, 16) for a in hexs}
    if not targets:
        sys.exit("no targets; pass hexaddrs, --list <file>, or --deployed")

    print(">>> batch_val_mame: %d target(s), start-frame=%d%s" %
          (len(targets), start, " (recapture)" if recapture else ""), flush=True)
    results = []
    for addr, name in targets.items():
        row = {"addr": addr, "name": name, "captured": captured(addr), "verdict": "?", "mism": "", "note": ""}
        # phase 1: capture (cached)
        if not validate_only and (recapture or not row["captured"]):
            rc1, o1, t1 = run("extract_frame.py", addr, start)
            ok1 = captured(addr) or "wrote" in o1
            rc2, o2, t2 = run("extract_exit.py", addr, start) if ok1 else (1, "", 0)
            row["captured"] = captured(addr)
            if not row["captured"]:
                row["verdict"] = "NO-CAPTURE"
                row["note"] = (("frame: " + o1.strip().splitlines()[-1][:60]) if o1.strip() else "") or "capture failed (never hit in playback?)"
                results.append(row); print(">>> $%06X [%s]: NO-CAPTURE" % (addr, name), flush=True); continue
        if capture_only:
            row["verdict"] = "CAPTURED" if row["captured"] else "NO-CAPTURE"
            results.append(row); print(">>> $%06X: %s" % (addr, row["verdict"]), flush=True); continue
        if not row["captured"]:
            row["verdict"] = "NO-FRAMES"; results.append(row); continue
        # phase 2: validate vs MAME
        rc, out, tt = run("val_escape_mame.py", addr, start)
        verdict = "GREEN" if re.search(r">>> GREEN", out) else ("RED" if re.search(r">>> RED", out) else "ERR")
        mm = re.search(r"\$40 mismatches[^:]*:\s*(\d+)", out) or re.search(r"mismatches.*?(\d+)", out)
        row["verdict"] = verdict
        row["mism"] = mm.group(1) if mm else ""
        if verdict == "ERR":
            row["note"] = (out.strip().splitlines() or ["(no output)"])[-1][:70]
        results.append(row)
        print(">>> $%06X [%s]: %s%s" % (addr, name, verdict, ("  mism=" + row["mism"]) if row["mism"] else ""), flush=True)

    # summary
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rep = SCRATCH / "batch_val_report.txt"
    lines = ["addr      name              cap  verdict    mism  note"]
    for r in results:
        lines.append("$%06X  %-16s  %s   %-9s  %-4s  %s" %
                     (r["addr"], r["name"][:16], "Y" if r["captured"] else "-", r["verdict"], r["mism"], r["note"]))
    rep.write_text("\n".join(lines) + "\n")
    green = sum(1 for r in results if r["verdict"] == "GREEN")
    red = sum(1 for r in results if r["verdict"] == "RED")
    nocap = sum(1 for r in results if r["verdict"] in ("NO-CAPTURE", "NO-FRAMES"))
    print(">>> SUMMARY: %d GREEN / %d RED / %d no-capture / %d total  -> %s" %
          (green, red, nocap, len(results), rep), flush=True)

if __name__ == "__main__":
    main()
