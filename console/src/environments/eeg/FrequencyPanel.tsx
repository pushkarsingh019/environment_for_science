import type { EegPreflightVisualization } from "../../types";
import { channelDisplayRole, type EegFrequency, type EegObservationView } from "./eegEvidence";
import { PAPER, channelColor, paperHeight, rowCenterY, rowRailY, sampleX, spectrumPath } from "./signalRender";

const LABEL_X = PAPER.plotX0 - 12;

interface FrequencyPanelProps {
  view: EegObservationView;
  visualization: EegPreflightVisualization;
}

/** Disclosure that re-opens whenever frequency evidence arrives for a new window (keyed remount). */
export function FrequencyPanel({ view, visualization }: FrequencyPanelProps): JSX.Element {
  const frequency = view.frequency;
  return (
    <details
      className="frequency-disclosure"
      data-testid="frequency-disclosure"
      key={frequency?.source_window_id ?? "none"}
      open={frequency !== null}
    >
      <summary>{visualization.details_toggle_label}</summary>
      {frequency === null ? (
        <p>Choose “View frequency evidence” to record measurements from this window.</p>
      ) : (
        <FrequencyFigure frequency={frequency} label={visualization.frequency_panel_label} view={view} />
      )}
    </details>
  );
}

interface FrequencyFigureProps {
  frequency: EegFrequency;
  label: string;
  view: EegObservationView;
}

function FrequencyFigure({ frequency, label, view }: FrequencyFigureProps): JSX.Element {
  const referenceRow = frequency.channels.length;
  const height = paperHeight(referenceRow + 1);
  const maximum = Math.max(
    1,
    ...frequency.channels.flatMap((channel) => channel.magnitudes),
    ...frequency.reference.magnitudes,
  );
  const referenceColour = channelColor(0, "reference");
  return (
    <figure
      aria-label={`${label}: synthetic measurements at ${frequency.bins_hz.join(", ")} hertz from window ${frequency.source_window_id}.`}
      className="frequency-figure"
    >
      <svg
        aria-hidden="true"
        className="frequency-paper"
        preserveAspectRatio="none"
        style={{ aspectRatio: `${PAPER.viewWidth} / ${height}` }}
        viewBox={`0 0 ${PAPER.viewWidth} ${height}`}
      >
        {frequency.bins_hz.map((bin, index) => {
          const x = sampleX(index, frequency.bins_hz.length);
          return (
            <g key={bin}>
              <line className="trace-rule is-major" x1={x} x2={x} y1={PAPER.topPad} y2={height - PAPER.bottomPad} />
              <text className="trace-axis" textAnchor="middle" x={x} y={height - 4}>
                {bin} Hz
              </text>
            </g>
          );
        })}
        {frequency.channels.map((channel, index) => {
          const role = channelDisplayRole(channel.site, view) === "optional" ? "optional" : "required";
          return (
            <SpectrumRow
              colour={channelColor(index, role)}
              key={channel.site}
              label={channel.site}
              magnitudes={channel.magnitudes}
              maximum={maximum}
              rowIndex={index}
              testId={`frequency-channel-${channel.site}`}
            />
          );
        })}
        <SpectrumRow
          colour={referenceColour}
          label={`${frequency.reference.site} ref`}
          magnitudes={frequency.reference.magnitudes}
          maximum={maximum}
          reference
          rowIndex={referenceRow}
          testId={`frequency-reference-${frequency.reference.site}`}
        />
      </svg>
      <p className="frequency-bins">Bins: {frequency.bins_hz.map((bin) => `${bin} Hz`).join(" · ")}</p>
      <dl className="frequency-relationships">
        <div>
          <dt>Mean absolute pairwise channel correlation</dt>
          <dd>{frequency.relationships.pairwise.toFixed(3)}</dd>
        </div>
        <div>
          <dt>Mean absolute correlation with {frequency.reference.site} reference comparison</dt>
          <dd>{frequency.relationships.reference.toFixed(3)}</dd>
        </div>
      </dl>
      <p className="measurement-note">{frequency.measurement_note}</p>
    </figure>
  );
}

interface SpectrumRowProps {
  colour: string;
  label: string;
  magnitudes: number[];
  maximum: number;
  reference?: boolean;
  rowIndex: number;
  testId: string;
}

function SpectrumRow({ colour, label, magnitudes, maximum, reference = false, rowIndex, testId }: SpectrumRowProps): JSX.Element {
  const baseline = rowRailY(rowIndex).bottom;
  const path = spectrumPath(magnitudes, rowIndex, maximum);
  return (
    <g data-testid={testId}>
      <line className="trace-baseline" x1={PAPER.plotX0} x2={PAPER.plotX1} y1={baseline} y2={baseline} />
      <text className="trace-site-label" dominantBaseline="middle" style={{ fill: colour }} textAnchor="end" x={LABEL_X} y={rowCenterY(rowIndex)}>
        {label}
      </text>
      <path className={`frequency-waveform${reference ? " frequency-reference-waveform" : ""}`} d={path} style={{ stroke: colour }} />
      {magnitudes.map((magnitude, index) => (
        <circle
          className="frequency-bin"
          cx={sampleX(index, magnitudes.length)}
          cy={baseline - (magnitude / maximum) * (PAPER.rowHeight - 12)}
          key={index}
          r={3}
          style={{ fill: colour }}
        />
      ))}
    </g>
  );
}
