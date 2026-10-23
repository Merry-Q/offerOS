"""Fail closed if Git publication candidates include private data or credentials."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx",
                    ".pdf", ".doc", ".docx", ".csv", ".xlsx"}
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "model API key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
}


def audit_paths(paths: list[str]) -> list[str]:
    findings = []
    for name in paths:
        path = PurePosixPath(name)
        lower = name.lower()
        if (any(part.lower() in {"data", "uploads", ".impeccable", ".railway", "__pycache__"} for part in path.parts)
                or path.suffix.lower() in PRIVATE_SUFFIXES
                or any(marker in lower for marker in (".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm"))
                or (path.name.lower().startswith(".env") and name != ".env.example")
                or lower.endswith(".env")):
            findings.append(f"{name}: private/runtime file")
            continue
        file = ROOT / name
        if not file.is_file():
            continue  # Deleted tracked paths are not published.
        data = file.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                findings.append(f"{name}: possible {label}")
    return findings


def main() -> int:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, check=True, capture_output=True)
    paths = sorted(set(result.stdout.decode("utf-8").strip("\0").split("\0")))
    findings = audit_paths([name for name in paths if name])
    if findings:
        print("Publication blocked (values redacted):\n" + "\n".join(findings))
        return 1
    print(f"Publication audit passed: {len(paths)} Git candidate paths; no private data or credential patterns found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
