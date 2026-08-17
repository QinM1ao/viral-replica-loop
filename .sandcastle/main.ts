import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";

import {
  codex,
  createSandbox,
  type Sandbox,
  type SandboxRunResult,
} from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import {
  IMPLEMENTATION_BLOCKED,
  IMPLEMENTED,
  REQUIRED_EFFORT,
  REQUIRED_MODEL,
  REVIEW_FAIL,
  REVIEW_PASS,
  advanceIntegrationBranch,
  compareTestSnapshots,
  compareTestSnapshotsAfterRetry,
  extractReviewFeedback,
  oneLine,
  positiveInteger,
  prepareIntegrationBranch,
  requireExecutionProfile,
  restoreIntegrationBranch,
  runUnittestSnapshot,
} from "./orchestration.ts";
import {
  acquireRunnerLock,
  publishAfkResult,
} from "./afk_control.ts";

type HostConfig = {
  TICKET_ROOT?: string;
  TICKET_ID?: string;
  CODEX_MODEL?: string;
  CODEX_EFFORT?: string;
  MAX_REPAIR_ROUNDS?: string;
  MAX_TICKETS?: string;
  INTEGRATION_BRANCH?: string;
  VERIFY_COMMAND?: string;
};

type Ticket = {
  id: number;
  title: string;
  body: string;
  status: string;
  blocked_by: number[];
  path: string;
  branch?: string;
  run_id?: string;
};

type TicketResult = {
  ticket: number;
  runId: string;
  branch: string;
  status: "afk-integrated" | "afk-blocked" | "transition-failed";
  reviewedCommit?: string;
  repairRounds: number;
  initialImplementLog?: string;
  repairLogs: string[];
  reviewLogs: string[];
  transientHostFailures?: string[];
  preservedWorktreePath?: string;
  reason?: string;
};

const repoRoot = process.cwd();
const sandcastleRoot = resolve(repoRoot, ".sandcastle");
const trackerPath = resolve(sandcastleRoot, "issue_tracker.py");

function parseEnvFile(path: string): HostConfig {
  if (!existsSync(path)) return {};
  const result: HostConfig = {};
  for (const rawLine of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const index = line.indexOf("=");
    if (index < 1) continue;
    const key = line.slice(0, index).trim() as keyof HostConfig;
    let value = line.slice(index + 1).trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

function tracker(root: string, args: string[]): unknown {
  const result = spawnSync(
    "python3",
    [trackerPath, "--root", root, ...args],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(
      `issue tracker failed (${args[0]}): ${result.stderr.trim() || result.stdout.trim()}`,
    );
  }
  return JSON.parse(result.stdout);
}

function required(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(
      `${name} is required; copy .sandcastle/host.env.example to .sandcastle/host.env`,
    );
  }
  return value;
}

function git(args: string[], cwd = repoRoot): string {
  const result = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `git ${args.join(" ")} failed: ${result.stderr.trim() || result.stdout.trim()}`,
    );
  }
  return result.stdout.trim();
}

async function sandboxGit(sandbox: Sandbox, args: string): Promise<string> {
  const result = await sandbox.exec(`git ${args}`);
  if (result.exitCode !== 0) {
    throw new Error(
      `sandbox git ${args} failed: ${result.stderr.trim() || result.stdout.trim()}`,
    );
  }
  return result.stdout.trim();
}

async function requireCleanSandbox(sandbox: Sandbox, phase: string): Promise<void> {
  const status = await sandboxGit(sandbox, "status --porcelain");
  if (status) {
    throw new Error(`${phase} left uncommitted changes: ${oneLine(status)}`);
  }
}

function createAgent() {
  return codex(REQUIRED_MODEL, {
    effort: REQUIRED_EFFORT,
    captureSessions: true,
  });
}

