import { useEffect, useState } from "react";
import { comparisonApi } from "../api";
import type {
  ComparisonFixtureState,
  ComparisonModelResult,
  ComparisonReplay,
  ModelComparisonResult,
} from "../types";
import { digestTail, displayName, percent } from "../app/format";
import { ComparisonChart } from "./ComparisonChart";
import { COMPARISON_FIXTURES, ErrorBanner, SectionCard, safeMessage } from "./evaluationShared";

const CLAIM_HEADLINES: Record<ModelComparisonResult["training_claim"], string> = {
  improved: "Improvement supported",
  regressed: "Regression observed",
  inconclusive: "No supported training win",
  unavailable: "Training contrast unavailable",
};

function SourceNotice({ comparison }: { comparison: ModelComparisonResult }) {
  if (comparison.fixture_notice) {
    return (
      <div className="comparison-notice is-fixture" data-testid="comparison-fixture-notice">
        <strong>Offline fixture</strong>
        <span>{comparison.fixture_notice}</span>
      </div>
    );
  }
  const digest = comparison.training_artifact_digest;
  return (
    <div className="comparison-notice is-real" data-testid="comparison-real-notice">
      <strong>Verified real evaluation</strong>
      <span>Imported evaluator-owned held-out evidence; no fixture or hosted score was substituted.</span>
      <small>
        <code>{comparison.training_result_id}</code>
        {digest && <code title={digest}>{digestTail(digest)}</code>}
      </small>
    </div>
  );
}

function ClaimCard({ comparison }: { comparison: ModelComparisonResult }) {
  const contrast = comparison.gemma_contrast;
  return (
    <article
      className={`comparison-claim is-${comparison.training_claim}`}
      data-testid={`comparison-claim-${comparison.training_claim}`}
    >
      <p className="eyebrow">Claim</p>
      <strong>{CLAIM_HEADLINES[comparison.training_claim]}</strong>
      {contrast && (
        <span>
          Trained − base success: {percent(contrast.trained_minus_base)}; 95% paired
          bootstrap interval {percent(contrast.interval_low)} to {percent(contrast.interval_high)}.
        </span>
      )}
    </article>
  );
}

function ModelCard({
  model,
  busy,
  onReplay,
}: {
  model: ComparisonModelResult;
  busy: boolean;
  onReplay: (route: string) => void;
}) {
  const metrics = model.metrics;
  return (
    <article className="comparison-model-card" data-testid={`comparison-model-${model.role}`}>
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">{model.reference_model ? "Reference model" : "Gemma evidence"}</p>
          <h3>{model.label}</h3>
        </div>
        <span className={`comparison-status is-${model.status}`}>{model.status.replaceAll("_", " ")}</span>
      </div>
      <div className="comparison-model-facts">
        <small>Requested: {model.requested_model}</small>
        <small>Returned: {model.returned_model ?? "Unavailable"}</small>
        {model.adapter_identity && <small>Adapter: {model.adapter_identity}</small>}
      </div>
      {model.failure ? (
        <div className="comparison-failure" data-testid={`comparison-failure-${model.role}`}>
          <strong>{model.failure.category} failure</strong>
          <span>{model.failure.summary}</span>
        </div>
      ) : metrics ? (
        <>
          <dl className="comparison-metrics">
            <div><dt>Task success</dt><dd>{percent(metrics.task_success)}</dd></div>
            <div><dt>Verifier score</dt><dd>{percent(metrics.verifier_score)}</dd></div>
            <div><dt>Abort precision</dt><dd>{percent(metrics.abort_precision)}</dd></div>
            <div><dt>Abort recall</dt><dd>{percent(metrics.abort_recall)}</dd></div>
            <div><dt>Mean actions</dt><dd>{metrics.mean_action_count.toFixed(1)}</dd></div>
            <div><dt>Tool errors</dt><dd>{metrics.tool_errors}</dd></div>
          </dl>
          <details className="evaluation-disclosure">
            <summary>Strata and {model.scenarios.length} constituent scenarios</summary>
            <dl className="comparison-metrics">
              {Object.entries(metrics.strata).map(([name, stratum]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{stratum.count} · {percent(stratum.task_success)}</dd>
                </div>
              ))}
            </dl>
            <div className="comparison-scenario-list">
              {model.scenarios.map((scenario) => (
                <button
                  className={`comparison-scenario ${scenario.success ? "is-success" : "is-failure"}`}
                  disabled={busy}
                  key={scenario.scenario_id}
                  onClick={() => onReplay(scenario.replay_route)}
                  type="button"
                >
                  {scenario.scenario_id} · {scenario.success ? "success" : "not successful"}
                </button>
              ))}
            </div>
          </details>
        </>
      ) : null}
      <details className="evaluation-disclosure">
        <summary>Model and run provenance</summary>
        <dl className="evaluation-facts">
          <div><dt>Configuration</dt><dd><code>{model.model_configuration_digest}</code></dd></div>
          <div><dt>Run</dt><dd><code>{model.run_id}</code></dd></div>
          {model.adapter_digest && (
            <div><dt>Adapter</dt><dd><code>{model.adapter_digest}</code></dd></div>
          )}
        </dl>
      </details>
    </article>
  );
}

