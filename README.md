# Decision Recall

**A temporal epistemic control layer for long-running AI decisions.**

Agents can remember what was decided. Decision Recall determines when recorded reasoning is no longer safe to reuse as the world changes—without rewriting history, inventing missing rationale, or turning uncertainty into a negative fact.

This branch contains the deterministic Decision Recall core plus the earlier DR-Bench research harness.

## Current product checkpoint

- M1 / M2 / M2.1: frozen
- Product Checkpoint 1: frozen
- Product Checkpoint 2 (Gemini compiler boundary + credentialed live 9/9): frozen
- Visible Winner Slice: **VWS-0.5 FAILED; VWS-0.6 narrative-simplification gate active**
- Target hackathon category: **Collaborative Partner**

Current comprehension contract:

```text
docs/VWS_0_6_NARRATIVE_SIMPLIFICATION.md
```

Current bilingual VWS-0.6 prototype:

```text
prototypes/vws-06/index.html
```

Previous failed VWS-0.5 prototype is preserved for evidence/history:

```text
prototypes/vws-05/index.html
```

VWS-0.6 exists only to test whether a zero-context viewer can understand the mechanism before production frontend investment. It is explicitly **not** the hackathon Proof-of-Action demo.

The narrative now separates:
- what mattered to the original decision;
- what matches the current world;
- the exact relation that was never established.

The same prototype supports Spanish and English copy from one semantic source. Spanish is used first to remove the language barrier from concept testing; English is tested afterward with English-capable viewers.

Before submission, the real judge-facing backend must be hosted on explicit Google Cloud infrastructure (minimum target: Cloud Run), the repository must include architecture/spin-up documentation, and the submitted video must show a continuous unedited live execution plus visible Google Cloud deployment proof.

## Architecture

![Decision Recall architecture](docs/architecture/decision-recall-architecture.svg)

Decision Recall separates probabilistic evidence interpretation from deterministic authority. Gemini produces bounded candidate evidence; the Decision Recall core controls identity, provenance, temporal authority, gap selection, evaluation, replay, and epistemic boundaries.

Human knowledge enters only through a server-verified capture gate when the system reaches a relation it cannot legitimately infer. Historical roles remain recorded while current-world applicability is reevaluated separately. If a required reuse relation was never established, the system stops with insufficient evidence rather than inventing a completion.

The deterministic core deliberately separates:

- fact/claim from historical role;
- `RelationSlot` (worth checking) from `RelationCandidate` (evidence-derived claim);
- historical role from current-world match;
- revisit trigger from current-world applicability;
- `T0_UNRESOLVED` from missing or currently-undetermined history;
- raw evidence from policy authorization.

Invalid epistemic transitions are rejected by guarded domain functions rather than left to prompt instructions.

## Milestone 1.1 — Core Semantic Hardening

The current golden scenario is supplier resilience (`D-104`). A sparse world event updates Apex reliability while the existing Beacon recovery state remains available in the canonical world state. The target then evaluates whether the recorded rationale is safe to reuse for the configured purpose.

Run the core suite:

```bash
python -m unittest discover -s tests -p 'test_decision_recall_milestone1.py' -v
```

## DR-Bench research harness

DR-Bench v0.1 remains a mechanism-agnostic benchmark for Material Decision Dependence, selective reevaluation, and minimum-disruption recovery. Its frozen dataset contains 16 deterministic scenarios: 12 development and 4 holdout.

The benchmark is intentionally kept separate from the Decision Recall mechanism. The public API `candidate_view(scenario, phase)` is the only supported way to hand scenario input to a candidate; raw loaded records contain a private oracle and must remain inside the benchmark harness.

Useful commands:

```powershell
python -m dr_bench list
python -m dr_bench show dev-001 --phase discovery --condition implicit
python -m dr_bench show dev-001 --phase discovery --condition structured
python -m dr_bench show dev-001 --phase recovery
python -m dr_bench evaluate dev-001 candidate.json --phase discovery
```

See `docs/SCHEMA.md` for the DR-Bench experimental contract.
