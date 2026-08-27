import type {
  ComparisonMetrics,
  ComparisonModelResult,
  ModelComparisonResult,
  PairedBootstrapAnalysis,
} from "../types";
import { percent, signedPercent } from "../app/format";

const AXIS_X0 = 200;
const AXIS_W = 480;
const ROW_Y0 = 34;
const ROW_H = 44;
const DIFF_Y = 250;
const STRATA = ["individual", "ambiguous", "pair", "triple"] as const;
const AXIS_TICKS = [0, 0.25, 0.5, 0.75, 1];

const ROLE_FILL: Record<ComparisonModelResult["role"], string> = {
  base_gemma: "#7fb3ea",
  trained_gemma: "var(--blue)",
  openai_reference: "#c9c5bf",
  gemini_reference: "#c9c5bf",
};

const CONCLUSION_FILL: Record<PairedBootstrapAnalysis["conclusion"], string> = {
  improved: "var(--green)",
  regressed: "var(--red)",
  inconclusive: "#8a8580",
};

function successX(value: number): number {
  return AXIS_X0 + value * AXIS_W;
}

/** −50 % … +50 % maps onto the same 480-unit axis, zero at x = 440. */
function differenceX(value: number): number {
  return AXIS_X0 + AXIS_W / 2 + value * AXIS_W;
}

function modelKind(model: ComparisonModelResult): string {
  return model.reference_model ? "Reference model" : "Gemma evidence";
}

function ModelRow({ model, index }: { model: ComparisonModelResult; index: number }) {
  const y = ROW_Y0 + index * ROW_H;
  const metrics = model.metrics;
  return (
    <g className="chart-row" data-role={model.role}>
      <text className="chart-label" x={8} y={y}>{model.label}</text>
      <text className="chart-sub" x={8} y={y + 14}>
        {modelKind(model)} · {model.requested_model}
      </text>
      {metrics ? (
        <AvailableBar metrics={metrics} role={model.role} y={y} />
      ) : (
        <>
          <rect x={AXIS_X0} y={y - 12} width={AXIS_W} height={18} rx={3} fill="url(#chart-hatch)" />
          <text className="chart-unavailable" x={AXIS_X0 + 8} y={y}>
            {model.failure ? `unavailable · ${model.failure.category}` : "unavailable"}
          </text>
        </>
      )}
    </g>
  );
}

function AvailableBar({
  metrics,
  role,
  y,
}: {
  metrics: ComparisonMetrics;
  role: ComparisonModelResult["role"];
  y: number;
}) {
  const width = metrics.task_success * AXIS_W;
  const end = AXIS_X0 + width;
  const inside = end + 56 > AXIS_X0 + AXIS_W;
  return (
    <>
      <rect x={AXIS_X0} y={y - 12} width={width} height={18} rx={3} fill={ROLE_FILL[role]} />
      <text
        className={inside ? "chart-value chart-value--inside" : "chart-value"}
        x={inside ? end - 8 : end + 8}
        y={y}
        textAnchor={inside ? "end" : "start"}
      >
        {percent(metrics.task_success)}
      </text>
      {STRATA.map((name) => {
        const stratum = metrics.strata[name];
        if (stratum.task_success === null) return null;
        return (
          <rect
            className="chart-stratum"
            height={6}
            key={name}
            width={6}
            x={successX(stratum.task_success) - 3}
            y={y + 9}
          >
            <title>{`${name} · ${stratum.count} · ${percent(stratum.task_success)}`}</title>
          </rect>
        );
      })}
    </>
  );
}

function DifferenceRow({ contrast }: { contrast: PairedBootstrapAnalysis | null }) {
  const cy = DIFF_Y - 4;
  const label = contrast
    ? `${signedPercent(contrast.trained_minus_base)} [${signedPercent(contrast.interval_low)}, ${signedPercent(contrast.interval_high)}]`
    : "unavailable";
  const labelLeft = contrast !== null && differenceX(contrast.interval_high) > AXIS_X0 + AXIS_W - 150;
  return (
    <g className="chart-row chart-row--difference">
      <text className="chart-label" x={8} y={DIFF_Y}>Trained − base</text>
      <text className="chart-sub" x={8} y={DIFF_Y + 14}>backend paired bootstrap, 95%</text>
      <line className="chart-zero" x1={differenceX(0)} x2={differenceX(0)} y1={cy - 18} y2={cy + 18} />
      {contrast && (
        <>
          <line
            className="chart-whisker"
            strokeWidth={2}
            x1={differenceX(contrast.interval_low)}
            x2={differenceX(contrast.interval_high)}
            y1={cy}
            y2={cy}
          />
          <line className="chart-whisker" x1={differenceX(contrast.interval_low)} x2={differenceX(contrast.interval_low)} y1={cy - 4} y2={cy + 4} />
          <line className="chart-whisker" x1={differenceX(contrast.interval_high)} x2={differenceX(contrast.interval_high)} y1={cy - 4} y2={cy + 4} />
          <circle cx={differenceX(contrast.trained_minus_base)} cy={cy} fill={CONCLUSION_FILL[contrast.conclusion]} r={5} />
        </>
      )}
      <text
        className="chart-value"
        textAnchor={labelLeft ? "end" : "start"}
        x={contrast
          ? (labelLeft ? differenceX(contrast.interval_low) - 10 : differenceX(contrast.interval_high) + 10)
          : AXIS_X0 + 8}
        y={DIFF_Y}
      >
        {label}
      </text>
      {[-0.5, 0, 0.5].map((value) => (
        <text className="chart-axis" key={value} textAnchor="middle" x={differenceX(value)} y={DIFF_Y + 34}>
          {value === 0 ? "0" : signedPercent(value).replace(".0", "")}
        </text>
      ))}
    </g>
  );
}

