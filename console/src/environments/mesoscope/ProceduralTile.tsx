import { displayName } from "../../app/format";
import { deterministicPoints, type MesoTile } from "./mesoscopeEvidence";

export interface ProceduralTileProps {
  regionId: string;
  expectedZ: string;
  tile: MesoTile | undefined;
}

/** One seeded, non-biological region tile; a missing tile still renders as a card. */
export function ProceduralTile({ regionId, expectedZ, tile }: ProceduralTileProps): JSX.Element {
  const missing = tile === undefined;
  const observedZ = missing ? expectedZ : tile.z_label;
  const status = missing ? "missing" : tile.status;
  const mismatch = missing || observedZ !== expectedZ;
  const seed = missing ? null : tile.tile_seed;
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
        aria-label={
          missing
            ? `${regionId} ${expectedZ} synthetic tile is missing.`
            : `${regionId} ${observedZ} deterministic synthetic procedural tile, status ${status}.`
        }
        className="mesoscope-tile-image"
        role="img"
        viewBox="0 0 100 100"
      >
        <rect className="mesoscope-tile-field" height="100" width="100" />
        {seed !== null &&
          points.map((point, index) => (
            <circle
              className={index % 3 === 0 ? "mesoscope-cell is-accent" : "mesoscope-cell"}
              cx={point.x}
              cy={point.y}
              key={`${seed}-${index}`}
              opacity={point.opacity}
              r={point.radius}
            />
          ))}
        {seed !== null && (
          <path
            className="mesoscope-tile-trace"
            d={`M0 ${60 + (seed % 7)} C18 42, 28 76, 44 52 S70 35, 100 ${48 + (seed % 9)}`}
          />
        )}
        {missing && (
          <>
            <path className="mesoscope-missing-mark" d="M28 28 L72 72 M72 28 L28 72" />
            <text className="mesoscope-missing-label" x="50" y="88">
              MISSING
            </text>
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
