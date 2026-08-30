# VWS-1 Decision Threads — Temporal Observatory Visual Contract

## Status

- Decision Threads: **visual metaphor frozen** unless a concrete semantic or judge-comprehension blocker appears.
- Temporal Observatory: **approved primary art direction**.
- Visual Pass 3 is a blocker-removal pass, not a new design exploration.
- This contract governs the judge-facing winner slice only. It does not reopen M1/M2/M2.1/PC1/PC2 semantics.

## Product truth

The visual layer is a projection of the frozen engine. It must never compute or invent authority, epistemic state, current-world match, reuse result, limiting requirement, or boundary.

Authoritative flow:

```text
Frozen engine
  -> Presentation DTO
  -> Decision Threads visual state
  -> React + Motion + SVG/CSS
```

Hosted truth path:

```text
Cloud Run /api/presentation
  -> preferred live deterministic engine state

if unavailable:
/demo-state.json
  -> explicit deterministic fallback
```

The source must be visible and honest. A live Cloud Run response may be labeled `Cloud Run · live engine`; build-time fallback must be labeled `deterministic fallback`.

## Visual metaphor

A decision is shown as a persistent temporal graph.

- **Instrument node** = source/world condition, recorded decision, current evaluation signal, or reuse destination.
- **Solid historical thread** = established/authorized historical relation.
- **Muted historical thread** = history remains established after time advances.
- **Dashed directional current trace** = current-world evaluation. It must be visibly different from historical authority.
- **Red current trace** = current mismatch.
- **Amber missing trace** = required relation not established.
- **?** = exact epistemic boundary.
- **Pulse** = one event-driven justified traversal. Pulses must never loop continuously as decoration.
- **Unsupported segment not rendered** = the system has no authority to continue.

Raw backend enum values such as `does_not_match` and `matches` belong in Proof/debug. Main-surface labels must be human language such as `NO LONGER MATCHES` and `STILL MATCHES`.

## Spatial rule

The application is one persistent observatory, not five slides and not three north-star panels. Apex, Beacon and D-104 preserve spatial continuity while state changes around them.

The canvas owns most of the attention. Explanatory copy is contextual support, not the primary narrator, and it must never obscure a persistent entity.

Three semantic planes must remain perceptible:

```text
OBSERVED WORLD
DECISION MEMORY
CURRENT WORLD
```

These are semantic layers, not generic dashboard columns.

## Discovery rule

The application must not reveal the answer to its own inspection before the user asks it to inspect.

Phase 0 may show the original decision, observable supplier facts, and already-established historical structure. It must **not** show the R2 `?`, `missing dependency`, or prospective human question.

Only after `Inspect decision` may the missing historical relation become visible.

## Motion grammar

Motion must encode product meaning and must be perceptible at ordinary demo speed.

### Detect

1. The user asks Decision Recall to inspect the decision.
2. A justified traversal reaches the already-established Apex path.
3. A Beacon traversal follows the available evidence.
4. The missing historical edge is revealed.
5. The pulse reaches `?` and stops.
6. Motion quiets.
7. The contextual human question appears at that gap.

### Ask -> mutate durable state

1. Human answers YES.
2. `?` resolves.
3. The historical edge draws into the persistent graph.
4. Exactly one pulse traverses the newly established edge.
5. The graph remains changed for later phases.

This mutation must be visually obvious because it is central to the Collaborative Partner story: the agent is not merely reading; durable decision state changes from human feedback.

### Then -> now

1. Time advances without replacing the historical graph.
2. Historical edges become quieter but remain present.
3. Current evidence appears through dashed/directional evaluation traces.
4. Apex current instability mismatches.
5. Beacon restart-delay current evidence matches.

Historical role and current-world match must never look like the same relation type even under video compression.

### Reuse stop — signature moment

1. A reuse traversal begins only over justified state.
2. It reaches the required sufficiency relation.
3. The pulse stops at `?`.
4. The unsupported edge remains physically undrawn / visibly unavailable.
5. Hold a short visual silence before explanation.
6. Keep the `?` and unreachable reuse destination visible.
7. Only then reveal `I CAN'T ESTABLISH THAT` **without covering the gap**.

The desired reaction is: **"I saw the reasoning physically stop at the exact relation it was not authorized to invent."**

## Hero copy

The mechanism leads; text explains after the mechanism.

Preferred final explanation:

```text
I CAN'T ESTABLISH THAT

Beacon mattered to the original decision.
What was never established: was that reason sufficient on its own?
```

Use engine-derived `insufficient_evidence` as status language. Do not claim an external block/action the engine does not model.

## Proof UI

Hashes, source mode, C1 identifiers, Gemini/compiler details and replay evidence belong in a secondary `Why / Proof` layer. They must not compete with the hero canvas.

The drawer may expose the raw engine state. The main surface should not.

## Prohibited visual shortcuts

Do not add:

- generic SaaS sidebars or card walls;
- constant decorative particles/pulses;
- random glassmorphism;
- neural-network imagery unrelated to actual semantics;
- 3D/Rive purely for spectacle;
- dead controls;
- a literal three-panel reproduction of the north-star concept art;
- copy overlays that hide Apex/Beacon/D-104 or the final sufficiency gap;
- a pre-revealed R2 gap before inspection.

Every important effect must answer: **what property of Decision Recall does this teach the judge?**

## Visual Pass 3 acceptance targets

1. Phase 0 contains no pre-revealed R2 `?`.
2. Apex/Beacon/D-104 remain visible and spatially persistent.
3. Inspect produces a clearly perceptible traversal and reveal.
4. Human YES visibly mutates durable state.
5. Historical and current evaluation grammars are unmistakably different.
6. Raw enum strings do not appear on the hero surface.
7. Question card and CTA never overlap.
8. Final reuse pulse reaches the sufficiency gap and visibly stops.
9. Final hero appears only after the stop and leaves the gap/reuse destination visible.
10. Hosted UI truthfully distinguishes live Cloud Run engine state from deterministic fallback.
11. No overflow or camera-visible unfinished chrome.

## Local run

From `apps/decision-threads`:

```bash
npm install
npm run dev
```

`npm run dev` still generates `public/demo-state.json` as the deterministic fallback before starting Vite. In the hosted Cloud Run experience, the frontend prefers `/api/presentation` and uses that file only if the runtime request fails.
