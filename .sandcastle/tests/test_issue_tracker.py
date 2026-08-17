import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TRACKER = Path(__file__).resolve().parents[1] / "issue_tracker.py"


def issue(number: int, status: str, blocked_by: str = "None") -> str:
    return (
        f"# {number} — Ticket {number}\n\n"
        "Type: task\n\n"
        f"**Blocked by:** {blocked_by}\n\n"
        f"**Status:** {status}\n\n"
        "- [ ] Acceptance criterion.\n"
    )


class IssueTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "16-baseline.md").write_text(
            issue(16, "resolved"), encoding="utf-8"
        )
        (self.root / "17-product-tree.md").write_text(
            issue(17, "resolved", "16 — Ticket 16"), encoding="utf-8"
        )
        (self.root / "18-package.md").write_text(
            issue(18, "ready-for-agent", "17 — Ticket 17"), encoding="utf-8"
        )
        (self.root / "19-fixtures.md").write_text(
            issue(19, "ready-for-agent", "18 — Ticket 18"), encoding="utf-8"
        )
        (self.root / "41-human-gate.md").write_text(
            issue(41, "ready-for-agent", "18 — Ticket 18"), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_tracker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TRACKER), "--root", str(self.root), *args],
            check=check,
            capture_output=True,
            text=True,
        )

    def test_list_returns_only_resolved_dependency_frontier(self) -> None:
        result = self.run_tracker("list")
        tickets = json.loads(result.stdout)
        self.assertEqual([ticket["id"] for ticket in tickets], [18])

    def test_legacy_heading_and_plain_metadata_are_supported(self) -> None:
        path = self.root / "15-legacy-format.md"
        path.write_text(
            "# Legacy format\n\n"
            "Type: prototype\n"
            "Status: resolved\n"
            "Blocked by: 01, 02\n",
            encoding="utf-8",
        )
        viewed = json.loads(self.run_tracker("view", "--id", "15").stdout)
        self.assertEqual(viewed["title"], "Legacy format")
        self.assertEqual(viewed["blocked_by"], [1, 2])

    def test_claim_is_exclusive_and_release_restores_frontier(self) -> None:
        claimed = json.loads(
            self.run_tracker(
                "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/ticket-18"
            ).stdout
        )
        self.assertEqual(claimed["status"], "claimed")

        duplicate = self.run_tracker(
            "claim",
            "--id",
            "18",
            "--run-id",
            "run-b",
            "--branch",
            "sandcastle/ticket-18-b",
            check=False,
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(json.loads(self.run_tracker("list").stdout), [])

        self.run_tracker(
            "release", "--id", "18", "--run-id", "run-a", "--reason", "smoke stop"
        )
        frontier = json.loads(self.run_tracker("list").stdout)
        self.assertEqual([ticket["id"] for ticket in frontier], [18])

    def test_resolve_advances_frontier_and_manual_gate_stays_excluded(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/ticket-18"
        )
        self.run_tracker(
            "review-ready",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/ticket-18",
            "--commit",
            "abc123",
            "--model",
            "gpt-5.6-sol",
            "--summary",
            "Implementation and review passed.",
        )
        self.run_tracker(
            "resolve",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/ticket-18",
            "--commit",
            "abc123",
            "--summary",
            "Implemented and verified.",
        )
        frontier = json.loads(self.run_tracker("list").stdout)
        self.assertEqual([ticket["id"] for ticket in frontier], [19])

        manual = self.run_tracker(
            "claim",
            "--id",
            "41",
            "--run-id",
            "run-manual",
            "--branch",
            "sandcastle/ticket-41",
            check=False,
        )
        self.assertNotEqual(manual.returncode, 0)

    def test_afk_integration_advances_frontier_before_human_resolution(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/ticket-18"
        )
        self.run_tracker(
            "review-ready",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/ticket-18",
            "--commit",
            "abc123",
            "--model",
            "gpt-5.6-sol",
            "--summary",
            "Implementation and review passed.",
        )
        integrated = json.loads(
            self.run_tracker(
                "integrate",
                "--id",
                "18",
                "--run-id",
                "run-a",
                "--branch",
                "sandcastle/ticket-18",
                "--integration-branch",
                "codex/sandcastle-afk-integration",
                "--commit",
                "abc123",
                "--summary",
                "Accepted into the AFK integration branch.",
            ).stdout
        )

        self.assertEqual(integrated["status"], "afk-integrated")
        self.assertIn(
            "Integration branch: `codex/sandcastle-afk-integration`",
            integrated["body"],
        )
        frontier = json.loads(self.run_tracker("list").stdout)
        self.assertEqual([ticket["id"] for ticket in frontier], [19])

        resolved = json.loads(
            self.run_tracker(
                "resolve",
                "--id",
                "18",
                "--run-id",
                "run-a",
                "--branch",
                "sandcastle/ticket-18",
                "--commit",
                "abc123",
                "--summary",
                "Human reviewed the final integration diff.",
            ).stdout
        )
        self.assertEqual(resolved["status"], "resolved")

    def test_afk_integration_rejects_an_unreviewed_commit(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/ticket-18"
        )
        self.run_tracker(
            "review-ready",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/ticket-18",
            "--commit",
            "abc123",
            "--model",
            "gpt-5.6-sol",
            "--summary",
            "Implementation and review passed.",
        )

        rejected = self.run_tracker(
            "integrate",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/ticket-18",
            "--integration-branch",
            "codex/sandcastle-afk-integration",
            "--commit",
            "def456",
            "--summary",
            "Wrong commit.",
            check=False,
        )

        self.assertNotEqual(rejected.returncode, 0)
        viewed = json.loads(self.run_tracker("view", "--id", "18").stdout)
        self.assertEqual(viewed["status"], "review-ready")

    def test_two_concurrent_claims_have_exactly_one_winner(self) -> None:
        commands = [
            [
                sys.executable,
                str(TRACKER),
                "--root",
                str(self.root),
                "claim",
                "--id",
                "18",
                "--run-id",
                run_id,
                "--branch",
                f"sandcastle/{run_id}",
            ]
            for run_id in ("run-a", "run-b")
        ]
        processes = [
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for command in commands
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sum(returncode == 0 for _, _, returncode in results), 1)

    def test_stale_run_cannot_mutate_a_reclaimed_ticket(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/run-a"
        )
        self.run_tracker(
            "release", "--id", "18", "--run-id", "run-a", "--reason", "retry"
        )
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-b", "--branch", "sandcastle/run-b"
        )

        stale = self.run_tracker(
            "release",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--reason",
            "stale coordinator",
            check=False,
        )

        self.assertNotEqual(stale.returncode, 0)
        viewed = json.loads(self.run_tracker("view", "--id", "18").stdout)
        self.assertEqual(viewed["status"], "claimed")

    def test_review_ready_binds_run_branch_commit_and_model(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/run-a"
        )
        ready = json.loads(
            self.run_tracker(
                "review-ready",
                "--id",
                "18",
                "--run-id",
                "run-a",
                "--branch",
                "sandcastle/run-a",
                "--commit",
                "abc123",
                "--model",
                "gpt-5.6-sol",
                "--summary",
                "Implementation and independent review passed.",
            ).stdout
        )

        self.assertEqual(ready["status"], "review-ready")
        self.assertIn("Model: `gpt-5.6-sol`", ready["body"])
        self.assertIn("Commit: `abc123`", ready["body"])

        wrong_commit = self.run_tracker(
            "resolve",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/run-a",
            "--commit",
            "def456",
            "--summary",
            "Wrong commit.",
            check=False,
        )
        self.assertNotEqual(wrong_commit.returncode, 0)

        resolved = json.loads(
            self.run_tracker(
                "resolve",
                "--id",
                "18",
                "--run-id",
                "run-a",
                "--branch",
                "sandcastle/run-a",
                "--commit",
                "abc123",
                "--summary",
                "Merged after final audit.",
            ).stdout
        )
        self.assertEqual(resolved["status"], "resolved")

    def test_afk_blocked_is_terminal_until_a_human_releases_it(self) -> None:
        self.run_tracker(
            "claim", "--id", "18", "--run-id", "run-a", "--branch", "sandcastle/run-a"
        )
        blocked = json.loads(
            self.run_tracker(
                "block",
                "--id",
                "18",
                "--run-id",
                "run-a",
                "--branch",
                "sandcastle/run-a",
                "--reason",
                "Reviewer found missing evidence.",
            ).stdout
        )
        self.assertEqual(blocked["status"], "afk-blocked")
        self.assertEqual(json.loads(self.run_tracker("list").stdout), [])

        resolve = self.run_tracker(
            "resolve",
            "--id",
            "18",
            "--run-id",
            "run-a",
            "--branch",
            "sandcastle/run-a",
            "--commit",
            "abc123",
            "--summary",
            "Must not resolve.",
            check=False,
        )
        self.assertNotEqual(resolve.returncode, 0)


if __name__ == "__main__":
    unittest.main()
