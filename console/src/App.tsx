import { useEffect, useState } from "react";
import { draftApi, environmentApi } from "./api";
import {
  DraftWorkspace,
  FrozenConfigurationPanel,
} from "./authoring/DraftWorkspace";
import {
  EnvironmentVisualization,
  environmentTraceEvidence,
} from "./environments";
import type {
  DraftCommandResult,
  EnvironmentDraft,
  EnvironmentSummary,
  FrozenEnvironment,
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

function DraftIdentity({ draft }: { draft: EnvironmentDraft }) {
  return (
    <section
      className="identity-panel draft-identity-panel"
      aria-label="Reversible draft identity"
    >
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Edit state</p>
          <h2>Reversible Environment draft</h2>
        </div>
        <span className="draft-badge">Editable</span>
      </div>
      <dl className="identity-list">
        <div>
          <dt>Draft revision</dt>
          <dd data-testid="draft-identity-revision" title={draft.revision_digest}>
            r{draft.revision} · {digestTail(draft.revision_digest)}
          </dd>
        </div>
        <div>
          <dt>Whole-cap inputs</dt>
          <dd>{draft.apparatus.recording_input_capacity}</dd>
        </div>
        <div>
          <dt>Authoring assistant</dt>
          <dd>{draft.authoring_assistant.name}</dd>
        </div>
      </dl>
      <p className="identity-note">
        Draft history is isolated from every frozen Policy-agent run.
      </p>
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
      <h2 id="start-title">Freeze the current draft and start</h2>
      <p>
        Launching records an immutable bundle revision, scenario identity, and active
        Policy agent before any scored action.
      </p>
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
        {busy ? "Freezing and starting…" : "Freeze draft and start run"}
      </button>
      <p className="boundary-note">{environment.simulation_label}. No hardware connection.</p>
    </section>
  );
}

export function App() {
  const [mode, setMode] = useState<"edit" | "run">("edit");
  const [environment, setEnvironment] = useState<EnvironmentSummary | null>(null);
  const [draft, setDraft] = useState<EnvironmentDraft | null>(null);
  const [draftResult, setDraftResult] = useState<DraftCommandResult | null>(null);
  const [frozen, setFrozen] = useState<FrozenEnvironment | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([environmentApi.getEnvironment(), draftApi.get()])
      .then(([loadedEnvironment, loadedDraft]) => {
        if (cancelled) return;
        setEnvironment(loadedEnvironment);
        setDraft(loadedDraft);
        setSelectedAgent(loadedEnvironment.policy_agents[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(errorMessage(reason, "Unable to load the Environment draft"));
        }
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

  async function performDraft(operation: () => Promise<EnvironmentDraft>) {
    setDraftBusy(true);
    setError(null);
    setDraftResult(null);
    try {
      setDraft(await operation());
    } catch (reason) {
      setError(errorMessage(reason, "The draft operation failed"));
    } finally {
      setDraftBusy(false);
    }
  }

  async function applyDraftCommand(command: string) {
    if (!draft) return;
    setDraftBusy(true);
    setError(null);
    try {
      const response = await draftApi.command(command, draft.revision);
      setDraft(response.draft);
      setDraftResult(response.result);
    } catch (reason) {
      setError(errorMessage(reason, "The Authoring assistant could not revise the draft"));
    } finally {
      setDraftBusy(false);
    }
  }

  function undoDraft() {
    if (!draft) return;
    void performDraft(() => draftApi.undo(draft.revision));
  }

  function redoDraft() {
    if (!draft) return;
    void performDraft(() => draftApi.redo(draft.revision));
  }

  function restoreDraft() {
    if (!draft) return;
    void performDraft(() => draftApi.restore(draft.revision));
  }

  function stageNote(filename: string, content: string) {
    if (!draft) return;
    void performDraft(() => draftApi.stageNote(filename, content, draft.revision));
  }

  async function startRun() {
    if (!draft || !selectedAgent) return;
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      const frozenEnvironment = await draftApi.freeze(draft.revision);
      const started = await environmentApi.start(
        frozenEnvironment.scenario_id,
        selectedAgent,
        frozenEnvironment.frozen_environment_id,
      );
      if (
        started.revision_digest !== frozenEnvironment.revision_digest ||
        started.scenario_id !== frozenEnvironment.scenario_id
      ) {
        throw new Error(
          "The started run did not match the frozen Environment identity.",
        );
      }
      setFrozen(frozenEnvironment);
      setRun(started);
    } catch (reason) {
      setError(errorMessage(reason, "Unable to freeze and start the run"));
    } finally {
      setBusy(false);
    }
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
          <span>{mode === "edit" ? "Edit" : "Run"}</span>
        </div>
      </header>

      <aside className="environment-nav" aria-label="Environment navigation">
        <div className="nav-heading"><p className="eyebrow">Environments</p></div>
        <button className="environment-row is-active" type="button">
          <span className="environment-icon" aria-hidden="true">EEG</span>
          <span><strong>EEG</strong><small>Authoring and marker recovery</small></span>
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
        <div className="workspace-mode-tabs" role="tablist" aria-label="Environment workspace">
          <button
            aria-controls="edit-workspace"
            aria-selected={mode === "edit"}
            className={mode === "edit" ? "is-active" : ""}
            data-testid="mode-edit"
            onClick={() => setMode("edit")}
            role="tab"
            type="button"
          >
            Edit
          </button>
          <button
            aria-controls="run-workspace"
            aria-selected={mode === "run"}
            className={mode === "run" ? "is-active" : ""}
            data-testid="mode-run"
            onClick={() => setMode("run")}
            role="tab"
            type="button"
          >
            Run
          </button>
        </div>

        {error && <div className="error-banner" role="alert"><strong>Console request failed.</strong> {error}</div>}

        {mode === "edit" ? (
          <section
            aria-labelledby="edit-heading"
            className="workspace-mode-panel"
            data-testid="edit-workspace"
            id="edit-workspace"
            role="tabpanel"
          >
            <div className="workspace-heading">
              <div>
                <p className="breadcrumb">EEG Environment / Reversible draft</p>
                <h1 id="edit-heading">{draft?.title ?? "Loading EEG draft…"}</h1>
                <p>Configure the whole-cap Apparatus and this Procedure's selected Montage.</p>
              </div>
              <span className="scenario-tag">Editable draft</span>
            </div>
            {draft ? (
              <DraftWorkspace
                busy={draftBusy}
                draft={draft}
                onCommand={(command) => void applyDraftCommand(command)}
                onRedo={redoDraft}
                onRestore={restoreDraft}
                onStageNote={stageNote}
                onUndo={undoDraft}
                result={draftResult}
              />
            ) : (
              <div className="loading-panel">Loading reversible authoring state…</div>
            )}
          </section>
        ) : (
          <section
            aria-labelledby="run-heading"
            className="workspace-mode-panel"
            data-testid="run-workspace"
            id="run-workspace"
            role="tabpanel"
          >
            <div className="workspace-heading">
              <div>
                <p className="breadcrumb">Frozen Environment / Seeded scenario</p>
                <h1 id="run-heading">{environment?.name ?? "Loading Environment…"}</h1>
                <p>{environment?.description ?? "Loading Environment details…"}</p>
              </div>
              <span className="scenario-tag">Frozen run</span>
            </div>
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
          </section>
        )}
      </main>

      <aside className="details-rail" aria-label="Environment and run details">
        {mode === "edit" ? (
          draft ? <DraftIdentity draft={draft} /> : <div className="loading-panel">Loading draft identity…</div>
        ) : environment ? (
          <>
            <ValidationPanel environment={environment} />
            {run ? <RunIdentity run={run} /> : <EmptyRunPanel environment={environment} selectedAgent={selectedAgent} setSelectedAgent={setSelectedAgent} onStart={() => void startRun()} busy={busy} />}
            {frozen && <FrozenConfigurationPanel frozen={frozen} />}
          </>
        ) : <div className="loading-panel" aria-live="polite">Loading validation…</div>}
      </aside>
    </div>
  );
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
