import { expect, test } from "@playwright/test";

async function tabToTestId(
  page: import("@playwright/test").Page,
  expected: string,
): Promise<void> {
  for (let step = 0; step < 20; step += 1) {
    await page.keyboard.press("Tab");
    const activeTestId = await page.evaluate(() =>
      document.activeElement?.getAttribute("data-testid"),
    );
    if (activeTestId === expected) return;
  }
  throw new Error(`Keyboard focus did not reach ${expected}`);
}

async function startSeededRun(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("mode-run").click();
  await expect(page.getByTestId("environment-validation")).toContainText(
    "Environment Bundle v1 validated",
  );
  await page.getByTestId("start-run").click();
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("marker-count")).toHaveText("2 onset markers");
  await expect(page.getByTestId("apparatus-visualization")).toHaveAttribute(
    "aria-label",
    "Synthetic EEG apparatus display with one lower-right test flash and 2 onset markers. Evidence is current.",
  );
  const markerEvents = page.getByTestId("marker-event");
  await expect(markerEvents).toHaveCount(2);
  await expect(markerEvents.nth(0)).toHaveAttribute("data-position", "38%");
  await expect(markerEvents.nth(1)).toHaveAttribute("data-position", "45%");
  const actionButtons = page.locator('[data-testid^="action-"]');
  await expect(actionButtons).toHaveCount(4);
  expect(
    await actionButtons.evaluateAll((buttons) =>
      buttons.map((button) => button.getAttribute("data-testid")),
    ),
  ).toEqual([
    "action-inspect_onset_route",
    "action-repair_refractory_route",
    "action-present_test_flash",
    "action-restart_response_handshake",
  ]);
  await expect(page.locator("textarea, input[type=password], [contenteditable=true]")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("refractory_route_repaired");
}

test("recovers, verifies, replays, and resets through the real runtime", async ({
  page,
}) => {
  await startSeededRun(page);

  await page.getByTestId("action-inspect_onset_route").click();
  await expect(page.getByTestId("route-inspection")).toContainText("inspected");

  await page.getByTestId("action-repair_refractory_route").click();
  await expect(page.getByTestId("freshness-status")).toContainText("stale");

  await page.getByTestId("action-present_test_flash").click();
  await expect(page.getByTestId("marker-count")).toHaveText("1 onset marker");
  await expect(page.getByTestId("marker-event")).toHaveCount(1);
  await expect(page.getByTestId("marker-event")).toHaveAttribute(
    "data-position",
    "38%",
  );
  await expect(page.getByTestId("freshness-status")).toContainText("current");

  await page.getByTestId("verify-run").click();
  await expect(page.getByTestId("verifier-result")).toContainText(
    "Recovery verified",
  );
  const traceRows = page.getByTestId("trace-list").locator("li");
  await expect(traceRows).toHaveCount(11);
  expect(
    await traceRows.evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-event-type")),
    ),
  ).toEqual([
    "observation",
    "action",
    "transition",
    "observation",
    "action",
    "transition",
    "observation",
    "action",
    "transition",
    "observation",
    "verifier",
  ]);
  await expect(page.getByTestId("trace-list")).toContainText(
    "flash-001 · stale · evidence r0 → state r1",
  );
  await expect(page.getByTestId("trace-list")).toContainText(
    "flash-002 · current · state r1 · 1 marker",
  );

  await page.getByTestId("replay-run").click();
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match",
  );

  await page.getByTestId("reset-run").click();
  await expect(page.getByTestId("marker-count")).toHaveText("2 onset markers");
  await expect(page.getByTestId("freshness-status")).toContainText("current");
  await expect(page.getByTestId("run-status")).toContainText("Active run");
});

test("records an incorrect permitted action as a failed recovery", async ({ page }) => {
  await startSeededRun(page);

  await page.getByTestId("action-restart_response_handshake").click();
  await page.getByTestId("verify-run").click();

  await expect(page.getByTestId("verifier-result")).toContainText(
    "Recovery not verified",
  );
  await expect(page.getByTestId("marker-count")).toHaveText("2 onset markers");
  await expect(page.getByTestId("trace-list")).toContainText(
    "Restart simulated response handshake",
  );
});

test("rejects stale evidence when repair is not followed by a fresh flash", async ({
  page,
}) => {
  await startSeededRun(page);
  await page.getByTestId("action-inspect_onset_route").click();
  await page.getByTestId("action-repair_refractory_route").click();
  await expect(page.getByTestId("freshness-status")).toContainText("stale");

  await page.getByTestId("verify-run").click();

  await expect(page.getByTestId("verifier-result")).toContainText(
    "No current post-repair test-flash evidence was available",
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
  await expect(page.getByTestId("marker-count")).toHaveText("2 onset markers");

  await tabToTestId(page, "action-inspect_onset_route");
  expect(
    await page
      .getByTestId("action-inspect_onset_route")
      .evaluate((element) => element.matches(":focus-visible")),
  ).toBe(true);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("route-inspection")).toContainText("inspected");

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
  for (const button of await page.locator('[data-testid^="action-"]').all()) {
    const bounds = await button.boundingBox();
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
