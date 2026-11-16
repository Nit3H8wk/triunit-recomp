#!/usr/bin/env python3
"""Publication guard for the repository (stdlib only, Python 3.8+).

Scans file paths and contents for material that must never be published:
ROM/media/binary files, generator output, disassembly in comments, dense
tables of original code addresses, long hex/base64 payloads and the rights
holder's marks outside the allowed files. Every pattern, threshold and
allow-list entry lives in tools/publish/allow.json.

Modes
  (default)       git-tracked files of the working tree, read from disk
  --staged        staged blobs (pre-commit hook)
  --all-objects   every blob reachable from any ref (history audit)

Exit status: 0 no findings, 1 findings, 2 usage or git error.
"""
import argparse
import bisect
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "allow.json"
EXCERPT_MAX = 80
HEX_KEEP = 16
CONTROL_BYTES = bytes(c for c in range(32) if c not in (9, 10, 11, 12, 13, 27))
HIGH_BYTES = bytes(range(0x80, 0x100))

C_LIKE = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inc", ".ipp", ".inl",
          ".cs", ".js", ".mjs", ".ts", ".java", ".rs", ".go", ".sv", ".v", ".glsl", ".hlsl", ".fx"}
HASH_LIKE = {".py", ".pyw", ".ps1", ".psm1", ".sh", ".bash", ".yml", ".yaml", ".toml", ".cfg", ".ini",
             ".cmake", ".mk", ".r", ".pl", ".rb"}
HASH_NAMES = {".gitignore", ".gitattributes", ".graphifyrc", ".graphifyignore", "makefile", "dockerfile"}
DASH_LIKE = {".lua", ".sql"}


class AuditError(Exception):
    pass


# ---------------------------------------------------------------- config

def glob_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def alternation(items):
    return "(?:" + "|".join(items) + ")"


