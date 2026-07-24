#!/usr/bin/env python3
"""Validate a legal Superman arcade ROM set and prepare private build inputs.

This tool supports the World ``superman`` set used by MAME 0.287.  It never
prints ROM contents.  See docs/PREPARE_ROMS.md for provenance and legal notes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence


class RomPreparationError(RuntimeError):
    """A user-actionable ROM preparation failure."""


@dataclass(frozen=True)
class RomSpec:
    name: str
    size: int
    sha1: str
    sha256: str
    purpose: str


@dataclass(frozen=True)
class OutputSpec:
    relative_path: str
    size: int
    sha256: str
    provenance: str


@dataclass(frozen=True)
class DrumSpec:
    name: str
    start: int
    end: int
    rate: int
    max_milliseconds: int
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceEntry:
    """One candidate file without exposing its contents in diagnostics."""

    display_name: str
    basename: str
    size: int
    read_bytes: Callable[[], bytes]


WORLD_ROMS: tuple[RomSpec, ...] = (
    RomSpec(
        "b61_09.a10",
        131_072,
        "e768d32eae1dba39c23189996fbd5454c8627809",
        "9991feb784e95cb7cc18e98777d28f39648700e4fbe07f46c23610144d1f0211",
        "68000 program, low even byte lane",
    ),
    RomSpec(
        "b61_07.a5",
        131_072,
        "8b562712810a5a72f4647f1ba1314a1be2e249e7",
        "cbc1b47d6b49736445c23ce6bd37f9e47f1a66ebd7a9d1f091b372f196d77d86",
        "68000 program, low odd byte lane",
    ),
    RomSpec(
        "b61_08.a8",
        131_072,
        "bf42b3f84dcad8fd9085c702a78dc895cc12d670",
        "a293be12c8dfcb255cb0b3333e1473eb65baa606717556e06c052a52c3963e87",
        "68000 program, high even byte lane",
    ),
    RomSpec(
        "b61_13.a3",
        131_072,
        "16f7cd6438e47fdaac93a368df5c093f6ff0f1f0",
        "685768026d4565afe2c2ccf5a6e134ca6448324c1770e65cbe728071620ebcff",
        "68000 program, high odd byte lane (World set)",
    ),
    RomSpec(
        "b61_10.d18",
        65_536,
        "7a76efaaeab71473f4b0b23a89141f203488ce1d",
        "818041e72708102ab0495a4cf112cc96c45408ff4a28a5a732baf6bd969ac523",
        "Z80 sound program required for faithful MAME boot",
    ),
    RomSpec(
        "b61-14.f1",
        524_288,
        "8d227439ab321fd5d432d860544daea0e78ce588",
        "6c9deb688a1e9ecc6c22e2b87eee8dd82c3f9bf81f36c2f64c8ab94b41cd7458",
        "graphics lane 0, low half",
    ),
    RomSpec(
        "b61-15.h1",
        524_288,
        "9ecfa84123a8f9d048f0a689647e92f25af73899",
        "d68aeb59866f47a93979bb9be59058665f002066244b700fb5b87adb506b6a36",
        "graphics lane 0, high half",
    ),
    RomSpec(
        "b61-16.j1",
        524_288,
        "03f4383f6ff8b5f1e26bc6bbef2fb1855d3bb93f",
        "544d6c9b3c5814edb5b5c628466cd633c7ecec536edc0d76278bd178f3c4e0dd",
        "graphics lane 1, low half",
    ),
    RomSpec(
        "b61-17.k1",
        524_288,
        "07ee02c18ce29f35e8ae87d0c1ed80b726c246a6",
        "d20107f868e75b5ff4755c037a5092c1ee659960a20a6a980258683a1a855441",
        "graphics lane 1, high half",
    ),
    RomSpec(
        "b61-01.e18",
        524_288,
        "f6febf9bda87ca04f0a5890d0e8001c26dfa6c81",
        "d6edab29029b6ba4c5dd3b701835509d93c78668efe8b07976eb4e4abc168556",
        "YM2610 ADPCM data required for faithful MAME boot",
    ),
    RomSpec(
        "b61_11.m11",
        8_192,
        "6ba3ba35fe313af77d732412572d91a202b50542",
        "c4aaecc43c071776a2a92ce9a5810a197c60297a4e3225ac94f942501f938c8f",
        "priority PROM",
    ),
    RomSpec(
        "cchip_upd78c11.bin",
        4_096,
        "73bc4b46cd2d6805ec926f39f22af00e38a3f822",
        "eb4a04aa470024829c857311eba9d3592264b4af71a31d2f66875c87fe378c59",
        "C-Chip uPD78C11 internal mask ROM",
    ),
)


# Known clone program ROMs are recognized only to produce a useful rejection.
# The port's program-image oracle is specifically the World set.
UNSUPPORTED_CLONE_ROMS: tuple[RomSpec, ...] = (
    RomSpec(
        "b61_12.a3",
        131_072,
        "75abf924a6e44203169d2fa15852caa0bf57db30",
        "",
        "US clone (supermanu) program ROM",
    ),
    RomSpec(
        "b61_06.a3",
        131_072,
        "b0b42c55d2404c7c193eb8cab3bd92e321947845",
        "",
        "Japan clone (supermanj) program ROM",
    ),
)


CORE_OUTPUTS: tuple[OutputSpec, ...] = (
    OutputSpec(
        "data/superman_m68k.bin",
        524_288,
        "6aa9c5b5b55e1545b4da7c2c8610ea01addb096101a667db3f86441d454d197e",
        "four 68000 program ROMs, MAME ROM_LOAD16_BYTE layout",
    ),
    OutputSpec(
        "tools/mame-trace/gfx1.bin",
        2_097_152,
        "6527c0ddcee69affb98ad75cd50791eadbe5d5dfeb2c6b303b0508638eda90af",
        "four graphics ROMs, MAME ROM_LOAD32_WORD_SWAP layout",
    ),
    OutputSpec(
        "data/cchip_boot_response.bin",
        256,
        "75058de1067ddab83ff6b6577be4052b611680c1a344a090bd861d615398f864",
        "C-Chip command-1 response captured from an organic MAME boot",
    ),
)


DRUMS: tuple[DrumSpec, ...] = (
    DrumSpec(
        "sm_drum_060000", 0x060000, 0x0629FF, 10_500, 350, 7_372,
        "7b27258f3fae57e35fc8dabfb1b3042c8c348abeca862304703e25aa6bf5b625",
    ),
    DrumSpec(
        "sm_drum_062a00", 0x062A00, 0x0651FF, 10_500, 350, 7_372,
        "fb24209cacc249e62b73b86d320628a7955ebf9ec2cff4dad13e49c59a65b65f",
    ),
    DrumSpec(
        "sm_drum_065200", 0x065200, 0x0677FF, 10_500, 350, 7_372,
        "040fb5b439b155de05b6df74b7ba7feaa3a777b8641b83fde5fe068d26a433ac",
    ),
    DrumSpec(
        "sm_drum_067800", 0x067800, 0x069EFF, 10_500, 350, 7_372,
        "1205e876fec697656da1b2b49f8bc71d55a403976cbc772fb253d957a6d088d5",
    ),
    DrumSpec(
        "sm_drum_069f00", 0x069F00, 0x06C4FF, 10_500, 350, 7_372,
        "020a70d193aa13458a9a2f95bf91f21d5f9f9eb31e2a2dc0d197fe75d53423a2",
    ),
    DrumSpec(
        "sm_drum_06c500", 0x06C500, 0x06F8FF, 9_000, 420, 7_596,
        "4443a7ee0ff184f010041b4cc8c8a35abee3869a08f94eee870dfd1698a33c53",
    ),
    DrumSpec(
        "sm_drum_06f900", 0x06F900, 0x0727FF, 9_000, 420, 7_596,
        "f0572bb0045e82fcfd279bb191e48425412d0efb95966f6ef42c7eed59aeb470",
    ),
    DrumSpec(
        "sm_drum_072800", 0x072800, 0x0757FF, 10_500, 350, 7_372,
        "cd20d0c231da2ed2ab5460c1c0eba119da027bf6ca28d5c64a47c00115ac9486",
    ),
    DrumSpec(
        "sm_drum_075800", 0x075800, 0x0778FF, 10_500, 350, 7_372,
        "61f64ef3c152c0d469cab5077a67af53b48bffc2410b41a2f2cfa0651c1ee830",
    ),
    DrumSpec(
        "sm_drum_077900", 0x077900, 0x0799FF, 10_500, 350, 7_372,
        "65b6dc165d994adc86397f71ec83093143eb01e8b8e5a23fd606542f1454a899",
    ),
    DrumSpec(
        "sm_drum_079a00", 0x079A00, 0x07B4FF, 10_500, 350, 7_372,
        "76214125518068e6f9d3f1a1b57abd8214c17dd11b30cf4c50345d174047924a",
    ),
    DrumSpec(
        "sm_drum_07b500", 0x07B500, 0x07F1FF, 9_000, 500, 9_036,
        "0132b46bfc19ae08745a2c1f412d736e7b6027b7ca888365dfce21dad5092837",
    ),
)


def drum_output_spec(drum: DrumSpec) -> OutputSpec:
    return OutputSpec(
        f"soundwork/tad/mml_drafts/instruments/{drum.name}.wav",
        drum.size,
        drum.sha256,
        (
            f"b61-01.e18 YM2610 ADPCM-A window "
            f"{drum.start:#08x}-{drum.end:#08x}"
        ),
    )


OUTPUTS: tuple[OutputSpec, ...] = CORE_OUTPUTS + tuple(
    drum_output_spec(drum) for drum in DRUMS
)

ROM_BY_NAME = {spec.name.casefold(): spec for spec in WORLD_ROMS}
CLONE_BY_NAME = {spec.name.casefold(): spec for spec in UNSUPPORTED_CLONE_ROMS}
KNOWN_ROM_NAMES = set(ROM_BY_NAME) | set(CLONE_BY_NAME)
EXPECTED_SIZES = {spec.size for spec in WORLD_ROMS + UNSUPPORTED_CLONE_ROMS}
OUTPUT_BY_PATH = {spec.relative_path: spec for spec in OUTPUTS}


def digest_bytes(data: bytes) -> tuple[str, str]:
    return hashlib.sha1(data).hexdigest(), hashlib.sha256(data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_zip_basename(name: str) -> str:
    # ZIP member paths always use forward slashes.  Only the basename matters
    # for MAME ROM identity; parent names are retained in display diagnostics.
    return PurePosixPath(name).name


def _directory_entry(path: Path, source_root: Path) -> SourceEntry:
    display = str(path.relative_to(source_root))
    stat = path.stat()
    return SourceEntry(display, path.name, stat.st_size, path.read_bytes)


def _zip_entries(path: Path, source_root: Path | None = None) -> list[SourceEntry]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RomPreparationError(f"cannot read ZIP archive {path}: {exc}") from exc

    prefix = path.name if source_root is None else str(path.relative_to(source_root))
    entries: list[SourceEntry] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            basename = _safe_zip_basename(info.filename)
            folded = basename.casefold()
            # Read canonical/known-clone names even when their reported size is
            # wrong, so validation can explain the exact mismatch.  Also admit
            # expected sizes to recognize a correctly dumped but renamed file.
            if (
                folded not in ROM_BY_NAME
                and folded not in CLONE_BY_NAME
                and info.file_size not in EXPECTED_SIZES
            ):
                continue
            if info.flag_bits & 0x1:
                raise RomPreparationError(
                    f"{prefix}!{info.filename} is encrypted; supply an unencrypted ROM archive"
                )

            def read_member(
                archive_path: Path = path, member_name: str = info.filename
            ) -> bytes:
                try:
                    with zipfile.ZipFile(archive_path) as member_archive:
                        return member_archive.read(member_name)
                except (OSError, KeyError, zipfile.BadZipFile) as exc:
                    raise RomPreparationError(
                        f"cannot read {archive_path.name}!{member_name}: {exc}"
                    ) from exc

            entries.append(
                SourceEntry(
                    f"{prefix}!{info.filename}",
                    basename,
                    info.file_size,
                    read_member,
                )
            )
    return entries


def _zip_names_known_rom(path: Path) -> bool:
    """Cheaply identify a generic archive that names at least one known ROM."""

    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                _safe_zip_basename(info.filename).casefold()
                in KNOWN_ROM_NAMES
                for info in archive.infolist()
                if not info.is_dir()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def collect_source_entries(source: Path) -> list[SourceEntry]:
    """Collect useful direct files or ZIP members from a user-supplied source."""

    if not source.exists():
        raise RomPreparationError(f"input path does not exist: {source}")
    if source.is_file():
        if source.suffix.casefold() != ".zip":
            raise RomPreparationError(
                f"input file is not a ZIP archive: {source}\n"
                "Pass either a ROM directory or a .zip containing the ROM files."
            )
        entries = _zip_entries(source)
    elif source.is_dir():
        direct_files = sorted(
            (path for path in source.iterdir() if path.is_file()),
            key=lambda path: path.name.casefold(),
        )
        entries = [
            _directory_entry(path, source)
            for path in direct_files
            if path.suffix.casefold() != ".zip"
            and (
                path.name.casefold() in ROM_BY_NAME
                or path.name.casefold() in CLONE_BY_NAME
                or path.stat().st_size in EXPECTED_SIZES
            )
        ]
        zip_paths = [path for path in direct_files if path.suffix.casefold() == ".zip"]
        world_archives = [
            path for path in zip_paths if path.name.casefold() == "superman.zip"
        ]
        named_clone_archives = [
            path
            for path in zip_paths
            if path.name.casefold()
            in {"supermanu.zip", "supermanj.zip"}
        ]
        if world_archives:
            # A full MAME rompath may also contain clone archives.  Once the
            # exact World archive is present they are outside the selected set,
            # not duplicate input files.
            selected_archives = world_archives
        elif named_clone_archives:
            selected_archives = named_clone_archives
        else:
            selected_archives = [
                path for path in zip_paths if _zip_names_known_rom(path)
            ]
            # A single generically named ZIP may contain checksum-identifiable
            # renamed files.  Avoid scanning every archive in a full ROM path.
            if not selected_archives and not entries and len(zip_paths) == 1:
                selected_archives = zip_paths
        for archive_path in selected_archives:
            entries.extend(_zip_entries(archive_path, source))
    else:
        raise RomPreparationError(f"input path is not a regular file or directory: {source}")

    if not entries:
        raise RomPreparationError(
            f"no candidate Superman ROM files found in {source}\n"
            "Expected loose files or a ZIP containing the MAME 'superman' World set."
        )
    return entries


def _read_and_hash(entry: SourceEntry) -> tuple[bytes, str, str]:
    data = entry.read_bytes()
    if len(data) != entry.size:
        raise RomPreparationError(
            f"{entry.display_name} changed while it was being read "
            f"(listed as {entry.size} bytes, read {len(data)} bytes)"
        )
    sha1, sha256 = digest_bytes(data)
    return data, sha1, sha256


def resolve_rom_set(
    entries: Sequence[SourceEntry],
    specs: Sequence[RomSpec] = WORLD_ROMS,
) -> tuple[dict[str, bytes], list[str]]:
    """Resolve and authenticate a ROM set.

    Exact names are required when present.  A uniquely renamed file is accepted
    only when both its size and cryptographic checksums identify it.
    """

    by_name: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        by_name.setdefault(entry.basename.casefold(), []).append(entry)

    duplicate_names = {
        name: matches
        for name, matches in by_name.items()
        if len(matches) > 1 and any(name == spec.name.casefold() for spec in specs)
    }
    if duplicate_names:
        details = []
        for name, matches in sorted(duplicate_names.items()):
            details.append(
                f"  {name}: " + ", ".join(match.display_name for match in matches)
            )
        raise RomPreparationError(
            "duplicate required ROM filenames found; remove the duplicate copies:\n"
            + "\n".join(details)
        )

    # Cache reads because renamed-file recognition may consider an entry more
    # than once. Keys are object identities so physically distinct entries with
    # equal metadata cannot collapse into one cache record.
    cache: dict[int, tuple[bytes, str, str]] = {}

    def load(entry: SourceEntry) -> tuple[bytes, str, str]:
        key = id(entry)
        if key not in cache:
            cache[key] = _read_and_hash(entry)
        return cache[key]

    resolved: dict[str, bytes] = {}
    notes: list[str] = []
    used_entries: set[int] = set()
    problems: list[str] = []

    for spec in specs:
        exact = by_name.get(spec.name.casefold(), [])
        if exact:
            entry = exact[0]
            if entry.size != spec.size:
                problems.append(
                    f"{spec.name}: wrong size in {entry.display_name}; "
                    f"expected {spec.size} bytes, found {entry.size}"
                )
                continue
            data, sha1, sha256 = load(entry)
            if sha1 != spec.sha1 or sha256 != spec.sha256:
                problems.append(
                    f"{spec.name}: checksum mismatch in {entry.display_name}\n"
                    f"    expected SHA-1   {spec.sha1}\n"
                    f"    actual   SHA-1   {sha1}\n"
                    f"    expected SHA-256 {spec.sha256}\n"
                    f"    actual   SHA-256 {sha256}"
                )
                continue
            resolved[spec.name] = data
            used_entries.add(id(entry))
            continue

        checksum_matches: list[tuple[SourceEntry, bytes]] = []
        for entry in entries:
            if id(entry) in used_entries or entry.size != spec.size:
                continue
            data, sha1, sha256 = load(entry)
            if sha1 == spec.sha1 and sha256 == spec.sha256:
                checksum_matches.append((entry, data))
        if len(checksum_matches) == 1:
            entry, data = checksum_matches[0]
            resolved[spec.name] = data
            used_entries.add(id(entry))
            notes.append(
                f"{entry.display_name} recognized by checksum as {spec.name}"
            )
        elif len(checksum_matches) > 1:
            locations = ", ".join(entry.display_name for entry, _ in checksum_matches)
            problems.append(
                f"{spec.name}: duplicated under multiple names: {locations}"
            )
        else:
            problems.append(f"{spec.name}: missing ({spec.purpose})")

    # Even an extra renamed copy of a required ROM is ambiguous and should be
    # surfaced instead of silently ignored.
    for spec in specs:
        matching_entries: list[SourceEntry] = []
        for entry in entries:
            if entry.size != spec.size:
                continue
            _, sha1, sha256 = load(entry)
            if sha1 == spec.sha1 and sha256 == spec.sha256:
                matching_entries.append(entry)
        if len(matching_entries) > 1:
            locations = ", ".join(entry.display_name for entry in matching_entries)
            marker = f"{spec.name}: duplicated"
            if not any(problem.startswith(marker) for problem in problems):
                problems.append(
                    f"{spec.name}: duplicated ROM contents found at {locations}"
                )

    if problems:
        clone_hint = identify_unsupported_clone(entries, load)
        suffix = f"\n\n{clone_hint}" if clone_hint else ""
        raise RomPreparationError(
            "ROM set validation failed:\n  " + "\n  ".join(problems) + suffix
        )
    return resolved, notes


def identify_unsupported_clone(
    entries: Sequence[SourceEntry],
    loader: Callable[[SourceEntry], tuple[bytes, str, str]],
) -> str | None:
    for clone in UNSUPPORTED_CLONE_ROMS:
        for entry in entries:
            if entry.basename.casefold() != clone.name.casefold():
                continue
            if entry.size != clone.size:
                continue
            _, sha1, _ = loader(entry)
            if sha1 == clone.sha1:
                set_name = "supermanu (US)" if clone.name == "b61_12.a3" else "supermanj (Japan)"
                return (
                    f"Detected the unsupported {set_name} clone via {clone.name}. "
                    "This project currently requires the World 'superman' set, "
                    "whose fourth program ROM is b61_13.a3."
                )
    return None


def interleave_byte_lanes(even: bytes, odd: bytes) -> bytes:
    if len(even) != len(odd):
        raise RomPreparationError(
            f"cannot interleave unequal byte lanes ({len(even)} and {len(odd)} bytes)"
        )
    output = bytearray(len(even) * 2)
    output[0::2] = even
    output[1::2] = odd
    return bytes(output)


def build_m68k(roms: Mapping[str, bytes]) -> bytes:
    low = interleave_byte_lanes(roms["b61_09.a10"], roms["b61_07.a5"])
    high = interleave_byte_lanes(roms["b61_08.a8"], roms["b61_13.a3"])
    return low + high


def load32_word_swap(output: bytearray, data: bytes, offset: int) -> None:
    """Apply MAME's ROM_LOAD32_WORD_SWAP to one even-sized source ROM."""

    if len(data) % 2:
        raise RomPreparationError(
            f"ROM_LOAD32_WORD_SWAP source has odd size {len(data)}"
        )
    pairs = len(data) // 2
    final_index = offset + pairs * 4
    last_written = offset + (pairs - 1) * 4 + 1 if pairs else offset
    if offset < 0 or (pairs and last_written >= len(output)):
        raise RomPreparationError(
            f"ROM_LOAD32_WORD_SWAP range {offset:#x}..{last_written + 1:#x} "
            f"does not fit output size {len(output):#x}"
        )
    output[offset:final_index:4] = data[1::2]
    output[offset + 1 : final_index:4] = data[0::2]


