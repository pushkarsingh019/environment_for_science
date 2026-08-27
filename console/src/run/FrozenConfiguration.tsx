import { acquisitionSummary } from "../app/format";
import type { FrozenEnvironment } from "../types";

/** Details-rail "Procedure" section in EEG Run: the configuration frozen for this run. */
export function FrozenConfiguration({ frozen }: { frozen: FrozenEnvironment }) {
  const { montage, acquisition_profile: profile } = frozen.procedure;
  const acquisition = acquisitionSummary(profile);
  return (
    <section aria-label="Frozen Procedure" className="rail-card" data-testid="frozen-configuration">
      <h3>{frozen.procedure.name}</h3>
      <dl className="identity-list">
        <div>
          <dt>Montage</dt>
          <dd data-testid="frozen-montage">{montage.recording_sites.join(", ")}</dd>
        </div>
        <div>
          <dt>Reference / ground</dt>
          <dd>
            {montage.reference} / {montage.ground}
          </dd>
        </div>
        <div>
          <dt>Acquisition</dt>
          <dd>
            {acquisition.sampling} · {acquisition.bandpass} · {acquisition.notch} notch
          </dd>
        </div>
      </dl>
      <p className="rail-note">
        Frozen from draft revision <span data-testid="frozen-draft-revision">{frozen.draft_revision}</span>;
        later Edit changes cannot alter this run.
      </p>
    </section>
  );
}
