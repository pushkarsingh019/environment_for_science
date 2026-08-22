import { useEffect, useMemo, useState } from "react";
import { environmentApi } from "./api";
import type {
  EnvironmentSummary,
  PolicyAgent,
  RunSnapshot,
  UnknownRecord,
} from "./types";

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function policyAgentName(value: RunSnapshot["policy_agent"]): string {
  if (typeof value === "string") return value;
  return value.name || value.id;
}

function latestFlash(observation: UnknownRecord): UnknownRecord {
  return asRecord(
    observation.latest_flash ?? observation.test_flash ?? observation.flash,
  );
}

function markerCount(observation: UnknownRecord): number | undefined {
  const flash = latestFlash(observation);
  const direct =
    numberValue(flash.marker_count) ?? numberValue(observation.marker_count);
  if (direct !== undefined) return direct;
  if (Array.isArray(flash.markers)) return flash.markers.length;
  if (Array.isArray(observation.onset_markers)) {
    return observation.onset_markers.length;
  }
  return undefined;
}

function observationSummary(observation: UnknownRecord): string {
  return (
    stringValue(observation.summary) ??
    stringValue(observation.message) ??
    "Waiting for a Policy-visible observation."
  );
}

function routeDetails(observation: UnknownRecord) {
  const route = asRecord(
    observation.onset_route ?? observation.route ?? observation.trigger_route,
  );
  return {
    inspection:
      stringValue(route.inspection_status) ??
      stringValue(route.inspection) ??
      (route.inspected === true ? "inspected" : "not inspected"),
    refractory:
      stringValue(route.refractory_route) ??
      stringValue(route.refractory_status) ??
      stringValue(observation.refractory_route_status) ??
      "unverified",
  };
}

function digestTail(digest: string): string {
  if (!digest) return "Unavailable";
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

function ValidationPanel({ environment }: { environment: EnvironmentSummary }) {
  const safe = !environment.hiddenStateExposed;
  const valid = environment.validation.status.toLowerCase() === "valid";

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
        <span className={`status-dot ${valid && safe ? "is-ready" : ""}`}>
          {valid && safe ? "Ready" : "Review"}
        </span>
      </div>
      <p className="validation-summary">{environment.validation.summary}</p>
      <ul className="quiet-list">
        {environment.validation.checks.map((check) => (
          <li key={check}>{check}</li>
        ))}
        <li>
          {safe
            ? "Policy-visible observations are separated from scenario truth"
            : "Visibility boundary requires review"}
        </li>
      </ul>
    </section>
  );
}

function ApparatusVisualization({ run }: { run: RunSnapshot | null }) {
  const observation = run?.observation ?? {};
  const count = markerCount(observation);
  const route = routeDetails(observation);
  const hasFlash = count !== undefined;
  const markerLabel =
    count === undefined
      ? "No test-flash evidence"
      : `${count} onset marker${count === 1 ? "" : "s"}`;
  const ariaLabel = hasFlash
    ? `Synthetic EEG apparatus display with a lower-right test flash routed to ${count} onset markers.`
    : "Synthetic EEG apparatus display with a lower-right optical onset route. No test-flash evidence yet.";

  return (
    <section className="visualization-card" aria-labelledby="visualization-title">
      <div className="section-heading-row visualization-heading">
        <div>
          <p className="eyebrow">Synthetic apparatus view</p>
          <h2 id="visualization-title">Onset-marker preflight</h2>
        </div>
        <span className="synthetic-label">Simulation only</span>
      </div>

      <div
        className="apparatus-visualization"
        data-testid="apparatus-visualization"
        aria-label={ariaLabel}
        role="img"
      >
        <div className="display-stage">
          <span className="visual-label">Presentation display</span>
          <div className="display-screen">
            <span className="fixation" aria-hidden="true" />
            <span
              className={`flash-patch ${hasFlash ? "is-present" : ""}`}
              aria-hidden="true"
            />
            <span className="flash-label">Lower-right test flash</span>
          </div>
        </div>

        <div className="route-stage" aria-hidden="true">
          <span className="route-line route-line-a" />
          <div className="route-node">
            <span className="route-node-name">Light detector</span>
            <span>simulated signal</span>
          </div>
          <span className="route-line route-line-b" />
          <div className="route-node route-node-primary">
            <span className="route-node-name">Refractory route</span>
            <span>{route.refractory}</span>
          </div>
          <span className="route-line route-line-c" />
        </div>

        <div className="marker-stage">
          <div className="marker-stage-heading">
            <span className="visual-label">Marker event lane</span>
            <strong data-testid="marker-count">{markerLabel}</strong>
          </div>
          <div className="marker-lane" aria-hidden="true">
            <span className="lane-baseline" />
            {Array.from({ length: Math.min(count ?? 0, 8) }, (_, index) => (
              <span
                className="marker-event"
                key={index}
                style={{ left: `${38 + index * 7}%` }}
              />
            ))}
          </div>
          <div className="route-readout">
            <span>Route inspection</span>
            <strong>{route.inspection}</strong>
          </div>
        </div>
      </div>

      <div className="observation-strip">
        <span className="observation-icon" aria-hidden="true" />
        <p>
          <span>Latest Policy-visible observation</span>
          {observationSummary(observation)}
        </p>
      </div>
    </section>
  );
}

