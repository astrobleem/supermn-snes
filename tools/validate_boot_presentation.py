#!/usr/bin/env python3
"""Fail-closed visual gate for settled SA-1 boot-screen captures.

The tool compares the isolated Mode-7 logo against approved reference captures,
checks its full-screen geometry, requires the loading text somewhere in the
candidate sequence, and rejects unexpected nonblack pixels outside the known
boot regions. It is a component result only: the caller must separately prove
fresh-power lineage, exact ROM identity, and mutation-free capture before using
it in a promotion report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops


SCREEN_WIDTH = 256
MIN_SCREEN_HEIGHT = 208
TOP_REGION = (0, 20, 256, 64)
LOGO_REGION = (0, 60, 256, 175)
BOTTOM_REGION = (0, 175, 220, 208)
ALLOWED_REGIONS = (
    (30, 24, 222, 64),
    (45, 64, 202, 165),
    (28, 184, 221, 208),
    (220, 184, 244, 208),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_digest(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(image.width.to_bytes(4, "little"))
    digest.update(image.height.to_bytes(4, "little"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def nonblack_bbox(image: Image.Image, region: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    cropped = image.crop(region)
    difference = ImageChops.difference(cropped, Image.new("RGB", cropped.size))
    bbox = difference.getbbox()
    if bbox is None:
        return None
    return (
        bbox[0] + region[0],
        bbox[1] + region[1],
        bbox[2] + region[0],
        bbox[3] + region[1],
    )


def logo_signature(image: Image.Image) -> tuple[tuple[int, int, int, int] | None, str | None]:
    bbox = nonblack_bbox(image, LOGO_REGION)
    if bbox is None:
        return None, None
    return bbox, image_digest(image.crop(bbox))


def unexpected_nonblack_pixels(image: Image.Image) -> int:
    allowed = Image.new("1", image.size)
    pixels = allowed.load()
    for left, top, right, bottom in ALLOWED_REGIONS:
        for y in range(top, min(bottom, image.height)):
            for x in range(left, min(right, image.width)):
                pixels[x, y] = 1
    count = 0
    for rgb, permitted in zip(image.getdata(), allowed.getdata()):
        if rgb != (0, 0, 0) and not permitted:
            count += 1
    return count


def open_rgb(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if image.width != SCREEN_WIDTH or image.height < MIN_SCREEN_HEIGHT:
        raise ValueError(f"unsupported screenshot dimensions {image.size}: {path}")
    return image


def evaluate(reference_paths: Iterable[Path], candidate_paths: Iterable[Path]) -> dict[str, Any]:
    references = [(path, open_rgb(path)) for path in reference_paths]
    candidates = [(path, open_rgb(path)) for path in candidate_paths]
    if not references:
        raise ValueError("at least one reference capture is required")
    if not candidates:
        raise ValueError("at least one candidate capture is required")

    approved: dict[tuple[int, int, int, int], set[str]] = {}
    for path, image in references:
        bbox, digest = logo_signature(image)
        if bbox is None or digest is None:
            raise ValueError(f"reference has no visible logo: {path}")
        approved.setdefault(bbox, set()).add(digest)
    approved_center2 = {bbox[0] + bbox[2] for bbox in approved}

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    loading_text_visible = False
    for path, image in candidates:
        bbox, digest = logo_signature(image)
        top_bbox = nonblack_bbox(image, TOP_REGION)
        bottom_bbox = nonblack_bbox(image, BOTTOM_REGION)
        loading_text_visible |= top_bbox is not None and bottom_bbox is not None
        unexpected = unexpected_nonblack_pixels(image)
        fully_visible = bbox is not None and bbox[0] > 0 and bbox[2] < image.width
        geometry_approved = bbox in approved
        pixels_approved = bool(
            bbox is not None
            and digest is not None
            and bbox in approved
            and digest in approved[bbox]
        )
        centered = bool(
            bbox is not None
            and any(abs((bbox[0] + bbox[2]) - center2) <= 1 for center2 in approved_center2)
        )
        row = {
            "path": str(path),
            "sha256": sha256(path),
            "size": list(image.size),
            "logo_bbox": list(bbox) if bbox else None,
            "logo_crop_sha256": digest,
            "top_text_bbox": list(top_bbox) if top_bbox else None,
            "bottom_text_bbox": list(bottom_bbox) if bottom_bbox else None,
            "unexpected_nonblack_pixels": unexpected,
            "checks": {
                "logo_fully_visible": fully_visible,
                "logo_geometry_approved": geometry_approved,
                "logo_pixels_approved": pixels_approved,
                "logo_horizontally_centered": centered,
                "no_unexpected_nonblack_pixels": unexpected == 0,
            },
        }
        for name, passed in row["checks"].items():
            if not passed:
                failures.append(f"{path.name}: {name}")
        rows.append(row)

    if not loading_text_visible:
        failures.append("loading/status text absent from every candidate capture")

    return {
        "schema": 1,
        "kind": "boot_presentation_component_gate",
        "authority": "component_only",
        "status": "pass" if not failures else "fail",
        "approved_logo_bboxes": [list(value) for value in sorted(approved)],
        "checks": {
            "all_candidate_logo_frames_green": not any(
                not all(row["checks"].values()) for row in rows
            ),
            "loading_text_visible_in_sequence": loading_text_visible,
        },
        "failures": failures,
        "captures": rows,
        "scope_note": (
            "Visual component gate only; does not prove fresh power, ROM hash, "
            "runtime-mutation absence, boot liveness, or promotion eligibility."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, action="append", required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate(args.reference, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
