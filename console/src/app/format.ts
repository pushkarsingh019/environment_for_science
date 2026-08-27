/** Long digests are shortened to `head…tail`; short values pass through unchanged. */
export function digestTail(digest: string): string {
  return digest.length > 24 ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : digest;
}

/** `not_run` → `Not Run`, `mock_package_verified` → `Mock Package Verified`. */
export function displayName(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export function acquisitionSummary(profile: {
  sampling_hz: number;
  online_bandpass_hz: [number, number];
  notch_hz: number;
}): { sampling: string; bandpass: string; notch: string } {
  const [low, high] = profile.online_bandpass_hz;
  return {
    sampling: `${profile.sampling_hz} Hz`,
    bandpass: `${low}–${high} Hz`,
    notch: `${profile.notch_hz} Hz`,
  };
}

const ACTOR_ROLE_LABELS = {
  authoring_assistant: "Authoring assistant",
  environment_author: "Environment author",
  system: "System",
} as const;

export function actorRole(role: keyof typeof ACTOR_ROLE_LABELS): string {
  return ACTOR_ROLE_LABELS[role];
}

export function percent(value: number | null): string {
  return value === null ? "Not estimable" : `${(value * 100).toFixed(1)}%`;
}

/** `+1.6%`, `−3.1%` (U+2212 minus), or `0.0%` for values that round to zero. */
export function signedPercent(value: number): string {
  const magnitude = Math.abs(value * 100).toFixed(1);
  if (magnitude === "0.0") return "0.0%";
  return `${value < 0 ? "−" : "+"}${magnitude}%`;
}

export const EEG_EVIDENCE_DOMAINS: ReadonlyArray<readonly [domain: string, label: string]> = [
  ["configuration", "Configuration"],
  ["eeg", "EEG"],
  ["onset", "Onset"],
  ["response", "Response"],
  ["recording", "Recording"],
];

export const MESOSCOPE_EVIDENCE_DOMAINS: ReadonlyArray<readonly [domain: string, label: string]> = [
  ["safety", "Safety"],
  ["plan", "Plan"],
  ["acquisition", "Acquisition"],
  ["package", "Package"],
];
