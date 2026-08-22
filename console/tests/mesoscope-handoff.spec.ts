import { expect, test, type Page } from "@playwright/test";

const SIMULATION_NOTICE =
  "SIMULATED DATA — NO HARDWARE CONNECTION — NOT LASER OR ANIMAL GUIDANCE";

const OUTCOMES = [
  { label: "Sealed example A", status: "valid", fault: null, check: null },
  { label: "Sealed example B", status: "invalid", fault: "MISSING_REGION", check: "Region Agreement" },
  { label: "Sealed example C", status: "invalid", fault: "WRONG_Z_ASSIGNMENT", check: "Z Assignment" },
  { label: "Sealed example D", status: "invalid", fault: "MISSING_CHANNEL", check: "Channel Agreement" },
  { label: "Sealed example E", status: "invalid", fault: "DUPLICATE_EVENT", check: "Event Records" },
  { label: "Sealed example F", status: "invalid", fault: "MISSING_EVENT", check: "Event Records" },
  { label: "Sealed example G", status: "invalid", fault: "MOTION_ROW_MISMATCH", check: "Motion Rows" },
  { label: "Sealed example H", status: "invalid", fault: "CHECKSUM_MISMATCH", check: "Checksums" },
] as const;

async function openMesoscope(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByTestId("environment-nav-mesoscope")).toBeVisible();
  await page.getByTestId("environment-nav-mesoscope").click();
  await expect(page.getByTestId("environment-nav-mesoscope")).toHaveAttribute(
    "aria-current",
    "page",
  );
}

async function startMesoscopeRun(
  page: Page,
  exampleLabel = "Sealed example A",
): Promise<void> {
  await openMesoscope(page);
  await page.getByTestId("mode-run").click();
  await page.getByTestId("seeded-example-selector").selectOption({
    label: exampleLabel,
  });
  const freezeResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/environments/mesoscope-four-region-handoff/freeze")
      && response.request().method() === "POST",
  );
  const startRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/runs") && request.method() === "POST",
  );
  await page.getByTestId("start-run").click();
  expect((await freezeResponse).ok()).toBe(true);
  expect((await startRequest).postDataJSON()).toMatchObject({
    environment_id: "mesoscope-four-region-handoff",
  });
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("mesoscope-handoff-visualization")).toBeVisible();
}

async function applyMesoscopeAction(page: Page, actionType: string): Promise<void> {
  const picker = page.getByTestId("action-picker");
  await expect(picker).toBeEnabled();
  await picker.selectOption(actionType);
  await expect(page.locator(".run-action-argument")).toHaveCount(0);
  const response = page.waitForResponse(
    (candidate) =>
      /\/api\/runs\/[^/]+\/actions$/.test(new URL(candidate.url()).pathname)
      && candidate.request().method() === "POST",
  );
  await page.getByTestId("apply-run-action").click();
  const actionResponse = await response;
  expect(actionResponse.ok()).toBe(true);
  expect(actionResponse.request().postDataJSON()).toEqual({
    type: actionType,
    input: {},
  });
}

async function validateMesoscopePackage(
  page: Page,
  exampleLabel: string,
): Promise<void> {
  await startMesoscopeRun(page, exampleLabel);
  await applyMesoscopeAction(page, "inspect_sealed_handoff");
  await applyMesoscopeAction(page, "run_mock_acquisition");
  await applyMesoscopeAction(page, "validate_mock_package");
}

async function verifyCurrentRun(page: Page): Promise<void> {
  const response = page.waitForResponse(
    (candidate) =>
      /\/api\/runs\/[^/]+\/verify$/.test(new URL(candidate.url()).pathname)
      && candidate.request().method() === "POST",
  );
  await page.getByTestId("verify-run").click();
  expect((await response).ok()).toBe(true);
  await expect(page.getByTestId("run-status")).toContainText("Completed run");
}

test("switches from EEG to the sealed read-only mesoscope Environment", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByTestId("environment-nav-eeg")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByTestId("environment-nav-mesoscope").click();

  await expect(page.getByTestId("environment-nav-mesoscope")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByTestId("sealed-environment-workspace")).toContainText(
    "Sealed mesoscope four-region handoff",
  );
  await expect(page.getByTestId("sealed-environment-workspace")).toContainText(
    SIMULATION_NOTICE,
  );
  await expect(page.getByTestId("sealed-environment-workspace")).toContainText(
    "Profiles, signed plans, and the independent safety gate are immutable.",
  );
  await expect(page.getByTestId("sealed-environment-workspace")).toContainText(
    "Research-paper and commercial reference profiles are visible and locked; their source conventions remain distinct.",
  );
  await expect(page.getByTestId("sealed-environment-workspace")).not.toContainText(
    "reference profiles are visible, signed",
  );
  await expect(page.getByTestId("authoring-command")).toHaveCount(0);
  await expect(page.getByTestId("restore-draft")).toHaveCount(0);
});

