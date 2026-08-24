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
  input_schema: JsonObject;
  group: "inspect" | "collect" | "remediate" | "decide";
  changes_state: boolean;
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

export interface ScalpSitePresentation {
  id: string;
  label: string;
  x: number;
  y: number;
  kind: "scalp" | "auxiliary";
}

export interface EegPreflightVisualization {
  kind: "eeg_preflight_v1";
  title: string;
  trace_panel_label: string;
  frequency_panel_label: string;
  montage_panel_label: string;
  details_toggle_label: string;
  synthetic_label: "Synthetic EEG apparatus simulation";
  scalp_sites: ScalpSitePresentation[];
}

export interface MesoscopeHandoffVisualization {
  kind: "mesoscope_handoff_v1";
  title: string;
  synthetic_label: "SYNTHETIC";
  sealed_label: "SEALED — DISCONNECTED FROM HARDWARE";
  survey_label: string;
  raw_view_label: string;
  spatial_view_label: string;
  details_toggle_label: string;
  profile_provenance: MesoscopeProvenance;
  plan_provenance: MesoscopeProvenance;
  package_provenance: MesoscopeProvenance[];
  region_ids: ["R1", "R2", "R3", "R4"];
  depth_labels: ["Z-A", "Z-B"];
}

export interface MesoscopeProvenance {
  classification: "INSTRUMENT FACT" | "SOFTWARE FACT" | "SIMULATION CHOICE";
  citation_ids: string[];
  note: string;
}

export type EegVisualization =
  | EegOnsetRouteVisualization
  | EegPreflightVisualization;

export type EnvironmentVisualization =
  | EegVisualization
  | MesoscopeHandoffVisualization;

export type EnvironmentKind = "eeg" | "mesoscope";
export type EnvironmentSourceKind = "editable_draft" | "sealed_seed";

export interface EnvironmentCatalogEntry {
  environment_id: string;
  environment_kind: EnvironmentKind;
  name: string;
  navigation_label: string;
  navigation_summary: string;
  source_kind: EnvironmentSourceKind;
}

export interface SeededScenarioSummary {
  scenario_id: string;
  label: string;
  stage: "preflight" | "short_acquisition" | "sealed_handoff";
}

/** Exact JSON DTO returned by GET /api/environment. */
export interface EnvironmentSummary {
  environment_id: string;
  environment_kind: EnvironmentKind;
  source_kind: EnvironmentSourceKind;
  name: string;
  description: string;
  simulation_label: string;
  seeded_examples: SeededScenarioSummary[];
  actions: ActionPresentation[];
  visualization: EnvironmentVisualization;
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
  draft_revision: number;
  procedure: DraftProcedure;
}

