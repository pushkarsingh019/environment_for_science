import type { SealedEnvironment } from "../../types";
import { digestTail } from "../../app/format";

/** Rail card for the frozen sealed seed; the revision digest sits behind a closed disclosure. */
export function SealedFrozenIdentity({ frozen }: { frozen: SealedEnvironment }): JSX.Element {
  return (
    <section aria-label="Sealed run identity" className="rail-card sealed-frozen-identity" data-testid="sealed-frozen-identity">
      <dl className="identity-list">
        <div>
          <dt>Profile</dt>
          <dd title={frozen.sealed_profile_id}>{frozen.sealed_profile_id}</dd>
        </div>
        <div>
          <dt>Signed plan</dt>
          <dd title={frozen.signed_plan_id}>{frozen.signed_plan_id}</dd>
        </div>
      </dl>
      <details className="rail-details">
        <summary>Details</summary>
        <dl className="identity-list">
          <div>
            <dt>Revision</dt>
            <dd title={frozen.revision_digest}>{digestTail(frozen.revision_digest)}</dd>
          </div>
        </dl>
      </details>
    </section>
  );
}
