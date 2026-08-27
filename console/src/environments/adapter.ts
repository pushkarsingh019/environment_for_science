import type { ComponentType } from "react";
import type { EnvironmentDraft, EnvironmentSummary, RunSnapshot, TraceEvent } from "../types";
import type { ActionPreference, BarCounters, Mode } from "../app/studioTypes";
import type { SceneState } from "../scene/sceneModel";

export interface SceneInput {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
  mode: Mode;
}

/** Counters may consult the editable draft, which is not part of the scene input. */
export interface CountersInput extends SceneInput {
  draft?: EnvironmentDraft | null;
}

export interface DocksProps {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
  busy: boolean;
  onPreferAction: (preference: ActionPreference) => void;
}

export interface EnvironmentAdapter {
  kind: EnvironmentSummary["visualization"]["kind"];
  buildScene(input: SceneInput): SceneState;
  sceneTitle(input: SceneInput): { title: string; subtitle: string; badge: string };
  /** EEG: cap lens rendered in the viewport dock slot; mesoscope: null. */
  EditDocks: ComponentType<DocksProps> | null;
  /** Rendered in the docks slot in Run mode only. */
  RunDocks: ComponentType<DocksProps>;
  traceEvidence(event: TraceEvent): string | null;
  counters(input: CountersInput): BarCounters;
  preferredActionForNode(nodeId: string, input: SceneInput): ActionPreference | null;
}
