import { displayName } from "../app/format";
import type { EnvironmentSummary, ReplayReport, RunSnapshot, VerifierResult } from "../types";

/** Scene-header chip: validation summary and checks behind a disclosure. */
export function ValidationChip({ environment }: { environment: EnvironmentSummary }) {
  return (
    <div className="validation-chip" data-testid="environment-validation">
      <details>
        <summary>
          <span aria-hidden="true" className="status-dot is-ready" />
          Validated
        </summary>
        <div className="validation-popover">
          <p>{environment.validation.summary}</p>
          <ul className="quiet-list">
            {environment.validation.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </div>
      </details>
    </div>
  );
}

function VerifierSummary({ result }: { result: VerifierResult }) {
  const metrics = Object.entries(result.metrics);
  return (
    <div className="result-main" data-testid="verifier-result">
      <strong className={`result-headline is-${result.passed ? "pass" : "fail"}`}>
        {result.passed ? "Verifier passed" : "Verifier did not pass"}
      </strong>
      <dl className="result-facts">
        <div>
          <dt>Disposition</dt>
          <dd data-testid="terminal-disposition">{displayName(result.terminal_disposition)}</dd>
        </div>
        {result.outcome_category && (
          <div>
            <dt>Category</dt>
            <dd data-testid="outcome-category">{displayName(result.outcome_category)}</dd>
          </div>
        )}
      </dl>
      <p>{result.summary}</p>
      <details className="result-explanation" data-testid="verifier-explanation">
        <summary>Why this result</summary>
        {result.reasons.length > 0 ? (
          <ul>
            {result.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p>No blocking reason was recorded.</p>
        )}
        {metrics.length > 0 && (
          <dl className="verifier-metrics">
            {metrics.map(([name, value]) => (
              <div key={name}>
                <dt>{name.replaceAll("_", " ")}</dt>
                <dd>{value.toFixed(2)}</dd>
              </div>
            ))}
          </dl>
        )}
      </details>
    </div>
  );
}

/** Scene-card ribbon under the header: verifier result and replay comparison. */
export function ResultRibbon({ run, replay }: { run: RunSnapshot; replay: ReplayReport | null }) {
  const result = run.verifier_result;
  if (!result && !replay) return null;
  return (
    <div aria-label="Run result" aria-live="polite" className="result-ribbon">
      {result && <VerifierSummary result={result} />}
      {replay && (
        <p className="replay-result" data-testid="replay-result">
          {replay.trace_matches && replay.result_matches
            ? "Trace and result digests match the source run."
            : "Replay diverged from the source run."}
        </p>
      )}
    </div>
  );
}
