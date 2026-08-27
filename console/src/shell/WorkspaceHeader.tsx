import type { Mode } from "../app/studioTypes";

export interface WorkspaceHeaderProps {
  crumb: string;
  title: string;
  titleId: "edit-heading" | "run-heading" | "evaluation-title";
  mode: Mode;
  onMode: (mode: Mode) => void;
}

interface ModeTab {
  mode: Mode;
  label: string;
  controls: string;
}

const MODE_TABS: readonly ModeTab[] = [
  { mode: "edit", label: "Edit", controls: "edit-workspace" },
  { mode: "run", label: "Run", controls: "run-workspace" },
  { mode: "evaluate", label: "Evaluate", controls: "evaluation-workspace" },
];

/** Breadcrumb, page title and the Edit / Run / Evaluate tablist. */
export function WorkspaceHeader(props: WorkspaceHeaderProps): JSX.Element {
  const { crumb, title, titleId, mode, onMode } = props;

  return (
    <div className="workspace-header">
      <div>
        <p className="breadcrumb">{crumb}</p>
        <h1 id={titleId}>{title}</h1>
      </div>
      <div className="mode-tabs" role="tablist" aria-label="Environment workspace">
        {MODE_TABS.map((tab) => {
          const active = tab.mode === mode;
          return (
            <button
              key={tab.mode}
              type="button"
              role="tab"
              data-testid={`mode-${tab.mode}`}
              aria-selected={active}
              aria-controls={tab.controls}
              className={active ? "is-active" : undefined}
              onClick={() => onMode(tab.mode)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
