import type {
  ActionPresentation,
  AuthoringAssistantIdentity,
  CanonicalTraceHeader,
  DraftAcquisitionProfile,
  DraftActor,
  DraftApparatus,
  DraftCommandResponse,
  DraftHistory,
  DraftLastChange,
  DraftMontage,
  DraftNote,
  DraftProcedure,
  DraftSite,
  EnvironmentDraft,
  EnvironmentSummary,
  EnvironmentValidationSummary,
  FrozenEnvironment,
  JsonObject,
  JsonValue,
  PolicyAgentIdentity,
  ReplayReport,
  ReplayResponse,
  RouteNodePresentation,
  ScalpSitePresentation,
  RunLineage,
  RunSnapshot,
  TraceAction,
  TraceEvent,
  TraceTransition,
  VerifierResult,
} from "./types";

type UncheckedRecord = Record<string, unknown>;

const SHA256_DIGEST = /^sha256:[0-9a-f]{64}$/;

function malformed(path: string, expectation: string): never {
  throw new Error(`${path} must ${expectation}.`);
}

function parseActionPresentation(
  value: unknown,
  path: string,
): ActionPresentation {
  const record = exactRecord(
    value,
    [
      "type",
      "title",
      "description",
      "input_schema",
      "group",
      "changes_state",
    ],
    path,
  );
  return {
    type: nonEmptyString(record.type, `${path}.type`),
    title: nonEmptyString(record.title, `${path}.title`),
    description: nonEmptyString(record.description, `${path}.description`),
    input_schema: jsonObject(record.input_schema, `${path}.input_schema`),
    group: oneOf(
      record.group,
      ["inspect", "collect", "remediate", "decide"] as const,
      `${path}.group`,
    ),
    changes_state: booleanValue(record.changes_state, `${path}.changes_state`),
  };
}

function parseRouteNode(
  value: unknown,
  path: string,
): RouteNodePresentation {
  const record = exactRecord(
    value,
    ["id", "name", "detail", "emphasis"],
    path,
  );
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    name: nonEmptyString(record.name, `${path}.name`),
    detail: nonEmptyString(record.detail, `${path}.detail`),
    emphasis: booleanValue(record.emphasis, `${path}.emphasis`),
  };
}

function parseVisualization(
  value: unknown,
  path: string,
): EnvironmentSummary["visualization"] {
  if (isRecord(value) && value.kind === "eeg_preflight_v1") {
    const record = exactRecord(
      value,
      [
        "kind",
        "title",
        "trace_panel_label",
        "frequency_panel_label",
        "montage_panel_label",
        "details_toggle_label",
        "synthetic_label",
        "scalp_sites",
      ],
      path,
    );
    if (!Array.isArray(record.scalp_sites)) {
      malformed(`${path}.scalp_sites`, "be an array");
    }
    return {
      kind: "eeg_preflight_v1",
      title: nonEmptyString(record.title, `${path}.title`),
      trace_panel_label: nonEmptyString(
        record.trace_panel_label,
        `${path}.trace_panel_label`,
      ),
      frequency_panel_label: nonEmptyString(
        record.frequency_panel_label,
        `${path}.frequency_panel_label`,
      ),
      montage_panel_label: nonEmptyString(
        record.montage_panel_label,
        `${path}.montage_panel_label`,
      ),
      details_toggle_label: nonEmptyString(
        record.details_toggle_label,
        `${path}.details_toggle_label`,
      ),
      synthetic_label: oneOf(
        record.synthetic_label,
        ["Synthetic EEG apparatus simulation"] as const,
        `${path}.synthetic_label`,
      ),
      scalp_sites: record.scalp_sites.map((site, index) =>
        parseScalpSite(site, `${path}.scalp_sites[${index}]`),
      ),
    };
  }
  const record = exactRecord(
    value,
    [
      "kind",
      "title",
      "display_label",
      "flash_label",
      "route_nodes",
      "marker_lane_label",
      "freshness_label",
    ],
    path,
  );
  if (!Array.isArray(record.route_nodes)) {
    malformed(`${path}.route_nodes`, "be an array");
  }
  return {
    kind: oneOf(record.kind, ["eeg_onset_route"] as const, `${path}.kind`),
    title: nonEmptyString(record.title, `${path}.title`),
    display_label: nonEmptyString(record.display_label, `${path}.display_label`),
    flash_label: nonEmptyString(record.flash_label, `${path}.flash_label`),
    route_nodes: record.route_nodes.map((node, index) =>
      parseRouteNode(node, `${path}.route_nodes[${index}]`),
    ),
    marker_lane_label: nonEmptyString(
      record.marker_lane_label,
      `${path}.marker_lane_label`,
    ),
    freshness_label: nonEmptyString(
      record.freshness_label,
      `${path}.freshness_label`,
    ),
  };
}

