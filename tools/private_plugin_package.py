#!/usr/bin/env python3
"""Build and validate the canonical private ShotLoom plugin package."""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from product_fixture_suite import FixtureValidationError, validate_fixture_suite


PACKAGE_NAME = "shotloom"
MARKETPLACE_NAME = "personal"
MARKETPLACE_DISPLAY_NAME = "Personal"
RELEASE_KEY_ID = "shotloom-rsa-sha256"

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".csv",
    ".command",
}

EXCLUDED_SOURCE_FILES = {
    Path("tests/test_canonical_plugin_job.py"),
    Path("tests/test_pre_seedance_parity.py"),
    Path("tests/test_private_plugin_package.py"),
    Path("tests/test_thin_plugin_smoke.py"),
    Path("tools/pre_seedance_parity.py"),
    Path("tools/private_plugin_package.py"),
}

FORBIDDEN_PATH_PATTERNS = (
    "output/**",
    "workspace-dev/**",
    ".sandcastle/**",
    ".pytest_cache/**",
    "__pycache__/**",
    ".mypy_cache/**",
    ".cache/**",
    ".venv*/**",
    "node_modules/**",
    "**/*.pyc",
    "**/.DS_Store",
    ".viral-replica/runtime/**",
    "**/output/**",
    "**/evidence/**",
    "**/jobs/job-*/**",
    "deliveries/**",
    "engine/output/**",
    "engine/evidence/**",
    "engine/deliveries/**",
    "engine/BRIEF.md",
    "engine/STATE.md",
    "engine/jobs.csv",
    "engine/RUNNER_STATE.json",
)

TEXT_REPLACEMENTS = (
    (
        "/Users/qmio/.codex/skills/source-faithful-captions/SKILL.md",
        "$source-faithful-captions (optional external post-production skill; not bundled in the first-release package)",
    ),
    (
        "/Users/qmio/.codex/skills/seedance/scripts/seedance.py",
        "<client-owned-seedance-route>",
    ),
    (
        "/Users/qmio/.codex/skills/seedance/config/default.json",
        "<client-owned-seedance-config>",
    ),
    (
        "/Users/qmio/.codex/skills/seedance-magic-mirror-video-prompt/scripts/run_seedance_magic_mirror.py",
        "<legacy-seedance-prompt-experiment>",
    ),
    (
        "/Users/qmio/.codex/skills/seedance/scripts/seedance_ai_router.py",
        "<client-owned-seedance-ai-router>",
    ),
    (
        "/Users/qmio/Documents/助理/viral-replica-loop",
        "<managed-plugin-copy>",
    ),
    ("~/.codex/skills/", "<global-skill-path-removed>/"),
)

