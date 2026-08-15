# DR-Bench v0.1 experimental contract

DR-Bench evaluates two phases independently under the frozen FLEET-1 protocol.

## Public/private boundary

Every record has a `candidate` partition and a `private` partition. Harnesses
must call `candidate_view(scenario, phase)` and must never send a raw record to
a system under test.

Discovery has two explicit conditions with the same private oracle:

- `structured`: decisions retain `evidence_available` knowledge IDs and
  structured assumptions. This is the provenance-available condition.
- `implicit`: decisions omit both fields. Dependence must be inferred from
  observable knowledge, changes, roles, timestamps, decisions, and intermediate
  cross-agent transmissions. This is the provenance-hidden condition.

Both conditions contain current consequences, available recovery actions, and
complexity metadata. Neither contains dependence or recovery ground truth.

Recovery views contain the same observable information plus
`affected_decision_ids`. This is intentional: Recovery receives ground-truth
affected decisions so Discovery advantage cannot leak into Recovery. Strength,
paths, still-justified labels, consequence labels, expected actions, and
expected final state remain private.

## Discovery contract

A Discovery candidate returns:

```json
{"decisions":[{"decision_id":"d1","materially_dependent":true,"dependency_strength":"critical","still_justified":false}]}
```

The oracle makes precision, recall, F1, false positives, false negatives,
strength accuracy, still-justified accuracy, and multi-hop recall objectively
computable. `independent` and `supporting` are non-material; `material` and
`critical` are materially dependent. Downstream status is a separate label.

## Recovery contract

A Recovery candidate returns selected public action IDs and an execution step:

```json
{"action_ids":["a1"],"at_step":1}
```

Actions expose their observable effects, cost, responsible role, and recovery
window. The private oracle identifies required and protected consequences,
desired repaired values, expected minimum action set, and final-world
invariants. The evaluator reports repair correctness, wrongful rollback,
unnecessary disruption, recovered value, recovery-window capture, and final
world-state correctness.

Action effects are applied in submitted order to a deep copy of the observable
world. Simulation is deterministic.

## Complexity axes

Each scenario declares controlled levels for agent hops (`0`, `1`, `2`, `4`),
semantic distance, information transformation, and organizational boundary.
The levels vary across DEV and HOLDOUT rather than collapsing into one hardness
score.

`candidate.transmissions` represents observable cross-agent messages,
summaries, plans, and intermediate outputs. Each item identifies sender,
recipient, time, content, and an optional predecessor transmission. The declared
agent-hop level must equal the longest valid predecessor chain. Validation also
requires each linked handoff to continue from the prior recipient and advance
in time. Thus multi-hop levels are structural rather than descriptive metadata.

The four bundled HOLDOUT cases have been inspected during benchmark design and
are therefore design holdout only, not a final blind experimental holdout. A
truly untouched set is intentionally deferred until immediately before
mechanism tuning.

The machine-readable structural schema is
`dr_bench/schema/scenario.schema.json`; cross-reference invariants are enforced
by `validate_scenario`.