function parseScalpSite(value: unknown, path: string): ScalpSitePresentation {
  const record = exactRecord(value, ["id", "label", "x", "y", "kind"], path);
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    label: nonEmptyString(record.label, `${path}.label`),
    x: finiteNumber(record.x, `${path}.x`),
    y: finiteNumber(record.y, `${path}.y`),
    kind: oneOf(record.kind, ["scalp", "auxiliary"] as const, `${path}.kind`),
  };
}

function isRecord(value: unknown): value is UncheckedRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactRecord(
  value: unknown,
  expectedKeys: readonly string[],
  path: string,
): UncheckedRecord {
  if (!isRecord(value)) malformed(path, "be an object");

  const expected = new Set(expectedKeys);
  const missing = expectedKeys.filter(
    (key) => !Object.prototype.hasOwnProperty.call(value, key),
  );
  const unexpected = Object.keys(value).filter((key) => !expected.has(key));
  if (missing.length > 0 || unexpected.length > 0) {
    const details = [
      missing.length > 0 ? `missing ${missing.join(", ")}` : "",
      unexpected.length > 0 ? `unexpected ${unexpected.join(", ")}` : "",
    ]
      .filter(Boolean)
      .join("; ");
    malformed(path, `contain exactly the declared fields (${details})`);
  }
  return value;
}

function extensibleRecord(
  value: unknown,
  requiredKeys: readonly string[],
  path: string,
): UncheckedRecord {
  if (!isRecord(value)) malformed(path, "be an object");

  const missing = requiredKeys.filter(
    (key) => !Object.prototype.hasOwnProperty.call(value, key),
  );
  if (missing.length > 0) {
    malformed(path, `contain the required fields (missing ${missing.join(", ")})`);
  }
  return value;
}

function stringValue(value: unknown, path: string): string {
  if (typeof value !== "string") malformed(path, "be a string");
  return value;
}

function nonEmptyString(value: unknown, path: string): string {
  const parsed = stringValue(value, path);
  if (parsed.length === 0) malformed(path, "be a non-empty string");
  return parsed;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") malformed(path, "be a boolean");
  return value;
}

function integerValue(value: unknown, path: string, minimum?: number): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    malformed(path, "be an integer");
  }
  if (minimum !== undefined && value < minimum) {
    malformed(path, `be an integer greater than or equal to ${minimum}`);
  }
  return value;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    malformed(path, "be a finite number");
  }
  return value;
}

function oneOf<const Values extends readonly string[]>(
  value: unknown,
  options: Values,
  path: string,
): Values[number] {
  if (typeof value !== "string" || !options.includes(value)) {
    malformed(path, `be one of ${options.join(", ")}`);
  }
  return value as Values[number];
}

function nullValue(value: unknown, path: string): null {
  if (value !== null) malformed(path, "be null");
  return null;
}

function jsonValue(value: unknown, path: string): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") return finiteNumber(value, path);
  if (Array.isArray(value)) {
    return value.map((item, index) => jsonValue(item, `${path}[${index}]`));
  }
  return jsonObject(value, path);
}

function jsonObject(value: unknown, path: string): JsonObject {
  if (!isRecord(value)) malformed(path, "be a JSON object");
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      jsonValue(item, `${path}.${key}`),
    ]),
  );
}

function stringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) malformed(path, "be an array");
  return value.map((item, index) =>
    stringValue(item, `${path}[${index}]`),
  );
}

