import type { JsonObject } from "../../types";
import { asObject, asObjects, booleanValue, finiteNumber, stringList, text } from "../../app/json";
import type { SceneHintLike } from "../eeg/eegEvidence";

export type RegionId = "R1" | "R2" | "R3" | "R4";
export type ZLabel = "Z-A" | "Z-B";

export interface MesoTile {
  region_id: string;
  z_label: string;
  tile_seed: number;
  status: string;
}

export type MesoscopeFreshnessDomain = "safety" | "plan" | "acquisition" | "package";

export interface MesoscopeObservationView {
  /** false when the observation carries no sealed contract. */
  present: boolean;
  stage: string;
  summary: string;
  profile_catalog: Array<{ profile_id: string; provenance_label: string; selected: boolean }>;
  sealed_profile: { profile_id: string; source_geometry: string } | null;
  plan_catalog: Array<{ plan_id: string; signature_digest: string; selected: boolean }>;
  signed_plan: {
    plan_id: string;
    regions: Array<{ region_id: string; z_label: string; visit_order: number }>;
  } | null;
  safety_gate: { state: string; independently_enforced: boolean | undefined } | null;
  survey: { visual_seed: number | undefined; watermark: string } | null;
  expected_outputs: JsonObject[];
  region_tiles: MesoTile[];
  channel_records: JsonObject[];
  event_records: JsonObject[];
  motion_rows: JsonObject[];
  manifest_records: JsonObject[];
  package_checksums: JsonObject[];
  package_checks: Array<{ check_id: string; status: "match" | "mismatch" }>;
  validation_status: "not_run" | "valid" | "invalid" | string;
  detected_faults: string[];
  terminal_status: string | null;
  freshness: Partial<Record<MesoscopeFreshnessDomain, { evidence_id: string; status: string }>>;
}

export interface MesoscopeHints {
  profile: SceneHintLike[];
  plan: SceneHintLike[];
  gate: SceneHintLike[];
  acquisition: SceneHintLike[];
  package: SceneHintLike[];
  disposition: SceneHintLike[];
}

const FRESHNESS_DOMAINS: readonly MesoscopeFreshnessDomain[] = ["safety", "plan", "acquisition", "package"];
const DEFAULT_Z: ZLabel = "Z-A";
const TILE_POINT_COUNT = 20;

function readSignedPlan(raw: JsonObject | null): MesoscopeObservationView["signed_plan"] {
  if (raw === null) return null;
  return {
    plan_id: text(raw.plan_id),
    regions: asObjects(raw.regions).map((region) => ({
      region_id: text(region.region_id, ""),
      z_label: text(region.z_label, DEFAULT_Z),
      visit_order: finiteNumber(region.visit_order) ?? 0,
    })),
  };
}

function readTiles(raw: unknown): MesoTile[] {
  return asObjects(raw)
    .filter((tile) => typeof tile.region_id === "string")
    .map((tile) => ({
      region_id: text(tile.region_id),
      z_label: text(tile.z_label, DEFAULT_Z),
      tile_seed: finiteNumber(tile.tile_seed) ?? 0,
      status: text(tile.status, "present"),
    }));
}

function readFreshness(raw: JsonObject | null): MesoscopeObservationView["freshness"] {
  const freshness: MesoscopeObservationView["freshness"] = {};
  if (raw === null) return freshness;
  for (const domain of FRESHNESS_DOMAINS) {
    const entry = asObject(raw[domain]);
    if (entry === null) continue;
    freshness[domain] = { evidence_id: text(entry.evidence_id), status: text(entry.status, "unavailable") };
  }
  return freshness;
}

