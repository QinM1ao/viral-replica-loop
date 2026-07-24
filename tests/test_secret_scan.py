import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scan-secrets.py"
SPEC = importlib.util.spec_from_file_location("scan_secrets", SCRIPT)
scan_secrets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scan_secrets)


class SecretScanTests(unittest.TestCase):
    def test_detects_secret_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "sk-" + "A" * 32
            (root / "config.json").write_text(
                f'{{"api_key": "{secret}"}}\n',
                encoding="utf-8",
            )

            findings = scan_secrets.scan(root)

            self.assertEqual(
                [(Path("config.json"), 1, "sk_token")],
                findings,
            )
            self.assertNotIn(secret, repr(findings))

    def test_allows_environment_references_and_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.py").write_text(
                'api_key = "${MATPOOL_API_KEY}"\n'
                'secret_key = "example-secret-value"\n',
                encoding="utf-8",
            )

            self.assertEqual([], scan_secrets.scan(root))

    def test_skips_generated_and_local_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "sk-" + "B" * 32
            for name in ("output", "input", "deliverables", ".scratch"):
                directory = root / name
                directory.mkdir()
                (directory / "local.json").write_text(secret, encoding="utf-8")

            self.assertEqual([], scan_secrets.scan(root))


if __name__ == "__main__":
    unittest.main()
