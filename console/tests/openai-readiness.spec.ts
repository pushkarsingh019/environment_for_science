import { expect, test } from "@playwright/test";

test("shows exact OpenAI Responses readiness without exposing a credential", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const readiness = page.getByTestId("hosted-reference-readiness");
  await expect(readiness).toContainText("OpenAI Responses");
  await expect(readiness).toContainText("gpt-5.6-sol");
  await expect(readiness).toContainText("Responses · stateless · storage disabled");
  await expect(readiness).toContainText("Missing credential");
  await expect(readiness).toContainText("hosted reference");
  await expect(page.locator("body")).not.toContainText("Bearer ");
});