/** Typed view over the sealed mesoscope observation; every list defaults to empty. */
export function readMesoscopeObservation(observation: JsonObject): MesoscopeObservationView {
  const sealedProfile = asObject(observation.sealed_profile);
  const signedPlan = readSignedPlan(asObject(observation.signed_plan));
  const gate = asObject(observation.safety_gate);
  const survey = asObject(observation.survey);
  return {
    present: sealedProfile !== null || signedPlan !== null,
    stage: text(observation.stage, ""),
    summary: text(observation.summary, ""),
    profile_catalog: asObjects(observation.profile_catalog).map((entry) => ({
      profile_id: text(entry.profile_id),
      provenance_label: text(entry.provenance_label),
      selected: booleanValue(entry.selected) ?? false,
    })),
    sealed_profile: sealedProfile
      ? { profile_id: text(sealedProfile.profile_id), source_geometry: text(sealedProfile.source_geometry) }
      : null,
    plan_catalog: asObjects(observation.plan_catalog).map((entry) => ({
      plan_id: text(entry.plan_id),
      signature_digest: text(entry.signature_digest),
      selected: booleanValue(entry.selected) ?? false,
    })),
    signed_plan: signedPlan,
    safety_gate: gate
      ? { state: text(gate.state, "unknown"), independently_enforced: booleanValue(gate.independently_enforced) }
      : null,
    survey: survey
      ? { visual_seed: finiteNumber(survey.visual_seed), watermark: text(survey.watermark, "SYNTHETIC") }
      : null,
    expected_outputs: asObjects(observation.expected_outputs),
    region_tiles: readTiles(observation.region_tiles),
    channel_records: asObjects(observation.channel_records),
    event_records: asObjects(observation.event_records),
    motion_rows: asObjects(observation.motion_rows),
    manifest_records: asObjects(observation.manifest_records),
    package_checksums: asObjects(observation.package_checksums),
    package_checks: asObjects(observation.package_checks)
      .filter((check) => typeof check.check_id === "string")
      .map((check) => ({
        check_id: text(check.check_id),
        status: check.status === "mismatch" ? "mismatch" : "match",
      })),
    validation_status: text(observation.validation_status, "not_run"),
    detected_faults: stringList(observation.detected_faults),
    terminal_status: typeof observation.terminal_status === "string" ? observation.terminal_status : null,
    freshness: readFreshness(asObject(observation.evidence_freshness)),
  };
}

/** Planned depth for a region from the signed plan; "Z-A" when the plan is silent. */
export function expectedZ(view: MesoscopeObservationView, regionId: string): string {
  const planned = view.signed_plan?.regions.find((region) => region.region_id === regionId);
  return planned?.z_label ?? DEFAULT_Z;
}

export function tileFor(view: MesoscopeObservationView, regionId: string): MesoTile | undefined {
  return view.region_tiles.find((tile) => tile.region_id === regionId);
}

/** Park–Miller minimal-standard generator; draw order per point is x, y, radius, opacity. */
export function deterministicPoints(seed: number): Array<{
  x: number;
  y: number;
  radius: number;
  opacity: number;
}> {
  let state = Math.abs(Math.trunc(seed)) || 1;
  const next = () => {
    state = (state * 48271) % 2147483647;
    return state / 2147483647;
  };
  return Array.from({ length: TILE_POINT_COUNT }, () => ({
    x: 8 + next() * 84,
    y: 8 + next() * 84,
    radius: 2.5 + next() * 6.5,
    opacity: 0.24 + next() * 0.46,
  }));
}

function hint(label: string, tone: SceneHintLike["tone"]): SceneHintLike {
  return { label, tone };
}

function gateHint(view: MesoscopeObservationView): SceneHintLike {
  switch (view.safety_gate?.state) {
    case "closed":
      return hint("closed", "ok");
    case "open":
      return hint("open", "fault");
    default:
      return hint("unknown", "attention");
  }
}

function acquisitionHint(view: MesoscopeObservationView): SceneHintLike {
  const outputs = view.channel_records.length;
  return outputs > 0 ? hint(`${outputs} outputs`, "ok") : hint("not run", "stale");
}

function packageHint(view: MesoscopeObservationView): SceneHintLike {
  switch (view.validation_status) {
    case "valid":
      return hint("valid", "ok");
    case "invalid": {
      const faults = view.detected_faults.join(", ");
      return hint(faults === "" ? "invalid" : `invalid · ${faults}`, "fault");
    }
    default:
      return hint("not run", "stale");
  }
}

/** Disposition wording is fixed vocabulary; the terminal status text itself is never echoed. */
function dispositionHint(view: MesoscopeObservationView): SceneHintLike {
  const terminal = view.terminal_status ?? "";
  if (terminal.includes("VERIFIED")) return hint("verified", "ok");
  if (terminal.includes("QUARANTINED")) return hint("quarantined", "attention");
  if (terminal.includes("REJECTED")) return hint("rejected", "fault");
  return hint("pending", "stale");
}

export function mesoscopeHints(view: MesoscopeObservationView): MesoscopeHints {
  return {
    profile: [hint("locked", "ok")],
    plan: [hint("locked", "ok")],
    gate: [gateHint(view)],
    acquisition: [acquisitionHint(view)],
    package: [packageHint(view)],
    disposition: [dispositionHint(view)],
  };
}