export interface SealedEnvironment {
  frozen_environment_id: string;
  environment_id: string;
  source_kind: "sealed_seed";
  bundle_revision: string;
  revision_digest: string;
  sealed_profile_id: string;
  signed_plan_id: string;
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
  terminal_disposition: "recovered" | "closed" | "aborted" | "failed";
  outcome_category: string | null;
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

export type EvaluationStatus = "queued" | "running" | "completed" | "interrupted";
export type EvaluationDisposition =
  | "scientific_success"
  | "scientific_failure"
  | "infrastructure_error";

export interface EvaluationModelIdentity {
  provider: "local-openai-compatible";
  requested_model: "google/gemma-4-E4B-it";
  adapter_revision: "local-gemma-openai-chat/1";
}

export interface EvaluationProgress {
  phase: EvaluationStatus;
  message: string;
  completed_scenarios: number;
  total_scenarios: number;
  scientific_successes: number;
  scientific_failures: number;
  infrastructure_errors: number;
}

export type EvaluationCalibrationStatus = "pending" | "ready" | "not_ready";

export interface EvaluationCalibrationLevel {
  level: 0 | 1 | 2 | 3 | 4 | 5;
  label: string;
  total_scenarios: number;
  completed_scenarios: number;
  scientific_successes: number;
  scientific_failures: number;
  infrastructure_errors: number;
  has_success_and_failure: boolean;
}

export interface EvaluationCalibration {
  status: EvaluationCalibrationStatus;
  summary: string;
  scientific_accuracy: number | null;
  target_accuracy_minimum: 0.2;
  target_accuracy_maximum: 0.7;
  overall_accuracy_in_target: boolean;
  levels_1_and_2_mixed: boolean;
  no_infrastructure_errors: boolean;
  authenticated_local_runtime: boolean;
  levels: EvaluationCalibrationLevel[];
}

export interface EvaluationAttemptSummary {
  attempt_id: string;
  ordinal: number;
  scenario_id: string;
  disposition: EvaluationDisposition;
  summary: string;
  interaction_digest: string;
  runtime_trace_digest: string;
  result_digest: string | null;
}

export interface EvaluationPlan {
  plan_revision: "science-environment-evaluation-plan/1";
  profile: "base-gemma-development-v1";
  environment_id: string;
  bundle_revision: string;
  bundle_digest: string;
  split: "development";
  curriculum_package_digest: string;
  model: EvaluationModelIdentity;
  model_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2";
  objective: string;
  scenario_ids: string[];
}

export interface EvaluationSummary {
  evaluation_id: string;
  profile: "base-gemma-development-v1";
  model: EvaluationModelIdentity;
  status: EvaluationStatus;
  progress: EvaluationProgress;
}

export interface EvaluationSnapshot {
  evaluation_id: string;
  status: EvaluationStatus;
  plan: EvaluationPlan;
  progress: EvaluationProgress;
  calibration: EvaluationCalibration;
  attempts: EvaluationAttemptSummary[];
}

export interface EvaluationReplayReport {
  source_trace_digest: string;
  replay_trace_digest: string;
  trace_matches: boolean;
  source_result_digest: string;
  replay_result_digest: string;
  result_matches: boolean;
}

export interface EvaluationInfrastructureError {
  category: "adapter" | "inference" | "protocol";
  code: string;
  summary: string;
}

export interface EvaluationToolCall {
  call_id: string;
  provider_call_id: string;
  ordinal: number;
  name: string;
  arguments: JsonObject;
}

export interface EvaluationMessage {
  role: "user" | "assistant" | "tool";
  content: string | JsonObject;
  response_id: string | null;
  response_turn: number | null;
  tool_calls: EvaluationToolCall[];
  tool_call_id: string | null;
  provider_tool_call_id: string | null;
  tool_call_ordinal: number | null;
  tool_name: string | null;
  provider_state: JsonObject[];
}

export interface EvaluationTokenUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cached_input_tokens: number | null;
  reasoning_tokens: number | null;
}

export interface EvaluationResponseRecord {
  turn: number;
  response_id: string;
  returned_model: string;
  usage: EvaluationTokenUsage | null;
  metadata: {
    created_unix_seconds: number;
    finish_reason: "stop" | "tool_calls" | "length";
    system_fingerprint: string | null;
    runtime_instance_id: string | null;
    provider_request_id: string | null;
    service_tier: string | null;
    provider_usage: JsonObject | null;
  } | null;
}

export interface EvaluationToolResult {
  call_id: string;
  provider_call_id: string;
  ordinal: number;
  name: string;
  status: "ok" | "error";
  observation: JsonObject | null;
  error_code: string | null;
  execution_id: string | null;
  cache_hit: boolean | null;
  retry_count: number | null;
}

export interface EvaluationRuntimeExecution {
  call_id: string;
  ordinal: number;
  execution_id: string;
  action: TraceAction;
  observation: JsonObject;
  resulting_status: "active" | "awaiting_verification";
  resulting_trace_digest: string;
  cache_hit: boolean;
  retry_count: number;
}

export interface EvaluationPythonRuntime {
  implementation: "cpython";
  version: "3.12";
  abi_tag: "cp312";
  platform: "linux-x86_64";
}

