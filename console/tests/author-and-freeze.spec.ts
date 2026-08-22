import { expect, test } from "@playwright/test";

import { completeNominalPreflight } from "./eeg-test-helpers";

const ADD_CZ = "Add Cz to the Montage";
const REMOVE_FT8 = "Remove FT8 from the Montage";
const SET_512_HZ = "Set the sampling rate to 512 Hz";
const UNSUPPORTED_CONNECTION = "Connect to the EEG amplifier";

test.describe.configure({ mode: "serial" });

async function openSeededDraft(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(page.getByTestId("mode-edit")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("draft-revision")).toHaveAttribute(
    "data-revision",
    /\d+/,
  );
  const restored = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/draft/restore") &&
      response.request().method() === "POST",
  );
  await page.getByTestId("restore-draft").click();
  await restored;
  await expect(page.getByTestId("draft-busy")).toHaveCount(0);
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    "FC3, FC4, FT7, FT8",
  );
  const revision = Number(
    await page.getByTestId("draft-revision").getAttribute("data-revision"),
  );
  expect(Number.isInteger(revision)).toBe(true);
  return revision;
}

async function applyCommand(
  page: import("@playwright/test").Page,
  command: string,
) {
  const response = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith("/api/draft/commands") &&
      candidate.request().method() === "POST",
  );
  await page.getByTestId("command-composer").fill(command);
  await page.getByTestId("apply-draft-command").click();
  await response;
  await expect(page.getByTestId("draft-busy")).toHaveCount(0);
}

async function tabToTestId(
  page: import("@playwright/test").Page,
  expected: string,
) {
  for (let step = 0; step < 30; step += 1) {
    await page.keyboard.press("Tab");
    if (
      (await page.evaluate(() =>
        document.activeElement?.getAttribute("data-testid"),
      )) === expected
    ) {
      return;
    }
  }
  throw new Error(`Keyboard focus did not reach ${expected}`);
}

test("accepts compatible nested scientific fields while rejecting an unknown product-envelope field", async ({
  page,
}) => {
  await page.route("**/api/draft", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.apparatus.compatible_minor_extension = "apparatus metadata";
    payload.apparatus.sites[0].compatible_minor_extension = "site metadata";
    payload.procedure.compatible_minor_extension = "procedure metadata";
    payload.procedure.montage.compatible_minor_extension = "montage metadata";
    payload.procedure.acquisition_profile.compatible_minor_extension =
      "acquisition metadata";
    payload.notes = [
      {
        id: "note-compatible-minor-extension",
        filename: "compatibility-note.txt",
        content: "Nested note metadata remains forward-compatible.",
        verification_status: "unverified_descriptive_input",
        run_control: false,
        compatible_minor_extension: "note metadata",
      },
    ];
    await route.fulfill({ response, json: payload });
  });

  await page.goto("/");
  await expect(page.getByTestId("whole-cap-visualization")).toBeVisible();
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    "FC3, FC4, FT7, FT8",
  );
  await expect(page.getByTestId("draft-note-compatibility-note.txt")).toContainText(
    "Nested note metadata remains forward-compatible.",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.unroute("**/api/draft");
  await page.route("**/api/draft", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    delete payload.procedure.montage.reference;
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(/missing reference/);

  await page.unroute("**/api/draft");
  await page.route("**/api/draft", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.compatible_minor_extension = "not allowed at the product envelope";
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    /unexpected compatible_minor_extension/,
  );
});

