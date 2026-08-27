import type { EdgeKind, GlyphId, SceneEdgeSpec, SceneLayout, SceneNodeSpec } from "./sceneModel";

export const EEG_NODE_IDS = [
  "display",
  "participant",
  "headphones",
  "response",
  "cap",
  "sbox",
  "pz5",
  "rz6",
  "computer",
  "experimenter",
] as const;

export type EegNodeId = (typeof EEG_NODE_IDS)[number];

type Box = readonly [w: number, h: number];
type Point = readonly [x: number, y: number];

function node(
  id: EegNodeId,
  label: string,
  glyph: GlyphId,
  size: { edit: Box; run: Box; mobile: Box },
  at: { edit: Point; run: Point; mobile: Point },
  chip = true,
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
    chip,
  };
}

function edge(
  id: string,
  kind: EdgeKind,
  from: EegNodeId,
  to: EegNodeId,
  d: { edit: string; run: string },
  dashed = true,
): SceneEdgeSpec {
  return { id, kind, from, to, d: { edit: d.edit, run: d.run, mobile: null }, dashed };
}

/** Sound-chamber apparatus. Coordinates are viewBox units; `at` is the glyph-box centre. */
export const EEG_LAYOUT: SceneLayout = {
  id: "eeg",
  viewBox: { edit: { w: 1440, h: 880 }, run: { w: 1440, h: 520 }, mobile: { w: 720, h: 1040 } },
  floor: { edit: "100,260 1340,260 1420,640 330,640", run: null, mobile: null },
  zones: [
    {
      id: "chamber",
      label: "SOUND CHAMBER",
      rect: {
        edit: { x: 203, y: 75, w: 1163, h: 447 },
        run: { x: 190, y: 40, w: 1260, h: 330 },
        mobile: { x: 40, y: 40, w: 640, h: 560 },
      },
    },
  ],
  nodes: [
    node(
      "display",
      "Display",
      "monitor",
      { edit: [200, 130], run: [150, 98], mobile: [200, 130] },
      { edit: [366, 204], run: [300, 150], mobile: [180, 140] },
    ),
    node(
      "participant",
      "Participant",
      "head-participant",
      { edit: [150, 170], run: [110, 125], mobile: [150, 170] },
      { edit: [1183, 152], run: [1180, 120], mobile: [540, 140] },
    ),
    node(
      "headphones",
      "Headphones",
      "headphones",
      { edit: [90, 70], run: [70, 54], mobile: [90, 70] },
      { edit: [1230, 297], run: [1290, 230], mobile: [540, 330] },
    ),
    node(
      "response",
      "Response",
      "response-box",
      { edit: [110, 100], run: [84, 76], mobile: [110, 100] },
      { edit: [1343, 322], run: [1390, 300], mobile: [540, 500] },
    ),
    node(
      "cap",
      "Cap",
      "cap-ring",
      { edit: [26, 26], run: [22, 22], mobile: [26, 26] },
      { edit: [1055, 328], run: [1005, 238], mobile: [180, 262] },
      false,
    ),
    node(
      "sbox",
      "32-ch S-Box",
      "splitter-box",
      { edit: [190, 120], run: [140, 90], mobile: [190, 120] },
      { edit: [1048, 392], run: [1000, 300], mobile: [180, 330] },
    ),
    node(
      "pz5",
      "PZ5",
      "amplifier",
      { edit: [100, 150], run: [76, 114], mobile: [100, 150] },
      { edit: [863, 452], run: [790, 330], mobile: [180, 520] },
    ),
    node(
      "rz6",
      "RZ6",
      "rack-processor",
      { edit: [470, 110], run: [380, 90], mobile: [470, 110] },
      { edit: [793, 712], run: [560, 440], mobile: [360, 700] },
    ),
    node(
      "computer",
      "Computer",
      "computer",
      { edit: [160, 130], run: [120, 98], mobile: [160, 130] },
      { edit: [308, 742], run: [140, 440], mobile: [180, 880] },
    ),
    node(
      "experimenter",
      "Experimenter",
      "head-experimenter",
      { edit: [110, 170], run: [84, 130], mobile: [110, 170] },
      { edit: [133, 642], run: [70, 300], mobile: [540, 880] },
    ),
  ],
  edges: [
    edge("e-stimulus", "stimulus", "display", "participant", {
      edit: "M 430 175 C 720 80, 1010 80, 1130 195",
      run: "M 380 120 C 640 50, 900 50, 1120 110",
    }),
    edge("e-marker", "marker", "display", "headphones", {
      edit: "M 430 235 C 720 340, 1010 330, 1195 300",
      run: "M 380 185 C 640 260, 950 260, 1250 230",
    }),
    edge("e-cap", "eeg", "cap", "sbox", { edit: "M 1055 341 L 1050 360", run: "M 1005 251 L 1002 270" }, false),
    edge("e-eeg", "eeg", "sbox", "rz6", {
      edit: "M 960 420 L 905 440 M 850 530 C 830 610, 800 640, 800 655",
      run: "M 910 320 L 840 330 M 780 405 C 760 440, 700 445, 660 445",
    }),
    edge("e-response", "response", "response", "rz6", {
      edit: "M 1330 372 C 1230 560, 1120 700, 1030 712",
      run: "M 1350 350 C 1250 470, 950 470, 750 445",
    }),
    edge("e-data", "data", "computer", "rz6", { edit: "M 392 745 L 556 725", run: "M 222 445 L 370 445" }),
  ],
  legend: [
    { kind: "eeg", label: "EEG" },
    { kind: "stimulus", label: "stimulus" },
    { kind: "marker", label: "marker" },
  ],
};
