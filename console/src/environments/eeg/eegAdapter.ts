import { createElement } from "react";
import { asObject, numberList, text } from "../../app/json";
import type { ActionPreference, BarCounters } from "../../app/studioTypes";
import { buildEegScene } from "../../scene/buildEegScene";
import { EEG_LAYOUT } from "../../scene/eegLayout";
import type { SceneState } from "../../scene/sceneModel";
import type { EnvironmentDraft, TraceEvent } from "../../types";
import type { DocksProps, EnvironmentAdapter, SceneInput } from "../adapter";
import { readEegObservation } from "./eegEvidence";
import { EegRunDocks } from "./EegRunDocks";
import { EegOnsetRouteVisualization, eegOnsetRouteTraceEvidence } from "./OnsetRouteVisualization";

/** Edit-mode counters need the draft montage; P-integrate passes it alongside the scene input. */
export type EegCountersInput = SceneInput & { draft?: EnvironmentDraft | null };

const NOT_OBSERVED = "Not observed";
const SCENE_TITLE = { title: "Sound chamber", subtitle: "spatial view", badge: "SIMULATION" } as const;

const NODE_ACTIONS: Readonly<Record<string, string>> = {
  display: "inspect_onset_route",
  headphones: "inspect_onset_route",
  participant: "inspect_participant_state",
  response: "inspect_response_timeline",
  cap: "inspect_eeg_signals",
  sbox: "inspect_eeg_signals",
  pz5: "inspect_configuration",
  computer: "inspect_configuration",
  rz6: "inspect_recording_timeline",
};

function actionCount(input: SceneInput): number {
  return input.run === null ? 0 : input.run.trace.filter((event) => event.type === "action").length;
}

function eegCounters(input: EegCountersInput): BarCounters {
  const checks = input.environment.validation.checks.length;
  const parts = EEG_LAYOUT.nodes.length;
  if (input.mode === "edit") {
    return { parts, steps: input.draft?.procedure.montage.recording_sites.length ?? 0, stepsLabel: "sites", checks };
  }
  return { parts, steps: actionCount(input), stepsLabel: "actions", checks };
}

function buildScene(input: SceneInput): SceneState {
  return buildEegScene({
    view: input.run === null ? null : readEegObservation(input.run.observation),
    mode: input.mode,
    hasRun: input.run !== null,
  });
}

function preferredActionForNode(nodeId: string, input: SceneInput): ActionPreference | null {
  const type = NODE_ACTIONS[nodeId];
  if (type === undefined || input.run === null || !input.run.permitted_actions.includes(type)) return null;
  return { type };
}

/** Ported from the retired PreflightVisualization: argument pairs for actions, evidence facts for observations. */
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
  const markers = numberList(onset?.marker_times_ms);
  const parts = [
    window ? `${text(window.evidence_id, NOT_OBSERVED)} · ${text(window.status, NOT_OBSERVED)}` : null,
    frequency ? `frequency from ${text(frequency.source_window_id, NOT_OBSERVED)}` : null,
    onset ? `${markers.length} onset marker${markers.length === 1 ? "" : "s"}` : null,
    response ? `response ${response.occurrence_detected === true ? "occurred" : "not detected"}` : null,
  ];
  return parts.filter((part): part is string => part !== null).join(" · ") || null;
}

export const eegAdapter: EnvironmentAdapter = {
  kind: "eeg_preflight_v1",
  buildScene,
  sceneTitle: () => SCENE_TITLE,
  EditDocks: null,
  RunDocks: EegRunDocks,
  traceEvidence: eegPreflightTraceEvidence,
  counters: eegCounters,
  preferredActionForNode,
};

function OnsetRouteDocks({ environment, run }: DocksProps): JSX.Element {
  return createElement(
    "section",
    { className: "scene-docks eeg-drawer" },
    createElement(EegOnsetRouteVisualization, { environment, run }),
  );
}

/** Legacy onset-route bundles keep their card-style visualization inside the scene docks. */
export const eegOnsetRouteAdapter: EnvironmentAdapter = {
  kind: "eeg_onset_route",
  buildScene: (input) => buildEegScene({ view: null, mode: input.mode, hasRun: input.run !== null }),
  sceneTitle: () => SCENE_TITLE,
  EditDocks: null,
  RunDocks: OnsetRouteDocks,
  traceEvidence: eegOnsetRouteTraceEvidence,
  counters: (input) => ({
    parts: EEG_LAYOUT.nodes.length,
    steps: actionCount(input),
    stepsLabel: "actions",
    checks: input.environment.validation.checks.length,
  }),
  preferredActionForNode: () => null,
};
