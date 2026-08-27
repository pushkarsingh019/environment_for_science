import type { LegendEntry } from "./sceneModel";

export interface SceneLegendProps {
  entries: LegendEntry[];
}

/** Signal-path key, anchored inside the viewport. */
export function SceneLegend(props: SceneLegendProps): JSX.Element | null {
  const { entries } = props;
  if (entries.length === 0) return null;

  return (
    <ul className="scene-legend" aria-label="Signal legend">
      {entries.map((entry) => (
        <li key={entry.kind}>
          <span className={`legend-swatch edge--${entry.kind}`} aria-hidden="true" />
          {entry.label}
        </li>
      ))}
    </ul>
  );
}
