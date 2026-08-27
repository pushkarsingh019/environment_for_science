import type { JsonObject } from "../../types";
import { asObject, asObjects, booleanValue, finiteNumber, numberList, stringList, text } from "../../app/json";

export interface EegChannel {
  site: string;
  role: "required" | "optional";
  samples: number[];
  measurements: { range_uv: number; unique_value_count: number; rail_fraction: number; near_zero_fraction: number };
}

export interface EegWindow {
  evidence_id: string;
  status: "current" | "stale";
  display_sample_count: number;
  display_duration_seconds: number;
  display_sampling_hz: number;
  source_sampling_hz: number;
  channels: EegChannel[];
  reference: { site: string; samples: number[] };
  measurement_note: string;
  comparison_plan: { instruction: string; required_observations: string[] } | null;
}

export interface EegFrequency {
  source_window_id: string;
  status: string;
  bins_hz: number[];
  channels: Array<{ site: string; magnitudes: number[] }>;
  reference: { site: string; magnitudes: number[] };
  relationships: { pairwise: number; reference: number };
  measurement_note: string;
}

export interface EegOnset {
  evidence_id: string;
  status: string;
  flash_sequence: number;
  location: string;
  flash_time_ms: number;
  marker_times_ms: number[];
  cue_visible: boolean | undefined;
}

export interface EegResponse {
  evidence_id: string;
  status: string;
  simulated_press: string;
  occurrence_detected: boolean | undefined;
  queried_identity: string | null;
  event_time_ms: number | undefined;
}

export interface EegRecording {
  evidence_id: string;
  status: string;
  recording_active: boolean | undefined;
  timeline: { stimulus_ms?: number; marker_ms?: number; eeg_anchor_ms?: number; response_ms?: number };
}

export interface EegFreshness {
  evidence_id: string;
  status: "current" | "stale";
  state_revision: number;
  evidence_state_revision: number;
  applicable: boolean;
}

export type EegFreshnessDomain = "configuration" | "eeg" | "onset" | "response" | "recording";

export interface EegObservationView {
  /** false when the observation carries no `eeg_window`. */
  present: boolean;
  stage: string;
  summary: string;
  montage: { recording_sites: string[]; reference: string; ground: string; coordinate_note: string };
  configuration: {
    selected_sampling_hz?: number;
    observed_sampling_hz?: number;
    selected_reference?: string;
    observed_reference?: string;
    status?: string;
  } | null;
  window: EegWindow | null;
  frequency: EegFrequency | null;
  onset: EegOnset | null;
  response: EegResponse | null;
  recording: EegRecording | null;
  participant: { tension_reported: boolean | null; recent_instruction: string | null };
  environment: { shared_source_present: boolean | null };
  freshness: Partial<Record<EegFreshnessDomain, EegFreshness>>;
  acquisition: { state: string; completed_trials: number; planned_trials: number } | null;
}

export type ChannelClass = "nominal" | "constant" | "clipped" | "dropout" | "noisy";

export interface SceneHintLike {
  label: string;
  tone: "ok" | "attention" | "fault" | "stale";
}

/** Fixed rig vocabulary; never derived from hidden fields. */
export interface EegHints {
  channels: Record<string, SceneHintLike[]>;
  reference: SceneHintLike[];
  configuration: SceneHintLike[];
  onset: SceneHintLike[];
  response: SceneHintLike[];
  recording: SceneHintLike[];
  participant: SceneHintLike[];
}

const FRESHNESS_DOMAINS: readonly EegFreshnessDomain[] = ["configuration", "eeg", "onset", "response", "recording"];
const RAIL_THRESHOLD = 0.25;
const NEAR_ZERO_THRESHOLD = 0.25;
const NOISY_RANGE_RATIO = 2.5;
const SHARED_PAIRWISE_THRESHOLD = 0.85;
const SHARED_REFERENCE_THRESHOLD = 0.6;
const MARKER_LAG_LIMIT_MS = 20;

const freshnessStatus = (value: unknown): "current" | "stale" => (value === "stale" ? "stale" : "current");
const optionalString = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);
const hint = (label: string, tone: SceneHintLike["tone"]): SceneHintLike => ({ label, tone });

/** Fallback measurements when the runtime omits them; mirrors the backend derivation. */
function measureSamples(samples: number[]): EegChannel["measurements"] {
  if (samples.length === 0) return { range_uv: 0, unique_value_count: 0, rail_fraction: 0, near_zero_fraction: 0 };
  const peak = Math.max(...samples.map(Math.abs));
  const fraction = (test: (sample: number) => boolean) => samples.filter(test).length / samples.length;
  return {
    range_uv: Math.max(...samples) - Math.min(...samples),
    unique_value_count: new Set(samples).size,
    rail_fraction: fraction((sample) => Math.abs(Math.abs(sample) - peak) <= 1e-9),
    near_zero_fraction: fraction((sample) => Math.abs(sample) < 0.5),
  };
}

