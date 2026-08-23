import { expect, test } from "@playwright/test";

test("launches, polls, and inspects evaluation evidence through the real loopback API", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const resetResponse = await fetch(
    "http://127.0.0.1:8001/reset-model-script",
    { method: "POST" },
  );
  expect(resetResponse.status).toBe(204);
  let progressRequestFailures = 0;
  page.on("requestfailed", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      request.method() === "GET"
      && /^\/api\/evaluations\/evaluation-[0-9a-f]{32}$/.test(pathname)
    ) {
      progressRequestFailures += 1;
    }
  });
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  await expect(page.getByTestId("evaluation-workspace")).toContainText(
    "Base Gemma development calibration",
  );
  await expect(page.getByTestId("evaluation-list")).toContainText(
    "No local evaluation has been reserved yet.",
  );

  const launchRequest = page.waitForRequest((request) => (
    new URL(request.url()).pathname === "/api/evaluations"
    && request.method() === "POST"
  ));
  const launchResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/api/evaluations"
    && response.request().method() === "POST"
  ));
  await page.getByTestId("launch-evaluation").click();

  const launchedRequest = await launchRequest;
  expect(launchedRequest.postDataJSON()).toEqual({
    profile: "base-gemma-development-v1",
  });
  expect((await launchedRequest.allHeaders()).cookie).toMatch(
    /(?:^|;\s*)science_studio_session=/,
  );
  const launchedResponse = await launchResponse;
  expect(launchedResponse.status()).toBe(202);
  const launched = await launchedResponse.json() as { evaluation_id: string };
  await expect(page.getByTestId("evaluation-progress-message")).toContainText(
    /Ready to evaluate|Evaluated \d+ of 32|Completed all 32/,
  );
  await expect(page.getByTestId("evaluation-progress-message")).toHaveText(
    /Evaluated [1-9]\d* of 32 development scenarios\./,
  );

  const restartResponse = await fetch(
    "http://127.0.0.1:8001/restart-studio",
    { method: "POST" },
  );
  expect(restartResponse.status).toBe(204);
  await expect(page.getByTestId("evaluation-progress-message")).toContainText(
    "Evaluation stopped before all scenarios finished",
    { timeout: 15_000 },
  );
  expect(progressRequestFailures).toBeGreaterThan(0);
  await expect(page.getByTestId("resume-evaluation")).toBeVisible();

  const holdResumeResponse = await fetch(
    "http://127.0.0.1:8001/hold-resume-transition",
    {
      body: JSON.stringify({ evaluation_id: launched.evaluation_id }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );
  expect(holdResumeResponse.status).toBe(204);

  const resumeRequest = page.waitForRequest((request) => (
    new URL(request.url()).pathname
      === `/api/evaluations/${launched.evaluation_id}/resume`
    && request.method() === "POST"
  ));
  const resumeResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname
      === `/api/evaluations/${launched.evaluation_id}/resume`
    && response.request().method() === "POST"
  ));
  const interruptedProgress = () => page.waitForResponse(async (response) => (
    new URL(response.url()).pathname
      === `/api/evaluations/${launched.evaluation_id}`
    && response.request().method() === "GET"
    && response.status() === 200
    && (await response.json() as { status: string }).status === "interrupted"
  ), { timeout: 3_000 });
  try {
    const firstInterruptedPoll = interruptedProgress();
    await page.getByTestId("resume-evaluation").click();
    await resumeRequest;
    expect((await resumeResponse).status()).toBe(202);
    await firstInterruptedPoll;
    await interruptedProgress();
  } finally {
    const releaseResumeResponse = await fetch(
      "http://127.0.0.1:8001/release-resume-transition",
      { method: "POST" },
    );
    expect(releaseResumeResponse.status).toBe(204);
  }

  await expect(page.getByTestId("evaluation-progress-message")).toHaveText(
    "Completed all 32 development scenarios: 1 scientific success, "
      + "2 scientific failures, and 29 infrastructure errors.",
    { timeout: 60_000 },
  );
  await expect(page.getByTestId("resume-evaluation")).toHaveCount(0);

  await expect(page.getByTestId("evaluation-scientific-successes")).toContainText("1");
  await expect(page.getByTestId("evaluation-scientific-failures")).toContainText("2");
  await expect(page.getByTestId("evaluation-infrastructure-errors")).toContainText("29");
  await expect(page.getByTestId("evaluation-attempts")).toContainText("attempt-0001");
  await expect(page.getByTestId("evaluation-calibration")).toContainText(
    "Not ready for training",
  );
  await expect(page.getByTestId("evaluation-calibration")).toContainText(
    "33% scientific accuracy",
  );
  await expect(page.getByTestId("evaluation-calibration")).toContainText(
    "Authenticated local runtime",
  );
  await expect(page.getByTestId("evaluation-calibration-levels")).toContainText(
    "Level 1",
  );
  await expect(page.getByTestId("evaluation-calibration-levels")).toContainText(
    "Level 2",
  );

  await page.getByTestId("replay-attempt-0008").click();
  await expect(page.getByTestId("evaluation-replay")).toContainText(
    "Trace and scientific result both match",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-events")).toContainText(
    "Observation",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-events")).toContainText(
    "Action",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-events")).toContainText(
    "Transition",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-events")).toContainText(
    "Verifier",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "assistant",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "inspect_configuration",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "Canonical ordinal 1: episode-call-000001",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "Provider: call-1",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "Response turn 1: response-8-1",
  );
  await expect(page.getByTestId("evaluation-replay-interaction")).toContainText(
    "Result: ok",
  );
  await expect(page.getByTestId("evaluation-replay-budget")).toContainText(
    "900 seconds",
  );
  await expect(page.getByTestId("evaluation-replay-executions")).toContainText(
    "Canonical: episode-call-000001",
  );
  await expect(page.getByTestId("evaluation-replay-executions")).toContainText(
    "Cache: miss · Retries: 0",
  );
  await expect(page.getByTestId("evaluation-replay-executions")).toContainText(
    /Execution: sha256:[0-9a-f]{64}/,
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "science-local-gemma-runtime-cp312-cu129/1",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "CPython 3.12 · cp312 · linux-x86_64",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "6 directly verified serving distributions",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "torch 2.11.0+cu129",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "vllm 0.26.0+cu129",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "science-environment-studio 0.1.0",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "kernel-read-only-mount",
  );
  await expect(page.getByTestId("evaluation-replay-runtime-attestation")).toContainText(
    "pre-exec service envelope",
  );

  await page.getByTestId("replay-attempt-0010").click();
  await expect(page.getByTestId("evaluation-replay")).toContainText(
    "Trace and scientific result both match",
  );
  await expect(page.getByTestId("evaluation-replay-responses")).toContainText(
    "Finish: length",
  );
  await expect(page.getByTestId("evaluation-replay-responses")).toContainText(
    "Tokens: 2058",
  );

  await expect(page.getByText("Policy agent", { exact: true })).toBeVisible();
  await expect(page.getByTestId("action-picker")).toHaveCount(0);
  await expect(page.getByTestId("verify-run")).toHaveCount(0);
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("evaluation-replay")).toBeVisible();
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(1);
});
