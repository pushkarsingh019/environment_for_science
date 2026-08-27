import { digestTail } from "../app/format";
import type { EnvironmentDraft } from "../types";

/** Details-rail "Draft" section (the rail is hidden in Edit but the identity stays rendered). */
export function DraftIdentity({ draft }: { draft: EnvironmentDraft }) {
  return (
    <dl className="identity-list">
      <div>
        <dt>Draft revision</dt>
        <dd data-testid="draft-identity-revision" title={draft.revision_digest}>
          r{draft.revision} · {digestTail(draft.revision_digest)}
        </dd>
      </div>
      <div>
        <dt>Whole-cap inputs</dt>
        <dd>{draft.apparatus.recording_input_capacity}</dd>
      </div>
    </dl>
  );
}
