import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { evaluationApi } from "../api";
import { BOTTOM_BAR_SLOT_ID } from "../app/studioTypes";
import type { EvaluationReplay, EvaluationSnapshot, EvaluationSummary } from "../types";
import { ReplayPanel } from "./ReplayPanel";
import {
  POLL_INTERVAL_MS,
  SectionCard,
  asSummary,
  dispositionLabel,
  ErrorBanner,
  mergeSummary,
  pollRetryDelay,
  safeMessage,
  statusLabel,
} from "./evaluationShared";

export interface LaunchControlsProps {
  busy: boolean;
  sessionReady: boolean;
  selected: EvaluationSnapshot | null;
  onLaunch: () => void;
  onResume: () => void;
}

/** Bottom-bar policy group for Evaluate: run status plus the two durable-run controls. */
export function LaunchControls(props: LaunchControlsProps): JSX.Element {
  const { busy, sessionReady, selected, onLaunch, onResume } = props;
  return (
    <>
      <div className="bar-label">
        <span className="bar-dot is-idle" aria-hidden="true" />
        <div>
          <strong>Evaluation</strong>
          <small>{selected ? statusLabel(selected.status) : "Not run"}</small>
        </div>
      </div>
      <button
        className="primary-button"
        data-testid="launch-evaluation"
        disabled={busy || !sessionReady}
        onClick={onLaunch}
        type="button"
      >
        {busy ? "Working…" : sessionReady ? "Run evaluation" : "Connecting…"}
      </button>
      {selected?.status === "interrupted" && (
        <button
          className="secondary-button"
          data-testid="resume-evaluation"
          disabled={busy}
          onClick={onResume}
          type="button"
        >
          {busy ? "Resuming…" : "Resume"}
        </button>
      )}
    </>
  );
}

/** Renders into the bottom bar when the shell slot exists, inline otherwise. */
function BarSlot({ children }: { children: JSX.Element }): JSX.Element {
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setHost(document.getElementById(BOTTOM_BAR_SLOT_ID));
  }, []);

  if (host === null) return <div className="evaluation-launch-row">{children}</div>;
  return createPortal(children, host);
}

