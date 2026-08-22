# Environments for Science

Science Environment Studio is a simulation-only prototype for authoring, running,
evaluating, and improving AI agents on scientific procedures. The first implemented
Environments model scalp electroencephalography (EEG) and a sealed synthetic mesoscope
handoff. The project doesn't connect to or control physical apparatus.

![Current Hero of the Project - an eeg setup](assets/hero1.png)

## Project status

The product, domain, interface, runtime, evaluation, and training decisions are complete.
Tickets 01 and 02 of 13 are complete and runnable end to end; eleven tickets remain. Ticket
03 is the next dependency-order target, and ticket 05 is also unblocked.

Read these documents before you implement a ticket:

1. [`CONTEXT.md`](CONTEXT.md) defines the canonical domain language.
2. [`docs/specification.md`](docs/specification.md) defines the executable product and
   its test requirements.
3. [`docs/implementation/README.md`](docs/implementation/README.md) tracks the build
   order and implementation checkpoint.
4. [`docs/product-decision-map.md`](docs/product-decision-map.md) links the resolved
   product decisions and supporting research.
5. [`DESIGN.md`](DESIGN.md) supplies visual tokens. It doesn't define the page layout.

The next implementation target is
[ticket 03: Diagnose EEG signal and response failures visually](docs/implementation/issues/03-diagnose-eeg-signal-and-response-failures-visually.md).

## Implementation checkpoint

Tickets 01 and 02 provide:

- An extensible Environment Bundle v1 validator with nested JSON Schema checks.
- A seeded synthetic EEG marker-recovery bundle and apparatus module.
- A deterministic Environment Runtime with immutable revisions, verification, reset, and
  true replay.
- A strict local HTTP adapter and append-only caller-visible JSONL trace journal.
- A quiet React and TypeScript Scientist Console with a visualization-first EEG workflow.
- A configurable schematic whole-cap Apparatus and a distinct Procedure-selected Montage.
- Bounded conversational authoring, reversible persistent drafts, and unverified note staging.
- Content-addressed frozen revisions with explicit Authoring-assistant/Policy-agent isolation.
- Durable frozen/run indexes, full-trace bindings, cross-process serialization, and
  crash-consistent prepared-intent recovery.
- Runtime, HTTP, and real-backend browser coverage for positive and negative paths.

The repository also retains the disposable Gemma training-path probe under
`probes/gemma-training-path/`; it is not product runtime code.

## Set up a development checkout

The Python package requires Python 3.9 or later. The console requires Node.js and npm.

1. Create the Python environment and install the development dependencies:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -e ".[dev]"
   ```

2. Install the console dependencies:

   ```bash
   cd console
   npm ci
   cd ..
   ```

3. Optional: Install Chromium for the Playwright browser test:

   ```bash
   cd console
   npx playwright install chromium
   cd ..
   ```

## Run the current product

From the repository root, one command builds the Scientist Console and starts both it and
the deterministic Runtime:

```bash
.venv/bin/python -m studio
```

Open `http://127.0.0.1:8000`. The application binds only to loopback and exposes synthetic
actions only. The persistent draft and frozen/run indexes are stored in
`artifacts/draft-workspace.sqlite3` and `artifacts/studio-index.sqlite3`. Each run writes an
append-only caller-visible trace under `artifacts/traces/`; generated artifacts are ignored
by Git.

## Run the available checks

Run the Python checks from the repository root:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check studio environments tests
.venv/bin/mypy studio environments
```

Run the console checks from the `console/` directory:

```bash
npm run build
npm run test:browser
```

The browser suite starts the same loopback-only product command and exercises the real
Runtime API; it does not mock HTTP responses.

## Repository layout

- `console/`: React and TypeScript Scientist Console.
- `studio/`: Product-owned Python contract and runtime code.
- `environments/`: Authored bundles and apparatus-specific Environment modules.
- `tests/`: Runtime and integration tests.
- `docs/implementation/`: Dependency-ordered implementation tickets.
- `docs/decisions/` and `docs/adr/`: Resolved product and architecture decisions.
- `docs/research*`: Scientific, model, serving, and provider research.
- `probes/`: Disposable integration probes that aren't product runtime code.
- `prototypes/`: Rejected or throwaway interaction prototypes retained as decision
  records.

## Safety and repository boundaries

Keep credentials in environment variables and local `.env` files. Don't commit model
artifacts, generated traces, private host details, SSH material, or workstation
credentials. Training and inference run only on the approved remote GPU workstations;
the local computer is an orchestration and interface host.
