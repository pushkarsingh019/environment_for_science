import { useState } from "react";
import type {
  DraftCommandResult,
  DraftProcedure,
  EnvironmentDraft,
  FrozenEnvironment,
} from "../types";

function numberLabel(value: number): string {
  return String(value);
}

function acquisitionSummary(procedure: DraftProcedure) {
  const profile = procedure.acquisition_profile;
  return {
    sampling: `${numberLabel(profile.sampling_hz)} Hz`,
    bandpass: `${numberLabel(profile.online_bandpass_hz[0])}–${numberLabel(profile.online_bandpass_hz[1])} Hz`,
    notch: `${numberLabel(profile.notch_hz)} Hz`,
  };
}

function actorRole(role: EnvironmentDraft["last_change"]["actor"]["role"]): string {
  const labels = {
    authoring_assistant: "Authoring assistant",
    environment_author: "Environment author",
    system: "System",
  };
  return labels[role];
}

function WholeCapVisualization({ draft }: { draft: EnvironmentDraft }) {
  const montage = draft.procedure.montage;
  const recordingSites = new Set(montage.recording_sites);
  const siteRole = (siteId: string) => {
    if (recordingSites.has(siteId)) return "recording";
    if (siteId === montage.reference) return "reference";
    if (siteId === montage.ground) return "ground";
    return "available";
  };

  return (
    <section className="draft-visualization-card" aria-labelledby="draft-visualization-title">
      <div className="section-heading-row draft-visualization-heading">
        <div>
          <p className="eyebrow">Configurable EEG Apparatus</p>
          <h2 id="draft-visualization-title">Whole-cap capability and selected Montage</h2>
        </div>
        <span className="synthetic-label">Schematic only</span>
      </div>

      <div className="whole-cap-layout">
        <div className="whole-cap-stage">
          <div
            aria-label={`Configurable whole-cap EEG Apparatus with ${draft.apparatus.sites.length} possible sites and a distinct Procedure-selected Montage.`}
            className="whole-cap-map"
            data-testid="whole-cap-visualization"
            role="img"
          >
            <span className="head-nasion" aria-hidden="true" />
            <span className="head-ear head-ear-left" aria-hidden="true" />
            <span className="head-ear head-ear-right" aria-hidden="true" />
            {draft.apparatus.sites.map((site) => {
              const role = siteRole(site.id);
              return (
                <span
                  aria-label={`${site.label}: ${role} site`}
                  className={`cap-site is-${role} is-${site.kind}`}
                  data-testid={`apparatus-site-${site.id}`}
                  key={site.id}
                  style={{ left: `${site.x}%`, top: `${site.y}%` }}
                  title={`${site.label} · ${role}`}
                >
                  {site.label}
                </span>
              );
            })}
          </div>
          <div className="cap-legend" aria-label="Whole-cap legend">
            <span><i className="legend-dot is-recording" />Recording</span>
            <span><i className="legend-dot is-reference" />Reference</span>
            <span><i className="legend-dot is-ground" />Ground</span>
            <span><i className="legend-dot is-available" />Apparatus site</span>
          </div>
        </div>

        <div className="montage-summary">
          <p className="eyebrow">Procedure-selected Montage</p>
          <h3>{draft.procedure.name}</h3>
          <dl className="montage-definition">
            <div>
              <dt>Recording sites</dt>
              <dd data-testid="montage-recording-sites">
                {montage.recording_sites.join(", ")}
              </dd>
            </div>
            <div>
              <dt>Reference</dt>
              <dd data-testid="montage-reference">{montage.reference}</dd>
            </div>
            <div>
              <dt>Ground</dt>
              <dd data-testid="montage-ground">{montage.ground}</dd>
            </div>
          </dl>
          <p className="apparatus-boundary">
            The Montage selects sites for this Procedure. It does not define or limit the
            whole-cap Apparatus.
          </p>
        </div>
      </div>

      <p className="scientific-claim" data-testid="scientific-claim">
        <strong>Schematic scientific claim.</strong> {draft.apparatus.scientific_claim}
      </p>
    </section>
  );
}

function SetupDetails({ procedure }: { procedure: DraftProcedure }) {
  const acquisition = acquisitionSummary(procedure);
  return (
    <details className="setup-details" data-testid="setup-details">
      <summary>Setup details</summary>
      <dl className="setup-values" data-testid="setup-values">
        <div><dt>Sampling</dt><dd>{acquisition.sampling}</dd></div>
        <div><dt>Online bandpass</dt><dd>{acquisition.bandpass}</dd></div>
        <div><dt>Notch</dt><dd>{acquisition.notch}</dd></div>
      </dl>
    </details>
  );
}

interface DraftWorkspaceProps {
  draft: EnvironmentDraft;
  busy: boolean;
  result: DraftCommandResult | null;
  onCommand: (command: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  onRestore: () => void;
  onStageNote: (filename: string, content: string) => void;
}

export function DraftWorkspace({
  draft,
  busy,
  result,
  onCommand,
  onUndo,
  onRedo,
  onRestore,
  onStageNote,
}: DraftWorkspaceProps) {
  const [command, setCommand] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);

