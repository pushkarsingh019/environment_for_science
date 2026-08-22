# Environments for Science

This context describes how scientific apparatus and adaptive procedures become executable environments for evaluating and improving agents.

## Language

**Environment author**:
An experimental scientist who understands an apparatus and its procedure but is not expected to write code or understand ML or RL interfaces.
_Avoid_: Developer, ML engineer

**Authoring assistant**:
The scientist-facing agent that helps an Environment author create, revise, preview, and understand an Environment. It does not participate in scored Policy-agent runs.
_Avoid_: Environment author, Policy agent

**Policy agent**:
The isolated model evaluated or trained inside a frozen Environment. It can act on the simulated Apparatus but cannot edit the Environment, inspect hidden scenario state, or alter verifiers.
_Avoid_: Authoring assistant, Environment author

**Instrument**:
A commercially supplied device used as part of a scientific apparatus.
_Avoid_: De novo equipment, system

**Custom component**:
Lab-built hardware or software used as part of a scientific apparatus.
_Avoid_: Custom stuff

**Apparatus**:
The connected collection of instruments and custom components used to perform an experiment.
_Avoid_: Setup, system

**Montage**:
The electrodes selected from an EEG cap and their reference scheme for a particular procedure. A montage configures an EEG apparatus; it does not define or limit the apparatus.
_Avoid_: Channels, cap

**Paradigm**:
The stimuli, task, trial conditions, and response meanings used by a procedure. A paradigm is not the apparatus that presents and records it.
_Avoid_: Setup, environment

**Procedure**:
An adaptive, stepwise scientific workflow whose next step can depend on current observations.
_Avoid_: Flow, fixed checklist

**Environment**:
An executable representation of a procedure through observations, permitted actions, transitions, safety rules, and verifiers.
_Avoid_: Workflow, simulation

**Harness**:
Software that runs and evaluates agent episodes in an environment.
_Avoid_: Environment, trainer