function EvaluationList(props: {
  evaluations: EvaluationSummary[];
  busy: boolean;
  onLoad: (evaluationId: string) => void;
}): JSX.Element {
  const { evaluations, busy, onLoad } = props;
  return (
    <SectionCard eyebrow="Durable local runs" title="Evaluations" testId="evaluation-list" count={evaluations.length}>
      {evaluations.length === 0 ? (
        <p className="evaluation-empty">
          No local evaluation has been reserved yet. Launching creates a fixed, restart-safe 32-scenario plan.
        </p>
      ) : (
        <ul className="evaluation-list">
          {evaluations.map((evaluation) => (
            <li key={evaluation.evaluation_id}>
              <div>
                <strong>{statusLabel(evaluation.status)}</strong>
                <span>
                  {evaluation.progress.completed_scenarios} / {evaluation.progress.total_scenarios} scenarios
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
    </SectionCard>
  );
}

function ProgressPanel(props: { snapshot: EvaluationSnapshot }): JSX.Element {
  const { snapshot } = props;
  const progress = snapshot.progress;
  const percentage = Math.round((progress.completed_scenarios / progress.total_scenarios) * 100);
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
      <p className="evaluation-progress-message" data-testid="evaluation-progress-message">
        {progress.message}
      </p>
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

function CalibrationPanel(props: { snapshot: EvaluationSnapshot }): JSX.Element {
  const calibration = props.snapshot.calibration;
  const heading = {
    pending: "Readiness pending",
    ready: "Ready for training",
    not_ready: "Not ready for training",
  }[calibration.status];
  const accuracy =
    calibration.scientific_accuracy === null
      ? "No scientific accuracy yet"
      : `${Math.round(calibration.scientific_accuracy * 100)}% scientific accuracy`;

  return (
    <section className="evaluation-card evaluation-calibration" data-testid="evaluation-calibration">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Pre-training assessment</p>
          <h2>{heading}</h2>
        </div>
        <span className={`evaluation-status is-${calibration.status}`}>{accuracy}</span>
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
      <div className="evaluation-calibration-levels" data-testid="evaluation-calibration-levels">
        {calibration.levels.map((level) => (
          <article key={level.level}>
            <header>
              <strong>Level {level.level}</strong>
              <span>
                {level.completed_scenarios} / {level.total_scenarios}
              </span>
            </header>
            <p>{level.label}</p>
            <small>
              {level.scientific_successes} success · {level.scientific_failures} failure ·{" "}
              {level.infrastructure_errors} infrastructure
            </small>
          </article>
        ))}
      </div>
    </section>
  );
}

function AttemptTable(props: {
  snapshot: EvaluationSnapshot;
  busy: boolean;
  onReplay: (attemptId: string) => void;
}): JSX.Element {
  const { snapshot, busy, onReplay } = props;
  return (
    <SectionCard
      eyebrow="Completed scenario attempts"
      title="Attempts"
      testId="evaluation-attempts"
      count={snapshot.attempts.length}
    >
      {snapshot.attempts.length === 0 ? (
        <p className="evaluation-empty">Attempts will appear here as durable slots complete.</p>
      ) : (
        <div className="evaluation-table-scroll">
          <table className="evaluation-table">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Disposition</th>
                <th>Summary</th>
                <th>Replay</th>
              </tr>
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
    </SectionCard>
  );
}

/** Durable local base-model evaluation: launch, resume, inspect and replay. */
export function DevelopmentEvaluation(): JSX.Element {
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
    evaluationApi
      .list()
      .then((loaded) => {
        if (cancelled) return;
        setEvaluations(loaded);
        setSessionReady(true);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(safeMessage(reason, "Unable to list local evaluations."));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const evaluationId = selected?.evaluation_id;
    const status = selected?.status;
    const waitingForResume = evaluationId === resumeRequested;
    if (!evaluationId || !status || (!waitingForResume && !["queued", "running"].includes(status))) {
      return undefined;
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
        setResumeRequested((current) =>
          current === evaluationId && loaded.status !== "interrupted" ? null : current,
        );
        setSelected((current) => (current?.evaluation_id === evaluationId ? loaded : current));
        setEvaluations((current) => mergeSummary(current, loaded));
        if (loaded.status === "interrupted" || ["queued", "running"].includes(loaded.status)) {
          schedule(POLL_INTERVAL_MS);
        }
      } catch (reason) {
        if (!active) return;
        consecutiveFailures += 1;
        setPollError(safeMessage(reason, "Unable to refresh evaluation progress."));
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

  async function launch(): Promise<void> {
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

  async function load(evaluationId: string): Promise<void> {
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

  async function resume(): Promise<void> {
    if (!selected || selected.status !== "interrupted") return;
    const evaluationId = selected.evaluation_id;
    setBusy(true);
    setError(null);
    setPollError(null);
    setReplay(null);
    try {
      const resumed = await evaluationApi.resume(evaluationId);
      setResumeRequested(evaluationId);
      setSelected((current) => (current?.evaluation_id === evaluationId ? resumed : current));
      setEvaluations((current) => mergeSummary(current, resumed));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to resume the local evaluation."));
    } finally {
      setBusy(false);
    }
  }

  async function openReplay(attemptId: string): Promise<void> {
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

  const message = error ?? pollError;

  return (
    <>
      <BarSlot>
        <LaunchControls
          busy={busy}
          sessionReady={sessionReady}
          selected={selected}
          onLaunch={() => void launch()}
          onResume={() => void resume()}
        />
      </BarSlot>

      <SectionCard
        eyebrow="Fixed development split · google/gemma-4-E4B-it"
        title="Base Gemma development calibration"
        id="development-evaluation"
      >
        <p className="evaluation-lead">
          Run the approved local model through all 32 development scenarios.
        </p>
        {message !== null && <ErrorBanner lead="Evaluation request failed." message={message} />}

        <div className="evaluation-grid">
          <EvaluationList evaluations={evaluations} busy={busy || !sessionReady} onLoad={(id) => void load(id)} />
          {selected ? (
            <ProgressPanel snapshot={selected} />
          ) : (
            <section className="evaluation-card evaluation-selection-empty">
              <p className="eyebrow">No evaluation selected</p>
              <h2>Run or load an evaluation</h2>
              <p>Progress, outcomes, and replay links appear here.</p>
            </section>
          )}
        </div>

        {replay && <ReplayPanel replay={replay} />}
        {selected && <CalibrationPanel snapshot={selected} />}
        {selected && <AttemptTable snapshot={selected} busy={busy} onReplay={(id) => void openReplay(id)} />}
      </SectionCard>
    </>
  );
}

export { asSummary };