export type EvaluationRuntimeDistributionName =
  | "jinja2"
  | "safetensors"
  | "tokenizers"
  | "torch"
  | "transformers"
  | "vllm"
  | "science-environment-studio";

export interface EvaluationRuntimeDistribution {
  distribution: EvaluationRuntimeDistributionName;
  version: string;
  wheel_sha256: string;
  record_manifest_sha256: string;
  import_module: string;
  import_origin: string;
  import_origin_sha256: string;
  verification: "wheel-record-sha256+import-origin";
}

export interface EvaluationLocalGemmaAttestation {
  attestation_version: "science-local-gemma-runtime-attestation/1";
  attestation_id: string;
  runtime_instance_id: string;
  trusted_bootstrap_sha256: string;
  challenge_nonce: string;
  generated_at_utc: string;
  runtime_started_at_utc: string;
  served_model: "google/gemma-4-E4B-it";
  checkpoint_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2";
  checkpoint_weights_sha256: string;
  tokenizer_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2";
  tokenizer_manifest_sha256: string;
  renderer_revision: "f770dcaa362e3a6a13a96f039741b3b84ca4114e";
  vllm_version: "0.26.0+cu129";
  vllm_source_revision: "568afb3a13806beb53bb2e6bd518269357b237c0";
  vllm_wheel_sha256: string;
  python_runtime: EvaluationPythonRuntime;
  runtime_receipt_id: "science-local-gemma-runtime-cp312-cu129/1";
  runtime_distributions: EvaluationRuntimeDistribution[];
  product_distribution: EvaluationRuntimeDistribution;
  python_bytecode_mode: "fresh-private-prefix-no-write";
  serving_root_filesystem_mode: "kernel-read-only-mount";
  network_scope: "loopback-only";
  api_key_authentication: true;
  attestation_middleware_revision: "science-local-gemma-attestation-middleware/1";
  vllm_config: {
    dtype: "bfloat16";
    max_model_len: 32768;
    tensor_parallel_size: 1;
    gpu_memory_utilization: 0.35;
    enforce_eager: true;
    max_num_seqs: 16;
    generation_config: "vllm";
    tool_call_parser: "gemma4";
    enable_auto_tool_choice: true;
    enable_lora: false;
    disable_log_requests: true;
    limit_mm_per_prompt: { image: 0; audio: 0; video: 0 };
  };
  adapter_revision: "local-gemma-openai-chat/1";
  served_adapter: "none";
  sampling_profile: "base-gemma-development-chat-v1";
  max_episode_seconds: 900;
  platform: "linux-x86_64";
  accelerator_architecture: string;
  accelerator_count: number;
  cuda_version: string;
  driver_version: string;
  serving_image_digest: string;
  serving_image_digest_provenance: "operator-supplied";
  evidence_scope: "server-reported-runtime-state";
  signature: string;
  evidence_digest: string;
  verification_method: "hmac-sha256-server-challenge";
}

export interface EvaluationInteraction {
  trace_version: "1.0";
  model: EvaluationModelIdentity;
  sampling: {
    profile: "base-gemma-development-chat-v1";
    temperature: 0;
    max_output_tokens: 2048;
    tool_choice: "auto";
    top_p: null;
    seed: null;
    streaming: false;
    store: false;
  };
  budgets: {
    max_turns: number;
    max_tool_calls: number;
    max_provider_tool_calls: 64;
    max_episode_seconds: 900;
  };
  run: {
    profile: "base-gemma-development-v1";
    started_at_utc: string;
    completed_at_utc: string;
    local_gemma_attestation: EvaluationLocalGemmaAttestation | null;
  };
  messages: EvaluationMessage[];
  responses: EvaluationResponseRecord[];
  tool_calls: EvaluationToolCall[];
  tool_results: EvaluationToolResult[];
  accepted_actions: TraceAction[];
  runtime_executions: EvaluationRuntimeExecution[];
  runtime_events: TraceEvent[];
  runtime_trace_digest: string;
  infrastructure_error: EvaluationInfrastructureError | null;
  interaction_digest: string;
}

