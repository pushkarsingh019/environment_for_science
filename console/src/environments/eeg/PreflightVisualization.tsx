import { useState } from "react";
import type {
  EegPreflightVisualization as EegPreflightVisualizationContract,
  EnvironmentSummary,
  JsonObject,
  JsonValue,
  RunSnapshot,
  TraceEvent,
} from "../../types";

function asObject(value: JsonValue | undefined): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function asObjects(value: JsonValue | undefined): JsonObject[] {
  return Array.isArray(value)
    ? value.map((item) => asObject(item)).filter((item) => Object.keys(item).length > 0)
    : [];
}

function strings(value: JsonValue | undefined): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function numbers(value: JsonValue | undefined): number[] {
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === "number")
    : [];
}

function text(value: JsonValue | undefined, fallback = "Not observed"): string {
  return typeof value === "string" ? value : fallback;
}

function number(value: JsonValue | undefined): number | null {
  return typeof value === "number" ? value : null;
}

function waveformPath(samples: number[], row: number): string {
  const left = 56;
  const width = 640;
  const center = 40 + row * 76;
  return samples
    .map((sample, index) => {
      const x = left + (index / Math.max(1, samples.length - 1)) * width;
      const y = center - (Math.max(-80, Math.min(80, sample)) / 80) * 27;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function spectrumPath(magnitudes: number[], row: number, maximum: number): string {
  const left = 56;
  const width = 640;
  const baseline = 57 + row * 67;
  return magnitudes
    .map((magnitude, index) => {
      const x = left + (index / Math.max(1, magnitudes.length - 1)) * width;
      const y = baseline - (magnitude / Math.max(1, maximum)) * 42;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function ScalpMontage({
  montage,
  channelSites,
  panelLabel,
  sites,
}: {
  montage: JsonObject;
  channelSites: string[];
  panelLabel: string;
  sites: EegPreflightVisualizationContract["scalp_sites"];
}) {
  const recordingSites = strings(montage.recording_sites);
  const reference = text(montage.reference, "");
  const ground = text(montage.ground, "");
  const shown = new Set([...channelSites, reference, ground]);
  const shownSites = sites.filter((site) => shown.has(site.id));

  return (
    <figure
      aria-label={`Schematic Procedure Montage: recording ${recordingSites.join(", ")}; reference ${reference}; ground ${ground}.`}
      className="diagnostic-montage"
      data-testid="eeg-montage"
    >
      <figcaption>{panelLabel}</figcaption>
      <div className="diagnostic-head" aria-hidden="true">
        <span className="diagnostic-nasion" />
        {shownSites.map((site) => {
          const id = site.id;
          const role = id === reference
            ? "reference"
            : id === ground
              ? "ground"
              : recordingSites.includes(id)
                ? "required"
                : "optional";
          return (
            <span
              className={`diagnostic-site is-${role}`}
              data-role={role}
              data-testid={`montage-site-${id}`}
              key={id}
              style={{ left: `${site.x}%`, top: `${site.y}%` }}
              title={`${id} · ${role}`}
            >
              {id}
            </span>
          );
        })}
      </div>
      <p>{text(montage.coordinate_note, "Schematic positions only.")}</p>
    </figure>
  );
}

function SignalView({
  observation,
  visualization,
}: {
  observation: JsonObject;
  visualization: EegPreflightVisualizationContract;
}) {
  const montage = asObject(observation.montage);
  const window = asObject(observation.eeg_window);
  const channels = asObjects(window.channels);
  const referenceComparison = asObject(window.reference_comparison);
  const referenceSite = text(referenceComparison.site, "");
  const referenceSamples = numbers(referenceComparison.samples);
  const frequency = Object.keys(asObject(observation.frequency_evidence)).length > 0
    ? asObject(observation.frequency_evidence)
    : null;
  const sampleCount = number(window.display_sample_count) ?? 0;
  const channelSites = channels.map((channel) => text(channel.site));
  const freshness = asObject(asObject(observation.evidence_freshness).eeg);
  const stateRevision = number(freshness.state_revision) ?? 0;
  const evidenceRevision = number(freshness.evidence_state_revision) ?? stateRevision;

  return (
    <div className="diagnostic-signal-layout">
      <div className="diagnostic-plots">
        <figure
          aria-label={`Synthetic EEG window ${text(window.evidence_id)} with ${channelSites.join(", ")} and reference comparison ${referenceSite}; ${sampleCount} displayed samples per trace; evidence is ${text(window.status)}.`}
          className={`trace-figure is-${text(window.status, "current")}`}
          data-evidence-revision={evidenceRevision}
          data-state-revision={stateRevision}
          data-testid="eeg-trace-window"
          data-window-id={text(window.evidence_id)}
        >
          <figcaption>
            <span>{visualization.trace_panel_label}</span>
            <small>
              {sampleCount} points · {number(window.display_duration_seconds)?.toFixed(1)} s
              display · repeating logical sweep
            </small>
          </figcaption>
          <svg
            aria-hidden="true"
            preserveAspectRatio="none"
            viewBox={`0 0 720 ${Math.max(90, (channels.length + 1) * 76)}`}
          >
            {channels.map((channel, index) => {
              const site = text(channel.site);
              const samples = numbers(channel.samples);
              return (
                <g
                  data-sample-count={samples.length}
                  data-testid={`trace-channel-${site}`}
                  key={site}
                >
                  <line className="trace-baseline" x1="56" x2="696" y1={40 + index * 76} y2={40 + index * 76} />
                  <text className="trace-site-label" x="4" y={44 + index * 76}>{site}</text>
                  <path className="trace-waveform" d={waveformPath(samples, index)} />
                </g>
              );
            })}
            <g
              data-sample-count={referenceSamples.length}
              data-testid={`trace-reference-${referenceSite}`}
            >
              <line
                className="trace-baseline"
                x1="56"
                x2="696"
                y1={40 + channels.length * 76}
                y2={40 + channels.length * 76}
              />
              <text className="trace-site-label" x="4" y={44 + channels.length * 76}>
                {referenceSite} ref
              </text>
              <path
                className="trace-waveform trace-reference-waveform"
                d={waveformPath(referenceSamples, channels.length)}
              />
            </g>
            <line
              className="trace-logical-sweep"
              data-testid="trace-logical-sweep"
              x1="56"
              x2="56"
              y1="8"
              y2={Math.max(82, (channels.length + 1) * 76 - 8)}
            />
          </svg>
          <div className="sr-only">
            <table className="evidence-table">
              <caption>Measurements derived from the displayed synthetic samples</caption>
              <thead><tr><th>Channel</th><th>Role</th><th>Range</th><th>Unique values</th><th>Rail fraction</th></tr></thead>
              <tbody>
                {channels.map((channel) => {
                  const measurements = asObject(channel.measurements);
                  return (
                    <tr key={text(channel.site)}>
                      <th>{text(channel.site)}</th>
                      <td>{text(channel.role)}</td>
                      <td>{number(measurements.range_uv)}</td>
                      <td>{number(measurements.unique_value_count)}</td>
                      <td>{number(measurements.rail_fraction)}</td>
                    </tr>
                  );
                })}
                <tr>
                  <th>{referenceSite}</th>
                  <td>reference comparison</td>
                  <td colSpan={3}>{referenceSamples.length} displayed samples</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="measurement-note">{text(window.measurement_note)}</p>
        </figure>

        <details
          className="frequency-disclosure"
          data-testid="frequency-disclosure"
          key={frequency ? text(frequency.source_window_id) : "frequency-empty"}
          open={frequency !== null}
        >
          <summary>{visualization.details_toggle_label}</summary>
          {frequency ? (
            <FrequencyView
              frequency={frequency}
              panelLabel={visualization.frequency_panel_label}
            />
          ) : (
            <p>Choose “View frequency evidence” to record measurements from this window.</p>
          )}
        </details>
      </div>
      <ScalpMontage
        channelSites={channelSites}
        montage={montage}
        panelLabel={visualization.montage_panel_label}
        sites={visualization.scalp_sites}
      />
    </div>
  );
}

function FrequencyView({
  frequency,
  panelLabel,
}: {
  frequency: JsonObject;
  panelLabel: string;
}) {
  const channels = asObjects(frequency.channels);
  const referenceComparison = asObject(frequency.reference_comparison);
  const referenceSite = text(referenceComparison.site, "");
  const referenceMagnitudes = numbers(referenceComparison.magnitudes);
  const relationships = asObject(frequency.relationships);
  const bins = numbers(frequency.bins_hz);
  const maximum = Math.max(
    1,
    ...channels.flatMap((channel) => numbers(channel.magnitudes)),
    ...referenceMagnitudes,
  );
  return (
    <figure
      aria-label={`${panelLabel}: synthetic measurements at ${bins.join(", ")} hertz from window ${text(frequency.source_window_id)}.`}
      className="frequency-figure"
    >
      <svg aria-hidden="true" preserveAspectRatio="none" viewBox={`0 0 720 ${Math.max(80, (channels.length + 1) * 67)}`}>
        {channels.map((channel, index) => {
          const site = text(channel.site);
          const magnitudes = numbers(channel.magnitudes);
          return (
            <g data-testid={`frequency-channel-${site}`} key={site}>
              <line className="trace-baseline" x1="56" x2="696" y1={57 + index * 67} y2={57 + index * 67} />
              <text className="trace-site-label" x="4" y={48 + index * 67}>{site}</text>
              <path className="frequency-waveform" d={spectrumPath(magnitudes, index, maximum)} />
            </g>
          );
        })}
        <g data-testid={`frequency-reference-${referenceSite}`}>
          <line
            className="trace-baseline"
            x1="56"
            x2="696"
            y1={57 + channels.length * 67}
            y2={57 + channels.length * 67}
          />
          <text className="trace-site-label" x="4" y={48 + channels.length * 67}>
            {referenceSite} ref
          </text>
          <path
            className="frequency-waveform frequency-reference-waveform"
            d={spectrumPath(referenceMagnitudes, channels.length, maximum)}
          />
        </g>
      </svg>
      <p className="frequency-bins">Bins: {bins.map((bin) => `${bin} Hz`).join(" · ")}</p>
      <dl className="frequency-relationships">
        <div>
          <dt>Mean absolute pairwise channel correlation</dt>
          <dd>{number(relationships.mean_absolute_pairwise_waveform_correlation)?.toFixed(3)}</dd>
        </div>
        <div>
          <dt>Mean absolute correlation with {referenceSite} reference comparison</dt>
          <dd>{number(relationships.mean_absolute_reference_waveform_correlation)?.toFixed(3)}</dd>
        </div>
      </dl>
      <p className="measurement-note">{text(frequency.measurement_note)}</p>
    </figure>
  );
}

function IntegrationView({ observation }: { observation: JsonObject }) {
  const onset = asObject(observation.onset_evidence);
  const response = asObject(observation.response_evidence);
  const recording = asObject(observation.recording_evidence);
  const timeline = asObject(recording.timeline);
  const markers = numbers(onset.marker_times_ms);
  const occurrence = response.occurrence_detected === true;
  return (
    <section className="integration-view" data-testid="integration-timeline">
      <div className="timeline-lanes" aria-hidden="true">
        <TimelineLane label="Recording" testId="timeline-recording-lane" values={[number(timeline.eeg_anchor_ms)]} />
        <TimelineLane label="Stimulus" testId="timeline-stimulus-lane" values={[number(timeline.stimulus_ms), number(onset.flash_time_ms)]} />
        <TimelineLane label="Onset markers" testId="timeline-onset-lane" values={markers} />
        <TimelineLane label="Response occurrence" testId="timeline-response-occurrence-lane" values={occurrence ? [number(response.event_time_ms)] : []} />
        <TimelineLane label="Response identity" testId="timeline-response-identity-lane" values={text(response.queried_identity, "") ? [number(response.event_time_ms)] : []} />
      </div>
      <dl className="integration-evidence-list">
        <div><dt>Recording state</dt><dd>{recording.recording_active === true ? "Active" : "Not active"} · {text(recording.status)}</dd></div>
        <div><dt>Lower-right cue</dt><dd>{asObject(onset.participant_view).lower_right_cue_visible === true ? "Visible in participant view" : "Not visible in participant view"}</dd></div>
        <div data-testid="marker-count"><dt>Onset markers</dt><dd>{markers.length} at {markers.length ? markers.join(", ") : "no recorded time"} ms</dd></div>
        <div><dt>Response occurrence</dt><dd>{occurrence ? "Detected" : "Not detected"}</dd></div>
        <div><dt>Queried identity</dt><dd>{text(response.queried_identity)}</dd></div>
        <div><dt>Simulated press</dt><dd>{text(response.simulated_press)}</dd></div>
      </dl>
    </section>
  );
}

function TimelineLane({
  label,
  testId,
  values,
}: {
  label: string;
  testId: string;
  values: Array<number | null>;
}) {
  const present = values.filter((value): value is number => value !== null);
  return (
    <div className="timeline-lane" data-testid={testId}>
      <span>{label}</span>
      <div><i />{present.map((value, index) => (
        <b key={`${value}-${index}`} style={{ left: `${Math.max(2, Math.min(98, value / 10))}%` }} />
      ))}</div>
    </div>
  );
}

export function EegPreflightVisualization({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
}) {
  const [view, setView] = useState<"signals" | "integrations">("signals");
  if (environment.visualization.kind !== "eeg_preflight_v1") return null;
  const visualization = environment.visualization;
  const observation = run?.observation ?? {};
  const window = asObject(observation.eeg_window);
  const freshness = asObject(asObject(observation.evidence_freshness).eeg);
  return (
    <section
      aria-labelledby="eeg-diagnostics-title"
      className="visualization-card eeg-diagnostics"
      data-testid="eeg-diagnostic-visualization"
    >
      <div className="visualization-heading">
        <div>
          <p className="eyebrow">Policy-visible evidence</p>
          <h2 id="eeg-diagnostics-title">{visualization.title}</h2>
        </div>
        <span className="synthetic-label">{visualization.synthetic_label}</span>
      </div>
      {!run ? (
        <div className="diagnostic-empty">
          <p>Start the frozen scenario to reveal its deterministic synthetic evidence.</p>
        </div>
      ) : (
        <>
          <div className="evidence-toolbar">
            <div aria-label="Evidence view" className="evidence-tabs" role="tablist">
              <button aria-selected={view === "signals"} onClick={() => setView("signals")} role="tab" type="button">Signals</button>
              <button aria-selected={view === "integrations"} onClick={() => setView("integrations")} role="tab" type="button">Integrations</button>
            </div>
            <p data-testid="freshness-status">
              {text(window.evidence_id)} · state r{number(freshness.state_revision) ?? 0} · <strong>{text(window.status)}</strong>
            </p>
          </div>
          {view === "signals" ? (
            <SignalView
              observation={observation}
              visualization={visualization}
            />
          ) : (
            <IntegrationView observation={observation} />
          )}
          <div className="observation-strip">
            <span className="observation-icon" aria-hidden="true">i</span>
            <p><span>Latest observation</span>{text(observation.summary)}</p>
          </div>
        </>
      )}
    </section>
  );
}

export function eegPreflightTraceEvidence(event: TraceEvent): string | null {
  if (event.type === "action") {
    const arguments_ = Object.entries(event.action.arguments)
      .map(([name, value]) => `${name}=${String(value)}`)
      .join(" · ");
    return arguments_ || null;
  }
  if (event.type !== "observation") return null;
  const window = asObject(event.observation.eeg_window);
  const frequency = asObject(event.observation.frequency_evidence);
  const onset = asObject(event.observation.onset_evidence);
  const response = asObject(event.observation.response_evidence);
  const markers = numbers(onset.marker_times_ms);
  const parts = [
    Object.keys(window).length
      ? `${text(window.evidence_id)} · ${text(window.status)}`
      : null,
    Object.keys(frequency).length
      ? `frequency from ${text(frequency.source_window_id)}`
      : null,
    Object.keys(onset).length ? `${markers.length} onset marker${markers.length === 1 ? "" : "s"}` : null,
    Object.keys(response).length
      ? `response ${response.occurrence_detected === true ? "occurred" : "not detected"}`
      : null,
  ];
  return parts.filter((part): part is string => part !== null).join(" · ") || null;
}
