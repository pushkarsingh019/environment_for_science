import { useState } from "react";
import type { FormEvent } from "react";
import { actorRole } from "../app/format";
import { BarLabel } from "../shell/BottomBar";
import type { DraftCommandResult, EnvironmentDraft } from "../types";

interface AuthoringComposerProps {
  draft: EnvironmentDraft | null;
  busy: boolean;
  result: DraftCommandResult | null;
  onCommand: (command: string) => void;
}

function LastChange({ draft }: { draft: EnvironmentDraft | null }) {
  if (!draft) return <>Loading draft…</>;
  return (
    <span data-testid="last-change-attribution">
      {actorRole(draft.last_change.actor.role)} · {draft.last_change.summary}
    </span>
  );
}

function AssistantResult({ result }: { result: DraftCommandResult }) {
  return (
    <span
      aria-live="polite"
      className={`assistant-result is-${result.status}`}
      data-testid="assistant-result"
      title={result.summary}
    >
      <strong>{result.status === "applied" ? "Applied" : "Unsupported"}</strong> {result.summary}
    </span>
  );
}

/** Bottom-bar left group in Edit mode: one-line command composer for the editable draft. */
export function AuthoringComposer({ draft, busy, result, onCommand }: AuthoringComposerProps) {
  const [command, setCommand] = useState("");
  const locked = busy || draft === null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitted = command.trim();
    if (!submitted || locked) return;
    onCommand(submitted);
    setCommand("");
  }

  return (
    <form className="authoring-composer" onSubmit={submit}>
      <BarLabel
        caption={<LastChange draft={draft} />}
        dot="assistant"
        extra={result && <AssistantResult result={result} />}
        title="Authoring assistant"
      />
      <label className="sr-only" htmlFor="draft-command">
        Describe one change
      </label>
      <input
        autoComplete="off"
        className="composer-input"
        data-testid="command-composer"
        disabled={locked}
        id="draft-command"
        maxLength={240}
        onChange={(event) => setCommand(event.target.value)}
        placeholder="Add Cz to the Montage"
        type="text"
        value={command}
      />
      <button
        className="secondary-button"
        data-testid="apply-draft-command"
        disabled={locked || command.trim() === ""}
        type="submit"
      >
        Apply
      </button>
      {busy && (
        <span className="bar-busy" data-testid="draft-busy">
          Updating…
        </span>
      )}
    </form>
  );
}

/** Bottom-bar left group when the assistant has no role on the current screen. */
export function AssistantAbsent({ caption }: { caption: "Not in this run" | "Not in evaluation" }) {
  return <BarLabel caption={caption} dot="assistant" title="Authoring assistant" />;
}

/** Bottom-bar left group for the sealed mesoscope seed, which has no editable draft. */
export function SealedAuthoringNote() {
  return <BarLabel caption="No draft edits" dot="assistant" title="Sealed seed" />;
}
