# Separate the authoring agent from the policy agent

Type: grilling
Status: resolved
Blocked by:

## Question

What responsibilities, state, tools, UI presence, and trust boundaries distinguish the agent that helps a scientist author and validate an environment from the policy model evaluated and trained inside that environment? Decide the canonical names for both roles and whether one model may ever fill both roles in the prototype.

## Answer

Use two isolated roles: the **Authoring assistant** edits a reversible Environment draft in the building workspace, while the **Policy agent** receives full simulated-Apparatus access inside a frozen run but cannot see hidden state or change the Environment or verifiers. The same underlying model may serve both through isolated instances. Keep simulation controls simple and defer real-hardware permissions. [Accepted boundary decision](../adr/0001-separate-authoring-assistant-from-policy-agent.md).
