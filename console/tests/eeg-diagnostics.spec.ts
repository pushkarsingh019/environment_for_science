import { expect, test } from "@playwright/test";

import {
  applySimulatedAction,
  horizontalOverflowReport,
  startSeededRun,
  tabToTestId,
} from "./eeg-test-helpers";

const RECORDING_SITES = ["FC3", "FC4", "FT7", "FT8"];

test("supports an evidence-led targeted EEG recovery without revealing privileged causes", async ({
  page,
}) => {
  await startSeededRun(page);

  const diagnostic = page.getByTestId("eeg-diagnostic-visualization");
  await expect(diagnostic).toContainText("EEG diagnostic preflight");
  await expect(diagnostic).toContainText("Synthetic EEG apparatus simulation");

  const traceWindow = page.getByTestId("eeg-trace-window");
  await expect(traceWindow).toHaveAttribute(
    "aria-label",
    /Synthetic EEG window .*FC3, FC4, FT7, FT8 and reference comparison FCz.*96 displayed samples per trace.*current/,
  );
  await expect(traceWindow).toContainText("repeating logical sweep");
  await expect(page.getByTestId("trace-logical-sweep")).toHaveCSS(
    "animation-name",
    "eeg-logical-sweep",
  );
  await expect(page.getByTestId("trace-reference-FCz")).toHaveAttribute(
    "data-sample-count",
    "96",
  );
  const initialWindowId = await traceWindow.getAttribute("data-window-id");
  for (const site of RECORDING_SITES) {
    await expect(page.getByTestId(`trace-channel-${site}`)).toHaveAttribute(
      "data-sample-count",
      "96",
    );
    await expect(page.getByTestId(`montage-site-${site}`)).toHaveAttribute(
      "data-role",
      "required",
    );
  }
  await expect(page.getByTestId("montage-site-FCz")).toHaveAttribute(
    "data-role",
    "reference",
  );
  await expect(page.getByTestId("montage-site-A1")).toHaveAttribute(
    "data-role",
    "ground",
  );
  await expect(page.getByTestId("eeg-montage")).toHaveAttribute(
    "aria-label",
    /recording FC3, FC4, FT7, FT8; reference FCz; ground A1/,
  );
  await expect(page.locator("table.evidence-table")).toContainText(
    "Measurements derived from the displayed synthetic samples",
  );

  const initialVisibleText = (await page.locator("body").innerText()).toLowerCase();
  for (const privilegedName of [
    "case_id",
    "signal_profile",
    "effective_actions",
    "fault_family",
    "eeg-demo-001",
  ]) {
    expect(initialVisibleText).not.toContain(privilegedName);
  }

  await page.getByTestId("action-picker").selectOption("abort_preflight");
  const abortPath = page.getByTestId("action-target");
  const abortEvidence = page.getByTestId("action-evidence-reference");
  await expect(abortPath).toHaveJSProperty("tagName", "SELECT");
  await expect(abortEvidence).toHaveJSProperty("tagName", "SELECT");
  expect(await abortPath.locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value),
  )).toEqual(["", "eeg", "onset", "response", "recording"]);
  expect(await abortEvidence.locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value),
  )).toContain(initialWindowId);
  await abortPath.selectOption("eeg");
  await abortEvidence.selectOption(initialWindowId ?? "");
  await expect(page.getByTestId("apply-run-action")).toBeEnabled();
  await expect(page.getByTestId("run-status")).toContainText("Active run");

  await expect(page.getByTestId("frequency-disclosure")).toContainText(
    "Choose “View frequency evidence”",
  );
  await applySimulatedAction(page, "inspect_eeg_signals");
  await applySimulatedAction(page, "inspect_frequency_evidence");
  await expect(page.getByTestId("frequency-disclosure")).toHaveAttribute("open", "");
  for (const site of RECORDING_SITES) {
    await expect(page.getByTestId(`frequency-channel-${site}`)).toBeAttached();
  }
  await expect(page.getByTestId("frequency-reference-FCz")).toBeAttached();
  await expect(page.getByTestId("frequency-disclosure")).toContainText(
    "Bins: 2 Hz · 6 Hz · 10 Hz · 18 Hz · 26 Hz",
  );
  await expect(page.getByTestId("frequency-disclosure")).toContainText(
    "Mean absolute correlation with FCz reference comparison",
  );

  await page.getByRole("tab", { name: "Integrations" }).click();
  await expect(page.getByTestId("integration-timeline")).toBeVisible();
  for (const lane of [
    "timeline-recording-lane",
    "timeline-stimulus-lane",
    "timeline-onset-lane",
    "timeline-response-occurrence-lane",
    "timeline-response-identity-lane",
  ]) {
    await expect(page.getByTestId(lane)).toBeAttached();
  }
  await expect(page.getByTestId("integration-timeline")).toContainText(
    "Recording state",
  );
  await expect(page.getByTestId("integration-timeline")).toContainText(
    "Response occurrence",
  );
  await expect(page.getByTestId("marker-count")).toContainText(
    "1 at 112.3 ms",
  );
  await page.getByRole("tab", { name: "Signals" }).click();

  await applySimulatedAction(page, "reseat_electrode", { site: "FC3" });
  await expect(page.getByTestId("freshness-status")).toContainText("state r1");
  await expect(page.getByTestId("freshness-status")).toContainText("stale");
  await expect(traceWindow).toHaveAttribute("data-state-revision", "1");
  await expect(traceWindow).toHaveAttribute("data-evidence-revision", "0");
  await expect(traceWindow).toHaveAttribute("data-window-id", initialWindowId ?? "");

  await applySimulatedAction(page, "collect_fresh_eeg_window");
  await expect(page.getByTestId("freshness-status")).toContainText("current");
  await expect(traceWindow).toHaveAttribute("data-state-revision", "1");
  await expect(traceWindow).toHaveAttribute("data-evidence-revision", "1");
  expect(await traceWindow.getAttribute("data-window-id")).not.toBe(initialWindowId);
  await expect(page.getByTestId("frequency-disclosure")).toContainText(
    "Choose “View frequency evidence”",
  );

  await applySimulatedAction(page, "complete_preflight");
  await page.getByTestId("verify-run").click();
  const result = page.getByTestId("verifier-result");
  await expect(result).toContainText("Verifier passed");
  await expect(result).toContainText("targeted recovery");
  await expect(result).toContainText(
    "Preflight verified after targeted simulated recovery and fresh evidence",
  );
  await page.getByTestId("verifier-explanation").locator("summary").click();
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "No blocking reason was recorded",
  );
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "terminal correctness",
  );
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "fresh validation",
  );

  await page.getByTestId("replay-run").click();
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match",
  );
  await page.getByTestId("reset-run").click();
  await expect(page.getByTestId("eeg-trace-window")).toHaveAttribute(
    "data-window-id",
    initialWindowId ?? "",
  );
  await expect(page.getByTestId("run-status")).toContainText("Active run");
});

