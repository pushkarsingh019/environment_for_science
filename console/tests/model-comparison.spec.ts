import { expect, test } from "@playwright/test";

import { horizontalOverflowReport } from "./eeg-test-helpers";

test("compares four models with bounded claims, failures, replays, and separate mesoscope evidence", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("model-comparison-panel");
  await expect(panel.getByTestId("comparison-fixture-notice")).toContainText(
    "not a live provider or training result",
  );
  await expect(panel.getByTestId("comparison-model-openai_reference")).toContainText(
    "Reference model",
  );
  await expect(panel.getByTestId("comparison-claim-improved")).toContainText(
    "95% paired bootstrap interval",
  );

  await panel.getByTestId("comparison-fixture-inconclusive").click();
  await expect(panel.getByTestId("comparison-claim-inconclusive")).toContainText(
    "No supported training win",
  );

  await panel.getByTestId("comparison-fixture-regressed").click();
  await expect(panel.getByTestId("comparison-claim-regressed")).toContainText(
    "Regression observed",
  );

  await panel.getByTestId("comparison-fixture-partially_unavailable").click();
  const providerFailure = panel.getByTestId("comparison-failure-openai_reference");
  await expect(providerFailure).toContainText("credential failure");
  await expect(providerFailure).toContainText("no live score was fabricated");

  await panel.getByTestId("comparison-fixture-adapter_error").click();
  await expect(panel.getByTestId("comparison-claim-unavailable")).toContainText(
    "Training contrast unavailable",
  );
  await expect(panel.getByTestId("comparison-failure-trained_gemma")).toContainText(
    "adapter failure",
  );

  await panel.getByTestId("comparison-fixture-successful").click();
  const base = panel.getByTestId("comparison-model-base_gemma");
  await base.getByText("Model and run provenance").click();
  await expect(base).toContainText("sha256:");
  await base.getByText(/Strata and 64 constituent scenarios/).click();
  await base.getByRole("button", { name: /eeg-/ }).first().click();
  await expect(panel.getByTestId("comparison-replay")).toContainText(
    "Reproducible from the exact manifest",
  );
  await expect(panel.getByTestId("mesoscope-generality-track")).toContainText(
    "not EEG training evidence",
  );
});

test("keeps the default comparison readable and keyboard reachable on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("model-comparison-panel");
  await expect(panel.getByTestId("comparison-claim-improved")).toBeVisible();
  await panel.getByTestId("comparison-fixture-inconclusive").focus();
  await expect(panel.getByTestId("comparison-fixture-inconclusive")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel.getByTestId("comparison-claim-inconclusive")).toBeVisible();

  const overflow = await horizontalOverflowReport(page);
  expect(overflow.overflow, JSON.stringify(overflow, null, 2)).toBeLessThanOrEqual(1);
});
