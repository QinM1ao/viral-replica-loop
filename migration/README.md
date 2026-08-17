# LegacyLayout baseline

This directory contains the immutable, machine-readable input to the compatibility migration.

The baseline is created from current filesystem bytes through the explicit source-closure policy. Git HEAD is recorded only as information; it is never used as the source tree. Files selected as legacy observation anchors are hashed in place and are never copied, normalized, replayed, or submitted to a provider.

Run the complete LegacyLayout test manifest twice with provider credential variables removed. The normal partition runs under the macOS external-network-deny sandbox plus an injected Python socket/DNS guard. Eight explicitly listed isolation tests must start their own macOS write sandbox, so they run in a separate source-bound partition with the inherited Python guard; macOS does not permit nesting one system sandbox inside another. Loopback remains available only because the isolation contract tests use a local test server:

```bash
python3 tools/legacy_baseline.py run-tests \
  --root . \
  --out migration/baselines/legacy-layout-v1/test-run-1.json

python3 tools/legacy_baseline.py run-tests \
  --root . \
  --out migration/baselines/legacy-layout-v1/test-run-2.json
```

Freeze only after both results pass with the same source, Runtime Contract, test IDs, protected legacy bytes, and stable result projection:

```bash
python3 tools/legacy_baseline.py freeze \
  --root . \
  --test-run migration/baselines/legacy-layout-v1/test-run-1.json \
  --test-run migration/baselines/legacy-layout-v1/test-run-2.json \
  --out migration/baselines/legacy-layout-v1/baseline.lock.json
```

Verification is read-only and reports each added, missing, or changed object:

```bash
python3 tools/legacy_baseline.py verify \
  --root . \
  --baseline migration/baselines/legacy-layout-v1/baseline.lock.json
```

Do not replace a baseline lock in place. A legitimate behavior or policy change requires a new baseline identity and a separately reviewed baseline directory.
