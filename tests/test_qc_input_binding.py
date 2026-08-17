import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

import sys

sys.path.insert(0, str(TOOLS))

from qc_input_binding import build_input_manifest, validate_input_binding  # noqa: E402


class QcInputBindingTests(unittest.TestCase):
    def test_canonical_output_alias_keeps_legacy_logical_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_root = workspace / ".viral-replica" / "state"
            canonical_work = workspace / "jobs" / "job-001" / "work"
            audio = canonical_work / "audio.mp3"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"fixture-audio")
            output = state_root / "output"
            output.mkdir(parents=True)
            (output / "job-001").symlink_to(
                canonical_work,
                target_is_directory=True,
            )

            relative = "output/job-001/audio.mp3"
            manifest = build_input_manifest(state_root, [relative])

            self.assertEqual(list(manifest), [relative])
            binding = {
                "version": 1,
                "manifest": manifest,
            }
            from qc_input_binding import manifest_fingerprint

            binding["fingerprint"] = manifest_fingerprint(manifest)
            self.assertEqual(
                validate_input_binding(state_root, binding),
                (True, "program QC input binding matches current files"),
            )


if __name__ == "__main__":
    unittest.main()
