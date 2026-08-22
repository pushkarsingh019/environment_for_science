import { expect, test } from "@playwright/test";

import {
  applySimulatedAction,
  horizontalOverflowReport,
  inspectCurriculumGates,
  recoverVisibleOnsetCue,
  startSeededRun,
  tabToTestId,
} from "./eeg-test-helpers";

test("recovers, verifies, replays, and resets through the real runtime", async ({
  page,
}) => {
  await startSeededRun(page, "Seeded example B");

  const initialWindowId = await page
    .getByTestId("eeg-trace-window")
    .getAttribute("data-window-id");
  await recoverVisibleOnsetCue(page);
  await expect(page.getByTestId("run-status")).toContainText("Awaiting verification");
  await page.getByTestId("verify-run").click();

  await expect(page.getByTestId("verifier-result")).toContainText("Verifier passed");
  await expect(page.getByTestId("terminal-disposition")).toHaveText("Closed");
  await expect(page.getByTestId("outcome-category")).toHaveText("Individual");
  const traceRows = page.getByTestId("trace-list").locator("li");
  await expect(traceRows).toHaveCount(29);
  expect(
    await traceRows.evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-event-type")),
    ),
  ).toEqual([
    "observation",
    ...Array.from({ length: 9 }, () => [
      "action",
      "transition",
      "observation",
    ]).flat(),
    "verifier",
  ]);
  await expect(page.getByTestId("trace-list")).toContainText(
    "Correct trigger visibility",
  );
  await expect(page.getByTestId("trace-list")).toContainText(
    "Present test flash",
  );
  await expect(page.getByTestId("trace-list")).toContainText("stale");
  await expect(page.getByTestId("trace-list")).toContainText("current");

  await page.getByTestId("replay-run").click();
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match",
  );

  await page.getByTestId("reset-run").click();
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("freshness-status")).toContainText("current");
  await expect(page.getByTestId("eeg-trace-window")).toHaveAttribute(
    "data-window-id",
    initialWindowId ?? "",
  );
});

test("records an ineffective permitted action as a failed recovery", async ({ page }) => {
  await startSeededRun(page, "Seeded example B");

  await inspectCurriculumGates(page);
  await applySimulatedAction(page, "reseat_electrode", { site: "FC4" });
  await applySimulatedAction(page, "complete_preflight");
  await page.getByTestId("verify-run").click();

  await expect(page.getByTestId("verifier-result")).toContainText(
    "Verifier did not pass",
  );
  await expect(page.getByTestId("terminal-disposition")).toHaveText("Failed");
  await page.getByTestId("verifier-explanation").locator("summary").click();
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "terminal decision was not supported",
  );
  await expect(page.getByTestId("trace-list")).toContainText("site=FC4");
});

test("rejects stale evidence when remediation is not followed by a fresh window", async ({
  page,
}) => {
  await startSeededRun(page, "Seeded example B");
  await inspectCurriculumGates(page);
  await applySimulatedAction(page, "correct_trigger_visibility");
  await expect(page.getByTestId("domain-freshness-onset")).toHaveText("Stale");
  await expect(page.getByTestId("domain-freshness-response")).toHaveText("Stale");
  await applySimulatedAction(page, "complete_preflight");
  await page.getByTestId("verify-run").click();

  await expect(page.getByTestId("terminal-disposition")).toHaveText("Failed");
  await page.getByTestId("verifier-explanation").locator("summary").click();
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "terminal decision was not supported",
  );
});

test("keeps the run controls and evidence usable by keyboard at mobile width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByTestId("mode-run").click();
  await tabToTestId(page, "start-run");
  expect(
    await page.getByTestId("start-run").evaluate((element) =>
      element.matches(":focus-visible"),
    ),
  ).toBe(true);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run-status")).toContainText("Active run");

  await tabToTestId(page, "action-picker");
  expect(
    await page.getByTestId("action-picker").evaluate((element) =>
      element.matches(":focus-visible"),
    ),
  ).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("apply-run-action")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("action-result")).toContainText(
    "Inspected current configuration evidence",
  );

  const overflow = await horizontalOverflowReport(page);
  expect(overflow.overflow, JSON.stringify(overflow, null, 2)).toBeLessThanOrEqual(1);
  for (const testId of ["action-picker", "apply-run-action", "verify-run", "reset-run"]) {
    const bounds = await page.getByTestId(testId).boundingBox();
    expect(bounds?.height).toBeGreaterThanOrEqual(44);
    expect(bounds?.width).toBeLessThanOrEqual(370);
  }
  const traceBounds = await page.getByTestId("trace-list").boundingBox();
  expect(traceBounds?.width).toBeLessThanOrEqual(370);
});

test("matches the approved primary desktop and mobile console layouts", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await startSeededRun(page);
  await expect(page).toHaveScreenshot("ticket-01-desktop.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [page.getByTestId("frozen-draft-revision")],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page).toHaveScreenshot("ticket-01-mobile.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [page.getByTestId("frozen-draft-revision")],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });
});
