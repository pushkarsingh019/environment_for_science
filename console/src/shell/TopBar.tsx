import type { ReactNode } from "react";
import type { EnvironmentCatalogEntry, EnvironmentSummary } from "../types";

export interface TopBarProps {
  catalog: EnvironmentCatalogEntry[];
  environment: EnvironmentSummary | null;
  busy: boolean;
  onSelectEnvironment: (environmentId: string) => void;
  /** DraftStateChip (P5) or a plain `<span>`. */
  stateChip: ReactNode;
  /** NoteImport (P5) or null. */
  importNote: ReactNode;
  /** DraftHistoryControls (P5) or null. */
  history: ReactNode;
}

/** Brand mark, the EEG | Mesoscope segmented control, and the tool slots. */
export function TopBar(props: TopBarProps): JSX.Element {
  const { catalog, environment, busy, onSelectEnvironment, stateChip, importNote, history } = props;

  return (
    <header className="topbar">
      <div className="brand-mark" aria-label="Science Environment Studio">
        <span className="brand-symbol" aria-hidden="true">
          E
        </span>
        <strong>Environment Studio</strong>
        <span className="brand-tag">prototype</span>
      </div>
      <nav className="environment-switch" aria-label="Environment">
        {catalog.map((entry) => {
          const active = entry.environment_id === environment?.environment_id;
          return (
            <button
              key={entry.environment_id}
              type="button"
              className={`environment-switch-button${active ? " is-active" : ""}`}
              data-testid={`environment-nav-${entry.environment_kind}`}
              aria-current={active ? "page" : undefined}
              disabled={busy}
              onClick={() => onSelectEnvironment(entry.environment_id)}
            >
              {entry.navigation_label}
            </button>
          );
        })}
      </nav>
      <div className="topbar-tools">
        {stateChip}
        {importNote}
        {history}
      </div>
    </header>
  );
}