async function runImplementation(
  sandbox: Sandbox,
  claimed: Ticket,
  specBody: string,
  runId: string,
): Promise<SandboxRunResult> {
  const result = await sandbox.run({
    name: `ticket-${claimed.id}-implement`,
    maxIterations: 1,
    agent: createAgent(),
    promptFile: resolve(sandcastleRoot, "prompt.md"),
    promptArgs: {
      TICKET_ID: String(claimed.id),
      TICKET_BODY: claimed.body,
      SPEC_BODY: specBody,
    },
    completionSignal: [IMPLEMENTED, IMPLEMENTATION_BLOCKED],
    logging: {
      type: "file",
      path: `.sandcastle/logs/ticket-${claimed.id}-${runId}-implement.log`,
      verbose: true,
    },
    idleTimeoutSeconds: 900,
    completionTimeoutSeconds: 60,
  });
  if (result.completionSignal === IMPLEMENTATION_BLOCKED) {
    throw new Error("implementation agent reported a blocker");
  }
  if (result.completionSignal !== IMPLEMENTED || result.commits.length === 0) {
    throw new Error("implementation ended without IMPLEMENTED and a commit");
  }
  await requireCleanSandbox(sandbox, "implementation");
  return result;
}

async function runReviewer(
  sandbox: Sandbox,
  claimed: Ticket,
  specBody: string,
  baseCommit: string,
  runId: string,
  round: number,
): Promise<SandboxRunResult> {
  const beforeHead = await sandboxGit(sandbox, "rev-parse HEAD");
  const result = await sandbox.run({
    name: `ticket-${claimed.id}-review-${round}`,
    maxIterations: 1,
    agent: createAgent(),
    promptFile: resolve(sandcastleRoot, "review-prompt.md"),
    promptArgs: {
      TICKET_ID: String(claimed.id),
      TICKET_BODY: claimed.body,
      SPEC_BODY: specBody,
      BASE_COMMIT: baseCommit,
    },
    completionSignal: [REVIEW_PASS, REVIEW_FAIL],
    logging: {
      type: "file",
      path: `.sandcastle/logs/ticket-${claimed.id}-${runId}-review-${round}.log`,
      verbose: true,
    },
    idleTimeoutSeconds: 900,
    completionTimeoutSeconds: 60,
  });
  const afterHead = await sandboxGit(sandbox, "rev-parse HEAD");
  await requireCleanSandbox(sandbox, "reviewer");
  if (afterHead !== beforeHead) {
    throw new Error("read-only reviewer changed the branch");
  }
  if (result.completionSignal !== REVIEW_PASS && result.completionSignal !== REVIEW_FAIL) {
    throw new Error("reviewer ended without REVIEW_PASS or REVIEW_FAIL");
  }
  return result;
}

async function repairImplementation(
  sandbox: Sandbox,
  claimed: Ticket,
  baseCommit: string,
  repairRequest: string,
  runId: string,
  round: number,
): Promise<SandboxRunResult> {
  const beforeHead = await sandboxGit(sandbox, "rev-parse HEAD");
  const repaired = await sandbox.run({
    agent: createAgent(),
    maxIterations: 1,
    prompt: [
      "You are a fresh repair agent for one bounded AFK ticket.",
      `Ticket: ${claimed.id} — ${claimed.title}`,
      `Base commit: ${baseCommit}`,
      "Ticket contract:",
      claimed.body,
      "",
      "Read the current diff and fix only the findings below.",
      "Run focused tests, review the diff,",
      `and create a new commit whose subject starts with RALPH: ticket ${claimed.id}.`,
      "The macOS host runs the complete deterministic suite after independent review.",
      `Emit ${IMPLEMENTED} only when all findings are fixed; emit ${IMPLEMENTATION_BLOCKED} if genuinely blocked.`,
      "",
      repairRequest,
    ].join("\n"),
    name: `ticket-${claimed.id}-repair-${round}`,
    completionSignal: [IMPLEMENTED, IMPLEMENTATION_BLOCKED],
    logging: {
      type: "file",
      path: `.sandcastle/logs/ticket-${claimed.id}-${runId}-repair-${round}.log`,
      verbose: true,
    },
    idleTimeoutSeconds: 900,
    completionTimeoutSeconds: 60,
  });
  if (repaired.completionSignal === IMPLEMENTATION_BLOCKED) {
    throw new Error(`repair round ${round} reported a blocker`);
  }
  const afterHead = await sandboxGit(sandbox, "rev-parse HEAD");
  if (repaired.completionSignal !== IMPLEMENTED || afterHead === beforeHead) {
    throw new Error(`repair round ${round} ended without a new committed fix`);
  }
  await requireCleanSandbox(sandbox, `repair round ${round}`);
  return repaired;
}

