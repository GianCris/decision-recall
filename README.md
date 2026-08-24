# Decision Recall

**A temporal epistemic control layer for long-running AI decisions.**

Agents can remember what was decided. Decision Recall determines when recorded reasoning is no longer safe to reuse as the world changes—without rewriting history, inventing missing rationale, or turning uncertainty into a negative fact.

This branch contains the deterministic Decision Recall core plus the earlier DR-Bench research harness.

## Current product checkpoint

- M1 / M2 / M2.1: frozen
- Product Checkpoint 1: frozen
- Product Checkpoint 2 (Gemini compiler boundary + credentialed live 9/9): frozen
- Visible Winner Slice: active
- Target hackathon category: **Collaborative Partner**

Judge-comprehension contract:

```text
docs/VWS_0_JUDGE_COMPREHENSION_CONTRACT.md
```

Static VWS-0.5 prototype for cold-viewer testing:

```text
prototypes/vws-05/index.html
```

The prototype is explicitly not the hackathon Proof-of-Action demo. The final submission path must execute live, run the backend on Google Cloud infrastructure (minimum target: Cloud Run), and show Google Cloud deployment evidence in the continuous demo video.

## Core architecture

```text
raw language / tool output
        ↓
probabilistic candidate extraction
        ↓
evidence + policy authorization
        ↓
canonical typed state
══════════════════════════════════
DETERMINISTIC DECISION RECALL CORE
══════════════════════════════════
        ↓
current-world match
revisit evaluation
target-scoped safe-reuse evaluation
        ↓
guarded epistemic result
```

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