export interface EvaluationReplay {
  evaluation_id: string;
  attempt: EvaluationAttemptSummary;
  interaction: EvaluationInteraction;
  snapshot: RunSnapshot | null;
  report: EvaluationReplayReport | null;
  infrastructure_error: EvaluationInfrastructureError | null;
}

export interface MesoscopePortabilityResult {
  replay_id: "valid-handoff" | "quarantine-handoff";
  scenario_id: string;
  fixture: true;
  terminal_summary: string;
  terminal_disposition: string;
  runtime_trace_digest: string;
  result_digest: string;
}

export interface MesoscopePortabilityReport {
  report_revision: "science-mesoscope-portability-report/1";
  track: "platform_generality";
  environment_id: "mesoscope-four-region-handoff";
  training_claim_included: false;
  fixture_notice: string;
  compilation: {
    compilation_version: "science-environment-verifiers-v1/1";
    verifiers_revision: string;
    model_id: "google/gemma-4-E4B-it";
    model_revision: string;
    bundle_id: string;
    bundle_revision: string;
    source_bundle_digest: string;
    artifact_digest: string;
    artifacts: Array<{ path: string; digest: string; size_bytes: number }>;
  };
  results: MesoscopePortabilityResult[];
}

export interface OpenAIProviderReadiness {
  provider: "openai";
  route: "responses";
  requested_model: "gpt-5.6-sol";
  adapter_revision: "openai-responses/1";
  credential_configured: boolean;
  status: "configured" | "missing_credential";
}

export interface GeminiProviderReadiness {
  provider: "gemini";
  route: "interactions";
  requested_model: "gemini-3.7-flash";
  adapter_revision: "gemini-interactions/1";
  credential_configured: boolean;
  status: "configured" | "missing_credential";
}

export interface ProviderReadinessSummary {
  openai: OpenAIProviderReadiness;
  gemini: GeminiProviderReadiness;
}

export interface DemoResetSummary {
  reset_version: "science-demo-reset/1";
  status: "reset";
  draft_revision: number;
  draft_digest: string;
  comparison_fixture_state: "successful";
  seeded_scenarios_restored: true;
  immutable_training_jobs_preserved: number;
  immutable_real_comparisons_preserved: number;
  immutable_artifacts_deleted: 0;
  summary: string;
}

export type ComparisonFixtureState =
  | "successful"
  | "inconclusive"
  | "regressed"
  | "partially_unavailable"
  | "adapter_error";

export type ComparisonModelRole =
  | "base_gemma"
  | "trained_gemma"
  | "openai_reference"
  | "gemini_reference";

export interface ComparisonScenarioLink {
  scenario_id: string;
  run_id: string;
  runtime_trace_digest: string;
  result_digest: string;
  success: boolean;
  verifier_score: number;
  replay_route: string;
}

export interface ComparisonStratum {
  count: number;
  task_success: number | null;
  verifier_score: number | null;
}

export interface ComparisonMetrics {
  scenario_count: number;
  task_success: number;
  verifier_score: number;
  abort_precision: number | null;
  abort_recall: number | null;
  mean_action_count: number;
  tool_errors: number;
  strata: Record<"individual" | "ambiguous" | "pair" | "triple", ComparisonStratum>;
}

export interface ComparisonModelResult {
  role: ComparisonModelRole;
  label: string;
  reference_model: boolean;
  requested_model: string;
  returned_model: string | null;
  adapter_identity: string | null;
  model_configuration_digest: string;
  run_id: string;
  status:
    | "available"
    | "credential_missing"
    | "provider_failure"
    | "adapter_failure"
    | "scientific_failure";
  metrics: ComparisonMetrics | null;
  failure: { category: "credential" | "provider" | "adapter" | "scientific"; summary: string } | null;
  scenarios: ComparisonScenarioLink[];
}

