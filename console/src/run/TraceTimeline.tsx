import type { EnvironmentSummary, RunSnapshot, TraceEvent } from "../types";

interface TraceTimelineProps {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
  traceEvidence: (event: TraceEvent) => string | null;
}

function eventKind(event: TraceEvent): string {
  return event.type === "verifier" ? "Verification" : event.type;
}

function TraceStep({ event, evidence }: { event: TraceEvent; evidence: string | null }) {
  return (
    <li data-event-type={event.type}>
      <span className="trace-seq">{event.sequence}</span>
      <p>
        <strong>{eventKind(event)}</strong>
        {event.summary}
        {evidence && <small className="trace-evidence">{evidence}</small>}
      </p>
    </li>
  );
}

/** Scene dock in Run mode (always mounted): one step per trace event, in order. */
export function TraceTimeline({ environment, run, traceEvidence }: TraceTimelineProps) {
  return (
    <section
      aria-labelledby="timeline-title"
      className="scene-dock scene-dock--timeline trace-timeline"
      id="timeline"
    >
      <p className="eyebrow" id="timeline-title">
        Timeline
      </p>
      {environment.environment_kind === "mesoscope" && (
        <p className="trace-caption" data-testid="mesoscope-trace-boundary">
          SEALED SYNTHETIC TRACE · DISCONNECTED FROM HARDWARE
        </p>
      )}
      {!run ? (
        <p className="scene-caption">Start a run to record its timeline.</p>
      ) : (
        <ol className="trace-list" data-testid="trace-list">
          {run.trace.map((event) => (
            <TraceStep event={event} evidence={traceEvidence(event)} key={event.sequence} />
          ))}
        </ol>
      )}
    </section>
  );
}
