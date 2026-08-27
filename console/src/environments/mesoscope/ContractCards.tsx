import type { MesoscopeHandoffVisualization, MesoscopeProvenance } from "../../types";
import { digestTail, displayName } from "../../app/format";
import type { MesoscopeObservationView } from "./mesoscopeEvidence";

export interface ProvenanceBadgesProps {
  items: MesoscopeProvenance[];
  testId: string;
}

/** `CLASSIFICATION[ids]` badges; the note is exposed as a tooltip. */
export function ProvenanceBadges({ items, testId }: ProvenanceBadgesProps): JSX.Element {
  return (
    <span className="mesoscope-classification-group" data-testid={testId}>
      {items.map((item) => (
        <span
          className="mesoscope-classification"
          key={`${item.classification}-${item.citation_ids.join("-")}`}
          title={item.note}
        >
          {item.classification}
          <small>[{item.citation_ids.join(", ")}]</small>
        </span>
      ))}
    </span>
  );
}

function ImmutableHeading({ title }: { title: string }): JSX.Element {
  return (
    <div className="mesoscope-card-heading">
      <p className="eyebrow">{title}</p>
      <span className="immutable-badge">Immutable</span>
    </div>
  );
}

function lockLabel(selected: boolean): string {
  return `${selected ? "Selected · " : ""}locked`;
}

export interface ContractCardsProps {
  view: MesoscopeObservationView;
  visualization: MesoscopeHandoffVisualization;
}

/** Sealed profile, signed plan, and safety gate; provenance lists stay open so the rail reads top to bottom. */
export function ContractCards({ view, visualization }: ContractCardsProps): JSX.Element {
  const planRegions = view.signed_plan?.regions ?? [];
  const planSummary = planRegions.map((region) => `${region.region_id} ${region.z_label}`).join(" · ");
  const gate = view.safety_gate;

  return (
    <section aria-label="Immutable sealed contract" className="mesoscope-contract-grid">
      <article data-testid="mesoscope-profile-card">
        <ImmutableHeading title="Sealed profile" />
        <h3>{view.sealed_profile?.profile_id ?? "Unavailable"}</h3>
        <p>{view.sealed_profile?.source_geometry ?? "Unavailable"}</p>
        <div className="mesoscope-provenance">
          <p className="mesoscope-provenance-title">
            <span>Profile provenance ({view.profile_catalog.length})</span>
            <ProvenanceBadges
              items={[visualization.profile_provenance]}
              testId="mesoscope-profile-classification"
            />
          </p>
          <ul className="mesoscope-compact-list">
            {view.profile_catalog.map((entry) => (
              <li key={entry.profile_id}>
                <strong>{entry.profile_id}</strong>
                <span>{entry.provenance_label}</span>
                <small>{lockLabel(entry.selected)}</small>
              </li>
            ))}
          </ul>
        </div>
      </article>

      <article data-testid="mesoscope-plan-card">
        <ImmutableHeading title="Signed plan" />
        <h3>{view.signed_plan?.plan_id ?? "Unavailable"}</h3>
        <p>{planSummary === "" ? "Unavailable" : planSummary}</p>
        <div className="mesoscope-provenance">
          <p className="mesoscope-provenance-title">
            <span>Plan signatures ({view.plan_catalog.length})</span>
            <ProvenanceBadges items={[visualization.plan_provenance]} testId="mesoscope-plan-classification" />
          </p>
          <ul className="mesoscope-compact-list">
            {view.plan_catalog.map((entry) => (
              <li key={entry.plan_id}>
                <strong>{entry.plan_id}</strong>
                <span title={entry.signature_digest}>{digestTail(entry.signature_digest)}</span>
                <small>{lockLabel(entry.selected)}</small>
              </li>
            ))}
          </ul>
        </div>
      </article>

      <article data-testid="mesoscope-safety-gate">
        <ImmutableHeading title="Independent safety gate" />
        <h3>{displayName(gate?.state ?? "unavailable")}</h3>
        <p>
          {gate?.independently_enforced === true
            ? "Independently enforced; no bypass or apparatus controls."
            : "Gate state unavailable."}
        </p>
        <dl className="mesoscope-mini-definition">
          <div>
            <dt>Mutable</dt>
            <dd>No</dd>
          </div>
          <div>
            <dt>Hardware connector</dt>
            <dd>None</dd>
          </div>
        </dl>
      </article>
    </section>
  );
}
