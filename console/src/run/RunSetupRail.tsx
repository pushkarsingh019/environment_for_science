import type { EnvironmentSummary } from "../types";

interface RunSetupRailProps {
  environment: EnvironmentSummary;
  selectedAgent: string;
  onSelectAgent: (id: string) => void;
  busy: boolean;
}

/** Details-rail "Run setup" section shown in Run mode before a run starts. */
export function RunSetupRail({ environment, selectedAgent, onSelectAgent, busy }: RunSetupRailProps) {
  return (
    <div className="run-setup">
      <p className="run-setup-copy">Choose a seeded example in the bar and press Start.</p>
      <label className="run-setup-label" htmlFor="policy-agent">
        Policy agent
      </label>
      <select
        className="run-setup-select"
        disabled={busy}
        id="policy-agent"
        onChange={(event) => onSelectAgent(event.target.value)}
        value={selectedAgent}
      >
        {environment.policy_agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      <p className="rail-note">{environment.simulation_label}. No hardware connection.</p>
    </div>
  );
}
