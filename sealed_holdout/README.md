# Sealed final holdout v0.1

Dataset identifier: `decision-recall-sealed-final-holdout-v0.1`.

This directory exists only on `sealed/final-holdout-v0.1`. It is separate from
`dr_bench/data`, is not package data, and is not enumerated by the normal
DR-Bench catalog. It must not be copied or merged into development, pilot,
baseline, mechanism, ablation, or challenge-set branches.

The eight scenarios are for final generalization evaluation. Their complexity
metadata is descriptive strata, not a controlled causal design. They cannot be
used to claim causal effects of hops, semantic distance, transformation,
visibility, or authority. Such claims require a separate future CADC sweep.

Only structural inspection is permitted before final evaluation:

```powershell
python -m sealed_holdout.validate_sealed
```

Do not invoke a model, baseline, or provider from validation tooling.
