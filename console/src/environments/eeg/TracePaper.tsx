import type { EegPreflightVisualization } from "../../types";
import { classifyChannel, eegHints, type EegChannel, type EegObservationView, type EegWindow, type SceneHintLike } from "./eegEvidence";
import {
  GAIN_STEPS,
  PAPER,
  channelColor,
  nearZeroSpans,
  paperHeight,
  rowCenterY,
  rowRailY,
  sampleX,
  timeTicks,
  tracePath,
  type Gain,
} from "./signalRender";

const CONSTANT_COLOUR = "#9a9691";
const LABEL_X = PAPER.plotX0 - 12;
const HINT_X = PAPER.plotX1 - 6;
const GHOST_RULES = 5;

interface TracePaperProps {
  view: EegObservationView;
  visualization: EegPreflightVisualization;
  gain: Gain;
  onGain: (gain: Gain) => void;
}

/** Ruled EEG paper with one tall row per channel, a reference row, and a repeating logical sweep. */
export function TracePaper({ view, visualization, gain, onGain }: TracePaperProps): JSX.Element {
  const window = view.window;
  if (window === null) return <GhostPaper />;
  const freshness = view.freshness.eeg;
  const stateRevision = freshness?.state_revision ?? 0;
  const evidenceRevision = freshness?.evidence_state_revision ?? stateRevision;
  const hints = eegHints(view).channels;
  const height = paperHeight(window.channels.length + 1);
  const sites = window.channels.map((channel) => channel.site).join(", ");
  const referenceSite = window.reference.site;

  return (
    <figure
      aria-label={`Synthetic EEG window ${window.evidence_id} with ${sites} and reference comparison ${referenceSite}; ${window.display_sample_count} displayed samples per trace; evidence is ${window.status}.`}
      className={`trace-figure is-${window.status}`}
      data-evidence-revision={evidenceRevision}
      data-state-revision={stateRevision}
      data-testid="eeg-trace-window"
      data-window-id={window.evidence_id}
    >
      <figcaption>
        <span>{visualization.trace_panel_label}</span>
        <small>
          {window.display_sample_count} points · {window.display_duration_seconds.toFixed(1)} s display · repeating logical sweep
        </small>
      </figcaption>
      <svg
        aria-hidden="true"
        className="trace-paper"
        preserveAspectRatio="none"
        style={{ aspectRatio: `${PAPER.viewWidth} / ${height}` }}
        viewBox={`0 0 ${PAPER.viewWidth} ${height}`}
      >
        <PaperRules duration={window.display_duration_seconds} height={height} />
        {window.channels.map((channel, index) => (
          <ChannelRow
            channel={channel}
            gain={gain}
            hints={hints[channel.site] ?? []}
            index={index}
            key={channel.site}
            peers={window.channels}
          />
        ))}
        <g data-sample-count={window.reference.samples.length} data-testid={`trace-reference-${referenceSite}`}>
          <RowFrame colour={channelColor(0, "reference")} label={`${referenceSite} ref`} rowIndex={window.channels.length} />
          <path
            className="trace-waveform trace-reference-waveform"
            d={tracePath(window.reference.samples, window.channels.length, gain)}
            style={{ stroke: channelColor(0, "reference") }}
          />
        </g>
        <line
          className="trace-logical-sweep"
          data-testid="trace-logical-sweep"
          x1={PAPER.plotX0}
          x2={PAPER.plotX0}
          y1={8}
          y2={height - 8}
        />
      </svg>
      <GainControl gain={gain} onGain={onGain} />
      <MeasurementsTable window={window} />
      <p className="measurement-note">{window.measurement_note}</p>
    </figure>
  );
}

function PaperRules({ duration, height }: { duration: number; height: number }): JSX.Element {
  const top = PAPER.topPad;
  const bottom = height - PAPER.bottomPad;
  return (
    <g className="trace-rules">
      {timeTicks(duration).map((tick) => (
        <g key={tick.x}>
          <line className={`trace-rule${tick.label ? " is-major" : ""}`} x1={tick.x} x2={tick.x} y1={top} y2={bottom} />
          {tick.label && (
            <text className="trace-axis" textAnchor="middle" x={tick.x} y={height - 4}>
              {tick.label}
            </text>
          )}
        </g>
      ))}
    </g>
  );
}