function readChannel(raw: JsonObject): EegChannel | null {
  const site = text(raw.site, "");
  if (site === "") return null;
  const samples = numberList(raw.samples);
  const measured = asObject(raw.measurements);
  const fallback = measureSamples(samples);
  return {
    site,
    role: raw.role === "optional" ? "optional" : "required",
    samples,
    measurements: {
      range_uv: finiteNumber(measured?.range_uv) ?? fallback.range_uv,
      unique_value_count: finiteNumber(measured?.unique_value_count) ?? fallback.unique_value_count,
      rail_fraction: finiteNumber(measured?.rail_fraction) ?? fallback.rail_fraction,
      near_zero_fraction: finiteNumber(measured?.near_zero_fraction) ?? fallback.near_zero_fraction,
    },
  };
}

function readWindow(raw: JsonObject | null): EegWindow | null {
  if (raw === null) return null;
  const channels = asObjects(raw.channels).map(readChannel).filter((channel): channel is EegChannel => channel !== null);
  const reference = asObject(raw.reference_comparison);
  const plan = asObject(raw.comparison_plan);
  return {
    evidence_id: text(raw.evidence_id),
    status: freshnessStatus(raw.status),
    display_sample_count: finiteNumber(raw.display_sample_count) ?? channels[0]?.samples.length ?? 0,
    display_duration_seconds: finiteNumber(raw.display_duration_seconds) ?? 0,
    display_sampling_hz: finiteNumber(raw.display_sampling_hz) ?? 0,
    source_sampling_hz: finiteNumber(raw.source_sampling_hz) ?? 0,
    channels,
    reference: { site: text(reference?.site, ""), samples: numberList(reference?.samples) },
    measurement_note: text(raw.measurement_note, ""),
    comparison_plan: plan
      ? { instruction: text(plan.instruction, ""), required_observations: stringList(plan.required_observations) }
      : null,
  };
}

function readFrequency(raw: JsonObject | null): EegFrequency | null {
  if (raw === null) return null;
  const reference = asObject(raw.reference_comparison);
  const relationships = asObject(raw.relationships);
  return {
    source_window_id: text(raw.source_window_id),
    status: text(raw.status, "current"),
    bins_hz: numberList(raw.bins_hz),
    channels: asObjects(raw.channels)
      .filter((channel) => typeof channel.site === "string")
      .map((channel) => ({ site: text(channel.site), magnitudes: numberList(channel.magnitudes) })),
    reference: { site: text(reference?.site, ""), magnitudes: numberList(reference?.magnitudes) },
    relationships: {
      pairwise: finiteNumber(relationships?.mean_absolute_pairwise_waveform_correlation) ?? 0,
      reference: finiteNumber(relationships?.mean_absolute_reference_waveform_correlation) ?? 0,
    },
    measurement_note: text(raw.measurement_note, ""),
  };
}

function readOnset(raw: JsonObject | null): EegOnset | null {
  if (raw === null) return null;
  return {
    evidence_id: text(raw.evidence_id),
    status: text(raw.status, "current"),
    flash_sequence: finiteNumber(raw.flash_sequence) ?? 0,
    location: text(raw.location, ""),
    flash_time_ms: finiteNumber(raw.flash_time_ms) ?? 0,
    marker_times_ms: numberList(raw.marker_times_ms),
    cue_visible: booleanValue(asObject(raw.participant_view)?.lower_right_cue_visible),
  };
}

function readResponse(raw: JsonObject | null): EegResponse | null {
  if (raw === null) return null;
  return {
    evidence_id: text(raw.evidence_id),
    status: text(raw.status, "current"),
    simulated_press: text(raw.simulated_press, ""),
    occurrence_detected: booleanValue(raw.occurrence_detected),
    queried_identity: optionalString(raw.queried_identity) ?? null,
    event_time_ms: finiteNumber(raw.event_time_ms),
  };
}

function readRecording(raw: JsonObject | null): EegRecording | null {
  if (raw === null) return null;
  const timeline = asObject(raw.timeline);
  return {
    evidence_id: text(raw.evidence_id),
    status: text(raw.status, "current"),
    recording_active: booleanValue(raw.recording_active),
    timeline: {
      stimulus_ms: finiteNumber(timeline?.stimulus_ms),
      marker_ms: finiteNumber(timeline?.marker_ms),
      eeg_anchor_ms: finiteNumber(timeline?.eeg_anchor_ms),
      response_ms: finiteNumber(timeline?.response_ms),
    },
  };
}

