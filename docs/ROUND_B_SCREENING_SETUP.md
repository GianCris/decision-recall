# Round B v0.1 Screening Scaffold

The scientific source of truth is `docs/ROUND_B_PROTOCOL_V0.1.md`. This scaffold is DEV-screening only; it does not authorize confirmation or sealed-holdout access.

Prepare without provider calls:

```powershell
python -m dr_baselines.round_b --output-dir round-b-screening-output --prepare
```

Execute later, only after explicit authorization and authentication:

```powershell
python -m dr_baselines.round_b --output-dir round-b-screening-output --execute
```

Analyze completed artifacts offline:

```powershell
python -m dr_baselines.round_b --output-dir round-b-screening-output --analysis-dir round-b-screening-analysis --analyze
```

The prepared directory freezes `execution_plan.json` and `experiment_manifest.json`. Execution separately persists delivery lifecycle, raw Stage-1 responses, canonical Stage-1 artifacts and hashes, terminal states, final RunRecords, evaluations, and `summary.json`. Stage-1 artifacts are intermediate observations and never enter Discovery performance denominators. Analysis creates a decision-level ledger, JSON analysis, and a claim-bounded Markdown report.