test("accepts a compatible minor mesoscope presentation extension", async ({
  page,
}) => {
  await page.route("**/api/environments/mesoscope-four-region-handoff", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.visualization.future_minor_extension = { enabled: true };
    body.visualization.profile_provenance.future_source_link =
      "archival citation metadata";
    await route.fulfill({ response, json: body });
  });

  await openMesoscope(page);

  await expect(page.getByTestId("sealed-environment-workspace")).toBeVisible();
  await expect(page.getByTestId("sealed-environment-workspace")).toContainText(
    "R1–R4 · Z-A / Z-B",
  );
});

test("exposes only empty-input sealed actions and permanent safety labels", async ({
  page,
}) => {
  await openMesoscope(page);
  const response = await page.request.get(
    "/api/environments/mesoscope-four-region-handoff",
  );
  expect(response.ok()).toBe(true);
  const environment = await response.json();
  expect(environment.actions.map((action: { type: string }) => action.type)).toEqual([
    "inspect_sealed_handoff",
    "run_mock_acquisition",
    "validate_mock_package",
    "accept_mock_package",
    "quarantine_mock_package",
    "reject_mock_package",
  ]);
  for (const action of environment.actions) {
    expect(action.input_schema).toEqual({
      type: "object",
      properties: {},
      additionalProperties: false,
    });
  }
  expect(JSON.stringify(environment.actions)).not.toMatch(
    /laser_power|detector_gain|align|calibrat|surgery|biological|motion_control/i,
  );
  expect(environment.visualization.profile_provenance).toEqual({
    classification: "INSTRUMENT FACT",
    citation_ids: ["P1", "M2"],
    note: expect.any(String),
  });
  expect(environment.visualization.plan_provenance).toMatchObject({
    classification: "SIMULATION CHOICE",
    citation_ids: ["P1", "M3", "SES-SIMULATION-CONTRACT"],
  });
  expect(
    environment.visualization.package_provenance.map(
      (item: { classification: string }) => item.classification,
    ),
  ).toEqual(["SOFTWARE FACT", "SIMULATION CHOICE"]);

  await page.getByTestId("mode-run").click();
  await expect(page.getByTestId("mesoscope-safety-boundary")).toContainText(
    "SEALED — DISCONNECTED FROM HARDWARE",
  );
  await expect(page.getByTestId("mesoscope-safety-boundary")).toContainText(
    SIMULATION_NOTICE,
  );
  await expect(page.getByTestId("mesoscope-trace-boundary")).toHaveText(
    "SEALED SYNTHETIC TRACE · DISCONNECTED FROM HARDWARE",
  );
});

test("withholds runtime semantics until a frozen run supplies observations", async ({
  page,
}) => {
  await openMesoscope(page);
  await page.getByTestId("mode-run").click();

  await expect(page.getByTestId("mesoscope-sealed-preview")).toHaveText(
    "Runtime evidence is not loaded. Freeze and start a sealed run to display product-owned profile, plan, survey, tile, and package observations.",
  );
  await expect(page.getByTestId("mesoscope-profile-card")).toHaveCount(0);
  await expect(page.getByTestId("mesoscope-plan-card")).toHaveCount(0);
  await expect(page.getByTestId("mesoscope-survey")).toHaveCount(0);
  await expect(page.locator('[data-testid^="mesoscope-tile-"]')).toHaveCount(0);
  await expect(page.getByTestId("mesoscope-validation-status")).toHaveCount(0);
  await expect(page.getByTestId("mesoscope-package-evidence")).toHaveCount(0);
});

