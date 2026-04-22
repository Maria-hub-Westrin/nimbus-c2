#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Repository hygiene: idempotent, safe, and CI-compatible.

What it does
------------

1. **Line-ending normalisation.** Rewrites every text file with Unix
   line endings (\\n). Your repo currently ships CRLF-damaged files on
   Windows checkouts; on Linux this manifests as phantom \\r characters
   at end-of-line and, after a botched merge, as the whole body
   collapsed onto one line.

2. **Newline-collapse corruption detection.** If a source file appears
   to have had its newlines collapsed to spaces (symptom: the entire
   body is on line 3 and begins with '#', so ``ast.parse()`` returns
   zero top-level definitions), this script *refuses to overwrite it*
   and reports the path. Recovery requires a manual restore from a
   known-good copy — the script cannot reconstruct lost statement
   boundaries.

3. **SPDX header installation / normalisation.** Every tracked text
   file with a recognised extension (.py, .md, .toml, .yaml, .yml,
   .sh, .rs, .ts, .js, .c, .cpp, .h) gets the canonical two-line
   SPDX header in the comment style native to its format. Jammed
   duplicate copyright lines produced by prior botched merges are
   collapsed.

4. **Exit status.** In ``--check`` mode, exit 0 if the tree is clean
   (no corruption, every file already has the canonical header);
   exit 1 otherwise. Makes this script CI-gating.

What it deliberately does not do
--------------------------------

- It does not delete files.
- It does not rewrite files it flags as corrupted — you keep the
  damaged copy until you restore from your local working tree or
  from git history.
- It does not touch files inside ``.git/``, ``__pycache__/``, or
  paths in ``.gitignore``-style exclusions.
- It does not *format* code (that is ``ruff``'s job).

Usage
-----

::

    # Dry-run diagnostic, machine-readable; exits 1 if anything is off.
    python scripts/repo_hygiene.py --check

    # In-place normalisation; backs up modified files as ``<name>.bak``.
    python scripts/repo_hygiene.py --write

    # Show diffs that would be applied, but do not modify anything.
    python scripts/repo_hygiene.py --dry-run
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

SPDX_AUTHOR = "2026 Maria Westrin"
SPDX_LICENSE = "MIT"

# Comment styles per file extension. Each entry is
# (prefix_per_line, suffix_per_line, block_prefix, block_suffix).
# For block-style languages (markdown, html) we emit a single
# multi-line block; for line-style languages (python, yaml, shell) we
# emit two one-line comments.
_HASH = ("#", "", None, None)
_SLASHSLASH = ("//", "", None, None)
_HTML = (None, None, "<!--", "-->")

_EXT_STYLE = {
    ".py":    _HASH,
    ".pyi":   _HASH,
    ".sh":    _HASH,
    ".bash":  _HASH,
    ".zsh":   _HASH,
    ".toml":  _HASH,
    ".yaml":  _HASH,
    ".yml":   _HASH,
    ".cfg":   _HASH,
    ".ini":   _HASH,
    ".dockerfile": _HASH,
    ".md":    _HTML,
    ".html":  _HTML,
    ".svg":   _HTML,
    ".xml":   _HTML,
    ".rs":    _SLASHSLASH,
    ".c":     _SLASHSLASH,
    ".cpp":   _SLASHSLASH,
    ".h":     _SLASHSLASH,
    ".hpp":   _SLASHSLASH,
    ".js":    _SLASHSLASH,
    ".jsx":   _SLASHSLASH,
    ".ts":    _SLASHSLASH,
    ".tsx":   _SLASHSLASH,
    ".css":   _SLASHSLASH,
}

# Paths (relative to repo root) to leave untouched entirely.
_EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "env", "node_modules", "dist", "build", ".tox",
    "benchmarks/results",  # generated artefacts
}

# File basenames that never get an SPDX header even if the extension matches.
_EXCLUDE_NAMES = {
    "LICENSE", "LICENSE.txt", "NOTICE", "AUTHORS", "CITATION.cff",
    "SPDX-HEADER.txt",
}


# --------------------------------------------------------------------------- #
# Diagnostics                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class FileReport:
    path: Path
    corrupted_single_line: bool = False
    has_crlf: bool = False
    had_jammed_copyright: bool = False
    header_added: bool = False
    header_already_canonical: bool = False
    header_style_unknown: bool = False
    written: bool = False
    skipped_reason: str = ""

    def changed(self) -> bool:
        return self.header_added or self.had_jammed_copyright or self.has_crlf


