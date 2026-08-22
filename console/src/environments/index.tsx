import type { EnvironmentSummary, RunSnapshot, TraceEvent } from "../types";
import {
  EegOnsetRouteVisualization,
  eegOnsetRouteTraceEvidence,
} from "./eeg/OnsetRouteVisualization";
import {
  EegPreflightVisualization,
  eegPreflightTraceEvidence,
} from "./eeg/PreflightVisualization";
import {
  MesoscopeHandoffVisualization,
  mesoscopeHandoffTraceEvidence,
} from "./mesoscope/MesoscopeHandoffVisualization";

type EnvironmentAdapter = {
  Visualization: (properties: {
    environment: EnvironmentSummary;
    run: RunSnapshot | null;
  }) => JSX.Element | null;
  traceEvidence: (event: TraceEvent) => string | null;
};

const environmentAdapters = {
  eeg_onset_route: {
    Visualization: EegOnsetRouteVisualization,
    traceEvidence: eegOnsetRouteTraceEvidence,
  },
  eeg_preflight_v1: {
    Visualization: EegPreflightVisualization,
    traceEvidence: eegPreflightTraceEvidence,
  },
  mesoscope_handoff_v1: {
    Visualization: MesoscopeHandoffVisualization,
    traceEvidence: mesoscopeHandoffTraceEvidence,
  },
} satisfies Record<
  EnvironmentSummary["visualization"]["kind"],
  EnvironmentAdapter
>;

function adapterFor(environment: EnvironmentSummary): EnvironmentAdapter {
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
