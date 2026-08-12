# Local SNES/SA-1 reference library

This host has a local, read-only hardware-reference library at
`/home/chad/snesmanual/`. The source material is not part of the repository and must
not be copied into commits or redistributed. Use narrow excerpts selected with `rg`
and `sed`; loading entire OCR books into an agent context wastes tokens and usually
makes the answer worse.

## Source priority and routing

| Local source | Use it for | Useful OCR anchors |
|---|---|---|
| `book1_djvu.txt` | Official Nintendo base-SNES programming rules: CPU, PPU, DMA, controller, APU and startup behavior | Chapter 24 programming cautions starts near line 8857. In particular: paired-register/latch reset (#1), legal VRAM/OAM/CGRAM access periods (#2), indeterminate power-on WRAM (#9), HUD/safe-area guidance (#13), and controller re-enable edges (#16). |
| `book2_djvu.txt` | Official Nintendo SA-1 behavior | Multi-processor operation starts near line 5708; interrupts and shared-memory handshakes follow; shared I-RAM collision priority is near 5968; explicit SA-1 wait causes are near 6078; SA-1 DMA starts near 7692 and its priority/speed rules continue through about 8000. |
| `fullsnes.txt` | Detailed independent register maps, timing notes, open-bus behavior, and implementation cross-checks | General DMA starts near 258; PPU/NMI/HBlank/VBlank material is around 1370; SA-1 begins near 7054. Search for the exact register or subsystem before extracting text. |
| `wdc_65816_programming_manual.pdf` | Generic 65C816 instruction and programming reference | Use for CPU semantics; it is not the authority for SNES or SA-1 bus timing. |
| `gsudevkit/`, `gsudevkit.zip` | Super FX/GSU material | Out of scope for this SA-1 cartridge unless later Gigandes work explicitly selects Super FX. |

Prefer the official Nintendo books when they answer the question. Use `fullsnes.txt`
as a detailed secondary source, especially where it labels behavior as uncertain or
implementation-derived. Resolve remaining uncertainty with the MAME/Nexen oracles and,
when required, real hardware; a manual quotation is not a substitute for a behavioral
test.

## Agent use

- Pure playback watchers do not need these books. They should keep writing large logs
  and frame artifacts to disk and return only the compact discrepancy report.
- For post-divergence diagnosis, search the library only for the implicated subsystem
  and pass a small relevant excerpt to the reasoning task.
- Cite the local filename, section, and approximate OCR line in retained engineering
  notes so a later agent can recover the same passage without rereading a whole book.
- OCR spelling and register formatting are noisy. Verify numeric claims against the
  surrounding section rather than trusting an isolated search hit.
