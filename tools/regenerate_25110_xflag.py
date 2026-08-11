#!/usr/bin/env python3
"""Regenerate $025110 with full X semantics and dynamic IRQ charging.

``entry_25110`` predates the campaign's routine use of ``--xflag``.  Its bank
contains several later, independently validated edits (canonical-A5 guard,
bounded address folds, compact stage-1 redirect, sentinel correction, and the
terminal-TST fix), so replacing the function with raw transpiler output would
silently discard evidence-backed work.

Use the no-X transpiler output as a merge base, the checked-in customized body
as local, and freshly generated ``--xflag`` output as the other side.  Then use
the X-aware generated body as a second merge base and add ``--accharge`` to
every retained generated basic block.  The verbose generated charge sequence
is reduced to a bank-local, flag-preserving three-byte JSR so the complete
charged body still fits below the fixed $97:A000 seam.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from fold_25110_addresses import fold


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/escbank3.pasm"
START = "; --- transpiled from $025110"
END = "; --- entry_129c6"
STAGE5_BYTE_ADD = """    lda $08
    sep #$20
    clc
    adc #$40
    sta $08
    rep #$20
    php
    lda #$0000
    rol a
    sta $A2
    plp
    lda $08
    and #$00FF
    eor #$0080
    sec
    sbc #$0080
"""
STATIC_RETURN_RESIDUES = {
    "br25110_1": """    ; restore real 68K call return residue below A7: $02598C
    lda $3C
    sec
    sbc #$0004
    tax
    lda #$0002
    xba
    sta $400000,x
    xba
    inx
    inx
    lda #$598C
    xba
    sta $400000,x
    xba
""",
    "br25110_2": """    ; restore real 68K call return residue below A7: $0259AC
    lda $3C
    sec
    sbc #$0004
    tax
    lda #$0002
    xba
    sta $400000,x
    xba
    inx
    inx
    lda #$59AC
    xba
    sta $400000,x
    xba
""",
}
TRANSPILE_ARGS = [
    sys.executable,
    str(ROOT / "tools/transpile.py"),
    "025110",
    "--bank1",
    "--workram=a0,a1,a2,a3",
]
CONFLICT_RE = re.compile(
    r"^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n",
    re.MULTILINE | re.DOTALL,
)
VERBOSE_CHARGE_RE = re.compile(
    r"""    php
    rep #\$30
    lda #\$000([1-6])
    jsr esc_ac_charge
    plp