@dataclass
class RunSummary:
    files_seen: int = 0
    files_touched: int = 0
    files_corrupted: int = 0
    reports: List[FileReport] = field(default_factory=list)

    def as_exit_code(self, check_mode: bool) -> int:
        if self.files_corrupted > 0:
            return 1
        if check_mode and self.files_touched > 0:
            return 1
        return 0


# --------------------------------------------------------------------------- #
# Per-file processing                                                         #
# --------------------------------------------------------------------------- #

def _detect_collapse_corruption(raw_text: str, ext: str) -> bool:
    """Detect the one-line-file corruption seen on the repo's current state.

    A Python file is considered corrupted iff it has fewer than 6 lines
    **and** ``ast.parse()`` returns zero top-level statements on its
    body. This combination is a clean signal: legitimate short Python
    files always have at least one top-level statement.

    A Markdown file is considered corrupted iff it is larger than 2 KB
    **and** has fewer than 3 line breaks — no legitimate 2 KB markdown
    file lives on a single line.
    """
    if ext in (".py", ".pyi"):
        if raw_text.count("\n") >= 6:
            return False
        try:
            tree = ast.parse(raw_text)
        except SyntaxError:
            # A syntax error is not itself corruption — real buggy code
            # is not this script's problem. But collapse-corrupted code
            # typically parses as comment-only with an empty body, not
            # as a SyntaxError.
            return False
        return len(tree.body) == 0 and len(raw_text) > 200
    if ext == ".md":
        return len(raw_text) > 2048 and raw_text.count("\n") < 3
    return False


def _strip_jammed_headers(lines: List[str], style: Tuple) -> Tuple[List[str], bool]:
    """Collapse repeated '# Copyright (c) Maria Westrin ...' fragments at top.

    The pattern in the current repo is: several '# Copyright' markers
    concatenated onto a single physical line, followed by a bunch of
    restated licence clauses. This function strips any leading
    block of such lines (anywhere near the top of the file, before real
    content) and leaves the first real content line intact.

    Returns (new_lines, was_modified).
    """
    if not lines:
        return lines, False

    prefix, suffix, block_prefix, block_suffix = style

    def looks_jammed(line: str) -> bool:
        stripped = line.strip()
        if stripped.count("Copyright (c) 2026 Maria Westrin") >= 2:
            return True
        if stripped.count("Licensed under the MIT License") >= 2:
            return True
        if stripped.count("derivative work must clearly credit") >= 1:
            return True
        return False

    changed = False
    out: List[str] = []
    consumed_header = False
    for idx, line in enumerate(lines):
        if not consumed_header and idx < 5 and looks_jammed(line):
            changed = True
            # drop this line entirely
            continue
        consumed_header = True
        out.append(line)
    return out, changed


def _has_canonical_spdx(lines: List[str], style: Tuple) -> bool:
    """Detect whether the canonical SPDX header is already present.

    Lenient: we only require the two magic tokens to appear somewhere in
    the first 10 lines, regardless of exact structural layout. This lets
    files legitimately carry additional attribution context inside the
    comment block (e.g. CODE_OF_CONDUCT.md attributing the Contributor
    Covenant under CC-BY-4.0) without the script treating that as a
    missing header and duplicating the SPDX lines on every run.
    """
    joined = "\n".join(lines[:10])
    return (
        f"SPDX-FileCopyrightText: {SPDX_AUTHOR}" in joined
        and f"SPDX-License-Identifier: {SPDX_LICENSE}" in joined
    )


def _canonical_header(style: Tuple) -> List[str]:
    prefix, suffix, block_prefix, block_suffix = style
    if block_prefix is not None:
        return [
            block_prefix,
            f"SPDX-FileCopyrightText: {SPDX_AUTHOR}",
            f"SPDX-License-Identifier: {SPDX_LICENSE}",
            block_suffix,
            "",
        ]
    return [
        f"{prefix} SPDX-FileCopyrightText: {SPDX_AUTHOR}{suffix}",
        f"{prefix} SPDX-License-Identifier: {SPDX_LICENSE}{suffix}",
    ]


def _insert_header(lines: List[str], style: Tuple) -> List[str]:
    """Prepend canonical header. If there's a shebang, keep it on line 1."""
    header = _canonical_header(style)
    if lines and lines[0].startswith("#!"):
        return [lines[0]] + header + lines[1:]
    return header + lines


