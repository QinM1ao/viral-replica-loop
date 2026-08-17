import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

type AfkState = {
  schemaVersion: 1;
  status: string;
  pid?: number;
  runId?: string;
  startedAt?: string;
  completedAt?: string;
  logPath?: string;
  result?: unknown;
  reason?: string;
};

const repoRoot = process.cwd();
const defaultStatePath = resolve(repoRoot, ".sandcastle", "afk-state.json");
const defaultRunnerLockPath = resolve(
  repoRoot,
  ".sandcastle",
  "runner.lock",
);

type LockRecord = {
  pid: number;
  token: string;
  acquiredAt: string;
};

type CliResult = {
  state: unknown;
  exitCode: number;
};

function statePath(): string {
  return resolve(process.env.SANDCASTLE_STATE_FILE || defaultStatePath);
}

function runnerLockPath(): string {
  return resolve(
    process.env.SANDCASTLE_RUNNER_LOCK_FILE || defaultRunnerLockPath,
  );
}

function startLockPath(path = statePath()): string {
  return `${path}.start.lock`;
}

function readState(path = statePath()): AfkState | undefined {
  if (!existsSync(path)) return undefined;
  return JSON.parse(readFileSync(path, "utf8")) as AfkState;
}

function writeState(state: AfkState, path = statePath()): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  renameSync(temporary, path);
}

