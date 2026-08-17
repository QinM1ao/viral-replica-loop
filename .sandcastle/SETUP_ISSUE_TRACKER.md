# Local Markdown issue tracker

The tracker is host-coordinated by `.sandcastle/issue_tracker.py`. Sandboxes do
not receive the private `.scratch` tree and cannot claim or close tickets.

## Configuration

Copy `.sandcastle/host.env.example` to the ignored `.sandcastle/host.env` and
set `TICKET_ROOT` to the migration `issues/` directory. `TICKET_ID` pins a
controlled run to one ticket. Omit it to process the dependency-ready frontier,
up to `MAX_TICKETS`.

Every implementation and independent review uses exactly `gpt-5.6-sol` with
`high` effort. The runner refuses weaker or different profiles instead of
falling back silently.

The automated lifecycle is:

1. atomically claim one dependency-ready ticket
2. implement and commit in an isolated branch/container
3. run a fresh, read-only independent reviewer
4. use a fresh bounded repair session for at most `MAX_REPAIR_ROUNDS`
5. rerun a fresh reviewer after every repair
6. compare the candidate host test result with the unchanged-main baseline,
   repairing only persistent failures
7. atomically advance `INTEGRATION_BRANCH` to the exact reviewed commit
8. mark the ticket `afk-integrated`, which unlocks its dependents without
   claiming that final human review has happened

The runner never changes `main`. It chains accepted tickets onto one
`codex/`-prefixed integration branch and may continue through up to
`MAX_TICKETS`, including dependency-linked tickets. When the batch returns
`batch-review-ready`, a human reviews `git diff main...<integration-branch>`,
merges that branch without squashing away its ancestry, and changes the
integrated tickets from `afk-integrated` to `resolved`. A blocked or ambiguous
run becomes `afk-blocked`; it never advances dependent tickets.

## Commands

```bash
npm run test:sandcastle
npm run sandcastle:list
npm run sandcastle:build
npm run sandcastle
npm run sandcastle:status
npm run sandcastle:reset
npm run sandcastle:run
```

`npm run sandcastle` starts a detached ordinary Node/Sandcastle worker and
returns immediately. The outer Codex task or terminal does not poll it.
`npm run sandcastle:status` reads the worker-owned state file on demand.
`npm run sandcastle:run` is the foreground form for CI or direct debugging;
the same host-wide lock prevents it from running beside the detached form.
Concurrent starts are rejected before a second agent batch can begin.

The tracker serializes updates with a host file lock, computes the frontier
from `Blocked by`, and permanently excludes tickets 41–43 from AFK claims.
The worker can run unattended. Review its final JSON state and files under
`.sandcastle/logs/` after `sandcastle:status` reports `batch-review-ready`.
`afk-integrated` means the internal implement/review/repair/host gates passed;
it is not the final merge authorization.
The host preflight refuses tracked or staged changes but allows untracked,
rebuildable test caches. If a process is forcibly killed before it can record a
terminal state, use the tracker `release` command with the latest Run value
recorded in that ticket, then run `npm run sandcastle:reset` before starting a
replacement run. `reset` refuses to clear a live worker or runner lock; it
never releases a ticket automatically. A stale state-lock error is not
auto-recovered: verify the reported PID is dead, remove the exact reported
`.start.lock` file, and rerun `sandcastle:reset`.
