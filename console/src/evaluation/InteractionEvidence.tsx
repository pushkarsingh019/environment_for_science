import type {
  EvaluationInteraction,
  EvaluationLocalGemmaAttestation,
  EvaluationMessage,
  EvaluationToolResult,
  TraceEvent,
} from "../types";
import { digestTail } from "../app/format";

function eventPayload(event: TraceEvent) {
  switch (event.type) {
    case "observation": return event.observation;
    case "action": return event.action;
    case "transition": return event.transition;
    case "verifier": return event.verifier;
  }
}

function eventLabel(event: TraceEvent): string {
  return event.type[0].toUpperCase() + event.type.slice(1);
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function Heading({ eyebrow, title, count }: { eyebrow: string; title: string; count?: number }) {
  return (
    <div className="section-heading-row">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
      </div>
      {count !== undefined && <span className="evaluation-count">{count}</span>}
    </div>
  );
}

function ServingReceipt({ attestation }: { attestation: EvaluationLocalGemmaAttestation }) {
  const product = attestation.product_distribution;
  return (
    <section data-testid="evaluation-replay-runtime-attestation">
      <Heading
        count={attestation.runtime_distributions.length}
        eyebrow="Serving receipt"
        title="Direct inference stack provenance"
      />
      <div className="evaluation-tile-grid">
        <article className="evaluation-tile">
          <div className="evaluation-tile-head">
            <strong>{attestation.runtime_receipt_id}</strong>
            <code title={attestation.evidence_digest}>{digestTail(attestation.evidence_digest)}</code>
          </div>
          <span>
            CPython {attestation.python_runtime.version}
            {" · "}{attestation.python_runtime.abi_tag}
            {" · "}{attestation.python_runtime.platform}
          </span>
        </article>
        <article className="evaluation-tile">
          <div className="evaluation-tile-head">
            <strong>{product.distribution} {product.version}</strong>
            <code title={product.wheel_sha256}>{digestTail(product.wheel_sha256)}</code>
          </div>
          <span>Verified product wheel and installed RECORD contents</span>
          <span>
            Independent bootstrap{" "}
            <code title={attestation.trusted_bootstrap_sha256}>
              {digestTail(attestation.trusted_bootstrap_sha256)}
            </code>
          </span>
        </article>
      </div>
      <details className="evaluation-disclosure">
        <summary>{attestation.runtime_distributions.length} directly verified serving distributions</summary>
        <ol className="evaluation-evidence-list">
          {attestation.runtime_distributions.map((distribution) => (
            <li key={distribution.distribution}>
              <div>
                <strong>{distribution.distribution} {distribution.version}</strong>
                <span>{distribution.verification}</span>
              </div>
              <p>Import: <code>{distribution.import_origin}</code></p>
              <details>
                <summary>Inspect artifact and installed-file digests</summary>
                <pre>{pretty({
                  wheel_sha256: distribution.wheel_sha256,
                  record_manifest_sha256: distribution.record_manifest_sha256,
                  import_origin_sha256: distribution.import_origin_sha256,
                })}</pre>
              </details>
            </li>
          ))}
        </ol>
      </details>
      <p className="evaluation-lead">
        Direct serving stack and product wheel verified on a
        {" "}{attestation.serving_root_filesystem_mode}; Python uses
        {" "}{attestation.python_bytecode_mode}. Complete transitive closure and the
        pre-exec service envelope remain operator-supplied immutable-image provenance.
      </p>
    </section>
  );
}

function RuntimeEvents({ interaction }: { interaction: EvaluationInteraction }) {
  return (
    <section data-testid="evaluation-replay-runtime-events">
      <Heading
        count={interaction.runtime_events.length}
        eyebrow="Runtime events"
        title="Observations, actions, transitions, and verification"
      />
      <details className="evaluation-disclosure">
        <summary>{interaction.runtime_events.length} recorded events</summary>
        <ol className="evaluation-evidence-list">
          {interaction.runtime_events.map((event) => (
            <li key={event.sequence}>
              <div>
                <span>#{event.sequence}</span>
                <strong>{eventLabel(event)}</strong>
              </div>
              <p>{event.summary}</p>
              <details>
                <summary>Inspect canonical payload</summary>
                <pre>{pretty(eventPayload(event))}</pre>
              </details>
            </li>
          ))}
        </ol>
      </details>
      <div className="evaluation-execution-ledger" data-testid="evaluation-replay-executions">
        <Heading
          count={interaction.runtime_executions.length}
          eyebrow="Execution ledger"
          title="Accepted actions, observations, and idempotency evidence"
        />
        <details className="evaluation-disclosure">
          <summary>{interaction.runtime_executions.length} accepted actions</summary>
          <ol className="evaluation-evidence-list">
            {interaction.runtime_executions.map((execution) => (
              <li key={execution.execution_id}>
                <div>
                  <span>Ordinal {execution.ordinal}</span>
                  <strong>{execution.action.type}</strong>
                </div>
                <p>Canonical: <code>{execution.call_id}</code></p>
                <p>
                  Execution: <code>{execution.execution_id}</code>
                  {" · "}Cache: {execution.cache_hit ? "hit" : "miss"}
                  {" · "}Retries: {execution.retry_count}
                </p>
                <p>
                  Resulting status: {execution.resulting_status}
                  {" · "}Trace: <code>{execution.resulting_trace_digest}</code>
                </p>
                <details>
                  <summary>Inspect action and observation</summary>
                  <pre>{pretty({ action: execution.action, observation: execution.observation })}</pre>
                </details>
              </li>
            ))}
          </ol>
        </details>
      </div>
    </section>
  );
}

function MessageItem({
  message,
  results,
}: {
  message: EvaluationMessage;
  results: Map<string, EvaluationToolResult>;
}) {
  return (
    <li>
      <header>
        <strong>{message.role}</strong>
        {message.response_id && (
          <code>Response turn {message.response_turn}: {message.response_id}</code>
        )}
        {message.tool_call_id && (
          <code>
            Canonical ordinal {message.tool_call_ordinal}: {message.tool_call_id}
            {" · "}Provider: {message.provider_tool_call_id}
          </code>
        )}
      </header>
      <pre>{typeof message.content === "string" ? message.content : pretty(message.content)}</pre>
      {message.tool_calls.map((call) => {
        const result = results.get(call.call_id);
        return (
          <div className="evaluation-call-lineage" key={call.call_id}>
            <div>
              <code>Canonical ordinal {call.ordinal}: {call.call_id}</code>
              <code>Provider: {call.provider_call_id}</code>
              <strong>{call.name}</strong>
              <span>Result: {result?.status ?? "missing"}</span>
            </div>
            {result?.execution_id && (
              <div>
                <code>Execution: {result.execution_id}</code>
                <span>Cache: {result.cache_hit ? "hit" : "miss"} · Retries: {result.retry_count}</span>
              </div>
            )}
            <pre>{pretty(call.arguments)}</pre>
            {result && (
              <details>
                <summary>Inspect linked result</summary>
                <pre>{pretty(result)}</pre>
              </details>
            )}
          </div>
        );
      })}
    </li>
  );
}

function ModelInteraction({ interaction }: { interaction: EvaluationInteraction }) {
  const results = new Map(interaction.tool_results.map((result) => [result.call_id, result]));
  return (
    <section data-testid="evaluation-replay-interaction">
      <Heading
        count={interaction.messages.length}
        eyebrow="Model interaction"
        title="Messages, tool calls, and linked results"
      />
      <div className="evaluation-tile-grid" data-testid="evaluation-replay-budget">
        <article className="evaluation-tile">
          <div className="evaluation-tile-head">
            <strong>Episode budget</strong>
            <code>{interaction.budgets.max_episode_seconds} seconds</code>
          </div>
          <span>
            {interaction.budgets.max_turns} turns
            {" · "}{interaction.budgets.max_tool_calls} tool calls
            {" · "}{interaction.sampling.max_output_tokens} output tokens per response
          </span>
        </article>
      </div>
      <div className="evaluation-tile-grid" data-testid="evaluation-replay-responses">
        {interaction.responses.map((response) => (
          <article className="evaluation-tile" key={response.response_id}>
            <div className="evaluation-tile-head">
              <strong>Turn {response.turn}</strong>
              <code>{response.response_id}</code>
            </div>
            <span>
              Finish: {response.metadata?.finish_reason ?? "not reported"}
              {" · "}Tokens: {response.usage?.total_tokens ?? "not reported"}
            </span>
          </article>
        ))}
      </div>
      <details className="evaluation-disclosure">
        <summary>{interaction.messages.length} messages</summary>
        <ol className="evaluation-message-list">
          {interaction.messages.map((message, index) => (
            <MessageItem
              key={`${index}-${message.role}-${message.tool_call_id ?? "message"}`}
              message={message}
              results={results}
            />
          ))}
        </ol>
      </details>
    </section>
  );
}

/** Serving receipt, runtime events, execution ledger, and model messages for one replayed attempt. */
export function InteractionEvidence({ interaction }: { interaction: EvaluationInteraction }): JSX.Element {
  const attestation = interaction.run.local_gemma_attestation;
  return (
    <div className="evaluation-interaction-evidence">
      {attestation && <ServingReceipt attestation={attestation} />}
      <RuntimeEvents interaction={interaction} />
      <ModelInteraction interaction={interaction} />
    </div>
  );
}
