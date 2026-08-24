import { expect, test } from "@playwright/test";

import {
  recoverVisibleOnsetCue,
  startSeededRun,
} from "./eeg-test-helpers";

test("runs the authoring, EEG, mesoscope, evaluation, training, replay, and reset journey", async ({
  page,
}) => {
  await page.goto("/");

  await page.getByTestId("command-composer").fill("Add Cz to the Montage");
  await page.getByTestId("apply-draft-command").click();
  await expect(page.getByTestId("montage-recording-sites")).toContainText("Cz");

  await startSeededRun(page, "Seeded example B");
  await recoverVisibleOnsetCue(page);
  await page.getByTestId("verify-run").click();
  await expect(page.getByTestId("verifier-result")).toContainText("Verifier passed");
  await page.getByTestId("replay-run").click();
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match",
  );

  await page.getByTestId("environment-nav-mesoscope").click();
  await page.getByTestId("mode-evaluate").click();
  await expect(page.getByTestId("mesoscope-portability-results")).toContainText(
    "MOCK PACKAGE VERIFIED",
  );
  await expect(page.getByTestId("mesoscope-portability-results")).toContainText(
    "safely quarantined",
  );
  await page.getByTestId("portability-replay-valid-handoff").click();
  await expect(page.getByTestId("mesoscope-portability-replay")).toContainText(
    "Trace and result match",
  );

  await page.getByTestId("environment-nav-eeg").click();
  await page.getByTestId("mode-evaluate").click();
  const training = page.getByTestId("training-acceptance-panel");
  await page.getByTestId("launch-training-acceptance").click();
  await expect(training.getByTestId("training-job-queued").first()).toContainText(
    "No model compute will run on this computer",
  );
  const comparison = page.getByTestId("model-comparison-panel");
  const successful = comparison.getByTestId("comparison-fixture-successful");
  await expect(successful).toBeVisible();
  if (await successful.isEnabled()) await successful.click();
  await expect(comparison.getByTestId("comparison-fixture-notice")).toContainText(
    "Offline fixture",
  );
  const base = comparison.getByTestId("comparison-model-base_gemma");
  await base.getByText(/Strata and 64 constituent scenarios/).click();
  await base.getByRole("button", { name: /eeg-/ }).first().click();
  await expect(comparison.getByTestId("comparison-replay")).toContainText(
    "Canonical replay receipt",
  );

  await page.getByTestId("reset-demo").click();
  await expect(page.getByTestId("demo-reset-notice")).toContainText(
    "Immutable real artifacts were preserved",
  );
  await expect(page.getByTestId("mode-edit")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    "FC3, FC4, FT7, FT8",
  );
});
