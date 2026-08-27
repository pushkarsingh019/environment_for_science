import { useStudioState } from "./app/useStudioState";
import type { NavSection } from "./app/studioTypes";
import { AssistantAbsent, AuthoringComposer, SealedAuthoringNote } from "./authoring/AuthoringComposer";
import { DraftHistoryControls, DraftStateChip } from "./authoring/DraftHistoryControls";
import { DraftIdentity } from "./authoring/DraftIdentity";
import { NoteImport } from "./authoring/NoteImport";
import { ProcedureStrip } from "./authoring/ProcedureStrip";
import { EvaluationBoundary, EvaluationWorkspace } from "./evaluation/EvaluationWorkspace";
import { adapterFor } from "./environments";
import { EegEditDocks } from "./environments/eeg/EegEditDocks";
import { MesoscopeBoundaryNote } from "./environments/mesoscope/mesoscopeAdapter";
import { ContractCards } from "./environments/mesoscope/ContractCards";
import { PackageEvidence } from "./environments/mesoscope/PackageEvidence";
import { SealedFrozenIdentity } from "./environments/mesoscope/SealedFrozenIdentity";
import { SealedSeedFacts } from "./environments/mesoscope/SealedSeedFacts";
import { readMesoscopeObservation } from "./environments/mesoscope/mesoscopeEvidence";
import { FrozenConfiguration } from "./run/FrozenConfiguration";
import { ResultRibbon, ValidationChip } from "./run/RunChecks";
import { RunControls } from "./run/RunControls";
import { RunIdentity } from "./run/RunIdentity";
import { RunSetupRail } from "./run/RunSetupRail";
import { TraceTimeline } from "./run/TraceTimeline";
import { SceneCanvas } from "./scene/SceneCanvas";
import { BarLabel, BottomBar } from "./shell/BottomBar";
import { DetailsRail, type RailSection } from "./shell/DetailsRail";
import { Notices } from "./shell/Notices";
import { SideNav } from "./shell/SideNav";
import { TopBar } from "./shell/TopBar";
import { WorkspaceHeader } from "./shell/WorkspaceHeader";

const SECTION_TARGETS: Record<NavSection, string[]> = {
  apparatus: ["scene-viewport"],
  procedure: ["procedure-strip", "rail-procedure"],
  observations: ["eeg-diagnostics-title", "timeline"],
  checks: ["environment-validation", "rail-checks"],
};

function scrollToSection(section: NavSection): void {
  for (const id of SECTION_TARGETS[section]) {
    const target = document.getElementById(id);
    if (target !== null) {
      target.scrollIntoView({ block: "start", behavior: "smooth" });
      return;
    }
  }
}

