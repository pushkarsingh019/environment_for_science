import type { DraftSite, EegPreflightVisualization, EnvironmentDraft, ScalpSitePresentation } from "../../types";
import { channelDisplayRole, classifyChannel, type EegObservationView } from "./eegEvidence";

type SiteActivate = (siteId: string) => void;

type MontageLensProps =
  | { variant: "edit"; draft: EnvironmentDraft; onSiteActivate?: SiteActivate }
  | { variant: "run"; view: EegObservationView; visualization: EegPreflightVisualization; onSiteActivate?: SiteActivate };

type EditRole = "recording" | "reference" | "ground" | "available";

const EDIT_LEGEND: ReadonlyArray<readonly [EditRole, string]> = [
  ["recording", "Recording"],
  ["reference", "Reference"],
  ["ground", "Ground"],
  ["available", "Apparatus site"],
];

/** Whole-cap lens (Edit) or the run-time Procedure Montage with per-site evidence tones. */
export function MontageLens(props: MontageLensProps): JSX.Element {
  return props.variant === "edit" ? (
    <EditLens draft={props.draft} onSiteActivate={props.onSiteActivate} />
  ) : (
    <RunLens onSiteActivate={props.onSiteActivate} view={props.view} visualization={props.visualization} />
  );
}

function editRole(site: DraftSite, draft: EnvironmentDraft): EditRole {
  const { montage } = draft.procedure;
  if (site.id === montage.reference) return "reference";
  if (site.id === montage.ground) return "ground";
  return montage.recording_sites.includes(site.id) ? "recording" : "available";
}

function EditLens({ draft, onSiteActivate }: { draft: EnvironmentDraft; onSiteActivate?: SiteActivate }): JSX.Element {
  const sites = draft.apparatus.sites;
  return (
    <div className="cap-lens">
      <div
        aria-label={`Configurable whole-cap EEG Apparatus with ${sites.length} possible sites and a distinct Procedure-selected Montage.`}
        className="whole-cap-map"
        data-testid="whole-cap-visualization"
        role="img"
      >
        <span aria-hidden="true" className="head-nasion" />
        <span aria-hidden="true" className="head-ear head-ear-left" />
        <span aria-hidden="true" className="head-ear head-ear-right" />
        {sites.map((site) => {
          const role = editRole(site, draft);
          return (
            <span
              aria-label={`${site.label}: ${role} site`}
              className={`cap-site is-${role} is-${site.kind}`}
              data-testid={`apparatus-site-${site.id}`}
              key={site.id}
              onClick={onSiteActivate && (() => onSiteActivate(site.id))}
              style={{ left: `${site.x}%`, top: `${site.y}%` }}
              title={`${site.label} · ${role}`}
            >
              {site.label}
            </span>
          );
        })}
      </div>
      <ul aria-label="Whole-cap legend" className="cap-legend">
        {EDIT_LEGEND.map(([role, label]) => (
          <li key={role}>
            <i aria-hidden="true" className={`legend-dot is-${role}`} />
            {label}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface RunLensProps {
  view: EegObservationView;
  visualization: EegPreflightVisualization;
  onSiteActivate?: SiteActivate;
}

function siteTone(site: ScalpSitePresentation, view: EegObservationView): "ok" | "attention" | "fault" | undefined {
  const channels = view.window?.channels ?? [];
  const channel = channels.find((candidate) => candidate.site === site.id);
  if (channel === undefined) return undefined;
  if (classifyChannel(channel, channels) === "nominal") return "ok";
  return channel.role === "required" ? "fault" : "attention";
}

function RunLens({ view, visualization, onSiteActivate }: RunLensProps): JSX.Element {
  const { montage } = view;
  const shown = new Set([...(view.window?.channels.map((channel) => channel.site) ?? []), montage.reference, montage.ground]);
  return (
    <figure
      aria-label={`Schematic Procedure Montage: recording ${montage.recording_sites.join(", ")}; reference ${montage.reference}; ground ${montage.ground}.`}
      className="diagnostic-montage"
      data-testid="eeg-montage"
    >
      <figcaption>{visualization.montage_panel_label}</figcaption>
      <div className="diagnostic-head">
        <span aria-hidden="true" className="diagnostic-nasion" />
        {visualization.scalp_sites
          .filter((site) => shown.has(site.id))
          .map((site) => {
            const role = channelDisplayRole(site.id, view);
            return (
              <span
                className={`diagnostic-site is-${role}`}
                data-role={role}
                data-testid={`montage-site-${site.id}`}
                data-tone={siteTone(site, view)}
                key={site.id}
                onClick={() => onSiteActivate?.(site.id)}
                role="button"
                style={{ left: `${site.x}%`, top: `${site.y}%` }}
                tabIndex={-1}
                title={`${site.id} · ${role}`}
              >
                {site.id}
              </span>
            );
          })}
      </div>
      <p>{montage.coordinate_note}</p>
    </figure>
  );
}
