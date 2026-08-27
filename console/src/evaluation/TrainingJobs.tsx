import { useEffect, useState } from "react";
import { trainingApi } from "../api";
import type { CurriculumTrainingJob, TrainingAcceptanceJob } from "../types";
import { digestTail } from "../app/format";
import { ErrorBanner, SectionCard, safeMessage, trainingStatusLabel } from "./evaluationShared";

interface JobQueue<Job> {
  jobs: Job[];
  busy: boolean;
  loaded: boolean;
  error: string | null;
  operate: (operation: () => Promise<Job>) => Promise<void>;
}

/** The read-only slice `JobShell` renders; independent of the job type. */
type JobQueueView = Pick<JobQueue<never>, "busy" | "loaded" | "error"> & { jobs: readonly unknown[] };

/** Shared list/merge/operate flow for both workstation job queues. */
function useJobQueue<Job extends { job_id: string }>(
  list: () => Promise<Job[]>,
  loadFallback: string,
  operateFallback: string,
): JobQueue<Job> {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    list()
      .then((items) => {
        if (active) {
          setJobs(items);
          setLoaded(true);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(safeMessage(reason, loadFallback));
      });
    return () => { active = false; };
    // The api functions and fallback strings are module constants.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function operate(operation: () => Promise<Job>) {
    setBusy(true);
    setError(null);
    try {
      const job = await operation();
      setJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
    } catch (reason) {
      setError(safeMessage(reason, operateFallback));
    } finally {
      setBusy(false);
    }
  }

  return { jobs, busy, loaded, error, operate };
}

function JobPanel({
  title,
  eyebrow,
  testId,
  launchTestId,
  launchLabel,
  onLaunch,
  queue,
  lead,
  empty,
  children,
}: {
  title: string;
  eyebrow: string;
  testId: string;
  launchTestId: string;
  launchLabel: string;
  onLaunch: () => void;
  /** Only the presentational fields, so both job queues fit regardless of job type. */
  queue: JobQueueView;
  lead: string;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <section className="evaluation-subcard" data-testid={testId}>
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
        </div>
        <button
          className="secondary-button compact-button"
          data-testid={launchTestId}
          disabled={queue.busy || !queue.loaded}
          onClick={onLaunch}
          type="button"
        >
          {launchLabel}
        </button>
      </div>
      <p className="evaluation-lead">{lead}</p>
      {queue.error && <ErrorBanner message={queue.error} />}
      {queue.jobs.length === 0
        ? <p className="evaluation-empty">{empty}</p>
        : <div className="evaluation-tile-grid">{children}</div>}
    </section>
  );
}

function CurriculumTrainingPanel() {
  const queue = useJobQueue<CurriculumTrainingJob>(
    trainingApi.listCurriculumJobs,
    "Unable to load curriculum training.",
    "The curriculum training operation failed.",
  );
  return (
    <JobPanel
      empty="No full-curriculum job has been queued."
      eyebrow="Workstation queue"
      launchLabel="Queue curriculum training"
      launchTestId="launch-curriculum-training"
      lead="Training and model inference stay on approved GPU workstations. The held-out split remains sealed until the final adapter and evaluation configuration are fixed."
      onLaunch={() => void queue.operate(() => trainingApi.launchCurriculumJob())}
      queue={queue}
      testId="curriculum-training-panel"
      title="Curriculum training"
    >
      {queue.jobs.map((job) => (
        <article className="evaluation-tile" data-testid={`curriculum-job-${job.status}`} key={job.job_id}>
          <div className="evaluation-tile-head">
            <strong>{trainingStatusLabel(job.status)}</strong>
            <code>{job.job_id}</code>
          </div>
          <span>{job.message}</span>
          <small>
            Frozen split counts: {job.training_scenarios} / {job.development_scenarios} / {job.heldout_scenarios}
          </small>
          {job.status === "queued" && (
            <div className="evaluation-tile-actions">
              <button
                className="secondary-button compact-button"
                disabled={queue.busy}
                onClick={() => void queue.operate(() => trainingApi.beginCurriculumJob(job.job_id))}
                type="button"
              >
                Record curriculum start
              </button>
            </div>
          )}
          {job.result_digest && (
            <small>Result <code title={job.result_digest}>{digestTail(job.result_digest)}</code></small>
          )}
        </article>
      ))}
    </JobPanel>
  );
}