function runHostGate(
  worktreePath: string,
  verifyCommand: string,
  baselineTests: ReturnType<typeof runUnittestSnapshot>,
): string[] {
  const candidateTests = runUnittestSnapshot(worktreePath, verifyCommand);
  try {
    compareTestSnapshots(baselineTests, candidateTests);
    return [];
  } catch {
    const retryTests = runUnittestSnapshot(worktreePath, verifyCommand);
    return compareTestSnapshotsAfterRetry(
      baselineTests,
      candidateTests,
      retryTests,
    );
  }
}

async function runBatch(): Promise<{
  summary: unknown;
  status: string;
  exitCode: number;
}> {
  const config = {
    ...parseEnvFile(resolve(sandcastleRoot, "host.env")),
    ...process.env,
  } as HostConfig;
  const ticketRoot = resolve(required(config.TICKET_ROOT, "TICKET_ROOT"));
  const profile = requireExecutionProfile(config.CODEX_MODEL, config.CODEX_EFFORT);
  const maxRepairs = positiveInteger(
    config.MAX_REPAIR_ROUNDS,
    2,
    "MAX_REPAIR_ROUNDS",
  );
  const maxTickets = positiveInteger(config.MAX_TICKETS, 10, "MAX_TICKETS");
  const verifyCommand = required(config.VERIFY_COMMAND, "VERIFY_COMMAND");
  const integrationBranch =
    config.INTEGRATION_BRANCH || "codex/sandcastle-afk-integration";

  if (process.argv.includes("--list")) {
    return {
      summary: tracker(ticketRoot, ["list"]),
      status: "frontier",
      exitCode: 0,
    };
  }

  if (git(["status", "--porcelain", "--untracked-files=no"])) {
    throw new Error(
      "host main worktree must have no tracked or staged changes before an AFK run",
    );
  }
  const hostCommit = git(["rev-parse", "HEAD"]);
  const mainCommit = git(["rev-parse", "main"]);
  if (hostCommit !== mainCommit) {
    throw new Error(
      `AFK run must start from main at ${mainCommit}; current HEAD is ${hostCommit}`,
    );
  }
  const specPath = resolve(ticketRoot, "..", "spec.md");
  const specBody = readFileSync(specPath, "utf8");
  const initialFrontier = tracker(ticketRoot, ["list"]) as Ticket[];
  if (initialFrontier.length === 0) {
    return {
      summary: { status: "empty", model: profile.model, results: [] },
      status: "empty",
      exitCode: 0,
    };
  }
  const baselineTests = runUnittestSnapshot(repoRoot, verifyCommand);
  let batchHead = prepareIntegrationBranch(repoRoot, integrationBranch);

  const requestedTicketId = config.TICKET_ID
    ? Number.parseInt(config.TICKET_ID, 10)
    : undefined;
  if (
    config.TICKET_ID &&
    (!Number.isInteger(requestedTicketId) || (requestedTicketId as number) < 1)
  ) {
    throw new Error(
      `TICKET_ID must be a positive integer, received: ${config.TICKET_ID}`,
    );
  }

  const results: TicketResult[] = [];
  const ticketLimit = requestedTicketId === undefined ? maxTickets : 1;

  for (let index = 0; index < ticketLimit; index++) {
    const frontier = tracker(ticketRoot, ["list"]) as Ticket[];
    if (frontier.length === 0) break;
    const ticketId = requestedTicketId ?? frontier[0].id;
    const runId = `${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}-${randomUUID().slice(0, 8)}`;
    const branch = `codex/ticket-${ticketId}-sandcastle-${runId.slice(-8)}`;
    const ticketBaseCommit = batchHead;
    const claimed = tracker(ticketRoot, [
      "claim",
      "--run-id",
      runId,
      "--branch",
      branch,
      "--id",
      String(ticketId),
    ]) as Ticket;

    let sandbox: Sandbox | undefined;
    let repairRounds = 0;
    let initialImplementLog: string | undefined;
    const repairLogs: string[] = [];
    const reviewLogs: string[] = [];
    let preservedWorktreePath: string | undefined;

    try {
      sandbox = await createSandbox({
        branch,
        baseBranch: ticketBaseCommit,
        sandbox: docker({
          mounts: [
            {
              hostPath: "~/.codex/auth.json",
              sandboxPath: "/home/agent/.codex/auth.json",
              readonly: true,
            },
            {
              hostPath: "~/.codex/skills/plugin-creator",
              sandboxPath: "/home/agent/.codex/skills/plugin-creator",
              readonly: true,
            },
          ],
          cpus: 4,
        }),
      });

      const implementation = await runImplementation(
        sandbox,
        claimed,
        specBody,
        runId,
      );
      initialImplementLog = implementation.logFilePath;
      let reviewRound = 1;
      let transientHostFailures: string[] = [];
      while (true) {
        const review = await runReviewer(
          sandbox,
          claimed,
          specBody,
          ticketBaseCommit,
          runId,
          reviewRound,
        );
        if (review.logFilePath) reviewLogs.push(review.logFilePath);

        let repairRequest: string | undefined;
        if (review.completionSignal === REVIEW_FAIL) {
          repairRequest = extractReviewFeedback(review.stdout);
        } else {
          try {
            transientHostFailures = runHostGate(
              sandbox.worktreePath,
              verifyCommand,
              baselineTests,
            );
          } catch (error) {
            repairRequest = [
              "The independent reviewer passed, but the deterministic macOS host gate failed twice.",
              "Fix only the persistent failures named below; do not change the gate or unrelated tests.",
              oneLine(error instanceof Error ? error.message : String(error), 4_000),
            ].join("\n");
          }
        }
        if (!repairRequest) {
          const reviewedCommit = await sandboxGit(sandbox, "rev-parse HEAD");
          const closeResult = await sandbox.close();
          sandbox = undefined;
          preservedWorktreePath = closeResult.preservedWorktreePath;
          if (preservedWorktreePath) {
            throw new Error("reviewed worktree remained dirty during cleanup");
          }

          tracker(ticketRoot, [
            "review-ready",
            "--id",
            String(claimed.id),
            "--run-id",
            runId,
            "--branch",
            branch,
            "--commit",
            reviewedCommit,
            "--model",
            profile.model,
            "--summary",
            `Independent review passed after ${repairRounds} repair round(s); ` +
              `host verification added no persistent failures and observed ` +
              `${transientHostFailures.length} transient failure(s).`,
          ]);
          batchHead = advanceIntegrationBranch(
            repoRoot,
            integrationBranch,
            ticketBaseCommit,
            reviewedCommit,
          );
          try {
            tracker(ticketRoot, [
              "integrate",
              "--id",
              String(claimed.id),
              "--run-id",
              runId,
              "--branch",
              branch,
              "--integration-branch",
              integrationBranch,
              "--commit",
              reviewedCommit,
              "--summary",
              "Automated implementation, independent review, and macOS host gate passed; final human review remains deferred to the integration branch.",
            ]);
          } catch (error) {
            try {
              batchHead = restoreIntegrationBranch(
                repoRoot,
                integrationBranch,
                reviewedCommit,
                ticketBaseCommit,
              );
            } catch (rollbackError) {
              throw new Error(
                `ticket integration record failed and Git rollback also failed: ${
                  rollbackError instanceof Error
                    ? rollbackError.message
                    : String(rollbackError)
                }; original error: ${
                  error instanceof Error ? error.message : String(error)
                }`,
              );
            }
            throw error;
          }
          results.push({
            ticket: claimed.id,
            runId,
            branch,
            status: "afk-integrated",
            reviewedCommit,
            repairRounds,
            transientHostFailures,
            initialImplementLog,
            repairLogs,
            reviewLogs,
          });
          break;
        }

        if (repairRounds >= maxRepairs) {
          throw new Error(`ticket still failed after ${maxRepairs} repair rounds`);
        }
        repairRounds += 1;
        const repaired = await repairImplementation(
          sandbox,
          claimed,
          ticketBaseCommit,
          repairRequest,
          runId,
          repairRounds,
        );
        if (repaired.logFilePath) repairLogs.push(repaired.logFilePath);
        reviewRound += 1;
      }
    } catch (error) {
      let cleanupError: unknown;
      if (sandbox) {
        try {
          const closeResult = await sandbox.close();
          preservedWorktreePath = closeResult.preservedWorktreePath;
        } catch (closeError) {
          cleanupError = closeError;
        }
      }
      const primaryReason = error instanceof Error ? error.message : String(error);
      const cleanupReason =
        cleanupError === undefined
          ? ""
          : `; cleanup also failed: ${
              cleanupError instanceof Error ? cleanupError.message : String(cleanupError)
            }`;
      const reason = oneLine(`${primaryReason}${cleanupReason}`);
      let transitionError: unknown;
      try {
        tracker(ticketRoot, [
          "block",
          "--id",
          String(claimed.id),
          "--run-id",
          runId,
          "--branch",
          branch,
          "--reason",
          reason,
        ]);
      } catch (blockError) {
        transitionError = blockError;
      }
      results.push({
        ticket: claimed.id,
        runId,
        branch,
        status: transitionError === undefined ? "afk-blocked" : "transition-failed",
        repairRounds,
        initialImplementLog,
        repairLogs,
        reviewLogs,
        preservedWorktreePath,
        reason:
          transitionError === undefined
            ? reason
            : `${reason}; tracker transition failed: ${oneLine(
                transitionError instanceof Error
                  ? transitionError.message
                  : String(transitionError),
              )}`,
      });
      break;
    }
  }

  const needsAttention = results.some(
    (result) =>
      result.status === "afk-blocked" || result.status === "transition-failed",
  );
  return {
    summary: {
      status: needsAttention ? "attention-needed" : "batch-review-ready",
      model: profile.model,
      effort: profile.effort,
      integrationBranch,
      integrationCommit: batchHead,
      reviewCommand: `git diff main...${integrationBranch}`,
      baselineTests: {
        count: baselineTests.count,
        existingFailures: baselineTests.failures,
      },
      results,
    },
    status: needsAttention ? "attention-needed" : "batch-review-ready",
    exitCode: needsAttention ? 2 : 0,
  };
}

let releaseRunnerLock: (() => void) | undefined;
try {
  if (!process.argv.includes("--list")) {
    releaseRunnerLock = acquireRunnerLock();
  }
  const outcome = await runBatch();
  process.stdout.write(`${JSON.stringify(outcome.summary, null, 2)}\n`);
  publishAfkResult(outcome.status, outcome.summary);
  process.exitCode = outcome.exitCode;
} catch (error) {
  const reason = oneLine(error instanceof Error ? error.message : String(error));
  const summary = { status: "failed", reason };
  process.stderr.write(`${JSON.stringify(summary, null, 2)}\n`);
  publishAfkResult("failed", summary, reason);
  process.exitCode = 2;
} finally {
  releaseRunnerLock?.();
}
