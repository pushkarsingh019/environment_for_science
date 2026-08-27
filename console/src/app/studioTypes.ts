import type {
  DraftCommandResult,
  EnvironmentCatalogEntry,
  EnvironmentDraft,
  EnvironmentSummary,
  FrozenEnvironment,
  JsonObject,
  ReplayReport,
  RunSnapshot,
  SealedEnvironment,
} from "../types";

export type Mode = "edit" | "run" | "evaluate";
export type NavSection = "apparatus" | "procedure" | "observations" | "checks";

export interface ActionPreference {
  type: string;
  values?: Record<string, string>;
}

export interface BarCounters {
  parts: number;
  steps: number;
  stepsLabel: string;
  checks: number;
}

/** P1 renders `<div id={BOTTOM_BAR_SLOT_ID}>`; P6 portals its launch controls into it. */
export const BOTTOM_BAR_SLOT_ID = "bottom-bar-policy-slot";
/** P5 owns the hidden file input; P1 SideNav clicks it by id. */
export const NOTE_FILE_INPUT_ID = "note-file";

export const RUN_STATUS_LABELS: Record<RunSnapshot["status"], string> = {
  active: "Active run",
  awaiting_verification: "Awaiting verification",
  completed: "Completed run",
};

export interface StudioState {
  mode: Mode;
  catalog: EnvironmentCatalogEntry[];
  environment: EnvironmentSummary | null;
  draft: EnvironmentDraft | null;
  draftResult: DraftCommandResult | null;
  frozen: FrozenEnvironment | null;
  sealedFrozen: SealedEnvironment | null;
  run: RunSnapshot | null;
  replay: ReplayReport | null;
  selectedAgent: string;
  selectedScenario: string;
  busy: boolean;
  draftBusy: boolean;
  error: string | null;
  resetNotice: string | null;
  section: NavSection;
  preferredAction: ActionPreference | null;
}

export interface StudioActions {
  setMode(mode: Mode): void;
  setSection(section: NavSection): void;
  selectEnvironment(environmentId: string): Promise<void>;
  applyDraftCommand(command: string): Promise<void>;
  undoDraft(): Promise<void>;
  redoDraft(): Promise<void>;
  restoreDraft(): Promise<void>;
  stageNote(filename: string, content: string): Promise<void>;
  /** Client-side validation errors surface through Notices (`role="alert"`). */
  reportError(message: string): void;
  setSelectedAgent(id: string): void;
  setSelectedScenario(id: string): void;
  startRun(): Promise<void>;
  applyAction(type: string, arguments_: JsonObject): Promise<void>;
  verifyRun(): Promise<void>;
  resetRun(): Promise<void>;
  replayRun(): Promise<void>;
  resetDemo(): Promise<void>;
  preferAction(preference: ActionPreference): void;
  consumePreferredAction(): void;
}
