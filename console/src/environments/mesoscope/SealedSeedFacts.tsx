import type { EnvironmentSummary } from "../../types";

const FACTS: ReadonlyArray<readonly [label: string, value: string]> = [
  [
    "Profiles",
    "Research-paper and commercial reference profiles are visible and locked; their source conventions remain distinct.",
  ],
  ["Signed plan", "R1–R4 · Z-A / Z-B"],
  ["Safety gate", "Independent and immutable"],
];

/** Scene-card footer for the sealed mesoscope seed in Edit mode; nothing here is editable. */
export function SealedSeedFacts({ environment }: { environment: EnvironmentSummary }): JSX.Element {
  return (
    <div className="sealed-facts">
      <p className="sealed-facts-lead">
        <strong>{environment.name}</strong>
        Profiles, signed plans, and the independent safety gate are immutable.
        <span className="state-chip">Read-only seed</span>
      </p>
      {FACTS.map(([label, value]) => (
        <dl className="sealed-fact" key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </dl>
      ))}
    </div>
  );
}