export interface PairedBootstrapAnalysis {
  analysis_version: "eeg-paired-bootstrap/1";
  seed: number;
  replicates: number;
  scenario_count: number;
  base_successes: number;
  trained_successes: number;
  trained_minus_base: number;
  confidence_level: number;
  interval_low: number;
  interval_high: number;
  conclusion: "improved" | "inconclusive" | "regressed";
  paired_outcomes_digest: string;
}

export interface ModelComparisonResult {
  comparison_version: "scientist-model-comparison/1";
  comparison_id: string;
  source: "seeded_offline_fixture" | "real_evaluation";
  fixture_state: ComparisonFixtureState | null;
  fixture_notice: string | null;
  claim_scope: "within_eeg_compositional_generalization";
  provenance: {
    scenario_manifest_id: "eeg-curriculum-release-1:held_out";
    scenario_manifest_digest: string;
    environment_bundle_id: "eeg-curriculum";
    environment_bundle_revision: "1.4.0";
    scoring_revision: "eeg-curriculum-scorer-1";
  };
  models: ComparisonModelResult[];
  gemma_contrast: PairedBootstrapAnalysis | null;
  training_claim: "improved" | "inconclusive" | "regressed" | "unavailable";
  mesoscope: {
    claim_scope: "platform_generality";
    label: "Separate mesoscope platform-generality evidence";
    compiler_route: "/api/platform-evidence/mesoscope";
    replay_route: "/api/platform-evidence/mesoscope/replay";
    eeg_training_evidence: false;
  };
}

export interface ComparisonReplay {
  replay_version: "scientist-model-comparison-replay/1";
  source: "seeded_offline_fixture" | "real_evaluation";
  provenance: ModelComparisonResult["provenance"];
  model_role: ComparisonModelRole;
  scenario: ComparisonScenarioLink;
  reproducible: true;
}

export interface CurriculumTrainingJob {
  job_id: string;
  status: "queued" | "running" | "failed" | "completed";
  message: string;
  training_scenarios: 96;
  development_scenarios: 32;
  heldout_scenarios: 64;
  training_package_digest: string;
  development_package_digest: string;
  heldout_package_digest: string;
  result_id: string | null;
  result_digest: string | null;
}

export interface TrainingOptimizationMetrics {
  loss: number;
  gradient_norm: number;
  mismatch_kl: number;
}

export interface TrainingAcceptanceEvidence {
  evidence_version: "science-gemma-acceptance-evidence/1";
  job_id: string;
  status: "verified";
  model: "google/gemma-4-E4B-it" | "google/gemma-4-E2B-it";
  model_revision: string;
  fallback_used: boolean;
  stack: Record<string, string>;
  configuration_digest: string;
  training_hardware_id: string;
  inference_hardware_id: string;
  optimization_metrics: TrainingOptimizationMetrics;
  adapter_tensor_count: number;
  changed_adapter_tensors: number;
  checkpoint_files: number;
  initial_adapter_digest: string;
  final_adapter_digest: string;
  reloaded_served_identity: "proof-final";
  training_scenario_ids: string[];
  training_trace_digests: string[];
  heldout_scenario_ids: string[];
  baseline_trace_digests: string[];
  reloaded_trace_digests: string[];
  artifact_digest: string;
}

export interface TrainingAcceptanceJob {
  job_id: string;
  status: "queued" | "running" | "failed" | "completed";
  message: string;
  artifact_reference: string;
  evidence: TrainingAcceptanceEvidence | null;
}

export interface MesoscopePortabilityReplay {
  replay_id: "valid-handoff" | "quarantine-handoff";
  source_trace_digest: string;
  replay_trace_digest: string;
  trace_matches: boolean;
  source_result_digest: string;
  replay_result_digest: string;
  result_matches: boolean;
  snapshot: RunSnapshot;
}
