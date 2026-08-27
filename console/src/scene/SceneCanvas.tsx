import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { STACKED_QUERY, useMediaQuery } from "../app/useMediaQuery";
import { GlyphDefs } from "./glyphs";
import { SceneEdge } from "./SceneEdge";
import { SceneLegend } from "./SceneLegend";
import { SceneNode } from "./SceneNode";
import { IDLE_EDGE, IDLE_NODE, type SceneLayoutMode, type SceneState } from "./sceneModel";

export interface SceneCanvasProps {
  state: SceneState;
  mode: "edit" | "run";
  title: string;
  subtitle: string;
  badge: string;
  ariaLabel: string;
  testId?: string;
  /** Validation chip in the card header. */
  header?: ReactNode;
  /** Sealed-boundary line, directly under the header. */
  boundaryNote?: ReactNode;
  /** Verifier result ribbon, above the viewport. */
  ribbon?: ReactNode;
  /** Absolutely positioned inside the viewport (the EEG cap lens). */
  viewportDock?: ReactNode;
  /** Evidence docks below the viewport, inside the card. */
  docks?: ReactNode;
  /** Procedure strip or sealed facts, at the foot of the card. */
  footer?: ReactNode;
  onNodeActivate?: (nodeId: string) => void;
}

/**
 * The apparatus canvas: the dominant surface in both Edit and Run. The viewport is
 * a single tab stop; arrow keys rove between parts and Enter activates one.
 */
export function SceneCanvas(props: SceneCanvasProps): JSX.Element {
  const {
    state,
    mode,
    title,
    subtitle,
    badge,
    ariaLabel,
    testId,
    header,
    boundaryNote,
    ribbon,
    viewportDock,
    docks,
    footer,
    onNodeActivate,
  } = props;

  const stacked = useMediaQuery(STACKED_QUERY);
  const layoutMode: SceneLayoutMode = stacked ? "mobile" : mode;
  const viewBox = state.layout.viewBox[layoutMode];
  const floor = state.layout.floor[layoutMode];
  const nodes = state.layout.nodes;
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [showFocus, setShowFocus] = useState(false);

  useEffect(() => {
    setFocusedIndex((index) => (index < nodes.length ? index : 0));
  }, [nodes.length]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (nodes.length === 0) return;
      const last = nodes.length - 1;
      let next: number | null = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") next = focusedIndex >= last ? 0 : focusedIndex + 1;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = focusedIndex <= 0 ? last : focusedIndex - 1;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = last;
      else if (event.key === "Enter" || event.key === " ") {
        if (onNodeActivate) {
          event.preventDefault();
          onNodeActivate(nodes[focusedIndex].id);
        }
        return;
      }
      if (next === null) return;
      event.preventDefault();
      setShowFocus(true);
      setFocusedIndex(next);
    },
    [focusedIndex, nodes, onNodeActivate],
  );

  return (
    <section className="scene-card" data-testid={testId} aria-label={ariaLabel}>
      <header className="scene-header">
        <div className="scene-title">
          <strong>{title}</strong>
          <span> · {subtitle}</span>
        </div>
        <div className="scene-header-tools">{header}</div>
        <span className="scene-badge">{badge}</span>
      </header>

      {boundaryNote}
      {ribbon}

      <div
        className="scene-viewport"
        id="scene-viewport"
        ref={viewportRef}
        data-mode={layoutMode}
        data-layout={state.layout.id}
        role="group"
        aria-label={`${title} apparatus scene`}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onBlur={() => setShowFocus(false)}
      >
        <svg
          className="scene-svg"
          viewBox={`0 0 ${viewBox.w} ${viewBox.h}`}
          preserveAspectRatio="xMidYMid meet"
          role="presentation"
        >
          <defs>
            <GlyphDefs />
          </defs>

          {floor && <polygon className="scene-floor" points={floor} />}

          {state.layout.zones.map((zone) => {
            const rect = zone.rect[layoutMode];
            if (rect === null) return null;
            return (
              <g className="scene-zone" key={zone.id}>
                <rect x={rect.x} y={rect.y} width={rect.w} height={rect.h} rx="24" />
                <text x={rect.x + 20} y={rect.y + 26}>
                  {zone.label}
                </text>
              </g>
            );
          })}

          {state.layout.edges.map((spec) => (
            <SceneEdge key={spec.id} spec={spec} state={state.edges[spec.id] ?? IDLE_EDGE} mode={layoutMode} />
          ))}

          {nodes.map((spec, index) => (
            <SceneNode
              key={spec.id}
              spec={spec}
              state={state.nodes[spec.id] ?? IDLE_NODE}
              mode={layoutMode}
              focused={showFocus && index === focusedIndex}
              onActivate={onNodeActivate}
            />
          ))}
        </svg>

        {viewportDock}
        <SceneLegend entries={state.legend} />
      </div>

      {docks}
      {footer}
    </section>
  );
}