function numberMap(value: unknown, path: string): Record<string, number> {
  if (!isRecord(value)) malformed(path, "be an object of finite numbers");
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      finiteNumber(item, `${path}.${key}`),
    ]),
  );
}

function digest(value: unknown, path: string): string {
  const parsed = stringValue(value, path);
  if (!SHA256_DIGEST.test(parsed)) {
    malformed(path, "be a lowercase sha256 digest");
  }
  return parsed;
}

function parsePolicyAgent(value: unknown, path: string): PolicyAgentIdentity {
  const record = exactRecord(value, ["id", "name"], path);
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    name: nonEmptyString(record.name, `${path}.name`),
  };
}

function parseEnvironmentValidation(
  value: unknown,
  path: string,
): EnvironmentValidationSummary {
  const record = exactRecord(value, ["status", "summary", "checks"], path);
  return {
    status: oneOf(record.status, ["valid"] as const, `${path}.status`),
    summary: stringValue(record.summary, `${path}.summary`),
    checks: stringArray(record.checks, `${path}.checks`),
  };
}

function parseEnvironmentSummary(value: unknown): EnvironmentSummary {
  const path = "EnvironmentSummary";
  const record = exactRecord(
    value,
    [
      "environment_id",
      "scenario_id",
      "scenario_ids",
      "name",
      "description",
      "simulation_label",
      "actions",
      "visualization",
      "validation",
      "hidden_state_exposed",
      "policy_agents",
    ],
    path,
  );
  if (record.hidden_state_exposed !== false) {
    malformed(`${path}.hidden_state_exposed`, "be the literal false");
  }
  if (!Array.isArray(record.policy_agents)) {
    malformed(`${path}.policy_agents`, "be an array");
  }
  if (!Array.isArray(record.actions)) {
    malformed(`${path}.actions`, "be an array");
  }
  return {
    environment_id: stringValue(
      record.environment_id,
      `${path}.environment_id`,
    ),
    scenario_id: stringValue(record.scenario_id, `${path}.scenario_id`),
    scenario_ids: stringArray(record.scenario_ids, `${path}.scenario_ids`),
    name: stringValue(record.name, `${path}.name`),
    description: stringValue(record.description, `${path}.description`),
    simulation_label: stringValue(
      record.simulation_label,
      `${path}.simulation_label`,
    ),
    actions: record.actions.map((action, index) =>
      parseActionPresentation(action, `${path}.actions[${index}]`),
    ),
    visualization: parseVisualization(
      record.visualization,
      `${path}.visualization`,
    ),
    validation: parseEnvironmentValidation(
      record.validation,
      `${path}.validation`,
    ),
    hidden_state_exposed: false,
    policy_agents: record.policy_agents.map((agent, index) =>
      parsePolicyAgent(agent, `${path}.policy_agents[${index}]`),
    ),
  };
}

function parseDraftSite(value: unknown, path: string): DraftSite {
  const record = extensibleRecord(
    value,
    ["id", "label", "x", "y", "kind"],
    path,
  );
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    label: nonEmptyString(record.label, `${path}.label`),
    x: finiteNumber(record.x, `${path}.x`),
    y: finiteNumber(record.y, `${path}.y`),
    kind: oneOf(record.kind, ["scalp", "auxiliary"] as const, `${path}.kind`),
  };
}

function parseDraftApparatus(value: unknown, path: string): DraftApparatus {
  const record = extensibleRecord(
    value,
    [
      "kind",
      "label",
      "recording_input_capacity",
      "coordinate_system",
      "scientific_claim",
      "sites",
    ],
    path,
  );
  if (!Array.isArray(record.sites)) malformed(`${path}.sites`, "be an array");
  return {
    kind: oneOf(record.kind, ["eeg"] as const, `${path}.kind`),
    label: nonEmptyString(record.label, `${path}.label`),
    recording_input_capacity: integerValue(
      record.recording_input_capacity,
      `${path}.recording_input_capacity`,
      1,
    ),
    coordinate_system: nonEmptyString(
      record.coordinate_system,
      `${path}.coordinate_system`,
    ),
    scientific_claim: nonEmptyString(
      record.scientific_claim,
      `${path}.scientific_claim`,
    ),
    sites: record.sites.map((site, index) =>
      parseDraftSite(site, `${path}.sites[${index}]`),
    ),
  };
}