FORBIDDEN_CONTENT_PATTERNS = {
    "maintainer_absolute_path": re.compile(r"(/Users/[^/\s]+/|/home/[^/\s]+/)"),
    "signed_url": re.compile(
        r"([?&](?:X-Amz-Signature|X-Goog-Signature|Signature|sig)=)",
        re.IGNORECASE,
    ),
    "global_skill_dependency": re.compile(
        r"(~?/\.codex/skills/|~?\.codex/skills/)",
        re.IGNORECASE,
    ),
    "credential_value": re.compile(
        r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|Authorization:\s*Bearer\s+[A-Za-z0-9._~+/-]{16,}"
        r"|\bAKIA[0-9A-Z]{16}\b"
        r"|\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{16,}['\"]"
        r"|^\s*(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*=\s*[A-Za-z0-9_./+=-]{16,}\s*$)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

FORBIDDEN_FILENAMES = {
    ".env",
    "auth.json",
    "credentials.json",
    "service-account.json",
}

KNOWN_FIXTURE_ORIGINS = {
    "assets/fixtures/fixture_origin.json",
    "assets/fixtures/v1/fixture_origin.json",
}

TIMING_FIXTURE_ORIGIN_FIELDS = {
    "fixture_id",
    "packaged_path",
    "source",
    "license_or_authorization",
    "non_client",
    "content_summary",
    "expected_logical_roles",
    "sha256",
    "creation_tool",
    "redistribution_rights",
}

FIXTURE_MEDIA_SUFFIXES = (
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".mkv",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".svg",
    ".y4m",
    ".pcm",
    ".pcm_u8",
)

COPY_ROOTS = (
    Path("AGENTS.md"),
    Path("CONTEXT.md"),
    Path("COST_POLICY.md"),
    Path("LOOP.md"),
    Path("PRODUCT_CONSTRAINTS.md"),
    Path("QC_RULES.md"),
    Path("README.md"),
    Path("LICENSE"),
    Path("requirements.txt"),
    Path("BRIEF.example.md"),
    Path("STATE.example.md"),
    Path("jobs.example.csv"),
    Path("install.sh"),
    Path("run-loop.sh"),
    Path("reset-loop.sh"),
    Path("migration"),
    Path("docs"),
    Path("rules"),
    Path("gates"),
    Path("workers"),
    Path("scripts"),
    Path("tools"),
    Path("tests"),
    Path(".agents/skills/viral-replica"),
    Path(".agents/skills/video-replication"),
    Path(".agents/skills/minimax-h3-replica"),
    Path(".agents/skills/seedance-25-replica"),
    Path(".agents/skills/video-shot-refinement"),
    Path(".agents/skills/video-subtitle-removal"),
)


class PackageBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    package_root: Path
    archive_path: Path
    archive_sha256: str
    content_manifest_path: Path
    content_manifest_sha256: str
    release_manifest_path: Path
    release_identity: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_source_files(source_root: Path) -> list[Path]:
    selected: list[Path] = []
    for entry in COPY_ROOTS:
        source = source_root / entry
        if source.is_file():
            selected.append(source)
            continue
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise PackageBuildError(
                        f"source allowlist contains a symbolic link: "
                        f"{path.relative_to(source_root)}"
                    )
                if not path.is_file():
                    continue
                rel = path.relative_to(source_root)
                if rel in EXCLUDED_SOURCE_FILES:
                    continue
                if any(part == "__pycache__" for part in rel.parts):
                    continue
                if path.suffix == ".pyc":
                    continue
                selected.append(path)
    return sorted(set(selected))


def transform_text(text: str) -> str:
    updated = text
    for old, new in TEXT_REPLACEMENTS:
        updated = updated.replace(old, new)
    updated = re.sub(
        r"/Users/[^/\s]+/\.codex/skills/",
        "<external-skill-root>/",
        updated,
    )
    updated = re.sub(r"/Users/[^/\s]+/", "<maintainer-home>/", updated)
    return updated


def copy_engine(source_root: Path, package_root: Path) -> None:
    for source in iter_source_files(source_root):
        rel = source.relative_to(source_root)
        target = package_root / "engine" / rel
        ensure_parent(target)
        if is_text_file(source):
            text = source.read_text(encoding="utf-8")
            target.write_text(transform_text(text), encoding="utf-8")
        else:
            shutil.copy2(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))


def write_private_smoke_engine(
    source_root: Path,
    package_root: Path,
) -> None:
    source = source_root / "tools" / "pre_seedance_parity.py"
    target = (
        package_root
        / "engine"
        / "smoke"
        / "pre_seedance_no_spend.py"
    )
    write_text(
        target,
        transform_text(source.read_text(encoding="utf-8")),
    )


def write_json(path: Path, payload: object, mode: int = 0o644) -> None:
    ensure_parent(path)
    path.write_bytes(stable_json_bytes(payload))
    path.chmod(mode)


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    ensure_parent(path)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    path.chmod(mode)


def plugin_manifest(version: str) -> dict[str, object]:
    return {
        "name": PACKAGE_NAME,
        "version": version,
        "description": "Private ShotLoom plugin package for source-locked video replication.",
        "author": {"name": "ShotLoom"},
        "license": "Proprietary",
        "keywords": ["video-replication", "minimax-h3", "seedance", "plugin"],
        "skills": "./skills/",
        "interface": {
            "displayName": "ShotLoom",
            "shortDescription": "Full-flow source-locked video replication",
            "longDescription": "Private ShotLoom plugin for source-locked video replication, shot refinement, and subtitle repair.",
            "developerName": "ShotLoom",
            "category": "Productivity",
            "capabilities": ["Interactive", "Write"],
            "defaultPrompt": [
                "Replicate this source video with my product and assets.",
                "Generate the current ShotLoom Job with the ordinary Seedance 2.0 API.",
                "Replicate this source video directly with MiniMax H3.",
                "Replicate and generate this video with the verified Seedance 2.5 API route.",
                "Refine one failed shot in the current delivery.",
                "Remove burned-in subtitles from the finished master.",
            ],
            "brandColor": "#14532D",
        },
    }


def marketplace_manifest() -> dict[str, object]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": MARKETPLACE_DISPLAY_NAME},
        "plugins": [
            {
                "name": PACKAGE_NAME,
                "source": {"source": "local", "path": f"./plugins/{PACKAGE_NAME}"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def write_public_wrappers(package_root: Path) -> None:
    wrappers = {
        "viral-replica": """---
name: viral-replica
description: Full-flow source-locked viral video replication, including ordinary Seedance 2.0 API generation when the user explicitly requests it.
---

# Viral Replica

For a new full-flow Job, collect the user's simple Intake paths and one explicit Workspace, then
resolve the launcher from this Skill file's directory, never from the current working directory.

Launcher path (relative to this Skill): `../../scripts/run-canonical-job.py`

```bash
SKILL_DIR="$(cd "$(dirname "<absolute-path-to-this-SKILL.md>")" && pwd)"
python3 "$SKILL_DIR/../../scripts/run-canonical-job.py" \
  --workspace "<explicit-workspace>" \
  --prepare-runtime

python3 "$SKILL_DIR/../../scripts/run-canonical-job.py" \
  --workspace "<explicit-workspace>" \
  --video "<source-video>" \
  --product-name "<product-name>" \
  --product-assets "<product-assets>" \
  --person-assets "<person-assets-or-storyboard_derived>" \
  --audio-assets "<audio-path-or-extract_from_original>" \
  --notes "<user-notes>"
```

The first command is idempotent: on first use it checks production ElevenLabs ASR credentials;
no local ASR model is downloaded or prepared. Omit `--target-duration`
unless the user explicitly requested one. The launcher probes the real
source duration, binds Plugin Root, Workspace Root, workflow contract, and current Job once, and
prints the first `看懂原片` runner/gate decision with inspection paths. Never replace the explicit
Workspace with cwd, a sibling checkout, a global Skill root, or another fallback.

When that decision selects `source_blueprint`, finish the whole selected worker and gate in the
same run. The preparation report is an internal checkpoint, not a completion or handoff: continue
through Source Rhythm authorship, rhythm QC, one all-beat visual review, rhythm-aware source
storyboards, and the existing gate without asking the user to confirm. Do not start image or video
generation until the gate records `PASS` and the lifecycle advances to `storyboard_passed`.

For a bounded prompt correction on an existing Pre-Seedance handoff, do not start or resume the
full loop. Resolve `../../engine/tools/pre_seedance_pack.py` from this Skill and run its
`prompt-only` command with the canonical `jobs/<job-id>/work` path, one Part, one execution block,
and the replacement visual text. This route must not run media tools, providers, or full QC.

If the user explicitly requests Seedance 2.5, read `../seedance-25-replica/SKILL.md` and let that
Skill own the current Job's generation model from unit planning through any later paid submission.
This is a terminal model route: after selecting it, do not continue into `seedance-run`, ordinary
Seedance 2.0 defaults, or 2.0 request builders. Keep this full-flow Skill's lifecycle, QC, and
paid-generation stop, then exit this Skill and return control to the Seedance 2.5 Skill.

If the user explicitly requests MiniMax H3, read `../minimax-h3-replica/SKILL.md` and let that
Skill own the direct Ref2VA workflow. Do not start the storyboard-edit or Seedance handoff route.

If the user explicitly requests ordinary Seedance 2.0 API generation, direct video generation,
or final-video generation for the current Job, read `../seedance-run/SKILL.md`. Treat that request
as approval for exactly the current Job's required Parts once and route through the plugin-owned
generation lifecycle. Never fall back to a global Seedance Skill or runner.

Then read:

- `../../engine/.agents/skills/viral-replica/SKILL.md` for the queue/lifecycle adapter
- `../../engine/.agents/skills/video-replication/SKILL.md` for the replication craft method

Expose only this entry for full-flow work. Do not surface engine-private craft, provider, checker,
bootstrap, or maintenance skills as alternate public entry points.

Maintainer no-spend verification uses `../../scripts/run-no-spend-smoke.py`. It runs the installed
package against non-client Product Fixtures, stops before paid generation, prints all five progress
labels, and reports concrete image, prompt, audio, manifest, handoff, and QC inspection paths.
""",
        "seedance-run": """---
name: seedance-run
description: Submit an ordinary Seedance 2.0-locked ShotLoom Job through its API. Use only when the user explicitly requests ordinary Seedance 2.0 or the prepared Job is already locked to ordinary 2.0; never use for a Seedance 2.5-locked Job.
---

# Seedance Run

Before doing any other work, inspect the current Job for `seedance25_route_lock.json` or an accepted
Seedance 2.5 upload pack. If either exists, stop this route and hand control to
`../seedance-25-replica/SKILL.md`. Do not reinterpret a generic request such as “生成当前视频” as
permission to replace the Job's Seedance 2.5 model family with ordinary Seedance 2.0.

This is the public continuation from a prepared ShotLoom Job into the plugin-owned paid generation
stage. It is not a generic provider CLI and must not bypass Job state, request QC, cost policy, or
duplicate-submission protection.

Resolve the explicit Workspace and current `jobs/<job-id>/work` from the user's paths or the active
ShotLoom Job. Set or preserve `handoff_mode=api`. A direct request to run Seedance, generate the
video, or produce the final video is approval for exactly the current Job's required Parts once;
record that approval using the Job-local approval contract before any paid call. A retry or retake
still requires the separate targeted approval required by the engine policy.

Read and follow, in order:

- `../../engine/AGENTS.md`
- `../../engine/COST_POLICY.md`
- `../../engine/workers/generation_worker.md`
- `../../engine/gates/generation_gate.md`

The only supported paid route is the sealed plugin-owned chain
`../../engine/tools/generation_fanout.py` ->
`../../engine/tools/seedance_taskcode_runner.py`. Run the free preflight, persist the reservation,
then run the sealed Part plan. Never invoke a global Seedance Skill, a script under
`~/.codex/skills`, or a sibling checkout. Do not call `seedance_taskcode_runner.py` directly.

Before the free preflight, enforce the verified all-reference transport route:

- Convert every reference image and every reference video into a Pixmax asset, poll every item
  until `Status=Active`, and submit only `asset://asset-...` visual URLs. Never mix a direct
  HTTPS visual URL into a paid request.
- Export the approved reference-audio master to MP3 without changing its content or timing,
  upload that MP3 to a public HTTP(S) URL, and submit that URL as `reference_audio`. Never submit
  WAV or an `asset://` audio reference.
- Preserve an asset manifest showing every submitted visual ref with `Status=Active`. The complete
  image/video ref set in the request must match that manifest. Stop before reservation or provider
  submission if any visual ref is missing, non-Active, or non-`asset://asset-...`, or if audio is
  not a public `.mp3` URL. By default, place it beside the request as
  `partX_asset_binding.json`; the runner writes `active_visual_asset_preflight.json`.

Ordinary Seedance 2.0 uses the exact model route declared by the current engine rules; do not
reinterpret it as Mini, Fast, or Seedance 2.5. Persist the create response, task key, polling
history, downloaded output, completion report, and selected-output manifest in the current Job.

If an earlier `task_create` attempt has no locally persisted task key and the provider outcome is unknown,
STOP and inspect or reconcile that attempt. Never submit another paid task merely because the old
caller timed out, lost buffered output, or used a proxy. Continue only by polling an existing task
key, or after the prior attempt is conclusively failed and the user supplies any newly required
targeted approval.
""",
        "minimax-h3-replica": """---
name: minimax-h3-replica
description: Replicate a source video with MiniMax H3 using replacement person, product, and approved audio references. Use only when the user explicitly requests MiniMax H3 for replication or asks to adapt an existing ShotLoom Job to MiniMax H3.
---

# MiniMax H3 Replica

Read `../../engine/.agents/skills/minimax-h3-replica/SKILL.md` and its linked prompt and request
standards. Use the accepted Job artifacts where available. Keep every H3 unit isolated, preserve
the raw provider output, and run its `audio_master_gate.py` before upload and paid submission.
Changed speech must use a complete TTS master per unit and direct user listening approval; a short
source timbre sample can never satisfy that gate. Stop before paid generation unless the current
Job has explicit approval.
""",
        "seedance-25-replica": """---
name: seedance-25-replica
description: Build and run source-faithful Seedance 2.5 replication tasks with up-to-30-second units, optional camera-only depth, explicit audio modes, and the verified Wujie taskCode 2509 route. Use when the user explicitly requests Seedance 2.5, asks to adapt an existing replica Job to Seedance 2.5, or asks to generate a prepared 2.5 Job.
---

# Seedance 2.5 Replica

Read `../../engine/.agents/skills/seedance-25-replica/SKILL.md` and every reference it requires.

Selecting this Skill locks the current Job to Seedance 2.5. Depth is optional and disabled by
default; add one same-interval camera-only depth reference only when the user requests it or an
accepted Job decision enables it. Choose exactly one audio mode before prompt writing:
`generated_voiceover` or `original_master_postmix`. Preserve that choice through prompt writing,
request packaging, generation, and finishing. Stop before paid generation unless the current Job
already has explicit approval.
""",
        "video-shot-refinement": """---
name: video-shot-refinement
description: Bounded local repair for one failed video interval inside an otherwise accepted master.
---

# Video Shot Refinement

Read `../../engine/.agents/skills/video-shot-refinement/SKILL.md`.

If the request expands into full re-replication, switch back to `$viral-replica` instead of
surfacing any engine-private craft entry.
""",
        "video-subtitle-removal": """---
name: video-subtitle-removal
description: Remove hard subtitles from a supplied or generated video using the cheapest valid route.
---

# Video Subtitle Removal

Read `../../engine/.agents/skills/video-subtitle-removal/SKILL.md`.

Keep this bounded to subtitle classification and removal. Do not surface provider or checker
implementation as public alternatives.
""",
    }
    for name, text in wrappers.items():
        write_text(package_root / "skills" / name / "SKILL.md", text)


def write_workspace_template(package_root: Path) -> None:
    write_text(
        package_root / "workspace-template" / "workspace.yaml",
        """schema_version: 1
workspace_kind: viral-replica
default_handoff_mode: web
supported_host: apple-silicon-macos
""",
    )
    readmes = {
        "references/products/README.md": "Store imported product references here.\n",
        "references/people/README.md": "Store imported approved person or model references here.\n",
        "references/videos/README.md": "Store imported source videos here.\n",
        "references/audio/README.md": "Store imported external audio references here.\n",
        "jobs/README.md": "Each job gets input, work, qc, and delivery archives under this tree.\n",
        "deliveries/README.md": "Expose only active accepted delivery outcomes here.\n",
        ".viral-replica/README.md": "Plugin-owned workspace system area. Keep runtime and cache rebuildable.\n",
    }
    for rel, text in readmes.items():
        write_text(package_root / "workspace-template" / rel, text)


def write_fixture_assets(source_root: Path, package_root: Path) -> None:
    product_fixture_src = source_root / "product-fixtures" / "v1"
    try:
        validate_fixture_suite(product_fixture_src)
    except FixtureValidationError as exc:
        raise PackageBuildError(f"Product Fixture suite failed validation: {exc}") from exc
    product_fixture_dst = package_root / "assets" / "fixtures" / "v1"
    for source in sorted(product_fixture_src.rglob("*")):
        if source.is_symlink():
            raise PackageBuildError("Product Fixture suite contains a symbolic link")
        if not source.is_file():
            continue
        target = product_fixture_dst / source.relative_to(product_fixture_src)
        ensure_parent(target)
        shutil.copy2(source, target)
        target.chmod(0o644)
    try:
        validate_fixture_suite(product_fixture_dst)
    except FixtureValidationError as exc:
        raise PackageBuildError(
            f"packaged Product Fixture suite failed validation: {exc}"
        ) from exc

    fixture_src = source_root / "tests" / "fixtures" / "timing_events.jsonl"
    fixture_dst = package_root / "assets" / "fixtures" / "timing_events.jsonl"
    ensure_parent(fixture_dst)
    shutil.copy2(fixture_src, fixture_dst)
    fixture_dst.chmod(0o644)
    write_json(
        package_root / "assets" / "fixtures" / "fixture_origin.json",
        {
            "fixture_id": "timing-events-jsonl",
            "packaged_path": "assets/fixtures/timing_events.jsonl",
            "source": str(fixture_src.relative_to(source_root)),
            "license_or_authorization": "repository-owned synthetic fixture",
            "non_client": True,
            "content_summary": "Synthetic stage-timing event log for deterministic timing reports.",
            "expected_logical_roles": ["timing_event_log"],
            "sha256": file_sha256(fixture_src),
            "creation_tool": "repository fixture",
            "redistribution_rights": "internal private release validation only",
        },
    )


def write_package_docs(package_root: Path) -> None:
    write_text(
        package_root / "docs" / "install.md",
        """# Minimal local installation

Run `./install.command` from the delivered package. The MVP validates the package, creates one
managed copy at `~/plugins/shotloom`, appends the supported personal-marketplace entry, runs
`codex plugin add shotloom@personal`, and confirms discovery with `codex plugin list`.

This is a first-install path only. An existing managed copy or marketplace entry stops with an
actionable message; upgrade, repair, rollback, uninstall, and automatic update remain outside this
MVP. Installation never creates a Client Workspace, installs a runtime, or stores credentials.
Start a new Codex task after installation so the three Customer Skills are loaded.
""",
    )
    write_text(
        package_root / "docs" / "package-layout.md",
        """# Canonical Layout

- `.codex-plugin/plugin.json`: Codex plugin manifest
- `marketplace.json`: personal marketplace seed entry
- `skills/`: exactly six public customer-facing wrappers
- `engine/`: private runtime root assembled from allowlisted product sources
- `profiles/builtin/`: built-in reusable product rules
- `workspace-template/`: canonical workspace bootstrap material
- `assets/fixtures/`: non-client validation fixtures
- `scripts/`: package-local install and validation utilities
- `tests/`: package-local structural smoke tests
""",
    )
    write_text(
        package_root / "docs" / "release-identity.md",
        """# Release Identity

Each private release is identified by strict semver plus the SHA-256 digest of the signed release
manifest. Reusing one semver for different archive bytes is rejected.
""",
    )
    write_text(
        package_root / "docs" / "product-fixtures.md",
        """# Product Fixtures

`assets/fixtures/v1/` is the frozen, non-client validation set. Its origin manifest records the
source, redistribution authorization, non-client statement, content summary, expected logical
roles, and byte digests for every Fixture.

LegacyLayout and CanonicalLayout consume the same Runtime Contract, ordered Effective Profile
components, zero-spend approval, reference order, and logical roles. The packaged validator runs
each layout twice through the sealed offline recorder. An unmatched or expired request, a network
or real-submit attempt, or a golden-evidence refresh request stops. Validation creates no provider,
paid, or media-generation task.
""",
    )
    write_text(
        package_root / "docs" / "no-spend-smoke.md",
        """# Installed no-spend smoke

On a Supported Host with its runtime dependencies already available:

```bash
python3 scripts/run-no-spend-smoke.py \
  --workspace "<new-empty-workspace>" \
  --report "<new-empty-workspace>/no-spend-smoke.json"
```

The smoke uses only packaged non-client Product Fixtures and the sealed zero-submit recorder. It
invokes the public `viral-replica` launcher, runs the production source-blueprint, image-batch, and
Pre-Seedance maker/gate/QC paths, emits a web handoff, resumes the same Job from its checkpoint, and
checks the shot-refinement and subtitle-removal approval boundaries. Any real task, paid task,
unmatched recorder request, fallback, outbound attempt, or write outside the Workspace is a hard
failure. The smoke never installs dependencies or reads Service Authorization.
""",
    )


def write_package_tests(package_root: Path) -> None:
    write_text(
        package_root / "tests" / "README.md",
        "Package-local smoke tests validate the canonical layout and the public skill surface.\n",
    )
    write_text(
        package_root / "tests" / "test_layout_contract.py",
        """import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LayoutContractTest(unittest.TestCase):
    def test_public_skill_surface_stays_bounded(self):
        skills = sorted(
            path.name for path in (ROOT / "skills").iterdir() if path.is_dir()
        )
        self.assertEqual(
            skills,
            [
                "minimax-h3-replica",
                "seedance-25-replica",
                "seedance-run",
                "video-shot-refinement",
                "video-subtitle-removal",
                "viral-replica",
            ],
        )

    def test_manifest_name_matches_package_root(self):
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual("shotloom", manifest["name"])


if __name__ == "__main__":
    unittest.main()
""",
    )


def write_generated_scripts(package_root: Path) -> None:
    write_text(
        package_root / "install.command",
        """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/scripts/install_private_plugin.py" --package-root "$ROOT" "$@"
""",
        mode=0o755,
    )
    write_text(
        package_root / "scripts" / "run-canonical-job.py",
        """#!/usr/bin/env python3
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(plugin_root / "engine" / "tools"))
    from canonical_plugin_job import main as launch

    return launch(plugin_root)


if __name__ == "__main__":
    raise SystemExit(main())
""",
        mode=0o755,
    )
    write_text(
        package_root / "scripts" / "run-no-spend-smoke.py",
        """#!/usr/bin/env python3
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(plugin_root / "engine" / "tools"))
    from thin_plugin_smoke import main as smoke

    return smoke(["--plugin-root", str(plugin_root), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
""",
        mode=0o755,
    )
    write_text(
        package_root / "scripts" / "install_private_plugin.py",
        """#!/usr/bin/env python3
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(plugin_root / "engine" / "tools"))
    from private_plugin_installer import main as install

    return install()


if __name__ == "__main__":
    raise SystemExit(main())
""",
        mode=0o755,
    )
    write_text(
        package_root / "scripts" / "validate-package.py",
        """#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path


TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".csv",
    ".command",
}

FORBIDDEN_PATH_PATTERNS = (
    "output/**",
    "workspace-dev/**",
    ".sandcastle/**",
    ".pytest_cache/**",
    "__pycache__/**",
    ".mypy_cache/**",
    ".cache/**",
    ".venv*/**",
    "node_modules/**",
    "**/*.pyc",
    "**/.DS_Store",
    ".viral-replica/runtime/**",
    "**/output/**",
    "**/evidence/**",
    "**/jobs/job-*/**",
    "deliveries/**",
    "engine/output/**",
    "engine/evidence/**",
    "engine/deliveries/**",
    "engine/BRIEF.md",
    "engine/STATE.md",
    "engine/jobs.csv",
    "engine/RUNNER_STATE.json",
)

FORBIDDEN_CONTENT_PATTERNS = {
    "maintainer_absolute_path": re.compile(r"(/Users/[^/\\s]+/|/home/[^/\\s]+/)"),
    "signed_url": re.compile(r"([?&](?:X-Amz-Signature|X-Goog-Signature|Signature|sig)=)", re.IGNORECASE),
    "global_skill_dependency": re.compile(r"(~?/\\.codex/skills/|~?\\.codex/skills/)", re.IGNORECASE),
    "credential_value": re.compile(
        r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|Authorization:\\s*Bearer\\s+[A-Za-z0-9._~+/-]{16,}"
        r"|\\bAKIA[0-9A-Z]{16}\\b"
        r"|\\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)\\s*[:=]\\s*['\\\"][A-Za-z0-9_./+=-]{16,}['\\\"]"
        r"|^\\s*(?:api[_-]?key|access[_-]?token|secret[_-]?key)\\s*=\\s*[A-Za-z0-9_./+=-]{16,}\\s*$)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

FORBIDDEN_FILENAMES = {
    ".env",
    "auth.json",
    "credentials.json",
    "service-account.json",
}

KNOWN_FIXTURE_ORIGINS = {
    "assets/fixtures/fixture_origin.json",
    "assets/fixtures/v1/fixture_origin.json",
}

TIMING_FIXTURE_ORIGIN_FIELDS = {
    "fixture_id",
    "packaged_path",
    "source",
    "license_or_authorization",
    "non_client",
    "content_summary",
    "expected_logical_roles",
    "sha256",
    "creation_tool",
    "redistribution_rights",
}

FIXTURE_MEDIA_SUFFIXES = (
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".mkv",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".svg",
    ".y4m",
    ".pcm",
    ".pcm_u8",
)

SEMVER_RE = re.compile(
    r"^(0|[1-9]\\d*)\\."
    r"(0|[1-9]\\d*)\\."
    r"(0|[1-9]\\d*)"
    r"(?:-(?:0|[1-9]\\d*|\\d*[A-Za-z-][0-9A-Za-z-]*)(?:\\."
    r"(?:0|[1-9]\\d*|\\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$"
)

EXPECTED_SKILLS = {
    "minimax-h3-replica",
    "seedance-25-replica",
    "seedance-run",
    "video-shot-refinement",
    "video-subtitle-removal",
    "viral-replica",
}

REQUIRED_PATHS = (
    ".codex-plugin/plugin.json",
    "marketplace.json",
    "install.command",
    "engine/AGENTS.md",
    "engine/rules/STAGE_RULES.json",
    "engine/tools/canonical_execution_context.py",
    "engine/tools/canonical_plugin_job.py",
    "engine/tools/run_next_loop_round.py",
    "engine/smoke/pre_seedance_no_spend.py",
    "engine/workers/checker_worker.md",
    "profiles/builtin",
    "workspace-template",
    "assets/fixtures",
    "tests",
    "docs",
    "scripts",
    "scripts/run-canonical-job.py",
    "scripts/run-no-spend-smoke.py",
)


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def validated_fixture_media(package_root: Path):
    package_root = package_root.resolve()
    fixture_root = package_root / "assets" / "fixtures"
    allowed = set()
    issues = []
    discovered = {
        path.relative_to(package_root).as_posix(): path
        for path in fixture_root.rglob("fixture_origin.json")
    }

    for relative in sorted(set(discovered) - KNOWN_FIXTURE_ORIGINS):
        issues.append(f"unknown_fixture_origin: {relative}")
    for relative in sorted(KNOWN_FIXTURE_ORIGINS - set(discovered)):
        issues.append(f"missing_fixture_origin: {relative}")

    timing_relative = "assets/fixtures/fixture_origin.json"
    timing_origin = discovered.get(timing_relative)
    if timing_origin is not None:
        timing_issues = []
        try:
            payload = json.loads(timing_origin.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            timing_issues.append(f"unreadable JSON: {exc}")
            payload = {}
        if timing_origin.is_symlink():
            timing_issues.append("manifest cannot be a symbolic link")
        if not isinstance(payload, dict) or set(payload) != TIMING_FIXTURE_ORIGIN_FIELDS:
            timing_issues.append("provenance fields are not exact")
        if payload.get("fixture_id") != "timing-events-jsonl":
            timing_issues.append("fixture identity changed")
        if payload.get("packaged_path") != "assets/fixtures/timing_events.jsonl":
            timing_issues.append("packaged path changed")
        if payload.get("source") != "tests/fixtures/timing_events.jsonl":
            timing_issues.append("source identity changed")
        if payload.get("non_client") is not True:
            timing_issues.append("non_client must be true")
        for field in (
            "license_or_authorization",
            "content_summary",
            "creation_tool",
            "redistribution_rights",
        ):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                timing_issues.append(f"{field} must be a non-empty string")
        roles = payload.get("expected_logical_roles")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role.strip() for role in roles)
        ):
            timing_issues.append("expected_logical_roles must be a non-empty string list")
        digest = payload.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            timing_issues.append("sha256 must be a lowercase SHA-256 digest")

        media = package_root / "assets" / "fixtures" / "timing_events.jsonl"
        if not media.is_file() or media.is_symlink():
            timing_issues.append("declared fixture file is missing or linked")
        elif isinstance(digest, str) and hashlib.sha256(media.read_bytes()).hexdigest() != digest:
            timing_issues.append("declared fixture digest does not match bytes")
        if timing_issues:
            issues.extend(
                f"invalid_fixture_origin: {timing_relative}: {detail}"
                for detail in timing_issues
            )
        else:
            allowed.add(media.relative_to(package_root).as_posix())

    suite_relative = "assets/fixtures/v1/fixture_origin.json"
    suite_origin = discovered.get(suite_relative)
    if suite_origin is not None:
        if suite_origin.is_symlink():
            issues.append(
                f"invalid_fixture_origin: {suite_relative}: "
                "manifest cannot be a symbolic link"
            )
        else:
            suite_root = suite_origin.parent
            try:
                sys.dont_write_bytecode = True
                sys.path.insert(0, str(package_root / "engine" / "tools"))
                from product_fixture_suite import validate_fixture_suite

                validate_fixture_suite(suite_root)
                suite_payload = json.loads(suite_origin.read_text(encoding="utf-8"))
                entries = list(suite_payload["suite_files"])
                for fixture in suite_payload["fixtures"]:
                    entries.extend(fixture["files"])
                for entry in entries:
                    candidate = (suite_root / entry["path"]).resolve()
                    candidate.relative_to(suite_root.resolve())
                    allowed.add(candidate.relative_to(package_root).as_posix())
            except Exception as exc:
                issues.append(
                    f"invalid_fixture_origin: {suite_relative}: {exc}"
                )
    return allowed, issues


def scan_package_tree(package_root: Path) -> list[str]:
    allowed_fixture_media, issues = validated_fixture_media(package_root)
    for path in sorted(package_root.rglob("*")):
        rel = path.relative_to(package_root).as_posix()
        if path.is_symlink():
            issues.append(f"symbolic_link_forbidden: {rel}")
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in FORBIDDEN_PATH_PATTERNS):
            issues.append(f"historical_job_or_workspace_state: {rel}")
            continue
        if not path.is_file():
            continue
        if path.name.lower() in FORBIDDEN_FILENAMES:
            issues.append(f"credential_material: {rel}")
        if rel != "scripts/validate-package.py" and (
            is_text_file(path) or path.name.lower() in FORBIDDEN_FILENAMES
        ):
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_CONTENT_PATTERNS.items():
                if pattern.search(text):
                    issues.append(f"{label}: {rel}")
        lower = rel.lower()
        if lower.endswith(FIXTURE_MEDIA_SUFFIXES):
            if rel not in allowed_fixture_media:
                issues.append(f"client_media_or_generated_asset: {rel}")
        if lower.endswith((".pem", ".key", ".p12", ".pfx")):
            issues.append(f"credential_material: {rel}")
    return issues


def validate_structure(package_root: Path) -> list[str]:
    issues = []
    if package_root.name != "shotloom":
        issues.append("package root must be named shotloom")
    for rel in REQUIRED_PATHS:
        if not (package_root / rel).exists():
            issues.append(f"missing required path: {rel}")

    try:
        manifest = json.loads(
            (package_root / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError) as exc:
        issues.append(f"invalid plugin manifest: {exc}")
        manifest = {}
    if manifest.get("name") != "shotloom":
        issues.append("plugin manifest name must be shotloom")
    if manifest.get("skills") != "./skills/":
        issues.append("plugin manifest skills must be ./skills/")
    version = manifest.get("version")
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        issues.append("plugin manifest version must be strict semver")

    skills_root = package_root / "skills"
    actual_skills = (
        {path.name for path in skills_root.iterdir() if path.is_dir()}
        if skills_root.is_dir()
        else set()
    )
    if actual_skills != EXPECTED_SKILLS:
        issues.append(
            "public skill surface must contain exactly: "
            + ", ".join(sorted(EXPECTED_SKILLS))
        )

    try:
        marketplace = json.loads(
            (package_root / "marketplace.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        issues.append(f"invalid marketplace manifest: {exc}")
        marketplace = {}
    plugins = marketplace.get("plugins")
    if (
        not isinstance(plugins, list)
        or len(plugins) != 1
        or plugins[0].get("name") != "shotloom"
        or plugins[0].get("source", {}).get("path")
        != "./plugins/shotloom"
    ):
        issues.append("marketplace identity must resolve ./plugins/shotloom")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root")
    args = parser.parse_args()
    package_root = Path(args.package_root).resolve()
    issues = validate_structure(package_root)
    issues.extend(scan_package_tree(package_root))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(package_root / "engine" / "tools"))
    try:
        from product_fixture_suite import validate_fixture_suite

        validate_fixture_suite(package_root / "assets" / "fixtures" / "v1")
    except Exception as exc:
        issues.append(f"invalid Product Fixture suite: {exc}")
    if issues:
        print("\\n".join(issues))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
        mode=0o755,
    )


def write_builtin_profiles(source_root: Path, package_root: Path) -> None:
    profile_root = source_root / "rules" / "product-profiles"
    for source in sorted(profile_root.rglob("*.json")):
        rel = source.relative_to(profile_root)
        target = package_root / "profiles" / "builtin" / rel
        ensure_parent(target)
        shutil.copy2(source, target)
        target.chmod(0o644)


def write_engine_compat_files(package_root: Path) -> None:
    write_text(
        package_root / "engine" / ".codex" / "agents" / "viral-replica-checker.toml",
        """name = "viral-replica-checker"
mode = "review-only"
instruction = "Inspect actual artifacts. Do not repair or mutate workspace state."
""",
    )
    for rel, text in {
        "README.md": "# Kongfengchun\n\nSanitized built-in operating notes for Kongfengchun profile routing.\n",
        "product-profile.md": "# Product Profile\n\nUse the built-in `rules/product-profiles` files as the machine-readable source of truth.\n",
        "passed-standards.md": "# Passed Standards\n\nUse source-locked storyboard edits, white thick mud for clay-mask work, and approved identity-only replacement.\n",
        "failed-cases.md": "# Failed Cases\n\nReject old product carry-over, subtitle leakage, wrong mud color, and protagonist identity spread to support roles.\n",
        "loop-overrides.md": "# Loop Overrides\n\nThe public package keeps the loop source-locked, necessary-only, and approval-gated.\n",
        "lesson-registry.jsonl": "",
    }.items():
        write_text(package_root / "engine" / "client-profiles" / "kongfengchun" / rel, text)


def build_content_manifest(package_root: Path, version: str) -> dict[str, object]:
    files = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(package_root))
        mode = oct(stat.S_IMODE(path.stat().st_mode))
        files.append(
            {
                "path": rel,
                "type": "file",
                "mode": mode,
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return {
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "version": version,
        "files": files,
    }


def openssl_sign(payload: bytes, private_key: Path, public_key: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload_path = root / "release-payload.json"
        signature_path = root / "release-payload.sig"
        payload_path.write_bytes(payload)
        try:
            subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(private_key),
                    "-out",
                    str(signature_path),
                    str(payload_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key),
                    "-signature",
                    str(signature_path),
                    str(payload_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PackageBuildError(
                "release signing failed or the public key does not match the private key"
            ) from exc
        return signature_path.read_bytes().hex()


def build_archive(package_root: Path, archive_path: Path) -> str:
    ensure_parent(archive_path)
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in sorted(package_root.rglob("*")):
                    rel = path.relative_to(package_root.parent)
                    info = tar.gettarinfo(str(path), arcname=str(rel))
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if path.is_file():
                        with path.open("rb") as handle:
                            tar.addfile(info, handle)
                    else:
                        tar.addfile(info)
    return file_sha256(archive_path)


def record_release_identity(
    registry_path: Path,
    version: str,
    package_name: str,
    archive_sha256: str,
    release_identity: str,
) -> None:
    registry = {"package_name": package_name, "releases": {}}
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    releases = registry.setdefault("releases", {})
    existing = releases.get(version)
    if existing and (
        existing.get("archive_sha256") != archive_sha256
        or existing.get("release_identity") != release_identity
    ):
        raise PackageBuildError(
            f"same version has a different release identity: {version}"
        )
    releases[version] = {
        "archive_sha256": archive_sha256,
        "release_identity": release_identity,
    }
    write_json(registry_path, registry)


def validated_fixture_media(package_root: Path) -> tuple[set[str], list[str]]:
    package_root = package_root.resolve()
    fixture_root = package_root / "assets" / "fixtures"
    allowed: set[str] = set()
    issues: list[str] = []
    discovered = {
        path.relative_to(package_root).as_posix(): path
        for path in fixture_root.rglob("fixture_origin.json")
    }

    for relative in sorted(set(discovered) - KNOWN_FIXTURE_ORIGINS):
        issues.append(f"unknown_fixture_origin: {relative}")
    for relative in sorted(KNOWN_FIXTURE_ORIGINS - set(discovered)):
        issues.append(f"missing_fixture_origin: {relative}")

    timing_relative = "assets/fixtures/fixture_origin.json"
    timing_origin = discovered.get(timing_relative)
    if timing_origin is not None:
        timing_issues: list[str] = []
        try:
            payload = json.loads(timing_origin.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            timing_issues.append(f"unreadable JSON: {exc}")
            payload = {}
        if timing_origin.is_symlink():
            timing_issues.append("manifest cannot be a symbolic link")
        if not isinstance(payload, dict) or set(payload) != TIMING_FIXTURE_ORIGIN_FIELDS:
            timing_issues.append("provenance fields are not exact")
        if payload.get("fixture_id") != "timing-events-jsonl":
            timing_issues.append("fixture identity changed")
        if payload.get("packaged_path") != "assets/fixtures/timing_events.jsonl":
            timing_issues.append("packaged path changed")
        if payload.get("source") != "tests/fixtures/timing_events.jsonl":
            timing_issues.append("source identity changed")
        if payload.get("non_client") is not True:
            timing_issues.append("non_client must be true")
        for field in (
            "license_or_authorization",
            "content_summary",
            "creation_tool",
            "redistribution_rights",
        ):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                timing_issues.append(f"{field} must be a non-empty string")
        roles = payload.get("expected_logical_roles")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role.strip() for role in roles)
        ):
            timing_issues.append("expected_logical_roles must be a non-empty string list")
        digest = payload.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            timing_issues.append("sha256 must be a lowercase SHA-256 digest")

        media = package_root / "assets" / "fixtures" / "timing_events.jsonl"
        if not media.is_file() or media.is_symlink():
            timing_issues.append("declared fixture file is missing or linked")
        elif isinstance(digest, str) and file_sha256(media) != digest:
            timing_issues.append("declared fixture digest does not match bytes")
        if timing_issues:
            issues.extend(
                f"invalid_fixture_origin: {timing_relative}: {detail}"
                for detail in timing_issues
            )
        else:
            allowed.add(media.relative_to(package_root).as_posix())

    suite_relative = "assets/fixtures/v1/fixture_origin.json"
    suite_origin = discovered.get(suite_relative)
    if suite_origin is not None:
        if suite_origin.is_symlink():
            issues.append(
                f"invalid_fixture_origin: {suite_relative}: "
                "manifest cannot be a symbolic link"
            )
        else:
            suite_root = suite_origin.parent
            try:
                validate_fixture_suite(suite_root)
                suite_payload = json.loads(suite_origin.read_text(encoding="utf-8"))
                entries = list(suite_payload["suite_files"])
                for fixture in suite_payload["fixtures"]:
                    entries.extend(fixture["files"])
                for entry in entries:
                    candidate = (suite_root / entry["path"]).resolve()
                    candidate.relative_to(suite_root.resolve())
                    allowed.add(candidate.relative_to(package_root).as_posix())
            except (FixtureValidationError, KeyError, OSError, TypeError, ValueError) as exc:
                issues.append(
                    f"invalid_fixture_origin: {suite_relative}: {exc}"
                )
    return allowed, issues


def scan_package_tree(package_root: Path) -> list[str]:
    allowed_fixture_media, issues = validated_fixture_media(package_root)
    for path in sorted(package_root.rglob("*")):
        rel = path.relative_to(package_root).as_posix()
        if path.is_symlink():
            issues.append(f"symbolic_link_forbidden: {rel}")
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in FORBIDDEN_PATH_PATTERNS):
            issues.append(f"historical_job_or_workspace_state: {rel}")
            continue
        if path.is_file():
            if path.name.lower() in FORBIDDEN_FILENAMES:
                issues.append(f"credential_material: {rel}")
            if rel != "scripts/validate-package.py" and (
                is_text_file(path) or path.name.lower() in FORBIDDEN_FILENAMES
            ):
                text = path.read_text(encoding="utf-8")
                for label, pattern in FORBIDDEN_CONTENT_PATTERNS.items():
                    if pattern.search(text):
                        issues.append(f"{label}: {rel}")
            lower = rel.lower()
            if lower.endswith(FIXTURE_MEDIA_SUFFIXES):
                if rel not in allowed_fixture_media:
                    issues.append(f"client_media_or_generated_asset: {rel}")
            if lower.endswith((".pem", ".key", ".p12", ".pfx")):
                issues.append(f"credential_material: {rel}")
    return issues


def build_package(
    *,
    source_root: Path,
    out_root: Path,
    version: str,
    signing_private_key: Path,
    signing_public_key: Path,
    release_registry: Path,
) -> BuildResult:
    if SEMVER_RE.fullmatch(version) is None:
        raise PackageBuildError(f"invalid strict semver: {version}")
    if out_root.exists():
        shutil.rmtree(out_root)
    package_root = out_root / PACKAGE_NAME
    package_root.mkdir(parents=True, exist_ok=True)

    copy_engine(source_root, package_root)
    write_private_smoke_engine(source_root, package_root)
    write_engine_compat_files(package_root)
    write_public_wrappers(package_root)
    write_workspace_template(package_root)
    write_fixture_assets(source_root, package_root)
    write_package_docs(package_root)
    write_package_tests(package_root)
    write_generated_scripts(package_root)
    write_builtin_profiles(source_root, package_root)
    write_json(package_root / ".codex-plugin" / "plugin.json", plugin_manifest(version))
    write_json(package_root / "marketplace.json", marketplace_manifest())

    issues = scan_package_tree(package_root)
    if issues:
        raise PackageBuildError("\n".join(issues))

    content_manifest = build_content_manifest(package_root, version)
    content_manifest_path = out_root / f"{PACKAGE_NAME}.content-manifest.json"
    write_json(content_manifest_path, content_manifest)
    content_manifest_sha256 = file_sha256(content_manifest_path)

    archive_path = out_root / f"{PACKAGE_NAME}-{version}.tar.gz"
    archive_sha256 = build_archive(package_root, archive_path)
    release_payload = {
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "version": version,
        "key_id": RELEASE_KEY_ID,
        "public_key_sha256": file_sha256(signing_public_key),
        "content_manifest_file": content_manifest_path.name,
        "content_manifest_sha256": content_manifest_sha256,
        "archive_file": archive_path.name,
        "archive_sha256": archive_sha256,
    }
    signature = openssl_sign(
        stable_json_bytes(release_payload),
        signing_private_key,
        signing_public_key,
    )
    signed_release_manifest = {
        "payload": release_payload,
        "signature_algorithm": "rsa-sha256",
        "signature": signature,
    }
    signed_manifest_sha256 = hashlib.sha256(
        stable_json_bytes(signed_release_manifest)
    ).hexdigest()
    release_identity = f"{version}+{signed_manifest_sha256}"
    release_manifest = {
        "schema_version": 1,
        "package_name": PACKAGE_NAME,
        "version": version,
        "signed_release_manifest": signed_release_manifest,
        "signed_manifest_sha256": signed_manifest_sha256,
        "release_identity": release_identity,
    }
    release_manifest_path = out_root / f"{PACKAGE_NAME}.release-manifest.json"
    write_json(release_manifest_path, release_manifest)
    record_release_identity(
        registry_path=release_registry,
        version=version,
        package_name=PACKAGE_NAME,
        archive_sha256=archive_sha256,
        release_identity=release_identity,
    )
    return BuildResult(
        package_root=package_root,
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        content_manifest_path=content_manifest_path,
        content_manifest_sha256=content_manifest_sha256,
        release_manifest_path=release_manifest_path,
        release_identity=release_identity,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--signing-private-key", required=True)
    parser.add_argument("--signing-public-key", required=True)
    parser.add_argument("--release-registry", required=True)
    args = parser.parse_args()
    build_package(
        source_root=Path(args.source_root).resolve(),
        out_root=Path(args.out_root).resolve(),
        version=args.version,
        signing_private_key=Path(args.signing_private_key).resolve(),
        signing_public_key=Path(args.signing_public_key).resolve(),
        release_registry=Path(args.release_registry).resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
