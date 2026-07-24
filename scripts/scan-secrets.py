#!/usr/bin/env python3
"""Fail a release when repository files contain credential-shaped literals."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".cache",
    ".scratch",
    ".venv",
    "deliverables",
    "input",
    "logs",
    "output",
    "__pycache__",
}
MAX_FILE_SIZE = 5 * 1024 * 1024
PLACEHOLDER_MARKERS = (
    "$",
    "${",
    "<",
    "dummy",
    "example",
    "fake",
    "os.environ",
    "replace",
    "test",
    "your_",
)
PATTERNS = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "sk_token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "literal_credential_assignment": re.compile(
        r"""(?ix)
        ["']?
        (?:api[_-]?key|access[_-]?token|client[_-]?secret|secret[_-]?key)
        ["']?
        \s*[:=]\s*
        ["']([^"']{16,})["']
        """
    ),
}


def eligible_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS or part.startswith(".venv-") for part in relative.parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue
        yield path


def is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def scan(root: Path) -> list[tuple[Path, int, str]]:
    findings = []
    for path in eligible_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            matched = False
            for name, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    captured = match.group(1) if match.lastindex else match.group(0)
                    if is_placeholder(captured):
                        continue
                    findings.append((path.relative_to(root), line_number, name))
                    matched = True
                    break
                if matched:
                    break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    findings = scan(root)
    if findings:
        print("Secret scan failed; credential-shaped literals found:")
        for path, line_number, name in findings:
            print(f"- {path}:{line_number} ({name})")
        return 1
    print("Secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