const ACCEPTANCE_ACTIONS: ReadonlyArray<{
  status: TrainingAcceptanceJob["status"];
  label: string;
  run: (jobId: string) => Promise<TrainingAcceptanceJob>;
}> = [
  { status: "queued", label: "Record workstation start", run: trainingApi.beginAcceptanceJob },
  { status: "running", label: "Verify imported evidence", run: trainingApi.verifyAcceptanceJob },
  { status: "failed", label: "Retry after replacing evidence", run: trainingApi.retryAcceptanceJob },
];

function AcceptanceEvidence({ job }: { job: TrainingAcceptanceJob }) {
  const evidence = job.evidence;
  if (!evidence) return null;
  const metrics = evidence.optimization_metrics;
  return (
    <details className="evaluation-disclosure" data-testid="training-acceptance-evidence">
      <summary>Inspect verified adapter and reload evidence</summary>
      <dl className="evaluation-facts">
        <div><dt>Model</dt><dd>{evidence.model}</dd></div>
        <div><dt>Changed tensors</dt><dd>{evidence.changed_adapter_tensors}</dd></div>
        <div>
          <dt>Finite loss / gradient / KL</dt>
          <dd>{metrics.loss} / {metrics.gradient_norm} / {metrics.mismatch_kl}</dd>
        </div>
        <div><dt>Reload identity</dt><dd>{evidence.reloaded_served_identity}</dd></div>
      </dl>
      <code title={evidence.artifact_digest}>{digestTail(evidence.artifact_digest)}</code>
    </details>
  );
}

function TrainingAcceptancePanel() {
  const queue = useJobQueue<TrainingAcceptanceJob>(
    trainingApi.listAcceptanceJobs,
    "Unable to load training jobs.",
    "The training job operation failed.",
  );
  return (
    <JobPanel
      empty="No bounded acceptance job has been queued."
      eyebrow="Bounded acceptance"
      launchLabel="Queue acceptance job"
      launchTestId="launch-training-acceptance"
      lead="The console coordinates evidence only. Model inference and optimization run on the two approved GPU workstations, never on this computer."
      onLaunch={() => void queue.operate(() => trainingApi.launchAcceptanceJob())}
      queue={queue}
      testId="training-acceptance-panel"
      title="Acceptance job"
    >
      {queue.jobs.map((job) => {
        const action = ACCEPTANCE_ACTIONS.find((item) => item.status === job.status);
        return (
          <article className="evaluation-tile" data-testid={`training-job-${job.status}`} key={job.job_id}>
            <div className="evaluation-tile-head">
              <strong>{trainingStatusLabel(job.status)}</strong>
              <code>{job.job_id}</code>
            </div>
            <span>{job.message}</span>
            <small>Sanitized artifact reference: {job.artifact_reference}</small>
            {action && (
              <div className="evaluation-tile-actions">
                <button
                  className="secondary-button compact-button"
                  disabled={queue.busy}
                  onClick={() => void queue.operate(() => action.run(job.job_id))}
                  type="button"
                >
                  {action.label}
                </button>
              </div>
            )}
            <AcceptanceEvidence job={job} />
          </article>
        );
      })}
    </JobPanel>
  );
}

/** Workstation-only training queues: curriculum training and bounded acceptance. */
export function TrainingJobs(): JSX.Element {
  return (
    <SectionCard eyebrow="Workstations" title="Training jobs">
      <div className="evaluation-subcard-grid">
        <CurriculumTrainingPanel />
        <TrainingAcceptancePanel />
      </div>
    </SectionCard>
  );
}
