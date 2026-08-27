import type { EegObservationView } from "./eegEvidence";

const NOT_OBSERVED = "Not observed";

interface LaneProps {
  label: string;
  testId: string;
  values: Array<number | undefined>;
}

/** Event markers placed on a 0–1000 ms lane, clamped inside the track. */
function TimelineLane({ label, testId, values }: LaneProps): JSX.Element {
  const present = values.filter((value): value is number => value !== undefined);
  return (
    <div className="timeline-lane" data-testid={testId}>
      <span>{label}</span>
      <div>
        <i />
        {present.map((value, index) => (
          <b className="marker-event" key={`${value}-${index}`} style={{ left: `${Math.max(2, Math.min(98, value / 10))}%` }} />
        ))}
      </div>
    </div>
  );
}

/** Recording, stimulus, marker and response timelines with the plain-language evidence list. */
export function IntegrationTimeline({ view }: { view: EegObservationView }): JSX.Element {
  const { onset, response, recording } = view;
  const timeline = recording?.timeline ?? {};
  const markers = onset?.marker_times_ms ?? [];
  const occurrence = response?.occurrence_detected === true;
  const identity = response?.queried_identity ?? null;
  return (
    <div className="integration-view" data-testid="integration-timeline">
      <div aria-hidden="true" className="timeline-lanes">
        <TimelineLane label="Recording" testId="timeline-recording-lane" values={[timeline.eeg_anchor_ms]} />
        <TimelineLane label="Stimulus" testId="timeline-stimulus-lane" values={[timeline.stimulus_ms, onset?.flash_time_ms]} />
        <TimelineLane label="Onset markers" testId="timeline-onset-lane" values={markers} />
        <TimelineLane
          label="Response occurrence"
          testId="timeline-response-occurrence-lane"
          values={occurrence ? [response?.event_time_ms] : []}
        />
        <TimelineLane
          label="Response identity"
          testId="timeline-response-identity-lane"
          values={identity !== null ? [response?.event_time_ms] : []}
        />
      </div>
      <dl className="integration-evidence-list">
        <div>
          <dt>Recording state</dt>
          <dd>
            {recording?.recording_active === true ? "Active" : "Not active"} · {recording?.status ?? NOT_OBSERVED}
          </dd>
        </div>
        <div>
          <dt>Lower-right cue</dt>
          <dd>{onset?.cue_visible === true ? "Visible in participant view" : "Not visible in participant view"}</dd>
        </div>
        <div>
          <dt>Onset markers</dt>
          <dd>
            <span data-testid="marker-count">
              {markers.length} at {markers.length > 0 ? markers.join(", ") : "no recorded time"} ms
            </span>
          </dd>
        </div>
        <div>
          <dt>Response occurrence</dt>
          <dd>{occurrence ? "Detected" : "Not detected"}</dd>
        </div>
        <div>
          <dt>Queried identity</dt>
          <dd>{identity ?? NOT_OBSERVED}</dd>
        </div>
        <div>
          <dt>Simulated press</dt>
          <dd>{response?.simulated_press || NOT_OBSERVED}</dd>
        </div>
      </dl>
    </div>
  );
}
