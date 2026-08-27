import type { Mode } from "../app/studioTypes";
import type { EnvironmentDraft } from "../types";

interface DraftHistoryControlsProps {
  draft: EnvironmentDraft;
  busy: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onRestore: () => void;
}

function HistoryArrow({ direction }: { direction: "undo" | "redo" }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.6"
      transform={direction === "redo" ? "scale(-1 1)" : undefined}
      viewBox="0 0 16 16"
    >
      <path d="M6 3.5 2.5 7l3.5 3.5" />
      <path d="M2.5 7h6.5a3.5 3.5 0 0 1 0 7H7" />
    </svg>
  );
}

/** Top-bar history slot: undo, redo, and restore for the editable draft. */
export function DraftHistoryControls({
  draft,
  busy,
  onUndo,
  onRedo,
  onRestore,
}: DraftHistoryControlsProps) {
  return (
    <div aria-label="Draft history" className="history-controls" role="group">
      <button
        aria-label="Undo"
        className="icon-button"
        data-testid="undo-draft"
        disabled={busy || !draft.history.can_undo}
        onClick={onUndo}
        title="Undo"
        type="button"
      >
        <HistoryArrow direction="undo" />
      </button>
      <button
        aria-label="Redo"
        className="icon-button"
        data-testid="redo-draft"
        disabled={busy || !draft.history.can_redo}
        onClick={onRedo}
        title="Redo"
        type="button"
      >
        <HistoryArrow direction="redo" />
      </button>
      <button
        className="secondary-button"
        data-testid="restore-draft"
        disabled={busy}
        onClick={onRestore}
        type="button"
      >
        Restore seed
      </button>
    </div>
  );
}

interface DraftStateChipProps {
  draft: EnvironmentDraft | null;
  mode: Mode;
  sealed: boolean;
}

/** Top-bar state chip: the draft revision in Edit, otherwise the screen's fixed state. */
export function DraftStateChip({ draft, mode, sealed }: DraftStateChipProps) {
  if (mode === "run") return <span className="state-chip">Frozen</span>;
  if (mode === "evaluate") return <span className="state-chip">Evaluate</span>;
  if (sealed) return <span className="state-chip">Sealed seed</span>;
  if (!draft) return <span className="state-chip">Loading…</span>;
  return (
    <span
      className="state-chip"
      data-revision={draft.revision}
      data-testid="draft-revision"
      title={draft.revision_digest}
    >
      Draft r{draft.revision}
    </span>
  );
}
