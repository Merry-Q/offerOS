"""Start one web process using the hosting platform's port and durable volume."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def server_command(environ: dict) -> list[str]:
    port = int(environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0",
            "--port", str(port), "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]


def prepare_data_dir(environ: dict) -> None:
    path = Path(environ.get("OFFEROS_DATA_DIR", "/var/lib/offeros"))
    path.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        # Railway mounts volumes as root. Change only the volume root, then drop
        # privileges before importing the application or reading runtime secrets.
        os.chown(path, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    if not os.access(path, os.W_OK):
        raise RuntimeError("The application data directory is not writable")


def main() -> None:
    command = server_command(os.environ)
    prepare_data_dir(os.environ)
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
