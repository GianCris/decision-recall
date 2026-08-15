# DR-Bench

DR-Bench v0.1 is a mechanism-agnostic benchmark for Material Decision
Dependence, selective reevaluation, and minimum-disruption recovery.

The frozen dataset contains 16 deterministic scenarios: 12 development and 4
holdout. It deliberately includes independent, supporting/non-material,
material, and critical dependencies plus adversarial related-but-unaffected
decisions and consequences.

It contains no candidate mechanism, baseline, Gemini integration, ADK/Fleet
infrastructure, or UI.

## Quick start

Python 3.11 or newer is required. There are no runtime dependencies.

```powershell
python -m unittest discover -s tests -v
python -m dr_bench list
python -m dr_bench show dev-001 --phase discovery
python -m dr_bench show dev-001 --phase recovery
python -m dr_bench evaluate dev-001 candidate.json --phase discovery
```

The public API `candidate_view(scenario, phase)` is the only supported way to
hand scenario input to a candidate. Raw loaded records contain a private oracle
and must remain inside the benchmark harness.

See [docs/SCHEMA.md](docs/SCHEMA.md) for the experimental contract.