def build_gfx(roms: Mapping[str, bytes]) -> bytes:
    output = bytearray(2_097_152)
    load32_word_swap(output, roms["b61-16.j1"], 0x000000)
    load32_word_swap(output, roms["b61-14.f1"], 0x000002)
    load32_word_swap(output, roms["b61-17.k1"], 0x100000)
    load32_word_swap(output, roms["b61-15.h1"], 0x100002)
    return bytes(output)


ADPCMA_RATE = 18_518
ADPCMA_STEP_TABLE = (
    16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253,
    279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876,
    963, 1060, 1166, 1282, 1411, 1552,
)
ADPCMA_STEP_ADJUST = (-1, -1, -1, -1, 2, 5, 7, 9)


def decode_adpcm_a(data: bytes) -> list[int]:
    """Decode Yamaha ADPCM-A using the proven vgm_extract_adpcm.py logic."""

    output: list[int] = []
    accumulator = 0
    step_index = 0
    for byte in data:
        for nibble in (byte >> 4, byte & 0x0F):
            step = ADPCMA_STEP_TABLE[step_index]
            delta = step >> 3
            if nibble & 1:
                delta += step >> 2
            if nibble & 2:
                delta += step >> 1
            if nibble & 4:
                delta += step
            accumulator += -delta if nibble & 8 else delta
            accumulator = max(-32_768, min(32_767, accumulator))
            output.append(accumulator)
            step_index += ADPCMA_STEP_ADJUST[nibble & 7]
            step_index = max(0, min(48, step_index))
    return output


