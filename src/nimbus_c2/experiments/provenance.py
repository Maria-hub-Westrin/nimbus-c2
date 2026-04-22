# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Provenance helpers: git metadata and Python version capture.

These functions produce the metadata that accompanies every experiment result.
Without them, a JSON result file is detached from the code that produced it.
With them, a reviewer can clone the exact commit and rerun.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass


@dataclass(frozen=True)
class GitStatus:
    """Git repository state at experiment time.

    Attributes
    ----------
    sha : str
        Full 40-character commit SHA, or 'unknown' if git lookup failed.
    short_sha : str
        First 7 characters of sha. Used in filenames.
    is_dirty : bool
        True if the working tree has uncommitted changes. A True value means
        the result cannot be reproduced from git alone — it also depends on
        uncommitted edits. This should be treated as a warning.
    branch : str
        Current branch name, or 'detached' if HEAD is detached.
    """

    sha: str
    short_sha: str
    is_dirty: bool
    branch: str


def git_sha_with_status(warn_on_dirty: bool = True) -> GitStatus:
    """Detect the current git commit and working-tree status.

    If git is not available or the current directory is not a git repository,
    returns a GitStatus with sha='unknown' and logs a warning.

    Parameters
    ----------
    warn_on_dirty : bool
        If True (default), emit a UserWarning when the working tree has
        uncommitted changes. This flags results that are not strictly
        reproducible from a git commit alone.
    """
    if shutil.which("git") is None:
        warnings.warn(
            "git executable not found; provenance tracking degraded",
            UserWarning,
            stacklevel=2,
        )
        return GitStatus(
            sha="unknown", short_sha="unknown", is_dirty=False, branch="unknown"
        )

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        dirty_output = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        is_dirty = bool(dirty_output)

        # Branch name (or 'HEAD' if detached)
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if branch == "HEAD":
            branch = "detached"

        if is_dirty and warn_on_dirty:
            warnings.warn(
                f"Git working tree is dirty at SHA {sha[:7]}. Results may "
                f"not be reproducible from this commit alone. Commit your "
                f"changes before running authoritative experiments.",
                UserWarning,
                stacklevel=2,
            )

        return GitStatus(
            sha=sha, short_sha=sha[:7], is_dirty=is_dirty, branch=branch
        )

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        warnings.warn(
            f"git lookup failed ({e}); provenance tracking degraded",
            UserWarning,
            stacklevel=2,
        )
        return GitStatus(
            sha="unknown", short_sha="unknown", is_dirty=False, branch="unknown"
        )


def python_version() -> str:
    """Return the full Python version string.

    Format: 'Python 3.12.10 (default, ...)'. Used in provenance records to
    flag cases where two Python versions might produce different results
    for the same code.
    """
    return f"Python {sys.version.split()[0]}"
