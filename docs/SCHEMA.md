# DR-Bench v0.1 contract

Each JSONL record is a standalone scenario. The normative machine-readable
shape is in `dr_bench/schema/scenario.schema.json`.

## Scenario lifecycle

1. `world` is the initial JSON object visible to a benchmark harness.
2. `events` are applied by ascending `seq`. Operations use JSON Pointer paths.
3. The system under test receives whatever history/context the experimenter
   chooses, plus `task.prompt`.
4. The system returns any JSON value.
5. `oracle.assertions` deterministically score that value.

The benchmark specifies neither memory nor retrieval. A harness may expose the
whole timeline, distribute events across agents, or hide history behind its own
mechanism. Results should document that experimental protocol.

## Event operations

- `set`: create or replace an object member.
- `delete`: remove an existing object member.
- `append`: append one JSON value to an existing array.

All operations are deterministic. Events must have unique, strictly increasing
positive sequence numbers.

## Assertions

Assertion paths point into the candidate response. Supported operators are:

- `equals` and `not_equals` (strict JSON type and value for `equals`)
- `contains` (string substring, array member, or object key)
- `set_equals` (order-insensitive array equality; scalar members only)
- `exists` and `absent`

The score is passed assertions divided by total assertions. A scenario passes
only at 1.0. The `oracle.final_world` entries are authoring-time invariants used
to catch inconsistent scenario data; they are not candidate assertions.

## Holdout note

The four holdout scenarios ship with v0.1 so the package is reproducible. Their
oracle data should not be supplied to a system under test. This is a structural
holdout, not a secret test set.
