import { DevelopmentEvaluation } from "./DevelopmentEvaluation";
import { HostedReferences } from "./HostedReferences";
import { MesoscopePortability } from "./MesoscopePortability";
import { ModelComparisonPanel } from "./ModelComparisonPanel";
import { TrainingJobs } from "./TrainingJobs";

export { EvaluationBoundary } from "./EvaluationBoundary";

/** Results first, then the runs and jobs that produced them. */
function EegEvaluation(): JSX.Element {
  return (
    <section
      aria-labelledby="evaluation-heading"
      className="workspace-mode-panel evaluation-workspace"
      data-testid="evaluation-workspace"
      id="evaluation-workspace"
      role="tabpanel"
    >
      <h1 className="sr-only" id="evaluation-heading">
        Evaluate
      </h1>
      <ModelComparisonPanel />
      <DevelopmentEvaluation />
      <HostedReferences />
      <TrainingJobs />
      <p className="evaluation-boundary-note">
        Evaluation is read-only in the Scientist Console. The Policy agent receives only declared
        simulated-Apparatus actions; endpoint and credential material never enter this view or its
        canonical records.
      </p>
    </section>
  );
}

export function EvaluationWorkspace({
  environmentKind = "eeg",
}: {
  environmentKind?: "eeg" | "mesoscope";
}): JSX.Element {
  return environmentKind === "mesoscope" ? <MesoscopePortability /> : <EegEvaluation />;
}
