#!/usr/bin/env python3
# Mechanical transform: Poppy-converted tad-audio.pasm -> Poppy-assemblable module.
# Pass 1: resolve ca65 conditionals for our config (HIROM, no custom defaults; drop segment machinery).
# Pass 2: strip enum/scope wrappers, flatten ::, strip f:/z:, rewrite .lobyte/.hibyte/.loword,
#         drop .assert + linker directives, re-home BSS/ZEROPAGE state vars.
# Hand-fixes (anon labels, ABI, integration) come after, guided by assembly errors.
import re, os

import pathlib
SRC = str(pathlib.Path(__file__).resolve().parent / "tad-audio.converted.pasm")
DST = str(pathlib.Path(__file__).resolve().parent / "tad_audio.pasm")
DEFINES = {"HIROM"}          # LOROM + TAD_CUSTOM_DEFAULTS deliberately unset

BSS_BASE = int(os.environ.get("TAD_BSS_BASE", "0x7EF100"), 0)   # WRAM state block [integration default]
ZP_BASE  = int(os.environ.get("TAD_ZP_BASE",  "0x30"), 0)       # direct page for sfx queue
# For byte-verify vs the ca65 reference, override: TAD_BSS_BASE=0x203 TAD_ZP_BASE=0x18
_jb = os.environ.get("TAD_CODE_BANK")                            # e.g. 0xE9 -> force internal jsl to bank $E9
JSL_BANK = ("$%06X" % (int(_jb, 0) << 16)) if _jb else None

def eval_cond(cond):
    c = cond.strip()
    if 'match(' in c:
        return None          # segment machinery -> drop whole block
    c = re.sub(r'\.defined\(\s*(\w+)\s*\)', lambda m: 'True' if m.group(1) in DEFINES else 'False', c)
    c = c.replace('&&', ' and ').replace('||', ' or ').replace('!', ' not ').replace('.not', ' not ')
    try:
        return bool(eval(c, {"__builtins__": {}}, {}))
    except Exception:
        return None

def resolve_conditionals(lines):
    out, stack = [], []
    live = lambda upto: all(f['emit'] for f in stack[:upto])
    for ln in lines:
        st = ln.strip()
        if re.match(r'if\b', st) and not re.match(r'if(def|ndef)\b', st):
            r = eval_cond(st[2:])
            stack.append({'emit': live(len(stack)) and bool(r), 'done': (r is True), 'drop': r is None}); continue
        m = re.match(r'ifndef\s+(\w+)', st)
        if m:
            r = m.group(1) not in DEFINES
            stack.append({'emit': live(len(stack)) and r, 'done': r, 'drop': False}); continue
        m = re.match(r'ifdef\s+(\w+)', st)
        if m:
            r = m.group(1) in DEFINES
            stack.append({'emit': live(len(stack)) and r, 'done': r, 'drop': False}); continue
        m = re.match(r'elseif\s+(.+)$', st)
        if m and stack:
            f = stack[-1]
            r = False if (f['drop'] or f['done']) else eval_cond(m.group(1))
            f['emit'] = live(len(stack) - 1) and (r is True); f['done'] = f['done'] or (r is True); continue
        if re.match(r'else\b', st) and stack:
            f = stack[-1]
            f['emit'] = (not f['drop']) and (not f['done']) and live(len(stack) - 1); f['done'] = True; continue
        if re.match(r'endif\b', st):
            if stack: stack.pop()
            continue
        if all(f['emit'] for f in stack):
            out.append(ln)
    return out

def strip_scope_qualifiers(s):   # Foo::BAR -> BAR
    return re.sub(r'\b[A-Za-z_]\w*::', '', s)

def rewrite_byte_ops(s):
    # Poppy: `.lobyte/.hibyte/.bankbyte` -> `<`/`>`/`^` PREFIX operators (parens `(E&$ff)` would parse
    # as indirect addressing on a memory operand!). `.bankbyte` is silently DROPPED by Poppy otherwise.
    # `.loword` -> `((E)&$ffff)` (only ever in `#` immediates here, so parens are safe).
    for fn, op in ((r'\.lobyte', '<'), (r'\.hibyte', '>'), (r'\.bankbyte', '^'), (r'\.loword', 'w')):
        while True:
            m = re.search(fn + r'\(', s)
            if not m: break
            i = m.end(); depth = 1; j = i
            while j < len(s) and depth:
                depth += (s[j] == '(') - (s[j] == ')'); j += 1
            inner = s[i:j-1]
            rep = ('((%s)&$ffff)' % inner) if op == 'w' else ('%s(%s)' % (op, inner))
            s = s[:m.start()] + rep + s[j:]
    return s

