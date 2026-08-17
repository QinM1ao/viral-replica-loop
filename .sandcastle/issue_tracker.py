#!/usr/bin/env python3
"""Host-side local Markdown issue tracker for Sandcastle.

The tracker is intentionally not available inside the agent sandbox. A single
host coordinator owns dependency resolution and status transitions so two
agents cannot claim the same Markdown ticket.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


STATUS_RE = re.compile(
    r"^(?P<prefix>\*\*)?Status:(?P<suffix>\*\*)?\s*(?P<status>[^\r\n]+?)\s*$",
    re.MULTILINE,
)
BLOCKED_RE = re.compile(
    r"^(?:\*\*)?Blocked by:(?:\*\*)?\s*(?P<value>[^\r\n]+?)\s*$",
    re.MULTILINE,
)
TITLE_RE = re.compile(
    r"^#\s+(?:(?P<id>\d+)\s+[—-]\s+)?(?P<title>.+?)\s*$", re.MULTILINE
)
BLOCKER_ID_RE = re.compile(r"\b(\d{1,3})\b")
CLAIM_SECTION_RE = re.compile(
    r"^### Sandcastle claim —[^\r\n]*\r?\n\r?\n(?P<body>(?:- [^\r\n]*\r?\n)+)",
    re.MULTILINE,
)
REVIEW_SECTION_RE = re.compile(
    r"^### Sandcastle review ready —[^\r\n]*\r?\n\r?\n(?P<body>(?:- [^\r\n]*\r?\n)+)",
    re.MULTILINE,
)
INTEGRATION_SECTION_RE = re.compile(
    r"^### Sandcastle AFK integration —[^\r\n]*\r?\n\r?\n"
    r"(?P<body>(?:- [^\r\n]*\r?\n)+)",
    re.MULTILINE,
)
MANUAL_ONLY_TICKETS = frozenset({41, 42, 43})
SATISFIED_BLOCKER_STATUSES = frozenset({"resolved", "afk-integrated"})


class TrackerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Ticket:
    id: int
    title: str
    status: str
    blocked_by: List[int]
    body: str
    path: Path

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "path": str(self.path),
        }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_ticket(path: Path) -> Ticket:
    body = path.read_text(encoding="utf-8")
    title_match = TITLE_RE.search(body)
    status_match = STATUS_RE.search(body)
    if title_match is None:
        raise TrackerError(f"missing ticket heading: {path}")
    if status_match is None:
        raise TrackerError(f"missing Status line: {path}")
    filename_number = int(path.name.split("-", 1)[0])
    heading_id = title_match.group("id")
    number = int(heading_id) if heading_id is not None else filename_number
    if heading_id is not None and number != filename_number:
        raise TrackerError(
            f"ticket id mismatch: heading={number}, filename={filename_number}, path={path}"
        )
    blocked_match = BLOCKED_RE.search(body)
    blocked_value = blocked_match.group("value") if blocked_match else "None"
    blocked_by = [int(value) for value in BLOCKER_ID_RE.findall(blocked_value)]
    return Ticket(
        id=number,
        title=title_match.group("title"),
        status=status_match.group("status").strip(),
        blocked_by=blocked_by,
        body=body,
        path=path,
    )


def load_tickets(root: Path) -> dict[int, Ticket]:
    if not root.is_dir():
        raise TrackerError(f"ticket root does not exist: {root}")
    tickets: dict[int, Ticket] = {}
    for path in sorted(root.glob("[0-9][0-9]-*.md")):
        ticket = parse_ticket(path)
        if ticket.id in tickets:
            raise TrackerError(f"duplicate ticket id {ticket.id}: {path}")
        tickets[ticket.id] = ticket
    if not tickets:
        raise TrackerError(f"no ticket Markdown files found under: {root}")
    return tickets


def unresolved_blockers(ticket: Ticket, tickets: dict[int, Ticket]) -> List[int]:
    unresolved: List[int] = []
    for blocker_id in ticket.blocked_by:
        blocker = tickets.get(blocker_id)
        if blocker is None:
            raise TrackerError(
                f"ticket {ticket.id} references missing blocker {blocker_id}"
            )
        if blocker.status not in SATISFIED_BLOCKER_STATUSES:
            unresolved.append(blocker_id)
    return unresolved


@contextlib.contextmanager
def tracker_lock(root: Path) -> Iterator[None]:
    identity = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"sandcastle-ticket-tracker-{identity}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def replace_status(body: str, status: str) -> str:
    match = STATUS_RE.search(body)
    if match is None:
        raise TrackerError("missing Status line")
    prefix = match.group("prefix") or ""
    suffix = match.group("suffix") or ""
    replacement = f"{prefix}Status:{suffix} {status}"
    return body[: match.start()] + replacement + body[match.end() :]


def append_comment(body: str, heading: str, lines: List[str]) -> str:
    separator = "" if body.endswith("\n") else "\n"
    if "\n## Comments\n" not in body:
        body = f"{body}{separator}\n## Comments\n"
    return f"{body}\n### {heading}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def atomic_write(path: Path, body: str) -> None:
    mode = path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def section_value(section: str, name: str) -> Optional[str]:
    match = re.search(
        rf"^- {re.escape(name)}: `(?P<value>[^`\r\n]+)`\s*$",
        section,
        re.MULTILINE,
    )
    return match.group("value") if match else None


def latest_section(body: str, pattern: re.Pattern[str], name: str) -> str:
    matches = list(pattern.finditer(body))
    if not matches:
        raise TrackerError(f"missing latest Sandcastle {name} record")
    return matches[-1].group("body")


def require_claim_owner(
    ticket: Ticket,
    run_id: str,
    branch: Optional[str] = None,
    statuses: frozenset[str] = frozenset({"claimed"}),
) -> None:
    if ticket.status not in statuses:
        raise TrackerError(
            f"ticket {ticket.id} must be one of {sorted(statuses)}, "
            f"current status is {ticket.status}"
        )
    section = latest_section(ticket.body, CLAIM_SECTION_RE, "claim")
    current_run = section_value(section, "Run")
    current_branch = section_value(section, "Branch")
    if current_run != run_id:
        raise TrackerError(f"ticket {ticket.id} is not claimed by run {run_id}")
    if branch is not None and current_branch != branch:
        raise TrackerError(
            f"ticket {ticket.id} is claimed on {current_branch}, not {branch}"
        )


def list_frontier(root: Path) -> List[dict]:
    tickets = load_tickets(root)
    frontier = []
    for ticket in tickets.values():
        if ticket.id in MANUAL_ONLY_TICKETS:
            continue
        if ticket.status != "ready-for-agent":
            continue
        if unresolved_blockers(ticket, tickets):
            continue
        frontier.append(ticket.as_json())
    return sorted(frontier, key=lambda item: item["id"])


def claim(root: Path, ticket_id: Optional[int], run_id: str, branch: str) -> dict:
    with tracker_lock(root):
        tickets = load_tickets(root)
        if ticket_id is None:
            candidates = [
                ticket
                for ticket in tickets.values()
                if ticket.id not in MANUAL_ONLY_TICKETS
                and ticket.status == "ready-for-agent"
                and not unresolved_blockers(ticket, tickets)
            ]
            if not candidates:
                raise TrackerError("no dependency-ready tickets are available")
            ticket = min(candidates, key=lambda item: item.id)
        else:
            if ticket_id in MANUAL_ONLY_TICKETS:
                raise TrackerError(
                    f"ticket {ticket_id} is manual-only and cannot be claimed by AFK automation"
                )
            ticket = tickets.get(ticket_id)
            if ticket is None:
                raise TrackerError(f"ticket {ticket_id} does not exist")
            if ticket.status != "ready-for-agent":
                raise TrackerError(
                    f"ticket {ticket.id} is {ticket.status}, expected ready-for-agent"
                )
            blockers = unresolved_blockers(ticket, tickets)
            if blockers:
                raise TrackerError(
                    f"ticket {ticket.id} has unresolved blockers: {', '.join(map(str, blockers))}"
                )
        updated = replace_status(ticket.body, "claimed")
        updated = append_comment(
            updated,
            f"Sandcastle claim — {utc_now()}",
            [f"Run: `{run_id}`", f"Branch: `{branch}`"],
        )
        atomic_write(ticket.path, updated)
        claimed = parse_ticket(ticket.path).as_json()
        claimed["branch"] = branch
        claimed["run_id"] = run_id
        return claimed


def release(root: Path, ticket_id: int, run_id: str, reason: str) -> dict:
    with tracker_lock(root):
        ticket = load_tickets(root).get(ticket_id)
        if ticket is None:
            raise TrackerError(f"ticket {ticket_id} does not exist")
        require_claim_owner(
            ticket,
            run_id,
            statuses=frozenset({"claimed", "afk-blocked", "review-ready"}),
        )
        updated = replace_status(ticket.body, "ready-for-agent")
        updated = append_comment(
            updated,
            f"Sandcastle release — {utc_now()}",
            [f"Run: `{run_id}`", f"Reason: {reason}"],
        )
        atomic_write(ticket.path, updated)
        return parse_ticket(ticket.path).as_json()


def block(
    root: Path,
    ticket_id: int,
    run_id: str,
    branch: str,
    reason: str,
) -> dict:
    with tracker_lock(root):
        ticket = load_tickets(root).get(ticket_id)
        if ticket is None:
            raise TrackerError(f"ticket {ticket_id} does not exist")
        require_claim_owner(
            ticket,
            run_id,
            branch,
            statuses=frozenset({"claimed", "review-ready"}),
        )
        updated = replace_status(ticket.body, "afk-blocked")
        updated = append_comment(
            updated,
            f"Sandcastle AFK block — {utc_now()}",
            [
                f"Run: `{run_id}`",
                f"Branch: `{branch}`",
                f"Reason: {reason}",
            ],
        )
        atomic_write(ticket.path, updated)
        return parse_ticket(ticket.path).as_json()


def review_ready(
    root: Path,
    ticket_id: int,
    run_id: str,
    branch: str,
    commit: str,
    model: str,
    summary: str,
) -> dict:
    with tracker_lock(root):
        ticket = load_tickets(root).get(ticket_id)
        if ticket is None:
            raise TrackerError(f"ticket {ticket_id} does not exist")
        require_claim_owner(ticket, run_id, branch)
        if not re.fullmatch(r"[0-9a-fA-F]{6,64}", commit):
            raise TrackerError("commit must be a hexadecimal Git object id")
        updated = replace_status(ticket.body, "review-ready")
        updated = append_comment(
            updated,
            f"Sandcastle review ready — {utc_now()}",
            [
                f"Run: `{run_id}`",
                f"Branch: `{branch}`",
                f"Commit: `{commit}`",
                f"Model: `{model}`",
                f"Summary: {summary}",
            ],
        )
        atomic_write(ticket.path, updated)
        return parse_ticket(ticket.path).as_json()


def integrate(
    root: Path,
    ticket_id: int,
    run_id: str,
    branch: str,
    integration_branch: str,
    commit: str,
    summary: str,
) -> dict:
    with tracker_lock(root):
        ticket = load_tickets(root).get(ticket_id)
        if ticket is None:
            raise TrackerError(f"ticket {ticket_id} does not exist")
        require_claim_owner(
            ticket,
            run_id,
            branch,
            statuses=frozenset({"review-ready"}),
        )
        if not re.fullmatch(r"[0-9a-fA-F]{6,64}", commit):
            raise TrackerError("commit must be a hexadecimal Git object id")
        review_section = latest_section(
            ticket.body, REVIEW_SECTION_RE, "review-ready"
        )
        if section_value(review_section, "Run") != run_id:
            raise TrackerError("review-ready record belongs to another run")
        if section_value(review_section, "Branch") != branch:
            raise TrackerError("review-ready record belongs to another branch")
        if section_value(review_section, "Commit") != commit:
            raise TrackerError("commit does not match the reviewed commit")
        updated = replace_status(ticket.body, "afk-integrated")
        updated = append_comment(
            updated,
            f"Sandcastle AFK integration — {utc_now()}",
            [
                f"Run: `{run_id}`",
                f"Branch: `{branch}`",
                f"Integration branch: `{integration_branch}`",
                f"Commit: `{commit}`",
                f"Summary: {summary}",
            ],
        )
        atomic_write(ticket.path, updated)
        return parse_ticket(ticket.path).as_json()


def resolve(
    root: Path,
    ticket_id: int,
    run_id: str,
    branch: str,
    commit: str,
    summary: str,
) -> dict:
    with tracker_lock(root):
        ticket = load_tickets(root).get(ticket_id)
        if ticket is None:
            raise TrackerError(f"ticket {ticket_id} does not exist")
        require_claim_owner(
            ticket,
            run_id,
            branch,
            statuses=frozenset({"review-ready", "afk-integrated"}),
        )
        if not re.fullmatch(r"[0-9a-fA-F]{6,64}", commit):
            raise TrackerError("commit must be a hexadecimal Git object id")
        if ticket.status == "afk-integrated":
            evidence_section = latest_section(
                ticket.body, INTEGRATION_SECTION_RE, "AFK integration"
            )
        else:
            evidence_section = latest_section(
                ticket.body, REVIEW_SECTION_RE, "review-ready"
            )
        if section_value(evidence_section, "Run") != run_id:
            raise TrackerError("review evidence belongs to another run")
        if section_value(evidence_section, "Branch") != branch:
            raise TrackerError("review evidence belongs to another branch")
        if section_value(evidence_section, "Commit") != commit:
            raise TrackerError("commit does not match the reviewed commit")
        updated = replace_status(ticket.body, "resolved")
        updated = append_comment(
            updated,
            f"Sandcastle resolution — {utc_now()}",
            [
                f"Run: `{run_id}`",
                f"Branch: `{branch}`",
                f"Commit: `{commit}`",
                f"Summary: {summary}",
            ],
        )
        atomic_write(ticket.path, updated)
        return parse_ticket(ticket.path).as_json()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list")

    view_parser = subparsers.add_parser("view")
    view_parser.add_argument("--id", required=True, type=int)

    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--id", type=int)
    claim_parser.add_argument("--run-id", required=True)
    claim_parser.add_argument("--branch", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--id", required=True, type=int)
    release_parser.add_argument("--run-id", required=True)
    release_parser.add_argument("--reason", required=True)

    block_parser = subparsers.add_parser("block")
    block_parser.add_argument("--id", required=True, type=int)
    block_parser.add_argument("--run-id", required=True)
    block_parser.add_argument("--branch", required=True)
    block_parser.add_argument("--reason", required=True)

    review_parser = subparsers.add_parser("review-ready")
    review_parser.add_argument("--id", required=True, type=int)
    review_parser.add_argument("--run-id", required=True)
    review_parser.add_argument("--branch", required=True)
    review_parser.add_argument("--commit", required=True)
    review_parser.add_argument("--model", required=True)
    review_parser.add_argument("--summary", required=True)

    integrate_parser = subparsers.add_parser("integrate")
    integrate_parser.add_argument("--id", required=True, type=int)
    integrate_parser.add_argument("--run-id", required=True)
    integrate_parser.add_argument("--branch", required=True)
    integrate_parser.add_argument("--integration-branch", required=True)
    integrate_parser.add_argument("--commit", required=True)
    integrate_parser.add_argument("--summary", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--id", required=True, type=int)
    resolve_parser.add_argument("--run-id", required=True)
    resolve_parser.add_argument("--branch", required=True)
    resolve_parser.add_argument("--commit", required=True)
    resolve_parser.add_argument("--summary", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    try:
        if args.command == "list":
            result = list_frontier(root)
        elif args.command == "view":
            ticket = load_tickets(root).get(args.id)
            if ticket is None:
                raise TrackerError(f"ticket {args.id} does not exist")
            result = ticket.as_json()
        elif args.command == "claim":
            result = claim(root, args.id, args.run_id, args.branch)
        elif args.command == "release":
            result = release(root, args.id, args.run_id, args.reason)
        elif args.command == "block":
            result = block(
                root,
                args.id,
                args.run_id,
                args.branch,
                args.reason,
            )
        elif args.command == "review-ready":
            result = review_ready(
                root,
                args.id,
                args.run_id,
                args.branch,
                args.commit,
                args.model,
                args.summary,
            )
        elif args.command == "integrate":
            result = integrate(
                root,
                args.id,
                args.run_id,
                args.branch,
                args.integration_branch,
                args.commit,
                args.summary,
            )
        elif args.command == "resolve":
            result = resolve(
                root,
                args.id,
                args.run_id,
                args.branch,
                args.commit,
                args.summary,
            )
        else:
            raise AssertionError(args.command)
    except TrackerError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
