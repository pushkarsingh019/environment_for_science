import type { EnvironmentSummary, RunSnapshot, TraceEvent } from "../types";
import {
  EegOnsetRouteVisualization,
  eegOnsetRouteTraceEvidence,
} from "./eeg/OnsetRouteVisualization";

const environmentAdapters = {
  eeg_onset_route: {
    Visualization: EegOnsetRouteVisualization,
    traceEvidence: eegOnsetRouteTraceEvidence,
  },
};

function adapterFor(environment: EnvironmentSummary) {
  return environmentAdapters[environment.visualization.kind];
}

export function EnvironmentVisualization({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
}) {
  const { Visualization } = adapterFor(environment);
  return <Visualization environment={environment} run={run} />;
}

export function environmentTraceEvidence(
  environment: EnvironmentSummary,
  event: TraceEvent,
): string | null {
  return adapterFor(environment).traceEvidence(event);
}