class Config:
    def __init__(self, data):
        self.extensions = {e.lower() for e in data["forbidden_extensions"]}
        self.name_res = [re.compile(r, re.I) for r in data["forbidden_name_regexes"]]
        self.generated_ext = {e.lower() for e in data["generated_include_extensions"]}
        self.binary_ratio = float(data["binary"]["max_control_ratio"])
        self.binary_sample = int(data["binary"]["sample_bytes"])
        gh = data["generated_header"]
        self.gen_lines = int(gh["first_lines"])
        self.gen_re = re.compile(gh["comment_regex"], re.I)
        self.gen_upper_re = re.compile(gh["uppercase_regex"])

        d = data["disassembly"]
        upper = alternation(d["tms34010_mnemonics"] + d["adsp2105_mnemonics"] + d["m6809_mnemonics"])
        lower_words = [m for m in d["tms34010_mnemonics"] + d["adsp2105_mnemonics"] + d["m6809_mnemonics"]
                       if m.isalpha() and m.lower() not in set(x.lower() for x in d["ambiguous_lowercase"])]
        lower = alternation([m.lower() for m in lower_words] + [d["lowercase_regex_extra"]])
        regs = alternation(d["registers"])
        adsp_regs = alternation(d["adsp_registers"])
        addr = d["address_regex"]
        opc = d["opcode_words_regex"]
        deco = d["line_decoration_regex"]
        sp = r"[ \t]"
        adsp_form = (r"(?i:(?:IF" + sp + r"+(?:NOT" + sp + r"+)?[A-Z]{1,7}" + sp + r"+)?(?:" + adsp_regs + r")"
                     + sp + r"*=" + sp + r"*(?:" + adsp_regs + r"\b|[DP]M" + sp + r"*\(|-?(?:0x)?[0-9A-F]+\b)"
                     r"|[DP]M" + sp + r"*\(" + sp + r"*(?:I[0-7]|0x|\d)"
                     r"|IF" + sp + r"+(?:NOT" + sp + r"+)?[A-Z]{1,7}" + sp + r"+(?:JUMP|CALL|RTS|RTI))")
        self.addr_re = re.compile(
            addr + opc + r"(?:(?-i:" + upper + r")\b|(?-i:" + lower + r")\b" + sp + r"+[^\s,;]|" + adsp_form + ")")
        self.list_re = re.compile(
            r"(?m)^" + deco + r"(?:" + addr + opc + r")?(?:[A-Za-z_]\w*:" + sp + r"*)?"
            r"(?:(?-i:" + upper + r")|(?-i:" + lower + r"))" + sp + r"+(?P<ops>.+)$")
        self.list_reg_re = re.compile(r"(?i)(?<![\w$])" + regs + r"(?![\w])")
        self.list_6809_re = re.compile(d["m6809_operand_regex"])
        self.adsp_line_re = re.compile(
            r"(?m)^" + deco + r"(?:IF" + sp + r"+(?:NOT" + sp + r"+)?[A-Z]{1,7}" + sp + r"+)?(?:(?:" + adsp_regs
            + r")" + sp + r"*=" + sp + r"*.*(?:(?<![\w])" + adsp_regs + r"(?![\w])|[DP]M" + sp + r"*\()"
            r"|[DP]M" + sp + r"*\([^)\n]*\)" + sp + r"*=" + sp + r"*(?:" + adsp_regs + r")(?![\w]))")
        self.min_listing = int(d["min_listing_lines"])

        p = data["pc_density"]
        self.pc_threshold = int(p["threshold"])
        self.pc_scope = [glob_regex(g) for g in p["scope"]]
        self.pc_overrides = [(glob_regex(o["path"]), int(o["max"])) for o in p.get("overrides", [])]
        self.pc_re = re.compile(p["address_regex"], re.I)

        h = data["hex_run"]
        self.hex_re = re.compile(r"[0-9A-Fa-f]{%d,}" % int(h["min_hex_digits"]))
        n = int(h["min_literals"]) - 1
        lit = r"[\"']?0x[0-9A-F]{1,8}[UL]{0,3}[\"']?"
        sep = r"[\s{}\[\]()]*,[\s{}\[\]()]*"   # nested initialisers {a,b},{c,d} keep the run going
        self.lit_re = re.compile(r"(?i)(?<![\w])(?:" + lit + sep + r"){%d,}" % n + lit)
        b = data["base64_run"]
        self.b64_re = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{%d,}={0,2}" % int(b["min_chars"]))

        m = data["mark_terms"]
        # patterns are lowercase and matched against lowercased text (much faster than re.I)
        self.mark_lc = re.compile(r"(?<![a-z0-9])" + alternation(m["patterns"]) + r"(?![a-z0-9])")
        self.mark_cs = re.compile(r"(?<![A-Za-z0-9])" + alternation(m["case_sensitive_patterns"])
                                  + r"(?![A-Za-z0-9])")
        self.mark_ci = re.compile(r"(?i)(?<![a-z0-9])" + alternation(m["patterns"]) + r"(?![a-z0-9])")
        self.mark_excl = [re.compile(x, re.I) for x in m["exclude_contexts"]]

        self.allow = []
        for entry in data["allow"]:
            if not entry.get("reason", "").strip():
                raise AuditError("allow.json entry without reason: %r" % entry)
            rules = entry["rule"] if isinstance(entry["rule"], list) else [entry["rule"]]
            self.allow.append((set(rules), glob_regex(entry["path"])))

    def mark_search(self, s):
        low = s.lower()
        rx = self.mark_lc if len(low) == len(s) else self.mark_ci   # offsets must stay valid
        return rx.search(low if rx is self.mark_lc else s) or self.mark_cs.search(s)

    def allowed(self, rule, path):
        return any((rule in rules or "*" in rules) and rx.match(path) for rules, rx in self.allow)


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return Config(json.load(f))


# ---------------------------------------------------------------- helpers

def excerpt(text):
    text = " ".join(text.split())
    text = re.sub(r"[0-9A-Fa-f]{%d,}" % (HEX_KEEP + 1), lambda m: m.group(0)[:HEX_KEEP] + "...", text)
    if len(text) > EXCERPT_MAX:
        text = text[:EXCERPT_MAX - 3] + "..."
    return text


def suffix(path):
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""


