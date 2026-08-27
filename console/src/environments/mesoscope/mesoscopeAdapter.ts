import { createElement } from "react";
import type { EnvironmentSummary } from "../../types";
import type { ActionPreference, BarCounters } from "../../app/studioTypes";
import { buildMesoscopeScene } from "../../scene/buildMesoscopeScene";
import type { EnvironmentAdapter, SceneInput } from "../adapter";
import { readMesoscopeObservation } from "./mesoscopeEvidence";
import { MesoscopeRunDocks, mesoscopeHandoffTraceEvidence, mesoscopeVisualization } from "./MesoscopeRunDocks";

const SCENE_PARTS = 6;
const PLANNED_REGIONS = 4;
const DISPOSITION_ACTIONS = ["accept_mock_package", "quarantine_mock_package", "reject_mock_package"] as const;

const NODE_ACTIONS: Readonly<Record<string, string>> = {
  profile: "inspect_sealed_handoff",
  plan: "inspect_sealed_handoff",
  gate: "inspect_sealed_handoff",
  acquisition: "run_mock_acquisition",
  package: "validate_mock_package",
};

function preferredActionForNode(nodeId: string, { run }: SceneInput): ActionPreference | null {
  if (run === null) return null;
  const permitted = run.permitted_actions;
  const type =
    nodeId === "disposition"
      ? DISPOSITION_ACTIONS.find((candidate) => permitted.includes(candidate))
      : NODE_ACTIONS[nodeId];
  return type !== undefined && permitted.includes(type) ? { type } : null;
}

function counters({ environment, run, mode }: SceneInput): BarCounters {
  const checks = environment.validation.checks.length;
  if (mode === "run") {
    const steps = run === null ? 0 : run.trace.filter((event) => event.type === "action").length;
    return { parts: SCENE_PARTS, steps, stepsLabel: "actions", checks };
  }
  return { parts: SCENE_PARTS, steps: PLANNED_REGIONS, stepsLabel: "regions", checks };
}

/** Single boundary line under the scene header: sealed label and simulation label together. */
export function MesoscopeBoundaryNote({ environment }: { environment: EnvironmentSummary }): JSX.Element {
  const sealedLabel = mesoscopeVisualization(environment)?.sealed_label ?? "SEALED";
  return createElement(
    "p",
    { className: "scene-boundary", "data-testid": "mesoscope-safety-boundary", role: "note" },
    createElement("strong", null, sealedLabel),
    ` · ${environment.simulation_label}`,
  );
}

export const mesoscopeAdapter: EnvironmentAdapter = {
  kind: "mesoscope_handoff_v1",
  buildScene({ run, mode }) {
    return buildMesoscopeScene({
      view: run === null ? null : readMesoscopeObservation(run.observation),
      mode,
      hasRun: run !== null,
    });
  },
  sceneTitle({ environment }) {
    return {
      title: "Sealed handoff",
      subtitle: "spatial view",
      badge: mesoscopeVisualization(environment)?.synthetic_label ?? "SIMULATION",
    };
  },
  EditDocks: null,
  RunDocks: MesoscopeRunDocks,
  traceEvidence: mesoscopeHandoffTraceEvidence,
  counters,
  preferredActionForNode,
};
