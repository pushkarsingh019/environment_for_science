/** Pure geometry for the EEG paper and frequency figure (viewBox 1000 wide, 64-unit rows). */

export const PAPER = {
  viewWidth: 1000,
  plotX0: 72,
  plotX1: 960,
  rowHeight: 64,
  topPad: 24,
  bottomPad: 16,
} as const;

export type Gain = 0.5 | 1 | 2 | 4;
export const GAIN_STEPS: readonly Gain[] = [0.5, 1, 2, 4];

const AMPLITUDE_SCALE = 1.2;
const HALF_SWING = 29;
const PLOT_WIDTH = PAPER.plotX1 - PAPER.plotX0;
const NEAR_ZERO_UV = 0.5;
const MINOR_TICK_SECONDS = 0.25;
const MAJOR_TICK_EVERY = 2;

const REQUIRED_COLOURS = ["#355c7d", "#1f8a7a", "#7a4fb3", "#b8631f", "#8a6a2e", "#2f6b3f"] as const;
const OPTIONAL_COLOUR = "#5b6470";
const REFERENCE_COLOUR = "#6c7f96";

export function paperHeight(rowCount: number): number {
  return PAPER.topPad + rowCount * PAPER.rowHeight + PAPER.bottomPad;
}

export function rowCenterY(rowIndex: number): number {
  return PAPER.topPad + rowIndex * PAPER.rowHeight + PAPER.rowHeight / 2;
}

/** The clamp rails of a row: a clipped channel visibly pins to these lines. */
export function rowRailY(rowIndex: number): { top: number; bottom: number } {
  const centre = rowCenterY(rowIndex);
  return { top: centre - HALF_SWING, bottom: centre + HALF_SWING };
}

export function sampleX(index: number, count: number): number {
  return PAPER.plotX0 + (count > 1 ? index / (count - 1) : 0) * PLOT_WIDTH;
}

const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value));

function polyline(points: Array<readonly [number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
}

/** Every sample plotted; amplitude scaled by gain and clamped to the row's rails. */
export function tracePath(samples: number[], rowIndex: number, gain: Gain): string {
  const centre = rowCenterY(rowIndex);
  return polyline(
    samples.map((sample, index) => [
      sampleX(index, samples.length),
      centre - clamp(sample * AMPLITUDE_SCALE * gain, -HALF_SWING, HALF_SWING),
    ]),
  );
}

/** Magnitudes rise from the bottom of the row band, normalised to the figure-wide maximum. */
export function spectrumPath(magnitudes: number[], rowIndex: number, globalMax: number): string {
  const baseline = rowRailY(rowIndex).bottom;
  const span = PAPER.rowHeight - 12;
  return polyline(
    magnitudes.map((magnitude, index) => [
      sampleX(index, magnitudes.length),
      baseline - (magnitude / Math.max(1, globalMax)) * span,
    ]),
  );
}

export function channelColor(index: number, role: "required" | "optional" | "reference"): string {
  if (role === "reference") return REFERENCE_COLOUR;
  if (role === "optional") return OPTIONAL_COLOUR;
  return REQUIRED_COLOURS[index % REQUIRED_COLOURS.length];
}

export interface SampleSpan {
  start: number;
  end: number;
}

/** Runs of near-zero samples (dropout gaps) at least `minRun` long; `end` is exclusive. */
export function nearZeroSpans(samples: number[], minRun = 4): SampleSpan[] {
  const spans: SampleSpan[] = [];
  let start: number | null = null;
  samples.forEach((sample, index) => {
    const quiet = Math.abs(sample) < NEAR_ZERO_UV;
    if (quiet && start === null) start = index;
    if (!quiet && start !== null) {
      if (index - start >= minRun) spans.push({ start, end: index });
      start = null;
    }
  });
  if (start !== null && samples.length - start >= minRun) spans.push({ start, end: samples.length });
  return spans;
}

export interface TimeTick {
  x: number;
  label: string | null;
}

/** Vertical paper rules every 0.25 s; every second rule is labelled. */
export function timeTicks(durationSeconds: number): TimeTick[] {
  if (durationSeconds <= 0) return [];
  const count = Math.floor(durationSeconds / MINOR_TICK_SECONDS + 1e-9);
  return Array.from({ length: count + 1 }, (_, step) => {
    const seconds = step * MINOR_TICK_SECONDS;
    return {
      x: PAPER.plotX0 + (seconds / durationSeconds) * PLOT_WIDTH,
      label: step % MAJOR_TICK_EVERY === 0 ? `${seconds.toFixed(1)} s` : null,
    };
  });
}
