import type { GlyphId } from "./sceneModel";

/**
 * Schematic instrument illustrations. Every glyph is a `<symbol>` whose viewBox
 * matches the node box declared in the layout, so `<use width height>` scales it
 * without distortion. Line art only: no photographs, no vendor marks.
 */

const LINE = "#3a3835";
const PANEL = "#f4f2ef";
const SCREEN_CASE = "#2b2f33";
const SCREEN_FACE = "#3a3f46";

function Monitor(): JSX.Element {
  return (
    <symbol id="glyph-monitor" viewBox="0 0 200 130">
      <rect x="8" y="98" width="184" height="6" rx="3" fill={LINE} opacity="0.18" />
      <rect x="86" y="86" width="28" height="18" fill={SCREEN_CASE} />
      <rect x="62" y="102" width="76" height="8" rx="4" fill={SCREEN_CASE} />
      <rect x="6" y="6" width="188" height="84" rx="8" fill={SCREEN_CASE} />
      <rect x="14" y="14" width="172" height="68" rx="4" fill={SCREEN_FACE} />
      {/* Lower-right optical trigger patch. */}
      <rect x="158" y="58" width="22" height="20" rx="2" fill="#ffffff" />
    </symbol>
  );
}

function HeadParticipant(): JSX.Element {
  return (
    <symbol id="glyph-head-participant" viewBox="0 0 150 170">
      <g fill="none" stroke={LINE} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        {/* Chair back. */}
        <path d="M112 62 C126 62, 132 72, 132 86 L132 168" opacity="0.55" />
        {/* Head facing left, with brow, nose and chin. */}
        <path d="M100 34 C74 30, 54 46, 52 66 C51 75, 44 80, 40 86 C37 90, 40 95, 46 96 L54 97 C55 108, 62 116, 74 118" />
        <path d="M100 34 C114 38, 121 52, 120 68 C119 88, 110 104, 96 112" />
        {/* Ear. */}
        <path d="M92 70 C98 66, 104 70, 103 77 C102 83, 96 85, 92 82" />
        {/* Neck and shoulders. */}
        <path d="M84 118 L84 132" />
        <path d="M50 168 C52 146, 64 134, 84 132 C106 130, 118 142, 122 168" />
      </g>
    </symbol>
  );
}

function HeadExperimenter(): JSX.Element {
  return (
    <symbol id="glyph-head-experimenter" viewBox="0 0 110 170">
      <g
        fill="none"
        stroke={LINE}
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="translate(110 0) scale(-1 1)"
      >
        <path d="M84 62 C96 62, 100 72, 100 86 L100 168" opacity="0.55" />
        <path d="M76 34 C54 30, 38 46, 36 64 C35 72, 29 77, 26 82 C23 86, 26 91, 31 92 L38 93 C39 103, 45 111, 56 113" />
        <path d="M76 34 C88 38, 94 52, 93 66 C92 84, 84 100, 72 108" />
        <path d="M68 68 C73 64, 78 68, 77 74 C76 80, 71 82, 68 79" />
        <path d="M62 113 L62 128" />
        <path d="M32 168 C34 148, 44 130, 62 128 C82 126, 92 142, 96 168" />
      </g>
    </symbol>
  );
}

function Headphones(): JSX.Element {
  return (
    <symbol id="glyph-headphones" viewBox="0 0 90 70">
      <g fill="none" stroke={LINE} strokeWidth="2.6" strokeLinecap="round">
        <path d="M14 44 L14 34 C14 17, 28 7, 45 7 C62 7, 76 17, 76 34 L76 44" />
      </g>
      <rect x="6" y="40" width="18" height="26" rx="6" fill={SCREEN_CASE} />
      <rect x="66" y="40" width="18" height="26" rx="6" fill={SCREEN_CASE} />
    </symbol>
  );
}

