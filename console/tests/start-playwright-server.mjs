import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const testDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(testDirectory, "..", "..");
const artifactRoot = mkdtempSync(
  join(tmpdir(), "science-environment-playwright-"),
);

const python = resolve(repositoryRoot, ".venv", "bin", "python");
const server = spawn(
  python,
  ["-m", "studio", "--port", "8000", "--artifact-root", artifactRoot],
  {
    cwd: repositoryRoot,
    stdio: "inherit",
  },
);

let shuttingDown = false;
function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  server.kill(signal);
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown(signal));
}

server.on("exit", (code, signal) => {
  rmSync(artifactRoot, { force: true, recursive: true });
  if (signal) {
    process.removeAllListeners(signal);
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 1);
  }
});
