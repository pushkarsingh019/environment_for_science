import type {
  EnvironmentSummary,
  PolicyAgent,
  RunSnapshot,
  UnknownRecord,
} from "./types";

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      const record = asRecord(item);
      return text(record.summary) || text(record.label) || text(record.name);
    })
    .filter(Boolean);
}

function policyAgents(value: unknown): PolicyAgent[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return [{ id: item, name: item }];
    const record = asRecord(item);
    const id = text(record.id) || text(record.value) || text(record.name);
    if (!id) return [];
    return [{ id, name: text(record.name, id) }];
  });
}

function normalizeEnvironment(payload: unknown): EnvironmentSummary {
  const root = asRecord(payload);
  const source = isRecord(root.environment) ? root.environment : root;
  const validation = asRecord(source.validation ?? root.validation);
  const scenario = asRecord(source.seeded_scenario ?? root.seeded_scenario);
  const agents = policyAgents(
    source.policy_agents ?? root.policy_agents ?? source.available_policy_agents,
  );

  return {
    environmentId:
      text(source.environment_id) || text(source.id, "eeg-marker-recovery"),
    scenarioId:
      text(source.scenario_id) ||
      text(root.scenario_id) ||
      text(scenario.scenario_id) ||
      text(scenario.id, "eeg-duplicate-onset-seed-01"),
    name:
      text(source.name) || text(source.title, "EEG onset-marker recovery"),
    description:
      text(source.description) ||
      "A deterministic synthetic preflight for the onset-marker route.",
    validation: {
      status: text(validation.status, "unknown"),
      summary:
        text(validation.summary) ||
        text(validation.message, "Environment validation unavailable"),
      checks: stringList(validation.checks),
    },
    policyAgents:
      agents.length > 0
        ? agents
        : [{ id: "seeded-policy-agent", name: "Seeded recovery Policy agent" }],
    hiddenStateExposed: source.hidden_state_exposed === true,
  };
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = asRecord(await response.json());
      message = text(body.detail) || text(body.message) || message;
    } catch {
      // The status remains useful when the server returns no JSON body.
    }
    throw new Error(message);
  }

  return response.json();
}

function normalizeRun(payload: unknown): RunSnapshot {
  const root = asRecord(payload);
  const source = isRecord(root.snapshot)
    ? root.snapshot
    : isRecord(root.run)
      ? root.run
      : root;
  const runId = text(source.run_id);
  if (!runId) throw new Error("The runtime response did not include a run identity.");

  return {
    ...source,
    run_id: runId,
    scenario_id: text(source.scenario_id),
    revision_digest: text(source.revision_digest),
    scenario_digest: text(source.scenario_digest),
    policy_agent:
      typeof source.policy_agent === "string" || isRecord(source.policy_agent)
        ? (source.policy_agent as string | PolicyAgent)
        : "Unknown Policy agent",
    status: text(source.status, "active"),
    observation: asRecord(source.observation),
    permitted_actions: Array.isArray(source.permitted_actions)
      ? (source.permitted_actions as Array<string | UnknownRecord>)
      : [],
    trace: Array.isArray(source.trace)
      ? (source.trace.filter(isRecord) as UnknownRecord[])
      : [],
    verifier_result: isRecord(source.verifier_result)
      ? source.verifier_result
      : null,
    replay_metadata: isRecord(root.replay_metadata)
      ? root.replay_metadata
      : isRecord(source.replay_metadata)
        ? source.replay_metadata
        : null,
    replay: isRecord(root.replay)
      ? root.replay
      : isRecord(source.replay)
        ? source.replay
        : null,
  };
}

export const environmentApi = {
  async getEnvironment(): Promise<EnvironmentSummary> {
    return normalizeEnvironment(await request("/api/environment"));
  },

  async startRun(scenarioId: string, policyAgent: string): Promise<RunSnapshot> {
    return normalizeRun(
      await request("/api/runs", {
        method: "POST",
        body: JSON.stringify({ scenario_id: scenarioId, policy_agent: policyAgent }),
      }),
    );
  },

  async getRun(runId: string): Promise<RunSnapshot> {
    return normalizeRun(await request(`/api/runs/${runId}`));
  },

  async applyAction(runId: string, type: string): Promise<RunSnapshot> {
    return normalizeRun(
      await request(`/api/runs/${runId}/actions`, {
        method: "POST",
        body: JSON.stringify({ type }),
      }),
    );
  },

  async verify(runId: string): Promise<RunSnapshot> {
    return normalizeRun(
      await request(`/api/runs/${runId}/verify`, { method: "POST" }),
    );
  },

  async reset(runId: string): Promise<RunSnapshot> {
    return normalizeRun(
      await request(`/api/runs/${runId}/reset`, { method: "POST" }),
    );
  },

  async replay(runId: string): Promise<RunSnapshot> {
    return normalizeRun(
      await request(`/api/runs/${runId}/replay`, { method: "POST" }),
    );
  },
};
