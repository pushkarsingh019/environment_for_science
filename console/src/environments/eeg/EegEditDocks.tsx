import type { EnvironmentDraft } from "../../types";
import type { DocksProps } from "../adapter";
import { MontageLens } from "./MontageLens";

/** Whole-cap lens docked top-right inside the Edit viewport; nothing until the draft loads. */
export function EegEditDocks({ draft }: DocksProps & { draft: EnvironmentDraft | null }): JSX.Element | null {
  if (draft === null) return null;
  return (
    <div className="scene-dock scene-dock--cap">
      <MontageLens draft={draft} variant="edit" />
    </div>
  );
}
