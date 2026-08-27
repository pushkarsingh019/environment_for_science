import type { SceneLayoutMode, SceneNodeSpec, SceneNodeState } from "./sceneModel";

export interface SceneNodeProps {
  spec: SceneNodeSpec;
  state: SceneNodeState;
  mode: SceneLayoutMode;
  focused: boolean;
  onActivate?: (nodeId: string) => void;
}

const CHIP_HEIGHT = 24;
const CHIP_GAP = 10;
const HINT_HEIGHT = 20;
const HINT_GAP = 6;

/** SVG text has no layout pass; chip widths are estimated from the label length. */
function chipWidth(label: string, fontSize: number): number {
  return Math.max(48, Math.round(label.length * fontSize * 0.56) + 22);
}

/** One apparatus part: glyph, status LED, name chip and up to two evidence hints. */
export function SceneNode(props: SceneNodeProps): JSX.Element {
  const { spec, state, mode, focused, onActivate } = props;
  const { w, h } = spec.size[mode];
  const { x, y } = spec.at[mode];
  const label = state.label ?? spec.label;
  const hints = state.hints.slice(0, 2);
  const description = hints.length > 0 ? `${label}: ${hints.map((hint) => hint.label).join(", ")}` : label;

  const chipW = chipWidth(label, 13);
  const chipY = h + CHIP_GAP;

  return (
    <g
      className={`scene-node${focused ? " is-focused" : ""}${onActivate ? " is-interactive" : ""}`}
      data-node={spec.id}
      data-tone={state.tone}
      transform={`translate(${x - w / 2} ${y - h / 2})`}
      role={onActivate ? "button" : "img"}
      tabIndex={-1}
      aria-label={description}
      onClick={onActivate ? () => onActivate(spec.id) : undefined}
    >
      <title>{description}</title>
      <use href={`#glyph-${spec.glyph}`} width={w} height={h} />
      <circle className="scene-led" cx={w - 7} cy={7} r={5.5} />

      {spec.chip && (
        <g className="scene-chip" transform={`translate(${(w - chipW) / 2} ${chipY})`}>
          <rect width={chipW} height={CHIP_HEIGHT} rx="8" />
          <text x={chipW / 2} y={CHIP_HEIGHT / 2 + 4.5} textAnchor="middle">
            {label}
          </text>
        </g>
      )}

      {hints.map((hint, index) => {
        const hintW = chipWidth(hint.label, 11.5);
        const hintY = chipY + (spec.chip ? CHIP_HEIGHT + HINT_GAP : 0) + index * (HINT_HEIGHT + HINT_GAP);
        return (
          <g
            key={hint.label}
            className="scene-hint"
            data-tone={hint.tone}
            transform={`translate(${(w - hintW) / 2} ${hintY})`}
          >
            <rect width={hintW} height={HINT_HEIGHT} rx="10" />
            <text x={hintW / 2} y={HINT_HEIGHT / 2 + 4} textAnchor="middle">
              {hint.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}
