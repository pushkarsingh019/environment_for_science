import type { MesoscopeHandoffVisualization } from "../../types";
import { expectedZ, tileFor, type MesoscopeObservationView } from "./mesoscopeEvidence";
import { ProceduralTile } from "./ProceduralTile";

export interface SurveyPhantomProps {
  view: MesoscopeObservationView;
  visualization: MesoscopeHandoffVisualization;
}

/** Cached procedural phantom (fixed geometry; the seed is displayed only) plus the four region tiles. */
export function SurveyPhantom({ view, visualization }: SurveyPhantomProps): JSX.Element {
  const seed = view.survey?.visual_seed;
  const watermark = view.survey?.watermark ?? "Unavailable";

  return (
    <figure className="mesoscope-survey" data-testid="mesoscope-survey">
      <figcaption>
        <span>{visualization.survey_label}</span>
        <small>
          {watermark} · seed {seed ?? "Unavailable"}
        </small>
      </figcaption>
      <div
        aria-label="Deterministic non-biological procedural phantom with four planned regions."
        className="mesoscope-survey-field"
        role="img"
      >
        <svg aria-hidden="true" viewBox="0 0 320 210">
          <path className="mesoscope-survey-path is-a" d="M-10 120 C55 12, 94 192, 160 74 S266 26, 340 104" />
          <path
            className="mesoscope-survey-path is-b"
            d="M44 -10 C77 58, 64 130, 10 220 M162 -5 C200 60, 190 132, 246 220"
          />
          <path className="mesoscope-survey-path is-c" d="M-10 55 C76 92, 86 24, 176 43 S264 166, 340 138" />
        </svg>
        {visualization.region_ids.map((regionId) => (
          <span className={`mesoscope-survey-region is-${regionId.toLowerCase()}`} key={regionId}>
            <strong>{regionId}</strong>
            <small>{expectedZ(view, regionId)}</small>
          </span>
        ))}
        <span className="mesoscope-watermark">SYNTHETIC PHANTOM</span>
      </div>
      <div className="mesoscope-tiles-heading">
        <span>{visualization.spatial_view_label}</span>
        <small>{visualization.raw_view_label} · deterministic procedural render</small>
      </div>
      <div className="mesoscope-tile-grid">
        {visualization.region_ids.map((regionId) => (
          <ProceduralTile
            expectedZ={expectedZ(view, regionId)}
            key={regionId}
            regionId={regionId}
            tile={tileFor(view, regionId)}
          />
        ))}
      </div>
    </figure>
  );
}
