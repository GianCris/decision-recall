# Round B v0.2 Interface and Screening Scaffold

The scientific source of truth is `docs/ROUND_B_PROTOCOL_V0.2.md`. Round B
v0.1 and its outputs remain immutable historical evidence. These commands are
documented for later explicit authorization; implementation verification does
not execute them.

Prepare the separate six-call Stage-1 interface sanity without provider calls:

```powershell
python -m dr_baselines.round_b_sanity --output-dir round-b-v02-sanity-output --prepare
```

Execute that sanity later, only after explicit authorization and authentication:

```powershell
python -m dr_baselines.round_b_sanity --output-dir round-b-v02-sanity-output --execute
```

The sanity schedules no Stage 2 and performs no Discovery evaluation. Its
artifacts cannot be reused by full screening. Sanity and screening require
different new output directories and incompatible manifest types.

Prepare without provider calls:

```powershell
python -m dr_baselines.round_b --output-dir round-b-v02-screening-output --prepare
```

Execute later, only after explicit authorization and authentication:

```powershell
python -m dr_baselines.round_b --output-dir round-b-v02-screening-output --execute
```

Analyze completed artifacts offline:

```powershell
python -m dr_baselines.round_b --output-dir round-b-v02-screening-output --analysis-dir round-b-v02-screening-analysis --analyze
```

The full-screening prepared directory freezes `execution_plan.json` and
`experiment_manifest.json`. Execution separately persists delivery lifecycle,
raw Stage-1 responses, validated canonical model payloads, out-of-band artifact
envelopes and hashes, terminal states, final RunRecords, evaluations, and
`summary.json`. Envelope fields never enter Stage-2 prompts. Stage-1 artifacts
are intermediate observations and never enter Discovery performance
denominators. Analysis creates a decision-level ledger, JSON analysis, and a
claim-bounded Markdown report.
