import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { acquireRunnerLock } from "../afk_control.ts";
import {
  advanceIntegrationBranch,
  compareTestSnapshots,
  compareTestSnapshotsAfterRetry,
  extractReviewFeedback,
  parseUnittestSnapshot,
  positiveInteger,
  prepareIntegrationBranch,
  requireExecutionProfile,
  restoreIntegrationBranch,
} from "../orchestration.ts";

function runProcess(
  command: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolveResult) => {
    const child = spawn(command, args, { cwd, env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => resolveResult({ code, stdout, stderr }));
  });
}

test("AFK profile requires gpt-5.6-sol with high effort", () => {
  assert.deepEqual(requireExecutionProfile(), {
    model: "gpt-5.6-sol",
    effort: "high",
  });
  assert.throws(() => requireExecutionProfile("gpt-5.4", "high"));
  assert.throws(() => requireExecutionProfile("gpt-5.6-sol", "medium"));
});

test("positive integer config is strict", () => {
  assert.equal(positiveInteger(undefined, 2, "ROUNDS"), 2);
  assert.equal(positiveInteger("3", 2, "ROUNDS"), 3);
  assert.throws(() => positiveInteger("0", 2, "ROUNDS"));
  assert.throws(() => positiveInteger("1.5", 2, "ROUNDS"));
});

test("review feedback uses the bounded tagged payload", () => {
  const output =
    "preamble\n<review-feedback>\nFix the signature.\n</review-feedback>\ntrailer";
  assert.equal(extractReviewFeedback(output), "Fix the signature.");
  assert.equal(extractReviewFeedback("abcdef", 3), "abc");
});

test("candidate tests may remove baseline failures but cannot add failures", () => {
  const baseline = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... FAIL",
      "FAIL: test_existing (tests.TestCase.test_existing)",
      "Ran 1 test in 1.0s",
      "FAILED (failures=1)",
    ].join("\n"),
  );
  const candidate = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... ok",
      "test_added (tests.TestCase.test_added) ... ok",
      "Ran 2 tests in 1.0s",
      "OK",
    ].join("\n"),
  );
  compareTestSnapshots(baseline, candidate);

  const regression = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... ok",
      "test_new (tests.TestCase.test_new) ... FAIL",
      "FAIL: test_new (tests.TestCase.test_new)",
      "Ran 2 tests in 1.0s",
      "FAILED (failures=1)",
    ].join("\n"),
  );
  assert.throws(() => compareTestSnapshots(baseline, regression));
});

test("a candidate-only failure must repeat before the host gate blocks", () => {
  const baseline = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... ok",
      "Ran 1 test in 1.0s",
      "OK",
    ].join("\n"),
  );
  const failed = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... FAIL",
      "FAIL: test_existing (tests.TestCase.test_existing)",
      "Ran 1 test in 1.0s",
      "FAILED (failures=1)",
    ].join("\n"),
  );
  const passed = parseUnittestSnapshot(
    [
      "test_existing (tests.TestCase.test_existing) ... ok",
      "Ran 1 test in 1.0s",
      "OK",
    ].join("\n"),
  );

  assert.deepEqual(
    compareTestSnapshotsAfterRetry(baseline, failed, passed),
    ["test_existing (tests.TestCase.test_existing)"],
  );
  assert.throws(() =>
    compareTestSnapshotsAfterRetry(baseline, failed, failed),
  );
});

test("verification output must include a unittest count", () => {
  assert.throws(() => parseUnittestSnapshot("python crashed"));
  assert.throws(() => parseUnittestSnapshot("Ran 1 test in 1.0s\nOK"));
});

