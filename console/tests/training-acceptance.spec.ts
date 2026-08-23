import { expect, test } from "@playwright/test";

test("shows queued, running, failed, and retryable workstation acceptance states", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("training-acceptance-panel");
  await expect(panel).toContainText("never on this computer");
  await page.getByTestId("launch-training-acceptance").click();
  await expect(panel.getByTestId("training-job-queued")).toContainText(
    "approved training and inference workstations",
  );

  await panel.getByRole("button", { name: "Record workstation start" }).click();
  await expect(panel.getByTestId("training-job-running")).toContainText(
    "awaiting verified optimization",
  );

  await panel.getByRole("button", { name: "Verify imported evidence" }).click();
  await expect(panel.getByTestId("training-job-failed")).toContainText(
    "Artifact verification failed",
  );
  await expect(panel.getByTestId("training-job-failed")).toContainText(
    "training-acceptance-imports/training-acceptance-",
  );

  await panel.getByRole("button", { name: "Retry after replacing evidence" }).click();
  await expect(panel.getByTestId("training-job-queued")).toContainText(
    "Queued again",
  );
});