function ResponseBox(): JSX.Element {
  return (
    <symbol id="glyph-response-box" viewBox="0 0 110 100">
      <rect x="6" y="10" width="98" height="78" rx="10" fill={SCREEN_CASE} />
      <rect x="12" y="16" width="86" height="66" rx="7" fill="#3c4247" />
      {[
        [38, 40],
        [72, 40],
        [38, 62],
        [72, 62],
      ].map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="9" fill="#c9413a" stroke="#8f2f2a" strokeWidth="1.5" />
      ))}
      <path d="M20 88 L20 96" stroke={LINE} strokeWidth="2.4" strokeLinecap="round" />
    </symbol>
  );
}

function SplitterBox(): JSX.Element {
  const sockets: JSX.Element[] = [];
  for (let row = 0; row < 4; row += 1) {
    for (let column = 0; column < 8; column += 1) {
      const index = row * 8 + column;
      sockets.push(
        <circle
          key={index}
          cx={30 + column * 16}
          cy={30 + row * 15}
          r="4.2"
          fill={index % 4 === 0 ? "#c9413a" : "#5f9d86"}
          stroke="#20242a"
          strokeWidth="1"
        />,
      );
    }
  }
  return (
    <symbol id="glyph-splitter-box" viewBox="0 0 190 120">
      <rect x="6" y="8" width="178" height="86" rx="8" fill={SCREEN_CASE} />
      <rect x="14" y="16" width="162" height="70" rx="5" fill="#343a40" />
      {sockets}
      {/* Two DB connectors on the lower edge. */}
      <rect x="34" y="94" width="46" height="16" rx="5" fill="#8d9299" stroke={LINE} strokeWidth="1.6" />
      <rect x="110" y="94" width="46" height="16" rx="5" fill="#8d9299" stroke={LINE} strokeWidth="1.6" />
    </symbol>
  );
}

function Amplifier(): JSX.Element {
  return (
    <symbol id="glyph-amplifier" viewBox="0 0 100 150">
      <rect x="8" y="6" width="84" height="138" rx="7" fill={PANEL} stroke={LINE} strokeWidth="2.2" />
      <rect x="18" y="16" width="64" height="24" rx="4" fill={SCREEN_FACE} />
      {[56, 72, 88, 104, 120].map((y, index) => (
        <g key={y}>
          <rect x="18" y={y} width="64" height="9" rx="3" fill="#e2ded7" />
          <rect x="18" y={y} width={index % 2 === 0 ? 46 : 30} height="9" rx="3" fill="#5f9d86" opacity="0.85" />
        </g>
      ))}
      <circle cx="82" cy="136" r="3.4" fill="#c9413a" />
    </symbol>
  );
}

function RackProcessor(): JSX.Element {
  return (
    <symbol id="glyph-rack-processor" viewBox="0 0 470 110">
      <rect x="6" y="10" width="458" height="90" rx="8" fill={PANEL} stroke={LINE} strokeWidth="2.2" />
      {/* Rack ears. */}
      <path d="M20 10 L20 100 M450 10 L450 100" stroke={LINE} strokeWidth="1.6" opacity="0.5" />
      <rect x="40" y="30" width="132" height="50" rx="5" fill={SCREEN_FACE} />
      <text x="106" y="61" textAnchor="middle" fontSize="20" fontFamily="ui-monospace, monospace" fill="#8fd6c4">
        1111
      </text>
      {[210, 250, 290].map((cx) => (
        <g key={cx}>
          <circle cx={cx} cy="55" r="16" fill="#e2ded7" stroke={LINE} strokeWidth="1.8" />
          <path d={`M${cx} 45 L${cx} 55`} stroke={LINE} strokeWidth="2" strokeLinecap="round" />
        </g>
      ))}
      {[336, 366, 396, 426].map((cx) => (
        <circle key={cx} cx={cx} cy="42" r="7" fill="#8d9299" stroke={LINE} strokeWidth="1.5" />
      ))}
      {[336, 366, 396, 426].map((cx) => (
        <circle key={`b-${cx}`} cx={cx} cy="72" r="7" fill="#8d9299" stroke={LINE} strokeWidth="1.5" />
      ))}
    </symbol>
  );
}