test("opens on a whole-cap Apparatus with a distinct seeded Montage and progressive setup details", async ({
  page,
}) => {
  await openSeededDraft(page);

  await expect(page.getByTestId("whole-cap-visualization")).toHaveAttribute(
    "aria-label",
    /configurable whole-cap EEG Apparatus.*Procedure-selected Montage/i,
  );
  expect(await page.locator('[data-testid^="apparatus-site-"]').count()).toBeGreaterThan(6);
  await expect(page.getByTestId("scientific-claim")).toContainText("Schematic");
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    "FC3, FC4, FT7, FT8",
  );
  await expect(page.getByTestId("montage-reference")).toHaveText("FCz");
  await expect(page.getByTestId("montage-ground")).toHaveText("A1");
  const roleStyles = await page.evaluate(() => {
    const styles = (testId: string) => {
      const element = document.querySelector<HTMLElement>(
        `[data-testid="${testId}"]`,
      );
      if (!element) throw new Error(`Missing ${testId}`);
      const computed = getComputedStyle(element);
      return {
        borderRadius: computed.borderRadius,
        borderStyle: computed.borderStyle,
      };
    };
    return {
      recording: styles("apparatus-site-FC3"),
      reference: styles("apparatus-site-FCz"),
      ground: styles("apparatus-site-A1"),
    };
  });
  expect(roleStyles.recording.borderRadius).not.toBe(
    roleStyles.reference.borderRadius,
  );
  expect(roleStyles.reference.borderRadius).not.toBe(
    roleStyles.ground.borderRadius,
  );
  expect(roleStyles.ground.borderStyle).toBe("double");

  const setup = page.getByTestId("setup-details");
  await expect(setup).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("setup-values")).toBeHidden();
  await setup.locator("summary").click();
  await expect(page.getByTestId("setup-values")).toBeVisible();
  await expect(page.getByTestId("setup-values")).toContainText("1017 Hz");
  await expect(page.getByTestId("setup-values")).toContainText("0.1–30 Hz");
  await expect(page.getByTestId("setup-values")).toContainText("50 Hz");
});

test("applies supported conversational edits, explains an unsupported request, and reverses draft history", async ({
  page,
}) => {
  await openSeededDraft(page);

  await applyCommand(page, ADD_CZ);
  await expect(page.getByTestId("assistant-result")).toContainText("Applied");
  await expect(page.getByTestId("montage-recording-sites")).toContainText("Cz");
  await expect(page.getByTestId("last-change-attribution")).toContainText(
    "Authoring assistant",
  );

  await applyCommand(page, REMOVE_FT8);
  await expect(page.getByTestId("montage-recording-sites")).not.toContainText("FT8");

  await applyCommand(page, SET_512_HZ);
  await expect(page.getByTestId("setup-details")).toContainText("512 Hz");

  const unsupportedRevision = await page
    .getByTestId("draft-revision")
    .getAttribute("data-revision");
  const unsupportedMontage = await page
    .getByTestId("montage-recording-sites")
    .textContent();
  await applyCommand(page, UNSUPPORTED_CONNECTION);
  await expect(page.getByTestId("assistant-result")).toContainText("Unsupported");
  await expect(page.getByTestId("assistant-result")).toContainText(
    /could not apply|montage sites|acquisition settings/i,
  );
  await expect(page.getByTestId("draft-revision")).toHaveAttribute(
    "data-revision",
    unsupportedRevision ?? "",
  );
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    unsupportedMontage ?? "",
  );
  await expect(page.locator("body")).not.toContainText("expected_revision");

  await page.getByTestId("undo-draft").click();
  await expect(page.getByTestId("setup-details")).toContainText("1017 Hz");
  await page.getByTestId("redo-draft").click();
  await expect(page.getByTestId("setup-details")).toContainText("512 Hz");

  await page.getByTestId("restore-draft").click();
  await expect(page.getByTestId("montage-recording-sites")).toHaveText(
    "FC3, FC4, FT7, FT8",
  );
  await expect(page.getByTestId("setup-details")).toContainText("1017 Hz");
  await expect(page.getByTestId("last-change-attribution")).toContainText(
    "Environment author",
  );
});