function RunIdentity({ run }: { run: RunSnapshot }) {
  const statusLabel =
    run.status.toLowerCase() === "active" ? "Active run" : run.status;

  return (
    <section className="identity-panel" aria-label="Frozen run identity">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Run state</p>
          <h2 data-testid="run-status">{statusLabel}</h2>
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
          <dd data-testid="policy-agent-identity">
            {policyAgentName(run.policy_agent)}
          </dd>
        </div>
      </dl>
      <p className="identity-note">
        This immutable revision stays fixed for reset and deterministic replay.
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
  const canStart =
    environment.validation.status.toLowerCase() === "valid" &&
    !environment.hiddenStateExposed;

  return (
    <section className="start-panel" aria-labelledby="start-title">
      <p className="eyebrow">Run setup</p>
      <h2 id="start-title">Freeze this seeded Environment</h2>
      <p>
        Starting creates an immutable revision and records the active Policy
        agent before any recovery action is taken.
      </p>
      <label htmlFor="policy-agent">Policy agent</label>
      <select
        id="policy-agent"
        value={selectedAgent}
        onChange={(event) => setSelectedAgent(event.target.value)}
      >
        {environment.policyAgents.map((agent: PolicyAgent) => (
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
        disabled={!canStart || busy}
      >
        {busy ? "Freezing revision…" : "Start frozen run"}
      </button>
      <p className="boundary-note">
        Synthetic apparatus actions only. No physical or operational controls.
      </p>
    </section>
  );
}

export function App() {
  const [environment, setEnvironment] = useState<EnvironmentSummary | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    environmentApi
      .getEnvironment()
      .then((loaded) => {
        if (cancelled) return;
        setEnvironment(loaded);
        setSelectedAgent(loaded.policyAgents[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Unable to load Environment");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const environmentTitle = useMemo(
    () => environment?.name ?? "Loading Environment…",
    [environment],
  );

  async function startRun() {
    if (!environment || !selectedAgent) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await environmentApi.startRun(environment.scenarioId, selectedAgent));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to start the run");
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
        <div className="nav-heading">
          <p className="eyebrow">Environments</p>
          <button type="button" className="icon-button" aria-label="Environment details">
            ···
          </button>
        </div>
        <button className="environment-row is-active" type="button">
          <span className="environment-icon" aria-hidden="true">EEG</span>
          <span>
            <strong>EEG</strong>
            <small>Marker recovery</small>
          </span>
        </button>
        <div className="nav-rule" />
        <p className="nav-caption">Available in later slices</p>
        <div className="environment-row is-disabled" aria-disabled="true">
          <span className="environment-icon muted" aria-hidden="true">4R</span>
          <span>
            <strong>Mesoscope</strong>
            <small>Sealed synthetic handoff</small>
          </span>
        </div>
        <footer className="nav-footer">
          <span className="simulation-indicator" aria-hidden="true" />
          Synthetic environments
        </footer>
      </aside>

      <main className="workspace">
        <div className="workspace-heading">
          <div>
            <p className="breadcrumb">EEG / Seeded preflight</p>
            <h1>{environmentTitle}</h1>
            <p>
              Trace one lower-right display flash through the simulated onset-marker route.
            </p>
          </div>
          <span className="scenario-tag">Seeded scenario</span>
        </div>

        {error && (
          <div className="error-banner" role="alert" data-testid="request-error">
            <strong>Console request failed.</strong> {error}
          </div>
        )}

        <ApparatusVisualization run={run} />

        <section className="lower-workspace" aria-label="Run actions and canonical trace">
          <div className="placeholder-panel">
            <p className="eyebrow">Permitted actions</p>
            <h2>Recovery actions</h2>
            <p>Start the frozen run to inspect and recover the simulated route.</p>
          </div>
          <div className="placeholder-panel">
            <p className="eyebrow">Canonical trace</p>
            <h2>Ordered run evidence</h2>
            <p>Observations, actions, transitions, freshness, and verification appear here.</p>
          </div>
        </section>
      </main>

      <aside className="details-rail" aria-label="Environment and run details">
        {environment ? (
          <>
            <ValidationPanel environment={environment} />
            {run ? (
              <RunIdentity run={run} />
            ) : (
              <EmptyRunPanel
                environment={environment}
                selectedAgent={selectedAgent}
                setSelectedAgent={setSelectedAgent}
                onStart={startRun}
                busy={busy}
              />
            )}
          </>
        ) : (
          <div className="loading-panel" aria-live="polite">Loading validation…</div>
        )}
      </aside>
    </div>
  );
}