function parseDraftMontage(value: unknown, path: string): DraftMontage {
  const record = extensibleRecord(
    value,
    ["recording_sites", "reference", "ground"],
    path,
  );
  return {
    recording_sites: stringArray(
      record.recording_sites,
      `${path}.recording_sites`,
    ),
    reference: nonEmptyString(record.reference, `${path}.reference`),
    ground: nonEmptyString(record.ground, `${path}.ground`),
  };
}

function parseDraftAcquisitionProfile(
  value: unknown,
  path: string,
): DraftAcquisitionProfile {
  const record = extensibleRecord(
    value,
    ["sampling_hz", "online_bandpass_hz", "notch_hz"],
    path,
  );
  if (
    !Array.isArray(record.online_bandpass_hz) ||
    record.online_bandpass_hz.length !== 2
  ) {
    malformed(`${path}.online_bandpass_hz`, "be a two-number array");
  }
  return {
    sampling_hz: finiteNumber(record.sampling_hz, `${path}.sampling_hz`),
    online_bandpass_hz: [
      finiteNumber(
        record.online_bandpass_hz[0],
        `${path}.online_bandpass_hz[0]`,
      ),
      finiteNumber(
        record.online_bandpass_hz[1],
        `${path}.online_bandpass_hz[1]`,
      ),
    ],
    notch_hz: finiteNumber(record.notch_hz, `${path}.notch_hz`),
  };
}

function parseDraftProcedure(value: unknown, path: string): DraftProcedure {
  const record = extensibleRecord(
    value,
    ["name", "montage", "acquisition_profile"],
    path,
  );
  return {
    name: nonEmptyString(record.name, `${path}.name`),
    montage: parseDraftMontage(record.montage, `${path}.montage`),
    acquisition_profile: parseDraftAcquisitionProfile(
      record.acquisition_profile,
      `${path}.acquisition_profile`,
    ),
  };
}

function parseDraftNote(value: unknown, path: string): DraftNote {
  const record = extensibleRecord(
    value,
    ["id", "filename", "content", "verification_status", "run_control"],
    path,
  );
  if (record.run_control !== false) {
    malformed(`${path}.run_control`, "be the literal false");
  }
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    filename: nonEmptyString(record.filename, `${path}.filename`),
    content: stringValue(record.content, `${path}.content`),
    verification_status: oneOf(
      record.verification_status,
      ["unverified_descriptive_input"] as const,
      `${path}.verification_status`,
    ),
    run_control: false,
  };
}

function parseDraftHistory(value: unknown, path: string): DraftHistory {
  const record = exactRecord(value, ["can_undo", "can_redo"], path);
  return {
    can_undo: booleanValue(record.can_undo, `${path}.can_undo`),
    can_redo: booleanValue(record.can_redo, `${path}.can_redo`),
  };
}

function parseDraftActor(value: unknown, path: string): DraftActor {
  const record = exactRecord(value, ["id", "name", "role"], path);
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    name: nonEmptyString(record.name, `${path}.name`),
    role: oneOf(
      record.role,
      ["authoring_assistant", "environment_author", "system"] as const,
      `${path}.role`,
    ),
  };
}

function parseDraftLastChange(value: unknown, path: string): DraftLastChange {
  const record = exactRecord(value, ["operation", "summary", "actor"], path);
  return {
    operation: nonEmptyString(record.operation, `${path}.operation`),
    summary: nonEmptyString(record.summary, `${path}.summary`),
    actor: parseDraftActor(record.actor, `${path}.actor`),
  };
}

function parseAuthoringAssistant(
  value: unknown,
  path: string,
): AuthoringAssistantIdentity {
  const record = exactRecord(value, ["id", "name"], path);
  return {
    id: nonEmptyString(record.id, `${path}.id`),
    name: nonEmptyString(record.name, `${path}.name`),
  };
}

