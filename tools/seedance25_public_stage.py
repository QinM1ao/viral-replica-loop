#!/usr/bin/env python3
"""Upload local Seedance 2.5 reference media to the configured public staging host."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_SSH_KEY = "Downloads/qm.pem"
DEFAULT_SSH_TARGET = "root@43.167.187.92"
DEFAULT_UPLOAD_DIR = "/opt/dance/backend/uploads"
DEFAULT_PUBLIC_BASE = "https://api.qinmiao.space/uploads"
SUPPORTED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".m4v", ".webm",
}


def validate_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"local media file is missing: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported media suffix {resolved.suffix!r}: {resolved}")
    return resolved


def verify_public_url(url: str) -> dict:
    request = Request(url, headers={"Range": "bytes=0-0", "User-Agent": "ShotLoom/Seedance25"})
    with urlopen(request, timeout=30) as response:
        status = response.status
        payload = response.read(2)
    if status not in {200, 206} or not payload:
        raise ValueError(f"public staging verification failed: HTTP {status}, {url}")
    return {"http_status": status, "first_bytes_received": len(payload)}


def upload_files(
    files: list[Path],
    *,
    ssh_key: Path,
    ssh_target: str,
    upload_dir: str,
    public_base: str,
) -> list[dict]:
    ssh_key = ssh_key.expanduser()
    if not ssh_key.is_absolute():
        ssh_key = Path.home() / ssh_key
    ssh_key = ssh_key.resolve()
    if not ssh_key.is_file():
        raise ValueError(f"public staging SSH key is missing: {ssh_key}")
    asset_dir = f"asset_codex_seedance25_{int(time.time())}_{secrets.token_hex(4)}"
    remote_dir = f"{upload_dir.rstrip('/')}/{asset_dir}"
    ssh_options = [
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "StrictHostKeyChecking=no",
        "-i", str(ssh_key),
    ]
    subprocess.run(
        ["ssh", *ssh_options, ssh_target, "mkdir", "-p", remote_dir],
        check=True,
    )
    results = []
    for index, source in enumerate(files, start=1):
        remote_name = f"{index:02d}_{secrets.token_hex(8)}{source.suffix.lower()}"
        remote_path = f"{remote_dir}/{remote_name}"
        partial_path = f"{remote_path}.part"
        subprocess.run(
            ["scp", "-O", *ssh_options, str(source), f"{ssh_target}:{partial_path}"],
            check=True,
            timeout=300,
        )
        subprocess.run(
            ["ssh", *ssh_options, ssh_target, "mv", partial_path, remote_path],
            check=True,
        )
        url = f"{public_base.rstrip('/')}/{asset_dir}/{remote_name}"
        results.append(
            {
                "file": str(source),
                "url": url,
                "byte_size": source.stat().st_size,
                "verification": verify_public_url(url),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--ssh-key", type=Path, default=Path(os.environ.get("QINMIAO_SSH_KEY", DEFAULT_SSH_KEY)))
    parser.add_argument("--ssh-target", default=os.environ.get("QINMIAO_SSH_TARGET", DEFAULT_SSH_TARGET))
    parser.add_argument("--upload-dir", default=os.environ.get("QINMIAO_UPLOAD_DIR", DEFAULT_UPLOAD_DIR))
    parser.add_argument("--public-base", default=os.environ.get("QINMIAO_PUBLIC_BASE", DEFAULT_PUBLIC_BASE))
    args = parser.parse_args()
    files = [validate_file(path) for path in args.files]
    try:
        items = upload_files(
            files,
            ssh_key=args.ssh_key,
            ssh_target=args.ssh_target,
            upload_dir=args.upload_dir,
            public_base=args.public_base,
        )
    except Exception as exc:
        report = {"overall": "FAIL", "error": str(exc), "items": []}
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(str(exc)) from exc
    report = {"overall": "PASS", "items": items}
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in items:
        print(item["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