"""
)


def specialize_charges(body: str) -> tuple[str, int]:
    """Shrink generated charge blocks to one flag-preserving local JSR."""

    return VERBOSE_CHARGE_RE.subn(
        lambda match: f"    jsr esc3_ac_charge_{match.group(1)}\n",
        body,
    )


def generated(*, xflag: bool, accharge: bool = False) -> str:
    command = [
        *TRANSPILE_ARGS,
        *(["--xflag"] if xflag else []),
        *(["--accharge"] if accharge else []),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("$025110 transpilation failed")
    body, count = fold(result.stdout)
    if count != 268:
        raise SystemExit(f"expected 268 bounded address folds, found {count}")
    if accharge:
        body, charge_count = specialize_charges(body)
        if charge_count != 226:
            raise SystemExit(
                f"expected 226 specialized charge blocks, found {charge_count}"
            )
    return body.rstrip() + "\n"


def resolve_conflicts(text: str) -> tuple[str, int]:
    count = 0

    def resolve(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        local, xflag = match.group(1), match.group(2)

        # Retain the hand-audited terminal TST materialization, but adopt the
        # X-expanded transpiler's renumbered DBRA fall-through label.
        if "h25110_final_tst_zero" in local:
            label_match = re.search(r"^(Lf25110_\d+):$", xflag, re.MULTILINE)
            if label_match is None:
                raise RuntimeError("terminal-TST conflict lost its remote label")
            return re.sub(
                r"^Lf25110_\d+:$",
                label_match.group(1) + ":",
                local,
                count=1,
                flags=re.MULTILINE,
            )

        # Two byte branches intentionally use the already-zero-extended direct
        # load.  Keep that simplification and only adopt the generated label.
        local_branch = re.search(
            r"^    (bn[el]|bpl|bmi) Lf25110_\d+$", local, re.MULTILINE
        )
        remote_branches = list(
            re.finditer(
                r"^    (bn[el]|bpl|bmi) (Lf25110_\d+)$",
                xflag,
                re.MULTILINE,
            )
        )
        if (
            local_branch is None
            or not remote_branches
            or local_branch.group(1) != remote_branches[-1].group(1)
        ):
            raise RuntimeError("unexpected $025110 regeneration conflict")
        remote = remote_branches[-1]
        return f"    {local_branch.group(1)} {remote.group(2)}\n"

    resolved = CONFLICT_RE.sub(resolve, text)
    if "<<<<<<<" in resolved or ">>>>>>>" in resolved:
        raise RuntimeError("unresolved $025110 regeneration conflict")
    return resolved, count


def restore_static_return_residues(text: str) -> str:
    """Retain the real popped 68000 return bytes below A7.

    The customized body predates transpile.py's
    ``--restore-static-residue`` option.  Apply its exact two generated
    corrections after the X-aware three-way merge so future regeneration
    cannot reintroduce native continuation addresses into observable stack
    residue.
    """

    for label, block in STATIC_RETURN_RESIDUES.items():
        comment = block.splitlines()[0]
        if comment in text:
            continue
        seam = f"{label}:\n"
        if text.count(seam) != 1:
            raise RuntimeError(f"could not find unique {label} residue seam")
        text = text.replace(seam, seam + block, 1)
    return text


def resolve_charge_conflicts(text: str) -> tuple[str, int]:
    """Retain audited local code at charge-only merge conflicts.

    Every generated conflict must contain at least one specialized remote
    charge.  Exact missing charges are restored at named logical seams below;
    retaining the local side here prevents a regenerated generic body from
    discarding the independently audited compact/HLE and CCR corrections.
    """

    count = 0

    def resolve(match: re.Match[str]) -> str:
        nonlocal count
        local, charged = match.group(1), match.group(2)
        if "esc3_ac_charge_" not in charged:
            raise RuntimeError(
                "unexpected non-charge conflict in $025110 accharge merge"
            )
        count += 1
        return local

    resolved = CONFLICT_RE.sub(resolve, text)
    if "<<<<<<<" in resolved or ">>>>>>>" in resolved:
        raise RuntimeError("unresolved $025110 accharge conflict")
    return resolved, count


def add_charge_after(text: str, seam: str, amount: int) -> str:
    marker = seam + "\n"
    charge = f"    jsr esc3_ac_charge_{amount}\n"
    if marker + charge in text:
        return text
    if text.count(marker) != 1:
        raise RuntimeError(f"could not find unique charge seam {seam}")
    return text.replace(marker, marker + charge, 1)


def restore_conflicted_charges(text: str) -> str:
    """Restore charges hidden inside the audited customization conflicts."""

    for seam, amount in (
        ("h25110_canonical_a5:", 2),
        ("Lf25110_1:", 2),
        ("h25110_stage1_outer:", 2),
        ("h25110_stage1_inner:", 2),
        ("h25110_stage1_inner_next:", 2),
        ("h25110_stage1_outer_next:", 2),
        ("h25110_stage1_done:", 3),
        ("h25110_stage2_outer:", 2),
        ("h25110_stage2_next:", 2),
        ("h25110_stage3_outer:", 2),
        ("h25110_stage4_setup:", 3),
        ("h25110_stage4_outer:", 2),
        ("h25110_stage4_next:", 2),
        ("h25110_stage5_select:", 2),
        ("h25110_stage5_wide:", 5),
        ("h25110_stage5_outer:", 2),
        ("L25110_259b0:", 2),
        ("h25110_stage5_outer_next:", 2),
        ("h25110_final_tst_done:", 1),
    ):
        text = add_charge_after(text, seam, amount)

    # These two return continuations first restore the real, observable 68000
    # return bytes below A7.  Charge the logical ADDQ/JMP only after that
    # bookkeeping, immediately before the generated continuation.
    for label, amount in (("br25110_1", 2), ("br25110_2", 1)):
        block = STATIC_RETURN_RESIDUES[label]
        charge = f"    jsr esc3_ac_charge_{amount}\n"
        if block + charge in text:
            continue
        if text.count(block) != 1:
            raise RuntimeError(f"could not find unique {label} residue block")
        text = text.replace(block, block + charge, 1)
    return text


def add_dynamic_charges(current: str) -> tuple[str, int]:
    if current.count("jsr esc3_ac_charge_") == 226:
        return current, 0

    with tempfile.TemporaryDirectory(prefix="supermn-25110-accharge-") as temp:
        directory = Path(temp)
        paths = {
            "local": current,
            "base": generated(xflag=True),
            "charged": generated(xflag=True, accharge=True),
        }
        for name, body in paths.items():
            (directory / name).write_text(body, encoding="utf-8")
        merge = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                str(directory / "local"),
                str(directory / "base"),
                str(directory / "charged"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    if merge.returncode > 127:
        sys.stderr.write(merge.stderr)
        raise SystemExit("git merge-file failed during $025110 accharge merge")
    merged, conflicts = resolve_charge_conflicts(merge.stdout)
    merged = restore_conflicted_charges(merged)
    charge_count = merged.count("jsr esc3_ac_charge_")
    if charge_count != 226:
        raise SystemExit(
            f"charged $025110 body has {charge_count} blocks, expected 226 "
            f"after {conflicts} conflicts"
        )
    return merged, conflicts


def merge_body(current: str) -> tuple[str, int]:
    # A checked-in regenerated body is already the target side of this
    # three-way merge.  Treat it as current rather than attempting to merge the
    # same X expansion a second time; the structural assertions below still
    # audit every retained customization.
    if current.count("sta $A2") == 54 and STAGE5_BYTE_ADD in current:
        merged = current
        conflicts = 0
    else:
        with tempfile.TemporaryDirectory(prefix="supermn-25110-xflag-") as temp:
            directory = Path(temp)
            paths = {
                "local": current,
                "base": generated(xflag=False),
                "xflag": generated(xflag=True),
            }
            for name, body in paths.items():
                (directory / name).write_text(body, encoding="utf-8")
            merge = subprocess.run(
                [
                    "git",
                    "merge-file",
                    "-p",
                    str(directory / "local"),
                    str(directory / "base"),
                    str(directory / "xflag"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        if merge.returncode > 127:
            sys.stderr.write(merge.stderr)
            raise SystemExit("git merge-file failed")
        merged, conflicts = resolve_conflicts(merge.stdout)
    merged = restore_static_return_residues(merged)
    merged, charge_conflicts = add_dynamic_charges(merged)
    required = {
        "X materializers": merged.count("sta $A2") == 54,
        "compact redirect": merged.count("jml.l $95F000") == 1,
        "bank-$97 sentinels": merged.count("lda #$00FC") == 2,
        "canonical guard": "h25110_canonical_a5:" in merged,
        "semantic stage-1 seam": "h25110_stage1_done:" in merged,
        "semantic profiling seams": all(
            f"h25110_{name}:" in merged
            for name in (
                "stage1_outer",
                "stage1_inner",
                "stage1_inner_next",
                "stage1_outer_next",
                "stage2_outer",
                "stage2_next",
                "stage3_outer",
                "stage4_setup",
                "stage4_outer",
                "stage4_next",
                "stage5_select",
                "stage5_wide",
                "stage5_outer",
                "stage5_inner_next",
                "stage5_outer_next",
            )
        ),
        "terminal TST fix": "h25110_final_tst_zero:" in merged,
        "Stage-5 byte ADD/TST": STAGE5_BYTE_ADD in merged,
        "static return residues": all(
            block.splitlines()[0] in merged
            for block in STATIC_RETURN_RESIDUES.values()
        ),
        "dynamic charge blocks": merged.count("jsr esc3_ac_charge_") == 226,
        "no verbose charge blocks": "jsr esc_ac_charge" not in merged,
    }
    failed = [name for name, valid in required.items() if not valid]
    if failed:
        raise SystemExit("regenerated body lost: " + ", ".join(failed))
    return merged, conflicts + charge_conflicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    source = SOURCE.read_text(encoding="utf-8")
    try:
        prefix, rest = source.split(START, 1)
        current_tail, suffix = rest.split(END, 1)
    except ValueError as exc:
        raise SystemExit("could not isolate entry_25110 body") from exc
    current = START + current_tail
    merged, conflicts = merge_body(current)
    changed = merged != current
    print(
        "regenerate_25110_xflag: "
        f"conflicts={conflicts}, changed={changed}, "
        f"lines={len(merged.splitlines())}"
    )
    if args.write and changed:
        SOURCE.write_text(prefix + merged + END + suffix, encoding="utf-8")
        print(f"wrote {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
