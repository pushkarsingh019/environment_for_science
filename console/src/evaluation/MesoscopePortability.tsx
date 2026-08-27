import { useEffect, useState } from "react";
import { portabilityApi } from "../api";
import type { MesoscopePortabilityReplay, MesoscopePortabilityReport } from "../types";
import { digestTail } from "../app/format";
import { ErrorBanner, SectionCard, safeMessage } from "./evaluationShared";

type PortabilityReplayId = MesoscopePortabilityReplay["replay_id"];

/** Mesoscope Evaluate tab: compiler receipt and seeded replay fixtures, no training claim. */
export function MesoscopePortability(): JSX.Element {
  const [report, setReport] = useState<MesoscopePortabilityReport | null>(null);
  const [replay, setReplay] = useState<MesoscopePortabilityReplay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    portabilityApi.mesoscope()
      .then((loaded) => {
        if (active) setReport(loaded);
      })
      .catch((reason: unknown) => {
        if (active) setError(safeMessage(reason, "Unable to load portability evidence."));
      });
    return () => { active = false; };
  }, []);

  async function openReplay(replayId: PortabilityReplayId) {
    setBusy(true);
    setError(null);
    try {
      setReplay(await portabilityApi.replayMesoscope(replayId));
    } catch (reason) {
      setError(safeMessage(reason, "Unable to replay portability evidence."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="mesoscope-evaluation-heading"
      className="workspace-mode-panel evaluation-workspace"
      data-testid="mesoscope-portability-workspace"
      id="evaluation-workspace"
      role="tabpanel"
    >
      <div className="evaluation-intro">
        <div>
          <h1 id="mesoscope-evaluation-heading">Platform-generality evidence</h1>
          <p>
            The sealed synthetic handoff uses the same compiler, Runtime, Verifiers adapter
            contract, canonical trace, and replay lifecycle as EEG.
          </p>
        </div>
        <span className="state-chip">No training claim</span>
      </div>
      {error && <ErrorBanner message={error} />}
      {!report ? (
        <section className="evaluation-card">
          <p className="evaluation-empty">Loading compiler and replay evidence…</p>
        </section>
      ) : (
        <>
          <SectionCard
            eyebrow="Compiler receipt"
            headerRight={<span className="evaluation-status is-completed">Conformant</span>}
            testId="mesoscope-portability-report"
            title={report.compilation.compilation_version}
          >
            <p className="evaluation-lead">{report.fixture_notice}</p>
            <dl className="evaluation-facts">
              <div><dt>Environment</dt><dd>{report.environment_id}</dd></div>
              <div><dt>Generated artifacts</dt><dd>{report.compilation.artifacts.length}</dd></div>
            </dl>
          </SectionCard>
          <SectionCard
            count={report.results.length}
            eyebrow="Fixtures"
            testId="mesoscope-portability-results"
            title="Verified and quarantine handoffs"
          >
            <div className="evaluation-tile-grid">
              {report.results.map((result) => (
                <article className="evaluation-tile" key={result.replay_id}>
                  <div className="evaluation-tile-head">
                    <strong>{result.terminal_summary}</strong>
                  </div>
                  <span>Offline fixture · {result.terminal_disposition}</span>
                  <code title={result.runtime_trace_digest}>{digestTail(result.runtime_trace_digest)}</code>
                  <button
                    className="secondary-button compact-button"
                    data-testid={`portability-replay-${result.replay_id}`}
                    disabled={busy}
                    onClick={() => void openReplay(result.replay_id)}
                    type="button"
                  >
                    Replay
                  </button>
                </article>
              ))}
            </div>
          </SectionCard>
        </>
      )}
      {replay && (
        <SectionCard
          eyebrow="Replay"
          headerRight={(
            <span className={`evaluation-status ${replay.trace_matches && replay.result_matches ? "is-completed" : "is-interrupted"}`}>
              {replay.trace_matches && replay.result_matches ? "Matched" : "Review"}
            </span>
          )}
          testId="mesoscope-portability-replay"
          title={replay.trace_matches && replay.result_matches ? "Trace and result match" : "Replay mismatch"}
        >
          <p className="evaluation-lead">{replay.snapshot.verifier_result?.summary}</p>
        </SectionCard>
      )}
      <p className="evaluation-boundary-note">
        This separate track demonstrates platform portability only. It does not imply
        mesoscope training or cross-Apparatus generalization.
      </p>
    </section>
  );
}
