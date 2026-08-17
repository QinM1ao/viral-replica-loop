#!/usr/bin/env python3
"""Install one private ShotLoom package into a local Codex marketplace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_NAME = "shotloom"
DEFAULT_MARKETPLACE_NAME = "personal"


class InstallStop(RuntimeError):
    pass


def _stable_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _marketplace_entry() -> dict[str, Any]:
    return {
        "name": PACKAGE_NAME,
        "source": {
            "source": "local",
            "path": f"./plugins/{PACKAGE_NAME}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def _load_marketplace(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return (
            {
                "name": DEFAULT_MARKETPLACE_NAME,
                "interface": {"displayName": "Personal"},
                "plugins": [],
            },
            True,
        )
    if not path.is_file() or path.is_symlink():
        raise InstallStop(f"marketplace path is not one real file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise InstallStop(f"marketplace is unreadable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise InstallStop("marketplace root must be an object")
    name = payload.get("name")
    plugins = payload.get("plugins")
    if not isinstance(name, str) or not name.strip():
        raise InstallStop("marketplace name must be a non-empty string")
    if not isinstance(plugins, list):
        raise InstallStop("marketplace plugins must be a list")
    if any(
        not isinstance(plugin, dict)
        or not isinstance(plugin.get("name"), str)
        for plugin in plugins
    ):
        raise InstallStop("marketplace contains an invalid plugin entry")
    if any(plugin["name"] == PACKAGE_NAME for plugin in plugins):
        raise InstallStop(
            f"{PACKAGE_NAME} already exists in {path}; "
            "upgrade is outside this MVP"
        )
    return payload, False


def _marketplace_product_root(path: Path) -> Path:
    path = path.expanduser().resolve()
    if tuple(path.parts[-3:]) != (
        ".agents",
        "plugins",
        "marketplace.json",
    ):
        raise InstallStop(
            "marketplace path must end with "
            ".agents/plugins/marketplace.json"
        )
    return path.parents[2]


def _run_codex(command: list[str], *, codex_bin: Path) -> str:
    result = subprocess.run(
        [str(codex_bin), *command],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InstallStop(
            f"Codex command failed: {' '.join(command)}: {detail}"
        )
    return result.stdout


def install(
    *,
    package_root: Path,
    marketplace_path: Path,
    codex_bin: Path,
) -> Path:
    package_root = package_root.resolve()
    marketplace_path = marketplace_path.expanduser().resolve()
    codex_bin = codex_bin.expanduser().resolve()
    if not codex_bin.is_file() or not os.access(codex_bin, os.X_OK):
        raise InstallStop(
            f"Codex CLI is unavailable or not executable: {codex_bin}; "
            "install a Supported Host Codex release and retry"
        )
    manifest_path = package_root / ".codex-plugin" / "plugin.json"
    if not manifest_path.is_file():
        raise InstallStop(f"missing package manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise InstallStop(f"package manifest is unreadable: {manifest_path}") from exc
    if manifest.get("name") != PACKAGE_NAME:
        raise InstallStop(f"package manifest name must be {PACKAGE_NAME}")
    validator = package_root / "scripts" / "validate-package.py"
    if not validator.is_file():
        raise InstallStop(f"missing package validator: {validator}")
    validation = subprocess.run(
        [str(validator), str(package_root)],
        text=True,
        capture_output=True,
    )
    if validation.returncode != 0:
        raise InstallStop(
            "package validation failed: "
            + (validation.stderr or validation.stdout).strip()
        )

    marketplace, is_new_marketplace = _load_marketplace(marketplace_path)
    marketplace_name = marketplace["name"]
    product_root = _marketplace_product_root(marketplace_path)
    install_root = product_root / "plugins"
    managed_copy = install_root / PACKAGE_NAME
    if managed_copy.exists():
        raise InstallStop(
            f"managed plugin copy already exists: {managed_copy}; "
            "upgrade is outside this MVP"
        )
    package_inside_install_root = False
    install_root_inside_package = False
    try:
        package_root.relative_to(install_root)
        package_inside_install_root = True
    except ValueError:
        pass
    try:
        install_root.relative_to(package_root)
        install_root_inside_package = True
    except ValueError:
        pass
    if package_inside_install_root or install_root_inside_package:
        raise InstallStop(
            "source package overlaps the managed plugin directory; "
            "install from a separate package directory"
        )

    marketplace["plugins"].append(_marketplace_entry())
    install_root.mkdir(parents=True, exist_ok=True)
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".shotloom-install-", dir=install_root)
    )
    staging_copy = staging_parent / PACKAGE_NAME
    marketplace_staging = marketplace_path.with_name(
        f".{marketplace_path.name}.shotloom-install"
    )
    try:
        shutil.copytree(package_root, staging_copy, symlinks=False)
        marketplace_staging.write_bytes(_stable_json_bytes(marketplace))
        os.replace(staging_copy, managed_copy)
        os.replace(marketplace_staging, marketplace_path)
    except Exception:
        if managed_copy.exists():
            shutil.rmtree(managed_copy)
        if marketplace_staging.exists():
            marketplace_staging.unlink()
        raise
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent)

    default_marketplace = (
        Path.home() / ".agents" / "plugins" / "marketplace.json"
    ).resolve()
    if is_new_marketplace and marketplace_path != default_marketplace:
        _run_codex(
            ["plugin", "marketplace", "add", str(product_root)],
            codex_bin=codex_bin,
        )
    _run_codex(
        ["plugin", "add", f"{PACKAGE_NAME}@{marketplace_name}"],
        codex_bin=codex_bin,
    )
    discovered = _run_codex(["plugin", "list"], codex_bin=codex_bin)
    if PACKAGE_NAME not in discovered or "installed" not in discovered:
        raise InstallStop(
            "Codex did not report shotloom as installed; "
            "inspect `codex plugin list` and retry from the package"
        )
    return managed_copy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True)
    parser.add_argument(
        "--marketplace-path",
        default=str(
            Path.home() / ".agents" / "plugins" / "marketplace.json"
        ),
    )
    parser.add_argument("--codex-bin", default="codex")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    codex_raw = Path(args.codex_bin).expanduser()
    codex_path = (
        Path(shutil.which(str(codex_raw)) or str(codex_raw))
        if codex_raw.parent == Path(".")
        else codex_raw
    )
    try:
        managed_copy = install(
            package_root=Path(args.package_root),
            marketplace_path=Path(args.marketplace_path),
            codex_bin=codex_path,
        )
    except (InstallStop, OSError, ValueError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    print(f"PASS installed {PACKAGE_NAME}: {managed_copy}")
    print(f"PASS Codex discovered {PACKAGE_NAME}")
    print("Start a new Codex task before invoking the installed Skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
