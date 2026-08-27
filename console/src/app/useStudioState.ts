import { useCallback, useEffect, useMemo, useState } from "react";
import { demoApi, draftApi, environmentApi } from "../api";
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
import type { ActionPreference, Mode, NavSection, StudioActions, StudioState } from "./studioTypes";

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/**
 * Every console request and the state it produces. The mount fetches run first so the
 * backend sets its local session cookie before any POST.
 */
export function useStudioState(): { state: StudioState; actions: StudioActions } {
  const [mode, setMode] = useState<Mode>("edit");
  const [section, setSection] = useState<NavSection>("apparatus");
  const [catalog, setCatalog] = useState<EnvironmentCatalogEntry[]>([]);
  const [environment, setEnvironment] = useState<EnvironmentSummary | null>(null);
  const [draft, setDraft] = useState<EnvironmentDraft | null>(null);
  const [draftResult, setDraftResult] = useState<DraftCommandResult | null>(null);
  const [frozen, setFrozen] = useState<FrozenEnvironment | null>(null);
  const [sealedFrozen, setSealedFrozen] = useState<SealedEnvironment | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [replay, setReplay] = useState<ReplayReport | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedScenario, setSelectedScenario] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [preferredAction, setPreferredAction] = useState<ActionPreference | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([environmentApi.getCatalog(), environmentApi.getEnvironment(), draftApi.get()])
      .then(([loadedCatalog, loadedEnvironment, loadedDraft]) => {
        if (cancelled) return;
        setCatalog(loadedCatalog);
        setEnvironment(loadedEnvironment);
        setDraft(loadedDraft);
        setSelectedAgent(loadedEnvironment.policy_agents[0]?.id ?? "");
        setSelectedScenario(loadedEnvironment.seeded_examples[0]?.scenario_id ?? "");
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason, "Unable to load the Environment draft"));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const perform = useCallback(async (operation: () => Promise<RunSnapshot>): Promise<void> => {
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      setRun(await operation());
    } catch (reason) {
      setError(errorMessage(reason, "The Runtime operation failed"));
    } finally {
      setBusy(false);
    }
  }, []);

  const performDraft = useCallback(
    async (operation: () => Promise<EnvironmentDraft>): Promise<void> => {
      setDraftBusy(true);
      setError(null);
      setDraftResult(null);
      try {
        setDraft(await operation());
      } catch (reason) {
        setError(errorMessage(reason, "The draft operation failed"));
      } finally {
        setDraftBusy(false);
      }
    },
    [],
  );

  const actions = useMemo<StudioActions>(() => {
    return {
      setMode,
      setSection,

      async selectEnvironment(environmentId: string): Promise<void> {
        if (environmentId === environment?.environment_id) return;
        setBusy(true);
        setError(null);
        try {
          const selected = await environmentApi.getEnvironmentById(environmentId);
          setEnvironment(selected);
          setSelectedAgent(selected.policy_agents[0]?.id ?? "");
          setSelectedScenario(selected.seeded_examples[0]?.scenario_id ?? "");
          setFrozen(null);
          setSealedFrozen(null);
          setRun(null);
          setReplay(null);
          setDraftResult(null);
          setPreferredAction(null);
          setSection("apparatus");
        } catch (reason) {
          setError(errorMessage(reason, "Unable to switch Environment"));
        } finally {
          setBusy(false);
        }
      },

      async applyDraftCommand(command: string): Promise<void> {
        if (!draft) return;
        setDraftBusy(true);
        setError(null);
        setDraftResult(null);
        try {
          const response = await draftApi.command(command, draft.revision);
          setDraft(response.draft);
          setDraftResult(response.result);
        } catch (reason) {
          setError(errorMessage(reason, "The Authoring assistant could not revise the draft"));
        } finally {
          setDraftBusy(false);
        }
      },

      async undoDraft(): Promise<void> {
        if (!draft) return;
        await performDraft(() => draftApi.undo(draft.revision));
      },

      async redoDraft(): Promise<void> {
        if (!draft) return;
        await performDraft(() => draftApi.redo(draft.revision));
      },

      async restoreDraft(): Promise<void> {
        if (!draft) return;
        await performDraft(() => draftApi.restore(draft.revision));
      },

      async stageNote(filename: string, content: string): Promise<void> {
        if (!draft) return;
        await performDraft(() => draftApi.stageNote(filename, content, draft.revision));
      },

      reportError(message: string): void {
        setError(message);
      },

      setSelectedAgent,
      setSelectedScenario,

      async startRun(): Promise<void> {
        if (
          !environment ||
          !selectedAgent ||
          !selectedScenario ||
          (environment.source_kind === "editable_draft" && !draft)
        ) {
          return;
        }
        setBusy(true);
        setError(null);
        setReplay(null);
        try {
          const frozenEnvironment =
            environment.source_kind === "sealed_seed"
              ? await environmentApi.freezeSealed(environment.environment_id)
              : await draftApi.freeze(draft!.revision);
          const started = await environmentApi.start(
            selectedScenario,
            selectedAgent,
            frozenEnvironment.frozen_environment_id,
            environment.environment_id,
          );
          if (
            started.revision_digest !== frozenEnvironment.revision_digest ||
            started.scenario_id !== selectedScenario
          ) {
            throw new Error("The started run did not match the frozen Environment identity.");
          }
          if ("source_kind" in frozenEnvironment) {
            setSealedFrozen(frozenEnvironment);
            setFrozen(null);
          } else {
            setFrozen(frozenEnvironment);
            setSealedFrozen(null);
          }
          setRun(started);
          setMode("run");
        } catch (reason) {
          setError(errorMessage(reason, "Unable to freeze and start the run"));
        } finally {
          setBusy(false);
        }
      },

      async applyAction(type: string, arguments_: JsonObject): Promise<void> {
        if (!run) return;
        await perform(() => environmentApi.apply(run.run_id, type, arguments_));
      },

      async verifyRun(): Promise<void> {
        if (!run) return;
        await perform(() => environmentApi.verify(run.run_id));
      },

      async resetRun(): Promise<void> {
        if (!run) return;
        await perform(() => environmentApi.reset(run.run_id));
      },

      async replayRun(): Promise<void> {
        if (!run) return;
        setBusy(true);
        setError(null);
        setReplay(null);
        try {
          const response = await environmentApi.replay(run.run_id);
          setRun(response.snapshot);
          setReplay(response.replay);
        } catch (reason) {
          setError(errorMessage(reason, "Unable to replay the trace"));
        } finally {
          setBusy(false);
        }
      },

      async resetDemo(): Promise<void> {
        setBusy(true);
        setDraftBusy(true);
        setError(null);
        setResetNotice(null);
        try {
          const reset = await demoApi.reset();
          const [loadedCatalog, loadedEnvironment, loadedDraft] = await Promise.all([
            environmentApi.getCatalog(),
            environmentApi.getEnvironment(),
            draftApi.get(),
          ]);
          setCatalog(loadedCatalog);
          setEnvironment(loadedEnvironment);
          setDraft(loadedDraft);
          setSelectedAgent(loadedEnvironment.policy_agents[0]?.id ?? "");
          setSelectedScenario(loadedEnvironment.seeded_examples[0]?.scenario_id ?? "");
          setFrozen(null);
          setSealedFrozen(null);
          setRun(null);
          setReplay(null);
          setDraftResult(null);
          setPreferredAction(null);
          setMode("edit");
          setSection("apparatus");
          setResetNotice(
            `${reset.summary} Preserved ${reset.immutable_training_jobs_preserved} training job(s).`,
          );
        } catch (reason) {
          setError(errorMessage(reason, "Unable to reset the demonstration"));
        } finally {
          setBusy(false);
          setDraftBusy(false);
        }
      },

      preferAction(preference: ActionPreference): void {
        setPreferredAction(preference);
      },

      consumePreferredAction(): void {
        setPreferredAction(null);
      },
    };
  }, [draft, environment, perform, performDraft, run, selectedAgent, selectedScenario]);

  const state: StudioState = {
    mode,
    catalog,
    environment,
    draft,
    draftResult,
    frozen,
    sealedFrozen,
    run,
    replay,
    selectedAgent,
    selectedScenario,
    busy,
    draftBusy,
    error,
    resetNotice,
    section,
    preferredAction,
  };

  return { state, actions };
}
