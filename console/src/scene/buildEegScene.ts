import type { Mode } from "../app/studioTypes";
import {
  classifyChannel,
  eegHints,
  sharedSignal,
  type EegChannel,
  type EegFreshnessDomain,
  type EegObservationView,
  type SceneHintLike,
} from "../environments/eeg/eegEvidence";
import { EEG_LAYOUT, EEG_NODE_IDS, type EegNodeId } from "./eegLayout";
import {
  IDLE_EDGE,
  IDLE_NODE,
  type LegendEntry,
  type SceneEdgeState,
  type SceneHint,
  type SceneNodeState,
  type SceneState,
  type SceneTone,
} from "./sceneModel";

export interface EegSceneInput {
  view: EegObservationView | null;
  mode: Mode;
  hasRun: boolean;
}

/** Action each apparatus node points at; the adapter checks `permitted_actions` before offering it. */
export const EEG_NODE_ACTIONS: Record<EegNodeId, string | null> = {
  display: "inspect_onset_route",
  headphones: "inspect_onset_route",
  participant: "inspect_participant_state",
  response: "inspect_response_timeline",
  cap: "inspect_eeg_signals",
  sbox: "inspect_eeg_signals",
  pz5: "inspect_configuration",
  computer: "inspect_configuration",
  rz6: "inspect_recording_timeline",
  experimenter: null,
};

const RUN_LEGEND: LegendEntry[] = [...EEG_LAYOUT.legend, { kind: "response", label: "response" }];
const POLICY_AGENT_LABEL = "Policy agent";
const MAX_HINTS = 2;
const SEVERITY: Record<SceneTone, number> = { idle: 0, ok: 1, locked: 1, active: 1, stale: 2, attention: 3, fault: 4 };

const isCurrent = (view: EegObservationView, domain: EegFreshnessDomain): boolean =>
  view.freshness[domain]?.status === "current";
const isStale = (view: EegObservationView, domain: EegFreshnessDomain): boolean =>
  view.freshness[domain]?.status === "stale";

function worst(tones: SceneTone[]): SceneTone {
  return tones.reduce<SceneTone>((acc, tone) => (SEVERITY[tone] > SEVERITY[acc] ? tone : acc), "ok");
}

/** Node tone from its hint tones, falling back to the domain freshness; idle when nothing is known. */
function toneFor(view: EegObservationView, domain: EegFreshnessDomain, hints: SceneHintLike[], known: boolean): SceneTone {
  if (!known && view.freshness[domain] === undefined) return "idle";
  if (hints.length > 0) return worst(hints.map((entry) => entry.tone));
  return isStale(view, domain) ? "stale" : "ok";
}

function nodeState(tone: SceneTone, hints: SceneHintLike[], label?: string): SceneNodeState {
  const trimmed: SceneHint[] = hints.slice(0, MAX_HINTS).map(({ label: text, tone: hintTone }) => ({ label: text, tone: hintTone }));
  return label === undefined ? { tone, hints: trimmed } : { tone, hints: trimmed, label };
}

function edgeState(tone: SceneTone, live: boolean): SceneEdgeState {
  return { tone, live };
}

/** Cap and splitter box share the montage evidence: channel problems first, then shared source, then staleness. */
function montageState(view: EegObservationView, channelHints: Record<string, SceneHintLike[]>): SceneNodeState {
  const window = view.window;
  if (window === null) return nodeState(toneFor(view, "eeg", [], false), []);
  const shared = sharedSignal(view);
  const classes = new Map(window.channels.map((channel) => [channel.site, classifyChannel(channel, window.channels)]));
  const problem = (role: EegChannel["role"]) =>
    window.channels.some((channel) => channel.role === role && classes.get(channel.site) !== "nominal");
  const hints: SceneHintLike[] = window.channels.flatMap((channel) =>
    (channelHints[channel.site] ?? [])
      .filter((entry) => entry.tone !== "stale")
      .map((entry) => ({ label: `${channel.site} ${entry.label}`, tone: entry.tone })),
  );
  if (shared.shared) hints.push({ label: "shared source", tone: "attention" });
  const stale = isStale(view, "eeg") || window.status === "stale";
  if (stale) hints.push({ label: "stale", tone: "stale" });
  const tone: SceneTone =
    problem("required") || shared.shared ? "fault" : problem("optional") ? "attention" : stale ? "stale" : "ok";
  return nodeState(tone, hints);
}

function liveStates(view: EegObservationView): Pick<SceneState, "nodes" | "edges"> {
  const hints = eegHints(view);
  const montage = montageState(view, hints.channels);
  const configurationTone: SceneTone =
    hints.configuration.length > 0 ? "fault" : toneFor(view, "configuration", [], view.configuration !== null);
  const displayTone = toneFor(view, "onset", hints.onset, view.onset !== null);
  const responseTone = toneFor(view, "response", hints.response, view.response !== null);
  const recordingTone = toneFor(view, "recording", hints.recording, view.recording !== null);
  const nodes: Record<EegNodeId, SceneNodeState> = {
    display: nodeState(displayTone, hints.onset),
    headphones: nodeState(displayTone, []),
    participant: nodeState(hints.participant.length > 0 ? "attention" : "ok", hints.participant),
    response: nodeState(responseTone, hints.response),
    cap: nodeState(montage.tone, []),
    sbox: montage,
    pz5: nodeState(configurationTone, hints.configuration),
    rz6: nodeState(recordingTone, hints.recording),
    computer: nodeState(view.acquisition === null ? "idle" : "ok", []),
    experimenter: nodeState("active", [], POLICY_AGENT_LABEL),
  };
  const edges: Record<string, SceneEdgeState> = {
    "e-cap": edgeState(montage.tone, isCurrent(view, "eeg")),
    "e-eeg": edgeState(montage.tone, isCurrent(view, "eeg")),
    "e-stimulus": edgeState(displayTone, isCurrent(view, "onset")),
    "e-marker": edgeState(displayTone, isCurrent(view, "onset")),
    "e-response": edgeState(responseTone, isCurrent(view, "response")),
    "e-data": edgeState(recordingTone, isCurrent(view, "recording")),
  };
  return { nodes, edges };
}

function idleStates(): Pick<SceneState, "nodes" | "edges"> {
  return {
    nodes: Object.fromEntries(EEG_NODE_IDS.map((id) => [id, IDLE_NODE])),
    edges: Object.fromEntries(EEG_LAYOUT.edges.map((edge) => [edge.id, IDLE_EDGE])),
  };
}

/**
 * Derives node tones, hint pills, and edge liveness from the Policy-visible observation only.
 * Without a run every station idles; with a run the experimenter seat becomes the Policy agent.
 */
export function buildEegScene({ view, mode, hasRun }: EegSceneInput): SceneState {
  const legend = mode === "run" ? RUN_LEGEND : EEG_LAYOUT.legend;
  if (view === null || !hasRun) return { layout: EEG_LAYOUT, legend, ...idleStates() };
  if (!view.present) {
    const idle = idleStates();
    return {
      layout: EEG_LAYOUT,
      legend,
      nodes: { ...idle.nodes, experimenter: nodeState("active", [], POLICY_AGENT_LABEL) },
      edges: idle.edges,
    };
  }
  return { layout: EEG_LAYOUT, legend, ...liveStates(view) };
}
