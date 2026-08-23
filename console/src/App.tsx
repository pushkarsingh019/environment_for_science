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
import { RunActionComposer } from "./environments/RunActionComposer";
import {
  EvaluationBoundaryPanel,
  EvaluationWorkspace,
} from "./evaluation/EvaluationWorkspace";
import type {
  DraftCommandResult,
  EnvironmentCatalogEntry,
  EnvironmentDraft,
  EnvironmentSummary,
  FrozenEnvironment,
  JsonObject,
  ReplayReport,
  RunSnapshot,
  SealedEnvironment,
  TraceEvent,
} from "./types";

function digestTail(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function displayName(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const EEG_EVIDENCE_DOMAINS = [
  ["configuration", "Configuration"],
  ["eeg", "EEG"],
  ["onset", "Onset"],
  ["response", "Response"],
  ["recording", "Recording"],
] as const;

const MESOSCOPE_EVIDENCE_DOMAINS = [
  ["safety", "Safety"],
  ["plan", "Plan"],
  ["acquisition", "Acquisition"],
  ["package", "Package"],
] as const;

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
  onAction: (type: string, arguments_: JsonObject) => void;
  onVerify: () => void;
  onReset: () => void;
  onReplay: () => void;
}) {
  const evidenceFreshness = run?.observation.evidence_freshness;
  const currentEvidenceIds = evidenceFreshness !== null
    && typeof evidenceFreshness === "object"
    && !Array.isArray(evidenceFreshness)
    ? Object.values(evidenceFreshness).flatMap((entry) => {
        if (entry === null || typeof entry !== "object" || Array.isArray(entry)) return [];
        return entry.status === "current" && typeof entry.evidence_id === "string"
          ? [entry.evidence_id]
          : [];
      })
    : [];
  return (
    <section className="action-panel" aria-labelledby="actions-title">
      <p className="eyebrow">Permitted actions</p>
      <h2 id="actions-title">Available actions</h2>
      {!run ? (
        <p className="panel-copy">Start the frozen run to inspect this Environment.</p>
      ) : (
        <>
          <RunActionComposer
            actions={environment.actions}
            busy={busy || run.status === "completed"}
            key={run.run_id}
            onAction={onAction}
            permittedActions={run.permitted_actions}
            resultSummary={String(run.observation.summary ?? "Current observation loaded.")}
            suggestedValues={{ evidence_id: currentEvidenceIds }}
          />
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
        {environment.environment_kind === "mesoscope"
          ? "Sealed synthetic actions only · disconnected from hardware · no physical or operational controls."
          : "Synthetic apparatus actions only. No physical or operational controls."}
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
      {environment.environment_kind === "mesoscope" && (
        <p className="mesoscope-trace-boundary" data-testid="mesoscope-trace-boundary">
          SEALED SYNTHETIC TRACE · DISCONNECTED FROM HARDWARE
        </p>
      )}
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
  const result = run.verifier_result;
  return (
    <section className="result-panel" aria-live="polite" aria-label="Run result">
      {result && (
        <div data-testid="verifier-result">
          <p className="eyebrow">Verifier result</p>
          <h2>{result.passed ? "Verifier passed" : "Verifier did not pass"}</h2>
          <p className="result-classification">
            Terminal disposition: {" "}
            <strong data-testid="terminal-disposition">
              {displayName(result.terminal_disposition)}
            </strong>
          </p>
          {result.outcome_category && (
            <p className="result-classification">
              Outcome category: {" "}
              <strong data-testid="outcome-category">
                {displayName(result.outcome_category)}
              </strong>
            </p>
          )}
          <p>{result.summary}</p>
          <details data-testid="verifier-explanation">
            <summary>Why the verifier reached this result</summary>
            {result.reasons.length > 0 ? (
              <ul className="quiet-list">
                {result.reasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            ) : <p>No blocking reason was recorded.</p>}
            <dl className="verifier-metrics">
              {Object.entries(result.metrics).map(([name, value]) => (
                <div key={name}>
                  <dt>{name.replaceAll("_", " ")}</dt>
                  <dd>{value.toFixed(2)}</dd>
                </div>
              ))}
            </dl>
          </details>
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

function RunIdentity({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot;
}) {
  const statusLabels: Record<RunSnapshot["status"], string> = {
    active: "Active run",
    awaiting_verification: "Awaiting verification",
    completed: "Completed run",
  };
  const freshness = run.observation.evidence_freshness;
  const freshnessRecord =
    freshness !== null && typeof freshness === "object" && !Array.isArray(freshness)
      ? freshness
      : {};
  const stage = typeof run.observation.stage === "string"
    ? displayName(run.observation.stage)
    : "Unavailable";
  const evidenceDomains = environment.environment_kind === "mesoscope"
    ? MESOSCOPE_EVIDENCE_DOMAINS
    : EEG_EVIDENCE_DOMAINS;
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
          <dt>{environment.environment_kind === "mesoscope" ? "Handoff stage" : "Curriculum stage"}</dt>
          <dd data-testid="curriculum-stage">{stage}</dd>
        </div>
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
      <p className="eyebrow">Evidence freshness</p>
      <dl className="identity-list" data-testid="domain-freshness">
        {evidenceDomains.map(([domain, label]) => {
          const entry = freshnessRecord[domain];
          const status =
            entry !== null && typeof entry === "object" && !Array.isArray(entry)
              && typeof entry.status === "string"
              ? displayName(entry.status)
              : "Unavailable";
          return (
            <div key={domain}>
              <dt>{label}</dt>
              <dd data-testid={`domain-freshness-${domain}`}>{status}</dd>
            </div>
          );
        })}
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
  selectedScenario,
  setSelectedScenario,
  onStart,
  busy,
}: {
  environment: EnvironmentSummary;
  selectedAgent: string;
  setSelectedAgent: (agent: string) => void;
  selectedScenario: string;
  setSelectedScenario: (scenario: string) => void;
  onStart: () => void;
  busy: boolean;
}) {
  const selectedExample = environment.seeded_examples.find(
    (example) => example.scenario_id === selectedScenario,
  );
  return (
    <section className="start-panel" aria-labelledby="start-title">
      <p className="eyebrow">Run setup</p>
      <h2 id="start-title">
        {environment.source_kind === "sealed_seed"
          ? "Freeze the sealed seed and start"
          : "Freeze the current draft and start"}
      </h2>
      <p>
        Launching records an immutable bundle revision, scenario identity, and active
        Policy agent before any scored action.
      </p>
      <label htmlFor="seeded-example">
        {environment.source_kind === "sealed_seed"
          ? "Sealed package example"
          : "Seeded curriculum example"}
      </label>
      <select
        data-testid="seeded-example-selector"
        id="seeded-example"
        value={selectedScenario}
        onChange={(event) => setSelectedScenario(event.target.value)}
      >
        {environment.seeded_examples.map((example) => (
          <option key={example.scenario_id} value={example.scenario_id}>
            {example.label}
          </option>
        ))}
      </select>
      {selectedExample && (
        <p className="boundary-note">
          Entry scope: {" "}
          <span data-testid="seeded-example-stage">
            {displayName(selectedExample.stage)}
          </span>
        </p>
      )}
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
        disabled={busy || !selectedAgent || !selectedScenario}
      >
        {busy
          ? "Freezing and starting…"
          : environment.source_kind === "sealed_seed"
            ? "Freeze sealed Environment and start run"
            : "Freeze draft and start run"}
      </button>
      <p className="boundary-note">{environment.simulation_label}. No hardware connection.</p>
    </section>
  );
}

function SealedEnvironmentWorkspace({
  environment,
}: {
  environment: EnvironmentSummary;
}) {
  const visualization = environment.visualization.kind === "mesoscope_handoff_v1"
    ? environment.visualization
    : null;
  return (
    <section
      aria-labelledby="edit-heading"
      className="sealed-environment-workspace"
      data-testid="sealed-environment-workspace"
      id="edit-workspace"
      role="tabpanel"
    >
      <div className="workspace-heading">
        <div>
          <p className="breadcrumb">Mesoscope Environment / Sealed seed</p>
          <h1 id="edit-heading">{environment.name}</h1>
          <p>
            Profiles, signed plans, and the independent safety gate are immutable.
          </p>
        </div>
        <span className="scenario-tag">Read-only</span>
      </div>
      <div className="sealed-boundary-banner" role="note">
        <strong>{visualization?.sealed_label ?? "SEALED"}</strong>
        <span>{environment.simulation_label}</span>
      </div>
      <div className="sealed-overview-grid">
        <article>
          <p className="eyebrow">Profiles</p>
          <h2>Source conventions remain separate</h2>
          <p>
            Research-paper and commercial reference profiles are visible and locked;
            their source conventions remain distinct.
          </p>
        </article>
        <article>
          <p className="eyebrow">Signed plan</p>
          <h2>R1–R4 · Z-A / Z-B</h2>
          <p>The selected four-region handoff cannot be redrawn or converted to apparatus control.</p>
        </article>
        <article>
          <p className="eyebrow">Safety gate</p>
          <h2>Independent and immutable</h2>
          <p>No reset, bypass, alignment, calibration, or physical connector is available.</p>
        </article>
      </div>
      <p className="sealed-workspace-note">
        Switch to Run to inspect the cached procedural phantom and verify a synthetic package.
      </p>
    </section>
  );
}

function SealedFrozenPanel({ frozen }: { frozen: SealedEnvironment }) {
  return (
    <section className="identity-panel" data-testid="sealed-frozen-identity">
      <p className="eyebrow">Sealed revision</p>
      <h2>Immutable handoff identity</h2>
      <dl className="identity-list">
        <div><dt>Profile</dt><dd>{frozen.sealed_profile_id}</dd></div>
        <div><dt>Signed plan</dt><dd>{frozen.signed_plan_id}</dd></div>
        <div>
          <dt>Revision</dt>
          <dd title={frozen.revision_digest}>{digestTail(frozen.revision_digest)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function App() {
  const [mode, setMode] = useState<"edit" | "run" | "evaluate">("edit");
  const [catalog, setCatalog] = useState<EnvironmentCatalogEntry[]>([]);
  const [environment, setEnvironment] = useState<EnvironmentSummary | null>(null);
  const [draft, setDraft] = useState<EnvironmentDraft | null>(null);
  const [draftResult, setDraftResult] = useState<DraftCommandResult | null>(null);
  const [frozen, setFrozen] = useState<FrozenEnvironment | null>(null);
  const [sealedFrozen, setSealedFrozen] = useState<SealedEnvironment | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedScenario, setSelectedScenario] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      environmentApi.getCatalog(),
      environmentApi.getEnvironment(),
      draftApi.get(),
    ])
      .then(([loadedCatalog, loadedEnvironment, loadedDraft]) => {
        if (cancelled) return;
        setCatalog(loadedCatalog);
        setEnvironment(loadedEnvironment);
        setDraft(loadedDraft);
        setSelectedAgent(loadedEnvironment.policy_agents[0]?.id ?? "");
        setSelectedScenario(
          loadedEnvironment.seeded_examples[0]?.scenario_id ?? "",
        );
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

  async function selectEnvironment(environmentId: string) {
    if (environmentId === environment?.environment_id) return;
    setBusy(true);
    setError(null);
    try {
      const selected = await environmentApi.getEnvironmentById(environmentId);
      setEnvironment(selected);
      setSelectedAgent(selected.policy_agents[0]?.id ?? "");
      setSelectedScenario(selected.seeded_examples[0]?.scenario_id ?? "");
      setFrozen(null);
      setSealedFrozen(null);
      setRun(null);
      setReplay(null);
      setDraftResult(null);
    } catch (reason) {
      setError(errorMessage(reason, "Unable to switch Environment"));
    } finally {
      setBusy(false);
    }
  }

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
    if (
      !environment ||
      !selectedAgent ||
      !selectedScenario ||
      (environment.source_kind === "editable_draft" && !draft)
    ) return;
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      const frozenEnvironment = environment.source_kind === "sealed_seed"
        ? await environmentApi.freezeSealed(environment.environment_id)
        : await draftApi.freeze(draft!.revision);
      const started = await environmentApi.start(
        selectedScenario,
        selectedAgent,
        frozenEnvironment.frozen_environment_id,
        environment.environment_id,
      );
      if (
        started.revision_digest !== frozenEnvironment.revision_digest ||
        started.scenario_id !== selectedScenario
      ) {
        throw new Error(
          "The started run did not match the frozen Environment identity.",
        );
      }
      if ("source_kind" in frozenEnvironment) {
        setSealedFrozen(frozenEnvironment);
        setFrozen(null);
      } else {
        setFrozen(frozenEnvironment);
        setSealedFrozen(null);
      }
      setRun(started);
    } catch (reason) {
      setError(errorMessage(reason, "Unable to freeze and start the run"));
    } finally {
      setBusy(false);
    }
  }

  function applyAction(type: string, arguments_: JsonObject) {
    if (!run) return;
    void perform(() => environmentApi.apply(run.run_id, type, arguments_));
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
          <span>{mode === "edit" ? "Edit" : mode === "run" ? "Run" : "Evaluate"}</span>
        </div>
      </header>

      <aside className="environment-nav" aria-label="Environment navigation">
        <div className="nav-heading"><p className="eyebrow">Environments</p></div>
        {catalog.map((entry) => {
          const active = entry.environment_id === environment?.environment_id;
          return (
            <button
              aria-current={active ? "page" : undefined}
              className={`environment-row${active ? " is-active" : ""}`}
              data-testid={`environment-nav-${entry.environment_kind}`}
              disabled={busy}
              key={entry.environment_id}
              onClick={() => void selectEnvironment(entry.environment_id)}
              type="button"
            >
              <span className="environment-icon" aria-hidden="true">
                {entry.environment_kind === "eeg" ? "EEG" : "4R"}
              </span>
              <span>
                <strong>{entry.navigation_label}</strong>
                <small>{entry.navigation_summary}</small>
              </span>
            </button>
          );
        })}
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
          <button
            aria-controls="evaluation-workspace"
            aria-selected={mode === "evaluate"}
            className={mode === "evaluate" ? "is-active" : ""}
            data-testid="mode-evaluate"
            onClick={() => setMode("evaluate")}
            role="tab"
            type="button"
          >
            Evaluate
          </button>
        </div>

        {error && <div className="error-banner" role="alert"><strong>Console request failed.</strong> {error}</div>}

        {mode === "evaluate" ? (
          <EvaluationWorkspace environmentKind={environment?.environment_kind} />
        ) : mode === "edit" ? (
          environment?.source_kind === "sealed_seed" ? (
            <SealedEnvironmentWorkspace environment={environment} />
          ) : (
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
          )
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
            {environment && (
              <EnvironmentVisualization
                environment={environment}
                key={run?.run_id ?? "no-run"}
                run={run}
              />
            )}
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
        {mode === "evaluate" ? (
          <EvaluationBoundaryPanel environmentKind={environment?.environment_kind} />
        ) : mode === "edit" ? (
          environment?.source_kind === "sealed_seed" ? (
            <ValidationPanel environment={environment} />
          ) : draft ? <DraftIdentity draft={draft} /> : <div className="loading-panel">Loading draft identity…</div>
        ) : environment ? (
          <>
            <ValidationPanel environment={environment} />
            {run ? (
              <RunIdentity environment={environment} run={run} />
            ) : (
              <EmptyRunPanel
                busy={busy}
                environment={environment}
                onStart={() => void startRun()}
                selectedAgent={selectedAgent}
                selectedScenario={selectedScenario}
                setSelectedAgent={setSelectedAgent}
                setSelectedScenario={setSelectedScenario}
              />
            )}
            {frozen && <FrozenConfigurationPanel frozen={frozen} />}
            {sealedFrozen && <SealedFrozenPanel frozen={sealedFrozen} />}
          </>
        ) : <div className="loading-panel" aria-live="polite">Loading validation…</div>}
      </aside>
    </div>
  );
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
