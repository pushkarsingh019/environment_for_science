import type { ReactNode } from "react";
import { displayName } from "../app/format";
import { asObject, text } from "../app/json";
import { RUN_STATUS_LABELS } from "../app/studioTypes";
import type { ActionPreference } from "../app/studioTypes";
import { RunActionComposer } from "../environments/RunActionComposer";
import { BarLabel } from "../shell/BottomBar";
import type { EnvironmentSummary, JsonObject, RunSnapshot } from "../types";

export interface RunControlsProps {
  mode: "edit" | "run";
  environment: EnvironmentSummary | null;
  run: RunSnapshot | null;
  busy: boolean;
  canStart: boolean;
  selectedScenario: string;
  onSelectScenario: (id: string) => void;
  preferred: ActionPreference | null;
  onPreferredConsumed: () => void;
  onStart: () => void;
  onOpenRun: () => void;
  onAction: (type: string, arguments_: JsonObject) => void;
  onVerify: () => void;
  onReplay: () => void;
  onReset: () => void;
}

const STATUS_DOT: Record<RunSnapshot["status"], "active" | "awaiting" | "done"> = {
  active: "active",
  awaiting_verification: "awaiting",
  completed: "done",
};

/** Evidence ids the observation currently reports as fresh; offered as argument suggestions. */
function currentEvidenceIds(run: RunSnapshot): string[] {
  const freshness = asObject(run.observation.evidence_freshness);
  if (!freshness) return [];
  return Object.values(freshness).flatMap((entry) => {
    const record = asObject(entry);
    return record && record.status === "current" && typeof record.evidence_id === "string"
      ? [record.evidence_id]
      : [];
  });
}

function PolicyTestLabel({ run, extra }: { run: RunSnapshot | null; extra?: ReactNode }) {
  return (
    <BarLabel
      caption={<span data-testid="run-status">{run ? RUN_STATUS_LABELS[run.status] : "Not run"}</span>}
      dot={run ? STATUS_DOT[run.status] : "idle"}
      extra={extra}
      title="Policy test"
    />
  );
}

interface SeededExamplePickerProps {
  environment: EnvironmentSummary | null;
  selectedScenario: string;
  onSelectScenario: (id: string) => void;
  busy: boolean;
}

function SeededExamplePicker({
  environment,
  selectedScenario,
  onSelectScenario,
  busy,
}: SeededExamplePickerProps) {
  const example = environment?.seeded_examples.find(
    (candidate) => candidate.scenario_id === selectedScenario,
  );
  return (
    <>
      <label className="sr-only" htmlFor="seeded-example">
        Seeded example
      </label>
      <select
        className="bar-select"
        data-testid="seeded-example-selector"
        disabled={busy || !environment}
        id="seeded-example"
        onChange={(event) => onSelectScenario(event.target.value)}
        value={selectedScenario}
      >
        {environment?.seeded_examples.map((candidate) => (
          <option key={candidate.scenario_id} value={candidate.scenario_id}>
            {candidate.label}
          </option>
        ))}
      </select>
      {example && (
        <span className="bar-caption" data-testid="seeded-example-stage">
          {displayName(example.stage)}
        </span>
      )}
    </>
  );
}

/** Bottom-bar right group ("Policy test") for Edit and Run modes. */
export function RunControls(props: RunControlsProps) {
  const { mode, environment, run, busy, canStart, onStart } = props;
  const picker = (
    <SeededExamplePicker
      busy={busy}
      environment={environment}
      onSelectScenario={props.onSelectScenario}
      selectedScenario={props.selectedScenario}
    />
  );

  if (mode === "edit") {
    return (
      <>
        <PolicyTestLabel run={run} />
        {picker}
        <button
          className="primary-button"
          data-testid="start-run"
          disabled={busy || !canStart}
          onClick={onStart}
          type="button"
        >
          {busy ? "Starting…" : run ? "Start new run" : "Start"}
        </button>
        {run && (
          <button className="secondary-button" onClick={props.onOpenRun} type="button">
            Open run
          </button>
        )}
      </>
    );
  }

  if (!run) {
    return (
      <>
        <PolicyTestLabel run={null} />
        {picker}
        <button
          className="primary-button"
          data-testid="start-run"
          disabled={busy || !canStart}
          onClick={onStart}
          type="button"
        >
          {busy ? "Starting…" : "Start"}
        </button>
        <button className="secondary-button" data-testid="reset-run" disabled type="button">
          Reset
        </button>
      </>
    );
  }

  const completed = run.status === "completed";
  return (
    <>
      <PolicyTestLabel
        extra={
          <span aria-live="polite" className="action-result" data-testid="action-result">
            {text(run.observation.summary, "Current observation loaded.")}
          </span>
        }
        run={run}
      />
      {environment && (
        <RunActionComposer
          actions={environment.actions}
          busy={busy || completed}
          key={run.run_id}
          onAction={props.onAction}
          onPreferredConsumed={props.onPreferredConsumed}
          permittedActions={run.permitted_actions}
          preferred={props.preferred}
          suggestedValues={{ evidence_id: currentEvidenceIds(run) }}
        />
      )}
      {completed ? (
        <button
          className="secondary-button"
          data-testid="replay-run"
          disabled={busy}
          onClick={props.onReplay}
          type="button"
        >
          Replay
        </button>
      ) : (
        <button
          className="secondary-button"
          data-testid="verify-run"
          disabled={busy}
          onClick={props.onVerify}
          type="button"
        >
          Verify
        </button>
      )}
      <button
        className="secondary-button"
        data-testid="reset-run"
        disabled={busy}
        onClick={props.onReset}
        type="button"
      >
        Reset
      </button>
    </>
  );
}
