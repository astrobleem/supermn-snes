# Preparing private ROM inputs

`tools/prepare_roms.py` is the supported user-facing entry point for turning a
legally obtained Taito **Superman** arcade ROM set into the private inputs used by
this repository.

```sh
python3 tools/prepare_roms.py /path/to/superman.zip
# or
python3 tools/prepare_roms.py /path/to/loose-rom-directory
```

The tool accepts a ZIP directly, loose files in a directory, or a `superman.zip`
immediately inside a directory. It authenticates every required ROM before deriving
anything, derives all outputs in memory or temporary storage, verifies each output by
size and SHA-256, and only then writes missing files. Paths are relative to the
repository inferred from the script location. Use `--output-root PATH` for another
checkout or staging tree.

## Supported set

The only supported program set is MAME 0.287 `superman` (World). The `supermanu`
(US) and `supermanj` (Japan) clones have different 68000 program bytes and are
rejected with a set-specific explanation. Supporting a clone requires its own
program-image oracle and port validation; silently substituting one would invalidate
the current build.

All 12 files are required because MAME must perform a complete, organic C-Chip boot
to derive the command-1 response. SHA-1 values below are the MAME 0.287 set
identities. The tool additionally checks pinned SHA-256 values.

| Filename | Size | SHA-1 |
|---|---:|---|
| `b61_09.a10` | 131,072 | `e768d32eae1dba39c23189996fbd5454c8627809` |
| `b61_07.a5` | 131,072 | `8b562712810a5a72f4647f1ba1314a1be2e249e7` |
| `b61_08.a8` | 131,072 | `bf42b3f84dcad8fd9085c702a78dc895cc12d670` |
| `b61_13.a3` | 131,072 | `16f7cd6438e47fdaac93a368df5c093f6ff0f1f0` |
| `b61_10.d18` | 65,536 | `7a76efaaeab71473f4b0b23a89141f203488ce1d` |
| `b61-14.f1` | 524,288 | `8d227439ab321fd5d432d860544daea0e78ce588` |
| `b61-15.h1` | 524,288 | `9ecfa84123a8f9d048f0a689647e92f25af73899` |
| `b61-16.j1` | 524,288 | `03f4383f6ff8b5f1e26bc6bbef2fb1855d3bb93f` |
| `b61-17.k1` | 524,288 | `07ee02c18ce29f35e8ae87d0c1ed80b726c246a6` |
| `b61-01.e18` | 524,288 | `f6febf9bda87ca04f0a5890d0e8001c26dfa6c81` |
| `b61_11.m11` | 8,192 | `6ba3ba35fe313af77d732412572d91a202b50542` |
| `cchip_upd78c11.bin` | 4,096 | `73bc4b46cd2d6805ec926f39f22af00e38a3f822` |

A correctly dumped file with a nonstandard name may be recognized by its unique size,
SHA-1, and SHA-256. Ambiguous copies, duplicate canonical names, wrong sizes, bad
checksums, encrypted ZIP members, missing files, and known clone ROMs all fail before
an output is changed.

## Generated outputs

The core layout is the exact MAME layout already proven by the historical extraction
tools:

- `data/superman_m68k.bin` concatenates two `ROM_LOAD16_BYTE` pairs:
  `b61_09`/`b61_07`, then `b61_08`/`b61_13`.
- `tools/mame-trace/gfx1.bin` applies `ROM_LOAD32_WORD_SWAP` at offsets
  `$000000`, `$000002`, `$100000`, and `$100002` to `b61-16`, `b61-14`,
  `b61-17`, and `b61-15`, respectively.
- `data/cchip_boot_response.bin` is not embedded in any source ROM. The tool stages
  the authenticated set privately, boots it in MAME 0.287, snapshots `$F01B20-$F01C1F`,
  accepts only the pinned response hash, and removes the staging directory.
- The 12 `sm_drum_*.wav` files are decoded directly from the known ADPCM-A windows in
  `b61-01.e18`, then run through the exact resample, trim, and fade policy retained in
  `tools/sound/vgm_extract_adpcm.py` and `tools/sound/prep_drums.py`.

