import type { EnvironmentSummary, MesoscopeHandoffVisualization, TraceEvent } from "../../types";
import { stringList, text } from "../../app/json";
import type { DocksProps } from "../adapter";
import { readMesoscopeObservation } from "./mesoscopeEvidence";
import { PackageStatus } from "./PackageStatus";
import { SurveyPhantom } from "./SurveyPhantom";

export const SEALED_PREVIEW_TEXT =
  "Runtime evidence is not loaded. Freeze and start a sealed run to display product-owned profile, plan, survey, tile, and package observations.";

/** The sealed handoff presentation block, or null for any other apparatus. */
export function mesoscopeVisualization(environment: EnvironmentSummary): MesoscopeHandoffVisualization | null {
  return environment.visualization.kind === "mesoscope_handoff_v1" ? environment.visualization : null;
}

/** Run-mode docks inside the scene card: survey phantom with tiles, and the package status. */
export function MesoscopeRunDocks({ environment, run }: DocksProps): JSX.Element {
  const visualization = mesoscopeVisualization(environment);
  const view = run === null ? null : readMesoscopeObservation(run.observation);

  return (
    <section
      aria-label="Synthetic survey and region tiles"
      className="scene-docks mesoscope-handoff"
      data-testid="mesoscope-handoff-visualization"
    >
      {view === null || visualization === null ? (
        <p className="scene-caption" data-testid="mesoscope-sealed-preview">
          {SEALED_PREVIEW_TEXT}
        </p>
      ) : (
        <>
          <div className="scene-dock scene-dock--survey">
            <SurveyPhantom view={view} visualization={visualization} />
          </div>
          <div className="scene-dock scene-dock--package">
            <PackageStatus view={view} />
          </div>
        </>
      )}
    </section>
  );
}

/** Timeline evidence line per trace event; only fields the Policy agent can see are echoed. */
export function mesoscopeHandoffTraceEvidence(event: TraceEvent): string | null {
  if (event.type === "observation") {
    const stage = text(event.observation.stage, "");
    const validation = text(event.observation.validation_status, "");
    const terminal = text(event.observation.terminal_status, "");
    const faults = stringList(event.observation.detected_faults);
    const line = [stage, validation, ...faults, terminal]
      .filter((item) => item !== "" && item !== "not_run")
      .join(" · ");
    return line === "" ? null : line;
  }
  if (event.type === "transition") {
    return `${event.transition.from_state} → ${event.transition.to_state} · state r${event.transition.state_revision}`;
  }
  if (event.type === "verifier") {
    return `${event.verifier.passed ? "passed" : "failed"} · ${event.verifier.terminal_disposition}`;
  }
  return `${event.action.type} · empty sealed input`;
}