test("keeps diagnostic evidence and schema-driven actions keyboard-usable on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByTestId("mode-run").click();
  await tabToTestId(page, "start-run");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("trace-logical-sweep")).toHaveCSS(
    "animation-name",
    "none",
  );

  await tabToTestId(page, "action-picker");
  await page.keyboard.press("Home");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("apply-run-action")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("action-result")).toContainText(
    "inspected comparatively",
  );

  await tabToTestId(page, "action-picker");
  await page.getByTestId("action-picker").selectOption("inspect_frequency_evidence");
  await expect(page.getByTestId("action-picker")).toHaveValue(
    "inspect_frequency_evidence",
  );
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("apply-run-action")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("frequency-disclosure")).toContainText(
    "Bins: 2 Hz · 6 Hz · 10 Hz · 18 Hz · 26 Hz",
  );

  const integrationsTab = page.getByRole("tab", { name: "Integrations" });
  await integrationsTab.focus();
  await page.keyboard.press("Enter");
  await expect(integrationsTab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("integration-timeline")).toBeVisible();

  const overflow = await horizontalOverflowReport(page);
  expect(overflow.overflow, JSON.stringify(overflow, null, 2)).toBeLessThanOrEqual(1);
  for (const testId of ["eeg-diagnostic-visualization", "action-picker", "trace-list"]) {
    const bounds = await page.getByTestId(testId).boundingBox();
    expect(bounds?.width).toBeLessThanOrEqual(390);
  }
});
