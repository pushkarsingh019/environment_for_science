import { expect, test } from "@playwright/test";

test("shows queued, running, failed, and retryable workstation acceptance states", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("training-acceptance-panel");
  await expect(panel).toContainText("never on this computer");
  await page.getByTestId("launch-training-acceptance").click();
  const launched = panel
    .getByTestId("training-job-queued")
    .filter({ hasText: "approved training and inference workstations" })
    .first();
  await expect(launched).toBeVisible();
  const jobId = await launched.locator("code").first().innerText();
  const job = (status: string) => panel
    .getByTestId(`training-job-${status}`)
    .filter({ hasText: jobId });

  await job("queued").getByRole("button", { name: "Record workstation start" }).click();
  await expect(job("running")).toContainText("awaiting verified optimization");

  await job("running").getByRole("button", { name: "Verify imported evidence" }).click();
  await expect(job("failed")).toContainText("Artifact verification failed");
  await expect(job("failed")).toContainText(
    "training-acceptance-imports/training-acceptance-",
  );

  await job("failed").getByRole("button", { name: "Retry after replacing evidence" }).click();
  await expect(job("queued")).toContainText("Queued again");
});
