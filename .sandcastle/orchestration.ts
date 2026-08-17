import { spawnSync } from "node:child_process";

export const REQUIRED_MODEL = "gpt-5.6-sol";
export const REQUIRED_EFFORT = "high";
export const IMPLEMENTED = "<promise>IMPLEMENTED</promise>";
export const IMPLEMENTATION_BLOCKED = "<promise>BLOCKED</promise>";
export const REVIEW_PASS = "<promise>REVIEW_PASS</promise>";
export const REVIEW_FAIL = "<promise>REVIEW_FAIL</promise>";

export type TestSnapshot = {
  count: number;
  testIds: string[];
  failures: string[];
  output: string;
};

function git(cwd: string, args: string[], acceptedStatuses = [0]): string {
  const result = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (!acceptedStatuses.includes(result.status ?? -1)) {
    throw new Error(
      `git ${args.join(" ")} failed: ${result.stderr.trim() || result.stdout.trim()}`,
    );
  }
  return result.stdout.trim();
}

function isAncestor(cwd: string, ancestor: string, descendant: string): boolean {
  const result = spawnSync(
    "git",
    ["merge-base", "--is-ancestor", ancestor, descendant],
    { cwd, encoding: "utf8" },
  );
  if (result.status === 0) return true;
  if (result.status === 1) return false;
  throw new Error(
    `git merge-base failed: ${result.stderr.trim() || result.stdout.trim()}`,
  );
}

function requireIntegrationBranchName(cwd: string, branch: string): void {
  git(cwd, ["check-ref-format", "--branch", branch]);
  if (branch === "main" || !branch.startsWith("codex/")) {
    throw new Error(
      `AFK integration branch must use the codex/ prefix and cannot be main: ${branch}`,
    );
  }
}

export function prepareIntegrationBranch(
  cwd: string,
  branch: string,
): string {
  requireIntegrationBranchName(cwd, branch);
  const mainCommit = git(cwd, ["rev-parse", "main"]);
  const ref = `refs/heads/${branch}`;
  const exists = spawnSync(
    "git",
    ["show-ref", "--verify", "--quiet", ref],
    { cwd, encoding: "utf8" },
  );
  if (exists.status !== 0 && exists.status !== 1) {
    throw new Error(
      `git show-ref failed: ${exists.stderr.trim() || exists.stdout.trim()}`,
    );
  }
  if (exists.status === 1) {
    git(cwd, ["update-ref", ref, mainCommit]);
    return mainCommit;
  }

  const current = git(cwd, ["rev-parse", branch]);
  if (current === mainCommit || isAncestor(cwd, mainCommit, current)) {
    return current;
  }
  if (isAncestor(cwd, current, mainCommit)) {
    git(cwd, ["update-ref", ref, mainCommit, current]);
    return mainCommit;
  }
  throw new Error(
    `AFK integration branch ${branch} diverged from main; review it before continuing`,
  );
}

export function advanceIntegrationBranch(
  cwd: string,
  branch: string,
  expectedCommit: string,
  reviewedCommit: string,
): string {
  requireIntegrationBranchName(cwd, branch);
  const current = git(cwd, ["rev-parse", branch]);
  if (current !== expectedCommit) {
    throw new Error(
      `AFK integration branch moved during the run: expected ${expectedCommit}, found ${current}`,
    );
  }
  if (!isAncestor(cwd, expectedCommit, reviewedCommit)) {
    throw new Error(
      `reviewed commit ${reviewedCommit} is not a descendant of ${expectedCommit}`,
    );
  }
  git(cwd, [
    "update-ref",
    `refs/heads/${branch}`,
    reviewedCommit,
    expectedCommit,
  ]);
  return reviewedCommit;
}

export function restoreIntegrationBranch(
  cwd: string,
  branch: string,
  expectedCommit: string,
  restoredCommit: string,
): string {
  requireIntegrationBranchName(cwd, branch);
  const current = git(cwd, ["rev-parse", branch]);
  if (current !== expectedCommit) {
    throw new Error(
      `AFK integration branch moved before rollback: expected ${expectedCommit}, found ${current}`,
    );
  }
  if (!isAncestor(cwd, restoredCommit, expectedCommit)) {
    throw new Error(
      `rollback target ${restoredCommit} is not an ancestor of ${expectedCommit}`,
    );
  }
  git(cwd, [
    "update-ref",
    `refs/heads/${branch}`,
    restoredCommit,
    expectedCommit,
  ]);
  return restoredCommit;
}

