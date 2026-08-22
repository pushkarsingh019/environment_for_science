import { expect, test } from "@playwright/test";

import { applySimulatedAction, startSeededRun } from "./eeg-test-helpers";

const SEEDED_LABELS = [
  "Seeded example A",
  "Seeded example B",
  "Seeded example C",
  "Seeded example D",
  "Seeded example E",
  "Seeded example F",
];

test("selects one of six neutral training examples without publishing the curriculum manifests", async ({
  page,
}) => {
  const environmentResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/environment") &&
      response.request().method() === "GET",
  );
  await page.goto("/");
  const environment = await (await environmentResponse).json();

  expect(Object.keys(environment).sort()).toEqual([
    "actions",
    "description",
    "environment_id",
    "hidden_state_exposed",
    "name",
    "policy_agents",
    "seeded_examples",
    "simulation_label",
    "validation",
    "visualization",
  ]);
  expect(environment.seeded_examples).toHaveLength(6);
  expect(environment.seeded_examples.map((example: { label: string }) => example.label))
    .toEqual(SEEDED_LABELS);
  expect(new Set(
    environment.seeded_examples.map((example: { stage: string }) => example.stage),
  )).toEqual(new Set(["preflight", "short_acquisition"]));
  expect(JSON.stringify(environment)).not.toMatch(
    /manifest|blueprint|nuisance|fault|category|heldout|development|package_digest/i,
  );

  await page.getByTestId("mode-run").click();
  const selector = page.getByTestId("seeded-example-selector");
  await expect(selector).toBeVisible();
  await expect(selector.locator("option")).toHaveText(SEEDED_LABELS);
  await selector.selectOption({ label: "Seeded example F" });
  await expect(page.getByTestId("seeded-example-stage")).toHaveText(
    "Short Acquisition",
  );

  const startRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/runs") && request.method() === "POST",
  );
  const freezeResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/draft/freeze") &&
      response.request().method() === "POST",
  );
  await page.getByTestId("start-run").click();
  const frozen = await (await freezeResponse).json();
  expect(Object.keys(frozen).sort()).toEqual([
    "bundle_revision",
    "draft_revision",
    "frozen_environment_id",
    "procedure",
    "revision_digest",
  ]);
  expect((await startRequest).postDataJSON()).toMatchObject({
    scenario_id: environment.seeded_examples[5].scenario_id,
  });
});

test("shows live lifecycle stage, domain freshness, and a distinct closed disposition", async ({
  page,
}) => {
  await startSeededRun(page, "Seeded example A");

  await expect(page.getByTestId("curriculum-stage")).toHaveText("Preflight");
  for (const domain of [
    "configuration",
    "eeg",
    "onset",
    "response",
    "recording",
  ]) {
    await expect(page.getByTestId(`domain-freshness-${domain}`)).toContainText(
      "Current",
    );
  }

  for (const action of [
    "inspect_configuration",
    "inspect_eeg_signals",
    "inspect_onset_route",
    "inspect_response_timeline",
    "inspect_recording_timeline",
  ]) {
    await applySimulatedAction(page, action);
  }
  await applySimulatedAction(page, "complete_preflight");
  await expect(page.getByTestId("curriculum-stage")).toHaveText("Terminal");
  await page.getByTestId("verify-run").click();

  const result = page.getByTestId("verifier-result");
  await expect(result).toContainText("Verifier passed");
  await expect(page.getByTestId("terminal-disposition")).toHaveText("Closed");
  await expect(page.getByTestId("outcome-category")).toHaveText("Nominal");
  await page.getByTestId("verifier-explanation").locator("summary").click();
  await expect(page.getByTestId("verifier-explanation")).toContainText(
    "terminal correctness",
  );
  await expect(page.getByTestId("verifier-explanation")).toContainText("reward");
});