test("renders the deterministic four-region package with progressive evidence", async ({
  page,
}) => {
  await startMesoscopeRun(page);

  for (const [region, depth] of [
    ["R1", "Z-A"],
    ["R2", "Z-A"],
    ["R3", "Z-B"],
    ["R4", "Z-B"],
  ]) {
    const tile = page.getByTestId(`mesoscope-tile-${region}`);
    await expect(tile).toHaveAttribute("data-z-label", depth);
    await expect(tile).toContainText(region);
    await expect(tile).toContainText("Synthetic only");
  }
  await expect(page.getByTestId("mesoscope-profile-card")).toContainText("Immutable");
  await expect(page.getByTestId("mesoscope-profile-classification")).toContainText(
    "INSTRUMENT FACT[P1, M2]",
  );
  await expect(page.getByTestId("mesoscope-plan-card")).toContainText("4R-HANDOFF-v1");
  await expect(page.getByTestId("mesoscope-plan-classification")).toContainText(
    "SIMULATION CHOICE[P1, M3, SES-SIMULATION-CONTRACT]",
  );
  await expect(page.getByTestId("mesoscope-safety-gate")).toContainText(
    "Independently enforced; no bypass or apparatus controls.",
  );

  const evidence = page.getByTestId("mesoscope-package-evidence");
  const packageProvenance = page.getByTestId("mesoscope-evidence-classification");
  await expect(packageProvenance).toContainText("SOFTWARE FACT[S4, S5, S6]");
  await expect(packageProvenance).toContainText(
    "SIMULATION CHOICE[SES-SIMULATION-CONTRACT]",
  );
  await expect(evidence).not.toHaveAttribute("open", "");
  await evidence.locator(":scope > summary").click();
  const expected = page.getByTestId("mesoscope-expected-outputs");
  await expect(expected).not.toHaveAttribute("open", "");
  await expected.locator("summary").click();
  await expect(page.getByTestId("mesoscope-expected-output-table").locator("tbody tr"))
    .toHaveCount(8);

  await applyMesoscopeAction(page, "inspect_sealed_handoff");
  await applyMesoscopeAction(page, "run_mock_acquisition");
  await expect(page.getByTestId("mesoscope-event-records").locator("summary"))
    .toContainText("3");
  await expect(page.getByTestId("mesoscope-motion-rows").locator("summary"))
    .toContainText("8");
  await expect(page.getByTestId("mesoscope-manifest-records").locator("summary"))
    .toContainText("8");
  await expect(page.getByTestId("mesoscope-checksums").locator("summary"))
    .toContainText("5");

  await page.getByTestId("mesoscope-checksums").locator("summary").click();
  await expect(page.getByTestId("mesoscope-checksum-table").locator("tbody tr"))
    .toHaveCount(5);
  await applyMesoscopeAction(page, "validate_mock_package");
  await expect(page.getByTestId("mesoscope-validation-status")).toContainText("Valid");
  await page.getByTestId("mesoscope-package-checks").locator("summary").click();
  await expect(page.getByTestId("mesoscope-package-checks")).not.toContainText(
    "Mismatch",
  );
  await expect(page.getByTestId("mesoscope-package-checks").locator("li"))
    .toHaveCount(7);
});

for (const outcome of OUTCOMES) {
  test(`runs and verifies ${outcome.label}: ${outcome.fault ?? "complete agreement"}`, async ({
    page,
  }) => {
    await validateMesoscopePackage(page, outcome.label);
    const validation = page.getByTestId("mesoscope-validation-status");
    await expect(validation).toContainText(
      outcome.status === "valid" ? "Valid" : "Invalid",
    );
    const dispositionActions = outcome.status === "valid"
      ? ["accept_mock_package"]
      : ["quarantine_mock_package", "reject_mock_package"];
    await expect(page.getByTestId("action-picker")).toHaveValue(
      dispositionActions[0],
    );
    expect(
      await page.getByTestId("action-picker").locator("option").evaluateAll(
        (options) => options.map((option) => (option as HTMLOptionElement).value),
      ),
    ).toEqual(dispositionActions);

    if (outcome.fault) {
      await expect(page.getByTestId("mesoscope-detected-faults")).toHaveText(
        outcome.fault,
      );
      const evidence = page.getByTestId("mesoscope-package-evidence");
      await evidence.locator(":scope > summary").click();
      const checks = page.getByTestId("mesoscope-package-checks");
      await checks.locator("summary").click();
      await expect(
        checks.locator("li.is-mismatch").filter({ hasText: outcome.check }),
      ).toHaveText(`${outcome.check}Mismatch`);
      if (outcome.fault === "MISSING_REGION") {
        await expect(page.getByTestId("mesoscope-tile-R4")).toHaveAttribute(
          "data-status",
          "missing",
        );
      }
      if (outcome.fault === "WRONG_Z_ASSIGNMENT") {
        await expect(page.getByTestId("mesoscope-tile-R3")).toHaveAttribute(
          "data-z-label",
          "Z-A",
        );
      }
      await applyMesoscopeAction(page, "quarantine_mock_package");
      await expect(page.getByTestId("mesoscope-terminal-status")).toHaveText(
        "SYNTHETIC PACKAGE QUARANTINED",
      );
    } else {
      await expect(page.getByTestId("mesoscope-detected-faults")).toHaveCount(0);
      await applyMesoscopeAction(page, "accept_mock_package");
      await expect(validation).toContainText("MOCK PACKAGE VERIFIED");
    }

    await expect(page.getByTestId("run-status")).toContainText(
      "Awaiting verification",
    );
    await verifyCurrentRun(page);
    const result = page.getByTestId("verifier-result");
    await expect(result).toContainText("Verifier passed");
    if (outcome.fault) {
      await expect(page.getByTestId("terminal-disposition")).toHaveText("Aborted");
      await expect(page.getByTestId("outcome-category")).toHaveText(
        "Package Quarantined",
      );
      await expect(page.locator("body")).not.toContainText("MOCK PACKAGE VERIFIED");
    } else {
      await expect(page.getByTestId("terminal-disposition")).toHaveText("Closed");
      await expect(page.getByTestId("outcome-category")).toHaveText(
        "Mock Package Verified",
      );
      await expect(result).toContainText("MOCK PACKAGE VERIFIED");
    }
  });
}