function parseEnvironmentDraft(value: unknown): EnvironmentDraft {
  const path = "EnvironmentDraft";
  const record = exactRecord(
    value,
    [
      "draft_id",
      "revision",
      "revision_digest",
      "environment_id",
      "title",
      "apparatus",
      "procedure",
      "notes",
      "history",
      "last_change",
      "authoring_assistant",
    ],
    path,
  );
  if (!Array.isArray(record.notes)) malformed(`${path}.notes`, "be an array");
  return {
    draft_id: nonEmptyString(record.draft_id, `${path}.draft_id`),
    revision: integerValue(record.revision, `${path}.revision`, 1),
    revision_digest: digest(record.revision_digest, `${path}.revision_digest`),
    environment_id: nonEmptyString(
      record.environment_id,
      `${path}.environment_id`,
    ),
    title: nonEmptyString(record.title, `${path}.title`),
    apparatus: parseDraftApparatus(record.apparatus, `${path}.apparatus`),
    procedure: parseDraftProcedure(record.procedure, `${path}.procedure`),
    notes: record.notes.map((note, index) =>
      parseDraftNote(note, `${path}.notes[${index}]`),
    ),
    history: parseDraftHistory(record.history, `${path}.history`),
    last_change: parseDraftLastChange(record.last_change, `${path}.last_change`),
    authoring_assistant: parseAuthoringAssistant(
      record.authoring_assistant,
      `${path}.authoring_assistant`,
    ),
  };
}

function parseDraftCommandResponse(value: unknown): DraftCommandResponse {
  const path = "DraftCommandResponse";
  const record = exactRecord(value, ["draft", "result"], path);
  const result = exactRecord(
    record.result,
    ["status", "summary"],
    `${path}.result`,
  );
  return {
    draft: parseEnvironmentDraft(record.draft),
    result: {
      status: oneOf(
        result.status,
        ["applied", "unsupported"] as const,
        `${path}.result.status`,
      ),
      summary: nonEmptyString(result.summary, `${path}.result.summary`),
    },
  };
}

function parseFrozenEnvironment(value: unknown): FrozenEnvironment {
  const path = "FrozenEnvironment";
  const record = exactRecord(
    value,
    [
      "frozen_environment_id",
      "bundle_revision",
      "revision_digest",
      "scenario_id",
      "scenario_ids",
      "draft_revision",
      "procedure",
    ],
    path,
  );
  return {
    frozen_environment_id: nonEmptyString(
      record.frozen_environment_id,
      `${path}.frozen_environment_id`,
    ),
    bundle_revision: nonEmptyString(
      record.bundle_revision,
      `${path}.bundle_revision`,
    ),
    revision_digest: digest(record.revision_digest, `${path}.revision_digest`),
    scenario_id: nonEmptyString(record.scenario_id, `${path}.scenario_id`),
    scenario_ids: stringArray(record.scenario_ids, `${path}.scenario_ids`),
    draft_revision: integerValue(
      record.draft_revision,
      `${path}.draft_revision`,
      1,
    ),
    procedure: parseDraftProcedure(record.procedure, `${path}.procedure`),
  };
}

function parseTraceAction(value: unknown, path: string): TraceAction {
  const record = exactRecord(value, ["type", "arguments"], path);
  return {
    type: nonEmptyString(record.type, `${path}.type`),
    arguments: jsonObject(record.arguments, `${path}.arguments`),
  };
}

function parseTraceTransition(value: unknown, path: string): TraceTransition {
  const record = exactRecord(
    value,
    ["id", "from_state", "to_state", "state_revision"],
    path,
  );
  return {
    id: stringValue(record.id, `${path}.id`),
    from_state: stringValue(record.from_state, `${path}.from_state`),
    to_state: stringValue(record.to_state, `${path}.to_state`),
    state_revision: integerValue(
      record.state_revision,
      `${path}.state_revision`,
      0,
    ),
  };
}