test("reads a local text note in the browser and stages only unverified descriptive input", async ({
  page,
}) => {
  const seedRevision = await openSeededDraft(page);
  const noteRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/draft/notes") && request.method() === "POST",
  );

  await page.getByTestId("note-file").setInputFiles({
    name: "participant-preflight.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Confirm the participant-facing instructions before acquisition."),
  });

  const request = await noteRequest;
  expect(request.postDataJSON()).toEqual({
    filename: "participant-preflight.txt",
    content: "Confirm the participant-facing instructions before acquisition.",
    expected_revision: seedRevision,
  });
  await expect(page.getByTestId("draft-note-participant-preflight.txt")).toContainText(
    "Unverified descriptive input",
  );
  await expect(page.getByTestId("draft-note-participant-preflight.txt")).toContainText(
    "Cannot control a run",
  );
  await expect(page.getByTestId("draft-note-participant-preflight.txt")).toContainText(
    "Confirm the participant-facing instructions",
  );

  await page.getByTestId("undo-draft").click();
  await expect(page.getByTestId("draft-note-participant-preflight.txt")).toHaveCount(0);

  const oversizedRequests: string[] = [];
  page.on("request", (candidate) => {
    if (candidate.url().endsWith("/api/draft/notes")) {
      oversizedRequests.push(candidate.url());
    }
  });
  await page.getByTestId("note-file").setInputFiles({
    name: "oversized.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(100_001, "x"),
  });
  await expect(page.getByRole("alert")).toContainText("100,000 bytes");
  expect(oversizedRequests).toEqual([]);
});

test("freezes and starts one revision while later Edit changes leave its configuration, trace, and replay unchanged", async ({
  page,
}) => {
  await openSeededDraft(page);
  await applyCommand(page, ADD_CZ);
  await page.getByTestId("mode-run").click();

  const startRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/runs") && request.method() === "POST",
  );
  await page.getByTestId("start-run").click();
  await expect(page.getByTestId("run-status")).toContainText("Active run");
  expect((await startRequest).postDataJSON()).toMatchObject({
    frozen_environment_id: expect.any(String),
  });
  await expect(page.getByTestId("frozen-montage")).toContainText(
    "FC3, FC4, FT7, FT8, Cz",
  );
  await expect(page.getByTestId("run-workspace")).not.toContainText(
    "Authoring assistant",
  );

  const frozenRevision = await page
    .getByTestId("frozen-revision")
    .getAttribute("title");
  const frozenConfiguration = await page.getByTestId("frozen-configuration").innerText();

  await completeNominalPreflight(page);
  await page.getByTestId("verify-run").click();
  await expect(page.getByTestId("verifier-result")).toContainText("Verifier passed");
  await expect(page.getByTestId("terminal-disposition")).toHaveText("Closed");
  const sourceTrace = await page.getByTestId("trace-list").innerText();

  await page.getByTestId("mode-edit").click();
  await applyCommand(page, REMOVE_FT8);
  await expect(page.getByTestId("montage-recording-sites")).not.toContainText("FT8");

  await page.getByTestId("mode-run").click();
  await expect(page.getByTestId("frozen-revision")).toHaveAttribute(
    "title",
    frozenRevision ?? "",
  );
  expect(await page.getByTestId("frozen-configuration").innerText()).toBe(
    frozenConfiguration,
  );
  expect(await page.getByTestId("trace-list").innerText()).toBe(sourceTrace);
  await page.getByTestId("replay-run").click();
  await expect(page.getByTestId("replay-result")).toContainText(
    "Trace and result digests match",
  );
});

test("keeps authoring progressive and keyboard-usable at mobile width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSeededDraft(page);

  await tabToTestId(page, "command-composer");
  expect(
    await page
      .getByTestId("command-composer")
      .evaluate((element) => element.matches(":focus-visible")),
  ).toBe(true);
  await page.getByTestId("command-composer").fill(ADD_CZ);
  await tabToTestId(page, "apply-draft-command");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("montage-recording-sites")).toContainText("Cz");

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByTestId("setup-details")).not.toHaveAttribute("open", "");
});

test("matches the approved primary Edit workspace at desktop and mobile widths", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openSeededDraft(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page).toHaveScreenshot("ticket-02-edit-desktop.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [
      page.getByTestId("draft-revision"),
      page.getByTestId("draft-identity-revision"),
    ],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page).toHaveScreenshot("ticket-02-edit-mobile.png", {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    mask: [
      page.getByTestId("draft-revision"),
      page.getByTestId("draft-identity-revision"),
    ],
    maskColor: "#efeeec",
    maxDiffPixelRatio: 0.005,
  });
});
