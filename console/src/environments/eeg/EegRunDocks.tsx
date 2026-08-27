import { useState } from "react";
import type { EegPreflightVisualization } from "../../types";
import type { DocksProps } from "../adapter";
import { readEegObservation, type EegObservationView } from "./eegEvidence";
import { FrequencyPanel } from "./FrequencyPanel";
import { IntegrationTimeline } from "./IntegrationTimeline";
import { MontageLens } from "./MontageLens";
import type { Gain } from "./signalRender";
import { GhostPaper, TracePaper } from "./TracePaper";

type EvidenceTab = "signals" | "integrations";

const TABS: ReadonlyArray<readonly [EvidenceTab, string]> = [
  ["signals", "Signals"],
  ["integrations", "Integrations"],
];

/** EEG evidence drawer docked under the scene viewport; ghost paper until a run starts. */
export function EegRunDocks({ environment, run, onPreferAction }: DocksProps): JSX.Element | null {
  const [tab, setTab] = useState<EvidenceTab>("signals");
  const [gain, setGain] = useState<Gain>(1);
  const visualization = environment.visualization;
  if (visualization.kind !== "eeg_preflight_v1") return null;
  const view = run === null ? null : readEegObservation(run.observation);

  return (
    <section aria-labelledby="eeg-diagnostics-title" className="scene-docks eeg-drawer" data-testid="eeg-diagnostic-visualization">
      <h2 className="sr-only" id="eeg-diagnostics-title">
        {visualization.title}
      </h2>
      <span className="sr-only">{visualization.synthetic_label}</span>
      {view === null || view.window === null ? (
        <>
          <GhostPaper />
          <p className="scene-caption">Start the run to see live evidence.</p>
        </>
      ) : (
        <>
          <div className="evidence-toolbar">
            <div aria-label="Evidence view" className="evidence-tabs" role="tablist">
              {TABS.map(([id, label]) => (
                <button
                  aria-controls={`evidence-panel-${id}`}
                  aria-selected={tab === id}
                  id={`evidence-tab-${id}`}
                  key={id}
                  onClick={() => setTab(id)}
                  role="tab"
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="freshness-status" data-testid="freshness-status">
              {view.window.evidence_id} · state r{view.freshness.eeg?.state_revision ?? 0} · <strong>{view.window.status}</strong>
            </p>
          </div>
          <div aria-labelledby={`evidence-tab-${tab}`} id={`evidence-panel-${tab}`} role="tabpanel">
            {tab === "signals" ? (
              <SignalsPanel
                gain={gain}
                onGain={setGain}
                onSite={(site) => onPreferAction({ type: "reseat_electrode", values: { site } })}
                view={view}
                visualization={visualization}
              />
            ) : (
              <IntegrationTimeline view={view} />
            )}
          </div>
          <p className="observation-strip">
            <span>Latest</span>
            {view.summary}
          </p>
        </>
      )}
    </section>
  );
}

interface SignalsPanelProps {
  view: EegObservationView;
  visualization: EegPreflightVisualization;
  gain: Gain;
  onGain: (gain: Gain) => void;
  onSite: (site: string) => void;
}

function SignalsPanel({ view, visualization, gain, onGain, onSite }: SignalsPanelProps): JSX.Element {
  return (
    <div className="diagnostic-signal-layout">
      <div className="diagnostic-plots">
        <TracePaper gain={gain} onGain={onGain} view={view} visualization={visualization} />
        <FrequencyPanel view={view} visualization={visualization} />
      </div>
      <MontageLens onSiteActivate={onSite} variant="run" view={view} visualization={visualization} />
    </div>
  );
}
