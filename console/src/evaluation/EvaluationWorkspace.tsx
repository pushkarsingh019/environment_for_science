import { useEffect, useState } from "react";
import { evaluationApi, portabilityApi, providerApi } from "../api";
import type {
  EvaluationAttemptSummary,
  EvaluationInteraction,
  EvaluationReplay,
  EvaluationSnapshot,
  EvaluationStatus,
  EvaluationSummary,
  MesoscopePortabilityReplay,
  MesoscopePortabilityReport,
  ProviderReadinessSummary,
  TraceEvent,
} from "../types";

const POLL_INTERVAL_MS = 750;
const POLL_MAX_INTERVAL_MS = 6_000;

function pollRetryDelay(consecutiveFailures: number): number {
  const exponent = Math.min(consecutiveFailures, 3);
  return Math.min(POLL_INTERVAL_MS * (2 ** exponent), POLL_MAX_INTERVAL_MS);
}

function statusLabel(status: EvaluationStatus): string {
  return {
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    interrupted: "Interrupted",
  }[status];
}

function dispositionLabel(
  disposition: EvaluationAttemptSummary["disposition"],
): string {
  return {
    scientific_success: "Scientific success",
    scientific_failure: "Scientific failure",
    infrastructure_error: "Infrastructure error",
  }[disposition];
}

function asSummary(snapshot: EvaluationSnapshot): EvaluationSummary {
  return {
    evaluation_id: snapshot.evaluation_id,
    profile: snapshot.plan.profile,
    model: snapshot.plan.model,
    status: snapshot.status,
    progress: snapshot.progress,
  };
}

function mergeSummary(
  summaries: EvaluationSummary[],
  snapshot: EvaluationSnapshot,
): EvaluationSummary[] {
  return [
    asSummary(snapshot),
    ...summaries.filter((item) => item.evaluation_id !== snapshot.evaluation_id),
  ];
}

function safeMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function EvaluationList({
  evaluations,
  busy,
  onLoad,
}: {
  evaluations: EvaluationSummary[];
  busy: boolean;
  onLoad: (evaluationId: string) => void;
}) {
  return (
    <section className="evaluation-card evaluation-list-card" data-testid="evaluation-list">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Durable local runs</p>
          <h2>Existing evaluations</h2>
        </div>
        <span className="evaluation-count">{evaluations.length}</span>
      </div>
      {evaluations.length === 0 ? (
        <p className="evaluation-empty">
          No local evaluation has been reserved yet. Launching creates a fixed,
          restart-safe 32-scenario plan.
        </p>
      ) : (
        <ul className="evaluation-list">
          {evaluations.map((evaluation) => (
            <li key={evaluation.evaluation_id}>
              <div>
                <strong>{statusLabel(evaluation.status)}</strong>
                <span>
                  {evaluation.progress.completed_scenarios} / {evaluation.progress.total_scenarios}
                  {" scenarios"}
                </span>
                <small>{evaluation.model.requested_model}</small>
              </div>
              <button
                className="secondary-button evaluation-load-button"
                data-testid={`load-${evaluation.evaluation_id}`}
                disabled={busy}
                onClick={() => onLoad(evaluation.evaluation_id)}
                type="button"
              >
                Load
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProgressPanel({
  snapshot,
  busy,
  onResume,
}: {
  snapshot: EvaluationSnapshot;
  busy: boolean;
  onResume: () => void;
}) {
  const progress = snapshot.progress;
  const percentage = Math.round(
    (progress.completed_scenarios / progress.total_scenarios) * 100,
  );
  return (
    <section className="evaluation-card evaluation-progress-card" aria-live="polite">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Development calibration</p>
          <h2>{statusLabel(snapshot.status)}</h2>
        </div>
        <span className={`evaluation-status is-${snapshot.status}`}>
          {progress.completed_scenarios} / {progress.total_scenarios}
        </span>
      </div>
      <p
        className="evaluation-progress-message"
        data-testid="evaluation-progress-message"
      >
        {progress.message}
      </p>
      {snapshot.status === "interrupted" && (
        <button
          className="secondary-button evaluation-resume-button"
          data-testid="resume-evaluation"
          disabled={busy}
          onClick={onResume}
          type="button"
        >
          {busy ? "Resuming…" : "Resume evaluation"}
        </button>
      )}
      <div
        aria-label={`${percentage}% complete`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percentage}
        className="evaluation-progress-track"
        role="progressbar"
      >
        <span style={{ width: `${percentage}%` }} />
      </div>
      <div className="evaluation-outcomes">
        <article data-testid="evaluation-scientific-successes">
          <strong>{progress.scientific_successes}</strong>
          <span>Scientific successes</span>
        </article>
        <article data-testid="evaluation-scientific-failures">
          <strong>{progress.scientific_failures}</strong>
          <span>Scientific failures</span>
        </article>
        <article data-testid="evaluation-infrastructure-errors">
          <strong>{progress.infrastructure_errors}</strong>
          <span>Infrastructure errors</span>
        </article>
      </div>
    </section>
  );
}

function CalibrationPanel({ snapshot }: { snapshot: EvaluationSnapshot }) {
  const calibration = snapshot.calibration;
  const statusHeading = {
    pending: "Readiness pending",
    ready: "Ready for training",
    not_ready: "Not ready for training",
  }[calibration.status];
  const accuracy = calibration.scientific_accuracy === null
    ? "No scientific accuracy yet"
    : `${Math.round(calibration.scientific_accuracy * 100)}% scientific accuracy`;
  return (
    <section
      className="evaluation-card evaluation-calibration"
      data-testid="evaluation-calibration"
    >
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Pre-training assessment</p>
          <h2>{statusHeading}</h2>
        </div>
        <span className={`evaluation-status is-${calibration.status}`}>
          {accuracy}
        </span>
      </div>
      <p>{calibration.summary}</p>
      <dl className="evaluation-calibration-checks">
        <div>
          <dt>20–70% accuracy band</dt>
          <dd>{calibration.overall_accuracy_in_target ? "Met" : "Not met"}</dd>
        </div>
        <div>
          <dt>Mixed outcomes in levels 1 and 2</dt>
          <dd>{calibration.levels_1_and_2_mixed ? "Met" : "Not met"}</dd>
        </div>
        <div>
          <dt>No infrastructure errors</dt>
          <dd>{calibration.no_infrastructure_errors ? "Met" : "Not met"}</dd>
        </div>
        <div>
          <dt>Authenticated local runtime</dt>
          <dd>{calibration.authenticated_local_runtime ? "Met" : "Not met"}</dd>
        </div>
      </dl>
      <div
        className="evaluation-calibration-levels"
        data-testid="evaluation-calibration-levels"
      >
        {calibration.levels.map((level) => (
          <article key={level.level}>
            <header>
              <strong>Level {level.level}</strong>
              <span>{level.completed_scenarios} / {level.total_scenarios}</span>
            </header>
            <p>{level.label}</p>
            <small>
              {level.scientific_successes} success · {level.scientific_failures} failure
              {" · "}{level.infrastructure_errors} infrastructure
            </small>
          </article>
        ))}
      </div>
    </section>
  );
}

function eventPayload(event: TraceEvent) {
  switch (event.type) {
    case "observation": return event.observation;
    case "action": return event.action;
    case "transition": return event.transition;
    case "verifier": return event.verifier;
  }
}

function eventLabel(event: TraceEvent): string {
  return event.type[0].toUpperCase() + event.type.slice(1);
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function InteractionEvidence({ interaction }: { interaction: EvaluationInteraction }) {
  const results = new Map(
    interaction.tool_results.map((result) => [result.call_id, result]),
  );
  const runtimeAttestation = interaction.run.local_gemma_attestation;
  return (
    <div className="evaluation-interaction-evidence">
      {runtimeAttestation && (
        <section data-testid="evaluation-replay-runtime-attestation">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">Authenticated local serving receipt</p>
              <h3>Direct inference stack provenance</h3>
            </div>
            <span className="evaluation-count">
              {runtimeAttestation.runtime_distributions.length}
            </span>
          </div>
          <div className="evaluation-response-list">
            <article>
              <div>
                <strong>{runtimeAttestation.runtime_receipt_id}</strong>
                <code>{runtimeAttestation.evidence_digest}</code>
              </div>
              <span>
                CPython {runtimeAttestation.python_runtime.version}
                {" · "}{runtimeAttestation.python_runtime.abi_tag}
                {" · "}{runtimeAttestation.python_runtime.platform}
              </span>
              <span>
                {runtimeAttestation.runtime_distributions.length}
                {" directly verified serving distributions"}
              </span>
            </article>
            <article>
              <div>
                <strong>
                  {runtimeAttestation.product_distribution.distribution}
                  {" "}{runtimeAttestation.product_distribution.version}
                </strong>
                <code>{runtimeAttestation.product_distribution.wheel_sha256}</code>
              </div>
              <span>Verified product wheel and installed RECORD contents</span>
              <span>
                Independent bootstrap
                {" "}<code>{runtimeAttestation.trusted_bootstrap_sha256}</code>
              </span>
            </article>
          </div>
          <ol className="evaluation-evidence-list">
            {runtimeAttestation.runtime_distributions.map((distribution) => (
              <li key={distribution.distribution}>
                <div>
                  <strong>
                    {distribution.distribution} {distribution.version}
                  </strong>
                  <span>{distribution.verification}</span>
                </div>
                <p>
                  Import: <code>{distribution.import_origin}</code>
                </p>
                <details>
                  <summary>Inspect artifact and installed-file digests</summary>
                  <pre>{canonicalJson({
                    wheel_sha256: distribution.wheel_sha256,
                    record_manifest_sha256: distribution.record_manifest_sha256,
                    import_origin_sha256: distribution.import_origin_sha256,
                  })}</pre>
                </details>
              </li>
            ))}
          </ol>
          <p>
            Direct serving stack and product wheel verified on a
            {" "}{runtimeAttestation.serving_root_filesystem_mode}; Python uses
            {" "}{runtimeAttestation.python_bytecode_mode}. Complete transitive
            closure and the pre-exec service envelope remain operator-supplied
            immutable-image provenance.
          </p>
        </section>
      )}
      <section data-testid="evaluation-replay-runtime-events">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">Canonical Runtime evidence</p>
            <h3>Observations, actions, transitions, and verification</h3>
          </div>
          <span className="evaluation-count">{interaction.runtime_events.length}</span>
        </div>
        <ol className="evaluation-evidence-list">
          {interaction.runtime_events.map((event) => (
            <li key={event.sequence}>
              <div>
                <span>#{event.sequence}</span>
                <strong>{eventLabel(event)}</strong>
              </div>
              <p>{event.summary}</p>
              <details>
                <summary>Inspect canonical payload</summary>
                <pre>{canonicalJson(eventPayload(event))}</pre>
              </details>
            </li>
          ))}
        </ol>
        <div
          className="evaluation-execution-ledger"
          data-testid="evaluation-replay-executions"
        >
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">Canonical execution ledger</p>
              <h3>Accepted actions, observations, and idempotency evidence</h3>
            </div>
            <span className="evaluation-count">{interaction.runtime_executions.length}</span>
          </div>
          <ol className="evaluation-evidence-list">
            {interaction.runtime_executions.map((execution) => (
              <li key={execution.execution_id}>
                <div>
                  <span>Ordinal {execution.ordinal}</span>
                  <strong>{execution.action.type}</strong>
                </div>
                <p>
                  Canonical: <code>{execution.call_id}</code>
                </p>
                <p>
                  Execution: <code>{execution.execution_id}</code>
                  {" · "}Cache: {execution.cache_hit ? "hit" : "miss"}
                  {" · "}Retries: {execution.retry_count}
                </p>
                <p>
                  Resulting status: {execution.resulting_status}
                  {" · "}Trace: <code>{execution.resulting_trace_digest}</code>
                </p>
                <details>
                  <summary>Inspect action and observation</summary>
                  <pre>{canonicalJson({
                    action: execution.action,
                    observation: execution.observation,
                  })}</pre>
                </details>
              </li>
            ))}
          </ol>
        </div>
      </section>
      <section data-testid="evaluation-replay-interaction">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">Model interaction lineage</p>
            <h3>Messages, tool calls, and linked results</h3>
          </div>
          <span className="evaluation-count">{interaction.messages.length}</span>
        </div>
        <div
          className="evaluation-response-list"
          data-testid="evaluation-replay-budget"
        >
          <article>
            <div>
              <strong>Episode budget</strong>
              <code>{interaction.budgets.max_episode_seconds} seconds</code>
            </div>
            <span>
              {interaction.budgets.max_turns} turns
              {" · "}{interaction.budgets.max_tool_calls} tool calls
              {" · "}{interaction.sampling.max_output_tokens} output tokens per response
            </span>
          </article>
        </div>
        <div
          className="evaluation-response-list"
          data-testid="evaluation-replay-responses"
        >
          {interaction.responses.map((response) => (
            <article key={response.response_id}>
              <div>
                <strong>Turn {response.turn}</strong>
                <code>{response.response_id}</code>
              </div>
              <span>
                Finish: {response.metadata?.finish_reason ?? "not reported"}
                {" · "}Tokens: {response.usage?.total_tokens ?? "not reported"}
              </span>
            </article>
          ))}
        </div>
        <ol className="evaluation-message-list">
          {interaction.messages.map((message, index) => (
            <li key={`${index}-${message.role}-${message.tool_call_id ?? "message"}`}>
              <header>
                <strong>{message.role}</strong>
                {message.response_id && (
                  <code>
                    Response turn {message.response_turn}: {message.response_id}
                  </code>
                )}
                {message.tool_call_id && (
                  <code>
                    Canonical ordinal {message.tool_call_ordinal}: {message.tool_call_id}
                    {" · "}Provider: {message.provider_tool_call_id}
                  </code>
                )}
              </header>
              <pre>{typeof message.content === "string"
                ? message.content
                : canonicalJson(message.content)}</pre>
              {message.tool_calls.map((call) => {
                const result = results.get(call.call_id);
                return (
                  <div className="evaluation-call-lineage" key={call.call_id}>
                    <div>
                      <code>Canonical ordinal {call.ordinal}: {call.call_id}</code>
                      <code>Provider: {call.provider_call_id}</code>
                      <strong>{call.name}</strong>
                      <span>Result: {result?.status ?? "missing"}</span>
                    </div>
                    {result?.execution_id && (
                      <div>
                        <code>Execution: {result.execution_id}</code>
                        <span>
                          Cache: {result.cache_hit ? "hit" : "miss"}
                          {" · "}Retries: {result.retry_count}
                        </span>
                      </div>
                    )}
                    <pre>{canonicalJson(call.arguments)}</pre>
                    {result && (
                      <details>
                        <summary>Inspect linked result</summary>
                        <pre>{canonicalJson(result)}</pre>
                      </details>
                    )}
                  </div>
                );
              })}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ReplayPanel({ replay }: { replay: EvaluationReplay }) {
  if (replay.infrastructure_error) {
    return (
      <section className="evaluation-card evaluation-replay" data-testid="evaluation-replay">
        <p className="eyebrow">Stored non-scientific outcome</p>
        <h2>Infrastructure error</h2>
        <p>{replay.infrastructure_error.summary}</p>
        <code>{replay.infrastructure_error.code}</code>
        <InteractionEvidence interaction={replay.interaction} />
      </section>
    );
  }
  const report = replay.report;
  const snapshot = replay.snapshot;
  if (!report || !snapshot) return null;
  const bothMatch = report.trace_matches && report.result_matches;
  return (
    <section className="evaluation-card evaluation-replay" data-testid="evaluation-replay">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Read-only deterministic replay</p>
          <h2>{bothMatch ? "Trace and scientific result both match" : "Replay mismatch"}</h2>
        </div>
        <span className={`evaluation-status ${bothMatch ? "is-completed" : "is-interrupted"}`}>
          {bothMatch ? "Matched" : "Review"}
        </span>
      </div>
      <p>{snapshot.verifier_result?.summary ?? replay.attempt.summary}</p>
      <dl className="evaluation-replay-checks">
        <div><dt>Canonical trace</dt><dd>{report.trace_matches ? "Match" : "Mismatch"}</dd></div>
        <div><dt>Verifier result</dt><dd>{report.result_matches ? "Match" : "Mismatch"}</dd></div>
      </dl>
      <InteractionEvidence interaction={replay.interaction} />
    </section>
  );
}

function AttemptTable({
  snapshot,
  busy,
  onReplay,
}: {
  snapshot: EvaluationSnapshot;
  busy: boolean;
  onReplay: (attemptId: string) => void;
}) {
  return (
    <section className="evaluation-card evaluation-attempt-card" data-testid="evaluation-attempts">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Completed scenario attempts</p>
          <h2>Scientific and infrastructure outcomes</h2>
        </div>
        <span className="evaluation-count">{snapshot.attempts.length}</span>
      </div>
      {snapshot.attempts.length === 0 ? (
        <p className="evaluation-empty">Attempts will appear here as durable slots complete.</p>
      ) : (
        <div className="evaluation-table-scroll">
          <table className="evaluation-table">
            <thead>
              <tr><th>Scenario</th><th>Disposition</th><th>Summary</th><th>Replay</th></tr>
            </thead>
            <tbody>
              {snapshot.attempts.map((attempt) => (
                <tr key={attempt.attempt_id}>
                  <td>
                    <code>{attempt.attempt_id}</code>
                    <small>{attempt.scenario_id}</small>
                  </td>
                  <td>
                    <span className={`evaluation-disposition is-${attempt.disposition}`}>
                      {dispositionLabel(attempt.disposition)}
                    </span>
                  </td>
                  <td>{attempt.summary}</td>
                  <td>
                    <button
                      className="secondary-button evaluation-replay-button"
                      data-testid={`replay-${attempt.attempt_id}`}
                      disabled={busy}
                      onClick={() => onReplay(attempt.attempt_id)}
                      type="button"
                    >
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MesoscopePortabilityWorkspace() {
  const [report, setReport] = useState<MesoscopePortabilityReport | null>(null);
  const [replay, setReplay] = useState<MesoscopePortabilityReplay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    portabilityApi.mesoscope()
      .then((loaded) => {
        if (active) setReport(loaded);
      })
      .catch((reason: unknown) => {
        if (active) setError(safeMessage(reason, "Unable to load portability evidence."));
      });
    return () => { active = false; };
  }, []);

  async function openReplay(
    replayId: "valid-handoff" | "quarantine-handoff",
  ) {
    setBusy(true);
    setError(null);
    try {
      setReplay(await portabilityApi.replayMesoscope(replayId));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to replay portability evidence."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="mesoscope-evaluation-heading"
      className="workspace-mode-panel evaluation-workspace"
      data-testid="mesoscope-portability-workspace"
      id="evaluation-workspace"
      role="tabpanel"
    >
      <div className="workspace-heading evaluation-heading">
        <div>
          <p className="breadcrumb">Mesoscope Environment / Separate evidence track</p>
          <h1 id="mesoscope-evaluation-heading">Platform-generality evidence</h1>
          <p>
            The sealed synthetic handoff uses the same compiler, Runtime, Verifiers
            adapter contract, canonical trace, and replay lifecycle as EEG.
          </p>
        </div>
        <span className="scenario-tag">No training claim</span>
      </div>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {!report ? (
        <section className="evaluation-card">
          <p>Loading compiler and replay evidence…</p>
        </section>
      ) : (
        <>
          <section className="evaluation-card" data-testid="mesoscope-portability-report">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Shared compiler receipt</p>
                <h2>{report.compilation.compilation_version}</h2>
              </div>
              <span className="evaluation-status is-completed">Conformant</span>
            </div>
            <p>{report.fixture_notice}</p>
            <dl className="evaluation-replay-checks">
              <div><dt>Environment</dt><dd>{report.environment_id}</dd></div>
              <div><dt>Generated artifacts</dt><dd>{report.compilation.artifacts.length}</dd></div>
            </dl>
          </section>
          <section className="evaluation-card" data-testid="mesoscope-portability-results">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Seeded protocol fixtures</p>
                <h2>Verified and quarantine handoffs</h2>
              </div>
              <span className="evaluation-count">{report.results.length}</span>
            </div>
            <div className="evaluation-response-list">
              {report.results.map((result) => (
                <article key={result.replay_id}>
                  <div>
                    <strong>{result.terminal_summary}</strong>
                    <code>{result.runtime_trace_digest}</code>
                  </div>
                  <span>Offline fixture · {result.terminal_disposition}</span>
                  <button
                    className="secondary-button"
                    data-testid={`portability-replay-${result.replay_id}`}
                    disabled={busy}
                    onClick={() => void openReplay(result.replay_id)}
                    type="button"
                  >
                    Open canonical replay
                  </button>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
      {replay && (
        <section className="evaluation-card" data-testid="mesoscope-portability-replay">
          <p className="eyebrow">Deterministic canonical replay</p>
          <h2>
            {replay.trace_matches && replay.result_matches
              ? "Trace and result match"
              : "Replay mismatch"}
          </h2>
          <p>{replay.snapshot.verifier_result?.summary}</p>
        </section>
      )}
      <p className="evaluation-boundary-note">
        This separate track demonstrates platform portability only. It does not imply
        mesoscope training or cross-Apparatus generalization.
      </p>
    </section>
  );
}

function HostedReferenceReadiness() {
  const [readiness, setReadiness] = useState<ProviderReadinessSummary | null>(null);

  useEffect(() => {
    let active = true;
    providerApi.readiness()
      .then((loaded) => {
        if (active) setReadiness(loaded);
      })
      .catch(() => {
        if (active) setReadiness(null);
      });
    return () => { active = false; };
  }, []);

  const providers = [
    {
      key: "openai",
      name: "OpenAI Responses",
      model: readiness?.openai.requested_model ?? "gpt-5.6-sol",
      route: "Responses · stateless · storage disabled",
      configured: readiness?.openai.credential_configured ?? false,
      variable: "OPENAI_API_KEY",
    },
    {
      key: "gemini",
      name: "Gemini Interactions",
      model: readiness?.gemini.requested_model ?? "gemini-3.7-flash",
      route: "Interactions · signed-step replay · storage disabled",
      configured: readiness?.gemini.credential_configured ?? false,
      variable: "GEMINI_API_KEY",
    },
  ] as const;
  return (
    <section className="evaluation-card" data-testid="hosted-reference-readiness">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Hosted reference readiness</p>
          <h2>Provider-native routes</h2>
        </div>
        <span className="evaluation-count">{providers.length}</span>
      </div>
      <p>
        GPT and Gemini are separately labeled hosted references under the same canonical
        tools, budgets, Runtime transitions, and deterministic Verifier.
      </p>
      <div className="evaluation-response-list">
        {providers.map((provider) => (
          <article data-testid={`provider-readiness-${provider.key}`} key={provider.key}>
            <div>
              <strong>{provider.name}</strong>
              <span className={`evaluation-status ${provider.configured
                ? "is-completed"
                : "is-interrupted"}`}>
                {provider.configured ? "Configured" : "Missing credential"}
              </span>
            </div>
            <span>{provider.model}</span>
            <span>{provider.route}</span>
            {!provider.configured && (
              <small>
                Set {provider.variable} only in the launch environment. No secret value
                is read into this view.
              </small>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function EegEvaluationWorkspace() {
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([]);
  const [selected, setSelected] = useState<EvaluationSnapshot | null>(null);
  const [replay, setReplay] = useState<EvaluationReplay | null>(null);
  const [busy, setBusy] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [resumeRequested, setResumeRequested] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    evaluationApi.list()
      .then((loaded) => {
        if (!cancelled) {
          setEvaluations(loaded);
          setSessionReady(true);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(safeMessage(reason, "Unable to list local evaluations."));
        }
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const evaluationId = selected?.evaluation_id;
    const status = selected?.status;
    const waitingForResume = evaluationId === resumeRequested;
    if (
      !evaluationId
      || !status
      || (!waitingForResume && !["queued", "running"].includes(status))
    ) {
      return;
    }
    let active = true;
    let timer: number | null = null;
    let consecutiveFailures = 0;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      try {
        const loaded = await evaluationApi.load(evaluationId);
        if (!active) return;
        consecutiveFailures = 0;
        setPollError(null);
        setResumeRequested((current) => (
          current === evaluationId && loaded.status !== "interrupted" ? null : current
        ));
        setSelected((current) => (
          current?.evaluation_id === evaluationId ? loaded : current
        ));
        setEvaluations((current) => mergeSummary(current, loaded));
        if (
          loaded.status === "interrupted"
          || ["queued", "running"].includes(loaded.status)
        ) {
          schedule(POLL_INTERVAL_MS);
        }
      } catch (reason) {
        if (!active) return;
        consecutiveFailures += 1;
        setPollError(
          safeMessage(reason, "Unable to refresh evaluation progress."),
        );
        schedule(pollRetryDelay(consecutiveFailures));
      }
    };

    setPollError(null);
    schedule(POLL_INTERVAL_MS);
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [resumeRequested, selected?.evaluation_id, selected?.status]);

  async function launch() {
    if (!sessionReady) return;
    setBusy(true);
    setError(null);
    setPollError(null);
    setReplay(null);
    try {
      const launched = await evaluationApi.launch();
      setSelected(launched);
      setEvaluations((current) => mergeSummary(current, launched));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to launch the local evaluation."));
    } finally {
      setBusy(false);
    }
  }

  async function load(evaluationId: string) {
    setBusy(true);
    setError(null);
    setPollError(null);
    setReplay(null);
    try {
      const loaded = await evaluationApi.load(evaluationId);
      setSelected(loaded);
      setEvaluations((current) => mergeSummary(current, loaded));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to load the local evaluation."));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!selected || selected.status !== "interrupted") return;
    const evaluationId = selected.evaluation_id;
    setBusy(true);
    setError(null);
    setPollError(null);
    setReplay(null);
    try {
      const resumed = await evaluationApi.resume(evaluationId);
      setResumeRequested(evaluationId);
      setSelected((current) => (
        current?.evaluation_id === evaluationId ? resumed : current
      ));
      setEvaluations((current) => mergeSummary(current, resumed));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to resume the local evaluation."));
    } finally {
      setBusy(false);
    }
  }

  async function openReplay(attemptId: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setReplay(await evaluationApi.replay(selected.evaluation_id, attemptId));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to replay the evaluation attempt."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="evaluation-heading"
      className="workspace-mode-panel evaluation-workspace"
      data-testid="evaluation-workspace"
      id="evaluation-workspace"
      role="tabpanel"
    >
      <div className="workspace-heading evaluation-heading">
        <div>
          <p className="breadcrumb">EEG Environment / Fixed development split</p>
          <h1 id="evaluation-heading">Base Gemma development calibration</h1>
          <p>
            Run the approved local model through all 32 development scenarios with
            immutable tools, budgets, scoring, and canonical Runtime traces.
          </p>
        </div>
        <span className="scenario-tag">Read-only evaluation</span>
      </div>

      <div className="evaluation-launch-row">
        <div>
          <strong>Fixed profile</strong>
          <span>google/gemma-4-E4B-it · deterministic development matrix</span>
        </div>
        <button
          className="primary-button evaluation-launch-button"
          data-testid="launch-evaluation"
          disabled={busy || !sessionReady}
          onClick={() => void launch()}
          type="button"
        >
          {busy
            ? "Working…"
            : sessionReady
              ? "Launch evaluation"
              : "Establishing local session…"}
        </button>
      </div>

      {(error ?? pollError) && (
        <div className="error-banner" role="alert">
          <strong>Evaluation request failed.</strong> {error ?? pollError}
        </div>
      )}

      <HostedReferenceReadiness />

      <div className="evaluation-grid">
        <EvaluationList
          evaluations={evaluations}
          busy={busy || !sessionReady}
          onLoad={(id) => void load(id)}
        />
        {selected ? (
          <ProgressPanel
            snapshot={selected}
            busy={busy}
            onResume={() => void resume()}
          />
        ) : (
          <section className="evaluation-card evaluation-selection-empty">
            <p className="eyebrow">No evaluation selected</p>
            <h2>Launch or load a durable run</h2>
            <p>Progress, outcome separation, and replay links will appear here.</p>
          </section>
        )}
      </div>
      {replay && <ReplayPanel replay={replay} />}
      {selected && <CalibrationPanel snapshot={selected} />}
      {selected && (
        <AttemptTable
          snapshot={selected}
          busy={busy}
          onReplay={(attemptId) => void openReplay(attemptId)}
        />
      )}
      <p className="evaluation-boundary-note">
        Evaluation is read-only in the Scientist Console. The Policy agent receives only
        declared simulated-Apparatus actions; endpoint and credential material never
        enter this view or its canonical records.
      </p>
    </section>
  );
}

export function EvaluationWorkspace({
  environmentKind = "eeg",
}: {
  environmentKind?: "eeg" | "mesoscope";
}) {
  return environmentKind === "mesoscope"
    ? <MesoscopePortabilityWorkspace />
    : <EegEvaluationWorkspace />;
}

export function EvaluationBoundaryPanel({
  environmentKind = "eeg",
}: {
  environmentKind?: "eeg" | "mesoscope";
}) {
  if (environmentKind === "mesoscope") {
    return (
      <section className="identity-panel evaluation-boundary-panel">
        <p className="eyebrow">Platform evidence boundary</p>
        <h2>Separate from EEG training</h2>
        <dl className="identity-list">
          <div><dt>Apparatus</dt><dd>Sealed synthetic mesoscope</dd></div>
          <div><dt>Track</dt><dd>Platform generality</dd></div>
          <div><dt>Evidence</dt><dd>Seeded offline fixtures</dd></div>
          <div><dt>Controls</dt><dd>No operational actions</dd></div>
        </dl>
      </section>
    );
  }
  return (
    <section className="identity-panel evaluation-boundary-panel">
      <p className="eyebrow">Evaluation boundary</p>
      <h2>Fixed and private</h2>
      <dl className="identity-list">
        <div><dt>Role</dt><dd>Policy agent</dd></div>
        <div><dt>Split</dt><dd>32 development scenarios</dd></div>
        <div><dt>Model</dt><dd>Base Gemma E4B</dd></div>
        <div><dt>Mode</dt><dd>Local inference</dd></div>
      </dl>
      <p className="identity-note">
        Scientific failures remain evidence. Adapter and inference errors are counted
        separately and never converted into scores.
      </p>
    </section>
  );
}
