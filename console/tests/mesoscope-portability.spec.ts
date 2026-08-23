import { expect, test } from "@playwright/test";

test("shows mesoscope compiler evidence separately and opens canonical replay", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("environment-nav-mesoscope").click();
  await page.getByTestId("mode-evaluate").click();

  await expect(page.getByTestId("mesoscope-portability-workspace")).toContainText(
    "Platform-generality evidence",
  );
  await expect(page.getByTestId("mesoscope-portability-report")).toContainText(
    "science-environment-verifiers-v1/1",
  );
  await expect(page.getByTestId("mesoscope-portability-report")).toContainText(
    "not hosted-model results",
  );
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
  await expect(page.getByTestId("mesoscope-portability-replay")).toContainText(
    "MOCK PACKAGE VERIFIED",
  );
  await expect(page.getByText("Separate from EEG training")).toBeVisible();
});
