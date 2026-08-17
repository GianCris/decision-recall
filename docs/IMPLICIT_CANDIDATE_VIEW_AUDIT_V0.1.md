# Implicit Candidate View Audit v0.1

Status: offline, contract-first, descriptive audit. This is not the Round B protocol and does not select or freeze a Round B relation vocabulary.

## 1. Inspected path

The runtime path is `dr_baselines.runner.run_baseline()` (B0) or `dr_baselines.mechanism_tournament.run_condition()` (M0), through `dr_bench.views.candidate_view(scenario, phase="discovery", condition="implicit")`. `dr_bench.catalog.load_scenarios()` loads `data/dev.jsonl`, attaches `data/interaction_chains.json` as `candidate.transmissions`, and calls `dr_bench.validation.validate_scenario()`. The machine scenario envelope is in `dr_bench/schema/scenario.schema.json`; nested validation is primarily procedural in `validation.py`.

`candidate_view()` deep-copies scenario identity, complexity, and the complete `scenario["candidate"]` object, adds `phase` and `discovery_condition`, then removes `evidence_available` and `assumptions` from every decision in implicit Discovery. It does not read `scenario["private"]` for Discovery.

## 2. Exact implicit-visible inventory

The frozen DEV instances expose these fields:

| Object | Visible fields | Classification |
|---|---|---|
| envelope | `schema_version`, `id`, `split`, `domain`, `title`, `phase`, `discovery_condition` | A |
| `complexity` | `agent_hops`, `semantic_distance`, `information_transformation`, `boundary` | A; the declared hop count is also B-derivable from the transmission predecessor chain |
| scenario context | `brief` | A free text |
| `agents[]` | `id`, `role` | A; role meaning is C |
| `knowledge_before[]` | `id`, `holder`, `statement`, `visibility[]` | A; holder/visibility references are explicit; statement meaning is C |
| `change` | `id`, `observed_by`, `statement` | A; observer reference is explicit; statement meaning and its relationship to prior knowledge are C |
| `transmissions[]` | `id`, `from_agent`, `to_agent`, `at`, `kind`, `predecessor`, `content` | A; endpoints, order value, kind string, and predecessor are explicit; content meaning is C |
| `decisions[]` | `id`, `agent_id`, `made_at`, `statement` | A; actor and order value are explicit; statement meaning is C |
| `world` | scenario-specific JSON properties and values | A; property names/values are visible but are not object IDs |
| `consequences[]` | `id`, `description`, `path`, `value` | A; description meaning is C |
| `recovery_actions[]` | `id`, `agent_id`, `description`, `cost`, `window_closes_at`, `effects[]` | A; actor/cost/window are explicit; description meaning is C |
| `effects[]` | `operation`, `path`, `value` | A; exact path equality is B; operational or decision relevance is C |

Classification: **A** explicitly present; **B** mechanically derivable without semantic judgment; **C** obtainable only through semantic inference; **D** private/not exposed.

The contract exposes numeric ordering fields for transmissions (`at`) and decisions (`made_at`), plus action windows. Numeric comparisons are B. It does not explicitly state that every cross-object comparison denotes causality, receipt, use, or dependence; those interpretations are C.

## 3. Reference namespaces

All IDs are scenario-local and must be interpreted with their object type; short values such as `c1`, `d1`, and `t1` are not globally unique.

| Namespace | Stable visible reference? | Explicit links |
|---|---:|---|
| scenario | yes: envelope `id` | none needed |
| agent/actor | yes: `agents[].id` | knowledge `holder`/`visibility`; change `observed_by`; transmission `from_agent`/`to_agent`; decision/action `agent_id` |
| prior knowledge/evidence | yes: `knowledge_before[].id` | holder and visibility only; no visible decision link |
| changed knowledge | yes: `change.id` | `observed_by` only; no explicit link to prior knowledge, transmission, or decision |
| decision | yes: `decisions[].id` | `agent_id` only |
| transmission/trace | yes: `transmissions[].id` | agent endpoints and optional transmission `predecessor` |
| generic event/message | messages are represented as transmissions; there is no separate event namespace | transmission structure above |
| consequence | yes: `consequences[].id` | a visible `path`; no explicit decision link |
| recovery action | yes: `recovery_actions[].id` | `agent_id` and effect paths; no explicit decision link |
| world location | path/property only, not an object ID | consequence/effect paths may equal a world path |

Decision IDs, knowledge IDs, transmission IDs, and the change ID are visible. Exact decision-to-knowledge references are not. The words in statements/content may suggest relationships, but those are free-text semantic evidence, not stable links.

## 4. Withheld or transformed categories

At the field/structure level, implicit construction:

- removes each decision's `evidence_available` list (the exact decision-to-knowledge references present in structured Discovery);
- removes each decision's structured `assumptions`;
- never copies the top-level `private` partition or its decision labels, dependency paths, downstream flags, hard-negative types, consequence labels, expected actions, or expected final world;
- does not add recovery-only `affected_decision_ids` during Discovery;
- leaves observable transmissions, roles, statements, ordering fields, world state, consequences, and recovery options visible.

This comparison establishes only withheld field categories. No private value was used to infer relation semantics.

## 5. Contract-supported relation candidates

These nine neutral structural candidates are technically supportable. They are findings, not an authorized vocabulary.

