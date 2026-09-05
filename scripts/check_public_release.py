#!/usr/bin/env python3
"""Fail on common accidental secrets/private data in distributable source."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "venv", "__pycache__", ".ruff_cache", ".pytest_cache", "artifacts", "dist"}
PATTERNS = (
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"/" r"Users/(?!private/|example/)[^/'\"\s]+/"),
    re.compile(r"/" r"home/(?!example/|runner/)[^/'\"\s]+/"),
)
PRIVATE_SUFFIXES = {".qgs", ".qgz", ".gpkg", ".sqlite", ".db", ".pem", ".key"}


def check(root=ROOT):
    problems = []
    count = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if set(relative.parts) & EXCLUDED or not path.is_file():
            continue
        count += 1
        if path.is_symlink() or path.suffix in PRIVATE_SUFFIXES or path.name.startswith(".env"):
            problems.append(f"{relative}: private file type or symlink")
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            if relative.parts[:2] != ("docs", "images"):
                problems.append(f"{relative}: unreviewed image location")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            problems.append(f"{relative}: unapproved binary file")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                problems.append(f"{relative}:{number}: possible sensitive content (value withheld)")
    return count, problems


if __name__ == "__main__":
    count, problems = check()
    print("\n".join(problems) if problems else f"Public-source audit passed: {count} files")
    raise SystemExit(bool(problems))