def strip_addr_prefix(s):
    # f: forces LONG (24-bit) addressing -> Poppy `.l` mnemonic suffix (changes opcode, e.g. cd->cf).
    if re.search(r'(?<=[ \t(,])f:(?=[A-Za-z_.$(0-9<>^])', s):
        s = re.sub(r'(?<=[ \t(,])f:(?=[A-Za-z_.$(0-9<>^])', '', s)
        s = re.sub(r'^(\s*)([a-zA-Z]{2,5})(\s)', r'\1\2.l\3', s, count=1)
    # z: (DP) / a: (abs) -> strip; Poppy already picks the right size for these operands.
    return re.sub(r'(?<=[ \t(,#])[za]:(?=[A-Za-z_.$(0-9<>^])', '', s)

lines = resolve_conditionals(open(SRC).read().split("\n"))
out, seg, bss_off, zp_off = [], None, 0, 0
for ln in lines:
    st = ln.strip()
    m = re.match(r'segment\s+"([^"]+)"', st)
    if m:
        seg = 'ZP' if 'ZERO' in m.group(1).upper() else 'BSS'
        out.append("; [segment %s -> re-homed]" % m.group(1)); continue
    if seg and re.match(r'[A-Za-z_]\w*:\s*fill\s+\d+', st):
        mm = re.match(r'([A-Za-z_]\w*):\s*fill\s+(\d+)', st); name, n = mm.group(1), int(mm.group(2))
        if seg == 'ZP': out.append("%s = $%02X" % (name, ZP_BASE + zp_off)); zp_off += n
        else:           out.append("%s = $%06X" % (name, BSS_BASE + bss_off)); bss_off += n
        continue
    if seg and st and not st.startswith(';') and not re.match(r'[A-Za-z_]\w*:\s*fill', st):
        seg = None
    if re.match(r'(enum|endenum|scope|endscope)\b', st):
        out.append("; " + st); continue
    if re.match(r'assert\b', st):
        out.append("; [assert] " + st); continue
    m = re.match(r'export\s+([A-Za-z_]\w*)\s*:\s*abs\s*=\s*(.+)$', st)
    if m:
        out.append("%s = %s" % (m.group(1), m.group(2))); continue
    if re.match(r'(export|import|exportzp|importzp|autoimport|setcpu|smart)\b', st):
        out.append("; [linker] " + st); continue
    # ca65 register-width directives: Poppy honors them ONLY when DOTTED (converter dropped the dot).
    if st in ('a8', 'a16', 'i8', 'i16'):
        out.append(ln.replace(st, '.' + st, 1)); continue
    ln = strip_addr_prefix(rewrite_byte_ops(strip_scope_qualifiers(ln)))
    # `<(X)` as a MEMORY operand is a DP low-byte access; force `.b` so Poppy sizes it DP in BOTH
    # passes (else pass-1 sizes it abs -> +1 byte, drifting every later label -> wrong branch/jsr operands).
    ln = re.sub(r'^(\s*)(lda|sta|cmp|and|ora|eor|adc|sbc|bit|ldx|ldy|stx|sty)(\s+)<\(', r'\1\2.b\3<(', ln)
    # Force `jsl` to `.l` (4-byte long): Poppy's pass-1 can size a bare `jsl` as 3 bytes while pass-2
    # emits 4, corrupting every preceding branch's target. All TAD jsl targets are rtl-returning.
    # If TAD_CODE_BANK is set (integration), also OR the target with that bank so the absolute jsl
    # lands in the right bank at runtime (Poppy assembles bank-$00 labels; code runs at e.g. $E9).
    if JSL_BANK:
        ln = re.sub(r'^(\s*)jsl(?:\.l)?\s+([A-Za-z_]\w*)\b', r'\1jsl.l \2|%s' % JSL_BANK, ln)
    else:
        ln = re.sub(r'^(\s*)jsl(\s)', r'\1jsl.l\2', ln)
    out.append(ln)