test("AFK integration advances its branch without moving main", () => {
  const repo = mkdtempSync(join(tmpdir(), "sandcastle-integration-"));
  const runGit = (...args: string[]) => {
    const result = spawnSync("git", args, { cwd: repo, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };

  try {
    runGit("init", "-b", "main");
    runGit("config", "user.name", "Sandcastle Test");
    runGit("config", "user.email", "sandcastle@example.invalid");
    writeFileSync(join(repo, "fixture.txt"), "base\n");
    runGit("add", "fixture.txt");
    runGit("commit", "-m", "base");
    const mainCommit = runGit("rev-parse", "main");

    assert.equal(
      prepareIntegrationBranch(repo, "codex/sandcastle-afk-integration"),
      mainCommit,
    );

    runGit("checkout", "-b", "ticket-20");
    writeFileSync(join(repo, "fixture.txt"), "ticket\n");
    runGit("commit", "-am", "ticket 20");
    const reviewedCommit = runGit("rev-parse", "HEAD");
    runGit("checkout", "main");

    assert.equal(
      advanceIntegrationBranch(
        repo,
        "codex/sandcastle-afk-integration",
        mainCommit,
        reviewedCommit,
      ),
      reviewedCommit,
    );
    assert.equal(runGit("rev-parse", "main"), mainCommit);
    assert.equal(
      runGit("rev-parse", "codex/sandcastle-afk-integration"),
      reviewedCommit,
    );
    assert.equal(
      restoreIntegrationBranch(
        repo,
        "codex/sandcastle-afk-integration",
        reviewedCommit,
        mainCommit,
      ),
      mainCommit,
    );
    assert.equal(
      runGit("rev-parse", "codex/sandcastle-afk-integration"),
      mainCommit,
    );
    assert.throws(() =>
      advanceIntegrationBranch(
        repo,
        "codex/sandcastle-afk-integration",
        reviewedCommit,
        reviewedCommit,
      ),
    );
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("AFK status is idle before a detached run starts", () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  try {
    const result = spawnSync(
      "npm",
      ["exec", "--", "tsx", ".sandcastle/afk_control.ts", "status"],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), { status: "idle" });
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("AFK start returns while the detached worker keeps running", () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  const tsxPath = resolve("node_modules/.bin/tsx");
  writeFileSync(
    join(temp, "package.json"),
    JSON.stringify({
      private: true,
      scripts: {
        "sandcastle:run": 'node -e "setTimeout(() => {}, 30000)"',
      },
    }),
  );
  let workerPid: number | undefined;
  try {
    const startedAt = Date.now();
    const result = spawnSync(
      tsxPath,
      [resolve(".sandcastle/afk_control.ts"), "start"],
      {
        cwd: temp,
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    const elapsed = Date.now() - startedAt;
    assert.equal(result.status, 0, result.stderr);
    const state = JSON.parse(result.stdout);
    workerPid = state.pid;
    assert.equal(state.status, "running");
    assert.ok(elapsed < 5_000, `detached start took ${elapsed}ms`);
  } finally {
    if (workerPid) {
      try {
        process.kill(-workerPid, "SIGTERM");
      } catch {
        // The short-lived fixture may already have exited.
      }
    }
    rmSync(temp, { recursive: true, force: true });
  }
});

test("concurrent AFK starts launch only one detached worker", async () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  const tsxPath = resolve("node_modules/.bin/tsx");
  writeFileSync(
    join(temp, "package.json"),
    JSON.stringify({
      private: true,
      scripts: {
        "sandcastle:run": 'node -e "setTimeout(() => {}, 30000)"',
      },
    }),
  );
  const runStart = () =>
    runProcess(
      tsxPath,
      [resolve(".sandcastle/afk_control.ts"), "start"],
      temp,
      { ...process.env, SANDCASTLE_STATE_FILE: statePath },
    );

  let workerPid: number | undefined;
  try {
    const results = await Promise.all([runStart(), runStart()]);
    assert.deepEqual(
      results.map((result) => result.code).sort(),
      [0, 2],
      results.map((result) => result.stderr).join("\n"),
    );
    const state = JSON.parse(readFileSync(statePath, "utf8"));
    workerPid = state.pid;
    assert.equal(state.status, "running");
  } finally {
    if (workerPid) {
      try {
        process.kill(-workerPid, "SIGTERM");
      } catch {
        // The short-lived fixture may already have exited.
      }
    }
    rmSync(temp, { recursive: true, force: true });
  }
});

test("concurrent starts never recover and replace a stale state lock", async () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  const lockPath = `${statePath}.start.lock`;
  const tsxPath = resolve("node_modules/.bin/tsx");
  writeFileSync(
    lockPath,
    JSON.stringify({
      pid: 2147483647,
      token: "stale-token",
      acquiredAt: "2026-07-30T00:00:00.000Z",
    }),
  );
  try {
    const runStart = () =>
      runProcess(
        tsxPath,
        [resolve(".sandcastle/afk_control.ts"), "start"],
        temp,
        { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      );
    const results = await Promise.all([runStart(), runStart()]);
    assert.deepEqual(
      results.map((result) => result.code),
      [2, 2],
    );
    assert.equal(existsSync(statePath), false);
    assert.equal(JSON.parse(readFileSync(lockPath, "utf8")).token, "stale-token");
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("an immediate worker result cannot be overwritten back to running", async () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  const workerPath = join(temp, "worker.ts");
  const tsxPath = resolve("node_modules/.bin/tsx");
  const controlUrl = pathToFileURL(
    resolve(".sandcastle/afk_control.ts"),
  ).href;
  writeFileSync(
    workerPath,
    [
      `import { publishAfkResult } from ${JSON.stringify(controlUrl)};`,
      'publishAfkResult("batch-review-ready", { ok: true });',
    ].join("\n"),
  );
  writeFileSync(
    join(temp, "package.json"),
    JSON.stringify({
      private: true,
      scripts: {
        "sandcastle:run": `"${tsxPath}" "${workerPath}"`,
      },
    }),
  );
  try {
    const startResult = spawnSync(
      tsxPath,
      [resolve(".sandcastle/afk_control.ts"), "start"],
      {
        cwd: temp,
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(startResult.status, 0, startResult.stderr);
    const statusResult = spawnSync(
      tsxPath,
      [resolve(".sandcastle/afk_control.ts"), "status"],
      {
        cwd: temp,
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(statusResult.status, 0, statusResult.stderr);
    let state = JSON.parse(readFileSync(statePath, "utf8"));
    for (
      let attempt = 0;
      attempt < 100 && ["launching", "running"].includes(state.status);
      attempt++
    ) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 25));
      state = JSON.parse(readFileSync(statePath, "utf8"));
    }
    assert.equal(state.status, "batch-review-ready");
    await new Promise((resolveWait) => setTimeout(resolveWait, 50));
    assert.equal(
      JSON.parse(readFileSync(statePath, "utf8")).status,
      "batch-review-ready",
    );
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("the host runner lock allows only one orchestration process", () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-runner-lock-"));
  const lockPath = join(temp, "runner.lock");
  try {
    const release = acquireRunnerLock(lockPath);
    assert.throws(
      () => acquireRunnerLock(lockPath),
      /another Sandcastle runner owns/,
    );
    release();
    const releaseAfter = acquireRunnerLock(lockPath);
    releaseAfter();
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("AFK status reports a dead detached worker instead of claiming it runs", () => {
  const temp = mkdtempSync(join(tmpdir(), "sandcastle-control-"));
  const statePath = join(temp, "state.json");
  writeFileSync(
    statePath,
    JSON.stringify({
      schemaVersion: 1,
      status: "running",
      pid: 2147483647,
      runId: "test-run",
      startedAt: "2026-07-30T00:00:00.000Z",
      logPath: join(temp, "run.log"),
    }),
  );
  try {
    const result = spawnSync(
      "npm",
      ["exec", "--", "tsx", ".sandcastle/afk_control.ts", "status"],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(result.status, 2, result.stderr);
    assert.equal(JSON.parse(result.stdout).status, "crashed");
    const restart = spawnSync(
      "npm",
      ["exec", "--", "tsx", ".sandcastle/afk_control.ts", "start"],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(restart.status, 2, restart.stderr);
    assert.equal(JSON.parse(restart.stdout).status, "crashed");
    const reset = spawnSync(
      "npm",
      ["exec", "--", "tsx", ".sandcastle/afk_control.ts", "reset"],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        env: { ...process.env, SANDCASTLE_STATE_FILE: statePath },
      },
    );
    assert.equal(reset.status, 0, reset.stderr);
    assert.deepEqual(JSON.parse(reset.stdout), { status: "idle" });
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});
