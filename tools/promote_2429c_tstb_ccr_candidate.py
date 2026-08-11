#!/usr/bin/env python3
"""Atomically promote the hash-pinned terminal-TST.B CCR repair.

The accepted source tree contains unrelated, unaccepted experiments, so this
promotion is deliberately from the byte-minimal candidate rather than from a
normal source rebuild.  It refuses any unexpected predecessor, candidate, or
backup identity and keeps both evidence images intact.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path


PREDECESSOR_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
CANDIDATE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str, role: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{role} does not exist: {path}")
    observed = sha256(path)
    if observed != expected:
        raise SystemExit(f"{role} hash mismatch: {observed} != {expected}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--predecessor-backup", type=Path, required=True)
    args = parser.parse_args()

    require_hash(args.candidate, CANDIDATE_SHA256, "candidate")
    require_hash(args.active, PREDECESSOR_SHA256, "active predecessor")
    require_hash(args.predecessor_backup, PREDECESSOR_SHA256, "predecessor backup")

    # Copy to a same-directory temporary, fsync it, then rename it into place.
    # The candidate and the backup remain available as immutable evidence.
    with tempfile.NamedTemporaryFile(
        prefix=f".{args.active.name}.2429c-promote-",
        dir=args.active.parent,
        delete=False,
    ) as temporary:
        temp_path = Path(temporary.name)
        with args.candidate.open("rb") as source:
            shutil.copyfileobj(source, temporary)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temp_path, args.active)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    require_hash(args.active, CANDIDATE_SHA256, "promoted active ROM")
    print(
        "promoted terminal-TST.B CCR candidate "
        f"active_sha256={CANDIDATE_SHA256} predecessor_backup={args.predecessor_backup}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