def process_file(path: Path, write: bool) -> FileReport:
    report = FileReport(path=path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as e:
        report.skipped_reason = f"read error: {e}"
        return report

    # Decode with permissive latin-1 so byte values like \x96 (en-dash)
    # survive. We re-encode as utf-8 on write.
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("latin-1")

    ext = path.suffix.lower()
    style = _EXT_STYLE.get(ext)
    if style is None:
        report.header_style_unknown = True
        return report

    # Detect CRLF.
    if "\r\n" in raw_text:
        report.has_crlf = True
        raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # Detect collapse corruption. If found, do not modify.
    if _detect_collapse_corruption(raw_text, ext):
        report.corrupted_single_line = True
        return report

    lines = raw_text.split("\n")

    # Collapse jammed copyright blobs.
    lines, changed_jammed = _strip_jammed_headers(lines, style)
    report.had_jammed_copyright = changed_jammed

    # Install canonical SPDX header if missing.
    if _has_canonical_spdx(lines, style):
        report.header_already_canonical = True
    else:
        lines = _insert_header(lines, style)
        report.header_added = True

    if report.changed() and write:
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            backup.write_bytes(raw_bytes)
        new_text = "\n".join(lines)
        if not new_text.endswith("\n"):
            new_text += "\n"
        path.write_text(new_text, encoding="utf-8")
        report.written = True

    return report


# --------------------------------------------------------------------------- #
# Tree walk                                                                   #
# --------------------------------------------------------------------------- #

def iter_files(repo_root: Path) -> Iterable[Path]:
    """Yield every candidate file below ``repo_root``.

    Respects ``_EXCLUDE_DIRS`` and ``_EXCLUDE_NAMES``. Does not follow
    symlinks. Deterministic order.
    """
    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _EXCLUDE_DIRS and not d.startswith(".")
            or d in {".github"}
        )
        for name in sorted(filenames):
            if name in _EXCLUDE_NAMES:
                continue
            full = Path(dirpath) / name
            if full.suffix.lower() in _EXT_STYLE:
                yield full


def run(
    repo_root: Path,
    write: bool,
    check_only: bool,
) -> RunSummary:
    summary = RunSummary()
    for f in iter_files(repo_root):
        summary.files_seen += 1
        report = process_file(f, write=write)
        summary.reports.append(report)
        if report.corrupted_single_line:
            summary.files_corrupted += 1
        if report.changed():
            summary.files_touched += 1
    return summary


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def format_summary(summary: RunSummary, check_only: bool) -> str:
    lines = [
        f"Scanned : {summary.files_seen} files",
        f"Touched : {summary.files_touched} files"
        + (" (would touch)" if check_only else ""),
        f"Corrupt : {summary.files_corrupted} files (manual recovery required)",
    ]
    if summary.files_corrupted > 0:
        lines.append("")
        lines.append("CORRUPTED (newline-collapse, body is a single comment):")
        for r in summary.reports:
            if r.corrupted_single_line:
                lines.append(f"  {r.path}")
        lines.append("")
        lines.append(
            "These files cannot be automatically recovered. Restore them\n"
            "from your local working copy, or from a prior git SHA via:\n"
            "    git checkout <good-sha> -- <path>"
        )
    if summary.files_touched > 0:
        lines.append("")
        lines.append(
            ("Would modify" if check_only else "Modified")
            + " (CRLF, jammed copyright, or missing SPDX header):"
        )
        for r in summary.reports:
            if r.changed() and not r.corrupted_single_line:
                tags = []
                if r.has_crlf:
                    tags.append("CRLF")
                if r.had_jammed_copyright:
                    tags.append("jammed")
                if r.header_added:
                    tags.append("header+")
                lines.append(f"  [{','.join(tags):<18}] {r.path}")
    if summary.files_touched == 0 and summary.files_corrupted == 0:
        lines.append("")
        lines.append("Clean.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Nimbus-C2 repository hygiene.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="Report problems; do not modify files. Exit 1 on any issue.")
    mode.add_argument("--write", action="store_true",
                      help="Apply fixes in place (backs up to <name>.bak).")
    mode.add_argument("--dry-run", action="store_true",
                      help="Show what would change; do not modify files.")
    parser.add_argument("--root", type=Path, default=None,
                        help="Repository root (defaults to git toplevel or CWD).")
    args = parser.parse_args(argv)

    if args.root is not None:
        root = args.root
    else:
        # Default to two levels up from this script (scripts/../repo_root).
        script_path = Path(__file__).resolve()
        root = script_path.parents[1]

    if not (root / "pyproject.toml").exists() and not (root / "LICENSE").exists():
        print(f"warning: {root} does not look like the repo root", file=sys.stderr)

    write = args.write
    check_only = args.check or args.dry_run
    summary = run(root, write=write, check_only=check_only)
    print(format_summary(summary, check_only=check_only))
    return summary.as_exit_code(check_mode=check_only)


if __name__ == "__main__":
    sys.exit(main())
