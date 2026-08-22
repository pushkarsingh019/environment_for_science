import { expect, test } from "@playwright/test";

const environment = {
  environment_id: "eeg-marker-recovery",
  scenario_id: "eeg-duplicate-onset-seed-01",
  name: "EEG onset-marker recovery",
  description: "A seeded synthetic onset-marker preflight.",
  validation: {
    status: "valid",
    summary: "Environment Bundle v1 validated",
    checks: ["Contract version supported", "Policy-visible observations declared"],
  },
  hidden_state_exposed: false,
  policy_agents: [
    { id: "seeded-policy-agent", name: "Seeded recovery Policy agent" },
  ],
};

const initialRun = {
  run_id: "run-eeg-001",
  scenario_id: environment.scenario_id,
  revision_digest: "rev_7fd29a0c",
  scenario_digest: "scenario_2c941e5b",
  policy_agent: {
    id: "seeded-policy-agent",
    name: "Seeded recovery Policy agent",
  },
  status: "active",
  observation: {
    summary: "One lower-right test flash produced two onset markers.",
    latest_flash: {
      location: "lower-right",
      marker_count: 2,
      evidence_id: "flash-001",
      freshness: "current",
    },
    onset_route: {
      inspection_status: "not inspected",
      refractory_route: "unverified",
    },
  },
  permitted_actions: [
    "inspect_onset_route",
    "repair_refractory_route",
    "present_test_flash",
    "restart_response_handshake",
  ],
  trace: [
    {
      sequence: 1,
      type: "observation",
      summary: "Initial lower-right test flash observed.",
      marker_count: 2,
      freshness: "current",
    },
  ],
  verifier_result: null,
};

test("validates the Environment and freezes a run at the public HTTP seam", async ({
  page,
}) => {
  await page.route("**/api/environment", (route) =>
    route.fulfill({ json: environment }),
  );
  await page.route("**/api/runs", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({
      scenario_id: environment.scenario_id,
      policy_agent: "seeded-policy-agent",
    });
    await route.fulfill({ status: 201, json: initialRun });
  });

  await page.goto("/");

  await expect(page.getByTestId("environment-validation")).toContainText(
    "Environment Bundle v1 validated",
  );
  await page.getByTestId("start-run").click();

  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("frozen-revision")).toContainText(
    initialRun.revision_digest,
  );
  await expect(page.getByTestId("policy-agent-identity")).toContainText(
    "Seeded recovery Policy agent",
  );
  await expect(page.getByTestId("marker-count")).toHaveText("2 onset markers");
  await expect(page.getByTestId("apparatus-visualization")).toHaveAttribute(
    "aria-label",
    /lower-right test flash.*2 onset markers/i,
  );
});
