#!/usr/bin/env python3
"""Pinned MAME 0.287 payload identity and direct-launch environment.

The snap launcher at ``/snap/bin/mame`` follows the mutable ``current``
revision and is itself only the generic ``snap`` executable. Oracle tools
must execute and hash the retained revision-4339 payload directly.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
MAME_VERSION = "0.287 (mame0287)"
MAME_REVISION = "4339"
MAME_SHA256 = (
    "297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f"
)
GNOME_REVISION = "263"

_MAME_CANDIDATES = (
    Path(f"/snap/mame/{MAME_REVISION}/mame"),
    ROOT / "build/toolchain/mame-4339-recovery/root/mame",
    Path("/tmp/mame-4339-recovery/root/mame"),
)
_MAME_OVERRIDE = os.environ.get("SUPERMN_MAME_EXE")
MAME = (
    Path(_MAME_OVERRIDE)
    if _MAME_OVERRIDE
    else next(
        (path for path in _MAME_CANDIDATES if path.is_file()),
        _MAME_CANDIDATES[0],
    )
)
_MAME_ROOT = MAME.parent

_LIBRARY_DIRECTORIES = (
    str(_MAME_ROOT / "lib"),
    str(_MAME_ROOT / "usr/lib"),
    str(_MAME_ROOT / "lib/x86_64-linux-gnu"),
    str(_MAME_ROOT / "usr/lib/x86_64-linux-gnu"),
    str(_MAME_ROOT / "usr/lib/x86_64-linux-gnu/pulseaudio"),
    f"/snap/gnome-42-2204/{GNOME_REVISION}/lib",
    f"/snap/gnome-42-2204/{GNOME_REVISION}/usr/lib",
    f"/snap/gnome-42-2204/{GNOME_REVISION}/lib/x86_64-linux-gnu",
    (
        f"/snap/gnome-42-2204/{GNOME_REVISION}/"
        "usr/lib/x86_64-linux-gnu"
    ),
    (
        f"/snap/gnome-42-2204/{GNOME_REVISION}/"
        "usr/lib/x86_64-linux-gnu/pulseaudio"
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def environment(
    base: Mapping[str, str] | None = None,
    **updates: str,
) -> dict[str, str]:
    result = dict(os.environ if base is None else base)
    inherited = result.get("LD_LIBRARY_PATH", "")
    override = result.get("SUPERMN_MAME_LD_LIBRARY_PATH", "")
    paths = (
        [item for item in override.split(":") if item]
        if override
        else [*_LIBRARY_DIRECTORIES]
    )
    if inherited:
        paths.append(inherited)
    result["LD_LIBRARY_PATH"] = ":".join(paths)
    result.update(updates)
    return result


def identity() -> dict[str, str]:
    if not MAME.is_file():
        raise RuntimeError(f"missing pinned MAME payload: {MAME}")
    observed_hash = sha256(MAME)
    if observed_hash != MAME_SHA256:
        raise RuntimeError(
            "pinned MAME payload hash mismatch: "
            f"{observed_hash} != {MAME_SHA256}"
        )
    observed_version = subprocess.check_output(
        [str(MAME), "-version"],
        env=environment(),
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()
    if observed_version != MAME_VERSION:
        raise RuntimeError(
            "pinned MAME version mismatch: "
            f"{observed_version!r} != {MAME_VERSION!r}"
        )
    return {
        "path": str(MAME.resolve()),
        "sha256": observed_hash,
        "version": observed_version,
        "snap_revision": MAME_REVISION,
        "gnome_content_revision": GNOME_REVISION,
    }