def is_binary(data, cfg):
    sample = data[:cfg.binary_sample]
    if not sample:
        return None
    if b"\x00" in sample:
        return "contains NUL bytes"
    ctrl = len(sample) - len(sample.translate(None, CONTROL_BYTES))
    if ctrl / len(sample) > cfg.binary_ratio:
        return "control-byte ratio %.2f" % (ctrl / len(sample))
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start < len(sample) - 4:
            high = len(sample) - len(sample.translate(None, HIGH_BYTES))
            if high / len(sample) > 0.30:
                return "non-text ratio %.2f" % (high / len(sample))
    return None


def _scan_lines(lines, line_marker, block_open=None, block_close=None, triple=False, backslash=True):
    out = []
    block = None
    lead = {line_marker[0], "'", '"'} | ({block_open[0]} if block_open else set())
    for n, line in enumerate(lines, 1):
        if not block and not any(c in line for c in lead):
            continue
        buf, i, quote, size = [], 0, None, len(line)
        while i < size:
            if block:
                j = line.find(block, i)
                if j < 0:
                    buf.append(line[i:])
                    break
                buf.append(line[i:j])
                i = j + len(block)
                block = None
                continue
            c = line[i]
            if quote:
                if c == "\\" and backslash:
                    i += 2
                    continue
                if c == quote:
                    quote = None
                i += 1
                continue
            if triple and line.startswith(('"""', "'''"), i):
                block = line[i:i + 3]
                i += 3
                continue
            if block_open and line.startswith(block_open, i):
                block = block_close
                i += len(block_open)
                continue
            if line.startswith(line_marker, i):
                buf.append(line[i + len(line_marker):])
                break
            if c in "\"'":
                if not (c == "'" and block_open == "/*" and i and line[i - 1].isdigit()):
                    quote = c
            i += 1
        if buf:
            text = " ".join(buf)
            if text.strip():
                out.append((n, text))
    return out


def comment_lines(path, lines):
    ext = "." + suffix(path) if suffix(path) else ""
    name = path.rsplit("/", 1)[-1].lower()
    if ext in C_LIKE:
        return _scan_lines(lines, "//", "/*", "*/")
    if ext in HASH_LIKE or name in HASH_NAMES:
        return _scan_lines(lines, "#", triple=ext in (".py", ".pyw"), backslash=ext != ".ps1")
    if ext in DASH_LIKE:
        return _scan_lines(lines, "--", "--[[", "]]")
    return [(n, l) for n, l in enumerate(lines, 1) if l.strip()]


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------- rules

def path_rules(path, cfg):
    found = []
    name = path.rsplit("/", 1)[-1]
    ext = "." + suffix(path) if suffix(path) else ""
    if ext in cfg.extensions or any(r.search(name) for r in cfg.name_res):
        found.append(("forbidden-extension", None, "forbidden file type " + (ext or name)))
    elif ext in cfg.generated_ext:
        found.append(("forbidden-extension", None, "generated include " + ext))
    return found


MARKERS = ("//", "#", "--", "/*", "*", ";", "<!--", '"""', "'''")


def generated_header(path, lines, comments, cfg):
    """Header lines among the first N; in source files only the leading comment block counts."""
    code = suffix(path) and ("." + suffix(path)) in C_LIKE | HASH_LIKE | DASH_LIKE
    for n, line in enumerate(lines[:cfg.gen_lines], 1):
        s = line.strip()
        if code and s and not (s.startswith(MARKERS) or s.startswith("#pragma once")
                               or comments.get(n, "").strip() == s):
            break
        if cfg.gen_re.search(line) or cfg.gen_upper_re.search(line):
            return [("generated-header", n, excerpt(line))]
    return []


