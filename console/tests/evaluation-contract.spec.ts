import { expect, test } from "@playwright/test";
import { decodeEvaluationSnapshot } from "../src/api";

const digest = `sha256:${"a".repeat(64)}`;
const totals = [4, 4, 4, 8, 8, 4] as const;

function runningFinalizationSnapshot(): unknown {
  const scenarioIds = Array.from(
    { length: 32 },
    (_, index) => `development-scenario-${String(index + 1).padStart(2, "0")}`,
  );
  return {
    evaluation_id: `evaluation-${"b".repeat(32)}`,
    status: "running",
    plan: {
      plan_revision: "science-environment-evaluation-plan/1",
      profile: "base-gemma-development-v1",
      environment_id: "eeg-preflight-v1",
      bundle_revision: "fixture-revision",
      bundle_digest: digest,
      split: "development",
      curriculum_package_digest: digest,
      model: {
        provider: "local-openai-compatible",
        requested_model: "google/gemma-4-E4B-it",
        adapter_revision: "local-gemma-openai-chat/1",
      },
      model_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2",
      objective: "Complete the fixed development matrix.",
      scenario_ids: scenarioIds,
    },
    progress: {
      phase: "running",
      message: "Evaluated 32 of 32 development scenarios.",
      completed_scenarios: 32,
      total_scenarios: 32,
      scientific_successes: 32,
      scientific_failures: 0,
      infrastructure_errors: 0,
    },
    calibration: {
      status: "pending",
      summary: "Readiness can be assessed after all development scenarios finish.",
      scientific_accuracy: 1,
      target_accuracy_minimum: 0.2,
      target_accuracy_maximum: 0.7,
      overall_accuracy_in_target: false,
      levels_1_and_2_mixed: false,
      no_infrastructure_errors: false,
      authenticated_local_runtime: false,
      levels: totals.map((total, level) => ({
        level,
        label: `Level ${level}`,
        total_scenarios: total,
        completed_scenarios: total,
        scientific_successes: total,
        scientific_failures: 0,
        infrastructure_errors: 0,
        has_success_and_failure: false,
      })),
    },
    attempts: scenarioIds.map((scenarioId, ordinal) => ({
      attempt_id: `attempt-${String(ordinal + 1).padStart(4, "0")}`,
      ordinal,
      scenario_id: scenarioId,
      disposition: "scientific_success",
      summary: "The scientific criteria passed.",
      interaction_digest: digest,
      runtime_trace_digest: digest,
      result_digest: digest,
    })),
  };
}

test("accepts the backend-valid 32-of-32 running finalization interval", () => {
  const decoded = decodeEvaluationSnapshot(runningFinalizationSnapshot());

  expect({
    status: decoded.status,
    calibration: decoded.calibration.status,
    completed: decoded.progress.completed_scenarios,
    noInfrastructureErrors: decoded.calibration.no_infrastructure_errors,
  }).toEqual({
    status: "running",
    calibration: "pending",
    completed: 32,
    noInfrastructureErrors: false,
  });
});

test("still rejects pending calibration after evaluation finalization", () => {
  const payload = runningFinalizationSnapshot() as {
    status: string;
    progress: { phase: string };
  };
  payload.status = "completed";
  payload.progress.phase = "completed";

  expect(() => decodeEvaluationSnapshot(payload)).toThrow(
    /bind calibration evidence to evaluation progress/,
  );
});
