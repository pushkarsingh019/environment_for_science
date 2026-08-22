import { expect, type Page } from "@playwright/test";

export async function tabToTestId(
  page: Page,
  expected: string,
  maximumSteps = 60,
): Promise<void> {
  for (let step = 0; step < maximumSteps; step += 1) {
    await page.keyboard.press("Tab");
    const activeTestId = await page.evaluate(() =>
      document.activeElement?.getAttribute("data-testid"),
    );
    if (activeTestId === expected) return;
  }
  throw new Error(`Keyboard focus did not reach ${expected}`);
}

export async function startSeededRun(
  page: Page,
  exampleLabel = "Seeded example A",
): Promise<void> {
  await page.goto("/");
  await expect(page.getByTestId("draft-revision")).toHaveAttribute(
    "data-revision",
    /\d+/,
  );
  const restored = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith("/api/draft/restore") &&
      candidate.request().method() === "POST",
  );
  await page.getByTestId("restore-draft").click();
  expect((await restored).ok()).toBe(true);
  await expect(page.getByTestId("draft-busy")).toHaveCount(0);
  await page.getByTestId("mode-run").click();
  await expect(page.getByTestId("environment-validation")).toContainText(
    "Environment Bundle v1 validated",
  );
  await page.getByTestId("seeded-example-selector").selectOption({
    label: exampleLabel,
  });
  await page.getByTestId("start-run").click();
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("eeg-diagnostic-visualization")).toBeVisible();
  await expect(page.getByTestId("freshness-status")).toContainText("current");
}

export async function applySimulatedAction(
  page: Page,
  actionType: string,
  arguments_: Record<string, string> = {},
): Promise<void> {
  const picker = page.getByTestId("action-picker");
  await expect(picker).toBeEnabled();
  await picker.selectOption(actionType);

  for (const [name, value] of Object.entries(arguments_)) {
    const testId = name === "evidence_id"
      ? "action-evidence-reference"
      : ["site", "path", "source", "control"].includes(name)
        ? "action-target"
        : `action-argument-${name}`;
    const field = page.getByTestId(testId);
    if ((await field.evaluate((element) => element.tagName)) === "SELECT") {
      await field.selectOption(value);
    } else {
      await field.fill(value);
    }
  }

  const response = page.waitForResponse(
    (candidate) =>
      /\/api\/runs\/[^/]+\/actions$/.test(new URL(candidate.url()).pathname) &&
      candidate.request().method() === "POST",
  );
  await page.getByTestId("apply-run-action").click();
  const actionResponse = await response;
  expect(actionResponse.ok()).toBe(true);
  expect(actionResponse.request().postDataJSON()).toEqual({
    type: actionType,
    input: arguments_,
  });
  if (!["complete_preflight", "close_acquisition", "abort_episode"].includes(actionType)) {
    await expect(picker).toBeEnabled();
  } else {
    await expect(page.getByTestId("run-status")).toContainText(
      "Awaiting verification",
    );
  }
}

export async function horizontalOverflowReport(page: Page) {
  return page.evaluate(() => {
    const documentElement = document.documentElement;
    const viewportWidth = documentElement.clientWidth;
    const selectors = [
      '[data-testid="eeg-diagnostic-visualization"]',
      ".diagnostic-signal-layout",
      ".diagnostic-plots",
      '[data-testid="eeg-trace-window"]',
      '[data-testid="eeg-trace-window"] svg',
    ];
    const measurements = Object.fromEntries(
      selectors.map((selector) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return [selector, null];
        const bounds = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return [selector, {
          left: bounds.left,
          right: bounds.right,
          width: bounds.width,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          computedWidth: style.width,
          minWidth: style.minWidth,
          overflow: style.overflow,
          overflowX: style.overflowX,
        }];
      }),
    );
    return {
      documentWidth: documentElement.scrollWidth,
      viewportWidth,
      overflow: documentElement.scrollWidth - viewportWidth,
      measurements,
      offenders: Array.from(document.querySelectorAll<HTMLElement>("body *"))
        .map((element) => {
          const bounds = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            tag: element.tagName.toLowerCase(),
            className: element.className,
            testId: element.dataset.testid ?? null,
            left: bounds.left,
            right: bounds.right,
            width: bounds.width,
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
            minWidth: style.minWidth,
            overflowX: style.overflowX,
          };
        })
        .filter((item) => item.right > viewportWidth + 1 || item.left < -1)
        .slice(0, 20),
    };
  });
}

export async function inspectCurriculumGates(page: Page): Promise<void> {
  for (const action of [
    "inspect_configuration",
    "inspect_eeg_signals",
    "inspect_onset_route",
    "inspect_response_timeline",
    "inspect_recording_timeline",
  ]) {
    await applySimulatedAction(page, action);
  }
}

export async function completeNominalPreflight(page: Page): Promise<void> {
  await inspectCurriculumGates(page);
  await applySimulatedAction(page, "complete_preflight");
}

export async function recoverVisibleOnsetCue(page: Page): Promise<void> {
  await inspectCurriculumGates(page);
  await applySimulatedAction(page, "correct_trigger_visibility");
  await applySimulatedAction(page, "present_test_flash");
  await applySimulatedAction(page, "run_response_preflight");
  await applySimulatedAction(page, "complete_preflight");
}
