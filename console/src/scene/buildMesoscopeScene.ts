import type { Mode } from "../app/studioTypes";
import type { SceneHintLike } from "../environments/eeg/eegEvidence";
import { mesoscopeHints, type MesoscopeObservationView } from "../environments/mesoscope/mesoscopeEvidence";
import { MESOSCOPE_LAYOUT, MESOSCOPE_NODE_IDS, type MesoscopeNodeId } from "./mesoscopeLayout";
import {
  IDLE_EDGE,
  IDLE_NODE,
  type SceneEdgeState,
  type SceneNodeState,
  type SceneState,
  type SceneTone,
} from "./sceneModel";

export interface MesoscopeSceneInput {
  view: MesoscopeObservationView | null;
  mode: Mode;
  hasRun: boolean;
}

/** Action each bench station points at; disposition offers the first permitted decision. */
export const MESOSCOPE_NODE_ACTIONS: Record<MesoscopeNodeId, readonly string[]> = {
  profile: ["inspect_sealed_handoff"],
  plan: ["inspect_sealed_handoff"],
  gate: ["inspect_sealed_handoff"],
  acquisition: ["run_mock_acquisition"],
  package: ["validate_mock_package"],
  disposition: ["accept_mock_package", "quarantine_mock_package", "reject_mock_package"],
};

const LOCKED: SceneNodeState = { tone: "locked", hints: [] };
const ACTIVE_TONES: ReadonlySet<SceneTone> = new Set(["ok", "attention", "fault"]);

function nodeState(tone: SceneTone, hints: SceneHintLike[]): SceneNodeState {
  return { tone, hints: hints.map(({ label, tone: hintTone }) => ({ label, tone: hintTone })) };
}

function gateTone(view: MesoscopeObservationView): SceneTone {
  switch (view.safety_gate?.state) {
    case "closed":
      return "ok";
    case "open":
      return "fault";
    default:
      return "attention";
  }
}

function packageTone(view: MesoscopeObservationView): SceneTone {
  switch (view.validation_status) {
    case "valid":
      return "ok";
    case "invalid":
      return "fault";
    default:
      return "idle";
  }
}

/** Disposition tone follows the fixed vocabulary; the terminal status text is never echoed. */
function dispositionTone(view: MesoscopeObservationView): SceneTone {
  const terminal = view.terminal_status ?? "";
  if (terminal.includes("VERIFIED")) return "ok";
  if (terminal.includes("QUARANTINED")) return "attention";
  if (terminal.includes("REJECTED")) return "fault";
  return "idle";
}

function liveStates(view: MesoscopeObservationView): Pick<SceneState, "nodes" | "edges"> {
  const hints = mesoscopeHints(view);
  const nodes: Record<MesoscopeNodeId, SceneNodeState> = {
    profile: nodeState("locked", hints.profile),
    plan: nodeState("locked", hints.plan),
    gate: nodeState(gateTone(view), hints.gate),
    acquisition: nodeState(view.freshness.acquisition?.status === "current" ? "ok" : "idle", hints.acquisition),
    package: nodeState(packageTone(view), hints.package),
    disposition: nodeState(dispositionTone(view), hints.disposition),
  };
  const edges = Object.fromEntries(
    MESOSCOPE_LAYOUT.edges.map((edge) => {
      const downstream = nodes[edge.to as MesoscopeNodeId].tone;
      const state: SceneEdgeState = { tone: downstream, live: ACTIVE_TONES.has(downstream) };
      return [edge.id, state];
    }),
  );
  return { nodes, edges };
}

function sealedStates(): Pick<SceneState, "nodes" | "edges"> {
  return {
    nodes: Object.fromEntries(
      MESOSCOPE_NODE_IDS.map((id) => [id, id === "profile" || id === "plan" || id === "gate" ? LOCKED : IDLE_NODE]),
    ),
    edges: Object.fromEntries(MESOSCOPE_LAYOUT.edges.map((edge) => [edge.id, IDLE_EDGE])),
  };
}

/** Sealed contract stations stay locked; acquisition, package, and disposition follow the run evidence. */
export function buildMesoscopeScene({ view, hasRun }: MesoscopeSceneInput): SceneState {
  const base = { layout: MESOSCOPE_LAYOUT, legend: MESOSCOPE_LAYOUT.legend };
  if (view === null || !hasRun || !view.present) return { ...base, ...sealedStates() };
  return { ...base, ...liveStates(view) };
}
