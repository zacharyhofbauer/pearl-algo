#!/usr/bin/env python3
# ============================================================================
# Category: Testing/Validation
# Purpose: Scan tracked files for potential secrets before commit
# Usage: python3 scripts/testing/check_no_secrets.py [--verbose]
# ============================================================================
"""
Secret Detection Guardrail

Scans Git-tracked files for patterns that suggest hardcoded secrets
(API keys, tokens, passwords). Intended to be run pre-commit or in CI.

Exit codes:
    0 - No secrets detected
    1 - Potential secrets found
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Patterns that suggest hardcoded secrets (high confidence)
SECRET_PATTERNS = [
    # Telegram bot tokens: digits:alphanumeric
    (r"\b\d{9,12}:[A-Za-z0-9_-]{35,}\b", "Telegram bot token"),
    # Generic API keys (long alphanumeric strings assigned to key vars)
    (r'(?:api_key|apikey|secret|token|password)\s*[=:]\s*["\']?[A-Za-z0-9_-]{20,}["\']?', "Hardcoded API key/secret"),
    # AWS-style keys
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key ID"),
    # Private keys
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
]

# Files/patterns to skip (already secrets or templates)
SKIP_PATTERNS = [
    r"\.env\.example$",
    r"env\.example$",
    r"\.git/",
    r"__pycache__/",
    r"\.pyc$",
    r"node_modules/",
    r"\.venv/",
]


def get_tracked_files() -> list[str]:
    """Return list of Git-tracked files."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().split("\n")


def should_skip(filepath: str) -> bool:
    """Check if file should be skipped."""
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, filepath):
            return True
    return False


def scan_file(filepath: str, verbose: bool = False) -> list[tuple[int, str, str]]:
    """Scan a single file for secret patterns. Returns list of (line_num, match, pattern_name)."""
    findings = []
    try:
        path = Path(filepath)
        if not path.exists() or path.is_dir():
            return findings
        # Skip binary files
        content = path.read_bytes()
        if b"\x00" in content[:8192]:
            return findings
        text = content.decode("utf-8", errors="ignore")
    except Exception:
        return findings

    for line_num, line in enumerate(text.splitlines(), 1):
        for pattern, name in SECRET_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append((line_num, line.strip()[:80], name))
    return findings


def main():
    parser = argparse.ArgumentParser(description="Scan tracked files for potential secrets")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all scanned files")
    args = parser.parse_args()

    print("Secret Detection Scan")
    print("=" * 60)

    try:
        files = get_tracked_files()
    except subprocess.CalledProcessError:
        print("ERROR: Not in a Git repository or git not available")
        sys.exit(1)

    files_scanned = 0
    all_findings = {}

    for filepath in files:
        if should_skip(filepath):
            if args.verbose:
                print(f"  SKIP: {filepath}")
            continue
        
        findings = scan_file(filepath, args.verbose)
        files_scanned += 1
        
        if findings:
            all_findings[filepath] = findings
        elif args.verbose:
            print(f"  OK: {filepath}")

    print(f"\nScanned {files_scanned} files")
    print()

    if all_findings:
        print("❌ POTENTIAL SECRETS DETECTED:")
        print("-" * 60)
        for filepath, findings in all_findings.items():
            print(f"\n{filepath}:")
            for line_num, snippet, pattern_name in findings:
                print(f"  Line {line_num}: [{pattern_name}]")
                print(f"    {snippet}...")
        print()
        print("=" * 60)
        print("FAILED: Remove or rotate the above secrets before committing.")
        print("If these are false positives, update SKIP_PATTERNS in this script.")
        sys.exit(1)
    else:
        print("✅ No secrets detected in tracked files")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()