function parseVerifierResult(value: unknown, path: string): VerifierResult {
  const hasOutcomeCategory =
    isRecord(value) && Object.prototype.hasOwnProperty.call(value, "outcome_category");
  const record = exactRecord(
    value,
    hasOutcomeCategory
      ? [
          "verifier_id",
          "result_version",
          "passed",
          "terminal_disposition",
          "outcome_category",
          "summary",
          "metrics",
          "evidence",
          "reasons",
        ]
      : [
          "verifier_id",
          "result_version",
          "passed",
          "terminal_disposition",
          "summary",
          "metrics",
          "evidence",
          "reasons",
        ],
    path,
  );
  return {
    verifier_id: nonEmptyString(record.verifier_id, `${path}.verifier_id`),
    result_version: nonEmptyString(
      record.result_version,
      `${path}.result_version`,
    ),
    passed: booleanValue(record.passed, `${path}.passed`),
    terminal_disposition: oneOf(
      record.terminal_disposition,
      ["recovered", "aborted", "failed"] as const,
      `${path}.terminal_disposition`,
    ),
    outcome_category:
      !hasOutcomeCategory || record.outcome_category === null
        ? null
        : nonEmptyString(record.outcome_category, `${path}.outcome_category`),
    summary: nonEmptyString(record.summary, `${path}.summary`),
    metrics: numberMap(record.metrics, `${path}.metrics`),
    evidence: jsonObject(record.evidence, `${path}.evidence`),
    reasons: stringArray(record.reasons, `${path}.reasons`),
  };
}

function parseTraceEvent(value: unknown, path: string): TraceEvent {
  const record = exactRecord(
    value,
    [
      "sequence",
      "type",
      "summary",
      "observation",
      "action",
      "transition",
      "verifier",
    ],
    path,
  );
  const sequence = integerValue(record.sequence, `${path}.sequence`, 1);
  const summary = nonEmptyString(record.summary, `${path}.summary`);
  const type = oneOf(
    record.type,
    ["observation", "action", "transition", "verifier"] as const,
    `${path}.type`,
  );

  switch (type) {
    case "observation":
      return {
        sequence,
        type,
        summary,
        observation: jsonObject(record.observation, `${path}.observation`),
        action: nullValue(record.action, `${path}.action`),
        transition: nullValue(record.transition, `${path}.transition`),
        verifier: nullValue(record.verifier, `${path}.verifier`),
      };
    case "action":
      return {
        sequence,
        type,
        summary,
        observation: nullValue(record.observation, `${path}.observation`),
        action: parseTraceAction(record.action, `${path}.action`),
        transition: nullValue(record.transition, `${path}.transition`),
        verifier: nullValue(record.verifier, `${path}.verifier`),
      };
    case "transition":
      return {
        sequence,
        type,
        summary,
        observation: nullValue(record.observation, `${path}.observation`),
        action: nullValue(record.action, `${path}.action`),
        transition: parseTraceTransition(
          record.transition,
          `${path}.transition`,
        ),
        verifier: nullValue(record.verifier, `${path}.verifier`),
      };
    case "verifier":
      return {
        sequence,
        type,
        summary,
        observation: nullValue(record.observation, `${path}.observation`),
        action: nullValue(record.action, `${path}.action`),
        transition: nullValue(record.transition, `${path}.transition`),
        verifier: parseVerifierResult(record.verifier, `${path}.verifier`),
      };
  }
}

function parseRunLineage(value: unknown, path: string): RunLineage {
  const record = exactRecord(value, ["operation", "source_run_id"], path);
  return {
    operation: oneOf(
      record.operation,
      ["start", "reset", "replay"] as const,
      `${path}.operation`,
    ),
    source_run_id:
      record.source_run_id === null
        ? null
        : stringValue(record.source_run_id, `${path}.source_run_id`),
  };
}

