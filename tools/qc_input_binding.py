#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(root, path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def resolve_path(root, raw):
    if raw is None or not str(raw).strip():
        return None
    path = Path(str(raw).strip()).expanduser()
    if path.is_absolute():
        return path
    return Path(root).resolve() / path


def path_record(path):
    if path.is_file():
        return {"kind": "file", "sha256": sha256_file(path)}
    if path.is_dir():
        return {
            "kind": "directory",
            "files": {
                str(child.relative_to(path)): sha256_file(child)
                for child in sorted(path.rglob("*"))
                if child.is_file()
            },
        }
    return {"kind": "missing"}


def build_input_manifest(root, paths):
    root = Path(root).resolve()
    resolved = {
        Path(path).expanduser().resolve()
        for path in paths
        if path is not None and str(path).strip()
    }
    return {
        display_path(root, path): path_record(path)
        for path in sorted(resolved)
    }


def manifest_fingerprint(manifest):
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def attach_input_binding(report, root, paths):
    manifest = build_input_manifest(root, paths)
    report["input_binding"] = {
        "version": 1,
        "manifest": manifest,
        "fingerprint": manifest_fingerprint(manifest),
    }
    return report


def validate_input_binding(root, binding):
    if not isinstance(binding, dict) or binding.get("version") != 1:
        return False, "program QC report has no exact input binding"
    expected = binding.get("manifest")
    if not isinstance(expected, dict) or not expected:
        return False, "program QC input binding is empty"
    if binding.get("fingerprint") != manifest_fingerprint(expected):
        return False, "program QC input binding fingerprint is invalid"
    current = build_input_manifest(
        root,
        [resolve_path(root, raw) for raw in expected],
    )
    if current != expected:
        return False, "program QC input binding does not match current files"
    return True, "program QC input binding matches current files"