def disassembly(comments, cfg):
    """Address + mnemonic lines, and runs of operand-shaped listing lines, in comment text."""
    found, offsets, pos = [], [], 0
    for _, t in comments:
        offsets.append(pos)
        pos += len(t) + 1
    ctext = "\n".join(t.replace("\n", " ") for _, t in comments)
    hit = {}
    for m in cfg.addr_re.finditer(ctext):
        i = bisect.bisect_right(offsets, m.start()) - 1
        hit.setdefault(i, None)
    for i in hit:
        found.append(("disassembly", comments[i][0], excerpt(comments[i][1])))
    listing = set()
    for m in cfg.list_re.finditer(ctext):
        ops = m.group("ops")
        if "," in ops and cfg.list_reg_re.search(ops) or cfg.list_6809_re.search(ops):
            listing.add(bisect.bisect_right(offsets, m.start()) - 1)
    for m in cfg.adsp_line_re.finditer(ctext):
        listing.add(bisect.bisect_right(offsets, m.start()) - 1)
    run = []
    for i in sorted(listing) + [None]:
        if i is not None and run and comments[i][0] == comments[run[-1]][0] + 1:
            run.append(i)
            continue
        if len(run) >= cfg.min_listing and any(r not in hit for r in run):
            first = next(r for r in run if r not in hit)
            found.append(("disassembly", comments[first][0],
                          excerpt(comments[first][1]) + " (+%d listing lines)" % (len(run) - 1)))
        run = [i]
    return found


def content_rules(path, data, cfg):
    found = []
    why = is_binary(data, cfg)
    if why:
        found.append(("binary", None, why))
        return found
    text = data.decode("utf-8", errors="replace")
    lines = [l[:-1] if l.endswith("\r") else l for l in text.split("\n")]

    comments = comment_lines(path, lines)
    found.extend(generated_header(path, lines, dict(comments), cfg))
    found.extend(disassembly(comments, cfg))

    if any(rx.match(path) for rx in cfg.pc_scope):
        pcs = {m.group(1).lower() for m in cfg.pc_re.finditer(text)}
        limit = next((mx for rx, mx in cfg.pc_overrides if rx.match(path)), cfg.pc_threshold)
        if len(pcs) > limit:
            found.append(("pc-density", None, "%d distinct code addresses (limit %d)" % (len(pcs), limit)))

    for m in cfg.hex_re.finditer(text):
        found.append(("hex-run", line_of(text, m.start()), "%d contiguous hex digits" % len(m.group(0))))
    for m in cfg.lit_re.finditer(text):
        count = len(re.findall(r"(?i)0x", m.group(0)))
        found.append(("hex-run", line_of(text, m.start()), "%d consecutive 0x literals" % count))
    for m in cfg.b64_re.finditer(text):
        s = m.group(0)
        if re.fullmatch(r"[0-9A-Fa-f=]+", s) or not (re.search(r"[A-Z]", s) and re.search(r"[a-z]", s)
                                                       and re.search(r"\d", s)):
            continue
        found.append(("base64-run", line_of(text, m.start()), "%d base64 characters" % len(s)))

    for n, line in enumerate(lines if cfg.mark_search(text) else (), 1):
        if not cfg.mark_search(line):
            continue
        probe = line
        for rx in cfg.mark_excl:
            probe = rx.sub(lambda m: " " * len(m.group(0)), probe)
        m = cfg.mark_search(probe)
        if m:
            found.append(("mark-term", n, excerpt(line[max(0, m.start() - 30):m.end() + 40])))
    return found


def audit_item(path, data, cfg):
    findings = []
    raw = path_rules(path, cfg) + (content_rules(path, data, cfg) if data is not None else [])
    for rule, line, text in raw:
        if not cfg.allowed(rule, path):
            findings.append({"rule": rule, "path": path, "line": line, "excerpt": text})
    return findings


# ---------------------------------------------------------------- sources

def git(root, *args, data=None):
    try:
        r = subprocess.run(["git", "-C", str(root)] + list(args), input=data, capture_output=True)
    except OSError as e:
        raise AuditError("git not available: %s" % e)
    if r.returncode != 0:
        raise AuditError("git %s failed: %s" % (" ".join(args), r.stderr.decode(errors="replace").strip()))
    return r.stdout


def z_list(raw):
    return [p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p]


def iter_worktree(root, untracked):
    args = ["ls-files", "-z", "--cached"] + (["--others", "--exclude-standard"] if untracked else [])
    for path in sorted(set(z_list(git(root, *args)))):
        full = Path(root) / path
        if full.is_file():
            yield path, full.read_bytes()


