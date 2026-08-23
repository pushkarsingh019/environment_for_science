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
  EnvironmentCatalogEntry,
  EnvironmentDraft,
  EnvironmentSummary,
  EnvironmentValidationSummary,
  EvaluationAttemptSummary,
  EvaluationCalibration,
  EvaluationCalibrationLevel,
  EvaluationInfrastructureError,
  EvaluationInteraction,
  EvaluationLocalGemmaAttestation,
  EvaluationMessage,
  EvaluationModelIdentity,
  EvaluationPlan,
  EvaluationProgress,
  EvaluationReplay,
  EvaluationReplayReport,
  EvaluationResponseRecord,
  EvaluationRuntimeExecution,
  EvaluationRuntimeDistribution,
  EvaluationSnapshot,
  EvaluationStatus,
  EvaluationSummary,
  EvaluationTokenUsage,
  EvaluationToolCall,
  EvaluationToolResult,
  FrozenEnvironment,
  JsonObject,
  JsonValue,
  MesoscopePortabilityReplay,
  MesoscopePortabilityReport,
  MesoscopePortabilityResult,
  MesoscopeProvenance,
  PolicyAgentIdentity,
  ProviderReadinessSummary,
  ReplayReport,
  ReplayResponse,
  RouteNodePresentation,
  ScalpSitePresentation,
  RunLineage,
  RunSnapshot,
  SealedEnvironment,
  SeededScenarioSummary,
  TraceAction,
  TraceEvent,
  TraceTransition,
  VerifierResult,
} from "./types";

type UncheckedRecord = Record<string, unknown>;

const SHA256_DIGEST = /^sha256:[0-9a-f]{64}$/;
const RAW_SHA256_DIGEST = /^[0-9a-f]{64}$/;
const COMPATIBLE_EXTENSION_KEY = /^(?:future|x)_[a-z0-9]+(?:_[a-z0-9]+)*$/;

function malformed(path: string, expectation: string): never {
  throw new Error(`${path} must ${expectation}.`);
}