test("replays the canonical sealed result and resets to the same cached scenario", async ({
  page,
}) => {
  await validateMesoscopePackage(page, "Sealed example A");
  await applyMesoscopeAction(page, "accept_mock_package");
  await verifyCurrentRun(page);
  const revision = await page.getByTestId("frozen-revision").getAttribute("title");

  const replayResponse = page.waitForResponse(
    (candidate) =>
      /\/api\/runs\/[^/]+\/replay$/.test(new URL(candidate.url()).pathname)
      && candidate.request().method() === "POST",
  );
  await page.getByTestId("replay-run").click();
  expect((await replayResponse).ok()).toBe(true);
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match the source run.",
  );
  await expect(page.getByTestId("frozen-revision")).toHaveAttribute(
    "title",
    revision ?? "",
  );

  const resetResponse = page.waitForResponse(
    (candidate) =>
      /\/api\/runs\/[^/]+\/reset$/.test(new URL(candidate.url()).pathname)
      && candidate.request().method() === "POST",
  );
  await page.getByTestId("reset-run").click();
  expect((await resetResponse).ok()).toBe(true);
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  await expect(page.getByTestId("mesoscope-validation-status")).toContainText(
    "Not Run",
  );
  await expect(page.getByTestId("mesoscope-tile-R4")).toHaveAttribute(
    "data-status",
    "cached",
  );
  await expect(page.getByTestId("verifier-result")).toHaveCount(0);
  await expect(page.getByTestId("frozen-revision")).toHaveAttribute(
    "title",
    revision ?? "",
  );
});

test("keeps the sealed handoff responsive and matches desktop and mobile layouts", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await validateMesoscopePackage(page, "Sealed example H");
  await expect(page.getByTestId("mesoscope-validation-status")).toContainText(
    "Invalid",
  );
  await expect(page.getByTestId("action-picker")).toHaveValue(
    "quarantine_mock_package",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page).toHaveScreenshot("ticket-05-mesoscope-desktop.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [page.getByTestId("frozen-revision")],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });
  const detailsRail = page.locator(".details-rail");
  const railMetrics = await detailsRail.evaluate((rail) => ({
    clientHeight: rail.clientHeight,
    overflowY: getComputedStyle(rail).overflowY,
    scrollHeight: rail.scrollHeight,
  }));
  expect(railMetrics.overflowY).toBe("auto");
  expect(railMetrics.scrollHeight).toBeGreaterThan(railMetrics.clientHeight);
  await page.getByTestId("sealed-frozen-identity").scrollIntoViewIfNeeded();
  const [railBounds, sealedBounds] = await Promise.all([
    detailsRail.boundingBox(),
    page.getByTestId("sealed-frozen-identity").boundingBox(),
  ]);
  expect((sealedBounds?.y ?? 0) + (sealedBounds?.height ?? 0)).toBeLessThanOrEqual(
    (railBounds?.y ?? 0) + (railBounds?.height ?? 0) + 1,
  );
  await detailsRail.evaluate((rail) => { rail.scrollTop = 0; });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  for (const testId of [
    "environment-nav-mesoscope",
    "action-picker",
    "apply-run-action",
    "verify-run",
    "reset-run",
  ]) {
    const bounds = await page.getByTestId(testId).boundingBox();
    expect(bounds?.height).toBeGreaterThanOrEqual(44);
    expect(bounds?.width).toBeLessThanOrEqual(390);
  }
  await expect(page).toHaveScreenshot("ticket-05-mesoscope-mobile.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [page.getByTestId("frozen-revision")],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });
});
