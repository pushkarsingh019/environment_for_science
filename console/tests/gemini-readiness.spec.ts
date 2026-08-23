import { expect, test } from "@playwright/test";

test("shows exact Gemini Interactions readiness without exposing a credential", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("mode-evaluate").click();

  const readiness = page.getByTestId("provider-readiness-gemini");
  await expect(readiness).toContainText("Gemini Interactions");
  await expect(readiness).toContainText("gemini-3.7-flash");
  await expect(readiness).toContainText(
    "Interactions · signed-step replay · storage disabled",
  );
  await expect(readiness).toContainText("Missing credential");
  await expect(page.locator("body")).not.toContainText("x-goog-api-key");
});
