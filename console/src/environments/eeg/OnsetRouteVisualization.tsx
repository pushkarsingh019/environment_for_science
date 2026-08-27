import { Fragment } from "react";
import type {
  EegOnsetRouteVisualization as VisualizationDefinition,
  EnvironmentSummary,
  RunSnapshot,
  TraceEvent,
} from "../../types";

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function EegOnsetRouteVisualization({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
}) {
  const definition = environment.visualization;
  if (definition.kind !== "eeg_onset_route") return null;
  const observation = run?.observation ?? {};
  const timeline = asRecord(observation.onset_timeline);
  const route = asRecord(observation.route_inspection);
  const freshness = asRecord(observation.freshness);
  const markerCount = number(timeline.marker_count);
  const markerLabel =
    markerCount === undefined
      ? "No test-flash evidence"
      : `${markerCount} onset marker${markerCount === 1 ? "" : "s"}`;
  const routeStatus = text(route.status, routeDefault(definition)).replaceAll(
    "_",
    " ",
  );
  const freshnessStatus = text(freshness.status, "unavailable");
  const observationSummary = text(
    observation.summary,
    "Waiting for an observation.",
  );
  const ariaLabel =
    markerCount === undefined
      ? "Synthetic EEG apparatus display awaiting test-flash evidence."
      : `Synthetic EEG apparatus display with one lower-right test flash and ${markerCount} onset markers. Evidence is ${freshnessStatus}.`;

  return (
    <section className="visualization-card" aria-labelledby="visualization-title">
      <div className="section-heading-row visualization-heading">
        <div>
          <p className="eyebrow">Synthetic apparatus view</p>
          <h2 id="visualization-title">{definition.title}</h2>
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
          <span className="visual-label">{definition.display_label}</span>
          <div className="display-screen">
            <span className="fixation" aria-hidden="true" />
            <span
              className={`flash-patch ${markerCount !== undefined ? "is-present" : ""}`}
              aria-hidden="true"
            />
            <span className="flash-label">{definition.flash_label}</span>
          </div>
        </div>

        <div className="route-stage">
          {definition.route_nodes.map((node, index) => (
            <Fragment key={node.id}>
              <span
                className={`route-line route-line-${index === 0 ? "a" : "b"}`}
                aria-hidden="true"
              />
              <div className={`route-node ${node.emphasis ? "route-node-primary" : ""}`}>
                <span className="route-node-name">{node.name}</span>
                <span
                  data-testid={node.id === "refractory_route" ? "route-inspection" : undefined}
                >
                  {node.id === "refractory_route" ? routeStatus : node.detail}
                </span>
              </div>
            </Fragment>
          ))}
          <span className="route-line route-line-c" aria-hidden="true" />
        </div>

        <div className="marker-stage">
          <div className="marker-stage-heading">
            <span className="visual-label">{definition.marker_lane_label}</span>
            <strong data-testid="marker-count">{markerLabel}</strong>
          </div>
          <div className="marker-lane" aria-hidden="true">
            <span className="lane-baseline" />
            {Array.from({ length: Math.min(markerCount ?? 0, 8) }, (_, index) => (
              <span
                className="marker-event"
                data-position={`${38 + index * 7}%`}
                data-testid="marker-event"
                key={index}
                style={{ left: `${38 + index * 7}%` }}
              />
            ))}
          </div>
          <div className="route-readout">
            <span>{definition.freshness_label}</span>
            <strong data-testid="freshness-status">{freshnessStatus}</strong>
          </div>
        </div>
      </div>

      <div className="observation-strip" aria-live="polite">
        <span className="observation-icon" aria-hidden="true" />
        <p>
          <span>Latest observation</span>
          {observationSummary}
        </p>
      </div>
    </section>
  );
}

export function eegOnsetRouteTraceEvidence(event: TraceEvent): string | null {
  if (event.type === "observation") {
    const timeline = asRecord(event.observation.onset_timeline);
    const freshness = asRecord(event.observation.freshness);
    const evidenceId = text(freshness.evidence_id, "");
    const freshnessStatus = text(freshness.status, "");
    const evidenceRevision = number(freshness.evidence_state_revision);
    const stateRevision = number(freshness.state_revision);
    const markerCount = number(timeline.marker_count);
    const revision =
      evidenceRevision !== undefined &&
      stateRevision !== undefined &&
      evidenceRevision !== stateRevision
        ? `evidence r${evidenceRevision} → state r${stateRevision}`
        : stateRevision !== undefined
          ? `state r${stateRevision}`
          : "";
    const markers =
      markerCount === undefined
        ? ""
        : `${markerCount} marker${markerCount === 1 ? "" : "s"}`;
    const details = [evidenceId, freshnessStatus, revision, markers].filter(Boolean);
    return details.length ? details.join(" · ") : null;
  }
  if (event.type === "transition") {
    return `${event.transition.from_state} → ${event.transition.to_state} · state r${event.transition.state_revision}`;
  }
  if (event.type === "verifier") {
    return event.verifier.passed ? "passed" : "failed";
  }
  return event.action.type;
}

function routeDefault(definition: VisualizationDefinition): string {
  return (
    definition.route_nodes.find((node) => node.id === "refractory_route")?.detail ??
    "unavailable"
  );
}
