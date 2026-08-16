# DEV Failure Autopsy v0.1

This is an offline, forensic, descriptive analysis of the frozen official
`dev-baselines-v0.4` execution. It does not call Gemini, require provider
credentials, infer hidden reasoning, or make causal claims.

Run from the repository root:

```powershell
python -m dr_baselines.dev_autopsy
```

The command accepts no source-selection arguments. It reads only
`dev-baseline-output-v4/` and refuses the source unless its manifest, summary,
execution-plan hash, frozen prompt/schema identifiers, 72 RunRecords, and 72
evaluations pass the fixed integrity checks. It creates
`dev_failure_autopsy_v0.1/` and refuses to overwrite an existing directory.

The primary ledger contains one row per scenario, repetition, baseline, and
decision—not one row per run. Observation-level failures retain repeated
predictions separately. Unique failure records collapse scenario, decision,
baseline, and error dimension while reporting failed and observed repetitions.

Successful comparison controls are selected using exact matches only. The
artifacts include all controls matching each individual frozen metadata field
and all ties for the largest exact field combination having at least one
match. No weighted distance, nearest-neighbor ranking, or manually selected
example is used.

Metadata slices overlap, repetitions are not independent scenarios, B1 is not
an oracle, and the structured outputs contain no hidden reasoning traces. The
analysis is descriptive rather than causal. Sealed-holdout data is prohibited
and is not a dependency of the analyzer.
