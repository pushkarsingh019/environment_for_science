import type { SceneEdgeSpec, SceneEdgeState, SceneLayoutMode } from "./sceneModel";

export interface SceneEdgeProps {
  spec: SceneEdgeSpec;
  state: SceneEdgeState;
  mode: SceneLayoutMode;
}

/** One signal path between two parts. Renders nothing when the mode hides it. */
export function SceneEdge(props: SceneEdgeProps): JSX.Element | null {
  const { spec, state, mode } = props;
  const d = spec.d[mode];
  if (d === null) return null;

  return (
    <path
      className={`scene-edge edge--${spec.kind}${state.live ? " is-live" : ""}`}
      data-edge={spec.id}
      data-tone={state.tone}
      d={d}
      fill="none"
      strokeDasharray={spec.dashed ? "9 7" : undefined}
    />
  );
}
