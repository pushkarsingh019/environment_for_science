import type { ReactNode } from "react";
import { BOTTOM_BAR_SLOT_ID, type BarCounters } from "../app/studioTypes";

export interface BottomBarProps {
  left: ReactNode;
  /** `"slot"` renders an empty group carrying `BOTTOM_BAR_SLOT_ID` for P6's portal. */
  right: ReactNode | "slot";
  counters: BarCounters | null;
}

/** The single action bar: authoring group | Separate | policy group | counters. */
export function BottomBar(props: BottomBarProps): JSX.Element {
  const { left, right, counters } = props;
  const isSlot = right === "slot";

  return (
    <div className="bottom-bar">
      <div className="bar-group bar-group--authoring">{left}</div>
      <div className="bar-divider" aria-hidden="true">
        <span>Separate</span>
      </div>
      <div className="bar-group bar-group--policy" id={isSlot ? BOTTOM_BAR_SLOT_ID : undefined}>
        {!isSlot && right}
      </div>
      {counters && (
        <p className="bar-counters">
          <span>{counters.parts} parts</span>
          <span>
            {counters.steps} {counters.stepsLabel}
          </span>
          <span>{counters.checks} checks</span>
        </p>
      )}
    </div>
  );
}

export type BarDot = "idle" | "active" | "awaiting" | "done" | "assistant";

export interface BarLabelProps {
  dot?: BarDot;
  title: string;
  caption: ReactNode;
  extra?: ReactNode;
}

/** Two-line group label with an optional status dot; shared by P5, P6 and PI. */
export function BarLabel(props: BarLabelProps): JSX.Element {
  const { dot, title, caption, extra } = props;

  return (
    <div className="bar-label">
      {dot && <span className={`bar-dot is-${dot}`} aria-hidden="true" />}
      <div>
        <strong>{title}</strong>
        <small>{caption}</small>
        {extra}
      </div>
    </div>
  );
}