function processIsRunning(pid: number | undefined): boolean {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function readLock(path: string): LockRecord {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as LockRecord;
  } catch (error) {
    throw new Error(
      `cannot read Sandcastle lock ${path}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

function acquireFileLock(
  path: string,
  label: string,
  waitForLiveOwnerMs = 0,
): () => void {
  mkdirSync(dirname(path), { recursive: true });
  const deadline = Date.now() + waitForLiveOwnerMs;
  const waitBuffer = new Int32Array(new SharedArrayBuffer(4));
  while (true) {
    const token = randomUUID();
    let fd: number;
    try {
      fd = openSync(path, "wx");
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        error.code !== "EEXIST"
      ) {
        throw error;
      }
      let owner: LockRecord;
      try {
        owner = readLock(path);
      } catch (lockError) {
        if (Date.now() < deadline) {
          Atomics.wait(waitBuffer, 0, 0, 25);
          continue;
        }
        throw lockError;
      }
      if (!processIsRunning(owner.pid)) {
        throw new Error(
          `stale Sandcastle ${label} lock at ${path} belongs to dead pid ${owner.pid}; explicit recovery is required`,
        );
      }
      if (Date.now() < deadline) {
        Atomics.wait(waitBuffer, 0, 0, 25);
        continue;
      }
      throw new Error(
        `another Sandcastle ${label} owns ${path} with pid ${owner.pid}`,
      );
    }
    const record: LockRecord = {
      pid: process.pid,
      token,
      acquiredAt: new Date().toISOString(),
    };
    try {
      writeFileSync(fd, `${JSON.stringify(record)}\n`, "utf8");
    } catch (error) {
      closeSync(fd);
      unlinkSync(path);
      throw error;
    }
    closeSync(fd);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      try {
        if (readLock(path).token === token) unlinkSync(path);
      } catch {
        // A missing or replaced lock is not ours to remove.
      }
    };
  }
}

export function acquireRunnerLock(path = runnerLockPath()): () => void {
  return acquireFileLock(path, "runner");
}

function blockedExitCode(status: string): number {
  return ["failed", "attention-needed", "crashed"].includes(status) ? 2 : 0;
}

function start(): CliResult {
  const path = statePath();
  const releaseStateLock = acquireFileLock(
    startLockPath(path),
    "state",
    5_000,
  );
  try {
    const existing = readState(path);
    if (
      existing &&
      ["launching", "running"].includes(existing.status)
    ) {
      if (processIsRunning(existing.pid)) {
        return { state: existing, exitCode: 2 };
      }
      const crashed: AfkState = {
        ...existing,
        status: "crashed",
        completedAt: new Date().toISOString(),
        reason: "previous Sandcastle worker exited without publishing a result",
      };
      writeState(crashed, path);
      return { state: crashed, exitCode: 2 };
    }
    if (
      existing &&
      ["failed", "attention-needed", "crashed"].includes(existing.status)
    ) {
      return { state: existing, exitCode: 2 };
    }

    const runId =
      process.env.SANDCASTLE_RUN_ID ||
      `${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}-${randomUUID().slice(0, 8)}`;
    const logPath = resolve(
      repoRoot,
      ".sandcastle",
      "logs",
      `afk-${runId}.log`,
    );
    mkdirSync(dirname(logPath), { recursive: true });
    const launching: AfkState = {
      schemaVersion: 1,
      status: "launching",
      pid: process.pid,
      runId,
      startedAt: new Date().toISOString(),
      logPath,
    };
    writeState(launching, path);
    const logFd = openSync(logPath, "a");
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn("npm", ["run", "sandcastle:run"], {
        cwd: repoRoot,
        detached: true,
        stdio: ["ignore", logFd, logFd],
        env: {
          ...process.env,
          SANDCASTLE_STATE_FILE: path,
          SANDCASTLE_RUN_ID: runId,
          SANDCASTLE_LOG_PATH: logPath,
        },
      });
    } catch (error) {
      closeSync(logFd);
      const failed: AfkState = {
        ...launching,
        status: "failed",
        completedAt: new Date().toISOString(),
        reason: error instanceof Error ? error.message : String(error),
      };
      writeState(failed, path);
      return { state: failed, exitCode: 2 };
    }
    if (!child.pid) {
      closeSync(logFd);
      const failed: AfkState = {
        ...launching,
        status: "failed",
        completedAt: new Date().toISOString(),
        reason: "failed to start detached Sandcastle worker",
      };
      writeState(failed, path);
      return { state: failed, exitCode: 2 };
    }
    child.once("error", (error) => {
      const releaseErrorStateLock = acquireFileLock(
        startLockPath(path),
        "state",
        5_000,
      );
      try {
        const current = readState(path);
        if (
          current?.runId !== runId ||
          !["launching", "running"].includes(current.status)
        ) {
          return;
        }
        writeState(
          {
            ...current,
            status: "failed",
            completedAt: new Date().toISOString(),
            reason: error.message,
          },
          path,
        );
      } finally {
        releaseErrorStateLock();
      }
    });
    const current = readState(path);
    const running: AfkState =
      current?.runId === runId && current.status === "launching"
        ? { ...current, status: "running", pid: child.pid }
        : current || launching;
    if (running.status === "running") writeState(running, path);
    child.unref();
    closeSync(logFd);
    return { state: running, exitCode: blockedExitCode(running.status) };
  } finally {
    releaseStateLock();
  }
}

function status(): CliResult {
  const path = statePath();
  const releaseStateLock = acquireFileLock(
    startLockPath(path),
    "state",
    5_000,
  );
  try {
    const current = readState(path);
    if (!current) return { state: { status: "idle" }, exitCode: 0 };
    if (
      ["launching", "running"].includes(current.status) &&
      !processIsRunning(current.pid)
    ) {
      const crashed: AfkState = {
        ...current,
        status: "crashed",
        completedAt: new Date().toISOString(),
        reason: "detached Sandcastle worker exited without publishing a result",
      };
      writeState(crashed, path);
      return { state: crashed, exitCode: 2 };
    }
    return { state: current, exitCode: blockedExitCode(current.status) };
  } finally {
    releaseStateLock();
  }
}

function reset(): CliResult {
  const path = statePath();
  const releaseStateLock = acquireFileLock(
    startLockPath(path),
    "state",
    5_000,
  );
  try {
    const current = readState(path);
    if (
      current &&
      ["launching", "running"].includes(current.status) &&
      processIsRunning(current.pid)
    ) {
      return { state: current, exitCode: 2 };
    }
    const lockPath = runnerLockPath();
    if (existsSync(lockPath)) {
      const owner = readLock(lockPath);
      if (processIsRunning(owner.pid)) {
        return {
          state: {
            status: "running",
            reason: `Sandcastle runner lock is owned by pid ${owner.pid}`,
          },
          exitCode: 2,
        };
      }
      unlinkSync(lockPath);
    }
    if (existsSync(path)) unlinkSync(path);
    return { state: { status: "idle" }, exitCode: 0 };
  } finally {
    releaseStateLock();
  }
}

export function publishAfkResult(
  status: string,
  result: unknown,
  reason?: string,
): void {
  const path = process.env.SANDCASTLE_STATE_FILE;
  if (!path) return;
  const releaseStateLock = acquireFileLock(
    startLockPath(path),
    "state",
    5_000,
  );
  try {
    const runId = process.env.SANDCASTLE_RUN_ID;
    const current = readState(path);
    if (current && runId && current.runId !== runId) return;
    const owned = current || {
      schemaVersion: 1 as const,
      status: "running",
      pid: process.ppid,
      runId,
      startedAt: new Date().toISOString(),
      logPath: process.env.SANDCASTLE_LOG_PATH,
    };
    writeState(
      {
        ...owned,
        status,
        completedAt: new Date().toISOString(),
        result,
        ...(reason ? { reason } : {}),
      },
      path,
    );
  } finally {
    releaseStateLock();
  }
}

const isDirect =
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isDirect) {
  const command = process.argv[2];
  let result: CliResult | undefined;
  try {
    if (command === "start") result = start();
    if (command === "status") result = status();
    if (command === "reset") result = reset();
  } catch (error) {
    result = {
      state: {
        status: "rejected",
        reason: error instanceof Error ? error.message : String(error),
      },
      exitCode: 2,
    };
  }
  if (!result) {
    process.stderr.write("usage: afk_control.ts <start|status|reset>\n");
    process.exitCode = 2;
  } else {
    process.stdout.write(`${JSON.stringify(result.state, null, 2)}\n`);
    process.exitCode = result.exitCode;
  }
}
