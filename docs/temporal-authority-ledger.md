# Decision Recall — Temporal + Authority Ledger (M2)

Decision Recall separates four questions that ordinary memory systems can easily blur:

1. **When did a source or assertion become available to Decision Recall?** (`recorded_at` / `batch_seq`)
2. **What time or interval is that evidence about?** (`TemporalReference`)
3. **What exact assertion did a policy authorize from that evidence?** (`AuthorizationRecord`)
4. **What was the system legitimately able to use at a particular cutoff?** (`as_of(cutoff_seq)`)

The central rule is:

> Later evidence may change today's assessment of the past, but it never changes what was recorded or authorized in an earlier historical view.

## Atomic ledger time

The ledger uses a monotonic `batch_seq` plus `entry_ordinal` inside a batch.

A cutoff is always a complete batch. There is no supported historical view in the middle of one atomic operation. Evidence + authorization + decision commit can therefore be written transactionally without creating an artificial intermediate state.

The PostgreSQL adapter allocates `batch_seq` by locking a single ledger-head row with `SELECT ... FOR UPDATE`. The semantic records and ledger index are committed in the same database transaction.

## Typed records, not a duplicate JSON event store

Typed domain tables are the semantic source of truth. `dr_ledger_entries` contains ordering/index metadata; it is not a second JSON copy of the domain state.

M2 persists typed records for:

- evidence and candidate assertions;
- authorization decisions;
- decision commits;
- evaluation snapshots;
- raw world evidence and observations;
- world-event authorization;
- corrections.

## Commit cutoff vs evaluation input cutoff

These are deliberately different.

A **decision commit cutoff** answers:

> What had been durably recorded and authorized when D-104 was committed?

If evidence existed before commit but its historical-role authorization was created only later, the committed historical view does **not** retroactively contain that role.

An **evaluation input cutoff** answers:

> What inputs was EV-901 allowed to inspect when evaluation started?

An evaluation may deterministically derive a policy authorization from evidence visible at that cutoff and persist that authorization/result afterward. The authorization output therefore does not have to pre-exist its own evaluation input cutoff.

## Historical epistemic states

`T0_UNRESOLVED` is a positive historical claim. It requires contemporaneous authority showing that, at t0, the relevant uncertainty was explicitly unresolved.

Absence of such an authorized record is **not** promoted to `T0_UNRESOLVED`. For a known required slot such as C1, the recorded historical view instead yields `NOT_DURABLY_RECORDED`.

This implements:

> “We did not preserve the answer” != “We knew at the time that the answer was unknown.”

Later retrospective testimony about t0 can be displayed in a current assessment, while the original recorded-at-t0 view stays unchanged.

## Semantic authority

Authorization is never just `authorized=true`.

An authorization binds:

- a concrete entity;
- an exact authorized assertion (for example `ESTABLISHED_HISTORICAL_ROLE`, `T0_UNRESOLVED`, `CURRENT_MATCH_RULE`, or `REVISIT_RULE`);
- evidence IDs;
- policy version;
- policy hash.

Persisted authorizations are replay-checked against the referenced policy and evidence when a historical view is reconstructed. Metadata claiming to have been authorized is not enough by itself.

Applicability and revisit rules remain independently authorized even when they happen to use the same numerical threshold.

## World evidence

The world side has the same boundary:

`RawWorldEvidence -> EventPolicy -> WorldEventAuthorizationRecord -> AuthorizedWorldState`

Raw world evidence is not visible to current-match evaluation merely because it exists. A first-class event authorization must also be present in the same as-of snapshot.

For V1, multiple authorized observations of a metric are resolved by:

1. latest temporal reference (`observed_at` or interval end);
2. then ledger batch/order as a deterministic tie-breaker.

Therefore late-arriving evidence about an older period cannot overwrite a newer world observation merely because it was ingested later.

## Corrections

Corrections are append-only. A correction suppresses the corrected entry in the current effective projection, while `as_of()` before the correction still reproduces the original view.

Decision Recall never deletes the old record to make history look cleaner.

## Replay guarantee

For the V1 temporal core, replay identity is anchored by:

- input cutoff;
- policy version + hash;
- TargetSpec version + hash;
- engine version + hash.

The same canonical inputs and versions produce the same deterministic replay fingerprint.

## Adversarial tests

M2 explicitly tests:

- hindsight leakage;
- commit-authority leakage;
- evaluation-time authorization semantics;
- false historical UNKNOWN promotion;
- retrospective evidence without history rewrite;
- deterministic replay/version sensitivity;
- atomic batch behavior;
- forged/unknown policy hashes;
- world evidence without event authorization;
- late-arriving older world evidence;
- append-only corrections;
- PostgreSQL transaction rollback;
- concurrent monotonic ledger sequence allocation.
