# Keep Environment semantics in one product-owned runtime

Status: accepted

Use one repository with a React/TypeScript scientist console and a local Python application that owns Environment Bundle validation, deterministic EEG and mesoscope execution, canonical traces, and compilation. The console and Verifiers adapter call the same deep run interface so scientific state transitions and verifier inputs are not duplicated. Provider adapters, Verifiers, and prime-rl sit at replaceable seams; authored bundles remain authoritative and generated framework artifacts remain disposable.
