import type { ActionPreference } from "../app/studioTypes";

export type SceneTone = "idle" | "ok" | "attention" | "fault" | "stale" | "locked" | "active";
export type SceneLayoutMode = "edit" | "run" | "mobile";

export type GlyphId =
  | "monitor"
  | "head-participant"
  | "head-experimenter"
  | "headphones"
  | "response-box"
  | "splitter-box"
  | "amplifier"
  | "rack-processor"
  | "computer"
  | "cap-ring"
  | "profile-card"
  | "plan-map"
  | "gate"
  | "acquisition-rig"
  | "ledger"
  | "stamp";

export type EdgeKind =
  | "eeg"
  | "stimulus"
  | "marker"
  | "response"
  | "data"
  | "plan"
  | "acquisition"
  | "package"
  | "gate";

export interface ScenePoint {
  x: number;
  y: number;
}

export interface SceneZone {
  id: string;
  label: string;
  rect: Record<SceneLayoutMode, { x: number; y: number; w: number; h: number } | null>;
}

export interface SceneNodeSpec {
  id: string;
  label: string;
  glyph: GlyphId;
  size: Record<SceneLayoutMode, { w: number; h: number }>;
  /** Centre of the glyph box in viewBox units. */
  at: Record<SceneLayoutMode, ScenePoint>;
  /** false → the label is exposed only as `<title>`. */
  chip: boolean;
}

export interface SceneEdgeSpec {
  id: string;
  kind: EdgeKind;
  from: string;
  to: string;
  d: Record<SceneLayoutMode, string | null>;
  dashed: boolean;
}

export interface LegendEntry {
  kind: EdgeKind;
  label: string;
}

export interface SceneLayout {
  id: "eeg" | "mesoscope";
  viewBox: Record<SceneLayoutMode, { w: number; h: number }>;
  /** Polygon points for the floor plane, or null when the mode has no floor. */
  floor: Record<SceneLayoutMode, string | null>;
  zones: SceneZone[];
  nodes: SceneNodeSpec[];
  edges: SceneEdgeSpec[];
  legend: LegendEntry[];
}

export interface SceneHint {
  label: string;
  tone: SceneTone;
}

export interface SceneNodeState {
  tone: SceneTone;
  hints: SceneHint[];
  label?: string;
  preferred?: ActionPreference | null;
}

export interface SceneEdgeState {
  tone: SceneTone;
  live: boolean;
}

export interface SceneState {
  layout: SceneLayout;
  nodes: Record<string, SceneNodeState>;
  edges: Record<string, SceneEdgeState>;
  legend: LegendEntry[];
}

export const IDLE_NODE: SceneNodeState = { tone: "idle", hints: [] };
export const IDLE_EDGE: SceneEdgeState = { tone: "idle", live: false };