function parseActionPresentation(
  value: unknown,
  path: string,
): ActionPresentation {
  const record = compatibleRecord(
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
  const record = extensibleRecord(
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

function parseMesoscopeProvenance(
  value: unknown,
  path: string,
): MesoscopeProvenance {
  const record = compatibleRecord(
    value,
    ["classification", "citation_ids", "note"],
    path,
  );
  const citationIds = stringArray(record.citation_ids, `${path}.citation_ids`);
  if (citationIds.length === 0 || citationIds.some((citation) => citation.length === 0)) {
    malformed(`${path}.citation_ids`, "contain at least one citation identity");
  }
  return {
    classification: oneOf(
      record.classification,
      ["INSTRUMENT FACT", "SOFTWARE FACT", "SIMULATION CHOICE"] as const,
      `${path}.classification`,
    ),
    citation_ids: citationIds,
    note: nonEmptyString(record.note, `${path}.note`),
  };
}

function parseVisualization(
  value: unknown,
  path: string,
): EnvironmentSummary["visualization"] {
  if (isRecord(value) && value.kind === "mesoscope_handoff_v1") {
    const record = compatibleRecord(
      value,
      [
        "kind",
        "title",
        "synthetic_label",
        "sealed_label",
        "survey_label",
        "raw_view_label",
        "spatial_view_label",
        "details_toggle_label",
        "profile_provenance",
        "plan_provenance",
        "package_provenance",
        "region_ids",
        "depth_labels",
      ],
      path,
    );
    const regionIds = stringArray(record.region_ids, `${path}.region_ids`);
    const depthLabels = stringArray(record.depth_labels, `${path}.depth_labels`);
    if (!Array.isArray(record.package_provenance) || record.package_provenance.length < 2) {
      malformed(`${path}.package_provenance`, "contain fact and proposal provenance");
    }
    if (regionIds.join("|") !== "R1|R2|R3|R4") {
      malformed(`${path}.region_ids`, "contain R1 through R4 in order");
    }
    if (depthLabels.join("|") !== "Z-A|Z-B") {
      malformed(`${path}.depth_labels`, "contain Z-A and Z-B in order");
    }
    return {
      kind: "mesoscope_handoff_v1",
      title: nonEmptyString(record.title, `${path}.title`),
      synthetic_label: oneOf(
        record.synthetic_label,
        ["SYNTHETIC"] as const,
        `${path}.synthetic_label`,
      ),
      sealed_label: oneOf(
        record.sealed_label,
        ["SEALED — DISCONNECTED FROM HARDWARE"] as const,
        `${path}.sealed_label`,
      ),
      survey_label: nonEmptyString(record.survey_label, `${path}.survey_label`),
      raw_view_label: nonEmptyString(record.raw_view_label, `${path}.raw_view_label`),
      spatial_view_label: nonEmptyString(
        record.spatial_view_label,
        `${path}.spatial_view_label`,
      ),
      details_toggle_label: nonEmptyString(
        record.details_toggle_label,
        `${path}.details_toggle_label`,
      ),
      profile_provenance: parseMesoscopeProvenance(
        record.profile_provenance,
        `${path}.profile_provenance`,
      ),
      plan_provenance: parseMesoscopeProvenance(
        record.plan_provenance,
        `${path}.plan_provenance`,
      ),
      package_provenance: record.package_provenance.map((item, index) =>
        parseMesoscopeProvenance(item, `${path}.package_provenance[${index}]`)
      ),
      region_ids: ["R1", "R2", "R3", "R4"],
      depth_labels: ["Z-A", "Z-B"],
    };
  }
  if (isRecord(value) && value.kind === "eeg_preflight_v1") {
    const record = extensibleRecord(
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
  const record = extensibleRecord(
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
  const record = extensibleRecord(value, ["id", "label", "x", "y", "kind"], path);
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

function compatibleRecord(
  value: unknown,
  requiredKeys: readonly string[],
  path: string,
): UncheckedRecord {
  const record = extensibleRecord(value, requiredKeys, path);
  const required = new Set(requiredKeys);
  const incompatible = Object.keys(record).filter(
    (key) => !required.has(key) && !COMPATIBLE_EXTENSION_KEY.test(key),
  );
  if (incompatible.length > 0) {
    malformed(
      path,
      `contain only declared fields or namespaced additions (unexpected ${incompatible.join(", ")})`,
    );
  }
  return record;
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

function canonicalJsonValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJsonValue).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJsonValue(value[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
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

function parseSeededScenarioSummary(
  value: unknown,
  path: string,
): SeededScenarioSummary {
  const record = exactRecord(value, ["scenario_id", "label", "stage"], path);
  return {
    scenario_id: nonEmptyString(record.scenario_id, `${path}.scenario_id`),
    label: nonEmptyString(record.label, `${path}.label`),
    stage: oneOf(
      record.stage,
      ["preflight", "short_acquisition", "sealed_handoff"] as const,
      `${path}.stage`,
    ),
  };
}

function parseEnvironmentCatalogEntry(
  value: unknown,
  path: string,
): EnvironmentCatalogEntry {
  const record = exactRecord(
    value,
    [
      "environment_id",
      "environment_kind",
      "name",
      "navigation_label",
      "navigation_summary",
      "source_kind",
    ],
    path,
  );
  return {
    environment_id: nonEmptyString(record.environment_id, `${path}.environment_id`),
    environment_kind: oneOf(
      record.environment_kind,
      ["eeg", "mesoscope"] as const,
      `${path}.environment_kind`,
    ),
    name: nonEmptyString(record.name, `${path}.name`),
    navigation_label: nonEmptyString(
      record.navigation_label,
      `${path}.navigation_label`,
    ),
    navigation_summary: nonEmptyString(
      record.navigation_summary,
      `${path}.navigation_summary`,
    ),
    source_kind: oneOf(
      record.source_kind,
      ["editable_draft", "sealed_seed"] as const,
      `${path}.source_kind`,
    ),
  };
}

function parseEnvironmentCatalog(value: unknown): EnvironmentCatalogEntry[] {
  if (!Array.isArray(value)) malformed("EnvironmentCatalog", "be an array");
  return value.map((entry, index) =>
    parseEnvironmentCatalogEntry(entry, `EnvironmentCatalog[${index}]`),
  );
}

function parseEnvironmentSummary(value: unknown): EnvironmentSummary {
  const path = "EnvironmentSummary";
  const record = exactRecord(
    value,
    [
      "environment_id",
      "environment_kind",
      "source_kind",
      "name",
      "description",
      "simulation_label",
      "seeded_examples",
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
  if (!Array.isArray(record.seeded_examples)) {
    malformed(`${path}.seeded_examples`, "be an array");
  }
  return {
    environment_id: stringValue(
      record.environment_id,
      `${path}.environment_id`,
    ),
    environment_kind: oneOf(
      record.environment_kind,
      ["eeg", "mesoscope"] as const,
      `${path}.environment_kind`,
    ),
    source_kind: oneOf(
      record.source_kind,
      ["editable_draft", "sealed_seed"] as const,
      `${path}.source_kind`,
    ),
    name: stringValue(record.name, `${path}.name`),
    description: stringValue(record.description, `${path}.description`),
    simulation_label: stringValue(
      record.simulation_label,
      `${path}.simulation_label`,
    ),
    seeded_examples: record.seeded_examples.map((example, index) =>
      parseSeededScenarioSummary(example, `${path}.seeded_examples[${index}]`),
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
    draft_revision: integerValue(
      record.draft_revision,
      `${path}.draft_revision`,
      1,
    ),
    procedure: parseDraftProcedure(record.procedure, `${path}.procedure`),
  };
}

function parseSealedEnvironment(value: unknown): SealedEnvironment {
  const path = "SealedEnvironment";
  const record = exactRecord(
    value,
    [
      "frozen_environment_id",
      "environment_id",
      "source_kind",
      "bundle_revision",
      "revision_digest",
      "sealed_profile_id",
      "signed_plan_id",
    ],
    path,
  );
  return {
    frozen_environment_id: nonEmptyString(
      record.frozen_environment_id,
      `${path}.frozen_environment_id`,
    ),
    environment_id: nonEmptyString(record.environment_id, `${path}.environment_id`),
    source_kind: oneOf(
      record.source_kind,
      ["sealed_seed"] as const,
      `${path}.source_kind`,
    ),
    bundle_revision: nonEmptyString(record.bundle_revision, `${path}.bundle_revision`),
    revision_digest: digest(record.revision_digest, `${path}.revision_digest`),
    sealed_profile_id: nonEmptyString(
      record.sealed_profile_id,
      `${path}.sealed_profile_id`,
    ),
    signed_plan_id: nonEmptyString(
      record.signed_plan_id,
      `${path}.signed_plan_id`,
    ),
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
      ["recovered", "closed", "aborted", "failed"] as const,
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

function patternedString(value: unknown, pattern: RegExp, path: string): string {
  const parsed = nonEmptyString(value, path);
  if (!pattern.test(parsed)) malformed(path, `match ${pattern.source}`);
  return parsed;
}

function parseEvaluationStatus(value: unknown, path: string): EvaluationStatus {
  return oneOf(
    value,
    ["queued", "running", "completed", "interrupted"] as const,
    path,
  );
}

function parseEvaluationModel(
  value: unknown,
  path: string,
): EvaluationModelIdentity {
  const record = exactRecord(
    value,
    ["provider", "requested_model", "adapter_revision"],
    path,
  );
  return {
    provider: oneOf(
      record.provider,
      ["local-openai-compatible"] as const,
      `${path}.provider`,
    ),
    requested_model: oneOf(
      record.requested_model,
      ["google/gemma-4-E4B-it"] as const,
      `${path}.requested_model`,
    ),
    adapter_revision: oneOf(
      record.adapter_revision,
      ["local-gemma-openai-chat/1"] as const,
      `${path}.adapter_revision`,
    ),
  };
}

function parseEvaluationProgress(
  value: unknown,
  path: string,
): EvaluationProgress {
  const record = exactRecord(
    value,
    [
      "phase",
      "message",
      "completed_scenarios",
      "total_scenarios",
      "scientific_successes",
      "scientific_failures",
      "infrastructure_errors",
    ],
    path,
  );
  const parsed = {
    phase: parseEvaluationStatus(record.phase, `${path}.phase`),
    message: nonEmptyString(record.message, `${path}.message`),
    completed_scenarios: integerValue(
      record.completed_scenarios,
      `${path}.completed_scenarios`,
      0,
    ),
    total_scenarios: integerValue(
      record.total_scenarios,
      `${path}.total_scenarios`,
      1,
    ),
    scientific_successes: integerValue(
      record.scientific_successes,
      `${path}.scientific_successes`,
      0,
    ),
    scientific_failures: integerValue(
      record.scientific_failures,
      `${path}.scientific_failures`,
      0,
    ),
    infrastructure_errors: integerValue(
      record.infrastructure_errors,
      `${path}.infrastructure_errors`,
      0,
    ),
  };
  const outcomes = parsed.scientific_successes
    + parsed.scientific_failures
    + parsed.infrastructure_errors;
  if (
    outcomes !== parsed.completed_scenarios
    || parsed.completed_scenarios > parsed.total_scenarios
  ) {
    malformed(path, "contain internally consistent outcome counts");
  }
  return parsed;
}

function parseEvaluationCalibrationLevel(
  value: unknown,
  path: string,
): EvaluationCalibrationLevel {
  const record = exactRecord(
    value,
    [
      "level",
      "label",
      "total_scenarios",
      "completed_scenarios",
      "scientific_successes",
      "scientific_failures",
      "infrastructure_errors",
      "has_success_and_failure",
    ],
    path,
  );
  const parsedLevel = integerValue(record.level, `${path}.level`, 0);
  if (![0, 1, 2, 3, 4, 5].includes(parsedLevel)) {
    malformed(`${path}.level`, "be an approved difficulty level");
  }
  const level = parsedLevel as EvaluationCalibrationLevel["level"];
  const totalScenarios = integerValue(
    record.total_scenarios,
    `${path}.total_scenarios`,
    1,
  );
  const completedScenarios = integerValue(
    record.completed_scenarios,
    `${path}.completed_scenarios`,
    0,
  );
  const scientificSuccesses = integerValue(
    record.scientific_successes,
    `${path}.scientific_successes`,
    0,
  );
  const scientificFailures = integerValue(
    record.scientific_failures,
    `${path}.scientific_failures`,
    0,
  );
  const infrastructureErrors = integerValue(
    record.infrastructure_errors,
    `${path}.infrastructure_errors`,
    0,
  );
  const mixed = booleanValue(
    record.has_success_and_failure,
    `${path}.has_success_and_failure`,
  );
  if (
    scientificSuccesses + scientificFailures + infrastructureErrors
      !== completedScenarios
    || completedScenarios > totalScenarios
    || mixed !== (scientificSuccesses > 0 && scientificFailures > 0)
  ) {
    malformed(path, "contain internally consistent level outcomes");
  }
  return {
    level,
    label: nonEmptyString(record.label, `${path}.label`),
    total_scenarios: totalScenarios,
    completed_scenarios: completedScenarios,
    scientific_successes: scientificSuccesses,
    scientific_failures: scientificFailures,
    infrastructure_errors: infrastructureErrors,
    has_success_and_failure: mixed,
  };
}

function parseEvaluationCalibration(
  value: unknown,
  path: string,
): EvaluationCalibration {
  const record = exactRecord(
    value,
    [
      "status",
      "summary",
      "scientific_accuracy",
      "target_accuracy_minimum",
      "target_accuracy_maximum",
      "overall_accuracy_in_target",
      "levels_1_and_2_mixed",
      "no_infrastructure_errors",
      "authenticated_local_runtime",
      "levels",
    ],
    path,
  );
  if (!Array.isArray(record.levels)) malformed(`${path}.levels`, "be an array");
  const levels = record.levels.map((item, index) =>
    parseEvaluationCalibrationLevel(item, `${path}.levels[${index}]`)
  );
  if (
    levels.length !== 6
    || levels.some((level, index) => level.level !== index)
  ) {
    malformed(`${path}.levels`, "contain the six ordered difficulty levels");
  }
  const minimum = finiteNumber(
    record.target_accuracy_minimum,
    `${path}.target_accuracy_minimum`,
  );
  const maximum = finiteNumber(
    record.target_accuracy_maximum,
    `${path}.target_accuracy_maximum`,
  );
  if (minimum !== 0.2 || maximum !== 0.7) {
    malformed(path, "retain the approved 20% to 70% accuracy band");
  }
  const scientificAccuracy = record.scientific_accuracy === null
    ? null
    : finiteNumber(record.scientific_accuracy, `${path}.scientific_accuracy`);
  if (
    scientificAccuracy !== null
    && (scientificAccuracy < 0 || scientificAccuracy > 1)
  ) {
    malformed(`${path}.scientific_accuracy`, "be between zero and one");
  }
  const overallInTarget = booleanValue(
    record.overall_accuracy_in_target,
    `${path}.overall_accuracy_in_target`,
  );
  const levelsMixed = booleanValue(
    record.levels_1_and_2_mixed,
    `${path}.levels_1_and_2_mixed`,
  );
  const noInfrastructure = booleanValue(
    record.no_infrastructure_errors,
    `${path}.no_infrastructure_errors`,
  );
  const authenticatedRuntime = booleanValue(
    record.authenticated_local_runtime,
    `${path}.authenticated_local_runtime`,
  );
  const calibrationStatus = oneOf(
    record.status,
    ["pending", "ready", "not_ready"] as const,
    `${path}.status`,
  );
  const levelsComplete = levels.every(
    (level) => level.completed_scenarios === level.total_scenarios,
  );
  const finalizedNoInfrastructure = levelsComplete
    && levels.every((level) => level.infrastructure_errors === 0);
  const ready = levelsComplete
    && overallInTarget
    && levelsMixed
    && noInfrastructure
    && authenticatedRuntime;
  if (
    overallInTarget !== (
      scientificAccuracy !== null
      && scientificAccuracy >= minimum
      && scientificAccuracy <= maximum
    )
    || levelsMixed !== (
      levels[1].has_success_and_failure && levels[2].has_success_and_failure
    )
    || (calibrationStatus === "pending" && (
      noInfrastructure || authenticatedRuntime
    ))
    || (calibrationStatus !== "pending"
      && noInfrastructure !== finalizedNoInfrastructure)
    || (authenticatedRuntime && !levelsComplete)
    || (calibrationStatus === "ready" && !ready)
    || (calibrationStatus === "not_ready" && (!levelsComplete || ready))
  ) {
    malformed(path, "contain internally consistent readiness evidence");
  }
  return {
    status: calibrationStatus,
    summary: nonEmptyString(record.summary, `${path}.summary`),
    scientific_accuracy: scientificAccuracy,
    target_accuracy_minimum: 0.2,
    target_accuracy_maximum: 0.7,
    overall_accuracy_in_target: overallInTarget,
    levels_1_and_2_mixed: levelsMixed,
    no_infrastructure_errors: noInfrastructure,
    authenticated_local_runtime: authenticatedRuntime,
    levels,
  };
}

function parseEvaluationAttempt(
  value: unknown,
  path: string,
): EvaluationAttemptSummary {
  const record = exactRecord(
    value,
    [
      "attempt_id",
      "ordinal",
      "scenario_id",
      "disposition",
      "summary",
      "interaction_digest",
      "runtime_trace_digest",
      "result_digest",
    ],
    path,
  );
  const disposition = oneOf(
    record.disposition,
    [
      "scientific_success",
      "scientific_failure",
      "infrastructure_error",
    ] as const,
    `${path}.disposition`,
  );
  const resultDigest = record.result_digest === null
    ? null
    : digest(record.result_digest, `${path}.result_digest`);
  if ((disposition === "infrastructure_error") !== (resultDigest === null)) {
    malformed(path, "separate infrastructure attempts from scientific results");
  }
  return {
    attempt_id: patternedString(
      record.attempt_id,
      /^attempt-[0-9]{4}$/,
      `${path}.attempt_id`,
    ),
    ordinal: integerValue(record.ordinal, `${path}.ordinal`, 0),
    scenario_id: nonEmptyString(record.scenario_id, `${path}.scenario_id`),
    disposition,
    summary: nonEmptyString(record.summary, `${path}.summary`),
    interaction_digest: digest(
      record.interaction_digest,
      `${path}.interaction_digest`,
    ),
    runtime_trace_digest: digest(
      record.runtime_trace_digest,
      `${path}.runtime_trace_digest`,
    ),
    result_digest: resultDigest,
  };
}

function parseEvaluationPlan(value: unknown, path: string): EvaluationPlan {
  const record = exactRecord(
    value,
    [
      "plan_revision",
      "profile",
      "environment_id",
      "bundle_revision",
      "bundle_digest",
      "split",
      "curriculum_package_digest",
      "model",
      "model_revision",
      "objective",
      "scenario_ids",
    ],
    path,
  );
  const scenarioIds = stringArray(record.scenario_ids, `${path}.scenario_ids`);
  if (scenarioIds.length !== 32 || new Set(scenarioIds).size !== 32) {
    malformed(`${path}.scenario_ids`, "contain 32 unique development identities");
  }
  return {
    plan_revision: oneOf(
      record.plan_revision,
      ["science-environment-evaluation-plan/1"] as const,
      `${path}.plan_revision`,
    ),
    profile: oneOf(
      record.profile,
      ["base-gemma-development-v1"] as const,
      `${path}.profile`,
    ),
    environment_id: nonEmptyString(record.environment_id, `${path}.environment_id`),
    bundle_revision: nonEmptyString(
      record.bundle_revision,
      `${path}.bundle_revision`,
    ),
    bundle_digest: digest(record.bundle_digest, `${path}.bundle_digest`),
    split: oneOf(record.split, ["development"] as const, `${path}.split`),
    curriculum_package_digest: digest(
      record.curriculum_package_digest,
      `${path}.curriculum_package_digest`,
    ),
    model: parseEvaluationModel(record.model, `${path}.model`),
    model_revision: oneOf(
      record.model_revision,
      ["ee0ef6023621cff504d758262d4e04895a5af4a2"] as const,
      `${path}.model_revision`,
    ),
    objective: nonEmptyString(record.objective, `${path}.objective`),
    scenario_ids: scenarioIds,
  };
}

function parseEvaluationSummary(value: unknown, path: string): EvaluationSummary {
  const record = exactRecord(
    value,
    ["evaluation_id", "profile", "model", "status", "progress"],
    path,
  );
  return {
    evaluation_id: patternedString(
      record.evaluation_id,
      /^evaluation-[0-9a-f]{32}$/,
      `${path}.evaluation_id`,
    ),
    profile: oneOf(
      record.profile,
      ["base-gemma-development-v1"] as const,
      `${path}.profile`,
    ),
    model: parseEvaluationModel(record.model, `${path}.model`),
    status: parseEvaluationStatus(record.status, `${path}.status`),
    progress: parseEvaluationProgress(record.progress, `${path}.progress`),
  };
}

function parseEvaluationSummaries(value: unknown): EvaluationSummary[] {
  if (!Array.isArray(value)) malformed("EvaluationSummary[]", "be an array");
  return value.map((item, index) =>
    parseEvaluationSummary(item, `EvaluationSummary[${index}]`)
  );
}

export function decodeEvaluationSnapshot(value: unknown): EvaluationSnapshot {
  const path = "EvaluationSnapshot";
  const record = exactRecord(
    value,
    ["evaluation_id", "status", "plan", "progress", "calibration", "attempts"],
    path,
  );
  if (!Array.isArray(record.attempts)) malformed(`${path}.attempts`, "be an array");
  const attempts = record.attempts.map((item, index) =>
    parseEvaluationAttempt(item, `${path}.attempts[${index}]`)
  );
  const progress = parseEvaluationProgress(record.progress, `${path}.progress`);
  const calibration = parseEvaluationCalibration(
    record.calibration,
    `${path}.calibration`,
  );
  const status = parseEvaluationStatus(record.status, `${path}.status`);
  if (attempts.length !== progress.completed_scenarios) {
    malformed(path, "match attempt rows to completed progress");
  }
  const calibrationTotals = calibration.levels.reduce(
    (totals, level) => ({
      scenarios: totals.scenarios + level.total_scenarios,
      completed: totals.completed + level.completed_scenarios,
      successes: totals.successes + level.scientific_successes,
      failures: totals.failures + level.scientific_failures,
      infrastructure: totals.infrastructure + level.infrastructure_errors,
    }),
    { scenarios: 0, completed: 0, successes: 0, failures: 0, infrastructure: 0 },
  );
  if (
    calibrationTotals.scenarios !== progress.total_scenarios
    || calibrationTotals.completed !== progress.completed_scenarios
    || calibrationTotals.successes !== progress.scientific_successes
    || calibrationTotals.failures !== progress.scientific_failures
    || calibrationTotals.infrastructure !== progress.infrastructure_errors
    || (status === "completed") === (calibration.status === "pending")
  ) {
    malformed(path, "bind calibration evidence to evaluation progress");
  }
  return {
    evaluation_id: patternedString(
      record.evaluation_id,
      /^evaluation-[0-9a-f]{32}$/,
      `${path}.evaluation_id`,
    ),
    status,
    plan: parseEvaluationPlan(record.plan, `${path}.plan`),
    progress,
    calibration,
    attempts,
  };
}

function parseEvaluationReplayReport(
  value: unknown,
  path: string,
): EvaluationReplayReport {
  const record = exactRecord(
    value,
    [
      "source_trace_digest",
      "replay_trace_digest",
      "trace_matches",
      "source_result_digest",
      "replay_result_digest",
      "result_matches",
    ],
    path,
  );
  return {
    source_trace_digest: digest(
      record.source_trace_digest,
      `${path}.source_trace_digest`,
    ),
    replay_trace_digest: digest(
      record.replay_trace_digest,
      `${path}.replay_trace_digest`,
    ),
    trace_matches: booleanValue(record.trace_matches, `${path}.trace_matches`),
    source_result_digest: digest(
      record.source_result_digest,
      `${path}.source_result_digest`,
    ),
    replay_result_digest: digest(
      record.replay_result_digest,
      `${path}.replay_result_digest`,
    ),
    result_matches: booleanValue(record.result_matches, `${path}.result_matches`),
  };
}

function parseEvaluationInfrastructureError(
  value: unknown,
  path: string,
): EvaluationInfrastructureError {
  const record = exactRecord(value, ["category", "code", "summary"], path);
  return {
    category: oneOf(
      record.category,
      ["adapter", "inference", "protocol"] as const,
      `${path}.category`,
    ),
    code: patternedString(
      record.code,
      /^[a-z0-9][a-z0-9_.-]*$/,
      `${path}.code`,
    ),
    summary: nonEmptyString(record.summary, `${path}.summary`),
  };
}

function parseEvaluationToolCall(
  value: unknown,
  path: string,
): EvaluationToolCall {
  const record = exactRecord(
    value,
    ["call_id", "provider_call_id", "ordinal", "name", "arguments"],
    path,
  );
  const ordinal = integerValue(record.ordinal, `${path}.ordinal`, 1);
  const callId = nonEmptyString(record.call_id, `${path}.call_id`);
  if (callId !== `episode-call-${String(ordinal).padStart(6, "0")}`) {
    malformed(path, "bind its canonical call ID to its ordinal");
  }
  return {
    call_id: callId,
    provider_call_id: nonEmptyString(
      record.provider_call_id,
      `${path}.provider_call_id`,
    ),
    ordinal,
    name: nonEmptyString(record.name, `${path}.name`),
    arguments: jsonObject(record.arguments, `${path}.arguments`),
  };
}

function parseEvaluationMessage(
  value: unknown,
  path: string,
): EvaluationMessage {
  const record = exactRecord(
    value,
    [
      "role",
      "content",
      "response_id",
      "response_turn",
      "tool_calls",
      "tool_call_id",
      "provider_tool_call_id",
      "tool_call_ordinal",
      "tool_name",
      "provider_state",
    ],
    path,
  );
  if (!Array.isArray(record.tool_calls)) {
    malformed(`${path}.tool_calls`, "be an array");
  }
  if (!Array.isArray(record.provider_state)) {
    malformed(`${path}.provider_state`, "be an array");
  }
  const providerState = record.provider_state.map((item, index) =>
    jsonObject(item, `${path}.provider_state[${index}]`)
  );
  const role = oneOf(
    record.role,
    ["user", "assistant", "tool"] as const,
    `${path}.role`,
  );
  const toolCalls = record.tool_calls.map((item, index) =>
    parseEvaluationToolCall(item, `${path}.tool_calls[${index}]`)
  );
  const toolCallId = record.tool_call_id === null
    ? null
    : nonEmptyString(record.tool_call_id, `${path}.tool_call_id`);
  const providerToolCallId = record.provider_tool_call_id === null
    ? null
    : nonEmptyString(
        record.provider_tool_call_id,
        `${path}.provider_tool_call_id`,
      );
  const toolCallOrdinal = record.tool_call_ordinal === null
    ? null
    : integerValue(record.tool_call_ordinal, `${path}.tool_call_ordinal`, 1);
  const toolName = record.tool_name === null
    ? null
    : nonEmptyString(record.tool_name, `${path}.tool_name`);
  const responseId = record.response_id === null
    ? null
    : nonEmptyString(record.response_id, `${path}.response_id`);
  const responseTurn = record.response_turn === null
    ? null
    : integerValue(record.response_turn, `${path}.response_turn`, 1);
  const content = role === "assistant"
    ? stringValue(record.content, `${path}.content`)
    : jsonObject(record.content, `${path}.content`);
  const validRoleShape = role === "assistant"
    ? responseId !== null
      && responseTurn !== null
      && toolCallId === null
      && providerToolCallId === null
      && toolCallOrdinal === null
      && toolName === null
    : role === "tool"
      ? responseId === null
        && responseTurn === null
        && toolCallId !== null
        && providerToolCallId !== null
        && toolCallOrdinal !== null
        && toolName !== null
        && toolCalls.length === 0
        && providerState.length === 0
      : responseId === null
        && responseTurn === null
        && toolCallId === null
        && providerToolCallId === null
        && toolCallOrdinal === null
        && toolName === null
        && toolCalls.length === 0
        && providerState.length === 0;
  if (!validRoleShape) malformed(path, "match its declared interaction role");
  if (
    role === "tool"
    && toolCallId !== `episode-call-${String(toolCallOrdinal).padStart(6, "0")}`
  ) {
    malformed(path, "bind its canonical tool message ID to its ordinal");
  }
  return {
    role,
    content,
    response_id: responseId,
    response_turn: responseTurn,
    tool_calls: toolCalls,
    tool_call_id: toolCallId,
    provider_tool_call_id: providerToolCallId,
    tool_call_ordinal: toolCallOrdinal,
    tool_name: toolName,
    provider_state: providerState,
  };
}

function optionalTokenCount(value: unknown, path: string): number | null {
  return value === null ? null : integerValue(value, path, 0);
}

function parseEvaluationTokenUsage(
  value: unknown,
  path: string,
): EvaluationTokenUsage {
  const record = exactRecord(
    value,
    [
      "input_tokens",
      "output_tokens",
      "total_tokens",
      "cached_input_tokens",
      "reasoning_tokens",
    ],
    path,
  );
  return {
    input_tokens: optionalTokenCount(record.input_tokens, `${path}.input_tokens`),
    output_tokens: optionalTokenCount(record.output_tokens, `${path}.output_tokens`),
    total_tokens: optionalTokenCount(record.total_tokens, `${path}.total_tokens`),
    cached_input_tokens: optionalTokenCount(
      record.cached_input_tokens,
      `${path}.cached_input_tokens`,
    ),
    reasoning_tokens: optionalTokenCount(
      record.reasoning_tokens,
      `${path}.reasoning_tokens`,
    ),
  };
}

function parseEvaluationResponseRecord(
  value: unknown,
  path: string,
): EvaluationResponseRecord {
  const record = exactRecord(
    value,
    ["turn", "response_id", "returned_model", "usage", "metadata"],
    path,
  );
  let metadata: EvaluationResponseRecord["metadata"] = null;
  if (record.metadata !== null) {
    const metadataRecord = exactRecord(
      record.metadata,
      [
        "created_unix_seconds",
        "finish_reason",
        "system_fingerprint",
        "runtime_instance_id",
        "provider_request_id",
        "service_tier",
        "provider_usage",
      ],
      `${path}.metadata`,
    );
    metadata = {
      created_unix_seconds: integerValue(
        metadataRecord.created_unix_seconds,
        `${path}.metadata.created_unix_seconds`,
        0,
      ),
      finish_reason: oneOf(
        metadataRecord.finish_reason,
        ["stop", "tool_calls", "length"] as const,
        `${path}.metadata.finish_reason`,
      ),
      system_fingerprint: metadataRecord.system_fingerprint === null
        ? null
        : nonEmptyString(
            metadataRecord.system_fingerprint,
            `${path}.metadata.system_fingerprint`,
          ),
      runtime_instance_id: metadataRecord.runtime_instance_id === null
        ? null
        : rawSha256Digest(
            metadataRecord.runtime_instance_id,
            `${path}.metadata.runtime_instance_id`,
          ),
      provider_request_id: metadataRecord.provider_request_id === null
        ? null
        : nonEmptyString(
            metadataRecord.provider_request_id,
            `${path}.metadata.provider_request_id`,
          ),
      service_tier: metadataRecord.service_tier === null
        ? null
        : nonEmptyString(
            metadataRecord.service_tier,
            `${path}.metadata.service_tier`,
          ),
      provider_usage: metadataRecord.provider_usage === null
        ? null
        : jsonObject(
            metadataRecord.provider_usage,
            `${path}.metadata.provider_usage`,
          ),
    };
  }
  return {
    turn: integerValue(record.turn, `${path}.turn`, 1),
    response_id: nonEmptyString(record.response_id, `${path}.response_id`),
    returned_model: nonEmptyString(record.returned_model, `${path}.returned_model`),
    usage: record.usage === null
      ? null
      : parseEvaluationTokenUsage(record.usage, `${path}.usage`),
    metadata,
  };
}

function parseEvaluationToolResult(
  value: unknown,
  path: string,
): EvaluationToolResult {
  const record = exactRecord(
    value,
    [
      "call_id",
      "provider_call_id",
      "ordinal",
      "name",
      "status",
      "observation",
      "error_code",
      "execution_id",
      "cache_hit",
      "retry_count",
    ],
    path,
  );
  const ordinal = integerValue(record.ordinal, `${path}.ordinal`, 1);
  const callId = nonEmptyString(record.call_id, `${path}.call_id`);
  if (callId !== `episode-call-${String(ordinal).padStart(6, "0")}`) {
    malformed(path, "bind its canonical result ID to its ordinal");
  }
  const status = oneOf(record.status, ["ok", "error"] as const, `${path}.status`);
  const observation = record.observation === null
    ? null
    : jsonObject(record.observation, `${path}.observation`);
  const errorCode = record.error_code === null
    ? null
    : patternedString(
        record.error_code,
        /^[a-z0-9][a-z0-9_.-]*$/,
        `${path}.error_code`,
      );
  const executionId = record.execution_id === null
    ? null
    : digest(record.execution_id, `${path}.execution_id`);
  const cacheHit = record.cache_hit === null
    ? null
    : booleanValue(record.cache_hit, `${path}.cache_hit`);
  const retryCount = record.retry_count === null
    ? null
    : integerValue(record.retry_count, `${path}.retry_count`, 0);
  if (
    (
      status === "ok"
      && (
        observation === null
        || errorCode !== null
        || executionId === null
        || cacheHit === null
        || retryCount === null
      )
    )
    || (
      status === "error"
      && (
        observation !== null
        || errorCode === null
        || executionId !== null
        || cacheHit !== null
        || retryCount !== null
      )
    )
  ) {
    malformed(path, "match its declared tool-result status");
  }
  return {
    call_id: callId,
    provider_call_id: nonEmptyString(
      record.provider_call_id,
      `${path}.provider_call_id`,
    ),
    ordinal,
    name: nonEmptyString(record.name, `${path}.name`),
    status,
    observation,
    error_code: errorCode,
    execution_id: executionId,
    cache_hit: cacheHit,
    retry_count: retryCount,
  };
}

function parseEvaluationRuntimeExecution(
  value: unknown,
  path: string,
): EvaluationRuntimeExecution {
  const record = exactRecord(
    value,
    [
      "call_id",
      "ordinal",
      "execution_id",
      "action",
      "observation",
      "resulting_status",
      "resulting_trace_digest",
      "cache_hit",
      "retry_count",
    ],
    path,
  );
  const ordinal = integerValue(record.ordinal, `${path}.ordinal`, 1);
  const callId = nonEmptyString(record.call_id, `${path}.call_id`);
  const cacheHit = booleanValue(record.cache_hit, `${path}.cache_hit`);
  const retryCount = integerValue(record.retry_count, `${path}.retry_count`, 0);
  if (
    callId !== `episode-call-${String(ordinal).padStart(6, "0")}`
    || cacheHit !== (retryCount > 0)
  ) {
    malformed(path, "preserve canonical ordinal and cache-retry evidence");
  }
  return {
    call_id: callId,
    ordinal,
    execution_id: digest(record.execution_id, `${path}.execution_id`),
    action: parseTraceAction(record.action, `${path}.action`),
    observation: jsonObject(record.observation, `${path}.observation`),
    resulting_status: oneOf(
      record.resulting_status,
      ["active", "awaiting_verification"] as const,
      `${path}.resulting_status`,
    ),
    resulting_trace_digest: digest(
      record.resulting_trace_digest,
      `${path}.resulting_trace_digest`,
    ),
    cache_hit: cacheHit,
    retry_count: retryCount,
  };
}

const APPROVED_RUNTIME_DISTRIBUTIONS = [
  {
    distribution: "jinja2",
    version: "3.1.6",
    wheel_sha256: "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67",
    import_module: "jinja2",
    import_origin: "jinja2/__init__.py",
  },
  {
    distribution: "safetensors",
    version: "0.7.0",
    wheel_sha256: "dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48",
    import_module: "safetensors",
    import_origin: "safetensors/__init__.py",
  },
  {
    distribution: "tokenizers",
    version: "0.22.2",
    wheel_sha256: "369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67",
    import_module: "tokenizers",
    import_origin: "tokenizers/__init__.py",
  },
  {
    distribution: "torch",
    version: "2.11.0+cu129",
    wheel_sha256: "68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3",
    import_module: "torch",
    import_origin: "torch/__init__.py",
  },
  {
    distribution: "transformers",
    version: "5.6.2",
    wheel_sha256: "f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f",
    import_module: "transformers",
    import_origin: "transformers/__init__.py",
  },
  {
    distribution: "vllm",
    version: "0.26.0+cu129",
    wheel_sha256: "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf",
    import_module: "vllm",
    import_origin: "vllm/__init__.py",
  },
] as const;

function rawSha256Digest(value: unknown, path: string): string {
  return patternedString(value, RAW_SHA256_DIGEST, path);
}

function parseRuntimeDistribution(
  value: unknown,
  index: number,
  path: string,
): EvaluationRuntimeDistribution {
  const expected = APPROVED_RUNTIME_DISTRIBUTIONS[index];
  if (expected === undefined) {
    malformed(path, "contain the six distributions in approved order");
  }
  const record = exactRecord(
    value,
    [
      "distribution",
      "version",
      "wheel_sha256",
      "record_manifest_sha256",
      "import_module",
      "import_origin",
      "import_origin_sha256",
      "verification",
    ],
    `${path}[${index}]`,
  );
  const distribution = oneOf(
    record.distribution,
    [expected.distribution] as const,
    `${path}[${index}].distribution`,
  );
  const version = nonEmptyString(record.version, `${path}[${index}].version`);
  const wheelSha256 = rawSha256Digest(
    record.wheel_sha256,
    `${path}[${index}].wheel_sha256`,
  );
  const importModule = nonEmptyString(
    record.import_module,
    `${path}[${index}].import_module`,
  );
  const importOrigin = nonEmptyString(
    record.import_origin,
    `${path}[${index}].import_origin`,
  );
  if (
    version !== expected.version
    || wheelSha256 !== expected.wheel_sha256
    || importModule !== expected.import_module
    || importOrigin !== expected.import_origin
  ) {
    malformed(
      `${path}[${index}]`,
      `match the approved ${expected.distribution} version, wheel, and import origin`,
    );
  }
  return {
    distribution,
    version,
    wheel_sha256: wheelSha256,
    record_manifest_sha256: rawSha256Digest(
      record.record_manifest_sha256,
      `${path}[${index}].record_manifest_sha256`,
    ),
    import_module: importModule,
    import_origin: importOrigin,
    import_origin_sha256: rawSha256Digest(
      record.import_origin_sha256,
      `${path}[${index}].import_origin_sha256`,
    ),
    verification: oneOf(
      record.verification,
      ["wheel-record-sha256+import-origin"] as const,
      `${path}[${index}].verification`,
    ),
  };
}

function parseProductDistribution(
  value: unknown,
  path: string,
): EvaluationRuntimeDistribution {
  const record = exactRecord(
    value,
    [
      "distribution",
      "version",
      "wheel_sha256",
      "record_manifest_sha256",
      "import_module",
      "import_origin",
      "import_origin_sha256",
      "verification",
    ],
    path,
  );
  return {
    distribution: oneOf(
      record.distribution,
      ["science-environment-studio"] as const,
      `${path}.distribution`,
    ),
    version: oneOf(record.version, ["0.1.0"] as const, `${path}.version`),
    wheel_sha256: rawSha256Digest(record.wheel_sha256, `${path}.wheel_sha256`),
    record_manifest_sha256: rawSha256Digest(
      record.record_manifest_sha256,
      `${path}.record_manifest_sha256`,
    ),
    import_module: oneOf(
      record.import_module,
      ["studio.policy_evaluation.gemma_server_bootstrap"] as const,
      `${path}.import_module`,
    ),
    import_origin: oneOf(
      record.import_origin,
      ["studio/policy_evaluation/gemma_server_bootstrap.py"] as const,
      `${path}.import_origin`,
    ),
    import_origin_sha256: rawSha256Digest(
      record.import_origin_sha256,
      `${path}.import_origin_sha256`,
    ),
    verification: oneOf(
      record.verification,
      ["wheel-record-sha256+import-origin"] as const,
      `${path}.verification`,
    ),
  };
}

export function decodeLocalGemmaAttestation(
  value: unknown,
  path = "LocalGemmaServerEvidence",
): EvaluationLocalGemmaAttestation {
  const record = exactRecord(
    value,
    [
      "attestation_version",
      "attestation_id",
      "runtime_instance_id",
      "trusted_bootstrap_sha256",
      "challenge_nonce",
      "generated_at_utc",
      "runtime_started_at_utc",
      "served_model",
      "checkpoint_revision",
      "checkpoint_weights_sha256",
      "tokenizer_revision",
      "tokenizer_manifest_sha256",
      "renderer_revision",
      "vllm_version",
      "vllm_source_revision",
      "vllm_wheel_sha256",
      "python_runtime",
      "runtime_receipt_id",
      "runtime_distributions",
      "product_distribution",
      "python_bytecode_mode",
      "serving_root_filesystem_mode",
      "network_scope",
      "api_key_authentication",
      "attestation_middleware_revision",
      "vllm_config",
      "adapter_revision",
      "served_adapter",
      "sampling_profile",
      "max_episode_seconds",
      "platform",
      "accelerator_architecture",
      "accelerator_count",
      "cuda_version",
      "driver_version",
      "serving_image_digest",
      "serving_image_digest_provenance",
      "evidence_scope",
      "signature",
      "evidence_digest",
      "verification_method",
    ],
    path,
  );
  const generatedAt = nonEmptyString(record.generated_at_utc, `${path}.generated_at_utc`);
  const runtimeStartedAt = nonEmptyString(
    record.runtime_started_at_utc,
    `${path}.runtime_started_at_utc`,
  );
  if (
    !Number.isFinite(Date.parse(generatedAt))
    || !Number.isFinite(Date.parse(runtimeStartedAt))
    || Date.parse(generatedAt) < Date.parse(runtimeStartedAt)
  ) {
    malformed(path, "contain an ordered runtime attestation timestamp window");
  }
  const pythonRecord = exactRecord(
    record.python_runtime,
    ["implementation", "version", "abi_tag", "platform"],
    `${path}.python_runtime`,
  );
  if (!Array.isArray(record.runtime_distributions)) {
    malformed(`${path}.runtime_distributions`, "contain the six distributions in approved order");
  }
  if (record.runtime_distributions.length !== APPROVED_RUNTIME_DISTRIBUTIONS.length) {
    malformed(`${path}.runtime_distributions`, "contain the six distributions in approved order");
  }
  if (record.runtime_distributions.some((item, index) => (
    !isRecord(item)
    || item.distribution !== APPROVED_RUNTIME_DISTRIBUTIONS[index]?.distribution
  ))) {
    malformed(`${path}.runtime_distributions`, "contain the six distributions in approved order");
  }
  const runtimeDistributions = record.runtime_distributions.map((item, index) =>
    parseRuntimeDistribution(item, index, `${path}.runtime_distributions`)
  );
  const productDistribution = parseProductDistribution(
    record.product_distribution,
    `${path}.product_distribution`,
  );
  const configRecord = exactRecord(
    record.vllm_config,
    [
      "dtype",
      "max_model_len",
      "tensor_parallel_size",
      "gpu_memory_utilization",
      "enforce_eager",
      "max_num_seqs",
      "generation_config",
      "tool_call_parser",
      "enable_auto_tool_choice",
      "enable_lora",
      "disable_log_requests",
      "limit_mm_per_prompt",
    ],
    `${path}.vllm_config`,
  );
  const multimodalRecord = exactRecord(
    configRecord.limit_mm_per_prompt,
    ["image", "audio", "video"],
    `${path}.vllm_config.limit_mm_per_prompt`,
  );
  const gpuMemoryUtilization = finiteNumber(
    configRecord.gpu_memory_utilization,
    `${path}.vllm_config.gpu_memory_utilization`,
  );
  if (gpuMemoryUtilization !== 0.35) {
    malformed(`${path}.vllm_config.gpu_memory_utilization`, "equal 0.35");
  }
  const apiKeyAuthentication = booleanValue(
    record.api_key_authentication,
    `${path}.api_key_authentication`,
  );
  const maxModelLen = integerValue(
    configRecord.max_model_len,
    `${path}.vllm_config.max_model_len`,
  );
  const tensorParallelSize = integerValue(
    configRecord.tensor_parallel_size,
    `${path}.vllm_config.tensor_parallel_size`,
  );
  const enforceEager = booleanValue(
    configRecord.enforce_eager,
    `${path}.vllm_config.enforce_eager`,
  );
  const maxNumSeqs = integerValue(
    configRecord.max_num_seqs,
    `${path}.vllm_config.max_num_seqs`,
  );
  const enableAutoToolChoice = booleanValue(
    configRecord.enable_auto_tool_choice,
    `${path}.vllm_config.enable_auto_tool_choice`,
  );
  const enableLora = booleanValue(
    configRecord.enable_lora,
    `${path}.vllm_config.enable_lora`,
  );
  const disableLogRequests = booleanValue(
    configRecord.disable_log_requests,
    `${path}.vllm_config.disable_log_requests`,
  );
  const imageLimit = integerValue(
    multimodalRecord.image,
    `${path}.vllm_config.limit_mm_per_prompt.image`,
  );
  const audioLimit = integerValue(
    multimodalRecord.audio,
    `${path}.vllm_config.limit_mm_per_prompt.audio`,
  );
  const videoLimit = integerValue(
    multimodalRecord.video,
    `${path}.vllm_config.limit_mm_per_prompt.video`,
  );
  const maxEpisodeSeconds = integerValue(
    record.max_episode_seconds,
    `${path}.max_episode_seconds`,
  );
  if (
    !apiKeyAuthentication
    || maxModelLen !== 32768
    || tensorParallelSize !== 1
    || !enforceEager
    || maxNumSeqs !== 16
    || !enableAutoToolChoice
    || enableLora
    || !disableLogRequests
    || imageLimit !== 0
    || audioLimit !== 0
    || videoLimit !== 0
    || maxEpisodeSeconds !== 900
  ) {
    malformed(path, "match the approved serving command configuration");
  }
  return {
    attestation_version: oneOf(
      record.attestation_version,
      ["science-local-gemma-runtime-attestation/1"] as const,
      `${path}.attestation_version`,
    ),
    attestation_id: nonEmptyString(record.attestation_id, `${path}.attestation_id`),
    runtime_instance_id: rawSha256Digest(
      record.runtime_instance_id,
      `${path}.runtime_instance_id`,
    ),
    trusted_bootstrap_sha256: rawSha256Digest(
      record.trusted_bootstrap_sha256,
      `${path}.trusted_bootstrap_sha256`,
    ),
    challenge_nonce: rawSha256Digest(record.challenge_nonce, `${path}.challenge_nonce`),
    generated_at_utc: generatedAt,
    runtime_started_at_utc: runtimeStartedAt,
    served_model: oneOf(record.served_model, ["google/gemma-4-E4B-it"] as const, `${path}.served_model`),
    checkpoint_revision: oneOf(record.checkpoint_revision, ["ee0ef6023621cff504d758262d4e04895a5af4a2"] as const, `${path}.checkpoint_revision`),
    checkpoint_weights_sha256: rawSha256Digest(record.checkpoint_weights_sha256, `${path}.checkpoint_weights_sha256`),
    tokenizer_revision: oneOf(record.tokenizer_revision, ["ee0ef6023621cff504d758262d4e04895a5af4a2"] as const, `${path}.tokenizer_revision`),
    tokenizer_manifest_sha256: rawSha256Digest(record.tokenizer_manifest_sha256, `${path}.tokenizer_manifest_sha256`),
    renderer_revision: oneOf(record.renderer_revision, ["f770dcaa362e3a6a13a96f039741b3b84ca4114e"] as const, `${path}.renderer_revision`),
    vllm_version: oneOf(record.vllm_version, ["0.26.0+cu129"] as const, `${path}.vllm_version`),
    vllm_source_revision: oneOf(record.vllm_source_revision, ["568afb3a13806beb53bb2e6bd518269357b237c0"] as const, `${path}.vllm_source_revision`),
    vllm_wheel_sha256: oneOf(record.vllm_wheel_sha256, ["7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf"] as const, `${path}.vllm_wheel_sha256`),
    python_runtime: {
      implementation: oneOf(pythonRecord.implementation, ["cpython"] as const, `${path}.python_runtime.implementation`),
      version: oneOf(pythonRecord.version, ["3.12"] as const, `${path}.python_runtime.version`),
      abi_tag: oneOf(pythonRecord.abi_tag, ["cp312"] as const, `${path}.python_runtime.abi_tag`),
      platform: oneOf(pythonRecord.platform, ["linux-x86_64"] as const, `${path}.python_runtime.platform`),
    },
    runtime_receipt_id: oneOf(record.runtime_receipt_id, ["science-local-gemma-runtime-cp312-cu129/1"] as const, `${path}.runtime_receipt_id`),
    runtime_distributions: runtimeDistributions,
    product_distribution: productDistribution,
    python_bytecode_mode: oneOf(
      record.python_bytecode_mode,
      ["fresh-private-prefix-no-write"] as const,
      `${path}.python_bytecode_mode`,
    ),
    serving_root_filesystem_mode: oneOf(
      record.serving_root_filesystem_mode,
      ["kernel-read-only-mount"] as const,
      `${path}.serving_root_filesystem_mode`,
    ),
    network_scope: oneOf(record.network_scope, ["loopback-only"] as const, `${path}.network_scope`),
    api_key_authentication: true,
    attestation_middleware_revision: oneOf(record.attestation_middleware_revision, ["science-local-gemma-attestation-middleware/1"] as const, `${path}.attestation_middleware_revision`),
    vllm_config: {
      dtype: oneOf(configRecord.dtype, ["bfloat16"] as const, `${path}.vllm_config.dtype`),
      max_model_len: 32768,
      tensor_parallel_size: 1,
      gpu_memory_utilization: gpuMemoryUtilization,
      enforce_eager: true,
      max_num_seqs: 16,
      generation_config: oneOf(configRecord.generation_config, ["vllm"] as const, `${path}.vllm_config.generation_config`),
      tool_call_parser: oneOf(configRecord.tool_call_parser, ["gemma4"] as const, `${path}.vllm_config.tool_call_parser`),
      enable_auto_tool_choice: true,
      enable_lora: false,
      disable_log_requests: true,
      limit_mm_per_prompt: {
        image: 0,
        audio: 0,
        video: 0,
      },
    },
    adapter_revision: oneOf(record.adapter_revision, ["local-gemma-openai-chat/1"] as const, `${path}.adapter_revision`),
    served_adapter: oneOf(record.served_adapter, ["none"] as const, `${path}.served_adapter`),
    sampling_profile: oneOf(record.sampling_profile, ["base-gemma-development-chat-v1"] as const, `${path}.sampling_profile`),
    max_episode_seconds: 900,
    platform: oneOf(record.platform, ["linux-x86_64"] as const, `${path}.platform`),
    accelerator_architecture: nonEmptyString(record.accelerator_architecture, `${path}.accelerator_architecture`),
    accelerator_count: integerValue(record.accelerator_count, `${path}.accelerator_count`, 1),
    cuda_version: nonEmptyString(record.cuda_version, `${path}.cuda_version`),
    driver_version: nonEmptyString(record.driver_version, `${path}.driver_version`),
    serving_image_digest: digest(record.serving_image_digest, `${path}.serving_image_digest`),
    serving_image_digest_provenance: oneOf(record.serving_image_digest_provenance, ["operator-supplied"] as const, `${path}.serving_image_digest_provenance`),
    evidence_scope: oneOf(record.evidence_scope, ["server-reported-runtime-state"] as const, `${path}.evidence_scope`),
    signature: rawSha256Digest(record.signature, `${path}.signature`),
    evidence_digest: digest(record.evidence_digest, `${path}.evidence_digest`),
    verification_method: oneOf(record.verification_method, ["hmac-sha256-server-challenge"] as const, `${path}.verification_method`),
  };
}

function parseEvaluationInteraction(
  value: unknown,
  path: string,
): EvaluationInteraction {
  const record = exactRecord(
    value,
    [
      "trace_version",
      "model",
      "sampling",
      "budgets",
      "run",
      "messages",
      "responses",
      "tool_calls",
      "tool_results",
      "accepted_actions",
      "runtime_executions",
      "runtime_events",
      "runtime_trace_digest",
      "infrastructure_error",
      "interaction_digest",
    ],
    path,
  );
  const messageValues = record.messages;
  const responseValues = record.responses;
  const toolCallValues = record.tool_calls;
  const toolResultValues = record.tool_results;
  const acceptedActionValues = record.accepted_actions;
  const runtimeExecutionValues = record.runtime_executions;
  const runtimeEventValues = record.runtime_events;
  if (!Array.isArray(messageValues)) malformed(`${path}.messages`, "be an array");
  if (!Array.isArray(responseValues)) malformed(`${path}.responses`, "be an array");
  if (!Array.isArray(toolCallValues)) malformed(`${path}.tool_calls`, "be an array");
  if (!Array.isArray(toolResultValues)) malformed(`${path}.tool_results`, "be an array");
  if (!Array.isArray(acceptedActionValues)) {
    malformed(`${path}.accepted_actions`, "be an array");
  }
  if (!Array.isArray(runtimeExecutionValues)) {
    malformed(`${path}.runtime_executions`, "be an array");
  }
  if (!Array.isArray(runtimeEventValues)) {
    malformed(`${path}.runtime_events`, "be an array");
  }
  const messages = messageValues.map((item, index) =>
    parseEvaluationMessage(item, `${path}.messages[${index}]`)
  );
  const responses = responseValues.map((item, index) =>
    parseEvaluationResponseRecord(item, `${path}.responses[${index}]`)
  );
  const toolCalls = toolCallValues.map((item, index) =>
    parseEvaluationToolCall(item, `${path}.tool_calls[${index}]`)
  );
  const toolResults = toolResultValues.map((item, index) =>
    parseEvaluationToolResult(item, `${path}.tool_results[${index}]`)
  );
  const acceptedActions = acceptedActionValues.map((item, index) =>
    parseTraceAction(item, `${path}.accepted_actions[${index}]`)
  );
  const runtimeExecutions = runtimeExecutionValues.map((item, index) =>
    parseEvaluationRuntimeExecution(item, `${path}.runtime_executions[${index}]`)
  );
  const assistantCalls = messages.flatMap((message) =>
    message.role === "assistant"
      ? message.tool_calls
      : []
  );
  const callKey = (
    call: EvaluationToolCall | EvaluationToolResult,
  ) => JSON.stringify([
    call.call_id,
    call.provider_call_id,
    call.ordinal,
    call.name,
  ]);
  const topLevelCallKeys = toolCalls.map(callKey);
  const resultKeys = toolResults.map(callKey);
  const toolMessageKeys = messages.flatMap((message) =>
    message.role === "tool"
      ? [JSON.stringify([
          message.tool_call_id,
          message.provider_tool_call_id,
          message.tool_call_ordinal,
          message.tool_name,
        ])]
      : []
  );
  if (
    assistantCalls.length !== toolCalls.length
    || assistantCalls.some((call, index) => (
      callKey(call) !== topLevelCallKeys[index]
      || canonicalJsonValue(call.arguments)
        !== canonicalJsonValue(toolCalls[index].arguments)
    ))
    || JSON.stringify(topLevelCallKeys) !== JSON.stringify(resultKeys)
    || JSON.stringify(resultKeys) !== JSON.stringify(toolMessageKeys)
    || new Set(toolCalls.map((call) => call.call_id)).size !== toolCalls.length
    || new Set(toolCalls.map((call) => call.ordinal)).size !== toolCalls.length
  ) {
    malformed(path, "preserve one ordered result for every assistant tool call");
  }
  if (
    messages.length === 0
    || messages[0].role !== "user"
    || messages.slice(1).some((message) => message.role === "user")
  ) {
    malformed(`${path}.messages`, "contain exactly one initial user turn");
  }
  const assistantMessages: EvaluationMessage[] = [];
  let messageCursor = 1;
  while (messageCursor < messages.length) {
    const assistant = messages[messageCursor];
    if (assistant.role !== "assistant") {
      malformed(`${path}.messages`, "preserve ordered assistant response turns");
    }
    assistantMessages.push(assistant);
    messageCursor += 1;
    for (const call of assistant.tool_calls) {
      const toolMessage = messages[messageCursor];
      if (
        toolMessage?.role !== "tool"
        || toolMessage.tool_call_id !== call.call_id
        || toolMessage.provider_tool_call_id !== call.provider_call_id
        || toolMessage.tool_call_ordinal !== call.ordinal
        || toolMessage.tool_name !== call.name
      ) {
        malformed(
          `${path}.messages`,
          "place every linked tool result immediately after its assistant call",
        );
      }
      messageCursor += 1;
    }
  }
  const assistantResponseKeys = assistantMessages.map((message) =>
    JSON.stringify([message.response_turn, message.response_id])
  );
  const responseKeys = responses.map((response) =>
    JSON.stringify([response.turn, response.response_id])
  );
  if (
    JSON.stringify(assistantResponseKeys) !== JSON.stringify(responseKeys)
    || responses.some((response, index) => response.turn !== index + 1)
  ) {
    malformed(path, "bind response records one-to-one to assistant turns");
  }
  const toolMessages = messages.filter((message) => message.role === "tool");
  if (toolMessages.some((message, index) => {
    const result = toolResults[index];
    const expected = result.status === "ok"
      ? { status: "ok", observation: result.observation }
      : { status: "error", error_code: result.error_code };
    return canonicalJsonValue(message.content) !== canonicalJsonValue(expected);
  })) {
    malformed(path, "bind tool message payloads to canonical execution results");
  }
  const successful = toolCalls.flatMap((call, index) => (
    toolResults[index].status === "ok" ? [[call, toolResults[index]] as const] : []
  ));
  if (
    successful.length !== runtimeExecutions.length
    || successful.some(([call, result], index) => {
      const execution = runtimeExecutions[index];
      return call.call_id !== execution.call_id
        || call.ordinal !== execution.ordinal
        || call.name !== execution.action.type
        || canonicalJsonValue(call.arguments)
          !== canonicalJsonValue(execution.action.arguments)
        || result.execution_id !== execution.execution_id
        || canonicalJsonValue(result.observation)
          !== canonicalJsonValue(execution.observation)
        || result.cache_hit !== execution.cache_hit
        || result.retry_count !== execution.retry_count;
    })
    || acceptedActions.length !== runtimeExecutions.length
    || acceptedActions.some((action, index) => (
      action.type !== runtimeExecutions[index].action.type
      || canonicalJsonValue(action.arguments)
        !== canonicalJsonValue(runtimeExecutions[index].action.arguments)
    ))
  ) {
    malformed(path, "bind successful calls to canonical Runtime executions");
  }
  const samplingRecord = exactRecord(
    record.sampling,
    [
      "profile",
      "temperature",
      "max_output_tokens",
      "tool_choice",
      "top_p",
      "seed",
      "streaming",
      "store",
    ],
    `${path}.sampling`,
  );
  if (
    finiteNumber(samplingRecord.temperature, `${path}.sampling.temperature`) !== 0
    || integerValue(
      samplingRecord.max_output_tokens,
      `${path}.sampling.max_output_tokens`,
      1,
    ) !== 2048
    || nullValue(samplingRecord.top_p, `${path}.sampling.top_p`) !== null
    || nullValue(samplingRecord.seed, `${path}.sampling.seed`) !== null
    || booleanValue(samplingRecord.streaming, `${path}.sampling.streaming`) !== false
    || booleanValue(samplingRecord.store, `${path}.sampling.store`) !== false
  ) {
    malformed(`${path}.sampling`, "match the fixed deterministic profile");
  }
  const budgetsRecord = exactRecord(
    record.budgets,
    [
      "max_turns",
      "max_tool_calls",
      "max_provider_tool_calls",
      "max_episode_seconds",
    ],
    `${path}.budgets`,
  );
  if (
    integerValue(
      budgetsRecord.max_episode_seconds,
      `${path}.budgets.max_episode_seconds`,
      1,
    ) !== 900
  ) {
    malformed(`${path}.budgets.max_episode_seconds`, "equal the fixed 900-second limit");
  }
  if (
    integerValue(
      budgetsRecord.max_provider_tool_calls,
      `${path}.budgets.max_provider_tool_calls`,
      1,
    ) !== 64
  ) {
    malformed(`${path}.budgets.max_provider_tool_calls`, "equal the fixed 64-call limit");
  }
  const runRecord = exactRecord(
    record.run,
    [
      "profile",
      "started_at_utc",
      "completed_at_utc",
      "local_gemma_attestation",
    ],
    `${path}.run`,
  );
  const startedAt = nonEmptyString(
    runRecord.started_at_utc,
    `${path}.run.started_at_utc`,
  );
  const completedAt = nonEmptyString(
    runRecord.completed_at_utc,
    `${path}.run.completed_at_utc`,
  );
  if (
    !Number.isFinite(Date.parse(startedAt))
    || !Number.isFinite(Date.parse(completedAt))
    || Date.parse(completedAt) < Date.parse(startedAt)
  ) {
    malformed(`${path}.run`, "contain an ordered timestamp window");
  }
  return {
    trace_version: oneOf(
      record.trace_version,
      ["1.0"] as const,
      `${path}.trace_version`,
    ),
    model: parseEvaluationModel(record.model, `${path}.model`),
    sampling: {
      profile: oneOf(
        samplingRecord.profile,
        ["base-gemma-development-chat-v1"] as const,
        `${path}.sampling.profile`,
      ),
      temperature: 0,
      max_output_tokens: 2048,
      tool_choice: oneOf(
        samplingRecord.tool_choice,
        ["auto"] as const,
        `${path}.sampling.tool_choice`,
      ),
      top_p: null,
      seed: null,
      streaming: false,
      store: false,
    },
    budgets: {
      max_turns: integerValue(
        budgetsRecord.max_turns,
        `${path}.budgets.max_turns`,
        1,
      ),
      max_tool_calls: integerValue(
        budgetsRecord.max_tool_calls,
        `${path}.budgets.max_tool_calls`,
        1,
      ),
      max_provider_tool_calls: 64,
      max_episode_seconds: 900,
    },
    run: {
      profile: oneOf(
        runRecord.profile,
        ["base-gemma-development-v1"] as const,
        `${path}.run.profile`,
      ),
      started_at_utc: startedAt,
      completed_at_utc: completedAt,
      local_gemma_attestation: runRecord.local_gemma_attestation === null
        ? null
        : decodeLocalGemmaAttestation(
            runRecord.local_gemma_attestation,
            `${path}.run.local_gemma_attestation`,
          ),
    },
    messages,
    responses,
    tool_calls: toolCalls,
    tool_results: toolResults,
    accepted_actions: acceptedActions,
    runtime_executions: runtimeExecutions,
    runtime_events: runtimeEventValues.map((item, index) =>
      parseTraceEvent(item, `${path}.runtime_events[${index}]`)
    ),
    runtime_trace_digest: digest(
      record.runtime_trace_digest,
      `${path}.runtime_trace_digest`,
    ),
    infrastructure_error: record.infrastructure_error === null
      ? null
      : parseEvaluationInfrastructureError(
          record.infrastructure_error,
          `${path}.infrastructure_error`,
        ),
    interaction_digest: digest(
      record.interaction_digest,
      `${path}.interaction_digest`,
    ),
  };
}

function parseEvaluationReplay(value: unknown): EvaluationReplay {
  const path = "EvaluationReplay";
  const record = exactRecord(
    value,
    [
      "evaluation_id",
      "attempt",
      "interaction",
      "snapshot",
      "report",
      "infrastructure_error",
    ],
    path,
  );
  const attempt = parseEvaluationAttempt(record.attempt, `${path}.attempt`);
  const interaction = parseEvaluationInteraction(
    record.interaction,
    `${path}.interaction`,
  );
  const scientific = attempt.disposition !== "infrastructure_error";
  const snapshot = record.snapshot === null ? null : parseRunSnapshot(record.snapshot);
  const report = record.report === null
    ? null
    : parseEvaluationReplayReport(record.report, `${path}.report`);
  const infrastructureError = record.infrastructure_error === null
    ? null
    : parseEvaluationInfrastructureError(
        record.infrastructure_error,
        `${path}.infrastructure_error`,
      );
  if (
    scientific !== (snapshot !== null && report !== null)
    || scientific === (infrastructureError !== null)
  ) {
    malformed(path, "contain exactly one scientific or infrastructure outcome");
  }
  const interactionHasInfrastructureError = interaction.infrastructure_error !== null;
  if (
    interaction.runtime_trace_digest !== attempt.runtime_trace_digest
    || interactionHasInfrastructureError !== !scientific
  ) {
    malformed(path, "bind interaction evidence to its attempt outcome");
  }
  return {
    evaluation_id: patternedString(
      record.evaluation_id,
      /^evaluation-[0-9a-f]{32}$/,
      `${path}.evaluation_id`,
    ),
    attempt,
    interaction,
    snapshot,
    report,
    infrastructure_error: infrastructureError,
  };
}

export function decodeMesoscopePortabilityReport(
  value: unknown,
): MesoscopePortabilityReport {
  const path = "MesoscopePortabilityReport";
  const record = exactRecord(
    value,
    [
      "report_revision",
      "track",
      "environment_id",
      "training_claim_included",
      "fixture_notice",
      "compilation",
      "results",
    ],
    path,
  );
  const compilation = exactRecord(
    record.compilation,
    [
      "compilation_version",
      "verifiers_revision",
      "model_id",
      "model_revision",
      "bundle_id",
      "bundle_revision",
      "source_bundle_digest",
      "artifact_digest",
      "artifacts",
    ],
    `${path}.compilation`,
  );
  if (!Array.isArray(compilation.artifacts)) {
    malformed(`${path}.compilation.artifacts`, "be an array");
  }
  const artifacts = compilation.artifacts.map((value, index) => {
    const artifactPath = `${path}.compilation.artifacts[${index}]`;
    const artifact = exactRecord(
      value,
      ["path", "digest", "size_bytes"],
      artifactPath,
    );
    return {
      path: nonEmptyString(artifact.path, `${artifactPath}.path`),
      digest: digest(artifact.digest, `${artifactPath}.digest`),
      size_bytes: integerValue(artifact.size_bytes, `${artifactPath}.size_bytes`),
    };
  });
  if (!Array.isArray(record.results) || record.results.length !== 2) {
    malformed(`${path}.results`, "contain the valid and quarantine fixtures");
  }
  const results: MesoscopePortabilityResult[] = record.results.map((value, index) => {
    const resultPath = `${path}.results[${index}]`;
    const result = exactRecord(
      value,
      [
        "replay_id",
        "scenario_id",
        "fixture",
        "terminal_summary",
        "terminal_disposition",
        "runtime_trace_digest",
        "result_digest",
      ],
      resultPath,
    );
    if (booleanValue(result.fixture, `${resultPath}.fixture`) !== true) {
      malformed(`${resultPath}.fixture`, "identify seeded offline evidence");
    }
    return {
      replay_id: oneOf(
        result.replay_id,
        ["valid-handoff", "quarantine-handoff"] as const,
        `${resultPath}.replay_id`,
      ),
      scenario_id: nonEmptyString(result.scenario_id, `${resultPath}.scenario_id`),
      fixture: true,
      terminal_summary: nonEmptyString(
        result.terminal_summary,
        `${resultPath}.terminal_summary`,
      ),
      terminal_disposition: nonEmptyString(
        result.terminal_disposition,
        `${resultPath}.terminal_disposition`,
      ),
      runtime_trace_digest: digest(
        result.runtime_trace_digest,
        `${resultPath}.runtime_trace_digest`,
      ),
      result_digest: digest(result.result_digest, `${resultPath}.result_digest`),
    };
  });
  if (new Set(results.map((result) => result.replay_id)).size !== 2) {
    malformed(`${path}.results`, "contain two distinct replay fixtures");
  }
  if (
    booleanValue(record.training_claim_included, `${path}.training_claim_included`)
      !== false
  ) {
    malformed(`${path}.training_claim_included`, "remain false");
  }
  return {
    report_revision: oneOf(
      record.report_revision,
      ["science-mesoscope-portability-report/1"] as const,
      `${path}.report_revision`,
    ),
    track: oneOf(record.track, ["platform_generality"] as const, `${path}.track`),
    environment_id: oneOf(
      record.environment_id,
      ["mesoscope-four-region-handoff"] as const,
      `${path}.environment_id`,
    ),
    training_claim_included: false,
    fixture_notice: nonEmptyString(record.fixture_notice, `${path}.fixture_notice`),
    compilation: {
      compilation_version: oneOf(
        compilation.compilation_version,
        ["science-environment-verifiers-v1/1"] as const,
        `${path}.compilation.compilation_version`,
      ),
      verifiers_revision: nonEmptyString(
        compilation.verifiers_revision,
        `${path}.compilation.verifiers_revision`,
      ),
      model_id: oneOf(
        compilation.model_id,
        ["google/gemma-4-E4B-it"] as const,
        `${path}.compilation.model_id`,
      ),
      model_revision: nonEmptyString(
        compilation.model_revision,
        `${path}.compilation.model_revision`,
      ),
      bundle_id: nonEmptyString(compilation.bundle_id, `${path}.compilation.bundle_id`),
      bundle_revision: nonEmptyString(
        compilation.bundle_revision,
        `${path}.compilation.bundle_revision`,
      ),
      source_bundle_digest: digest(
        compilation.source_bundle_digest,
        `${path}.compilation.source_bundle_digest`,
      ),
      artifact_digest: digest(
        compilation.artifact_digest,
        `${path}.compilation.artifact_digest`,
      ),
      artifacts,
    },
    results,
  };
}

function parseMesoscopePortabilityReplay(value: unknown): MesoscopePortabilityReplay {
  const path = "MesoscopePortabilityReplay";
  const record = exactRecord(
    value,
    [
      "replay_id",
      "source_trace_digest",
      "replay_trace_digest",
      "trace_matches",
      "source_result_digest",
      "replay_result_digest",
      "result_matches",
      "snapshot",
    ],
    path,
  );
  return {
    replay_id: oneOf(
      record.replay_id,
      ["valid-handoff", "quarantine-handoff"] as const,
      `${path}.replay_id`,
    ),
    source_trace_digest: digest(
      record.source_trace_digest,
      `${path}.source_trace_digest`,
    ),
    replay_trace_digest: digest(
      record.replay_trace_digest,
      `${path}.replay_trace_digest`,
    ),
    trace_matches: booleanValue(record.trace_matches, `${path}.trace_matches`),
    source_result_digest: digest(
      record.source_result_digest,
      `${path}.source_result_digest`,
    ),
    replay_result_digest: digest(
      record.replay_result_digest,
      `${path}.replay_result_digest`,
    ),
    result_matches: booleanValue(record.result_matches, `${path}.result_matches`),
    snapshot: parseRunSnapshot(record.snapshot),
  };
}

function parseProviderReadiness(value: unknown): ProviderReadinessSummary {
  const path = "ProviderReadinessSummary";
  const record = exactRecord(value, ["openai", "gemini"], path);
  const openai = exactRecord(
    record.openai,
    [
      "provider",
      "route",
      "requested_model",
      "adapter_revision",
      "credential_configured",
      "status",
    ],
    `${path}.openai`,
  );
  const gemini = exactRecord(
    record.gemini,
    [
      "provider",
      "route",
      "requested_model",
      "adapter_revision",
      "credential_configured",
      "status",
    ],
    `${path}.gemini`,
  );
  const configured = booleanValue(
    openai.credential_configured,
    `${path}.openai.credential_configured`,
  );
  const status = oneOf(
    openai.status,
    ["configured", "missing_credential"] as const,
    `${path}.openai.status`,
  );
  const geminiConfigured = booleanValue(
    gemini.credential_configured,
    `${path}.gemini.credential_configured`,
  );
  const geminiStatus = oneOf(
    gemini.status,
    ["configured", "missing_credential"] as const,
    `${path}.gemini.status`,
  );
  if (
    configured !== (status === "configured")
    || geminiConfigured !== (geminiStatus === "configured")
  ) {
    malformed(path, "bind each status to credential readiness");
  }
  return {
    openai: {
      provider: oneOf(openai.provider, ["openai"] as const, `${path}.openai.provider`),
      route: oneOf(openai.route, ["responses"] as const, `${path}.openai.route`),
      requested_model: oneOf(
        openai.requested_model,
        ["gpt-5.6-sol"] as const,
        `${path}.openai.requested_model`,
      ),
      adapter_revision: oneOf(
        openai.adapter_revision,
        ["openai-responses/1"] as const,
        `${path}.openai.adapter_revision`,
      ),
      credential_configured: configured,
      status,
    },
    gemini: {
      provider: oneOf(
        gemini.provider,
        ["gemini"] as const,
        `${path}.gemini.provider`,
      ),
      route: oneOf(
        gemini.route,
        ["interactions"] as const,
        `${path}.gemini.route`,
      ),
      requested_model: oneOf(
        gemini.requested_model,
        ["gemini-3.7-flash"] as const,
        `${path}.gemini.requested_model`,
      ),
      adapter_revision: oneOf(
        gemini.adapter_revision,
        ["gemini-interactions/1"] as const,
        `${path}.gemini.adapter_revision`,
      ),
      credential_configured: geminiConfigured,
      status: geminiStatus,
    },
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
  async getCatalog(): Promise<EnvironmentCatalogEntry[]> {
    return request("/api/environments", parseEnvironmentCatalog);
  },

  async getEnvironment(): Promise<EnvironmentSummary> {
    return request("/api/environment", parseEnvironmentSummary);
  },

  async getEnvironmentById(environmentId: string): Promise<EnvironmentSummary> {
    return request(
      `/api/environments/${encodeURIComponent(environmentId)}`,
      parseEnvironmentSummary,
    );
  },

  async freezeSealed(environmentId: string): Promise<SealedEnvironment> {
    return request(
      `/api/environments/${encodeURIComponent(environmentId)}/freeze`,
      parseSealedEnvironment,
      { method: "POST" },
    );
  },

  async start(
    scenarioId: string,
    policyAgent: string,
    frozenEnvironmentId: string,
    environmentId?: string,
  ): Promise<RunSnapshot> {
    return request("/api/runs", parseRunSnapshot, {
      method: "POST",
      body: JSON.stringify({
        ...(environmentId ? { environment_id: environmentId } : {}),
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

export const providerApi = {
  async readiness(): Promise<ProviderReadinessSummary> {
    return request("/api/provider-readiness", parseProviderReadiness);
  },
};

export const portabilityApi = {
  async mesoscope(): Promise<MesoscopePortabilityReport> {
    return request(
      "/api/platform-evidence/mesoscope",
      decodeMesoscopePortabilityReport,
    );
  },

  async replayMesoscope(
    replayId: MesoscopePortabilityResult["replay_id"],
  ): Promise<MesoscopePortabilityReplay> {
    return request(
      `/api/platform-evidence/mesoscope/replays/${encodeURIComponent(replayId)}`,
      parseMesoscopePortabilityReplay,
      { method: "POST" },
    );
  },
};

export const evaluationApi = {
  async list(): Promise<EvaluationSummary[]> {
    return request("/api/evaluations", parseEvaluationSummaries);
  },

  async launch(): Promise<EvaluationSnapshot> {
    return request("/api/evaluations", decodeEvaluationSnapshot, {
      method: "POST",
      body: JSON.stringify({ profile: "base-gemma-development-v1" }),
    });
  },

  async load(evaluationId: string): Promise<EvaluationSnapshot> {
    return request(
      `/api/evaluations/${encodeURIComponent(evaluationId)}`,
      decodeEvaluationSnapshot,
    );
  },

  async resume(evaluationId: string): Promise<EvaluationSnapshot> {
    return request(
      `/api/evaluations/${encodeURIComponent(evaluationId)}/resume`,
      decodeEvaluationSnapshot,
      { method: "POST" },
    );
  },

  async replay(
    evaluationId: string,
    attemptId: string,
  ): Promise<EvaluationReplay> {
    return request(
      `/api/evaluations/${encodeURIComponent(evaluationId)}/attempts/`
      + `${encodeURIComponent(attemptId)}/replay`,
      parseEvaluationReplay,
      { method: "POST" },
    );
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
