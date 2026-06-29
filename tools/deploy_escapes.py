#!/usr/bin/env python3
"""Batch-deploy native escapes: the automation of the transpile->place->dispatch step for the AOT
coverage grind (the repeatable recipe proven by entry_1008, commit 5744594).

For each 68K function address it:
  1. transpile.py <addr> --bank2  -> entry_<addr> native body (the $94 escape-bank conventions).
  2. splices that body into src/escbank2.pasm (before the BODIES_END marker; escbank2 / $94 has
     room -- escbank / $92 is at its $F000 ceiling and inserting there corrupts the dispatchers).
  3. adds a jah2_ext jsr-hook dispatch block in src/escbank.pasm ($92) that cross-bank `jml`s to the
     $94 body: `cmp #<lo16> / bne jx_<addr> / inc $0764 / plp / pla / lda $54 / sta $40 / jml entry_<addr>`.
Idempotent: skips an addr already deployed. Run the build + a validator (val_frame_diff and/or
batch_val_mame) AFTER to gate correctness, then commit the GREEN ones. Bank-$00 jsr-reached targets
only (the synthetic-jsr / jah2 convention); jmp/rts/coroutine-reached fns use the xlat table instead.

Usage: deploy_escapes.py <hexaddr> [<hexaddr> ...]   |   --list <file>
"""
import sys, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESC, ESC2 = ROOT / "src/escbank.pasm", ROOT / "src/escbank2.pasm"
PY = sys.executable
BODIES_END = "; >>> ESCBANK2_BODIES_END"
SCAN_ANCHOR = ("    ; >>> JAH2_EXT_SCAN — deploy_escape inserts `cmp/bne/dispatch` blocks before jx_real <<<\n"
               "    cmp #$2DF0")

def deployed(addr):
    return ("entry_%x:" % addr) in ESC2.read_text() or ("entry_%x:" % addr) in ESC.read_text()

def deploy_one(addr):
    name = "entry_%x" % addr
    r = subprocess.run([PY, str(ROOT / "tools/transpile.py"), "%x" % addr, "--bank2"],
                       capture_output=True, text=True)
    body = r.stdout.strip()
    if r.returncode != 0 or "Unsupported" in body or not re.search(r"^%s:" % name, body, re.M):
        return False, (body.splitlines() or [r.stderr.strip()])[-1][:90]
    # 1) body -> escbank2
    s2 = ESC2.read_text()
    s2 = s2.replace(BODIES_END, "; --- $%06X (deploy_escapes.py, bank2 $94) ---\n%s\n%s" % (addr, body, BODIES_END), 1)
    ESC2.write_text(s2)
    # 2) jah2_ext cross-bank dispatch -> escbank ($92)
    s = ESC.read_text()
    jx = "jx_%x" % addr
    disp = ("    ; >>> JAH2_EXT_SCAN — deploy_escape inserts `cmp/bne/dispatch` blocks before jx_real <<<\n"
            "    cmp #$%04X\n    bne %s\n    inc $0764\n    plp\n    pla\n    lda $54\n    sta $40\n    jml %s\n"
            "%s:\n    cmp #$2DF0" % (addr & 0xFFFF, jx, name, jx))
    if SCAN_ANCHOR not in s:
        return False, "JAH2_EXT_SCAN anchor missing in escbank.pasm"
    ESC.write_text(s.replace(SCAN_ANCHOR, disp, 1))
    return True, name

def main():
    args = sys.argv[1:]
    if "--list" in args:
        lf = Path(args[args.index("--list") + 1])
        addrs = [int(x, 16) for x in (l.split("#")[0].strip() for l in lf.read_text().splitlines()) if x]
    else:
        addrs = [int(a, 16) for a in args if not a.startswith("--")]
    if not addrs:
        sys.exit("usage: deploy_escapes.py <hexaddr> ... | --list <file>")
    done, skip, fail = [], [], []
    for a in addrs:
        if deployed(a):
            skip.append(a); print(">>> $%06X already deployed" % a); continue
        ok, info = deploy_one(a)
        (done if ok else fail).append(a)
        print(">>> $%06X: %s" % (a, "deployed -> %s" % info if ok else "FAILED (%s)" % info))
    print(">>> deployed %d, skipped %d, failed %d. Now: build_interp.sh + validate (val_frame_diff / batch_val_mame), commit GREEN."
          % (len(done), len(skip), len(fail)))

if __name__ == "__main__":
    main()
