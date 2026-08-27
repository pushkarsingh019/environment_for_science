import type { JsonObject, JsonValue, MesoscopeHandoffVisualization } from "../../types";
import { digestTail, displayName } from "../../app/format";
import { ProvenanceBadges } from "./ContractCards";
import type { MesoscopeObservationView } from "./mesoscopeEvidence";

interface Column {
  key: string;
  label: string;
}

const EXPECTED_OUTPUT_COLUMNS: readonly Column[] = [
  { key: "output_id", label: "Output" },
  { key: "region_id", label: "Region" },
  { key: "z_label", label: "Depth" },
  { key: "channel_id", label: "Channel" },
  { key: "frame_count", label: "Frames" },
];
const EVENT_COLUMNS: readonly Column[] = [
  { key: "sequence_index", label: "Sequence" },
  { key: "event_id", label: "Event" },
  { key: "package_id", label: "Package" },
];
const MOTION_COLUMNS: readonly Column[] = [
  { key: "row_id", label: "Row" },
  { key: "region_id", label: "Region" },
  { key: "z_label", label: "Depth" },
  { key: "channel_id", label: "Channel" },
  { key: "quality_status", label: "Quality" },
];
const MANIFEST_COLUMNS: readonly Column[] = [
  { key: "output_id", label: "Output" },
  { key: "package_id", label: "Package" },
];
const CHECKSUM_COLUMNS: readonly Column[] = [
  { key: "artifact_id", label: "Artifact" },
  { key: "expected_digest", label: "Expected" },
  { key: "computed_digest", label: "Computed" },
  { key: "observed_digest", label: "Observed" },
];

/** Booleans read Yes/No, absent values read —, digests are shortened with the full value as a tooltip. */
function cellText(value: JsonValue | undefined, key: string): { label: string; title: string } {
  if (value === undefined || value === null) return { label: "—", title: "—" };
  if (typeof value === "boolean") {
    const label = value ? "Yes" : "No";
    return { label, title: label };
  }
  const raw = typeof value === "string" ? value : typeof value === "number" ? String(value) : JSON.stringify(value);
  if (raw === "") return { label: "—", title: "—" };
  return { label: key.includes("digest") ? digestTail(raw) : raw, title: raw };
}

function EvidenceTable({
  columns,
  rows,
  testId,
}: {
  columns: readonly Column[];
  rows: JsonObject[];
  testId: string;
}): JSX.Element {
  if (rows.length === 0) return <p className="mesoscope-empty-evidence">Available after mock acquisition.</p>;
  return (
    <div className="mesoscope-table-scroll">
      <table className="mesoscope-evidence-table" data-testid={testId}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${testId}-${rowIndex}`}>
              {columns.map((column) => {
                const cell = cellText(row[column.key], column.key);
                return (
                  <td key={column.key} title={cell.title}>
                    {cell.label}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Disclosure({
  count,
  label,
  testId,
  children,
}: {
  count: number;
  label: string;
  testId: string;
  children: JSX.Element;
}): JSX.Element {
  return (
    <details data-testid={testId}>
      <summary>
        {label} <span>{count}</span>
      </summary>
      {children}
    </details>
  );
}

function ContractChecks({ view }: { view: MesoscopeObservationView }): JSX.Element {
  if (view.package_checks.length === 0) {
    return <p className="mesoscope-empty-evidence">Run package validation to compare every sealed record.</p>;
  }
  return (
    <ul className="mesoscope-check-list">
      {view.package_checks.map((check) => (
        <li className={`is-${check.status}`} key={check.check_id}>
          <span>{displayName(check.check_id)}</span>
          <strong>{displayName(check.status)}</strong>
        </li>
      ))}
    </ul>
  );
}

export interface PackageEvidenceProps {
  view: MesoscopeObservationView;
  visualization: MesoscopeHandoffVisualization;
}

/** Closed disclosure of the six sealed package ledgers; every nested table stays closed until opened. */
export function PackageEvidence({ view, visualization }: PackageEvidenceProps): JSX.Element {
  return (
    <details className="mesoscope-package-evidence" data-testid="mesoscope-package-evidence">
      <summary>
        {visualization.details_toggle_label}
        <ProvenanceBadges items={visualization.package_provenance} testId="mesoscope-evidence-classification" />
      </summary>
      <section aria-label="Sealed package evidence" className="mesoscope-evidence-disclosures">
        <Disclosure count={view.expected_outputs.length} label="Expected outputs" testId="mesoscope-expected-outputs">
          <EvidenceTable
            columns={EXPECTED_OUTPUT_COLUMNS}
            rows={view.expected_outputs}
            testId="mesoscope-expected-output-table"
          />
        </Disclosure>
        <Disclosure count={view.event_records.length} label="Event records" testId="mesoscope-event-records">
          <EvidenceTable columns={EVENT_COLUMNS} rows={view.event_records} testId="mesoscope-event-record-table" />
        </Disclosure>
        <Disclosure count={view.motion_rows.length} label="Motion rows" testId="mesoscope-motion-rows">
          <EvidenceTable columns={MOTION_COLUMNS} rows={view.motion_rows} testId="mesoscope-motion-row-table" />
        </Disclosure>
        <Disclosure count={view.manifest_records.length} label="Package manifest" testId="mesoscope-manifest-records">
          <EvidenceTable columns={MANIFEST_COLUMNS} rows={view.manifest_records} testId="mesoscope-manifest-table" />
        </Disclosure>
        <Disclosure count={view.package_checksums.length} label="Package checksums" testId="mesoscope-checksums">
          <EvidenceTable columns={CHECKSUM_COLUMNS} rows={view.package_checksums} testId="mesoscope-checksum-table" />
        </Disclosure>
        <Disclosure count={view.package_checks.length} label="Contract checks" testId="mesoscope-package-checks">
          <ContractChecks view={view} />
        </Disclosure>
      </section>
    </details>
  );
}
