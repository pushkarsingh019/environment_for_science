export type UnknownRecord = Record<string, unknown>;

export interface PolicyAgent {
  id: string;
  name: string;
}

export interface EnvironmentValidation {
  status: string;
  summary: string;
  checks: string[];
}

export interface EnvironmentSummary {
  environmentId: string;
  scenarioId: string;
  name: string;
  description: string;
  validation: EnvironmentValidation;
  policyAgents: PolicyAgent[];
  hiddenStateExposed: boolean;
}

export interface RunSnapshot {
  run_id: string;
  scenario_id: string;
  revision_digest: string;
  scenario_digest: string;
  policy_agent: string | PolicyAgent;
  status: string;
  observation: UnknownRecord;
  permitted_actions: Array<string | UnknownRecord>;
  trace: UnknownRecord[];
  verifier_result: UnknownRecord | null;
  replay_metadata?: UnknownRecord | null;
  replay?: UnknownRecord | null;
  trace_digest?: string;
  result_digest?: string;
  [key: string]: unknown;
}