function Computer(): JSX.Element {
  return (
    <symbol id="glyph-computer" viewBox="0 0 160 130">
      <rect x="10" y="8" width="140" height="92" rx="8" fill={SCREEN_CASE} />
      <rect x="18" y="16" width="124" height="76" rx="4" fill={SCREEN_FACE} />
      <text x="80" y="62" textAnchor="middle" fontSize="26" fontWeight="700" fill="#cfd6dc" letterSpacing="1">
        EEG
      </text>
      <rect x="62" y="100" width="36" height="10" rx="3" fill={SCREEN_CASE} />
      <rect x="40" y="110" width="80" height="8" rx="4" fill={SCREEN_CASE} />
    </symbol>
  );
}

function CapRing(): JSX.Element {
  return (
    <symbol id="glyph-cap-ring" viewBox="0 0 26 26">
      <circle cx="13" cy="13" r="9" fill="none" stroke="var(--sig-eeg)" strokeWidth="3" />
    </symbol>
  );
}

function ProfileCard(): JSX.Element {
  return (
    <symbol id="glyph-profile-card" viewBox="0 0 180 130">
      <rect x="10" y="8" width="160" height="114" rx="9" fill="#ffffff" stroke={LINE} strokeWidth="2.2" />
      {[36, 54, 72].map((y) => (
        <path key={y} d={`M28 ${y} L134 ${y}`} stroke={LINE} strokeWidth="2" opacity="0.35" strokeLinecap="round" />
      ))}
      <path d="M28 90 L92 90" stroke={LINE} strokeWidth="2" opacity="0.35" strokeLinecap="round" />
      <circle cx="132" cy="95" r="17" fill="var(--meso-violet-soft)" stroke="var(--meso-violet)" strokeWidth="2.2" />
      <path d="M124 95 L130 101 L141 89" fill="none" stroke="var(--meso-violet)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </symbol>
  );
}

function PlanMap(): JSX.Element {
  const quadrants: Array<{ id: string; x: number; y: number; depth: string }> = [
    { id: "R1", x: 18, y: 16, depth: "Z-A" },
    { id: "R2", x: 100, y: 16, depth: "Z-A" },
    { id: "R3", x: 18, y: 88, depth: "Z-B" },
    { id: "R4", x: 100, y: 88, depth: "Z-B" },
  ];
  return (
    <symbol id="glyph-plan-map" viewBox="0 0 220 160">
      <rect x="8" y="8" width="204" height="144" rx="9" fill="#ffffff" stroke={LINE} strokeWidth="2.2" />
      {quadrants.map((quadrant) => (
        <g key={quadrant.id}>
          <rect
            x={quadrant.x}
            y={quadrant.y}
            width="94"
            height="56"
            rx="6"
            fill={quadrant.depth === "Z-A" ? "var(--meso-violet-soft)" : "var(--meso-teal-soft)"}
            stroke={quadrant.depth === "Z-A" ? "var(--meso-violet)" : "var(--meso-teal)"}
            strokeWidth="1.8"
          />
          <text x={quadrant.x + 47} y={quadrant.y + 27} textAnchor="middle" fontSize="17" fontWeight="700" fill={LINE}>
            {quadrant.id}
          </text>
          <text x={quadrant.x + 47} y={quadrant.y + 45} textAnchor="middle" fontSize="12" fill={LINE} opacity="0.7">
            {quadrant.depth}
          </text>
        </g>
      ))}
    </symbol>
  );
}

