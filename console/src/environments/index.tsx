import type { EnvironmentSummary, TraceEvent } from "../types";
import type { EnvironmentAdapter } from "./adapter";
import { eegAdapter, eegOnsetRouteAdapter } from "./eeg/eegAdapter";
import { mesoscopeAdapter } from "./mesoscope/mesoscopeAdapter";

/** One adapter per bundle visualization kind; the union is exhaustive by construction. */
export const environmentAdapters = {
  eeg_onset_route: eegOnsetRouteAdapter,
  eeg_preflight_v1: eegAdapter,
  mesoscope_handoff_v1: mesoscopeAdapter,
} satisfies Record<EnvironmentSummary["visualization"]["kind"], EnvironmentAdapter>;

export function adapterFor(environment: EnvironmentSummary): EnvironmentAdapter {
  return environmentAdapters[environment.visualization.kind];
}

export function environmentTraceEvidence(
  environment: EnvironmentSummary,
  event: TraceEvent,
): string | null {
  return adapterFor(environment).traceEvidence(event);
}