function RowFrame({ colour, label, rowIndex }: { colour: string; label: string; rowIndex: number }): JSX.Element {
  const centre = rowCenterY(rowIndex);
  return (
    <>
      <line className="trace-baseline" x1={PAPER.plotX0} x2={PAPER.plotX1} y1={centre} y2={centre} />
      <text className="trace-site-label" dominantBaseline="middle" style={{ fill: colour }} textAnchor="end" x={LABEL_X} y={centre}>
        {label}
      </text>
    </>
  );
}

interface ChannelRowProps {
  channel: EegChannel;
  index: number;
  gain: Gain;
  peers: EegChannel[];
  hints: SceneHintLike[];
}

function ChannelRow({ channel, index, gain, peers, hints }: ChannelRowProps): JSX.Element {
  const channelClass = classifyChannel(channel, peers);
  const colour = channelClass === "constant" ? CONSTANT_COLOUR : channelColor(index, channel.role);
  const rails = rowRailY(index);
  const hintText = hints.map((hint) => hint.label).join(" · ");
  return (
    <g
      data-channel-class={channelClass}
      data-hint={hintText || undefined}
      data-role={channel.role}
      data-sample-count={channel.samples.length}
      data-testid={`trace-channel-${channel.site}`}
    >
      <RowFrame colour={colour} label={channel.site} rowIndex={index} />
      {channelClass === "clipped" && (
        <>
          <line className="trace-rail" x1={PAPER.plotX0} x2={PAPER.plotX1} y1={rails.top} y2={rails.top} />
          <line className="trace-rail" x1={PAPER.plotX0} x2={PAPER.plotX1} y1={rails.bottom} y2={rails.bottom} />
        </>
      )}
      {channelClass === "dropout" &&
        nearZeroSpans(channel.samples).map((span) => {
          const x0 = sampleX(span.start, channel.samples.length);
          const x1 = sampleX(span.end - 1, channel.samples.length);
          return (
            <rect className="trace-gap" height={rails.bottom - rails.top} key={span.start} width={x1 - x0} x={x0} y={rails.top} />
          );
        })}
      <path className="trace-waveform" d={tracePath(channel.samples, index, gain)} style={{ stroke: colour }} />
      {hints.length > 0 && (
        <text className="trace-hint" data-tone={hints[0].tone} textAnchor="end" x={HINT_X} y={rails.top - 2}>
          {hintText}
        </text>
      )}
    </g>
  );
}

function GainControl({ gain, onGain }: { gain: Gain; onGain: (gain: Gain) => void }): JSX.Element {
  return (
    <div aria-label="Trace gain" className="paper-gain" role="group">
      {GAIN_STEPS.map((step) => (
        <button aria-pressed={gain === step} key={step} onClick={() => onGain(step)} type="button">
          ×{step}
        </button>
      ))}
    </div>
  );
}

function MeasurementsTable({ window }: { window: EegWindow }): JSX.Element {
  return (
    <div className="sr-only">
      <table className="evidence-table">
      <caption>Measurements derived from the displayed synthetic samples</caption>
      <thead>
        <tr>
          <th>Channel</th>
          <th>Role</th>
          <th>Range</th>
          <th>Unique values</th>
          <th>Rail fraction</th>
        </tr>
      </thead>
      <tbody>
        {window.channels.map((channel) => (
          <tr key={channel.site}>
            <th>{channel.site}</th>
            <td>{channel.role}</td>
            <td>{channel.measurements.range_uv}</td>
            <td>{channel.measurements.unique_value_count}</td>
            <td>{channel.measurements.rail_fraction}</td>
          </tr>
        ))}
        <tr>
          <th>{window.reference.site}</th>
          <td>reference comparison</td>
          <td colSpan={3}>{window.reference.samples.length} displayed samples</td>
        </tr>
      </tbody>
      </table>
    </div>
  );
}

/** Pre-run placeholder: blank ruled paper with no evidence attributes. */
export function GhostPaper(): JSX.Element {
  return (
    <div aria-hidden="true" className="trace-figure is-ghost">
      {Array.from({ length: GHOST_RULES }, (_, index) => (
        <span className="ghost-rule" key={index} />
      ))}
    </div>
  );
}