| Candidate description | Visible support | Observation | Stable endpoints | Mechanical validation | Judgment-leak risk |
|---|---|---|---:|---:|---|
| decision assigned to agent | `decisions[].agent_id` | mechanical | yes | yes | low if kept as authorship only |
| knowledge held by agent | `knowledge_before[].holder` | mechanical | yes | yes | low; does not imply use |
| knowledge visible to agent | `knowledge_before[].visibility[]` | mechanical | yes | yes | low; does not imply receipt or use |
| change observed by agent | `change.observed_by` | mechanical | yes | yes | low; does not imply propagation |
| transmission sent by agent | `transmissions[].from_agent` | mechanical | yes | yes | low |
| transmission addressed to agent | `transmissions[].to_agent` | mechanical | yes | yes | low; must not be renamed “used by” |
| transmission follows transmission | `transmissions[].predecessor` | mechanical | yes | yes, including chain/time constraints in the frozen validator | low if limited to represented chain order |
| recovery action assigned to agent | `recovery_actions[].agent_id` | mechanical | yes | yes | low; does not imply expected/correct action |
| action effect and consequence co-reference an exact path | `effects[].path == consequences[].path` | mechanically derived | action/consequence IDs are stable; path is the join key | yes for exact equality | moderate: equality says only shared world location, not that action is required or correct |

Numeric “earlier/later” comparisons are mechanically computable from `at`/`made_at`, but a cross-type transmission→decision relation is **not** accepted as structurally established: shared clocks and causal/use semantics are not asserted by an explicit link. Such comparisons may be recorded as visible attributes, not promoted to provenance.

Rejected as mechanically grounded Stage-1 relations:

- knowledge/evidence → decision: the only exact link (`evidence_available`) is removed; any link requires C-level interpretation of statements, actor visibility, transmissions, and order;
- change → prior knowledge: no explicit reference joins `change.id` to a knowledge ID; semantic contradiction/correction is C;
- transmission → knowledge or transmission → decision: no such reference is exposed; content similarity or temporal/actor alignment is C;
- decision → consequence/action/world outcome: no explicit decision reference exists; path and free-text correspondence are insufficient to establish decision lineage;
- any relation whose name asserts materiality, dependency strength, independence, support, necessity, sufficiency, survivability, reopening, alternative support, or an oracle answer: D or forbidden semantic judgment.

Therefore **no evidence→decision relation is mechanically observable in the frozen implicit view**. A model could propose one only through semantic inference, and a validator could validate its endpoints—not its semantic truth—from this contract.

## 6. DEV applicability (checked second)

The twelve implicit DEV views contain 36 decision IDs, 24 knowledge IDs, 12 change IDs, 34 agent IDs, 20 transmission IDs, 24 consequence IDs, and 24 action IDs. All nine structural candidates occur in DEV. Decision-agent, knowledge-holder/visibility, change-observer, and action-agent links occur in every scenario.

Transmission coverage varies: dev-005 and dev-012 contain no transmissions; dev-001/003/008/009 contain one; dev-002/004/007/011 contain two; dev-006/010 contain four. Predecessor links consequently occur only in scenarios with multi-item chains. In every DEV scenario, at least two action effect paths exactly match consequence paths; additional effects need not match a consequence path.

Every DEV decision retains only `id`, `agent_id`, `made_at`, and free-text `statement`. No DEV implicit decision has an exact knowledge, change, transmission, consequence, or action reference. Thus every evidence→decision, transmission→decision, change→knowledge, and decision→consequence proposal would require free-text/semantic interpretation. The two zero-transmission scenarios additionally provide no trace reference to use even as a semantic intermediary. No contract-supported candidate has zero DEV coverage, although transmission-chain candidates do not apply to all scenarios.

## 7. Future validation boundary

**Schema-invalid** can cover malformed JSON, missing/extra required fields, wrong container/scalar types, and—after external authorization—values outside a frozen relation allowlist. This audit does not define that schema or allowlist.

**Semantic-reference-invalid** can mechanically cover an endpoint absent from the corresponding visible namespace, an endpoint typed as the wrong visible object kind, or a structurally asserted link that contradicts an explicit visible field (for example, the wrong decision actor or a nonexistent transmission predecessor).

The three levels are:

1. **Reference existence:** mechanically verify that a typed scenario-local ID exists.
2. **Structural link:** mechanically compare a claimed link with an explicit field or exact path equality. Only the nine candidates above meet this boundary.
3. **Semantic truth:** decide whether free text means evidence was used, transformed, relied upon, contradicted, or affected a decision. The implicit contract cannot mechanically verify this level.

A syntactically valid proposed evidence→decision edge with existing endpoints could pass level 1 while remaining unverifiable at levels 2–3. No automatic repair, normalization, regeneration, or imputation is justified.

## 8. RC0-safe boundary

A future generic RC0 context record could safely organize the unchanged visible envelope and typed collections: scenario metadata; complexity declarations; brief; agent IDs/roles; prior-knowledge IDs/statements/holder/visibility; change ID/statement/observer; transmission IDs/content/kind/agent endpoints/predecessor/order; decision IDs/statements/actors/order; visible world values; consequence IDs/descriptions/paths/values; and recovery-action IDs/descriptions/actors/cost/windows/effects. It may preserve explicit ordering and reference fields or group items by an explicitly named agent.

RC0 must not add decision→knowledge/transmission/change/support mappings, semantic equivalence links, inferred causal chains, necessity/sufficiency judgments, or richer identifiers. Even when co-locating visible objects by actor or time, it must not label that organization as reliance or support.

## 9. Material limitations

- Nested candidate objects are procedurally validated but only loosely specified by the JSON Schema, so the frozen runtime/data shape—not a fully closed nested schema—is the operative inventory.
- IDs are stable only within a scenario and typed namespace; bare IDs can collide across object types.
- Numeric ordering is visible, but cross-object causal meaning is not structurally encoded.
- Knowledge statements, change statements, message content, decision statements, roles, and descriptions require semantic interpretation.
- The implicit view deliberately removes the sole exact decision→knowledge mapping and structured assumptions.
- DEV coverage establishes applicability only; it does not authorize a vocabulary or establish generalization.
- The final Round B relation vocabulary remains externally undecided.