function readFreshness(raw: JsonObject | null): EegObservationView["freshness"] {
  const freshness: EegObservationView["freshness"] = {};
  for (const domain of FRESHNESS_DOMAINS) {
    const entry = asObject(raw?.[domain]);
    if (entry === null) continue;
    const stateRevision = finiteNumber(entry.state_revision) ?? 0;
    freshness[domain] = {
      evidence_id: text(entry.evidence_id),
      status: freshnessStatus(entry.status),
      state_revision: stateRevision,
      evidence_state_revision: finiteNumber(entry.evidence_state_revision) ?? stateRevision,
      applicable: booleanValue(entry.applicable) ?? true,
    };
  }
  return freshness;
}

function readConfiguration(raw: JsonObject | null): EegObservationView["configuration"] {
  if (raw === null) return null;
  return {
    selected_sampling_hz: finiteNumber(raw.selected_sampling_hz),
    observed_sampling_hz: finiteNumber(raw.observed_sampling_hz),
    selected_reference: optionalString(raw.selected_reference),
    observed_reference: optionalString(raw.observed_reference),
    status: optionalString(raw.status),
  };
}

/** Typed view over the untyped runtime observation; tolerates both EEG runtimes. */
export function readEegObservation(observation: JsonObject): EegObservationView {
  const stage = text(observation.stage, "");
  const montage = asObject(observation.montage);
  const participant = asObject(observation.participant_evidence);
  const environment = asObject(observation.environment_evidence);
  const acquisition = asObject(observation.acquisition);
  const window = readWindow(asObject(observation.eeg_window));
  return {
    present: window !== null,
    stage,
    summary: text(observation.summary, ""),
    montage: {
      recording_sites: stringList(montage?.recording_sites),
      reference: text(montage?.reference, ""),
      ground: text(montage?.ground, ""),
      coordinate_note: text(montage?.coordinate_note, "Schematic positions only."),
    },
    configuration: readConfiguration(asObject(observation.configuration_evidence)),
    window,
    frequency: readFrequency(asObject(observation.frequency_evidence)),
    onset: readOnset(asObject(observation.onset_evidence)),
    response: readResponse(asObject(observation.response_evidence)),
    recording: readRecording(asObject(observation.recording_evidence)),
    participant: {
      tension_reported: booleanValue(participant?.simulated_tension_reported) ?? null,
      recent_instruction: optionalString(participant?.recent_instruction) ?? null,
    },
    environment: { shared_source_present: booleanValue(environment?.shared_source_present) ?? null },
    freshness: readFreshness(asObject(observation.evidence_freshness)),
    acquisition: acquisition
      ? {
          state: text(acquisition.state, stage),
          completed_trials: finiteNumber(acquisition.completed_trials) ?? 0,
          planned_trials: finiteNumber(acquisition.planned_trials) ?? 0,
        }
      : null,
  };
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

/**
 * constant: a single distinct value; clipped: pinned at the rail; dropout: long near-zero gaps;
 * noisy: range well above the median range of the other channels; otherwise nominal.
 */
export function classifyChannel(channel: EegChannel, peers: EegChannel[]): ChannelClass {
  const { measurements } = channel;
  if (measurements.unique_value_count <= 1) return "constant";
  if (measurements.rail_fraction >= RAIL_THRESHOLD) return "clipped";
  if (measurements.near_zero_fraction >= NEAR_ZERO_THRESHOLD) return "dropout";
  const peerRanges = peers
    .filter((peer) => peer !== channel && peer.site !== channel.site)
    .map((peer) => peer.measurements.range_uv);
  const baseline = median(peerRanges.length > 0 ? peerRanges : [measurements.range_uv]);
  return baseline > 0 && measurements.range_uv > NOISY_RANGE_RATIO * baseline ? "noisy" : "nominal";
}

export function sharedSignal(view: EegObservationView): { shared: boolean; withReference: boolean } {
  const relationships = view.frequency?.relationships;
  return {
    shared:
      (relationships !== undefined && relationships.pairwise >= SHARED_PAIRWISE_THRESHOLD) ||
      view.environment.shared_source_present === true,
    withReference: relationships !== undefined && relationships.reference >= SHARED_REFERENCE_THRESHOLD,
  };
}

function isStale(view: EegObservationView, domain: EegFreshnessDomain, status: string | undefined): boolean {
  return view.freshness[domain]?.status === "stale" || status === "stale";
}

function channelHint(channelClass: ChannelClass, channel: EegChannel): SceneHintLike | null {
  const tone = channel.role === "required" ? "fault" : "attention";
  const { rail_fraction, near_zero_fraction } = channel.measurements;
  switch (channelClass) {
    case "constant":
      return hint("constant", tone);
    case "clipped":
      return hint(`at rail ${Math.round(rail_fraction * 100)}%`, tone);
    case "dropout":
      return hint(`near zero ${Math.round(near_zero_fraction * 100)}%`, tone);
    case "noisy":
      return hint("wide range", tone);
    case "nominal":
      return null;
  }
}

function channelHints(view: EegObservationView): Record<string, SceneHintLike[]> {
  const window = view.window;
  if (window === null) return {};
  const stale = isStale(view, "eeg", window.status);
  return Object.fromEntries(
    window.channels.map((channel) => {
      const classHint = channelHint(classifyChannel(channel, window.channels), channel);
      const hints = classHint ? [classHint] : [];
      if (stale) hints.push(hint("stale", "stale"));
      return [channel.site, hints];
    }),
  );
}

function configurationHints(view: EegObservationView): SceneHintLike[] {
  if (view.configuration === null) return [];
  const { selected_sampling_hz, observed_sampling_hz, selected_reference, observed_reference } = view.configuration;
  const hints: SceneHintLike[] = [];
  if (observed_sampling_hz !== undefined && selected_sampling_hz !== undefined && observed_sampling_hz !== selected_sampling_hz) {
    hints.push(hint(`${observed_sampling_hz} Hz observed`, "fault"));
  }
  if (observed_reference !== undefined && selected_reference !== undefined && observed_reference !== selected_reference) {
    hints.push(hint(`ref ${observed_reference}`, "fault"));
  }
  return hints;
}

function onsetHints(view: EegObservationView): SceneHintLike[] {
  const onset = view.onset;
  if (onset === null) return [];
  const hints: SceneHintLike[] = [];
  if (onset.cue_visible === true) hints.push(hint("cue visible", "attention"));
  if (onset.marker_times_ms.length === 0) hints.push(hint("no marker", "fault"));
  if (onset.marker_times_ms.length >= 2) hints.push(hint("×2", "attention"));
  if (isStale(view, "onset", onset.status)) hints.push(hint("stale", "stale"));
  return hints;
}

function responseHints(view: EegObservationView): SceneHintLike[] {
  const response = view.response;
  if (response === null) return [];
  const hints: SceneHintLike[] = [];
  if (response.occurrence_detected === true && response.queried_identity === null) hints.push(hint("no identity", "attention"));
  if (isStale(view, "response", response.status)) hints.push(hint("stale", "stale"));
  return hints;
}

function isMisaligned({ stimulus_ms, marker_ms, eeg_anchor_ms }: EegRecording["timeline"]): boolean {
  if (stimulus_ms === undefined) return false;
  const markerLate = marker_ms !== undefined && marker_ms - stimulus_ms > MARKER_LAG_LIMIT_MS;
  const anchorOff = eeg_anchor_ms !== undefined && eeg_anchor_ms !== stimulus_ms;
  return markerLate || anchorOff;
}

function recordingHints(view: EegObservationView): SceneHintLike[] {
  const recording = view.recording;
  if (recording === null) return [];
  const hints: SceneHintLike[] = [];
  if (recording.recording_active === false) hints.push(hint("not recording", "fault"));
  if (isMisaligned(recording.timeline)) hints.push(hint("misaligned", "attention"));
  if (isStale(view, "recording", recording.status)) hints.push(hint("stale", "stale"));
  return hints;
}

export function eegHints(view: EegObservationView): EegHints {
  return {
    channels: channelHints(view),
    reference: sharedSignal(view).withReference ? [hint("shared source", "attention")] : [],
    configuration: configurationHints(view),
    onset: onsetHints(view),
    response: responseHints(view),
    recording: recordingHints(view),
    participant: view.participant.tension_reported === true ? [hint("tension reported", "attention")] : [],
  };
}

/** Display role for a site; reference and ground take precedence over channel roles. */
export function channelDisplayRole(site: string, view: EegObservationView): "reference" | "ground" | "required" | "optional" {
  if (site === view.montage.reference) return "reference";
  if (site === view.montage.ground) return "ground";
  if (view.montage.recording_sites.includes(site)) return "required";
  const channel = view.window?.channels.find((candidate) => candidate.site === site);
  return channel?.role === "required" ? "required" : "optional";
}
