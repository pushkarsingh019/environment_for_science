import { expect, test } from "@playwright/test";

test("labels active real or fixture comparison evidence without ambiguity", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("model-comparison-panel");
  const real = panel.getByTestId("comparison-real-notice");
  const fixture = panel.getByTestId("comparison-fixture-notice");
  await expect(real.or(fixture)).toBeVisible();
  if (await real.isVisible()) {
    await expect(real).toContainText("Verified real evaluation");
    await expect(real).toContainText("eeg-training-result-");
    await expect(real).toContainText("sha256:");
    await expect(panel.getByTestId("comparison-model-trained_gemma")).toContainText(
      "eeg-curriculum-final",
    );
    const base = panel.getByTestId("comparison-model-base_gemma");
    await base.getByText(/Strata and 64 constituent scenarios/).click();
    await base.getByRole("button", { name: /eeg-/ }).first().click();
    await expect(panel.getByTestId("comparison-replay")).toContainText(
      "Canonical evaluator snapshot loaded",
    );
  } else {
    await expect(fixture).toContainText("Offline fixture");
  }
});
