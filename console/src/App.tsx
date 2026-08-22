import { useEffect, useState } from "react";
import { environmentApi } from "./api";
import {
  EnvironmentVisualization,
  environmentTraceEvidence,
} from "./environments";
import type {
  EnvironmentSummary,
  ReplayReport,
  RunSnapshot,
  TraceEvent,
} from "./types";

function digestTail(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function ValidationPanel({ environment }: { environment: EnvironmentSummary }) {
  return (
    <section
      className="validation-panel"
      aria-labelledby="validation-title"
      data-testid="environment-validation"
    >
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Environment validation</p>
          <h2 id="validation-title">Bundle readiness</h2>
        </div>
        <span className="status-dot is-ready">Ready</span>
      </div>
      <p className="validation-summary">{environment.validation.summary}</p>
      <details className="validation-details">
        <summary>Validation details</summary>
        <ul className="quiet-list">
          {environment.validation.checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function actionPresentation(environment: EnvironmentSummary, type: string) {
  return environment.actions.find((action) => action.type === type);
}

function ActionPanel({
  environment,
  run,
  busy,
  onAction,
  onVerify,
  onReset,
  onReplay,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
  busy: boolean;
  onAction: (type: string) => void;
  onVerify: () => void;
  onReset: () => void;
  onReplay: () => void;
}) {
  return (
    <section className="action-panel" aria-labelledby="actions-title">
      <p className="eyebrow">Permitted actions</p>
      <h2 id="actions-title">Available actions</h2>
      {!run ? (
        <p className="panel-copy">Start the frozen run to inspect this Environment.</p>
      ) : (
        <>
          <div className="action-grid">
            {run.permitted_actions.map((actionType) => (
              <button
                className="action-button"
                data-testid={`action-${actionType}`}
                disabled={busy}
                key={actionType}
                onClick={() => onAction(actionType)}
                title={actionPresentation(environment, actionType)?.description}
                type="button"
              >
                {actionPresentation(environment, actionType)?.title ?? actionType}
              </button>
            ))}
          </div>
          <div className="run-control-row">
            {run.status !== "completed" && (
              <button
                className="primary-button compact-button"
                data-testid="verify-run"
                disabled={busy}
                onClick={onVerify}
                type="button"
              >
                Verify current evidence
              </button>
            )}
            {run.status === "completed" && (
              <button
                className="secondary-button"
                data-testid="replay-run"
                disabled={busy}
                onClick={onReplay}
                type="button"
              >
                Replay trace
              </button>
            )}
            <button
              className="secondary-button"
              data-testid="reset-run"
              disabled={busy}
              onClick={onReset}
              type="button"
            >
              Reset scenario
            </button>
          </div>
        </>
      )}
      <p className="boundary-note">
        Synthetic apparatus actions only. No physical or operational controls.
      </p>
    </section>
  );
}

function traceKind(event: TraceEvent): string {
  return event.type === "verifier" ? "Verification" : event.type;
}

function TraceRow({
  environment,
  event,
}: {
  environment: EnvironmentSummary;
  event: TraceEvent;
}) {
  const evidence = environmentTraceEvidence(environment, event);
  return (
    <li data-event-type={event.type}>
      <span>{event.sequence}</span>
      <p>
        <strong>{traceKind(event)}</strong>
        {event.summary}
        {evidence && <small className="trace-evidence">{evidence}</small>}
      </p>
    </li>
  );
}

function TracePanel({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
}) {
  return (
    <section className="trace-panel" aria-labelledby="trace-title">
      <p className="eyebrow">Canonical trace</p>
      <h2 id="trace-title">Ordered run evidence</h2>
      {!run ? (
        <p className="panel-copy">Observations, actions, transitions, and verification appear here.</p>
      ) : (
        <ol className="trace-list" data-testid="trace-list">
          {run.trace.map((event) => (
            <TraceRow environment={environment} event={event} key={event.sequence} />
          ))}
        </ol>
      )}
    </section>
  );
}

function ResultPanel({
  run,
  replay,
}: {
  run: RunSnapshot;
  replay: ReplayReport | null;
}) {
  if (!run.verifier_result && !replay) return null;
  return (
    <section className="result-panel" aria-live="polite" aria-label="Run result">
      {run.verifier_result && (
        <div data-testid="verifier-result">
          <p className="eyebrow">Verifier result</p>
          <h2>{run.verifier_result.passed ? "Verifier passed" : "Verifier did not pass"}</h2>
          <p>{run.verifier_result.summary}</p>
        </div>
      )}
      {replay && (
        <p data-testid="replay-result">
          {replay.trace_matches && replay.result_matches
            ? "Trace and result digests match the source run."
            : "Replay diverged from the source run."}
        </p>
      )}
    </section>
  );
}

function RunIdentity({ run }: { run: RunSnapshot }) {
  const statusLabels: Record<RunSnapshot["status"], string> = {
    active: "Active run",
    awaiting_verification: "Awaiting verification",
    completed: "Completed run",
  };
  return (
    <section className="identity-panel" aria-label="Frozen run identity">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Run state</p>
          <h2 data-testid="run-status">{statusLabels[run.status]}</h2>
        </div>
        <span className="frozen-badge">Frozen</span>
      </div>
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
          <dt>Active Policy agent</dt>
          <dd data-testid="policy-agent-identity">{run.policy_agent.name}</dd>
        </div>
      </dl>
      <p className="identity-note">
        This immutable revision remains fixed across reset and deterministic replay.
      </p>
    </section>
  );
}

function EmptyRunPanel({
  environment,
  selectedAgent,
  setSelectedAgent,
  onStart,
  busy,
}: {
  environment: EnvironmentSummary;
  selectedAgent: string;
  setSelectedAgent: (agent: string) => void;
  onStart: () => void;
  busy: boolean;
}) {
  return (
    <section className="start-panel" aria-labelledby="start-title">
      <p className="eyebrow">Run setup</p>
      <h2 id="start-title">Freeze this seeded Environment</h2>
      <p>Starting records an immutable revision and the active Policy agent.</p>
      <label htmlFor="policy-agent">Policy agent</label>
      <select
        id="policy-agent"
        value={selectedAgent}
        onChange={(event) => setSelectedAgent(event.target.value)}
      >
        {environment.policy_agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      <button
        className="primary-button"
        type="button"
        data-testid="start-run"
        onClick={onStart}
        disabled={busy || !selectedAgent}
      >
        {busy ? "Freezing revision…" : "Start frozen run"}
      </button>
      <p className="boundary-note">{environment.simulation_label}. No hardware connection.</p>
    </section>
  );
}

export function App() {
  const [environment, setEnvironment] = useState<EnvironmentSummary | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    environmentApi
      .getEnvironment()
      .then((loaded) => {
        if (cancelled) return;
        setEnvironment(loaded);
        setSelectedAgent(loaded.policy_agents[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason, "Unable to load Environment"));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function perform(operation: () => Promise<RunSnapshot>) {
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      setRun(await operation());
    } catch (reason) {
      setError(errorMessage(reason, "The Runtime operation failed"));
    } finally {
      setBusy(false);
    }
  }

  function startRun() {
    if (!environment || !selectedAgent) return;
    void perform(() => environmentApi.start(environment.scenario_id, selectedAgent));
  }

  function applyAction(type: string) {
    if (!run) return;
    void perform(() => environmentApi.apply(run.run_id, type));
  }

  function verifyRun() {
    if (!run) return;
    void perform(() => environmentApi.verify(run.run_id));
  }

  function resetRun() {
    if (!run) return;
    void perform(() => environmentApi.reset(run.run_id));
  }

  async function replayRun() {
    if (!run) return;
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      const response = await environmentApi.replay(run.run_id);
      setRun(response.snapshot);
      setReplay(response.replay);
    } catch (reason) {
      setError(errorMessage(reason, "Unable to replay the trace"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark" aria-label="Science Environment Studio">
          <span className="brand-symbol" aria-hidden="true">S</span>
          <span>Science Environment Studio</span>
        </div>
        <div className="topbar-context">
          <span className="mode-badge">Scientist Console</span>
          <span className="topbar-divider" />
          <span>{run ? "Run" : "Review"}</span>
        </div>
      </header>

      <aside className="environment-nav" aria-label="Environment navigation">
        <div className="nav-heading"><p className="eyebrow">Environments</p></div>
        <button className="environment-row is-active" type="button">
          <span className="environment-icon" aria-hidden="true">EEG</span>
          <span><strong>EEG</strong><small>Marker recovery</small></span>
        </button>
        <div className="nav-rule" />
        <p className="nav-caption">Available in later slices</p>
        <div className="environment-row is-disabled" aria-disabled="true">
          <span className="environment-icon muted" aria-hidden="true">4R</span>
          <span><strong>Mesoscope</strong><small>Sealed synthetic handoff</small></span>
        </div>
        <footer className="nav-footer">
          <span className="simulation-indicator" aria-hidden="true" />Synthetic environments
        </footer>
      </aside>

      <main className="workspace">
        <div className="workspace-heading">
          <div>
            <p className="breadcrumb">Environment / Seeded scenario</p>
            <h1>{environment?.name ?? "Loading Environment…"}</h1>
            <p>{environment?.description ?? "Loading Environment details…"}</p>
          </div>
          <span className="scenario-tag">Seeded scenario</span>
        </div>

        {error && <div className="error-banner" role="alert"><strong>Console request failed.</strong> {error}</div>}
        {environment && <EnvironmentVisualization environment={environment} run={run} />}
        {run && <ResultPanel run={run} replay={replay} />}
        <section className="lower-workspace" aria-label="Run actions and canonical trace">
          {environment && (
            <>
              <ActionPanel environment={environment} run={run} busy={busy} onAction={applyAction} onVerify={verifyRun} onReset={resetRun} onReplay={() => void replayRun()} />
              <TracePanel environment={environment} run={run} />
            </>
          )}
        </section>
      </main>

      <aside className="details-rail" aria-label="Environment and run details">
        {environment ? (
          <>
            <ValidationPanel environment={environment} />
            {run ? <RunIdentity run={run} /> : <EmptyRunPanel environment={environment} selectedAgent={selectedAgent} setSelectedAgent={setSelectedAgent} onStart={startRun} busy={busy} />}
          </>
        ) : <div className="loading-panel" aria-live="polite">Loading validation…</div>}
      </aside>
    </div>
  );
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