def resample_linear(
    samples: Sequence[int], source_rate: int, destination_rate: int
) -> list[int]:
    """Match prep_drums.py's deterministic linear integer resampler."""

    if destination_rate == source_rate:
        return list(samples)
    output_length = int(len(samples) * destination_rate / source_rate)
    ratio = source_rate / destination_rate
    output: list[int] = []
    for index in range(output_length):
        source_position = index * ratio
        source_index = int(source_position)
        fraction = source_position - source_index
        first = samples[source_index]
        second = (
            samples[source_index + 1]
            if source_index + 1 < len(samples)
            else first
        )
        output.append(int(first + (second - first) * fraction))
    return output


def mono_pcm16_wav(samples: Sequence[int], rate: int) -> bytes:
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


def build_drum_wavs(adpcm_rom: bytes) -> dict[str, bytes]:
    """Reproduce the 12 ARAM-budgeted drum WAVs from b61-01.e18."""

    outputs: dict[str, bytes] = {}
    for drum in DRUMS:
        if drum.end >= len(adpcm_rom):
            raise RomPreparationError(
                f"{drum.name} source window ends at {drum.end:#x}, "
                f"past ADPCM ROM size {len(adpcm_rom):#x}"
            )
        decoded = decode_adpcm_a(adpcm_rom[drum.start : drum.end + 1])
        samples = resample_linear(decoded, ADPCMA_RATE, drum.rate)
        sample_limit = drum.max_milliseconds * drum.rate // 1_000
        sample_count = min(len(samples), sample_limit)
        sample_count -= sample_count % 16
        samples = samples[:sample_count]

        fade_samples = min(60 * drum.rate // 1_000, sample_count)
        for index in range(fade_samples):
            sample_index = sample_count - fade_samples + index
            samples[sample_index] = int(
                samples[sample_index] * (fade_samples - index) / fade_samples
            )

        relative_path = (
            f"soundwork/tad/mml_drafts/instruments/{drum.name}.wav"
        )
        outputs[relative_path] = mono_pcm16_wav(samples, drum.rate)
    return outputs


def verify_output_bytes(spec: OutputSpec, data: bytes) -> None:
    actual_hash = sha256_bytes(data)
    errors = []
    if len(data) != spec.size:
        errors.append(f"expected {spec.size} bytes, generated {len(data)}")
    if actual_hash != spec.sha256:
        errors.append(f"expected SHA-256 {spec.sha256}, generated {actual_hash}")
    if errors:
        raise RomPreparationError(
            f"derived output verification failed for {spec.relative_path}: "
            + "; ".join(errors)
        )


def _lua_quote(value: str) -> str:
    # Lua accepts the same basic double-quoted escaping used here.  POSIX paths
    # cannot contain NUL; escape the only characters significant to this script.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def build_cchip_capture_lua(snapshot_prefix: Path, frames: int = 180) -> str:
    """Return a small MAME script that snapshots the dynamic command-1 payload."""

    return f"""\
local cpu = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local frame = 0
local prefix = {_lua_quote(str(snapshot_prefix))}

local function snapshot()
  local path = string.format("%s.%03d", prefix, frame)
  local file = assert(io.open(path, "wb"))
  for i = 0, 255 do
    file:write(string.char(prog:read_u8(0xF01B20 + i)))
  end
  file:close()
end

local function on_frame()
  frame = frame + 1
  snapshot()
  if frame >= {frames} then manager.machine:exit() end
end

if emu.register_frame_done then emu.register_frame_done(on_frame)
elseif emu.register_frame then emu.register_frame(on_frame)
else error("this MAME build has no frame callback API") end
"""


def find_mame(explicit: str | None) -> str:
    requested = explicit or os.environ.get("MAME")
    if requested:
        candidate = shutil.which(requested) if os.sep not in requested else requested
        if not candidate or not Path(candidate).is_file():
            raise RomPreparationError(
                f"MAME executable not found: {requested}\n"
                "Install MAME 0.287 or pass --mame /path/to/mame."
            )
        return str(candidate)
    candidate = shutil.which("mame")
    if not candidate:
        raise RomPreparationError(
            "MAME is required to derive data/cchip_boot_response.bin but was not found.\n"
            "Install MAME 0.287, set MAME=/path/to/mame, or pass --mame /path/to/mame."
        )
    return candidate


def check_mame_version(mame: str) -> str:
    try:
        result = subprocess.run(
            [mame, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RomPreparationError(f"could not run MAME version check: {exc}") from exc
    version_line = (result.stdout or result.stderr).splitlines()
    version = version_line[0].strip() if version_line else "(no version reported)"
    if result.returncode != 0:
        raise RomPreparationError(
            f"MAME version check failed with exit code {result.returncode}: {version}"
        )
    if "0.287" not in version:
        raise RomPreparationError(
            f"unsupported MAME version: {version}\n"
            "The dynamic C-Chip derivation is validated against MAME 0.287. "
            "Use --mame to select that version."
        )
    return version


def capture_cchip_response(
    roms: Mapping[str, bytes],
    mame: str,
    *,
    frames: int = 180,
    scratch_parent: Path | None = None,
) -> bytes:
    """Boot the authenticated set in MAME and capture its dynamic 256-byte reply."""

    mame_version = check_mame_version(mame)
    expected = OUTPUT_BY_PATH["data/cchip_boot_response.bin"]
    # Strictly confined MAME packages (notably the snap) cannot see the host's
    # ordinary /tmp namespace.  Keep the ephemeral staging directory beside
    # the checked-out tool by default; it is still removed on every exit.
    scratch_parent = scratch_parent or (
        Path(__file__).resolve().parent.parent / "build"
    )
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="prepare-roms-mame-", dir=scratch_parent
    ) as tmp_name:
        tmp = Path(tmp_name)
        rom_dir = tmp / "roms"
        rom_dir.mkdir()
        with zipfile.ZipFile(
            rom_dir / "superman.zip", "w", compression=zipfile.ZIP_STORED
        ) as archive:
            for spec in WORLD_ROMS:
                archive.writestr(spec.name, roms[spec.name])
        # Some MAME installations resolve the device ROM through its parent set.
        with zipfile.ZipFile(
            rom_dir / "cchip.zip", "w", compression=zipfile.ZIP_STORED
        ) as archive:
            archive.writestr(
                "cchip_upd78c11.bin", roms["cchip_upd78c11.bin"]
            )

        snapshot_prefix = tmp / "cchip-response"
        script = tmp / "capture_cchip.lua"
        script.write_text(
            build_cchip_capture_lua(snapshot_prefix, frames),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.setdefault("SDL_VIDEODRIVER", "dummy")
        env.setdefault("SDL_AUDIODRIVER", "dummy")
        command = [
            mame,
            "superman",
            "-rompath",
            str(rom_dir),
            "-video",
            "none",
            "-sound",
            "none",
            "-nothrottle",
            "-skip_gameinfo",
            "-seconds_to_run",
            str(max(6, frames // 60 + 3)),
            "-autoboot_script",
            str(script),
            "-autoboot_delay",
            "0",
            "-nvram_directory",
            str(tmp / "nvram"),
            "-cfg_directory",
            str(tmp / "cfg"),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=45,
            )
        except subprocess.TimeoutExpired as exc:
            raise RomPreparationError(
                "MAME timed out while deriving the C-Chip boot response"
            ) from exc
        except OSError as exc:
            raise RomPreparationError(f"could not launch MAME: {exc}") from exc

        snapshots = sorted(tmp.glob("cchip-response.*"))
        for path in snapshots:
            data = path.read_bytes()
            if len(data) == expected.size and sha256_bytes(data) == expected.sha256:
                return data

        diagnostic = "\n".join(
            line
            for line in (result.stdout + "\n" + result.stderr).splitlines()
            if any(
                marker in line.casefold()
                for marker in ("error", "fatal", "not found", "incorrect", "required")
            )
        )
        diagnostic = diagnostic[-2000:]
        detail = f"\nMAME diagnostics:\n{diagnostic}" if diagnostic else ""
        raise RomPreparationError(
            "MAME completed without producing the expected C-Chip command-1 response.\n"
            f"Version: {mame_version}; snapshots inspected: {len(snapshots)}; "
            f"MAME exit code: {result.returncode}.\n"
            "The ROM set itself passed all checksums. Confirm that this is an "
            "unmodified MAME 0.287 build with Lua enabled."
            + detail
        )


def derive_outputs(
    roms: Mapping[str, bytes],
    mame: str,
    *,
    scratch_parent: Path | None = None,
) -> dict[str, bytes]:
    outputs = {
        "data/superman_m68k.bin": build_m68k(roms),
        "tools/mame-trace/gfx1.bin": build_gfx(roms),
        "data/cchip_boot_response.bin": capture_cchip_response(
            roms, mame, scratch_parent=scratch_parent
        ),
    }
    outputs.update(build_drum_wavs(roms["b61-01.e18"]))
    for relative_path, data in outputs.items():
        verify_output_bytes(OUTPUT_BY_PATH[relative_path], data)
    return outputs


def inspect_existing_outputs(output_root: Path) -> dict[str, str]:
    states: dict[str, str] = {}
    for spec in OUTPUTS:
        target = output_root / spec.relative_path
        if not target.exists():
            states[spec.relative_path] = "missing"
            continue
        if not target.is_file():
            states[spec.relative_path] = "not a regular file"
            continue
        data = target.read_bytes()
        actual_hash = sha256_bytes(data)
        if len(data) == spec.size and actual_hash == spec.sha256:
            states[spec.relative_path] = "verified"
        else:
            states[spec.relative_path] = (
                f"invalid: {len(data)} bytes, SHA-256 {actual_hash}"
            )
    return states


def write_outputs(
    output_root: Path,
    outputs: Mapping[str, bytes],
    *,
    force: bool,
) -> tuple[list[str], list[str]]:
    states = inspect_existing_outputs(output_root)
    invalid = [
        f"{path}: {state}"
        for path, state in states.items()
        if state not in ("missing", "verified")
    ]
    if invalid and not force:
        raise RomPreparationError(
            "refusing to overwrite invalid existing private inputs:\n  "
            + "\n  ".join(invalid)
            + "\nRe-run with --force only after confirming those files may be replaced."
        )

    to_write = [
        path
        for path in outputs
        if states[path] != "verified"
    ]
    staged: list[tuple[Path, Path]] = []
    try:
        for relative_path in to_write:
            target = output_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.prepare-roms-",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(outputs[relative_path])
                    stream.flush()
                    os.fsync(stream.fileno())
                verify_output_bytes(OUTPUT_BY_PATH[relative_path], temporary.read_bytes())
                temporary.chmod(0o600)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            staged.append((temporary, target))

        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)

    unchanged = [path for path, state in states.items() if state == "verified"]
    return to_write, unchanged


def validate_only(output_root: Path) -> None:
    states = inspect_existing_outputs(output_root)
    failures = [
        f"{path}: {state}" for path, state in states.items() if state != "verified"
    ]
    if failures:
        raise RomPreparationError(
            "existing private build input validation failed:\n  "
            + "\n  ".join(failures)
        )
    print("Existing private build inputs:")
    for spec in OUTPUTS:
        print(
            f"  OK {spec.relative_path}: {spec.size} bytes, SHA-256 {spec.sha256}"
        )


def build_argument_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=(
            "Validate a legally obtained Taito Superman World ROM set and "
            "prepare the deterministic private inputs reproducible from that set."
        ),
        epilog=(
            "Examples:\n"
            "  python3 tools/prepare_roms.py /path/to/superman.zip\n"
            "  python3 tools/prepare_roms.py /path/to/loose-roms --dry-run\n"
            "  python3 tools/prepare_roms.py /path/to/roms --validate-only\n\n"
            "Only hashes, sizes, filenames, and status are printed; ROM bytes are never printed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="directory or ZIP containing the legally obtained arcade ROM files",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repo_root,
        help=(
            "project root receiving generated files "
            "(default: repository root inferred from this script)"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="fully validate and derive in temporary storage without writing outputs",
    )
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the supplied set and existing outputs without deriving or writing",
    )
    parser.add_argument(
        "--mame",
        metavar="PATH",
        help="MAME 0.287 executable (default: $MAME or 'mame' on PATH)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output that fails its expected size or SHA-256",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    source = args.source.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()

    entries = collect_source_entries(source)
    roms, notes = resolve_rom_set(entries)
    print("ROM set: superman (World), MAME 0.287")
    print(f"  OK {len(roms)}/{len(WORLD_ROMS)} required ROMs passed size, SHA-1, and SHA-256")
    for note in notes:
        print(f"  NOTE {note}")

    if args.force and (args.dry_run or args.validate_only):
        selected_mode = "--dry-run" if args.dry_run else "--validate-only"
        raise RomPreparationError(f"--force cannot be used with {selected_mode}")

    if args.validate_only:
        validate_only(output_root)
        print(
            "NOTE: exact FM authoring WAVs are a separate preserved input; "
            "see docs/PREPARE_ROMS.md."
        )
        print("Validation complete; no files were written.")
        return 0

    mame = find_mame(args.mame)
    outputs = derive_outputs(roms, mame)
    print("Derived private build inputs:")
    for spec in OUTPUTS:
        print(
            f"  OK {spec.relative_path}: {spec.size} bytes, SHA-256 {spec.sha256}"
        )
    print(
        "NOTE: exact FM authoring WAVs are a separate preserved input; "
        "see docs/PREPARE_ROMS.md."
    )

    if args.dry_run:
        print("Dry run complete; no project files were written.")
        return 0

    written, unchanged = write_outputs(output_root, outputs, force=args.force)
    for relative_path in written:
        print(f"  WROTE {output_root / relative_path}")
    for relative_path in unchanged:
        print(f"  KEPT  {output_root / relative_path} (already verified)")
    print("ROM preparation complete.")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except RomPreparationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