export function App(): JSX.Element {
  const { state, actions } = useStudioState();
  const {
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
  } = state;

  const adapter = environment ? adapterFor(environment) : null;
  const sceneInput = environment ? { environment, run, mode } : null;
  const editable = environment?.source_kind === "editable_draft";
  const mesoscope = environment?.environment_kind === "mesoscope";
  const canStart =
    Boolean(environment) &&
    Boolean(selectedAgent) &&
    Boolean(selectedScenario) &&
    (environment?.source_kind === "sealed_seed" || Boolean(draft)) &&
    !busy;

  const sceneTitle = adapter && sceneInput ? adapter.sceneTitle(sceneInput) : null;
  const counters =
    adapter && sceneInput && mode !== "evaluate" ? adapter.counters({ ...sceneInput, draft }) : null;
  const RunDocks = adapter?.RunDocks ?? null;

  const crumbEnvironment = mesoscope ? "Mesoscope" : "EEG";
  const header =
    mode === "edit"
      ? {
          crumb: `${crumbEnvironment} apparatus / canvas`,
          title: mesoscope ? (environment?.name ?? "Loading Environment…") : (draft?.title ?? "Loading EEG draft…"),
          titleId: "edit-heading" as const,
        }
      : mode === "run"
        ? {
            crumb: `${crumbEnvironment} apparatus / run`,
            title: environment?.name ?? "Loading Environment…",
            titleId: "run-heading" as const,
          }
        : {
            crumb: `${crumbEnvironment} apparatus / evaluate`,
            title: "Evaluate",
            titleId: "evaluation-title" as const,
          };

  const railSections: RailSection[] = [];
  if (mode === "evaluate") {
    railSections.push({
      id: "evaluation",
      title: "Evaluation",
      node: <EvaluationBoundary environmentKind={environment?.environment_kind} />,
    });
  } else if (mode === "edit") {
    if (draft && editable) {
      railSections.push({ id: "identity", title: "Draft", node: <DraftIdentity draft={draft} /> });
    }
  } else if (environment) {
    if (run === null) {
      railSections.push({
        id: "run",
        title: "Run setup",
        node: (
          <RunSetupRail
            environment={environment}
            selectedAgent={selectedAgent}
            onSelectAgent={actions.setSelectedAgent}
            busy={busy}
          />
        ),
      });
    } else {
      railSections.push({
        id: "run",
        title: "Run",
        node: <RunIdentity environment={environment} run={run} />,
      });
      if (mesoscope) {
        if (sealedFrozen) {
          railSections.push({
            id: "procedure",
            title: "Sealed revision",
            node: <SealedFrozenIdentity frozen={sealedFrozen} />,
          });
        }
        const view = readMesoscopeObservation(run.observation);
        if (view && environment.visualization.kind === "mesoscope_handoff_v1") {
          railSections.push({
            id: "contract",
            title: "Sealed contract",
            node: <ContractCards view={view} visualization={environment.visualization} />,
          });
          railSections.push({
            id: "package",
            title: "Package evidence",
            node: <PackageEvidence view={view} visualization={environment.visualization} />,
          });
        }
      } else if (frozen) {
        railSections.push({
          id: "procedure",
          title: "Procedure",
          node: <FrozenConfiguration frozen={frozen} />,
        });
      }
    }
    railSections.push({
      id: "checks",
      title: "Checks",
      node: (
        <ul className="quiet-list">
          {environment.validation.checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      ),
    });
  }

  const barLeft =
    mode === "edit" ? (
      editable ? (
        <AuthoringComposer
          draft={draft}
          busy={draftBusy}
          result={draftResult}
          onCommand={(command) => void actions.applyDraftCommand(command)}
        />
      ) : (
        <SealedAuthoringNote />
      )
    ) : mode === "run" ? (
      <AssistantAbsent caption="Not in this run" />
    ) : (
      <AssistantAbsent caption="Not in evaluation" />
    );

  const runControls = (
    <RunControls
      mode={mode === "run" ? "run" : "edit"}
      environment={environment}
      run={run}
      busy={busy}
      canStart={canStart}
      selectedScenario={selectedScenario}
      onSelectScenario={actions.setSelectedScenario}
      preferred={preferredAction}
      onPreferredConsumed={actions.consumePreferredAction}
      onStart={() => void actions.startRun()}
      onOpenRun={() => actions.setMode("run")}
      onAction={(type, arguments_) => void actions.applyAction(type, arguments_)}
      onVerify={() => void actions.verifyRun()}
      onReplay={() => void actions.replayRun()}
      onReset={() => void actions.resetRun()}
    />
  );

  return (
    <div className="app-shell" data-mode={mode}>
      <TopBar
        catalog={catalog}
        environment={environment}
        busy={busy}
        onSelectEnvironment={(id) => void actions.selectEnvironment(id)}
        stateChip={<DraftStateChip draft={draft} mode={mode} sealed={!editable} />}
        importNote={
          mode === "edit" && editable ? (
            <NoteImport
              busy={draftBusy}
              onStageNote={(filename, content) => void actions.stageNote(filename, content)}
              onError={actions.reportError}
            />
          ) : null
        }
        history={
          mode === "edit" && editable && draft ? (
            <DraftHistoryControls
              draft={draft}
              busy={draftBusy}
              onUndo={() => void actions.undoDraft()}
              onRedo={() => void actions.redoDraft()}
              onRestore={() => void actions.restoreDraft()}
            />
          ) : null
        }
      />

      <SideNav
        mode={mode}
        section={section}
        onSection={(next) => {
          actions.setSection(next);
          scrollToSection(next);
        }}
        noteCount={draft?.notes.length ?? 0}
        canImportNote={mode === "edit" && Boolean(editable)}
        resetBusy={busy || draftBusy}
        onResetDemo={() => void actions.resetDemo()}
      />

      <main className="workspace">
        <Notices error={error} status={resetNotice} />
        <WorkspaceHeader
          crumb={header.crumb}
          title={header.title}
          titleId={header.titleId}
          mode={mode}
          onMode={actions.setMode}
        />

        {mode === "evaluate" ? (
          <EvaluationWorkspace environmentKind={environment?.environment_kind} />
        ) : mode === "edit" ? (
          <section
            aria-labelledby="edit-heading"
            className="workspace-mode-panel"
            data-testid={mesoscope ? "sealed-environment-workspace" : "edit-workspace"}
            id="edit-workspace"
            role="tabpanel"
          >
            {environment && adapter && sceneInput && sceneTitle && (
              <SceneCanvas
                state={adapter.buildScene(sceneInput)}
                mode="edit"
                title={sceneTitle.title}
                subtitle={sceneTitle.subtitle}
                badge={sceneTitle.badge}
                ariaLabel={`${crumbEnvironment} apparatus scene`}
                header={<ValidationChip environment={environment} />}
                boundaryNote={mesoscope ? <MesoscopeBoundaryNote environment={environment} /> : undefined}
                footer={
                  mesoscope ? (
                    <SealedSeedFacts environment={environment} />
                  ) : draft ? (
                    <div className="edit-footer">
                      <ProcedureStrip draft={draft} />
                      {environment.visualization.kind === "eeg_preflight_v1" && (
                        <EegEditDocks
                          environment={environment}
                          run={run}
                          busy={busy}
                          onPreferAction={actions.preferAction}
                          draft={draft}
                        />
                      )}
                    </div>
                  ) : (
                    <p className="scene-caption">Loading draft…</p>
                  )
                }
                onNodeActivate={() => actions.setSection("apparatus")}
              />
            )}
          </section>
        ) : (
          <section
            aria-labelledby="run-heading"
            className="workspace-mode-panel"
            data-testid="run-workspace"
            id="run-workspace"
            role="tabpanel"
          >
            {environment && adapter && sceneInput && sceneTitle && RunDocks && (
              <SceneCanvas
                state={adapter.buildScene(sceneInput)}
                mode="run"
                title={sceneTitle.title}
                subtitle={sceneTitle.subtitle}
                badge={sceneTitle.badge}
                ariaLabel={`${crumbEnvironment} apparatus scene`}
                header={<ValidationChip environment={environment} />}
                boundaryNote={mesoscope ? <MesoscopeBoundaryNote environment={environment} /> : undefined}
                ribbon={run ? <ResultRibbon run={run} replay={replay} /> : undefined}
                docks={
                  <>
                    <RunDocks
                      key={run?.run_id ?? "no-run"}
                      environment={environment}
                      run={run}
                      busy={busy}
                      onPreferAction={actions.preferAction}
                    />
                    <TraceTimeline
                      environment={environment}
                      run={run}
                      traceEvidence={adapter.traceEvidence}
                    />
                  </>
                }
                onNodeActivate={(nodeId) => {
                  const preference = adapter.preferredActionForNode(nodeId, sceneInput);
                  if (preference) actions.preferAction(preference);
                  actions.setSection("observations");
                }}
              />
            )}
          </section>
        )}

        <BottomBar
          left={barLeft}
          right={
            mode === "evaluate"
              ? mesoscope
                ? <BarLabel dot="idle" title="Evaluation" caption="Read-only platform evidence" />
                : "slot"
              : runControls
          }
          counters={counters}
        />
      </main>

      <DetailsRail open={mode !== "edit"} sections={railSections} />
    </div>
  );
}
