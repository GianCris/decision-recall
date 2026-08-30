# Decision Recall — Temporal Authority + Full Replay (M2.1)

Decision Recall separates questions that ordinary agent memory can easily blur:

1. **When did information become available to the system?** (`batch_seq`; `recorded_at` is metadata)
2. **What time or interval is the evidence about?** (`TemporalReference`)
3. **For what world time is an evaluation being performed?** (`world_time`)
4. **What exact semantic entity/assertion was authorized?** (contract artifact + entity definition hash + assertion)
5. **Under what context was it authorized?** (`COMMIT_TIME`, `EVALUATION_DERIVED`, or `RECOVERY_DERIVED` + `scope_ref`)
6. **What exact committed contract and target did an evaluation consume?** (canonical artifacts + hashes)
7. **Can the original epistemic result be reproduced from those exact inputs?** (full replay through `evaluate_target()`)

The central rule remains:

> Later evidence may change today's assessment of the past, but it never changes what was recorded or authorized in an earlier historical view.

## Canonical semantic identity

M2.1 uses one explicitly versioned canonicalization scheme: `CANONICAL_V1`.

Canonical artifacts are stored for:

- the committed `DecisionContract`;
- the versioned `TargetSpec`;
- the world/metric schema used to validate world evidence.

Each artifact contains canonical JSON and a SHA-256 content hash. Authorizations additionally bind to an `entity_definition_hash`, so authorizing the entity named `R1` is not enough: the authorization is tied to the exact semantic definition of that R1 within the exact contract artifact.

Changing the definition while preserving the human-readable entity ID changes the hash and invalidates reuse of the old authorization.

## Atomic ledger time

The temporal ledger uses monotonic `batch_seq` plus `entry_ordinal` inside a batch.

A cutoff is always a complete batch. There is no supported historical view in the middle of one atomic operation. Evidence + authorization + decision commit can therefore be written transactionally without creating an artificial intermediate state.

The PostgreSQL temporal adapter allocates `batch_seq` by locking one ledger-head row with `SELECT ... FOR UPDATE`. Typed records and ledger ordering metadata commit in the same database transaction.

`batch_seq` is the ordering authority used by historical cutoffs. `recorded_at` is useful temporal metadata; M2.1 does not claim a cryptographically trusted clock.

## Exact committed contract

A strong decision commit is bound to:

- `decision_id`;
- `contract_version`;
- immutable contract artifact ID;
- canonical contract hash;
- CaptureProfile version/hash;
- commit cutoff.

For V1, the same `decision_id + contract_version` cannot be committed twice in the supported semantic registry. A materially new decision should receive a successor decision ID rather than silently replacing the old contract.

A contract hash is not used as a substitute for the contract itself: the canonical artifact is retained so replay can reconstruct the exact object.

## Scoped semantic authority

Authorization is not `authorized=true`.

A scoped authorization binds:

- exact contract artifact;
- entity ID;
- entity definition hash;
- exact authorized assertion;
- exactly one supporting evidence record in V1;
- policy version/hash;
- authorization scope;
- scope reference;
- TargetRef for derived evaluation/recovery authority when applicable.

`COMMIT_TIME` authority is usable for the recorded-at-commit historical view only when the corresponding authorization is actually visible at the commit cutoff and matches the real ledger `AuthorizationRecord`, evidence, policy, contract artifact, and entity hash.

`EVALUATION_DERIVED` and `RECOVERY_DERIVED` authority cannot silently rewrite the committed t0 view.

This implements:

> Evidence existing != a historical relation having been authorized at commit time.

## Historical epistemic states

`T0_UNRESOLVED` is a positive historical claim. It requires temporally valid contemporaneous authority that the uncertainty itself was known to be unresolved at t0.

For a **known slot in the committed contract**, absence of such authority can yield `NOT_DURABLY_RECORDED`.

For an entity that never existed in the committed contract, the projection rejects it as unknown/out of scope rather than pretending it was merely “not durably recorded.”

This implements:

> “We did not preserve the answer” != “We knew at the time that the answer was unknown.”

## Availability time != world time

A ledger cutoff answers:

> What information was available to Decision Recall?

`world_time` answers:

> For what point in the world is this evaluation being performed?

The authorized world projection therefore uses both.

