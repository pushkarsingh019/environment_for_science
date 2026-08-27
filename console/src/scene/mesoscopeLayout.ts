import type { EdgeKind, GlyphId, SceneEdgeSpec, SceneLayout, SceneNodeSpec } from "./sceneModel";

export const MESOSCOPE_NODE_IDS = ["profile", "plan", "gate", "acquisition", "package", "disposition"] as const;

export type MesoscopeNodeId = (typeof MESOSCOPE_NODE_IDS)[number];

type Box = readonly [w: number, h: number];
type Point = readonly [x: number, y: number];

function node(
  id: MesoscopeNodeId,
  label: string,
  glyph: GlyphId,
  size: { edit: Box; run: Box; mobile: Box },
  at: { edit: Point; run: Point; mobile: Point },
): SceneNodeSpec {
  return {
    id,
    label,
    glyph,
    size: {
      edit: { w: size.edit[0], h: size.edit[1] },
      run: { w: size.run[0], h: size.run[1] },
      mobile: { w: size.mobile[0], h: size.mobile[1] },
    },
    at: {
      edit: { x: at.edit[0], y: at.edit[1] },
      run: { x: at.run[0], y: at.run[1] },
      mobile: { x: at.mobile[0], y: at.mobile[1] },
    },
    chip: true,
  };
}

function edge(
  id: string,
  kind: EdgeKind,
  from: MesoscopeNodeId,
  to: MesoscopeNodeId,
  d: { edit: string; run: string },
): SceneEdgeSpec {
  return { id, kind, from, to, d: { edit: d.edit, run: d.run, mobile: null }, dashed: true };
}

/** Sealed bench. Six stations joined by the plan, acquisition, and package routes. */
export const MESOSCOPE_LAYOUT: SceneLayout = {
  id: "mesoscope",
  viewBox: { edit: { w: 1440, h: 880 }, run: { w: 1440, h: 520 }, mobile: { w: 720, h: 980 } },
  floor: { edit: "120,330 1320,330 1400,760 320,760", run: null, mobile: null },
  zones: [
    {
      id: "bench",
      label: "SEALED BENCH",
      rect: {
        edit: { x: 120, y: 90, w: 1200, h: 560 },
        run: { x: 110, y: 40, w: 1220, h: 340 },
        mobile: { x: 40, y: 40, w: 640, h: 700 },
      },
    },
  ],
  nodes: [
    node(
      "profile",
      "Sealed profile",
      "profile-card",
      { edit: [180, 130], run: [140, 100], mobile: [180, 130] },
      { edit: [300, 250], run: [220, 160], mobile: [180, 140] },
    ),
    node(
      "plan",
      "Signed plan",
      "plan-map",
      { edit: [220, 160], run: [170, 124], mobile: [220, 160] },
      { edit: [640, 250], run: [520, 160], mobile: [540, 140] },
    ),
    node(
      "gate",
      "Safety gate",
      "gate",
      { edit: [150, 130], run: [116, 100], mobile: [150, 130] },
      { edit: [980, 250], run: [820, 160], mobile: [180, 360] },
    ),
    node(
      "acquisition",
      "Mock acquisition",
      "acquisition-rig",
      { edit: [220, 150], run: [170, 116], mobile: [220, 150] },
      { edit: [420, 560], run: [400, 380], mobile: [540, 360] },
    ),
    node(
      "package",
      "Package",
      "ledger",
      { edit: [180, 140], run: [140, 108], mobile: [180, 140] },
      { edit: [800, 560], run: [760, 380], mobile: [180, 580] },
    ),
    node(
      "disposition",
      "Disposition",
      "stamp",
      { edit: [150, 130], run: [116, 100], mobile: [150, 130] },
      { edit: [1150, 560], run: [1120, 330], mobile: [540, 580] },
    ),
  ],
  edges: [
    edge("e-plan", "plan", "plan", "acquisition", {
      edit: "M 640 335 C 640 450, 460 450, 440 485",
      run: "M 520 225 C 520 300, 420 300, 410 322",
    }),
    edge("e-gate", "gate", "gate", "acquisition", {
      edit: "M 960 320 C 900 460, 620 500, 535 545",
      run: "M 790 215 C 740 320, 560 350, 490 365",
    }),
    edge("e-acq", "acquisition", "acquisition", "package", { edit: "M 535 560 L 705 560", run: "M 490 380 L 685 380" }),
    edge("e-package", "package", "package", "disposition", { edit: "M 895 560 L 1070 560", run: "M 835 380 C 920 380, 990 336, 1060 332" }),
  ],
  legend: [
    { kind: "plan", label: "plan" },
    { kind: "acquisition", label: "acquisition" },
    { kind: "package", label: "package" },
  ],
};
