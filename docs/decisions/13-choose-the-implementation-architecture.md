# Choose the implementation architecture

Type: grilling
Status: resolved
Blocked by: 06

## Question

Given the chosen visual language, portable Environment contract, EEG simulator contract, and demo story, where should the frontend, seeded Authoring assistant, deterministic simulator runtime, compiler, verifier adapter, trace store, and result-ingestion seams live? Choose a repository and module shape that can implement the accepted EEG episode incrementally without turning generated artifacts or third-party frameworks into the product's core model.

## Decision

Use one repository with a React/TypeScript scientist console and a local Python application containing the product-owned contract validator, deterministic runtime, EEG and mesoscope Environment modules, trace store, compiler, and adapters. The UI and Verifiers adapter call the same deep run interface so simulator semantics are not duplicated. Keep provider adapters, Verifiers, and prime-rl at replaceable seams; generated artifacts live outside authored bundles. Store local drafts and canonical traces in SQLite/JSONL, and run training and inference only on the two workstations. See ADR 0002.
