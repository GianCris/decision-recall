# DR-Bench

DR-Bench v0.1 is a small, mechanism-agnostic benchmark for testing whether an
agent can act on decisions after the surrounding world changes.

The initial release contains:

- 16 deterministic scenarios: 12 development and 4 holdout
- a versioned JSON scenario schema
- a minimal, deterministic world-state simulator
- validators for both scenario definitions and candidate responses
- a command-line runner and standard-library-only tests

It intentionally contains no Gemini integration, Decision Recall mechanism,
ADK Fleet integration, or UI.

## Quick start

Python 3.11 or newer is required. No runtime dependencies are needed.

```powershell
python -m unittest discover -s tests -v
python -m dr_bench list
python -m dr_bench show dev-001
python -m dr_bench evaluate dev-001 candidate.json
```

A candidate file is any JSON value. Each scenario declares assertions against
that value, so the benchmark does not prescribe how a system arrives at its
answer. For example, `dev-001` expects:

```json
{"vendor": "Nimbus", "region": "eu-west"}
```

See [docs/SCHEMA.md](docs/SCHEMA.md) for the scenario and evaluation contract.
