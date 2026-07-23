#!/usr/bin/env python3
"""Regenerate $025110 with full X semantics while retaining audited edits.

``entry_25110`` predates the campaign's routine use of ``--xflag``.  Its bank
contains several later, independently validated edits (canonical-A5 guard,
bounded address folds, compact stage-1 redirect, sentinel correction, and the
terminal-TST fix), so replacing the function with raw transpiler output would
silently discard evidence-backed work.

Use the no-X transpiler output as a merge base, the checked-in customized body
as local, and freshly generated ``--xflag`` output as the other side.  The
three known conflicts are semantic simplifications whose labels are renumbered
by X expansion; resolve those narrowly and fail on any new conflict shape.
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


def generated(*, xflag: bool) -> str:
    command = [*TRANSPILE_ARGS, *( ["--xflag"] if xflag else [])]
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


def merge_body(current: str) -> tuple[str, int]:
    # A checked-in regenerated body is already the target side of this
    # three-way merge.  Treat it as current rather than attempting to merge the
    # same X expansion a second time; the structural assertions below still
    # audit every retained customization.
    if current.count("sta $A2") == 54:
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
    }
    failed = [name for name, valid in required.items() if not valid]
    if failed:
        raise SystemExit("regenerated body lost: " + ", ".join(failed))
    return merged, conflicts


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
