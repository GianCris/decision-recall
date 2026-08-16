# Mechanism Tournament Round A1 scaffold

The authoritative scientific design remains
`docs/MECHANISM_TOURNAMENT_V0.1.md`. Runtime constants are literal copies of
the frozen probe blocks and regression tests verify them against that document.

Prepare an audited output directory without constructing a provider client:

```powershell
python -m dr_baselines.mechanism_tournament --output-dir mechanism-a1-output --prepare
```

PREPARE freezes the current Git identity, protocol and prompt hashes, condition
registry, candidate-view routing, structured response schema, audited v0.4
transport policy, cyclic 60-slot plan, position counts, and classification
completeness policy. EXECUTE refuses a changed Git/configuration/manifest/plan
and never regenerates prepared inputs. It requires a separately authorized
explicit command:

```powershell
python -m dr_baselines.mechanism_tournament --output-dir mechanism-a1-output --execute
```

M0/M1/M2/M3 use the frozen implicit view; R1 uses the frozen structured view.
Every call is built independently from its slot input. Native structured output
and the existing parser/evaluator remain unchanged. Delivery uses the audited
v0.4 adapter, timeout, single SDK attempt, four-attempt harness cap, 5/10/20
backoff, first-response-wins rule, and 10-second sequential inter-slot pacing.

Runs, evaluations, `delivery_attempts.jsonl`, and `summary.json` preserve the
scientific-slot/delivery-attempt distinction. Any missing, invalid, failed, or
aborted observation forces `A1_CLASSIFICATION_INCOMPLETE`; no candidate is
advanced or eliminated automatically.

Offline analysis makes no provider call:

```powershell
python -m dr_baselines.mechanism_tournament --output-dir mechanism-a1-output --analyze --analysis-dir mechanism-a1-analysis
```

It writes a decision ledger, M0 comparisons, condition metrics, frozen probe
classifications, and a development-only report. Run all tests with:

```powershell
python -m unittest discover -s tests -v
```

This scaffold is DEV-only and has no sealed-holdout input path.
