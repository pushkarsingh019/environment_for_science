import type { EvaluationReplay } from "../types";
import { InteractionEvidence } from "./InteractionEvidence";
import { SectionCard } from "./evaluationShared";

/** Deterministic replay of one attempt; `null` when a scientific replay lacks its report. */
export function ReplayPanel({ replay }: { replay: EvaluationReplay }): JSX.Element | null {
  if (replay.infrastructure_error) {
    return (
      <SectionCard eyebrow="Replay" id="evaluation-replay" testId="evaluation-replay" title="Infrastructure error">
        <p className="evaluation-lead">{replay.infrastructure_error.summary}</p>
        <code>{replay.infrastructure_error.code}</code>
        <InteractionEvidence interaction={replay.interaction} />
      </SectionCard>
    );
  }
  const report = replay.report;
  const snapshot = replay.snapshot;
  if (!report || !snapshot) return null;
  const bothMatch = report.trace_matches && report.result_matches;
  return (
    <SectionCard
      eyebrow="Replay"
      headerRight={(
        <span className={`evaluation-status ${bothMatch ? "is-completed" : "is-interrupted"}`}>
          {bothMatch ? "Matched" : "Review"}
        </span>
      )}
      id="evaluation-replay"
      testId="evaluation-replay"
      title={bothMatch ? "Trace and scientific result both match" : "Replay mismatch"}
    >
      <p className="evaluation-lead">{snapshot.verifier_result?.summary ?? replay.attempt.summary}</p>
      <dl className="evaluation-checks">
        <div className={report.trace_matches ? "is-met" : "is-unmet"}>
          <dt>Trace</dt><dd>{report.trace_matches ? "Match" : "Mismatch"}</dd>
        </div>
        <div className={report.result_matches ? "is-met" : "is-unmet"}>
          <dt>Result</dt><dd>{report.result_matches ? "Match" : "Mismatch"}</dd>
        </div>
      </dl>
      <InteractionEvidence interaction={replay.interaction} />
    </SectionCard>
  );
}