def iter_staged(root):
    names = z_list(git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"))
    for path in names:
        mode = git(root, "ls-files", "-s", "-z", "--", path).split(b" ", 1)[0]
        if mode == b"160000":
            continue
        yield path, git(root, "cat-file", "blob", ":" + path)


def cat_batch(root, shas):
    p = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def feed():
        try:
            for s in shas:
                p.stdin.write(s.encode() + b"\n")
        finally:
            p.stdin.close()

    t = threading.Thread(target=feed, daemon=True)
    t.start()
    try:
        for _ in shas:
            header = p.stdout.readline().split()
            if len(header) < 3:
                raise AuditError("git cat-file --batch: bad header %r" % header)
            body = p.stdout.read(int(header[2]))
            p.stdout.read(1)
            yield header[0].decode(), body
    finally:
        t.join()
        p.stdout.close()
        p.wait()


def iter_all_objects(root):
    first = {}
    for line in git(root, "rev-list", "--all", "--objects").decode("utf-8", "surrogateescape").splitlines():
        sha, _, path = line.partition(" ")
        if path and sha not in first:
            first[sha] = path
    shas = list(first)
    kinds = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                data="".join(s + "\n" for s in shas).encode()).decode().split("\n")
    blobs = [k.split()[0] for k in kinds if k.endswith(" blob")]
    for sha, body in cat_batch(root, blobs):
        yield "%s@%s" % (first[sha], sha[:12]), first[sha], body
    # rev-list names each blob once; every other path that ever existed still gets the path rules.
    seen = {first[s] for s in blobs}
    raw = git(root, "log", "--all", "--name-only", "-z", "--format=", "--no-renames")
    for path in sorted(set(z_list(raw)) - seen):
        yield path + "@history", path, None


# ---------------------------------------------------------------- main

def run(root, mode, cfg, untracked=False):
    findings, scanned, mark_paths = [], 0, []
    if mode == "all-objects":
        items = ((label, path, data) for label, path, data in iter_all_objects(root))
    elif mode == "staged":
        items = ((p, p, d) for p, d in iter_staged(root))
    else:
        items = ((p, p, d) for p, d in iter_worktree(root, untracked))
    for label, path, data in items:
        scanned += 1
        for f in audit_item(path, data, cfg):
            f["path"] = label
            findings.append(f)
        if cfg.mark_search(path):
            mark_paths.append(label)
    counts = {}
    for f in findings:
        counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    return {"mode": mode, "files_scanned": scanned, "finding_count": len(findings), "counts": counts,
            "files_with_findings": len({f["path"] for f in findings}), "findings": findings,
            "info": {"paths_with_mark_terms": len(mark_paths), "mark_term_paths": mark_paths}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="scan the staged blobs (pre-commit)")
    g.add_argument("--all-objects", action="store_true", help="scan every blob reachable from any ref")
    ap.add_argument("--include-untracked", action="store_true",
                    help="default mode: also scan untracked, non-ignored files")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    ap.add_argument("--root", default=None, help="repository root (default: git top level of cwd)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="rules and allow-lists (allow.json)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        root = a.root or git(".", "rev-parse", "--show-toplevel").decode().strip()
        cfg = load_config(a.config)
        mode = "staged" if a.staged else "all-objects" if a.all_objects else "worktree"
        report = run(root, mode, cfg, a.include_untracked)
    except (AuditError, OSError, KeyError, ValueError, re.error) as e:
        print("audit: error: %s" % e, file=sys.stderr)
        return 2
    if a.json:
        json.dump(report, sys.stdout, indent=1)
        sys.stdout.write("\n")
    else:
        for f in report["findings"]:
            loc = f["path"] + (":%d" % f["line"] if f["line"] else "")
            print("%s: %s: %s" % (loc, f["rule"], f["excerpt"]))
        summary = ", ".join("%s %d" % kv for kv in sorted(report["counts"].items())) or "none"
        print("audit (%s): %d files scanned, %d findings in %d files (%s)" % (
            report["mode"], report["files_scanned"], report["finding_count"], report["files_with_findings"],
            summary))
        if report["info"]["paths_with_mark_terms"]:
            print("info: %d scanned paths contain mark terms in their names" % report["info"]["paths_with_mark_terms"])
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