function parseTraceHeader(value: unknown, path: string): CanonicalTraceHeader {
  const record = exactRecord(
    value,
    [
      "trace_version",
      "runtime_revision",
      "bundle_id",
      "bundle_revision",
      "revision_digest",
      "scenario_id",
      "split",
      "seed",
      "scenario_digest",
      "initial_state_digest",
      "policy_agent",
    ],
    path,
  );
  return {
    trace_version: oneOf(
      record.trace_version,
      ["1.0"] as const,
      `${path}.trace_version`,
    ),
    runtime_revision: oneOf(
      record.runtime_revision,
      ["science-environment-runtime/1"] as const,
      `${path}.runtime_revision`,
    ),
    bundle_id: stringValue(record.bundle_id, `${path}.bundle_id`),
    bundle_revision: stringValue(
      record.bundle_revision,
      `${path}.bundle_revision`,
    ),
    revision_digest: digest(record.revision_digest, `${path}.revision_digest`),
    scenario_id: stringValue(record.scenario_id, `${path}.scenario_id`),
    split: stringValue(record.split, `${path}.split`),
    seed: integerValue(record.seed, `${path}.seed`),
    scenario_digest: digest(record.scenario_digest, `${path}.scenario_digest`),
    initial_state_digest: digest(
      record.initial_state_digest,
      `${path}.initial_state_digest`,
    ),
    policy_agent: parsePolicyAgent(record.policy_agent, `${path}.policy_agent`),
  };
}

function parseRunSnapshot(value: unknown): RunSnapshot {
  const path = "RunSnapshot";
  const record = exactRecord(
    value,
    [
      "run_id",
      "scenario_id",
      "revision_digest",
      "scenario_digest",
      "policy_agent",
      "status",
      "observation",
      "permitted_actions",
      "trace",
      "trace_digest",
      "verifier_result",
      "result_digest",
      "lineage",
      "trace_header",
    ],
    path,
  );
  if (!Array.isArray(record.trace)) malformed(`${path}.trace`, "be an array");
  return {
    run_id: nonEmptyString(record.run_id, `${path}.run_id`),
    scenario_id: nonEmptyString(record.scenario_id, `${path}.scenario_id`),
    revision_digest: digest(record.revision_digest, `${path}.revision_digest`),
    scenario_digest: digest(record.scenario_digest, `${path}.scenario_digest`),
    policy_agent: parsePolicyAgent(record.policy_agent, `${path}.policy_agent`),
    status: oneOf(
      record.status,
      ["active", "awaiting_verification", "completed"] as const,
      `${path}.status`,
    ),
    observation: jsonObject(record.observation, `${path}.observation`),
    permitted_actions: stringArray(
      record.permitted_actions,
      `${path}.permitted_actions`,
    ),
    trace: record.trace.map((event, index) =>
      parseTraceEvent(event, `${path}.trace[${index}]`),
    ),
    trace_digest: digest(record.trace_digest, `${path}.trace_digest`),
    verifier_result:
      record.verifier_result === null
        ? null
        : parseVerifierResult(
            record.verifier_result,
            `${path}.verifier_result`,
          ),
    result_digest:
      record.result_digest === null
        ? null
        : digest(record.result_digest, `${path}.result_digest`),
    lineage: parseRunLineage(record.lineage, `${path}.lineage`),
    trace_header: parseTraceHeader(record.trace_header, `${path}.trace_header`),
  };
}

function parseReplayReport(value: unknown, path: string): ReplayReport {
  const record = exactRecord(
    value,
    [
      "source_run_id",
      "replay_run_id",
      "trace_matches",
      "result_matches",
      "source_trace_digest",
      "replay_trace_digest",
      "source_result_digest",
      "replay_result_digest",
    ],
    path,
  );
  return {
    source_run_id: stringValue(record.source_run_id, `${path}.source_run_id`),
    replay_run_id: stringValue(record.replay_run_id, `${path}.replay_run_id`),
    trace_matches: booleanValue(record.trace_matches, `${path}.trace_matches`),
    result_matches: booleanValue(
      record.result_matches,
      `${path}.result_matches`,
    ),
    source_trace_digest: digest(
      record.source_trace_digest,
      `${path}.source_trace_digest`,
    ),
    replay_trace_digest: digest(
      record.replay_trace_digest,
      `${path}.replay_trace_digest`,
    ),
    source_result_digest: digest(
      record.source_result_digest,
      `${path}.source_result_digest`,
    ),
    replay_result_digest: digest(
      record.replay_result_digest,
      `${path}.replay_result_digest`,
    ),
  };
}

