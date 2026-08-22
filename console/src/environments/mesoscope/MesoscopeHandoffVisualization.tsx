import type {
  EnvironmentSummary,
  JsonObject,
  JsonValue,
  MesoscopeProvenance,
  RunSnapshot,
  TraceEvent,
} from "../../types";

function asObject(value: JsonValue | undefined): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function asObjects(value: JsonValue | undefined): JsonObject[] {
  return Array.isArray(value)
    ? value
      .map((item) => asObject(item))
      .filter((item) => Object.keys(item).length > 0)
    : [];
}

function text(value: JsonValue | undefined, fallback = "Unavailable"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function finiteNumber(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function boolean(value: JsonValue | undefined): boolean {
  return value === true;
}

function displayName(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function digestTail(value: string): string {
  return value.startsWith("sha256:") && value.length > 28
    ? `${value.slice(0, 14)}…${value.slice(-8)}`
    : value;
}

function ProvenanceBadges({
  items,
  testId,
}: {
  items: MesoscopeProvenance[];
  testId: string;
}) {
  return (
    <span className="source-classification-group" data-testid={testId}>
      {items.map((item) => (
        <span
          className="source-classification"
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

function deterministicPoints(seed: number): Array<{
  x: number;
  y: number;
  radius: number;
  opacity: number;
}> {
  let state = Math.abs(Math.trunc(seed)) || 1;
  const next = () => {
    state = (state * 48271) % 2147483647;
    return state / 2147483647;
  };
  return Array.from({ length: 20 }, () => ({
    x: 8 + next() * 84,
    y: 8 + next() * 84,
    radius: 2.5 + next() * 6.5,
    opacity: 0.24 + next() * 0.46,
  }));
}

function ProceduralTile({
  expectedZ,
  regionId,
  tile,
}: {
  expectedZ: string;
  regionId: string;
  tile: JsonObject | undefined;
}) {
  const missing = tile === undefined;
  const observedZ = missing ? expectedZ : text(tile.z_label);
  const status = missing ? "missing" : text(tile.status);
  const mismatch = missing || observedZ !== expectedZ;
  const seed = missing ? null : finiteNumber(tile.tile_seed);
  const points = seed === null ? [] : deterministicPoints(seed);

  return (
    <article
      className={`mesoscope-tile${mismatch ? " is-mismatch" : ""}`}
      data-status={status}
      data-testid={`mesoscope-tile-${regionId}`}
      data-z-label={observedZ}
    >
      <div className="mesoscope-tile-heading">
        <strong>{regionId}</strong>
        <span>{observedZ}</span>
      </div>
      <svg
        aria-label={missing
          ? `${regionId} ${expectedZ} synthetic tile is missing.`
          : `${regionId} ${observedZ} deterministic synthetic procedural tile, status ${status}.`}
        className="mesoscope-tile-image"
        role="img"
        viewBox="0 0 100 100"
      >
        <rect className="mesoscope-tile-field" height="100" width="100" />
        {!missing && seed !== null && points.map((point, index) => (
          <circle
            className={index % 3 === 0 ? "mesoscope-cell is-accent" : "mesoscope-cell"}
            cx={point.x}
            cy={point.y}
            key={`${seed}-${index}`}
            opacity={point.opacity}
            r={point.radius}
          />
        ))}
        {!missing && seed !== null && (
          <path
            className="mesoscope-tile-trace"
            d={`M0 ${60 + (seed % 7)} C18 42, 28 76, 44 52 S70 35, 100 ${48 + (seed % 9)}`}
          />
        )}
        {missing && (
          <>
            <path className="mesoscope-missing-mark" d="M28 28 L72 72 M72 28 L28 72" />
            <text className="mesoscope-missing-label" x="50" y="88">MISSING</text>
          </>
        )}
      </svg>
      <footer>
        <span>{displayName(status)}</span>
        <span>{mismatch ? "Contract mismatch" : "Synthetic only"}</span>
      </footer>
    </article>
  );
}

function ContractCards({
  observation,
  planProvenance,
  profileProvenance,
}: {
  observation: JsonObject;
  planProvenance: MesoscopeProvenance;
  profileProvenance: MesoscopeProvenance;
}) {
  const profile = asObject(observation.sealed_profile);
  const profileCatalog = asObjects(observation.profile_catalog);
  const plan = asObject(observation.signed_plan);
  const planCatalog = asObjects(observation.plan_catalog);
  const regions = asObjects(plan.regions);
  const gate = asObject(observation.safety_gate);

  return (
    <section className="mesoscope-contract-grid" aria-label="Immutable sealed contract">
      <article data-testid="mesoscope-profile-card">
        <div className="mesoscope-card-heading">
          <p className="eyebrow">Sealed profile</p>
          <span className="immutable-badge">Immutable</span>
        </div>
        <h3>{text(profile.profile_id)}</h3>
        <p>{text(profile.source_geometry)}</p>
        <details>
          <summary>
            Profile provenance ({profileCatalog.length})
            <ProvenanceBadges
              items={[profileProvenance]}
              testId="mesoscope-profile-classification"
            />
          </summary>
          <ul className="mesoscope-compact-list">
            {profileCatalog.map((entry) => (
              <li key={text(entry.profile_id)}>
                <strong>{text(entry.profile_id)}</strong>
                <span>{text(entry.provenance_label)}</span>
                <small>{boolean(entry.selected) ? "Selected · " : ""}locked</small>
              </li>
            ))}
          </ul>
        </details>
      </article>

      <article data-testid="mesoscope-plan-card">
        <div className="mesoscope-card-heading">
          <p className="eyebrow">Signed plan</p>
          <span className="immutable-badge">Immutable</span>
        </div>
        <h3>{text(plan.plan_id)}</h3>
        <p>{regions.map((region) => `${text(region.region_id)} ${text(region.z_label)}`).join(" · ") || "Unavailable"}</p>
        <details>
          <summary>
            Plan signatures ({planCatalog.length})
            <ProvenanceBadges
              items={[planProvenance]}
              testId="mesoscope-plan-classification"
            />
          </summary>
          <ul className="mesoscope-compact-list">
            {planCatalog.map((entry) => (
              <li key={text(entry.plan_id)}>
                <strong>{text(entry.plan_id)}</strong>
                <span title={text(entry.signature_digest)}>{digestTail(text(entry.signature_digest))}</span>
                <small>{boolean(entry.selected) ? "Selected · " : ""}locked</small>
              </li>
            ))}
          </ul>
        </details>
      </article>

      <article data-testid="mesoscope-safety-gate">
        <div className="mesoscope-card-heading">
          <p className="eyebrow">Independent safety gate</p>
          <span className="immutable-badge">Immutable</span>
        </div>
        <h3>{displayName(text(gate.state))}</h3>
        <p>
          {boolean(gate.independently_enforced)
            ? "Independently enforced; no bypass or apparatus controls."
            : "Gate state unavailable."}
        </p>
        <dl className="mesoscope-mini-definition">
          <div><dt>Mutable</dt><dd>No</dd></div>
          <div><dt>Hardware connector</dt><dd>None</dd></div>
        </dl>
      </article>
    </section>
  );
}

function EvidenceTable({
  columns,
  rows,
  testId,
}: {
  columns: Array<{ key: string; label: string }>;
  rows: JsonObject[];
  testId: string;
}) {
  return rows.length > 0 ? (
    <div className="mesoscope-table-scroll">
      <table className="mesoscope-evidence-table" data-testid={testId}>
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${testId}-${rowIndex}`}>
              {columns.map((column) => (
                <td key={column.key} title={text(row[column.key], "—")}>
                  {column.key.includes("digest")
                    ? digestTail(text(row[column.key], "—"))
                    : typeof row[column.key] === "boolean"
                      ? row[column.key] ? "Yes" : "No"
                      : text(row[column.key], String(row[column.key] ?? "—"))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : <p className="mesoscope-empty-evidence">Available after mock acquisition.</p>;
}

function PackageEvidence({ observation }: { observation: JsonObject }) {
  const expectedOutputs = asObjects(observation.expected_outputs);
  const eventRecords = asObjects(observation.event_records);
  const motionRows = asObjects(observation.motion_rows);
  const manifestRecords = asObjects(observation.manifest_records);
  const checksums = asObjects(observation.package_checksums);
  const checks = asObjects(observation.package_checks);

  return (
    <section className="mesoscope-evidence-disclosures" aria-label="Sealed package evidence">
      <details data-testid="mesoscope-expected-outputs">
        <summary>Expected outputs <span>{expectedOutputs.length}</span></summary>
        <EvidenceTable
          columns={[
            { key: "output_id", label: "Output" },
            { key: "region_id", label: "Region" },
            { key: "z_label", label: "Depth" },
            { key: "channel_id", label: "Channel" },
            { key: "frame_count", label: "Frames" },
          ]}
          rows={expectedOutputs}
          testId="mesoscope-expected-output-table"
        />
      </details>
      <details data-testid="mesoscope-event-records">
        <summary>Event records <span>{eventRecords.length}</span></summary>
        <EvidenceTable
          columns={[
            { key: "sequence_index", label: "Sequence" },
            { key: "event_id", label: "Event" },
            { key: "package_id", label: "Package" },
          ]}
          rows={eventRecords}
          testId="mesoscope-event-record-table"
        />
      </details>
      <details data-testid="mesoscope-motion-rows">
        <summary>Motion rows <span>{motionRows.length}</span></summary>
        <EvidenceTable
          columns={[
            { key: "row_id", label: "Row" },
            { key: "region_id", label: "Region" },
            { key: "z_label", label: "Depth" },
            { key: "channel_id", label: "Channel" },
            { key: "quality_status", label: "Quality" },
          ]}
          rows={motionRows}
          testId="mesoscope-motion-row-table"
        />
      </details>
      <details data-testid="mesoscope-manifest-records">
        <summary>Package manifest <span>{manifestRecords.length}</span></summary>
        <EvidenceTable
          columns={[
            { key: "output_id", label: "Output" },
            { key: "package_id", label: "Package" },
          ]}
          rows={manifestRecords}
          testId="mesoscope-manifest-table"
        />
      </details>
      <details data-testid="mesoscope-checksums">
        <summary>Package checksums <span>{checksums.length}</span></summary>
        <EvidenceTable
          columns={[
            { key: "artifact_id", label: "Artifact" },
            { key: "expected_digest", label: "Expected" },
            { key: "computed_digest", label: "Computed" },
            { key: "observed_digest", label: "Observed" },
          ]}
          rows={checksums}
          testId="mesoscope-checksum-table"
        />
      </details>
      <details data-testid="mesoscope-package-checks">
        <summary>Contract checks <span>{checks.length}</span></summary>
        {checks.length > 0 ? (
          <ul className="mesoscope-check-list">
            {checks.map((check) => {
              const status = text(check.status);
              return (
                <li className={`is-${status}`} key={text(check.check_id)}>
                  <span>{displayName(text(check.check_id))}</span>
                  <strong>{displayName(status)}</strong>
                </li>
              );
            })}
          </ul>
        ) : <p className="mesoscope-empty-evidence">Run package validation to compare every sealed record.</p>}
      </details>
    </section>
  );
}

export function MesoscopeHandoffVisualization({
  environment,
  run,
}: {
  environment: EnvironmentSummary;
  run: RunSnapshot | null;
}) {
  const definition = environment.visualization;
  if (definition.kind !== "mesoscope_handoff_v1") return null;
  const headingAndBoundary = (
    <>
      <div className="section-heading-row visualization-heading">
        <div>
          <p className="eyebrow">Sealed four-region handoff</p>
          <h2>{definition.title}</h2>
        </div>
        <span className="synthetic-label">{definition.synthetic_label}</span>
      </div>

      <div
        className="mesoscope-safety-boundary"
        data-testid="mesoscope-safety-boundary"
        role="note"
      >
        <strong>{definition.sealed_label}</strong>
        <span>{environment.simulation_label}</span>
      </div>
    </>
  );
  if (run === null) {
    return (
      <section
        className="visualization-card mesoscope-handoff"
        data-testid="mesoscope-handoff-visualization"
      >
        {headingAndBoundary}
        <div
          className="mesoscope-sealed-preview"
          data-testid="mesoscope-sealed-preview"
        >
          Runtime evidence is not loaded. Freeze and start a sealed run to display
          product-owned profile, plan, survey, tile, and package observations.
        </div>
      </section>
    );
  }

  const observation = run.observation;
  const survey = asObject(observation.survey);
  const surveySeed = finiteNumber(survey.visual_seed);
  const signedPlan = asObject(observation.signed_plan);
  const plannedRegions = asObjects(signedPlan.regions);
  const tiles = asObjects(observation.region_tiles);
  const expectedByRegion = Object.fromEntries(
    definition.region_ids.map((regionId) => {
      const planned = plannedRegions.find((region) => region.region_id === regionId);
      return [regionId, text(planned?.z_label)];
    }),
  );
  const tileByRegion = Object.fromEntries(
    tiles.map((tile) => [text(tile.region_id), tile]),
  );
  const validationStatus = text(observation.validation_status);
  const detectedFaults = Array.isArray(observation.detected_faults)
    ? observation.detected_faults.filter((fault): fault is string => typeof fault === "string")
    : [];
  const terminalStatus = typeof observation.terminal_status === "string"
    ? observation.terminal_status
    : null;
  const stage = text(observation.stage);
  const summary = text(
    observation.summary,
    "Runtime summary unavailable.",
  );

  return (
    <section
      className="visualization-card mesoscope-handoff"
      data-testid="mesoscope-handoff-visualization"
    >
      {headingAndBoundary}

      <ContractCards
        observation={observation}
        planProvenance={definition.plan_provenance}
        profileProvenance={definition.profile_provenance}
      />

      <section className="mesoscope-survey-layout" aria-label="Synthetic survey and region tiles">
        <figure className="mesoscope-survey" data-testid="mesoscope-survey">
          <figcaption>
            <span>{definition.survey_label}</span>
            <small>
              {text(survey.watermark)} · seed {surveySeed ?? "Unavailable"}
            </small>
          </figcaption>
          <div className="mesoscope-survey-field" role="img" aria-label="Deterministic non-biological procedural phantom with four planned regions.">
            <svg aria-hidden="true" viewBox="0 0 320 210">
              <path className="mesoscope-survey-path is-a" d="M-10 120 C55 12, 94 192, 160 74 S266 26, 340 104" />
              <path className="mesoscope-survey-path is-b" d="M44 -10 C77 58, 64 130, 10 220 M162 -5 C200 60, 190 132, 246 220" />
              <path className="mesoscope-survey-path is-c" d="M-10 55 C76 92, 86 24, 176 43 S264 166, 340 138" />
            </svg>
            {definition.region_ids.map((regionId) => (
              <span
                className={`mesoscope-survey-region is-${regionId.toLocaleLowerCase()}`}
                key={regionId}
              >
                <strong>{regionId}</strong>
                <small>{expectedByRegion[regionId]}</small>
              </span>
            ))}
            <span className="mesoscope-watermark">SYNTHETIC PHANTOM</span>
          </div>
        </figure>

        <div className="mesoscope-tiles-panel">
          <div className="mesoscope-tiles-heading">
            <span>{definition.spatial_view_label}</span>
            <small>{definition.raw_view_label} · deterministic procedural render</small>
          </div>
          <div className="mesoscope-tile-grid">
            {definition.region_ids.map((regionId) => (
              <ProceduralTile
                expectedZ={expectedByRegion[regionId]}
                key={regionId}
                regionId={regionId}
                tile={tileByRegion[regionId]}
              />
            ))}
          </div>
        </div>
      </section>

      <section
        className={`mesoscope-validation-strip is-${validationStatus}`}
        data-testid="mesoscope-validation-status"
      >
        <div>
          <p className="eyebrow">Package status</p>
          <strong>{displayName(validationStatus)}</strong>
          <span> · {displayName(stage)}</span>
        </div>
        <p>{summary}</p>
        {terminalStatus && (
          <strong
            className="mesoscope-terminal-status"
            data-testid="mesoscope-terminal-status"
          >
            {terminalStatus}
          </strong>
        )}
        {detectedFaults.length > 0 && (
          <ul data-testid="mesoscope-detected-faults">
            {detectedFaults.map((fault) => <li key={fault}>{fault}</li>)}
          </ul>
        )}
      </section>

      <details className="mesoscope-package-evidence" data-testid="mesoscope-package-evidence">
        <summary>
          {definition.details_toggle_label}
          <ProvenanceBadges
            items={definition.package_provenance}
            testId="mesoscope-evidence-classification"
          />
        </summary>
        <PackageEvidence observation={observation} />
      </details>
    </section>
  );
}

export function mesoscopeHandoffTraceEvidence(event: TraceEvent): string | null {
  if (event.type === "observation") {
    const stage = text(event.observation.stage, "");
    const validation = text(event.observation.validation_status, "");
    const terminal = text(event.observation.terminal_status, "");
    const faults = Array.isArray(event.observation.detected_faults)
      ? event.observation.detected_faults.filter((fault): fault is string => typeof fault === "string")
      : [];
    return [stage, validation, ...faults, terminal]
      .filter((item) => item && item !== "not_run")
      .join(" · ") || null;
  }
  if (event.type === "transition") {
    return `${event.transition.from_state} → ${event.transition.to_state} · state r${event.transition.state_revision}`;
  }
  if (event.type === "verifier") {
    return `${event.verifier.passed ? "passed" : "failed"} · ${event.verifier.terminal_disposition}`;
  }
  return `${event.action.type} · empty sealed input`;
}
