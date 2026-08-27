import { displayName } from "../../app/format";
import type { MesoscopeObservationView } from "./mesoscopeEvidence";

/** Package validation status, handoff stage, latest summary, and any backend-provided terminal wording. */
export function PackageStatus({ view }: { view: MesoscopeObservationView }): JSX.Element {
  const summary = view.summary === "" ? "Runtime summary unavailable." : view.summary;

  return (
    <div
      className={`mesoscope-validation-strip is-${view.validation_status}`}
      data-testid="mesoscope-validation-status"
    >
      <p className="eyebrow">Package status</p>
      <strong>{displayName(view.validation_status)}</strong>
      <span> · {displayName(view.stage)}</span>
      <p>{summary}</p>
      {view.terminal_status !== null && (
        <strong className="mesoscope-terminal-status" data-testid="mesoscope-terminal-status">
          {view.terminal_status}
        </strong>
      )}
      {view.detected_faults.length > 0 && (
        <ul data-testid="mesoscope-detected-faults">
          {view.detected_faults.map((fault) => (
            <li key={fault}>{fault}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
