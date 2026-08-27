import { createElement, type ReactNode } from "react";
import type {
  ComparisonFixtureState,
  EvaluationDisposition,
  EvaluationSnapshot,
  EvaluationStatus,
  EvaluationSummary,
  TrainingAcceptanceJob,
} from "../types";
import { errorMessage } from "../app/format";

export const POLL_INTERVAL_MS = 750;
export const POLL_MAX_INTERVAL_MS = 6_000;

/** 1.5 s, 3 s, 6 s, 6 s… after consecutive polling failures. */
export function pollRetryDelay(consecutiveFailures: number): number {
  const exponent = Math.min(consecutiveFailures, 3);
  return Math.min(POLL_INTERVAL_MS * 2 ** exponent, POLL_MAX_INTERVAL_MS);
}

const STATUS_LABELS: Record<EvaluationStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  interrupted: "Interrupted",
};

export function statusLabel(status: EvaluationStatus): string {
  return STATUS_LABELS[status];
}

const TRAINING_STATUS_LABELS: Record<TrainingAcceptanceJob["status"], string> = {
  queued: "Queued",
  running: "Running",
  failed: "Failed",
  completed: "Completed",
};

export function trainingStatusLabel(status: TrainingAcceptanceJob["status"]): string {
  return TRAINING_STATUS_LABELS[status];
}

const DISPOSITION_LABELS: Record<EvaluationDisposition, string> = {
  scientific_success: "Scientific success",
  scientific_failure: "Scientific failure",
  infrastructure_error: "Infrastructure error",
};

export function dispositionLabel(disposition: EvaluationDisposition): string {
  return DISPOSITION_LABELS[disposition];
}

export function asSummary(snapshot: EvaluationSnapshot): EvaluationSummary {
  return {
    evaluation_id: snapshot.evaluation_id,
    profile: snapshot.plan.profile,
    model: snapshot.plan.model,
    status: snapshot.status,
    progress: snapshot.progress,
  };
}

/** Prepends the snapshot's summary and drops any older row with the same id. */
export function mergeSummary(
  summaries: EvaluationSummary[],
  snapshot: EvaluationSnapshot,
): EvaluationSummary[] {
  return [
    asSummary(snapshot),
    ...summaries.filter((item) => item.evaluation_id !== snapshot.evaluation_id),
  ];
}

export function safeMessage(reason: unknown, fallback: string): string {
  return errorMessage(reason, fallback);
}

export const COMPARISON_FIXTURES: ReadonlyArray<{
  value: ComparisonFixtureState;
  label: string;
}> = [
  { value: "successful", label: "Supported improvement" },
  { value: "inconclusive", label: "Inconclusive" },
  { value: "regressed", label: "Regressed" },
  { value: "partially_unavailable", label: "Hosted model unavailable" },
  { value: "adapter_error", label: "Adapter error" },
];

export interface SectionCardProps {
  title: string;
  eyebrow?: string;
  testId?: string;
  count?: number;
  children: ReactNode;
  headerRight?: ReactNode;
  id?: string;
}

/**
 * White surface with a heading row. Rendered through `createElement` because
 * this module is deliberately a `.ts` file shared by every evaluation panel.
 */
export function SectionCard(props: SectionCardProps): JSX.Element {
  const { title, eyebrow, testId, count, children, headerRight, id } = props;
  const heading = createElement(
    "div",
    null,
    eyebrow !== undefined && createElement("p", { className: "eyebrow" }, eyebrow),
    createElement("h2", null, title),
  );
  const badge = count !== undefined
    && createElement("span", { className: "evaluation-count" }, count);
  return createElement(
    "section",
    { className: "evaluation-card", "data-testid": testId, id },
    createElement("div", { className: "section-heading-row" }, heading, badge, headerRight),
    children,
  );
}

/** Inline request-failure notice used by every evaluation panel. */
export function ErrorBanner(props: { message: string; lead?: string }): JSX.Element {
  return createElement(
    "div",
    { className: "evaluation-error", role: "alert" },
    props.lead !== undefined && createElement("strong", null, props.lead),
    props.lead !== undefined && " ",
    props.message,
  );
}