def transform_proc_body(proc_name, body):
    # Poppy DROPS branches to dotted labels (parses `.name` as a directive). So rename EVERY
    # proc-local label (the converter's `.name` @cheap-locals AND non-dotted proc-scoped names like
    # ReturnFalse) to a unique NON-dotted global `<proc>__<name>`. Fixes both dropped branches and
    # cross-proc collisions. Directives (`.a8`/`.i16`, no trailing colon) are untouched.
    # collect proc-local names (lowercased base -> unique global). Sources: label defs `.?@?name:`
    # (sigil optional) and SIGILED equates `[.@]name = expr` (e.g. the `@_BlankSongData = *-1` hack).
    # Converter is inconsistent on sigil (@ vs .) AND case, so match refs case-insensitively w/ any sigil.
    local = {}
    for ln in body:
        m = re.match(r'\s*[.@]?([A-Za-z_]\w*):(?!:)', ln) or re.match(r'\s*[.@]([A-Za-z_]\w*)\s*=(?!=)', ln)
        if m:
            local[m.group(1).lower()] = "%s__%s" % (proc_name, m.group(1))
    res = []
    for ln in body:
        for base in sorted(local, key=len, reverse=True):
            ln = re.sub(r'(?<![\w.@])[.@]?' + re.escape(base) + r'\b', local[base], ln, flags=re.IGNORECASE)
        res.append(ln)
    return res

def process_anon(lines):
    # ca65 anon labels (lone ':' def; ':-'/':+' refs) -> globally-unique non-dotted labels.
    # def-and-ref of a given loop are always tight (no global label between) so nearest-resolution holds.
    anon_defs = []                          # (line_index, name)
    tmp = []
    for idx, ln in enumerate(lines):
        if ln.strip() == ':':
            name = "__anon%d" % len(anon_defs); anon_defs.append((idx, name))
            tmp.append(re.sub(r':\s*$', name + ':', ln))
        else:
            tmp.append(ln)
    def resolve(k, s):
        def repl(m):
            seq = m.group(0)[1:]
            before = [nm for (di, nm) in anon_defs if di < k]
            after  = [nm for (di, nm) in anon_defs if di > k]
            return before[-len(seq)] if seq[0] == '-' else after[len(seq) - 1]
        return re.sub(r':[-+]+', repl, s)
    return [resolve(k, ln) for k, ln in enumerate(tmp)]

def process_macros(lines):
    # Poppy's `macro` mis-emits non-trivial bodies (emits at def site, drops branches). So INLINE
    # the macro bodies at their invocation sites (as ca65 does) and drop the defs. Runs BEFORE the
    # proc/anon passes so the inlined bodies' labels get dot-scoped/uniqued naturally.
    macros, stripped, i, n = {}, [], 0, len(lines)
    while i < n:
        m = re.match(r'\s*macro\s+([A-Za-z_]\w*)', lines[i])
        if m:
            name = m.group(1); body = []; i += 1
            while i < n and not re.match(r'\s*endmacro\b', lines[i]):
                body.append(lines[i]); i += 1
            i += 1                                   # skip endmacro
            macros[name.lower()] = body
            continue
        stripped.append(lines[i]); i += 1
    out = []
    for ln in stripped:                              # inline invocations (bare macro-name lines)
        m = re.match(r'(\s*)([A-Za-z_]\w*)\s*(\(\s*\))?\s*(;.*)?$', ln)
        if m and m.group(2).lower() in macros:
            out.extend(macros[m.group(2).lower()])
        else:
            out.append(ln)
    return out

def process_procs(lines):
    result, i, n = [], 0, len(lines)
    while i < n:
        st = lines[i].strip()
        m = re.match(r'proc\s+([A-Za-z_]\w*)', st)
        if not m:
            result.append(lines[i]); i += 1; continue
        result.append(m.group(1) + ":")     # `proc NAME [: far] [; c]` -> `NAME:`
        j = i + 1; body = []
        while j < n and not re.match(r'endproc\b', lines[j].strip()):
            body.append(lines[j]); j += 1
        result.extend(transform_proc_body(m.group(1), body))
        i = j + 1                            # skip endproc
    return result

out = process_macros(out)
out = process_procs(out)
out = process_anon(out)
os.makedirs(os.path.dirname(DST), exist_ok=True)
open(DST, "w").write("\n".join(out))
print("wrote", DST, "(%d lines)  BSS=%dB ZP=%dB" % (len(out), bss_off, zp_off))
txt = "\n".join(l for l in out if not l.strip().startswith(';'))
for pat in ('::', r'\bf:', r'\bz:', r'\.lobyte', r'\.hibyte', r'\.loword', r'\bmatch\(', r'segment "', r'\berror\b'):
    c = len(re.findall(pat, txt, re.M))
    if c: print("  RESIDUAL %-12s = %d" % (pat, c))