function AccessibleTable({ comparison }: { comparison: ModelComparisonResult }) {
  const contrast = comparison.gemma_contrast;
  return (
    <div className="sr-only">
      <table>
      <caption>Task success of four models on the held-out scenarios</caption>
      <thead>
        <tr>
          <th scope="col">Model</th><th scope="col">Task success</th>
          {STRATA.map((name) => <th key={name} scope="col">{name}</th>)}
          <th scope="col">Verifier score</th><th scope="col">Abort precision</th>
          <th scope="col">Abort recall</th><th scope="col">Mean actions</th><th scope="col">Tool errors</th>
        </tr>
      </thead>
      <tbody>
        {comparison.models.map((model) => (
          <tr key={model.role}>
            <th scope="row">{model.label}</th>
            {model.metrics ? (
              <>
                <td>{percent(model.metrics.task_success)}</td>
                {STRATA.map((name) => {
                  const stratum = model.metrics?.strata[name];
                  return <td key={name}>{stratum ? percent(stratum.task_success) : "Not estimable"}</td>;
                })}
                <td>{percent(model.metrics.verifier_score)}</td>
                <td>{percent(model.metrics.abort_precision)}</td>
                <td>{percent(model.metrics.abort_recall)}</td>
                <td>{model.metrics.mean_action_count.toFixed(1)}</td>
                <td>{model.metrics.tool_errors}</td>
              </>
            ) : (
              <td colSpan={10}>{model.failure ? `unavailable · ${model.failure.category}` : "unavailable"}</td>
            )}
          </tr>
        ))}
        <tr>
          <th scope="row">Trained − base</th>
          <td colSpan={10}>
            {contrast
              ? `${signedPercent(contrast.trained_minus_base)}, 95% interval ${signedPercent(contrast.interval_low)} to ${signedPercent(contrast.interval_high)} (backend paired bootstrap)`
              : "unavailable"}
          </td>
        </tr>
      </tbody>
      </table>
    </div>
  );
}

/** Results poster: four point-estimate bars plus the backend paired-bootstrap difference row. */
export function ComparisonChart({ comparison }: { comparison: ModelComparisonResult }): JSX.Element {
  return (
    <div className="comparison-chart-figure">
      <svg
        aria-label="Task success of four models on 64 held-out scenarios, with the trained-minus-base difference and its 95% interval"
        className="comparison-chart"
        role="img"
        viewBox="0 0 720 300"
      >
        <defs>
          <pattern height={6} id="chart-hatch" patternTransform="rotate(45)" patternUnits="userSpaceOnUse" width={6}>
            <rect fill="#f4f2ef" height={6} width={6} />
            <line stroke="#d8d5d1" strokeWidth={2} x1={0} x2={0} y1={0} y2={6} />
          </pattern>
        </defs>
        {AXIS_TICKS.map((tick) => (
          <g key={tick}>
            <text className="chart-axis" textAnchor="middle" x={successX(tick)} y={14}>
              {`${tick * 100}%`}
            </text>
            <line className="chart-grid" x1={successX(tick)} x2={successX(tick)} y1={20} y2={204} />
          </g>
        ))}
        {comparison.models.map((model, index) => (
          <ModelRow index={index} key={model.role} model={model} />
        ))}
        <line className="chart-separator" x1={8} x2={712} y1={214} y2={214} />
        <DifferenceRow contrast={comparison.gemma_contrast} />
      </svg>
      <AccessibleTable comparison={comparison} />
      <p className="comparison-chart-caption">
        Bars are point estimates of task success over the 64 held-out scenarios; small ticks
        mark the individual, ambiguous, pair and triple strata. Only the difference row
        carries an interval: the backend paired bootstrap, 95%.
      </p>
    </div>
  );
}