function ReplayReceipt({
  replay,
  models,
}: {
  replay: ComparisonReplay;
  models: ComparisonModelResult[];
}) {
  const label = models.find((model) => model.role === replay.model_role)?.label
    ?? displayName(replay.model_role);
  const digests: Array<[string, string | null]> = [
    ["Configuration", replay.model_configuration_digest],
    ["Adapter", replay.adapter_digest],
    ["Training artifact", replay.training_artifact_digest],
    ["Runtime trace", replay.scenario.runtime_trace_digest],
    ["Result", replay.scenario.result_digest],
  ];
  return (
    <article className="comparison-receipt" data-testid="comparison-replay">
      <p className="eyebrow">Canonical replay receipt</p>
      <strong>{label} · {replay.scenario.scenario_id}</strong>
      <span>
        {replay.reproducible
          ? `Canonical evaluator snapshot loaded (${replay.canonical_snapshot?.trace.length ?? 0} trace events).`
          : "Offline fixture receipt only; no real canonical trace is claimed."}
      </span>
      <details className="evaluation-disclosure">
        <summary>Digests</summary>
        <dl className="evaluation-facts">
          {digests.map(([name, digest]) => digest && (
            <div key={name}><dt>{name}</dt><dd><code>{digest}</code></dd></div>
          ))}
        </dl>
      </details>
    </article>
  );
}

/** Results poster for the four-model held-out comparison, with offline fixture states. */
export function ModelComparisonPanel(): JSX.Element {
  const [comparison, setComparison] = useState<ModelComparisonResult | null>(null);
  const [replay, setReplay] = useState<ComparisonReplay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    comparisonApi.current()
      .then((result) => { if (active) setComparison(result); })
      .catch((reason: unknown) => {
        if (active) setError(safeMessage(reason, "Unable to load model comparison."));
      });
    return () => { active = false; };
  }, []);

  async function chooseFixture(state: ComparisonFixtureState) {
    setBusy(true);
    setError(null);
    setReplay(null);
    try {
      setComparison(await comparisonApi.selectFixture(state));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to select comparison evidence."));
    } finally {
      setBusy(false);
    }
  }

  async function openReplay(route: string) {
    setBusy(true);
    setError(null);
    try {
      setReplay(await comparisonApi.replay(route));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to replay that scenario."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      eyebrow="Held-out comparison"
      testId="model-comparison-panel"
      title="Results · 64 held-out scenarios"
    >
      {error && <ErrorBanner message={error} />}
      {!comparison ? (
        <p className="evaluation-empty">Loading comparison evidence…</p>
      ) : (
        <>
          <SourceNotice comparison={comparison} />
          <ClaimCard comparison={comparison} />
          <ComparisonChart comparison={comparison} />
          <div aria-label="Offline comparison states" className="comparison-fixture-row" role="group">
            <span className="comparison-fixture-label">Seeded states</span>
            {COMPARISON_FIXTURES.map((fixture) => (
              <button
                className="secondary-button compact-button"
                data-testid={`comparison-fixture-${fixture.value}`}
                disabled={busy || comparison.fixture_state === fixture.value}
                key={fixture.value}
                onClick={() => void chooseFixture(fixture.value)}
                type="button"
              >
                {fixture.label}
              </button>
            ))}
          </div>
          <div className="comparison-model-grid">
            {comparison.models.map((model) => (
              <ModelCard busy={busy} key={model.role} model={model} onReplay={(route) => void openReplay(route)} />
            ))}
          </div>
          {replay && <ReplayReceipt models={comparison.models} replay={replay} />}
          <article className="comparison-track" data-testid="mesoscope-generality-track">
            <p className="eyebrow">Separate evidence track</p>
            <h3>{comparison.mesoscope.label}</h3>
            <p>
              Compiler portability only. This is not EEG training evidence and does not imply
              cross-Apparatus learning.
            </p>
          </article>
        </>
      )}
    </SectionCard>
  );
}
