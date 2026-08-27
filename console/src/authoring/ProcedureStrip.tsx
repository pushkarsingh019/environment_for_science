import { acquisitionSummary } from "../app/format";
import type { EnvironmentDraft } from "../types";
import { NotesList } from "./NotesList";

/** Scene-card footer in EEG Edit: the Procedure's Montage, setup disclosure, and staged notes. */
export function ProcedureStrip({ draft }: { draft: EnvironmentDraft }) {
  const { montage, acquisition_profile: profile } = draft.procedure;
  const acquisition = acquisitionSummary(profile);
  return (
    <div className="procedure-strip" id="procedure-strip">
      <div className="montage-summary">
        <p className="eyebrow">Procedure · {draft.procedure.name}</p>
        <dl className="montage-definition">
          <div>
            <dt>Recording sites</dt>
            <dd data-testid="montage-recording-sites">{montage.recording_sites.join(", ")}</dd>
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
        <p className="scientific-claim" data-testid="scientific-claim">
          <strong>Schematic claim.</strong> {draft.apparatus.scientific_claim}
        </p>
      </div>
      <details className="setup-details" data-testid="setup-details">
        <summary>Setup details</summary>
        <dl className="setup-values" data-testid="setup-values">
          <div>
            <dt>Sampling</dt>
            <dd>{acquisition.sampling}</dd>
          </div>
          <div>
            <dt>Online bandpass</dt>
            <dd>{acquisition.bandpass}</dd>
          </div>
          <div>
            <dt>Notch</dt>
            <dd>{acquisition.notch}</dd>
          </div>
          <div>
            <dt>Whole-cap inputs</dt>
            <dd>{draft.apparatus.recording_input_capacity}</dd>
          </div>
        </dl>
      </details>
      <NotesList notes={draft.notes} />
    </div>
  );
}
