---
status: accepted
---

# Separate the Authoring assistant from the Policy agent

The **Authoring assistant** helps the Environment author build and understand an Environment, while the **Policy agent** is evaluated or trained inside a frozen Environment. They have separate prompts, tools, context, state, and logs: the Policy agent can use all simulated Apparatus actions but cannot edit the Environment, inspect hidden scenario state, or alter verifiers, and the Authoring assistant is absent from scored runs. The same underlying model may fill both roles only through isolated instances.

Because the prototype controls mock instruments only, it has no permissions or approval framework. Authoring-assistant changes apply directly to a reversible draft, and evaluation and training use ordinary launch controls; real-hardware authorization is a future boundary rather than prototype behavior. In the UI, the Authoring assistant appears in the building workspace, while a separately labeled Policy agent appears in run traces with its model, observations, actions, and score.