function Gate(): JSX.Element {
  return (
    <symbol id="glyph-gate" viewBox="0 0 150 130">
      <rect x="12" y="70" width="126" height="18" rx="6" fill="#e2ded7" stroke={LINE} strokeWidth="2.2" />
      <path d="M30 88 L30 120 M120 88 L120 120" stroke={LINE} strokeWidth="2.6" strokeLinecap="round" />
      <rect x="58" y="18" width="34" height="30" rx="6" fill={PANEL} stroke={LINE} strokeWidth="2.4" />
      <path d="M66 18 L66 12 C66 5, 84 5, 84 12 L84 18" fill="none" stroke={LINE} strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="75" cy="32" r="4" fill={LINE} />
    </symbol>
  );
}

function AcquisitionRig(): JSX.Element {
  return (
    <symbol id="glyph-acquisition-rig" viewBox="0 0 220 150">
      <rect x="14" y="12" width="192" height="88" rx="9" fill={PANEL} stroke={LINE} strokeWidth="2.2" />
      <circle cx="72" cy="56" r="26" fill="#ffffff" stroke={LINE} strokeWidth="2.2" />
      <circle cx="72" cy="56" r="13" fill="var(--meso-teal-soft)" stroke="var(--meso-teal)" strokeWidth="2" />
      {[124, 156, 188].map((x) => (
        <rect key={x} x={x - 12} y="40" width="24" height="32" rx="4" fill="#e2ded7" stroke={LINE} strokeWidth="1.6" />
      ))}
      {/* Cut connector: the sealed boundary. */}
      <path d="M52 112 L108 112" stroke={LINE} strokeWidth="2.4" strokeLinecap="round" strokeDasharray="7 7" />
      <path d="M124 104 L146 126 M146 104 L124 126" stroke="#9f2f2f" strokeWidth="2.6" strokeLinecap="round" />
    </symbol>
  );
}

function Ledger(): JSX.Element {
  return (
    <symbol id="glyph-ledger" viewBox="0 0 180 140">
      <rect x="12" y="10" width="156" height="120" rx="9" fill="#ffffff" stroke={LINE} strokeWidth="2.2" />
      <rect x="12" y="10" width="156" height="26" rx="9" fill="#efece6" />
      <path d="M12 36 L168 36" stroke={LINE} strokeWidth="2" />
      <path d="M64 36 L64 130 M116 36 L116 130" stroke={LINE} strokeWidth="1.6" opacity="0.45" />
      {[58, 80, 102].map((y) => (
        <path key={y} d={`M12 ${y} L168 ${y}`} stroke={LINE} strokeWidth="1.6" opacity="0.45" />
      ))}
    </symbol>
  );
}

function Stamp(): JSX.Element {
  return (
    <symbol id="glyph-stamp" viewBox="0 0 150 130">
      <circle cx="75" cy="60" r="42" fill="none" stroke={LINE} strokeWidth="3" opacity="0.75" />
      <circle cx="75" cy="60" r="32" fill="none" stroke={LINE} strokeWidth="1.8" opacity="0.45" />
      <path d="M58 60 L70 73 L94 47" fill="none" stroke={LINE} strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M26 116 L124 116" stroke={LINE} strokeWidth="2.6" strokeLinecap="round" opacity="0.55" />
    </symbol>
  );
}

const GLYPHS: Record<GlyphId, () => JSX.Element> = {
  monitor: Monitor,
  "head-participant": HeadParticipant,
  "head-experimenter": HeadExperimenter,
  headphones: Headphones,
  "response-box": ResponseBox,
  "splitter-box": SplitterBox,
  amplifier: Amplifier,
  "rack-processor": RackProcessor,
  computer: Computer,
  "cap-ring": CapRing,
  "profile-card": ProfileCard,
  "plan-map": PlanMap,
  gate: Gate,
  "acquisition-rig": AcquisitionRig,
  ledger: Ledger,
  stamp: Stamp,
};

/** All instrument symbols, mounted once per scene inside `<defs>`. */
export function GlyphDefs(): JSX.Element {
  return (
    <>
      {(Object.keys(GLYPHS) as GlyphId[]).map((id) => {
        const Glyph = GLYPHS[id];
        return <Glyph key={id} />;
      })}
    </>
  );
}
