import { NOTE_FILE_INPUT_ID, type Mode, type NavSection } from "../app/studioTypes";

export interface SideNavProps {
  mode: Mode;
  section: NavSection;
  onSection: (section: NavSection) => void;
  noteCount: number;
  /** When true the Manual import row clicks the hidden note file input owned by P5. */
  canImportNote: boolean;
  resetBusy: boolean;
  onResetDemo: () => void;
}

interface NavEntry {
  id: NavSection;
  label: string;
}

const NAV_ENTRIES: readonly NavEntry[] = [
  { id: "apparatus", label: "Apparatus" },
  { id: "procedure", label: "Procedure" },
  { id: "observations", label: "Observations & actions" },
  { id: "checks", label: "Checks" },
];

function NavIcon({ section }: { section: NavSection }): JSX.Element {
  const common = {
    width: 14,
    height: 14,
    viewBox: "0 0 14 14",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (section) {
    case "apparatus":
      return (
        <svg {...common}>
          <rect x="1.5" y="1.5" width="4.5" height="4.5" rx="1" />
          <rect x="8" y="1.5" width="4.5" height="4.5" rx="1" />
          <rect x="1.5" y="8" width="4.5" height="4.5" rx="1" />
          <rect x="8" y="8" width="4.5" height="4.5" rx="1" />
        </svg>
      );
    case "procedure":
      return (
        <svg {...common}>
          <path d="M4 3.5h8.5M4 7h8.5M4 10.5h8.5" />
          <path d="M1.5 3.5h.01M1.5 7h.01M1.5 10.5h.01" />
        </svg>
      );
    case "observations":
      return (
        <svg {...common}>
          <path d="M1.5 10.5c2.5 0 3-7 5.5-7s3 7 5.5 7" />
          <path d="M10.5 8.5l2 2-2 2" />
        </svg>
      );
    case "checks":
      return (
        <svg {...common}>
          <path d="M2.5 7.5l3 3 6-7" />
        </svg>
      );
  }
}

/** Quiet left navigation: sections, manual import, simulation card, reset link. */
export function SideNav(props: SideNavProps): JSX.Element {
  const { section, onSection, noteCount, canImportNote, resetBusy, onResetDemo } = props;

  const importNote = () => {
    document.getElementById(NOTE_FILE_INPUT_ID)?.click();
  };

  return (
    <aside className="side-nav" aria-label="Console navigation">
      <p className="eyebrow">Environment</p>
      <ul className="nav-list">
        {NAV_ENTRIES.map((entry) => {
          const active = entry.id === section;
          return (
            <li key={entry.id}>
              <button
                type="button"
                className={`nav-row${active ? " is-active" : ""}`}
                aria-current={active ? "true" : undefined}
                data-section={entry.id}
                onClick={() => onSection(entry.id)}
              >
                <span className="nav-icon" aria-hidden="true">
                  <NavIcon section={entry.id} />
                </span>
                {entry.label}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="eyebrow">Sources</p>
      <button type="button" className="nav-row nav-import" disabled={!canImportNote} onClick={importNote}>
        <span className="nav-icon" aria-hidden="true">
          +
        </span>
        Manual import
        <span className="nav-count">{noteCount}</span>
      </button>
      <div className="nav-card">
        <strong>Simulated apparatus</strong>
        <p>Simulation only — not medical guidance and not connected to physical instruments.</p>
      </div>
      <button
        type="button"
        className="link-button nav-reset"
        data-testid="reset-demo"
        disabled={resetBusy}
        onClick={onResetDemo}
      >
        Reset demo
      </button>
    </aside>
  );
}