export function requireExecutionProfile(
  model = REQUIRED_MODEL,
  effort = REQUIRED_EFFORT,
): { model: typeof REQUIRED_MODEL; effort: typeof REQUIRED_EFFORT } {
  if (model !== REQUIRED_MODEL || effort !== REQUIRED_EFFORT) {
    throw new Error(
      `AFK runs require ${REQUIRED_MODEL} with ${REQUIRED_EFFORT} effort; ` +
        `received model=${model}, effort=${effort}`,
    );
  }
  return { model: REQUIRED_MODEL, effort: REQUIRED_EFFORT };
}

export function positiveInteger(
  value: string | undefined,
  fallback: number,
  name: string,
): number {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${name} must be a positive integer, received: ${value}`);
  }
  return parsed;
}

export function extractReviewFeedback(stdout: string, limit = 12_000): string {
  const match = stdout.match(
    /<review-feedback>\s*([\s\S]*?)\s*<\/review-feedback>/i,
  );
  const feedback = (match?.[1] || stdout).trim();
  if (!feedback) return "Reviewer requested changes without usable feedback.";
  return feedback.slice(0, limit);
}

export function parseUnittestSnapshot(output: string): TestSnapshot {
  const countMatches = [...output.matchAll(/^Ran (\d+) tests? in /gm)];
  const count = Number(countMatches.at(-1)?.[1]);
  if (!Number.isInteger(count)) {
    throw new Error("verification output did not contain a unittest test count");
  }
  const testIds = [...output.matchAll(/^(test[^\r\n]+) \.\.\. /gm)].map(
    (match) => match[1].trim(),
  );
  if (testIds.length !== count) {
    throw new Error(
      `verification output listed ${testIds.length} test ids but ran ${count}; ` +
        "VERIFY_COMMAND must use unittest verbose mode",
    );
  }
  const failures = [
    ...output.matchAll(/^(?:FAIL|ERROR): (.+)$/gm),
  ].map((match) => match[1].trim());
  return {
    count,
    testIds: [...new Set(testIds)].sort(),
    failures: [...new Set(failures)].sort(),
    output,
  };
}

export function compareTestSnapshots(
  baseline: TestSnapshot,
  candidate: TestSnapshot,
): void {
  if (candidate.count < baseline.count) {
    throw new Error(
      `candidate ran fewer tests than baseline (${candidate.count} < ${baseline.count})`,
    );
  }
  const candidateIds = new Set(candidate.testIds);
  const removed = baseline.testIds.filter((testId) => !candidateIds.has(testId));
  if (removed.length) {
    throw new Error(`candidate removed or renamed baseline tests: ${removed.join(", ")}`);
  }
  const baselineFailures = new Set(baseline.failures);
  const added = candidate.failures.filter((failure) => !baselineFailures.has(failure));
  if (added.length) {
    throw new Error(`candidate introduced test failures: ${added.join(", ")}`);
  }
}

export function compareTestSnapshotsAfterRetry(
  baseline: TestSnapshot,
  first: TestSnapshot,
  retry: TestSnapshot,
): string[] {
  if (
    first.count !== retry.count ||
    first.testIds.join("\n") !== retry.testIds.join("\n")
  ) {
    throw new Error("candidate retry changed the discovered test inventory");
  }
  const retryFailures = new Set(retry.failures);
  const persistentFailures = first.failures.filter((failure) =>
    retryFailures.has(failure),
  );
  compareTestSnapshots(baseline, {
    ...retry,
    failures: persistentFailures,
  });
  const persistent = new Set(persistentFailures);
  return [...new Set([...first.failures, ...retry.failures])]
    .filter((failure) => !persistent.has(failure))
    .sort();
}

export function runUnittestSnapshot(
  cwd: string,
  command: string,
): TestSnapshot {
  const result = spawnSync("/bin/zsh", ["-lc", command], {
    cwd,
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  const output = `${result.stdout || ""}\n${result.stderr || ""}`;
  const snapshot = parseUnittestSnapshot(output);
  if (result.status !== 0 && snapshot.failures.length === 0) {
    throw new Error(`verification command failed without test findings:\n${output}`);
  }
  return snapshot;
}

export function oneLine(value: string, limit = 500): string {
  return value.replace(/\s+/g, " ").trim().slice(0, limit);
}