For the V1 aggregate semantics used by the Supplier Resilience golden scenario, an interval statistic becomes usable at the end of its interval. A 30-day aggregate ending Oct 4 cannot be used by an evaluation of Sep 20 merely because the source was already present in storage.

If two equally applicable, authorized observations for the same metric conflict and neither has been superseded/corrected under the V1 model, the metric is omitted from the canonical world state so downstream `CurrentMatch` becomes `UNKNOWN`. Decision Recall does not silently choose a winner by insertion order.

## World evidence boundary

The world side remains:

`RawWorldEvidence -> EventPolicy -> WorldEventAuthorizationRecord -> AuthorizedWorldState`

Raw evidence alone does not change CurrentMatch. Its first-class event authorization must be visible and reproducible under the referenced EventPolicy.

Stored raw-world content hashes are checked before strict replay so tampered content cannot silently retain old authority metadata.

## Dependency-aware corrections

Corrections are append-only.

A correction makes its target inactive in the **current effective projection** but does not remove the original ledger entry. If corrected evidence supported an authorization, that dependent authorization also becomes inactive for the current projection rather than crashing the entire view.

An `as_of()` view from before the correction still reconstructs the original state.

M2.1 deliberately does not claim a complete governance framework for who is allowed to issue corrections; correction authorization/quorum is outside the hackathon-critical V1 scope.

## Strong evaluation identity

A replayable evaluation snapshot is bound to:

- a concrete decision commit;
- exact contract hash;
- evaluation input cutoff;
- `world_time`;
- exact Target artifact/hash;
- exact world-schema artifact/hash;
- evidence/authority policy version/hash;
- EventPolicy version/hash;
- engine version/hash;
- canonical evaluation result;
- canonical result hash;
- canonicalization version.

An evaluation that references a missing/non-visible commit is rejected.

## Full replay guarantee

The M2.1 replay path does not hash only historical evidence metadata.

It performs:

`commit artifact`
`+ scoped commit-time authority at the commit cutoff`
`+ authorized world state at input cutoff AND world_time`
`+ exact TargetSpec artifact`
`+ exact world schema`
`+ policy identities`
`+ engine artifact identity`
`-> materialized ValidatedDecisionContract`
`-> evaluate_target()`
`-> canonical TargetEvaluation`
`-> result hash`

Strict verification compares both the replayed canonical result and its hash with the stored evaluation snapshot.

The defensible guarantee is:

> Given the same committed canonical artifact, temporal input cutoff, world time, policy/Target/world-schema configuration identities, and engine artifact identity, Decision Recall reproduces the same canonical epistemic evaluation result.

This is not a claim that arbitrary raw-language LLM extraction is deterministic.

## PostgreSQL parity

The temporal ledger already has a real PostgreSQL 16 adapter. M2.1 additionally persists the canonical artifacts, scoped authorization metadata, strong commit identity, and canonical evaluation snapshot so a fresh process can reload the semantic registry and replay an evaluation against the PostgreSQL ledger.

A conformance test executes the same temporal operations in memory and PostgreSQL and checks equivalent replay/correction behavior.

## Deliberate V1 limits

To keep the hackathon-critical path rigorous rather than ornamental, M2.1 deliberately does **not** add:

- blockchain or cryptographic signing;
- distributed consensus;
- trusted timestamp infrastructure;
- arbitrary multi-evidence composition (one evidence record per semantic authorization in V1);
- a general interval algebra;
- correction quorum/governance;
- multi-region event sourcing.

These are extensions, not prerequisites for the Supplier Resilience golden path.

## Adversarial closure tests

The dedicated M1/M2/M2.1 suite attacks, among other things:

- hindsight leakage;
- commit-authority leakage;
- false historical UNKNOWN promotion;
- semantic entity-definition swaps;
- contract mutation under the same human label;
- ghost evaluations without a real commit;
- evaluation-derived authority rewriting t0;
- future-valid world evidence leaking into earlier `world_time`;
- conflicting authorized world observations;
- source-content hash tampering;
- evidence correction cascades;
- full world-sensitive replay through `evaluate_target()`;
- canonicalization stability;
- PostgreSQL registry reload and in-memory/PostgreSQL replay parity.

On the current M2.1 branch, GitHub Actions executes 73 dedicated Decision Recall tests against the deterministic core, temporal/authority layers, full replay, and PostgreSQL integration, plus a separate non-core deterministic/offline regression job.