| Output | Size | SHA-256 |
|---|---:|---|
| `data/superman_m68k.bin` | 524,288 | `6aa9c5b5b55e1545b4da7c2c8610ea01addb096101a667db3f86441d454d197e` |
| `tools/mame-trace/gfx1.bin` | 2,097,152 | `6527c0ddcee69affb98ad75cd50791eadbe5d5dfeb2c6b303b0508638eda90af` |
| `data/cchip_boot_response.bin` | 256 | `75058de1067ddab83ff6b6577be4052b611680c1a344a090bd861d615398f864` |
| `…/sm_drum_060000.wav` | 7,372 | `7b27258f3fae57e35fc8dabfb1b3042c8c348abeca862304703e25aa6bf5b625` |
| `…/sm_drum_062a00.wav` | 7,372 | `fb24209cacc249e62b73b86d320628a7955ebf9ec2cff4dad13e49c59a65b65f` |
| `…/sm_drum_065200.wav` | 7,372 | `040fb5b439b155de05b6df74b7ba7feaa3a777b8641b83fde5fe068d26a433ac` |
| `…/sm_drum_067800.wav` | 7,372 | `1205e876fec697656da1b2b49f8bc71d55a403976cbc772fb253d957a6d088d5` |
| `…/sm_drum_069f00.wav` | 7,372 | `020a70d193aa13458a9a2f95bf91f21d5f9f9eb31e2a2dc0d197fe75d53423a2` |
| `…/sm_drum_06c500.wav` | 7,596 | `4443a7ee0ff184f010041b4cc8c8a35abee3869a08f94eee870dfd1698a33c53` |
| `…/sm_drum_06f900.wav` | 7,596 | `f0572bb0045e82fcfd279bb191e48425412d0efb95966f6ef42c7eed59aeb470` |
| `…/sm_drum_072800.wav` | 7,372 | `cd20d0c231da2ed2ab5460c1c0eba119da027bf6ca28d5c64a47c00115ac9486` |
| `…/sm_drum_075800.wav` | 7,372 | `61f64ef3c152c0d469cab5077a67af53b48bffc2410b41a2f2cfa0651c1ee830` |
| `…/sm_drum_077900.wav` | 7,372 | `65b6dc165d994adc86397f71ec83093143eb01e8b8e5a23fd606542f1454a899` |
| `…/sm_drum_079a00.wav` | 7,372 | `76214125518068e6f9d3f1a1b57abd8214c17dd11b30cf4c50345d174047924a` |
| `…/sm_drum_07b500.wav` | 9,036 | `0132b46bfc19ae08745a2c1f412d736e7b6027b7ca888365dfce21dad5092837` |

The abbreviated drum paths above all begin with
`soundwork/tad/mml_drafts/instruments/`.

## Modes and overwrite policy

```sh
# Validate the set and derive everything, but retain no project outputs.
python3 tools/prepare_roms.py /path/to/superman.zip --dry-run

# Validate the set plus already-generated outputs; do not launch MAME or write.
python3 tools/prepare_roms.py /path/to/superman.zip --validate-only

# Prepare a separate checkout or staging tree.
python3 tools/prepare_roms.py /path/to/superman.zip --output-root /path/to/checkout

# Select a pinned MAME binary. $MAME and then PATH are the defaults.
python3 tools/prepare_roms.py /path/to/superman.zip --mame /path/to/mame
```

Correct existing outputs are retained. An existing file with the wrong size or hash
causes the whole operation to stop before writing. `--force` permits replacement, but
only after all source files and newly derived outputs have passed verification.
Writes use same-directory temporary files and atomic replacement.

Default preparation and `--dry-run` require MAME 0.287 with Lua enabled. A confined
MAME package may not see the system `/tmp`, so the tool creates its short-lived MAME
staging directory inside the checkout's gitignored `build/` directory and removes it
on exit.

Run the synthetic regression suite with:

```sh
python3 -m unittest -v tests/test_prepare_roms.py
```

## Audio boundary and fresh clones

The ROM set is sufficient to regenerate the three direct binary inputs and all 12
ADPCM-A drum WAVs above. It is **not currently sufficient to reproduce the exact 45
`fm_p*.wav` authoring samples** used by the consolidated TAD project. Those files came
from the separate VGM patch-capture and ymfm rendering pipeline, including
human-selected patch, loop, envelope, and octave-anchor decisions. The tracked
`fm_instruments.json` records the final bindings but does not retain every input needed
to reproduce the exact WAV bytes from the arcade set alone.

Consequently, a fresh clone can run this ROM preparation tool successfully, but
rebuilding the current 96,065-byte `soundwork/tad/build/audio-data.bin` still requires
restoring the private FM WAV authoring set or rerunning the separately documented sound
pipeline from its external VGM inputs. This is an explicit remaining reproducibility
gap, not something `prepare_roms.py` hides or replaces with placeholder audio.

## Legal boundary

This repository and tool do not download, contain, or redistribute the arcade ROMs.
The user must supply a legally obtained set. The tool prints only filenames, sizes,
hashes, and status—not ROM bytes. All generated binaries and WAVs are derivative
private data covered by `.gitignore`; do not commit or redistribute them. The temporary
MAME archive exists only for the duration of derivation.

The older `tools/build_m68k_rom.py`, `tools/determine_interleave.py`, and sound
extraction tools remain in place as historical/proven references. They were not
deleted or silently replaced.
