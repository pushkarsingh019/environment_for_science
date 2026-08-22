export type JsonPrimitive = string | number | boolean | null;

export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export interface JsonObject {
  [key: string]: JsonValue;
}

/** Policy-visible JSON supplied by the Environment Runtime. */
export type UnknownRecord = JsonObject;

export interface PolicyAgentIdentity {
  id: string;
  name: string;
}

export interface EnvironmentValidationSummary {
  status: "valid";
  summary: string;
  checks: string[];
}

export interface ActionPresentation {
  type: string;
  title: string;
  description: string;
}

export interface RouteNodePresentation {
  id: string;
  name: string;
  detail: string;
  emphasis: boolean;
}

export interface EegOnsetRouteVisualization {
  kind: "eeg_onset_route";
  title: string;
  display_label: string;
  flash_label: string;
  route_nodes: RouteNodePresentation[];
  marker_lane_label: string;
  freshness_label: string;
}

/** Exact JSON DTO returned by GET /api/environment. */
export interface EnvironmentSummary {
  environment_id: string;
  scenario_id: string;
  name: string;
  description: string;
  simulation_label: string;
  actions: ActionPresentation[];
  visualization: EegOnsetRouteVisualization;
  validation: EnvironmentValidationSummary;
  hidden_state_exposed: false;
  policy_agents: PolicyAgentIdentity[];
}

export interface DraftSite {
  id: string;
  label: string;
  x: number;
  y: number;
  kind: "scalp" | "auxiliary";
}

export interface DraftApparatus {
  kind: "eeg";
  label: string;
  recording_input_capacity: number;
  coordinate_system: string;
  scientific_claim: string;
  sites: DraftSite[];
}

export interface DraftMontage {
  recording_sites: string[];
  reference: string;
  ground: string;
}

export interface DraftAcquisitionProfile {
  sampling_hz: number;
  online_bandpass_hz: [number, number];
  notch_hz: number;
}

export interface DraftProcedure {
  name: string;
  montage: DraftMontage;
  acquisition_profile: DraftAcquisitionProfile;
}

export interface DraftNote {
  id: string;
  filename: string;
  content: string;
  verification_status: "unverified_descriptive_input";
  run_control: false;
}

export interface DraftHistory {
  can_undo: boolean;
  can_redo: boolean;
}

export interface DraftActor {
  id: string;
  name: string;
  role: "authoring_assistant" | "environment_author" | "system";
}

export interface DraftLastChange {
  operation: string;
  summary: string;
  actor: DraftActor;
}

export interface AuthoringAssistantIdentity {
  id: string;
  name: string;
}

/** Exact JSON DTO returned by the reversible authoring endpoints. */
export interface EnvironmentDraft {
  draft_id: string;
  revision: number;
  revision_digest: string;
  environment_id: string;
  title: string;
  apparatus: DraftApparatus;
  procedure: DraftProcedure;
  notes: DraftNote[];
  history: DraftHistory;
  last_change: DraftLastChange;
  authoring_assistant: AuthoringAssistantIdentity;
}

export interface DraftCommandResult {
  status: "applied" | "unsupported";
  summary: string;
}

export interface DraftCommandResponse {
  draft: EnvironmentDraft;
  result: DraftCommandResult;
}

export interface FrozenEnvironment {
  frozen_environment_id: string;
  bundle_revision: string;
  revision_digest: string;
  scenario_id: string;
  draft_revision: number;
  procedure: DraftProcedure;
}

export interface TraceAction {
  type: string;
  arguments: JsonObject;
}

export interface TraceTransition {
  id: string;
  from_state: string;
  to_state: string;
  state_revision: number;
}

export interface VerifierResult {
  verifier_id: string;
  result_version: string;
  passed: boolean;
  terminal_disposition: "recovered" | "failed";
  summary: string;
  metrics: Record<string, number>;
  evidence: JsonObject;
  reasons: string[];
}

interface TraceEventBase {
  sequence: number;
  summary: string;
}

export interface ObservationTraceEvent extends TraceEventBase {
  type: "observation";
  observation: JsonObject;
  action: null;
  transition: null;
  verifier: null;
}

export interface ActionTraceEvent extends TraceEventBase {
  type: "action";
  observation: null;
  action: TraceAction;
  transition: null;
  verifier: null;
}

export interface TransitionTraceEvent extends TraceEventBase {
  type: "transition";
  observation: null;
  action: null;
  transition: TraceTransition;
  verifier: null;
}

export interface VerifierTraceEvent extends TraceEventBase {
  type: "verifier";
  observation: null;
  action: null;
  transition: null;
  verifier: VerifierResult;
}

export type TraceEvent =
  | ObservationTraceEvent
  | ActionTraceEvent
  | TransitionTraceEvent
  | VerifierTraceEvent;

export interface RunLineage {
  operation: "start" | "reset" | "replay";
  source_run_id: string | null;
}

export interface CanonicalTraceHeader {
  trace_version: "1.0";
  runtime_revision: "science-environment-runtime/1";
  bundle_id: string;
  bundle_revision: string;
  revision_digest: string;
  scenario_id: string;
  split: string;
  seed: number;
  scenario_digest: string;
  initial_state_digest: string;
  policy_agent: PolicyAgentIdentity;
}

/** Exact JSON DTO returned by each non-replay run endpoint. */
export interface RunSnapshot {
  run_id: string;
  scenario_id: string;
  revision_digest: string;
  scenario_digest: string;
  policy_agent: PolicyAgentIdentity;
  status: "active" | "awaiting_verification" | "completed";
  observation: JsonObject;
  permitted_actions: string[];
  trace: TraceEvent[];
  trace_digest: string;
  verifier_result: VerifierResult | null;
  result_digest: string | null;
  lineage: RunLineage;
  trace_header: CanonicalTraceHeader;
}

export interface ReplayReport {
  source_run_id: string;
  replay_run_id: string;
  trace_matches: boolean;
  result_matches: boolean;
  source_trace_digest: string;
  replay_trace_digest: string;
  source_result_digest: string;
  replay_result_digest: string;
}

/** Exact JSON DTO returned by POST /api/runs/{run_id}/replay. */
export interface ReplayResponse {
  snapshot: RunSnapshot;
  replay: ReplayReport;
}
