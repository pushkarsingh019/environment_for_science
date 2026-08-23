import { expect, test } from "@playwright/test";

test("shows durable workstation-only curriculum training with frozen split counts", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const panel = page.getByTestId("curriculum-training-panel");
  await expect(panel).toContainText("held-out split remains sealed");
  await panel.getByTestId("launch-curriculum-training").click();
  await expect(panel.getByTestId("curriculum-job-queued")).toContainText(
    "Frozen split counts: 96 / 32 / 64",
  );
  await expect(panel.getByTestId("curriculum-job-queued")).toContainText(
    "no model compute runs on this computer",
  );

  await panel.getByRole("button", { name: "Record curriculum start" }).click();
  await expect(panel.getByTestId("curriculum-job-running")).toContainText(
    "Development diagnostics and sealed held-out evaluation remain separate",
  );
});
