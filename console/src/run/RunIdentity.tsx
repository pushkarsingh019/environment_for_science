import { digestTail, displayName, EEG_EVIDENCE_DOMAINS, MESOSCOPE_EVIDENCE_DOMAINS } from "../app/format";
import { asObject } from "../app/json";
import type { EnvironmentSummary, JsonObject, RunSnapshot } from "../types";

function stageLabel(observation: JsonObject): string {
  return typeof observation.stage === "string" ? displayName(observation.stage) : "Unavailable";
}

function freshnessLabel(observation: JsonObject, domain: string): string {
  const entry = asObject(asObject(observation.evidence_freshness)?.[domain]);
  return entry && typeof entry.status === "string" ? displayName(entry.status) : "Unavailable";
}

/** Details-rail "Run" section: stage, Policy agent, evidence freshness, and the fixed identity. */
export function RunIdentity({ environment, run }: { environment: EnvironmentSummary; run: RunSnapshot }) {
  const mesoscope = environment.environment_kind === "mesoscope";
  const domains = mesoscope ? MESOSCOPE_EVIDENCE_DOMAINS : EEG_EVIDENCE_DOMAINS;
  return (
    <div className="run-identity">
      <dl className="identity-list">
        <div>
          <dt>{mesoscope ? "Handoff stage" : "Stage"}</dt>
          <dd data-testid="curriculum-stage">{stageLabel(run.observation)}</dd>
        </div>
        <div>
          <dt>Active Policy agent</dt>
          <dd data-testid="policy-agent-identity">{run.policy_agent.name}</dd>
        </div>
      </dl>
      <p className="eyebrow">Evidence</p>
      <dl className="identity-list" data-testid="domain-freshness">
        {domains.map(([domain, label]) => (
          <div key={domain}>
            <dt>{label}</dt>
            <dd data-testid={`domain-freshness-${domain}`}>{freshnessLabel(run.observation, domain)}</dd>
          </div>
        ))}
      </dl>
      <details className="rail-details">
        <summary>Details</summary>
        <dl className="identity-list">
          <div>
            <dt>Environment revision</dt>
            <dd data-testid="frozen-revision" title={run.revision_digest}>
              {digestTail(run.revision_digest)}
            </dd>
          </div>
          <div>
            <dt>Scenario digest</dt>
            <dd title={run.scenario_digest}>{digestTail(run.scenario_digest)}</dd>
          </div>
          <div>
            <dt>Run</dt>
            <dd>{run.run_id}</dd>
          </div>
        </dl>
        <p className="rail-note">This revision stays fixed across reset and replay.</p>
      </details>
    </div>
  );
}