  function submitCommand(event: React.FormEvent) {
    event.preventDefault();
    const submitted = command.trim();
    if (!submitted || busy) return;
    onCommand(submitted);
    setCommand("");
  }

  async function stageNote(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      setNoteError("Choose a local .txt note. Other file types are not read.");
      return;
    }
    if (file.size > 100_000) {
      setNoteError("Choose a text note no larger than 100,000 bytes.");
      return;
    }
    const content = await file.text();
    if (!content.trim() || content.includes("\0")) {
      setNoteError("Choose a non-empty plain-text note without null characters.");
      return;
    }
    setNoteError(null);
    onStageNote(file.name, content);
  }

  return (
    <div className="draft-workspace" data-testid="draft-workspace">
      <WholeCapVisualization draft={draft} />

      <section className="draft-lower-workspace">
        <section className="authoring-panel" aria-labelledby="authoring-title">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">Draft command</p>
              <h2 id="authoring-title">Revise with the Authoring assistant</h2>
            </div>
            <span
              className="draft-revision"
              data-revision={draft.revision}
              data-testid="draft-revision"
              title={draft.revision_digest}
            >
              Draft r{draft.revision}
            </span>
          </div>

          <form className="command-form" onSubmit={submitCommand}>
            <label htmlFor="draft-command">Describe one scientific draft change</label>
            <textarea
              id="draft-command"
              data-testid="command-composer"
              disabled={busy}
              onChange={(event) => setCommand(event.target.value)}
              placeholder="Add Cz to the Montage"
              rows={3}
              value={command}
            />
            <button
              className="primary-button compact-button"
              data-testid="apply-draft-command"
              disabled={busy || command.trim().length === 0}
              type="submit"
            >
              Apply to draft
            </button>
          </form>
          {busy && <p className="draft-busy" data-testid="draft-busy">Updating draft…</p>}
          {result && (
            <div
              aria-live="polite"
              className={`assistant-result is-${result.status}`}
              data-testid="assistant-result"
            >
              <strong>{result.status === "applied" ? "Applied" : "Unsupported"}</strong>
              <p>{result.summary}</p>
            </div>
          )}

          <div className="last-change-card">
            <p>{draft.last_change.summary}</p>
            <span data-testid="last-change-attribution">
              {actorRole(draft.last_change.actor.role)} · {draft.last_change.actor.name}
            </span>
          </div>

          <div className="history-controls" aria-label="Draft history">
            <button
              className="secondary-button"
              data-testid="undo-draft"
              disabled={busy || !draft.history.can_undo}
              onClick={onUndo}
              type="button"
            >Undo</button>
            <button
              className="secondary-button"
              data-testid="redo-draft"
              disabled={busy || !draft.history.can_redo}
              onClick={onRedo}
              type="button"
            >Redo</button>
            <button
              className="secondary-button"
              data-testid="restore-draft"
              disabled={busy}
              onClick={onRestore}
              type="button"
            >Restore seed</button>
          </div>
        </section>

        <section className="draft-details-panel" aria-labelledby="draft-details-title">
          <p className="eyebrow">Procedure details</p>
          <h2 id="draft-details-title">Configuration and descriptive notes</h2>
          <SetupDetails procedure={draft.procedure} />

          <div className="note-import">
            <h3>Local descriptive note</h3>
            <p>The browser reads one local text file and stages its filename and text only.</p>
            <label className="file-button">
              Choose .txt note
              <input
                accept=".txt,text/plain"
                data-testid="note-file"
                disabled={busy}
                onChange={(event) => void stageNote(event)}
                type="file"
              />
            </label>
            {noteError && <p className="note-error" role="alert">{noteError}</p>}
          </div>

          <div className="draft-notes" aria-label="Staged descriptive notes">
            {draft.notes.length === 0 ? (
              <p className="empty-note">No local notes staged.</p>
            ) : (
              draft.notes.map((note) => (
                <article
                  className="draft-note"
                  data-testid={`draft-note-${note.filename}`}
                  key={note.id}
                >
                  <div><strong>{note.filename}</strong><span>Unverified descriptive input</span></div>
                  <p>{note.content}</p>
                  <small>Cannot control a run.</small>
                </article>
              ))
            )}
          </div>
        </section>
      </section>
    </div>
  );
}

export function FrozenConfigurationPanel({
  frozen,
}: {
  frozen: FrozenEnvironment;
}) {
  const acquisition = acquisitionSummary(frozen.procedure);
  return (
    <section className="frozen-configuration" data-testid="frozen-configuration">
      <p className="eyebrow">Frozen Procedure configuration</p>
      <h2>{frozen.procedure.name}</h2>
      <dl>
        <div><dt>Montage</dt><dd data-testid="frozen-montage">{frozen.procedure.montage.recording_sites.join(", ")}</dd></div>
        <div><dt>Reference / ground</dt><dd>{frozen.procedure.montage.reference} / {frozen.procedure.montage.ground}</dd></div>
        <div><dt>Acquisition</dt><dd>{acquisition.sampling} · {acquisition.bandpass} · {acquisition.notch} notch</dd></div>
      </dl>
      <p>
        Frozen from draft revision{" "}
        <span data-testid="frozen-draft-revision">{frozen.draft_revision}</span>;
        later Edit changes cannot alter this run.
      </p>
    </section>
  );
}