function parseReplayResponse(value: unknown): ReplayResponse {
  const path = "ReplayResponse";
  const record = exactRecord(value, ["snapshot", "replay"], path);
  return {
    snapshot: parseRunSnapshot(record.snapshot),
    replay: parseReplayReport(record.replay, `${path}.replay`),
  };
}

function errorDetail(value: unknown): string | undefined {
  if (!isRecord(value)) return undefined;
  return typeof value.detail === "string" && value.detail.length > 0
    ? value.detail
    : undefined;
}

async function request<T>(
  path: string,
  parse: (payload: unknown) => T,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body !== undefined) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...init, headers });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      response.ok
        ? `Invalid response from ${path}: expected JSON.`
        : `Request failed (${response.status}).`,
    );
  }

  if (!response.ok) {
    throw new Error(
      errorDetail(payload) ?? `Request failed (${response.status}).`,
    );
  }

  try {
    return parse(payload);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "malformed payload";
    throw new Error(`Invalid response from ${path}: ${detail}`);
  }
}

export const environmentApi = {
  async getEnvironment(): Promise<EnvironmentSummary> {
    return request("/api/environment", parseEnvironmentSummary);
  },

  async start(
    scenarioId: string,
    policyAgent: string,
    frozenEnvironmentId: string,
  ): Promise<RunSnapshot> {
    return request("/api/runs", parseRunSnapshot, {
      method: "POST",
      body: JSON.stringify({
        scenario_id: scenarioId,
        policy_agent: policyAgent,
        frozen_environment_id: frozenEnvironmentId,
      }),
    });
  },

  async get(runId: string): Promise<RunSnapshot> {
    return request(`/api/runs/${runId}`, parseRunSnapshot);
  },

  async apply(
    runId: string,
    type: string,
    input: JsonObject = {},
  ): Promise<RunSnapshot> {
    return request(`/api/runs/${runId}/actions`, parseRunSnapshot, {
      method: "POST",
      body: JSON.stringify({ type, input }),
    });
  },

  async verify(runId: string): Promise<RunSnapshot> {
    return request(`/api/runs/${runId}/verify`, parseRunSnapshot, {
      method: "POST",
    });
  },

  async reset(runId: string): Promise<RunSnapshot> {
    return request(`/api/runs/${runId}/reset`, parseRunSnapshot, {
      method: "POST",
    });
  },

  async replay(runId: string): Promise<ReplayResponse> {
    return request(`/api/runs/${runId}/replay`, parseReplayResponse, {
      method: "POST",
    });
  },
};

export const draftApi = {
  async get(): Promise<EnvironmentDraft> {
    return request("/api/draft", parseEnvironmentDraft);
  },

  async command(
    command: string,
    expectedRevision: number,
  ): Promise<DraftCommandResponse> {
    return request("/api/draft/commands", parseDraftCommandResponse, {
      method: "POST",
      body: JSON.stringify({
        command,
        expected_revision: expectedRevision,
      }),
    });
  },

  async undo(expectedRevision: number): Promise<EnvironmentDraft> {
    return request("/api/draft/undo", parseEnvironmentDraft, {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
  },

  async redo(expectedRevision: number): Promise<EnvironmentDraft> {
    return request("/api/draft/redo", parseEnvironmentDraft, {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
  },

  async restore(expectedRevision: number): Promise<EnvironmentDraft> {
    return request("/api/draft/restore", parseEnvironmentDraft, {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
  },

  async stageNote(
    filename: string,
    content: string,
    expectedRevision: number,
  ): Promise<EnvironmentDraft> {
    return request("/api/draft/notes", parseEnvironmentDraft, {
      method: "POST",
      body: JSON.stringify({
        filename,
        content,
        expected_revision: expectedRevision,
      }),
    });
  },

  async freeze(expectedRevision: number): Promise<FrozenEnvironment> {
    return request("/api/draft/freeze", parseFrozenEnvironment, {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
  },
};
